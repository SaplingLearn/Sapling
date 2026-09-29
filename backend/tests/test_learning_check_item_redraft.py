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


# ── A38 fix round (M2): an allowlist, per-concept outcomes, and an expiry ────


def _run_many(svc, failures, outcome, names):
    """One pass over several concepts (one batch); returns (outcome, calls)."""
    items = _Items()
    calls: list = []

    def factory(name):
        return {"check_items": items, "check_item_draft_failures": failures}[name]

    async def fake_draft(concepts, passages, *, deps, flex):
        calls.append(list(concepts))
        return outcome

    chunks = [
        {"id": f"c{i}", "chunk_index": i, "chunk_text": f"{n} text", "doc_id": "doc-1"}
        for i, n in enumerate(names)
    ]
    with (
        patch.object(svc, "table", side_effect=factory),
        patch.object(svc, "draft_items", side_effect=fake_draft),
    ):
        out = svc.generate_for_concepts(
            user_id="u1", course_id="course-1", concept_names=names, chunks=chunks, flex=True
        )
    return out, len(calls)


class TestRedraftAllowlist:
    @pytest.mark.parametrize(
        "reason",
        [
            "ModelHTTPError",
            "ModelAPIError",
            "ReadTimeout",
            "TimeoutException",
            "TimeoutError",
            "ConnectError",
            "TransportError",
            "UsageLimitExceeded",
            "RuntimeError",
            "SomethingNew",
        ],
    )
    def test_only_a_validation_failure_counts(self, env, reason):
        from agents.check_items import CheckItemsUnavailable

        failures = _Failures()
        for _ in range(5):
            _, calls, _ = _run(env, failures, CheckItemsUnavailable(reason=reason))
            assert calls == 1, reason
        assert failures.rows == {}, reason

    def test_a_batch_level_failure_is_charged_only_after_a_split(self, env):
        """A38 fix round 2: a multi-concept validation failure is nobody's by
        itself; the split re-runs each concept alone, and only a concept that
        fails ALONE is counted."""
        failures = _Failures()
        names = ["Learning Rate", "Momentum", "Batch Size"]
        out, calls = _run_many(env, failures, _invalid(), names)
        assert calls == 1 + len(names) and out.concepts_attempted == 3
        assert {r["failures"] for r in failures.rows.values()} == {1}
        assert len(failures.rows) == 3

    def test_a_good_co_batched_concept_is_never_stalled(self, env):
        from agents.check_items import CheckItemsOutput

        failures = _Failures()
        names = ["Learning Rate", "Momentum"]
        # the call answered: Learning Rate got a draft, Momentum got none
        half = CheckItemsOutput(items=[_draft()])
        for _ in range(5):
            out, calls = _run_many(env, failures, half, names)
            assert calls == 1 and out.items_created == 1, "Learning Rate is drafted every pass"
        assert ("course-1", _KEY) not in failures.rows
        # Momentum's own outcome (nothing stored for it) is what counts: it stalls
        from learning.params import CHECK_ITEM_REDRAFT_MAX_FAILURES as n

        assert failures.rows[("course-1", "momentum")]["failures"] == n


class TestRedraftExpiry:
    def test_param(self):
        from learning import params

        assert params.CHECK_ITEM_REDRAFT_FAILURE_TTL_DAYS == 14

    def test_a_stalled_concept_is_retried_after_the_ttl(self, env, monkeypatch):
        from datetime import UTC, datetime, timedelta

        from learning.params import CHECK_ITEM_REDRAFT_FAILURE_TTL_DAYS as ttl
        from learning.params import CHECK_ITEM_REDRAFT_MAX_FAILURES as n

        failures = _Failures()
        for _ in range(n):
            _run(env, failures, _invalid())
        _, calls, _ = _run(env, failures, _invalid())
        assert calls == 0
        later = datetime.now(UTC) + timedelta(days=ttl, hours=1)
        monkeypatch.setattr(env, "_utcnow", lambda: later)
        _, calls, _ = _run(env, failures, _invalid())
        assert calls == 1, "past the TTL the concept is drafted again"
        _, calls, _ = _run(env, failures, _invalid())
        assert calls == 0, "and a fresh failure stalls it for another TTL"

    def test_a_row_with_no_readable_updated_at_is_not_stalled(self, env):
        from learning.params import CHECK_ITEM_REDRAFT_MAX_FAILURES as n

        fp = env._source_fingerprint([_CHUNK])
        for stamp in (None, "not a date"):
            row = {
                "course_id": "course-1",
                "concept_key": _KEY,
                "failures": n,
                "source_fp": fp,
                "updated_at": stamp,
            }
            _, calls, _ = _run(env, _Failures([row]), _good())
            assert calls == 1, stamp

    def test_a_prompt_or_model_change_resets_the_count(self, env, monkeypatch):
        from agents import check_items
        from learning.params import CHECK_ITEM_REDRAFT_MAX_FAILURES as n

        failures = _Failures()
        for _ in range(n):
            _run(env, failures, _invalid())
        _, calls, _ = _run(env, failures, _invalid())
        assert calls == 0
        monkeypatch.setattr(check_items, "_PROMPT_HASH", "a-new-prompt")
        _, calls, _ = _run(env, failures, _invalid())
        assert calls == 1, "a new prompt is a new source"
        for _ in range(n):
            _run(env, failures, _invalid())
        _, calls, _ = _run(env, failures, _invalid())
        assert calls == 0
        monkeypatch.setenv("SAPLING_MODEL_CHECK_ITEMS", "some-other-model")
        _, calls, _ = _run(env, failures, _invalid())
        assert calls == 1, "a new model is a new source"


def test_the_draft_failures_table_is_backend_only():
    """A38 fix round (m1): RLS with no policy + guarded REVOKE/GRANT, the idiom of
    20260929050404_learning_ai_tutor_daily_calls.sql, in a NEW migration."""
    hits = sorted(MIG_DIR.glob("*_learning_check_item_draft_failures_rls.sql"))
    assert len(hits) == 1, hits
    assert re.fullmatch(r"\d{14}_learning_check_item_draft_failures_rls\.sql", hits[0].name)
    first = sorted(MIG_DIR.glob("*_learning_check_item_draft_failures.sql"))[0].name
    assert hits[0].name > first, "appended after the table's own migration"
    ddl = hits[0].read_text()
    t = "check_item_draft_failures"
    assert f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY" in ddl
    assert f"REVOKE ALL ON TABLE {t} FROM PUBLIC" in ddl
    assert "FROM pg_roles WHERE rolname = r" in ddl
    assert f"'REVOKE ALL ON TABLE {t} FROM %I'" in ddl
    assert "rolname = 'service_role'" in ddl
    assert f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {t} TO service_role" in ddl
    assert "CREATE POLICY" not in ddl.upper()


# ── A38 fix round 2 (MAJOR 1): a failing multi-concept call is split ────────


def _split_run(svc, failures, bad: str, names):
    """One pass where any call that includes `bad` fails validation; a call
    without it drafts one valid item per concept. Returns (outcome, calls, items)."""
    from agents.check_items import CheckItemsOutput, CheckItemsUnavailable

    items = _Items()
    calls: list = []

    def factory(name):
        return {"check_items": items, "check_item_draft_failures": failures}[name]

    async def fake_draft(concepts, passages, *, deps, flex):
        calls.append(list(concepts))
        if bad in concepts:
            return CheckItemsUnavailable(reason="UnexpectedModelBehavior")
        return CheckItemsOutput(
            items=[_draft(concept=c, chunk_ids=[passages[0]["id"]]) for c in concepts]
        )

    chunks = [
        {"id": f"c{i}", "chunk_index": i, "chunk_text": f"{n} text", "doc_id": "doc-1"}
        for i, n in enumerate(names)
    ]
    with (
        patch.object(svc, "table", side_effect=factory),
        patch.object(svc, "draft_items", side_effect=fake_draft),
    ):
        out = svc.generate_for_concepts(
            user_id="u1", course_id="course-1", concept_names=names, chunks=chunks, flex=True
        )
    return out, calls, items


class TestSplitOnValidationFailure:
    NAMES = ["Learning Rate", "Momentum", "Batch Size"]

    def test_batch_mates_are_rescued_and_only_the_bad_concept_counts(self, env):
        failures = _Failures()
        out, calls, items = _split_run(env, failures, "Momentum", self.NAMES)
        assert calls[0] == self.NAMES
        assert sorted(map(tuple, calls[1:])) == [(n,) for n in sorted(self.NAMES)]
        stored = {r["concept_key"] for rows in items.upserts for r in rows}
        assert stored == {"learning rate", "batch size"}, "the batch-mates get items this pass"
        assert out.concepts_attempted == 3 and out.unavailable == 1
        assert {k for (_, k), r in failures.rows.items() if r["failures"]} == {"momentum"}
        assert failures.rows[("course-1", "momentum")]["failures"] == 1

    def test_cost_is_at_most_one_plus_n_calls_per_failing_batch(self, env):
        from learning.params import CHECK_ITEM_CONCEPTS_PER_CALL as per_call

        failures = _Failures()
        _, calls, _ = _split_run(env, failures, "Momentum", self.NAMES)
        assert len(calls) <= 1 + per_call
        # every concept failing: still one split per batch, never a second
        _, calls, _ = _split_run(env, _Failures(), "*", ["*"] + self.NAMES[1:])
        assert len(calls) <= 1 + per_call

    def test_the_bad_concept_is_skipped_after_the_bound(self, env):
        from learning.params import CHECK_ITEM_REDRAFT_MAX_FAILURES as n

        failures = _Failures()
        for _ in range(n):
            _split_run(env, failures, "Momentum", self.NAMES)
        assert failures.rows[("course-1", "momentum")]["failures"] == n
        out, calls, _ = _split_run(env, failures, "Momentum", self.NAMES)
        assert all("Momentum" not in c for c in calls)
        assert out.concepts_skipped >= 1

    def test_a_transient_batch_failure_is_not_split(self, env):
        from agents.check_items import CheckItemsUnavailable

        failures = _Failures()
        out, calls = _run_many(
            env, failures, CheckItemsUnavailable(reason="ReadTimeout"), self.NAMES
        )
        assert calls == 1 and failures.rows == {}
