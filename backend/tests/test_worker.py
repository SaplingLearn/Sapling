"""#116: the worker loop (worker/runner.py) and its process (worker/__main__.py).

The queue here is a fake that hands out scripted jobs. That is deliberate and
limited: it pins the LOOP (dispatch, outcome recording, stop handling, batch
shape), not claim semantics. A fake claim cannot see a re-offer bug, so
SKIP LOCKED, leases, attempts and dead-lettering are tested against real SQL
in tests/integration/test_jobs_queue_db.py.
"""
import os
import signal
import threading
from unittest.mock import patch

import pytest

from services import jobs as jobs_module
from services.jobs import Job, PermanentJobError
from worker import __main__ as worker_main
from worker.runner import Worker


def _job(n: int, type_: str = "t.ok") -> Job:
    return Job(id=f"j-{n}", type=type_, payload={"n": n}, attempt=1, max_attempts=5,
               locked_by="w")


class FakeQueue:
    def __init__(self, jobs=(), handlers=None, *, claim_error=None,
                 complete_result=True, fail_result="failed"):
        self.pending = list(jobs)
        self.handlers = handlers or {}
        self.claim_error = claim_error
        self.complete_result = complete_result
        self.fail_result = fail_result
        self.claims: list[dict] = []
        self.completed: list[str] = []
        self.failed: list[tuple[str, str, bool]] = []

    def claim(self, worker_id, *, types=None, limit=1, lease_seconds=300):
        self.claims.append({"worker": worker_id, "types": types, "limit": limit,
                            "lease": lease_seconds})
        if self.claim_error:
            raise self.claim_error
        out, self.pending = self.pending[:limit], self.pending[limit:]
        return out

    def get_handler(self, job_type):
        return self.handlers.get(job_type)

    def complete(self, job):
        self.completed.append(job.id)
        return self.complete_result

    def fail(self, job, error, *, permanent=False):
        self.failed.append((job.id, error, permanent))
        return self.fail_result


def _worker(queue, **kw):
    kw.setdefault("types", ["t.ok"])
    return Worker(worker_id="w", queue=queue, poll_interval=0.01, **kw)


# ── dispatch ────────────────────────────────────────────────────────────────


def test_a_successful_job_is_completed():
    seen = []
    q = FakeQueue([_job(1)], {"t.ok": seen.append})
    assert _worker(q).run_once() == 1
    assert seen == [{"n": 1}]
    assert q.completed == ["j-1"] and q.failed == []


def test_claims_one_at_a_time_for_the_registered_types_up_to_the_batch():
    q = FakeQueue([_job(i) for i in range(5)], {"t.ok": lambda p: None})
    assert _worker(q, batch=3, lease_seconds=420).run_once() == 3
    assert [c["limit"] for c in q.claims] == [1, 1, 1]
    assert all(c["types"] == ["t.ok"] and c["lease"] == 420 for c in q.claims)
    assert q.completed == ["j-0", "j-1", "j-2"]


def test_an_empty_queue_ends_the_pass():
    q = FakeQueue([], {"t.ok": lambda p: None})
    assert _worker(q, batch=10).run_once() == 0
    assert len(q.claims) == 1


def test_a_handler_exception_is_a_retryable_failure():
    def boom(payload):
        raise ValueError("provider blip")

    q = FakeQueue([_job(1)], {"t.ok": boom})
    _worker(q).run_once()
    assert q.completed == []
    assert q.failed == [("j-1", "ValueError: provider blip", False)]


def test_a_permanent_error_dead_letters_at_once():
    def bad(payload):
        raise PermanentJobError("payload has no offering_id")

    q = FakeQueue([_job(1)], {"t.ok": bad}, fail_result="dead")
    _worker(q).run_once()
    assert q.failed == [("j-1", "PermanentJobError: payload has no offering_id", True)]


def test_an_unknown_type_fails_with_backoff_not_straight_to_dead():
    # A newer API image may have enqueued a type a worker mid-deploy lacks.
    q = FakeQueue([_job(1, "t.new")], {"t.ok": lambda p: None})
    _worker(q).run_once()
    assert q.completed == []
    (job_id, error, permanent), = q.failed
    assert job_id == "j-1" and "t.new" in error and permanent is False


def test_a_failed_claim_ends_the_pass_without_raising():
    q = FakeQueue(claim_error=RuntimeError("PostgREST down"))
    assert _worker(q).run_once() == 0


def test_a_lost_lease_on_complete_or_fail_does_not_raise():
    q = FakeQueue([_job(1)], {"t.ok": lambda p: None}, complete_result=False)
    assert _worker(q).run_once() == 1

    def boom(payload):
        raise ValueError("x")

    q = FakeQueue([_job(2)], {"t.ok": boom}, fail_result=None)
    assert _worker(q).run_once() == 1


def test_a_complete_that_raises_leaves_the_job_to_its_lease():
    class Q(FakeQueue):
        def complete(self, job):
            raise RuntimeError("db")

    q = Q([_job(1), _job(2)], {"t.ok": lambda p: None})
    assert _worker(q).run_once() == 2  # the pass goes on


def test_a_worker_needs_types():
    with pytest.raises(ValueError):
        Worker(worker_id="w", types=[], queue=FakeQueue())


# ── stopping ────────────────────────────────────────────────────────────────


def test_stop_lets_the_job_in_hand_finish_and_claims_nothing_more():
    stop = threading.Event()
    finished = []

    def handler(payload):
        stop.set()  # SIGTERM arrives mid-job
        finished.append(payload["n"])

    q = FakeQueue([_job(1), _job(2), _job(3)], {"t.ok": handler})
    w = _worker(q, stop=stop, batch=10)
    w.run_forever()  # returns because stop is set
    assert finished == [1]
    assert q.completed == ["j-1"]  # the job in hand was still recorded
    assert len(q.claims) == 1 and len(q.pending) == 2


def test_run_forever_polls_until_stopped():
    stop = threading.Event()
    q = FakeQueue([], {"t.ok": lambda p: None})
    t = threading.Thread(target=_worker(q, stop=stop).run_forever)
    t.start()
    try:
        for _ in range(200):
            if len(q.claims) >= 3:
                break
            threading.Event().wait(0.01)
    finally:
        stop.set()
        t.join(timeout=2)
    assert not t.is_alive()
    assert len(q.claims) >= 3  # kept polling an empty queue


def test_sigterm_sets_the_stop_event():
    stop = threading.Event()
    old_term = signal.getsignal(signal.SIGTERM)
    old_int = signal.getsignal(signal.SIGINT)
    try:
        worker_main.install_signal_handlers(stop)
        os.kill(os.getpid(), signal.SIGTERM)
        assert stop.wait(2)
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)


# ── the process ─────────────────────────────────────────────────────────────


@pytest.fixture
def quiet_main():
    """main() without touching the real process: no .env load, no root-logger
    rewiring, no signal handlers, no events drain thread."""
    with patch("dotenv.load_dotenv"), \
         patch.object(worker_main, "_configure_logging"), \
         patch.object(worker_main, "install_signal_handlers"), \
         patch("services.events_service.start_worker"), \
         patch("services.events_service.shutdown") as shutdown:
        yield shutdown


def test_boot_failure_refuses_to_start(quiet_main):
    with patch.object(worker_main, "boot", side_effect=RuntimeError("Missing SUPABASE_URL")), \
         patch("worker.runner.Worker.run_forever") as run:
        assert worker_main.main([]) == worker_main.EXIT_BOOT_FAILED
    run.assert_not_called()


def test_boot_runs_the_api_lifespan_checks_in_order():
    calls = []
    with patch("agents._providers.freeze_model_mode",
               side_effect=lambda: calls.append("freeze") or "real"), \
         patch("config.validate_config", side_effect=lambda: calls.append("config")), \
         patch("services.encryption_canary.verify_encryption_key",
               side_effect=lambda: calls.append("canary")):
        worker_main.boot()
    assert calls == ["freeze", "config", "canary"]


def test_a_requested_type_without_a_handler_refuses_to_start(quiet_main):
    with patch.object(worker_main, "boot"), \
         patch.object(worker_main, "load_handlers", return_value=["t.ok"]), \
         patch("worker.runner.Worker.run_forever") as run:
        assert worker_main.main(["--types", "t.ok,t.nope"]) == worker_main.EXIT_BOOT_FAILED
    run.assert_not_called()


def test_once_runs_one_pass_with_the_cli_settings_and_flushes_events(quiet_main):
    with patch.object(worker_main, "boot"), \
         patch.object(worker_main, "load_handlers", return_value=["t.a", "t.b"]), \
         patch("worker.runner.Worker.run_once", autospec=True) as run_once:
        rc = worker_main.main(["--once", "--batch", "4", "--lease-seconds", "900",
                               "--poll-interval", "0.5", "--worker-id", "w-test"])
    assert rc == 0
    (w,), _ = run_once.call_args
    assert (w.worker_id, w.types, w.batch, w.lease_seconds, w.poll_interval) == (
        "w-test", ["t.a", "t.b"], 4, 900, 0.5)
    quiet_main.assert_called_once()  # events_service.shutdown


def test_load_handlers_registers_course_context():
    assert "course_context.refresh" in worker_main.load_handlers()


# ── lease heartbeat (20261108213623) ────────────────────────────────────────


class BeatingQueue(FakeQueue):
    def __init__(self, *a, beat_results=None, beat_error=None, **kw):
        super().__init__(*a, **kw)
        self.beats: list[str] = []
        self.beat_results = list(beat_results or [])
        self.beat_error = beat_error
        self.scheduled: list[int] = []
        self.schedule_error = None

    def heartbeat(self, job):
        self.beats.append(job.id)
        if self.beat_error:
            raise self.beat_error
        return self.beat_results.pop(0) if self.beat_results else True

    def schedule_prune(self, older_than_days):
        self.scheduled.append(older_than_days)
        if self.schedule_error:
            raise self.schedule_error
        return {"id": "p", "inserted": True}


def _sleeper(seconds):
    return lambda payload: threading.Event().wait(seconds)


def test_a_long_handler_heartbeats_its_lease_until_it_finishes():
    q = BeatingQueue([_job(1)], {"t.ok": _sleeper(0.25)})
    _worker(q, heartbeat_interval=0.03).run_once()
    assert len(q.beats) >= 3 and set(q.beats) == {"j-1"}
    n = len(q.beats)
    threading.Event().wait(0.1)
    assert len(q.beats) == n, "kept beating after the handler returned"
    assert q.completed == ["j-1"]


def test_a_quick_handler_never_beats():
    q = BeatingQueue([_job(1)], {"t.ok": lambda p: None})
    _worker(q, heartbeat_interval=5).run_once()
    assert q.beats == [] and q.completed == ["j-1"]


def test_the_default_heartbeat_is_a_third_of_the_fleet_minimum_and_zero_turns_it_off():
    # Paced by the FLEET minimum, not this worker's own lease: another worker
    # claiming with MIN_LEASE_SECONDS must never see this one's job as expired.
    third = jobs_module.MIN_LEASE_SECONDS / 3
    assert _worker(FakeQueue()).heartbeat_interval == third
    assert _worker(FakeQueue(), lease_seconds=3600).heartbeat_interval == third
    q = BeatingQueue([_job(1)], {"t.ok": _sleeper(0.1)})
    _worker(q, heartbeat_interval=0).run_once()
    assert q.beats == []


def _lease_lost_warnings(caplog):
    return [r for r in caplog.records
            if r.levelname == "WARNING" and "job.lease_lost" in r.getMessage()]


def test_a_refused_heartbeat_stops_beating_and_the_outcome_is_still_attempted(caplog):
    q = BeatingQueue([_job(1)], {"t.ok": _sleeper(0.25)}, beat_results=[True, False],
                     complete_result=False)
    with caplog.at_level("INFO", "sapling.worker"):
        _worker(q, heartbeat_interval=0.03).run_once()
    assert q.beats == ["j-1", "j-1"]  # stopped at the refusal
    assert q.completed == ["j-1"]     # the fenced complete still decides it
    assert "heartbeat refused" in caplog.text
    # One lost claim, one warning: the refused complete is only INFO.
    assert len(_lease_lost_warnings(caplog)) == 1


def test_a_refused_heartbeat_then_a_refused_fail_warns_once(caplog):
    def boom(payload):
        threading.Event().wait(0.2)
        raise ValueError("x")

    q = BeatingQueue([_job(1)], {"t.ok": boom}, beat_results=[False], fail_result=None)
    with caplog.at_level("INFO", "sapling.worker"):
        _worker(q, heartbeat_interval=0.03).run_once()
    assert q.failed and q.failed[0][0] == "j-1"   # still attempted
    assert len(_lease_lost_warnings(caplog)) == 1


def test_a_reaped_job_still_records_its_real_outcome(caplog):
    # Heartbeat refused because the row was reaped `dead` on its last attempt:
    # complete_job accepts the same fence on a dead row, so the run is recorded.
    q = BeatingQueue([_job(1)], {"t.ok": _sleeper(0.2)}, beat_results=[False],
                     complete_result=True)
    with caplog.at_level("INFO", "sapling.worker"):
        _worker(q, heartbeat_interval=0.03).run_once()
    assert q.completed == ["j-1"]
    assert "job.succeeded" in caplog.text


def test_a_lost_complete_without_a_refused_heartbeat_still_warns(caplog):
    q = BeatingQueue([_job(1)], {"t.ok": lambda p: None}, complete_result=False)
    with caplog.at_level("INFO", "sapling.worker"):
        _worker(q, heartbeat_interval=5).run_once()
    assert len(_lease_lost_warnings(caplog)) == 1


# ── the fleet-wide lease rule (services/jobs.py MIN_LEASE_SECONDS) ──────────


def test_a_worker_refuses_a_lease_under_the_fleet_minimum():
    with pytest.raises(ValueError, match="minimum"):
        _worker(FakeQueue(), lease_seconds=jobs_module.MIN_LEASE_SECONDS - 1)
    assert _worker(FakeQueue(), lease_seconds=jobs_module.MIN_LEASE_SECONDS).lease_seconds \
        == jobs_module.MIN_LEASE_SECONDS


def test_an_explicit_heartbeat_interval_is_capped_at_the_fleet_pace():
    w = _worker(FakeQueue(), lease_seconds=3600, heartbeat_interval=1200)
    assert w.heartbeat_interval == jobs_module.HEARTBEAT_INTERVAL_SECONDS


def test_any_allowed_lease_outlasts_every_workers_heartbeat_gap():
    # The invariant the rule exists for: the shortest lease any claimer may
    # use spans three beats of ANY worker, so two lost beats are survivable.
    for lease in (jobs_module.MIN_LEASE_SECONDS, 900, 3600):
        w = _worker(FakeQueue(), lease_seconds=lease)
        assert 3 * w.heartbeat_interval <= jobs_module.MIN_LEASE_SECONDS


@pytest.mark.parametrize("how", ["cli", "env"])
def test_the_cli_refuses_a_short_lease_at_boot(quiet_main, monkeypatch, caplog, how):
    argv = ["--once"]
    if how == "cli":
        argv += ["--lease-seconds", "60"]
    else:
        monkeypatch.setenv("JOBS_LEASE_SECONDS", "60")
    with patch.object(worker_main, "boot") as boot, \
         patch("worker.runner.Worker.run_once") as run, \
         caplog.at_level("CRITICAL", "sapling.worker"):
        assert worker_main.main(argv) == worker_main.EXIT_BOOT_FAILED
    boot.assert_not_called()
    run.assert_not_called()
    assert "minimum" in caplog.text and "JOBS_LEASE_SECONDS" in caplog.text


def test_a_heartbeat_error_is_retried_next_interval():
    q = BeatingQueue([_job(1)], {"t.ok": _sleeper(0.2)}, beat_error=RuntimeError("blip"))
    _worker(q, heartbeat_interval=0.03).run_once()
    assert len(q.beats) >= 2
    assert q.completed == ["j-1"]


def test_the_heartbeat_gives_up_on_a_hung_handler(caplog):
    q = BeatingQueue([_job(1)], {"t.ok": _sleeper(0.4)})
    with caplog.at_level("ERROR", "sapling.worker"):
        _worker(q, heartbeat_interval=0.03, max_heartbeat_seconds=0.1).run_once()
    assert 1 <= len(q.beats) <= 4
    assert "heartbeat_gave_up" in caplog.text


def test_a_handler_failure_still_stops_the_heartbeat():
    def boom(payload):
        threading.Event().wait(0.1)
        raise ValueError("x")

    q = BeatingQueue([_job(1)], {"t.ok": boom})
    _worker(q, heartbeat_interval=0.03).run_once()
    n = len(q.beats)
    threading.Event().wait(0.1)
    assert len(q.beats) == n and q.failed and q.failed[0][0] == "j-1"


# ── prune upkeep ────────────────────────────────────────────────────────────


def _run_briefly(worker, seconds=0.15):
    t = threading.Thread(target=worker.run_forever)
    t.start()
    threading.Event().wait(seconds)
    worker.stop.set()
    t.join(timeout=2)
    assert not t.is_alive()


def test_a_worker_that_claims_prune_schedules_it_once_per_interval():
    q = BeatingQueue([], {"jobs.prune": lambda p: None})
    _run_briefly(_worker(q, types=["jobs.prune"], prune_interval=3600, prune_after_days=9))
    assert q.scheduled == [9]


def test_prune_is_rescheduled_after_the_interval():
    q = BeatingQueue([], {"jobs.prune": lambda p: None})
    _run_briefly(_worker(q, types=["jobs.prune"], prune_interval=0.02), seconds=0.2)
    assert len(q.scheduled) >= 2


@pytest.mark.parametrize("kw", [
    {"types": ["t.ok"]},                                  # does not claim it
    {"types": ["jobs.prune"], "prune_after_days": 0},     # switched off
])
def test_prune_is_not_scheduled_by_a_worker_that_will_not_run_it(kw):
    q = BeatingQueue([], {"t.ok": lambda p: None, "jobs.prune": lambda p: None})
    _run_briefly(_worker(q, **kw))
    assert q.scheduled == []


def test_a_failed_prune_schedule_does_not_stop_the_worker():
    q = BeatingQueue([_job(1, "jobs.prune")], {"jobs.prune": lambda p: None})
    q.schedule_error = RuntimeError("PostgREST down")
    _run_briefly(_worker(q, types=["jobs.prune"]))
    assert q.scheduled and q.completed == ["j-1"]


def test_cli_passes_the_upkeep_settings(quiet_main, monkeypatch):
    monkeypatch.setenv("JOBS_PRUNE_AFTER_DAYS", "21")
    with patch.object(worker_main, "boot"), \
         patch.object(worker_main, "load_handlers", return_value=["t.a"]), \
         patch("worker.runner.Worker.run_once", autospec=True) as run_once:
        assert worker_main.main(["--once", "--max-heartbeat-seconds", "600"]) == 0
    (w,), _ = run_once.call_args
    assert (w.prune_after_days, w.max_heartbeat_seconds) == (21, 600)


def test_load_handlers_registers_the_prune_job():
    assert "jobs.prune" in worker_main.load_handlers()
