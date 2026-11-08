"""#116: services/jobs.py (registry, backoff, the RPC argument shapes) and the
first job moved onto the queue, course-context aggregation.

Hermetic: `rpc` is patched, so these pin what the module SENDS. What the SQL
does with it (SKIP LOCKED, lease re-offer, attempts, dead-lettering, dedupe)
is pinned against real Postgres in tests/integration/test_jobs_queue_db.py.
"""
import random
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from services import course_context_service as ccs
from services import feature_flags as ff
from services import jobs
from services.feature_flags import Resolution


@pytest.fixture
def registry(monkeypatch):
    fresh: dict = {}
    monkeypatch.setattr(jobs, "_HANDLERS", fresh)
    return fresh


def _job(**over) -> jobs.Job:
    base = dict(id="j-1", type="t.x", payload={"a": 1}, attempt=1, max_attempts=5,
                locked_by="w-1")
    base.update(over)
    return jobs.Job(**base)


# ── registry ────────────────────────────────────────────────────────────────


def test_job_handler_registers_and_returns_the_function(registry):
    @jobs.job_handler("t.one")
    def handle(payload):
        return payload

    assert jobs.get_handler("t.one") is handle
    assert handle({"x": 1}) == {"x": 1}  # the decorator does not wrap
    assert jobs.get_handler("t.unknown") is None


def test_registered_types_are_sorted(registry):
    jobs.job_handler("b.two")(lambda p: None)
    jobs.job_handler("a.one")(lambda p: None)
    assert jobs.registered_types() == ["a.one", "b.two"]


def test_a_second_different_handler_for_a_type_is_refused(registry):
    def first(payload):
        pass

    def second(payload):
        pass

    jobs.job_handler("t.dup")(first)
    jobs.job_handler("t.dup")(first)  # the same function again: a no-op
    with pytest.raises(ValueError, match="t.dup"):
        jobs.job_handler("t.dup")(second)
    assert jobs.get_handler("t.dup") is first


def test_course_context_registers_its_handler():
    assert jobs.get_handler(ccs.COURSE_CONTEXT_JOB) is ccs._run_course_context_job
    assert ccs.COURSE_CONTEXT_JOB in jobs.registered_types()


# ── backoff ─────────────────────────────────────────────────────────────────


def test_backoff_doubles_from_the_base_and_caps():
    got = [jobs.backoff_seconds(a, jitter=False) for a in range(1, 10)]
    assert got == [30, 60, 120, 240, 480, 960, 1920, 3600, 3600]


def test_backoff_treats_a_nonpositive_attempt_as_the_first():
    assert jobs.backoff_seconds(0, jitter=False) == 30
    assert jobs.backoff_seconds(-3, jitter=False) == 30


def test_backoff_huge_attempt_does_not_overflow():
    assert jobs.backoff_seconds(10_000, jitter=False) == jobs.BACKOFF_CAP_SECONDS


def test_backoff_jitter_stays_within_half_to_full_delay():
    rng = random.Random(116)
    for attempt in range(1, 9):
        full = jobs.backoff_seconds(attempt, jitter=False)
        for _ in range(50):
            got = jobs.backoff_seconds(attempt, rng=rng)
            assert full // 2 <= got <= full


# ── what each call sends ────────────────────────────────────────────────────


def test_enqueue_sends_the_function_arguments_by_name():
    when = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    with patch.object(jobs, "rpc", return_value=[{"id": "u-1", "inserted": True}]) as rpc:
        out = jobs.enqueue("t.x", {"offering_id": "o1"}, dedupe_key="k", run_after=when,
                           max_attempts=3)
    rpc.assert_called_once_with("enqueue_job", {
        "p_type": "t.x",
        "p_payload": {"offering_id": "o1"},
        "p_dedupe_key": "k",
        "p_run_after": "2026-11-08T12:00:00+00:00",
        "p_max_attempts": 3,
    })
    assert out == {"id": "u-1", "inserted": True}


def test_enqueue_defaults():
    with patch.object(jobs, "rpc", return_value=[{"id": "u-2", "inserted": False}]) as rpc:
        out = jobs.enqueue("t.x")
    args = rpc.call_args.args[1]
    assert args["p_payload"] == {} and args["p_dedupe_key"] is None
    assert args["p_run_after"] is None
    assert args["p_max_attempts"] == jobs.DEFAULT_MAX_ATTEMPTS
    assert out == {"id": "u-2", "inserted": False}


def test_enqueue_raises_on_a_database_error():
    with patch.object(jobs, "rpc", side_effect=RuntimeError("PGRST202")):
        with pytest.raises(RuntimeError):
            jobs.enqueue("t.x")


def test_claim_sends_types_limit_and_lease_and_parses_rows():
    row = {"id": "u-3", "type": "t.x", "payload": {"a": 1}, "status": "running",
           "attempts": 2, "max_attempts": 5, "locked_by": "w-9", "locked_at": "…"}
    with patch.object(jobs, "rpc", return_value=[row]) as rpc:
        got = jobs.claim("w-9", types=["t.x"], limit=1, lease_seconds=60)
    rpc.assert_called_once_with("claim_jobs", {
        "p_worker": "w-9", "p_types": ["t.x"], "p_limit": 1, "p_lease_seconds": 60,
    })
    assert got == [jobs.Job(id="u-3", type="t.x", payload={"a": 1}, attempt=2,
                            max_attempts=5, locked_by="w-9")]


def test_claim_without_types_claims_every_type():
    with patch.object(jobs, "rpc", return_value=[]) as rpc:
        assert jobs.claim("w") == []
    assert rpc.call_args.args[1]["p_types"] is None
    assert rpc.call_args.args[1]["p_lease_seconds"] == jobs.DEFAULT_LEASE_SECONDS


def test_complete_is_fenced_on_worker_and_attempt():
    with patch.object(jobs, "rpc", return_value=True) as rpc:
        assert jobs.complete(_job(attempt=3)) is True
    rpc.assert_called_once_with("complete_job",
                                {"p_id": "j-1", "p_worker": "w-1", "p_attempt": 3})
    with patch.object(jobs, "rpc", return_value=False):
        assert jobs.complete(_job()) is False


def test_fail_sends_the_attempts_backoff_and_returns_the_new_status():
    with patch.object(jobs, "rpc", return_value="failed") as rpc:
        got = jobs.fail(_job(attempt=2), "boom", rng=random.Random(1))
    assert got == "failed"
    name, args = rpc.call_args.args
    assert name == "fail_job"
    assert args["p_id"] == "j-1" and args["p_worker"] == "w-1" and args["p_attempt"] == 2
    assert args["p_error"] == "boom" and args["p_permanent"] is False
    assert 30 <= args["p_backoff_seconds"] <= 60  # attempt 2: [60/2, 60]


def test_fail_permanent_and_lost_lease():
    with patch.object(jobs, "rpc", return_value="dead") as rpc:
        assert jobs.fail(_job(), "bad payload", permanent=True) == "dead"
    assert rpc.call_args.args[1]["p_permanent"] is True
    with patch.object(jobs, "rpc", return_value=None):
        assert jobs.fail(_job(), "x") is None


def test_fail_truncates_the_error():
    with patch.object(jobs, "rpc", return_value="failed") as rpc:
        jobs.fail(_job(), "x" * 10_000)
    assert len(rpc.call_args.args[1]["p_error"]) == jobs.MAX_ERROR_CHARS


# ── the flag ────────────────────────────────────────────────────────────────


def test_jobs_queue_flag_is_server_only_and_off_first():
    fd = ff.REGISTRY[jobs.JOBS_QUEUE_FLAG]
    assert fd.variants == ("off", "on")
    assert not fd.client_visible
    assert "worker" in fd.description  # says it needs one


def test_jobs_queue_flag_defaults_off_with_no_stored_config():
    # The hermetic Supabase stub answers every read with no rows.
    assert ff.flag_on(jobs.JOBS_QUEUE_FLAG, "u1") is False


# ── course-context aggregation behind the flag ──────────────────────────────


def _flag(variant: str):
    return patch("services.feature_flags.explain",
                 return_value=Resolution(variant, "default", ""))


def test_flag_off_runs_the_aggregation_inline_and_enqueues_nothing():
    with _flag("off") as explain, \
         patch.object(ccs, "update_course_context") as update, \
         patch.object(jobs, "rpc") as rpc:
        ccs.refresh_course_context("off-1", user_id="u1")
    update.assert_called_once_with("off-1")
    rpc.assert_not_called()
    explain.assert_called_once_with(jobs.JOBS_QUEUE_FLAG, "u1")


def test_flag_off_propagates_the_aggregations_error_like_before():
    # Callers wrap the old direct call in their own try/except; unchanged.
    with _flag("off"), patch.object(ccs, "update_course_context",
                                    side_effect=RuntimeError("db")):
        with pytest.raises(RuntimeError):
            ccs.refresh_course_context("off-1", user_id="u1")


def test_flag_on_enqueues_a_deduped_job_and_does_not_run_inline():
    with _flag("on"), \
         patch.object(ccs, "update_course_context") as update, \
         patch.object(jobs, "rpc", return_value=[{"id": "j", "inserted": True}]) as rpc:
        ccs.refresh_course_context("off-1", user_id="u1")
    update.assert_not_called()
    rpc.assert_called_once()
    name, args = rpc.call_args.args
    assert name == "enqueue_job"
    assert args["p_type"] == "course_context.refresh"
    assert args["p_payload"] == {"offering_id": "off-1"}
    assert args["p_dedupe_key"] == "course_context.refresh:off-1"


def test_flag_on_falls_back_inline_when_the_enqueue_fails():
    # The jobs migration not applied yet, or PostgREST down: never lose it.
    with _flag("on"), \
         patch.object(ccs, "update_course_context") as update, \
         patch.object(jobs, "rpc", side_effect=RuntimeError("PGRST202")):
        ccs.refresh_course_context("off-1", user_id="u1")
    update.assert_called_once_with("off-1")


def test_empty_offering_does_nothing():
    with patch.object(ccs, "update_course_context") as update, \
         patch("services.feature_flags.explain") as explain:
        ccs.refresh_course_context("", user_id="u1")
    update.assert_not_called()
    explain.assert_not_called()


def test_the_worker_handler_runs_the_same_aggregation():
    with patch.object(ccs, "update_course_context") as update:
        ccs._run_course_context_job({"offering_id": "off-9"})
    update.assert_called_once_with("off-9")


@pytest.mark.parametrize("payload", [{}, None, {"offering_id": ""}, {"offering_id": 7}])
def test_the_worker_handler_dead_letters_a_payload_without_an_offering(payload):
    with patch.object(ccs, "update_course_context") as update:
        with pytest.raises(jobs.PermanentJobError):
            ccs._run_course_context_job(payload)
    update.assert_not_called()


def test_graph_service_triggers_resolve_the_flag_for_the_student():
    """graph_service's refreshes now go through refresh_course_context with
    the student's id; with the flag off that is the same inline call."""
    from services import graph_service

    with patch.object(ccs, "refresh_course_context") as refresh, \
         patch("services.academics.user_offering_ids_for_course", return_value=["o1"]), \
         patch.object(graph_service, "table") as tbl:
        tbl.return_value.select.return_value = [{"id": "n1", "course_id": "c1"}]
        assert graph_service.delete_node("u7", "n1") == {"deleted": True}
    refresh.assert_called_once_with("o1", user_id="u7")
