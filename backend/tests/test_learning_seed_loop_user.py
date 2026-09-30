"""PKG-13: the rich seed carries the two loop users (staff/QA toggle, build phase;
spec §13 A14) — prerequisite chains, shared encrypted check items (A2, A34)
drafted from an indexed, shared course-material document (A23), and the capped
user's spend and due flashcard (A26). Hermetic — `db.seed_helpers.table` and the
seed's own `table` are replaced by a recorder; nothing reaches PostgREST."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import config
from db import seed_helpers
from db import seed_local_rich as seed
from learning.checks import is_servable, posttest_reserve_hash
from learning.params import (
    CHECK_ITEM_DIFFICULTIES,
    CHECK_ITEM_MIN_RUBRIC,
    CHECK_ITEM_MIN_WRONG,
    EDGE_PREREQ_SOURCE_IS_PREREQ,
    PROBE_ITEMS_PER_SKILL_MIN,
)
from services import chunk_visibility, rag_service
from services.check_item_service import _row_to_item
from services.encryption import decrypt_if_present
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


def test_prerequisite_chain(recorder):
    for uid in seed.LOOP_USERS:
        nodes = [r for r in recorder.rows["graph_nodes"] if r["user_id"] == uid]
        assert len(nodes) == seed.SEED_LOOP_CONCEPTS == len(seed.LOOP_NODES)
        assert all(r["course_id"] == seed.COURSE_CS for r in nodes)
        assert all(r["mastery_score"] == 0.0 and r["mastery_tier"] == "unexplored" for r in nodes)
        edges = [r for r in recorder.rows["graph_edges"] if r["user_id"] == uid]
        assert len(edges) == seed.SEED_LOOP_CONCEPTS - 1
        assert all(r["relationship_type"] == "prerequisite" for r in edges)
        # oriented by EDGE_PREREQ_SOURCE_IS_PREREQ: the chain's earlier concept is the prerequisite
        order = [seed.loop_node_id(uid, slug) for slug, _, _ in seed.LOOP_NODES]
        for pre, dep in zip(order, order[1:]):
            expected = (pre, dep) if EDGE_PREREQ_SOURCE_IS_PREREQ else (dep, pre)
            assert any((e["source_node_id"], e["target_node_id"]) == expected for e in edges)
    # Same concept names for both users → the same concept keys → shared items (A2).
    names = {
        uid: sorted(r["concept_name"] for r in recorder.rows["graph_nodes"] if r["user_id"] == uid)
        for uid in seed.LOOP_USERS
    }
    assert names[seed.USER_LOOP] == names[seed.USER_CAPPED]


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
        plain = decrypt_if_present(r["prompt"])
        assert plain != r["prompt"], "prompt stored in plaintext"
        assert plain.startswith(E2E_LOOP_PROBE_PROMPT)
        for col in ("reference_answer", "final_answer", "rubric_json", "common_wrong_json"):
            assert decrypt_if_present(r[col]) != r[col], f"{col} stored in plaintext"
        assert decrypt_if_present(r["reference_answer"]) == E2E_LOOP_REFERENCE
        assert decrypt_if_present(r["final_answer"]) == E2E_LOOP_FINAL_ANSWER  # A34
        # the E2E grader grades on the token anywhere in its message (prompt + reference)
        assert E2E_GRADER_CORRECT_TOKEN not in plain + E2E_LOOP_REFERENCE
        assert len(json.loads(decrypt_if_present(r["rubric_json"]))) >= CHECK_ITEM_MIN_RUBRIC
        assert len(json.loads(decrypt_if_present(r["common_wrong_json"]))) >= CHECK_ITEM_MIN_WRONG
        assert r["graded"] is False
        assert len(r["question_hash"]) == 64
    assert len({(r["course_id"], r["concept_key"], r["question_hash"]) for r in items}) == len(
        items
    )


def test_seeded_items_hydrate_and_leave_the_probe_enough_after_the_reserve(recorder):
    """Through the REAL decrypt boundary: every item is servable (A34), and each
    concept keeps at least PROBE_ITEMS_PER_SKILL_MIN + 1 servable items once the
    post-test reserve is set aside (A23: the probe never serves it)."""
    by_key: dict[str, list] = {}
    for row in recorder.rows["check_items"]:
        item = _row_to_item(row)
        assert is_servable(item), row["id"]
        by_key.setdefault(item.concept_key, []).append(item)
    for key, items in by_key.items():
        reserve = posttest_reserve_hash(items)
        assert reserve is not None
        rest = [i for i in items if i.question_hash != reserve]
        assert len(rest) >= PROBE_ITEMS_PER_SKILL_MIN + 1, key


def test_items_are_drafted_from_an_indexed_shared_course_document(recorder, monkeypatch):
    """A23: items come only from shared course material. The seeded document is
    course_material above MIN_SHARE_CONFIDENCE, indexed, and its uploader
    consents — so decide_visibility says shared, and every chunk is the shared,
    content-addressed, encrypted, embedded row the indexer would write."""
    (doc,) = recorder.rows["documents"]
    assert doc["id"] == seed.LOOP_DOC_ID and doc["user_id"] == seed.USER_LOOP
    assert doc["offering_id"] == seed.OFF_CS_S26
    assert doc["index_status"] == "indexed"
    settings = {r["user_id"]: r for r in recorder.rows["user_settings"]}
    monkeypatch.setattr(
        chunk_visibility,
        "shares_class_context",
        lambda uid: settings[uid]["share_class_context"],
    )
    assert (
        chunk_visibility.decide_visibility(
            doc["user_id"],
            shareability=doc["shareability"],
            confidence=doc["shareability_confidence"],
        )
        == chunk_visibility.SHARED
    )
    for col in ("summary", "concept_notes", "extracted_text"):
        assert decrypt_if_present(doc[col]) != doc[col], f"documents.{col} in plaintext"

    chunks = recorder.rows["course_chunks"]
    assert len(chunks) == seed.SEED_LOOP_CONCEPTS == doc["index_chunk_count"]
    for c in chunks:
        plain = decrypt_if_present(c["chunk_text"])
        assert plain != c["chunk_text"], "chunk_text stored in plaintext"
        # ids hash the PLAINTEXT (encryption after hashing, ADR 0025)
        assert c["id"] == c["chunk_hash"] == rag_service.chunk_id(seed.COURSE_CS_CODE, plain)
        assert c["course_id"] == seed.COURSE_CS_CODE and c["doc_id"] == doc["id"]
        assert c["visibility"] == chunk_visibility.SHARED and c["category"] == doc["category"]
        assert c["uploader_id"] == doc["user_id"]
        assert len(c["embedding"]) == rag_service._OUTPUT_DIM
        assert abs(sum(v * v for v in c["embedding"]) - 1.0) < 1e-9  # unit-normalised
    contributors = recorder.rows["course_chunk_contributors"]
    assert {(r["chunk_id"], r["user_id"]) for r in contributors} == {
        (c["id"], doc["user_id"]) for c in chunks
    }
    chunk_ids = {c["id"] for c in chunks}
    for item in recorder.rows["check_items"]:
        assert item["source_document_ids"] == [doc["id"]] and item["document_id"] == doc["id"]
        assert item["source_chunk_ids"] and set(item["source_chunk_ids"]) <= chunk_ids


def test_capped_user_spend_is_past_the_novice_allowance(recorder):
    rows = recorder.rows["llm_usage"]
    assert rows and all(r["user_id"] == seed.USER_CAPPED for r in rows)
    allowance = config.STUDENT_DAILY_BUDGET_USD * config.BUDGET_NOVICE_MULTIPLIER
    assert sum(float(r["cost_usd"]) for r in rows) > allowance  # hard level in every band
    assert len(rows) < config.LEARN_RATE_LIMIT_PER_MIN  # the $ cap, not the rate limit
    assert all(r["task"] not in ("grader", "grader_second", "decision") for r in rows)
    # stamped NOW on every run (an upsert): a stack seeded once stays capped past
    # UTC midnight only through a re-seed, never on a stale timestamp
    for r in rows:
        at = datetime.fromisoformat(r["created_at"])
        assert abs((datetime.now(timezone.utc) - at).total_seconds()) < 60


def test_capped_spend_is_refreshed_by_a_reseed_not_skipped(recorder):
    import inspect

    src = inspect.getsource(seed.seed_learning_loop)
    usage = src[src.index('"llm_usage"') - 40 : src.index('"llm_usage"')]
    assert "h.upsert(" in usage and "insert_if_absent" not in usage


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
    assert decrypt_if_present(cards[0]["front"]) != cards[0]["front"]  # 🔒 front/back (#518)
    assert decrypt_if_present(cards[0]["back"]) != cards[0]["back"]
    assert cards[0]["due_at"] < datetime.now(timezone.utc).isoformat()


def test_no_learner_state_seeded(recorder):
    assert "learner_state" not in recorder.rows


def test_main_runs_the_loop_step_and_summarises_its_tables():
    import inspect

    src = inspect.getsource(seed.main)
    assert src.index("seed_sessions()") < src.index("seed_learning_loop()")
    for name in (
        "user_settings",
        "check_items",
        "llm_usage",
        "course_chunks",
        "course_chunk_contributors",
    ):
        assert name in seed._SUMMARY_ORDER, name


def test_the_loop_step_writes_through_the_seed_helpers_and_reads_no_chunk_back():
    """inv 29 sanctions db/seed_local_rich.py as a source_chunk_ids WRITER only:
    the loop step goes through db/seed_helpers and never selects a row itself."""
    import inspect

    src = inspect.getsource(seed.seed_learning_loop)
    assert ".select(" not in src and "table(" not in src
