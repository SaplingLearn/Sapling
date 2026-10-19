"""Optional browser assets: canonical encryption, fresh shape, no fake evidence."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from db import seed_learning_goal_journey as fixture
from db.e2e_handler_constants import read_constants
from learning import misconceptions, planner, probe
from learning.checks import posttest_reserve_hash, question_hash, select_item
from learning.params import BKT_PROFICIENT, PROBE_SESSION_CAP
from services.check_item_service import _row_to_item
from services.encryption import decrypt_if_present, encrypt_if_present, encrypt_json


@pytest.fixture
def assets(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    final, prompt, reference = read_constants(
        "E2E_LOOP_FINAL_ANSWER", "E2E_LOOP_PROBE_PROMPT", "E2E_LOOP_REFERENCE"
    )
    templates = {}
    for slug in fixture.SLUGS:
        for difficulty in fixture.DIAGNOSTIC_COUNTS:
            templates[f"rich-check-{slug}-free-d{difficulty}"] = {
                "id": f"rich-check-{slug}-free-d{difficulty}",
                "course_id": fixture.COURSE_CS,
                "concept_key": slug,
                "document_id": "reviewed-course-document",
                "format": "free",
                "difficulty": difficulty,
                "prompt": encrypt_if_present(f"{prompt} [{slug}, free, difficulty {difficulty}]"),
                "reference_answer": encrypt_if_present(reference),
                "final_answer": encrypt_if_present(final),
                "rubric_json": encrypt_json(
                    [{"id": "r1", "text": "States the seeded final answer."}]
                ),
                "common_wrong_json": encrypt_json(
                    [{"key": "wrong", "text": "Gives a different answer."}]
                ),
                "source_chunk_ids": [f"course-chunk-{slug}"],
                "source_document_ids": ["reviewed-course-document"],
                "question_hash": "replaced",
                "graded": False,
            }
    sessions, writes, deletes, reads = [], [], [], []

    class Table:
        def __init__(self, name):
            self.name = name

        def select(self, *_args, filters=None, **_kwargs):
            reads.append((self.name, filters))
            if self.name == "node_mastery_events":
                # Actual migration schema has node_id and no user_id column.
                assert set(filters) == {"node_id"}
            if self.name == "sessions":
                return sessions
            return []

        def delete(self, filters):
            deletes.append((self.name, filters))

    monkeypatch.setattr(fixture, "table", Table)
    monkeypatch.setattr(fixture, "_template", lambda item_id: templates[item_id])
    monkeypatch.setattr(fixture.h, "upsert", lambda name, row, **_kw: writes.append((name, row)))
    return SimpleNamespace(
        templates=templates, sessions=sessions, writes=writes, deletes=deletes, reads=reads
    )


def _items(assets):
    return [_row_to_item(row) for name, row in assets.writes if name == "check_items"]


def test_diagnostic_assets_only_seed_priors_not_observations(assets):
    fixture.seed_goal_continuation_items("diagnostic")
    assert (
        "node_mastery_events",
        {"node_id": "in.(rich-node-loop-binary,rich-node-loop-bitwise)"},
    ) in assets.reads
    assert {name for name, _row in assets.writes} == {"check_items", "learner_state"}
    priors = [row for name, row in assets.writes if name == "learner_state"]
    assert len(priors) == 2
    assert all(row["p_known"] == fixture.INITIAL_PRIOR for row in priors)
    assert all(set(row) == {"user_id", "node_id", "p_known"} for row in priors)
    assert len(assets.deletes) == 2
    items = _items(assets)
    assert len(items) == sum(fixture.DIAGNOSTIC_COUNTS.values()) * len(fixture.SLUGS)
    assert {item.format for item in items} == {"free"}
    assert len({item.question_hash for item in items}) == len(items)
    for name, row in assets.writes:
        if name != "check_items":
            continue
        plaintext = decrypt_if_present(row["prompt"])
        assert row["prompt"] != plaintext
        assert row["question_hash"] == question_hash(plaintext)
        assert row["document_id"] == "reviewed-course-document"
        assert row["source_chunk_ids"] == [f"course-chunk-{row['concept_key']}"]


@pytest.mark.parametrize(
    "url", ["https://prod.example", "http://127.0.0.1.evil.test", "http://evil.test/localhost"]
)
def test_fixture_refuses_remote_even_if_local_appears_in_url(assets, monkeypatch, url):
    monkeypatch.setenv("SUPABASE_URL", url)
    with pytest.raises(RuntimeError, match="loopback"):
        fixture.seed_goal_continuation_items("diagnostic")
    assert not assets.writes and not assets.deletes


def test_diagnostic_cannot_reset_assets_after_session_started(assets):
    assets.sessions.append({"id": "already-started"})
    with pytest.raises(RuntimeError, match="precede"):
        fixture.seed_goal_continuation_items("diagnostic")
    assert not assets.writes and not assets.deletes


def test_practice_requires_real_plan_and_never_writes_learner_state(assets):
    with pytest.raises(RuntimeError, match="real"):
        fixture.seed_goal_continuation_items("practice")
    for slug in fixture.SLUGS:
        assets.templates[f"rich-goal-{slug}-diagnostic-free-d3-0"] = assets.templates[
            f"rich-check-{slug}-free-d3"
        ]
    assets.sessions.append({"id": "s", "loop_state": {"phase": "plan", "goal": {"version": 1}}})
    fixture.seed_goal_continuation_items("practice")
    assert not assets.deletes
    assert {name for name, _row in assets.writes} == {"check_items"}
    assert len(assets.writes) == 4
    assert {(item.format, item.difficulty) for item in _items(assets)} == {
        ("free", 3),
        ("teachback", 3),
    }


def test_fixture_bank_allows_real_release_policy_then_fresh_alternate_shape(assets, monkeypatch):
    """Policy rehearsal, not model/browser evidence; no unaided flags are forged.

    Use the real adaptive selector + release/recheck policy with a supplied
    journal. The actual browser journey must separately earn all these grades.
    """
    fixture.seed_goal_continuation_items("diagnostic")
    bank = [item for item in _items(assets) if item.concept_key == "binary"]
    reserve = posttest_reserve_hash(bank)
    practice_reserve = max(item.question_hash for item in bank if item.question_hash != reserve)
    eligible = [
        SimpleNamespace(**item.model_dump(), node_id="A")
        for item in bank
        if item.question_hash not in {reserve, practice_reserve}
    ]
    journal, history = [], []
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(misconceptions, "recent_evidence", lambda *_a, **_kw: list(journal))

    def observe(item, correct):
        recheck = misconceptions.recheck_after_release("u", "A", {}, now=now, item=item)
        history.append(
            {
                "node_id": "A",
                "question_hash": item.question_hash,
                "difficulty": item.difficulty,
                "channel": "teachback_llm" if item.format == "teachback" else "free_response",
                "correct": correct,
                "idk": False,
                "independent": not recheck,
                "same_session_recheck": recheck,
                "p_after": fixture.INITIAL_PRIOR,
            }
        )
        journal.append(
            {
                "question_hash": item.question_hash,
                "released": not correct,
                "shape": (item.format, item.difficulty),
            }
        )
        return recheck

    while len(history) < PROBE_SESSION_CAP:
        item = probe.next_probe_item(
            {"A": fixture.INITIAL_PRIOR},
            eligible,
            [],
            channel_for_format={"free": "free_response"},
            history=history,
        )
        if item is None:
            break
        observe(item, correct=not (len(history) == 0 and item.difficulty == 3))
    summary = probe.diagnostic_summary(history, skills=["A"])["skills"][0]
    assert summary["status"] == "bracketed"
    assert (summary["floor_difficulty"], summary["ceiling_difficulty"]) == (2, 3)
    assert planner.planning_states({"A": fixture.INITIAL_PRIOR}, history)["A"] < BKT_PROFICIENT

    template = assets.templates["rich-check-binary-free-d3"]
    practice = [
        _row_to_item(
            fixture.fixture_item(template, slug="binary", stage="practice", format=fmt, variant=0)
        )
        for fmt in ("free", "teachback")
    ]
    assert posttest_reserve_hash(bank + practice) == reserve
    seen = {entry["question_hash"] for entry in history} | {reserve}
    first = select_item(bank + practice, format="free", difficulty=3, exclude_hashes=seen)
    assert first is not None and first.difficulty == 3
    assert observe(first, True) is True  # released free/d3 is still owed
    assert planner.planning_states({"A": fixture.INITIAL_PRIOR}, history)["A"] < BKT_PROFICIENT
    second = select_item(
        bank + practice,
        format="teachback",
        difficulty=3,
        exclude_hashes=seen | {first.question_hash},
    )
    assert second is not None and second.difficulty == 3
    assert observe(second, True) is False  # genuinely different, unreleased class
    assert planner.planning_states({"A": fixture.INITIAL_PRIOR}, history)["A"] >= BKT_PROFICIENT
