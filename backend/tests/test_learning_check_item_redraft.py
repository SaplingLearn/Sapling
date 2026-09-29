"""PKG-04 post-hoc (owner decision A38, low-severity 2): bounded redrafting.

A concept whose drafts always fail was redrafted on every upload and every
backfill. `check_item_draft_failures` counts a concept's consecutive failed
passes against a fingerprint of the passages it is drafted from: at
CHECK_ITEM_REDRAFT_MAX_FAILURES failures on an unchanged source the concept is
skipped; a stored item resets the count; a changed source resets it too. The
bookkeeping fails open: a read or write error never blocks drafting."""

from __future__ import annotations

import pathlib
import re
from unittest.mock import patch

import pytest

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"
_KEY = "learning rate"
_CHUNK = {"id": "c1", "chunk_index": 0, "chunk_text": "learning rate text", "doc_id": "doc-1"}
_OTHER = {"id": "c2", "chunk_index": 1, "chunk_text": "learning rate, revised", "doc_id": "doc-2"}


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_check_item_draft_failures.sql"))
    assert len(hits) == 1, hits
    return hits[0].read_text()


def _draft(**over):
    from learning.checks import CheckItemDraft

    base = dict(
        concept="Learning Rate",
        format="free",
        difficulty=1,
        prompt="In one sentence, what does the learning rate control?",
        reference_answer="The size of each update step along the negative gradient.",
        final_answer="The size of each update step",
        rubric=["Names the step size.", "Ties it to the gradient direction."],
        wrong_keys=["rate_is_iterations"],
        wrong_texts=["Confuses the rate with the number of iterations."],
        chunk_ids=["c1"],
    )
    base.update(over)
    return CheckItemDraft(**base)


class _Items:
    """check_items: nothing stored yet; upserts are kept."""

    def __init__(self):
        self.upserts: list = []

    def select(self, columns, filters=None, **kw):
        return []

    def upsert(self, rows, on_conflict=None):
        self.upserts.append(rows)
        return []


class _Failures:
    """check_item_draft_failures keyed (course_id, concept_key)."""

    def __init__(self, rows=(), *, fail_read=False, fail_write=False):
        self.rows = {(r["course_id"], r["concept_key"]): dict(r) for r in rows}
        self.fail_read = fail_read
        self.fail_write = fail_write
        self.reads = 0
        self.writes = 0

    def select(self, columns, filters=None, **kw):
        self.reads += 1
        if self.fail_read:
            raise RuntimeError("pg down")
        course = filters["course_id"][3:]
        return [dict(r) for (c, _), r in self.rows.items() if c == course]

    def upsert(self, rows, on_conflict=None):
        self.writes += 1
        if self.fail_write:
            raise RuntimeError("pg down")
        assert on_conflict == "course_id,concept_key"
        for r in rows if isinstance(rows, list) else [rows]:
            self.rows[(r["course_id"], r["concept_key"])] = dict(r)
        return []


@pytest.fixture
def env(monkeypatch):
    import config
    from services import check_item_service as svc

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    monkeypatch.setattr(svc, "CHECK_ITEM_MC_MIN_PER_CONCEPT", 0)  # no A37 top-up here
    with (
        patch.object(svc, "_withdrawn_sources", return_value=[]),
        patch.object(svc, "log_event"),
    ):
        yield svc


def _run(svc, failures, outcome, *, chunks=(_CHUNK,)):
    """One generation pass for "Learning Rate"; `outcome` is what the agent
    returns. Returns (GenerationOutcome, agent call count, items table)."""
    items = _Items()
    calls: list = []

    def factory(name):
        return {"check_items": items, "check_item_draft_failures": failures}[name]

    async def fake_draft(concepts, passages, *, deps, flex):
        calls.append(list(concepts))
        return outcome

    with (
        patch.object(svc, "table", side_effect=factory),
        patch.object(svc, "draft_items", side_effect=fake_draft),
    ):
        out = svc.generate_for_concepts(
            user_id="u1",
            course_id="course-1",
            concept_names=["Learning Rate"],
            chunks=list(chunks),
            flex=True,
        )
    return out, len(calls), items


def _invalid():
    from agents.check_items import CheckItemsUnavailable

    return CheckItemsUnavailable(reason="UnexpectedModelBehavior")


def _good():
    from agents.check_items import CheckItemsOutput

    return CheckItemsOutput(items=[_draft()])


class TestParamAndMigration:
    def test_param(self):
        from learning import params

        assert params.CHECK_ITEM_REDRAFT_MAX_FAILURES == 3

    def test_migration_is_a_series_migration_keyed_per_course_concept(self):
        hits = sorted(MIG_DIR.glob("*_learning_check_item_draft_failures.sql"))
        assert re.fullmatch(r"\d{14}_learning_check_item_draft_failures\.sql", hits[0].name)
        sql = _migration()
        assert "PKG-04" in sql
        assert "CREATE TABLE IF NOT EXISTS check_item_draft_failures" in sql
        for col in ("course_id", "concept_key", "failures", "source_fp"):
            assert re.search(rf"^\s*{col}\s", sql, re.M), col
        assert "PRIMARY KEY (course_id, concept_key)" in sql
        assert "REFERENCES" not in sql.upper()  # course assets, never a student's node (A2)


class TestBoundedRedraft:
    def test_a_concept_whose_drafts_keep_failing_is_skipped_after_the_bound(self, env):
        from learning.params import CHECK_ITEM_REDRAFT_MAX_FAILURES as n

        failures = _Failures()
        for i in range(n):
            out, calls, _ = _run(env, failures, _invalid())
            assert calls == 1 and out.concepts_attempted == 1
            assert failures.rows[("course-1", _KEY)]["failures"] == i + 1
        out, calls, _ = _run(env, failures, _invalid())
        assert calls == 0, "no agent call once the bound is reached on an unchanged source"
        assert out.concepts_attempted == 0 and out.concepts_skipped == 1
        assert failures.rows[("course-1", _KEY)]["failures"] == n

    def test_drafts_that_all_fail_validation_count_as_a_failure(self, env):
        from agents.check_items import CheckItemsOutput

        failures = _Failures()
        # the call answered, but nothing it drafted is for this concept: 0 stored
        off_topic = CheckItemsOutput(items=[_draft(concept="Momentum")])
        _, calls, items = _run(env, failures, off_topic)
        assert calls == 1 and items.upserts == []
        assert failures.rows[("course-1", _KEY)]["failures"] == 1

    def test_a_transient_http_failure_is_not_the_concepts_fault(self, env):
        from agents.check_items import CheckItemsUnavailable

        failures = _Failures()
        _run(env, failures, CheckItemsUnavailable(reason="ModelHTTPError"))
        assert failures.rows == {}

    def test_a_stored_item_resets_the_count(self, env):
        from learning.params import CHECK_ITEM_REDRAFT_MAX_FAILURES as n

        failures = _Failures()
        for _ in range(n - 1):
            _run(env, failures, _invalid())
        out, calls, items = _run(env, failures, _good())
        assert calls == 1 and out.items_created == 1
        assert failures.rows[("course-1", _KEY)]["failures"] == 0
        for _ in range(n - 1):
            _run(env, failures, _invalid())
        _, calls, _ = _run(env, failures, _invalid())
        assert calls == 1, "the reset gave the concept a fresh budget"

    def test_a_success_with_no_record_writes_nothing(self, env):
        failures = _Failures()
        _run(env, failures, _good())
        assert failures.writes == 0 and failures.rows == {}

    def test_a_changed_source_resets_the_count(self, env):
        from learning.params import CHECK_ITEM_REDRAFT_MAX_FAILURES as n

        failures = _Failures()
        for _ in range(n):
            _run(env, failures, _invalid())
        _, calls, _ = _run(env, failures, _invalid(), chunks=(_CHUNK,))
        assert calls == 0
        old_fp = failures.rows[("course-1", _KEY)]["source_fp"]
        _, calls, _ = _run(env, failures, _invalid(), chunks=(_CHUNK, _OTHER))
        assert calls == 1, "new passages: drafted again"
        row = failures.rows[("course-1", _KEY)]
        assert row["failures"] == 1 and row["source_fp"] != old_fp
        # a chunk whose text changed under the same id is a changed source too
        failures = _Failures()
        for _ in range(n):
            _run(env, failures, _invalid())
        edited = dict(_CHUNK, chunk_text="learning rate text, corrected")
        _, calls, _ = _run(env, failures, _invalid(), chunks=(edited,))
        assert calls == 1

    def test_the_fingerprint_ignores_passage_order(self, env):
        a = env._source_fingerprint([_CHUNK, _OTHER])
        assert a == env._source_fingerprint([_OTHER, _CHUNK])
        assert a != env._source_fingerprint([_CHUNK])

    def test_a_failed_read_still_drafts_and_warns(self, env, caplog):
        from learning.params import CHECK_ITEM_REDRAFT_MAX_FAILURES as n

        fp = env._source_fingerprint([_CHUNK])
        row = {"course_id": "course-1", "concept_key": _KEY, "failures": n, "source_fp": fp}
        failures = _Failures([row], fail_read=True)
        with caplog.at_level("WARNING", logger="sapling.services.check_items"):
            out, calls, _ = _run(env, failures, _good())
        assert calls == 1 and out.items_created == 1
        assert any("draft-failure" in r.getMessage() for r in caplog.records)

    def test_a_failed_write_still_drafts_and_warns(self, env, caplog):
        failures = _Failures(fail_write=True)
        with caplog.at_level("WARNING", logger="sapling.services.check_items"):
            out, calls, _ = _run(env, failures, _invalid())
        assert calls == 1 and out.concepts_attempted == 1
        assert any("draft-failure" in r.getMessage() for r in caplog.records)

    def test_the_bound_is_per_course(self, env):
        from learning.params import CHECK_ITEM_REDRAFT_MAX_FAILURES as n

        fp = env._source_fingerprint([_CHUNK])
        row = {"course_id": "course-2", "concept_key": _KEY, "failures": n, "source_fp": fp}
        _, calls, _ = _run(env, _Failures([row]), _invalid())
        assert calls == 1

    def test_flag_off_touches_nothing(self, monkeypatch):
        import config
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
        with patch.object(svc, "table") as t, patch.object(svc, "draft_items") as d:
            out = svc.generate_for_concepts(
                user_id="u1",
                course_id="course-1",
                concept_names=["Learning Rate"],
                chunks=[_CHUNK],
                flex=True,
            )
        assert tuple(out) == (0, 0, 0, 0, 0)
        t.assert_not_called()
        d.assert_not_called()
