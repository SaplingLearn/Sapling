"""PKG-13: the rich seed carries the two loop users (staff/QA toggle, build phase;
spec §13 A14) — shared encrypted check items (A2, A34) and the capped user's
spend and due flashcard (A26). The seeded rows' ciphertext is the E2E
`ciphertext` oracle's to judge on the booted stack. Hermetic — `db.seed_helpers.table` and the
seed's own `table` are replaced by a recorder; nothing reaches PostgREST."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import config
from db import seed_helpers
from db import seed_local_rich as seed
from learning.params import (
    CHECK_ITEM_DIFFICULTIES,
    CHECK_ITEM_MIN_RUBRIC,
    CHECK_ITEM_MIN_WRONG,
)
from services.encryption import bind, decrypt_if_present
from services.graph_service import _normalize_concept


class _Recorder:
    def __init__(self):
        self.rows: dict[str, list[dict]] = {}

    def __call__(self, name):
        rec = self

        class _T:
            def select(self, cols, filters=None, limit=None, **kw):
                return []

            def upsert(self, row, on_conflict=None):
                rec.rows.setdefault(name, []).append(row)

            def insert(self, row):
                rec.rows.setdefault(name, []).append(row)

        return _T()


@pytest.fixture
def recorder(monkeypatch):
    r = _Recorder()
    monkeypatch.setattr(seed_helpers, "table", r)
    monkeypatch.setattr(seed, "table", r)
    monkeypatch.setattr(seed, "_admin_role_id", lambda: None)  # the recorder has no roles table
    seed_helpers.reset_counts()
    seed.seed_users()  # the loop users' `users` rows come from _USERS
    seed.seed_enrollments()  # … and their enrollments from _ENROLLMENTS
    seed.seed_learning_loop()
    return r


def test_loop_users_carry_the_staff_toggle_and_are_enrolled(recorder):
    assert seed.LOOP_USERS == (seed.USER_LOOP, seed.USER_CAPPED)
    for uid in seed.LOOP_USERS:
        settings = [r for r in recorder.rows["user_settings"] if r["user_id"] == uid]
        assert settings and settings[0]["learning_loop_beta"] is True
        users = [r for r in recorder.rows["users"] if r["id"] == uid]
        assert users and users[0]["is_approved"] and users[0]["onboarding_completed"]
        enrolled = [r for r in recorder.rows["enrollments"] if r["user_id"] == uid]
        assert [r["offering_id"] for r in enrolled] == [seed.OFF_CS_S26]


def test_check_items_are_shared_course_assets_encrypted_and_hashed(recorder):
    from agents.function_handlers_e2e import (
        E2E_GRADER_CORRECT_TOKEN,
        E2E_LOOP_FINAL_ANSWER,
        E2E_LOOP_PROBE_PROMPT,
        E2E_LOOP_REFERENCE,
    )

    items = recorder.rows["check_items"]
    assert seed.SEED_LOOP_ITEMS_PER_CONCEPT == len(seed.SEED_LOOP_FORMATS) * len(
        CHECK_ITEM_DIFFICULTIES
    )
    assert (
        len(items) == seed.SEED_LOOP_CONCEPTS * seed.SEED_LOOP_ITEMS_PER_CONCEPT
    )  # once, not per user
    assert {r["format"] for r in items} == set(seed.SEED_LOOP_FORMATS)
    assert sorted({r["difficulty"] for r in items}) == sorted(CHECK_ITEM_DIFFICULTIES)
    keys = {_normalize_concept(name) for _, name, _ in seed.LOOP_NODES}
    assert {r["concept_key"] for r in items} == keys
    for r in items:
        assert "node_id" not in r and r["course_id"] == seed.COURSE_CS  # A2
        plain = decrypt_if_present(r["prompt"], bind=bind("check_items", "prompt", r))
        assert plain != r["prompt"], "prompt stored in plaintext"
        assert plain.startswith(E2E_LOOP_PROBE_PROMPT)
        for col in ("reference_answer", "final_answer", "rubric_json", "common_wrong_json"):
            assert decrypt_if_present(r[col], bind=bind("check_items", col, r)) != r[col], (
                f"{col} stored in plaintext"
            )
        assert decrypt_if_present(r["reference_answer"], bind=bind("check_items", "reference_answer", r)) == E2E_LOOP_REFERENCE
        assert decrypt_if_present(r["final_answer"], bind=bind("check_items", "final_answer", r)) == E2E_LOOP_FINAL_ANSWER  # A34
        # the E2E grader grades on the token anywhere in its message (prompt + reference)
        assert E2E_GRADER_CORRECT_TOKEN not in plain + E2E_LOOP_REFERENCE
        assert len(json.loads(decrypt_if_present(r["rubric_json"], bind=bind("check_items", "rubric_json", r)))) >= CHECK_ITEM_MIN_RUBRIC
        assert len(json.loads(decrypt_if_present(r["common_wrong_json"], bind=bind("check_items", "common_wrong_json", r)))) >= CHECK_ITEM_MIN_WRONG
        assert r["graded"] is False
        assert len(r["question_hash"]) == 64
    assert len({(r["course_id"], r["concept_key"], r["question_hash"]) for r in items}) == len(
        items
    )


def test_capped_user_spend_is_past_the_novice_allowance(recorder):
    rows = recorder.rows["llm_usage"]
    assert rows and all(r["user_id"] == seed.USER_CAPPED for r in rows)
    allowance = config.STUDENT_DAILY_BUDGET_USD * config.BUDGET_NOVICE_MULTIPLIER
    assert sum(float(r["cost_usd"]) for r in rows) > allowance  # hard level in every band
    assert len(rows) < config.LEARN_RATE_LIMIT_PER_MIN  # the $ cap, not the rate limit
    assert all(r["task"] not in ("grader", "grader_second", "learning_decision") for r in rows)
    # stamped NOW on every run (an upsert): a stack seeded once stays capped past
    # UTC midnight only through a re-seed, never on a stale timestamp
    for r in rows:
        at = datetime.fromisoformat(r["created_at"])
        assert abs((datetime.now(timezone.utc) - at).total_seconds()) < 60


def test_the_loop_seed_imports_no_model_sdk():
    """The seed runs in a fresh process before every Playwright test; importing
    the handler module or rag_service (pydantic-ai + google-genai) cost ~2.4 s a
    test (PKG-13 fix round). Run the loop step's imports in a clean interpreter."""
    import subprocess
    import sys

    probe = (
        "import sys, inspect, ast\n"
        "import db.seed_local_rich as s\n"
        "tree = ast.parse(inspect.getsource(s.seed_learning_loop))\n"
        "tree2 = ast.parse(inspect.getsource(s._seed_embedding))\n"
        "for t in (tree, tree2):\n"
        "    for n in ast.walk(t):\n"
        "        if isinstance(n, ast.ImportFrom): __import__(n.module)\n"
        "        elif isinstance(n, ast.Import): [__import__(a.name) for a in n.names]\n"
        "print('pydantic_ai' in sys.modules, 'google.genai' in sys.modules)\n"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["False", "False"], out.stderr


def test_capped_user_has_one_due_flashcard(recorder):
    cards = recorder.rows["flashcards"]
    assert len(cards) == 1 and cards[0]["user_id"] == seed.USER_CAPPED
    assert cards[0]["offering_id"] == seed.OFF_CS_S26
    assert decrypt_if_present(cards[0]["front"], bind=bind("flashcards", "front", cards[0])) not in (None, cards[0]["front"])  # 🔒 front/back (#518)
    assert decrypt_if_present(cards[0]["back"], bind=bind("flashcards", "back", cards[0])) not in (None, cards[0]["back"])
    assert cards[0]["due_at"] < datetime.now(timezone.utc).isoformat()


def test_no_learner_state_seeded(recorder):
    assert "learner_state" not in recorder.rows


def test_the_loop_step_writes_through_the_seed_helpers_and_reads_no_chunk_back():
    """inv 29 sanctions db/seed_local_rich.py as a source_chunk_ids WRITER only:
    the loop step goes through db/seed_helpers and never selects a row itself."""
    import inspect

    src = inspect.getsource(seed.seed_learning_loop)
    assert ".select(" not in src and "table(" not in src
