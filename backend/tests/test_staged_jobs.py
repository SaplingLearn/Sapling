"""services/staged_jobs.py: the staged-job machinery shared by the queued
upload (document_jobs) and the queued Gradescope sync (gradescope_jobs).

The two callers' own suites (test_document_upload_jobs.py,
test_gradescope_sync_jobs.py) pin the behaviour end to end; these pin the
shared pieces directly: the exact writes and filters on the wire, liveness,
the enqueue fallback, and the watch loop under both drivers.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services import staged_jobs as sj

SPEC = sj.Spec(table="things", job_type="thing.run", owner_column="meta", label="thing")


def _db(update_returns=None, select_returns=None):
    handle = MagicMock()
    handle.update.return_value = [{"id": "r1"}] if update_returns is None else update_returns
    handle.select.return_value = select_returns or []
    db = MagicMock(return_value=handle)
    return db, handle


def _iso(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


# ── pure helpers ────────────────────────────────────────────────────────────


def test_spec_paths_and_dedupe_key():
    assert SPEC.owner_path == "meta->>owner"
    assert SPEC.inline_owner_path == "meta->>inline_owner"
    assert SPEC.dedupe_key("r1") == "thing.run:r1"


def test_age_seconds_reads_naive_and_z_timestamps_as_utc():
    assert sj.age_seconds(None) is None and sj.age_seconds("nope") is None
    naive = (datetime.now(timezone.utc) - timedelta(seconds=30)).replace(tzinfo=None).isoformat()
    assert 29 <= sj.age_seconds(naive) <= 31
    z = (datetime.now(timezone.utc) - timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert 9 <= sj.age_seconds(z) <= 12


def test_token_in_only_returns_a_non_empty_string():
    assert sj.token_in({"meta": {"owner": "w#1"}}, "meta", "owner") == "w#1"
    for row in (None, {}, {"meta": None}, {"meta": {"owner": ""}}, {"meta": {"owner": 3}}):
        assert sj.token_in(row, "meta", "owner") is None


def test_owner_token_is_worker_and_attempt_or_unique():
    assert sj.owner_token(SimpleNamespace(locked_by="w-1", attempt=2)) == "w-1#2"
    a, b = sj.owner_token(None), sj.owner_token(None)
    assert a.startswith("direct#") and a != b


@pytest.mark.parametrize("job,lease,alive", [
    (None, None, False),
    ({"status": "queued"}, 60, True),
    ({"status": "failed"}, 60, True),
    ({"status": "running", "locked_ago": 10}, 60, True),
    ({"status": "running", "locked_ago": 600}, 60, False),
    ({"status": "running", "locked_ago": 600}, None, True),  # lease not judged
    ({"status": "running"}, 60, True),  # unreadable locked_at reads alive
    ({"status": "dead"}, None, False),
    ({"status": "succeeded"}, None, False),
])
def test_job_alive(job, lease, alive):
    if job and "locked_ago" in job:  # built at run time, not collection time
        job = {"status": job["status"], "locked_at": _iso(job["locked_ago"])}
    assert sj.job_alive(job, lease_seconds=lease) is alive


def test_live_job_statuses():
    assert sj.LIVE_JOB == {"queued", "running", "failed"}


# ── DB steps: exact writes and filters ──────────────────────────────────────


def test_take_back_swaps_queued_to_inline_with_the_token_and_clears():
    db, h = _db()
    assert sj.take_back(SPEC, db, "r1", "tok", clear={"blob": None}) is True
    db.assert_called_with("things")
    h.update.assert_called_once_with(
        {"stage": "inline", "blob": None, "meta": {"inline_owner": "tok"}},
        filters={"id": "eq.r1", "stage": "eq.queued"},
    )
    db, h = _db(update_returns=[])
    assert sj.take_back(SPEC, db, "r1", "tok") is False


def test_finish_inline_is_fenced_on_the_token_and_never_raises():
    db, h = _db()
    assert sj.finish_inline(SPEC, db, "r1", "tok", {"stage": "done"}) is True
    h.update.assert_called_once_with({"stage": "done"}, filters={
        "id": "eq.r1", "stage": "eq.inline", "meta->>inline_owner": "eq.tok"})
    h.update.side_effect = RuntimeError("down")
    assert sj.finish_inline(SPEC, db, "r1", "tok", {"stage": "done"}) is False


@pytest.mark.parametrize("owner,expected", [("w#1", "eq.w#1"), (None, "is.null")])
def test_cas_update_fences_on_stage_and_owner(owner, expected):
    db, h = _db()
    assert sj.cas_update(SPEC, db, "r1", {"x": 1}, stage="running", owner=owner) is True
    h.update.assert_called_once_with({"x": 1}, filters={
        "id": "eq.r1", "stage": "eq.running", "meta->>owner": expected})


def test_cas_update_without_owner_fences_on_stage_only():
    db, h = _db(update_returns=[])
    assert sj.cas_update(SPEC, db, "r1", {"x": 1}, stage="saving") is False
    h.update.assert_called_once_with({"x": 1}, filters={"id": "eq.r1", "stage": "eq.saving"})


def test_claim_from_queued_and_takeover_from_the_previous_owner():
    db, h = _db()
    assert sj.claim(SPEC, db, {"id": "r1", "stage": "queued"}, to_stage="running", owner="w#2")
    h.update.assert_called_with({"stage": "running", "meta": {"owner": "w#2"}},
                                filters={"id": "eq.r1", "stage": "eq.queued"})
    sj.claim(SPEC, db, {"id": "r1", "stage": "running", "meta": {"owner": "w#1"}},
             to_stage="running", owner="w#2")
    h.update.assert_called_with({"stage": "running", "meta": {"owner": "w#2"}}, filters={
        "id": "eq.r1", "stage": "eq.running", "meta->>owner": "eq.w#1"})
    sj.claim(SPEC, db, {"id": "r1", "stage": "running", "meta": {}},
             to_stage="running", owner="w#2")
    assert h.update.call_args.kwargs["filters"]["meta->>owner"] == "is.null"


def test_enqueue_records_the_job_id_best_effort():
    db, h = _db()
    with patch.object(sj.jobs, "enqueue", return_value={"id": "j1"}) as enq:
        assert sj.enqueue(SPEC, db, "r1", {"thing_id": "r1"}) == "j1"
    enq.assert_called_once_with("thing.run", {"thing_id": "r1"}, dedupe_key="thing.run:r1")
    h.update.assert_called_once_with({"job_id": "j1"}, filters={"id": "eq.r1"},
                                     prefer_return_minimal=True)
    h.update.side_effect = RuntimeError("blip")
    with patch.object(sj.jobs, "enqueue", return_value={"id": "j2"}):
        assert sj.enqueue(SPEC, db, "r1", {}) == "j2"  # the write failing is not fatal


def test_job_row_by_id_else_by_dedupe_key():
    db, h = _db(select_returns=[{"status": "queued"}])
    assert sj.job_row(SPEC, db, "r1", "j1") == {"status": "queued"}
    h.select.assert_called_with("status", filters={"id": "eq.j1"}, limit=1)
    sj.job_row(SPEC, db, "r1", None, "status,locked_at")
    h.select.assert_called_with("status,locked_at", filters={"dedupe_key": "eq.thing.run:r1"},
                                order="created_at.desc", limit=1)


def test_enqueue_or_take_back():
    ok = MagicMock()
    assert sj.enqueue_or_take_back(SPEC, "r1", enqueue_fn=ok, take_back_fn=MagicMock(),
                                   token="t") is False
    boom = MagicMock(side_effect=RuntimeError("down"))
    back = MagicMock(return_value=True)
    assert sj.enqueue_or_take_back(SPEC, "r1", enqueue_fn=boom, take_back_fn=back, token="t")
    back.assert_called_once_with("r1", "t")
    for lost in (MagicMock(return_value=False), MagicMock(side_effect=RuntimeError("blip"))):
        assert sj.enqueue_or_take_back(SPEC, "r1", enqueue_fn=boom, take_back_fn=lost,
                                       token="t") is False


# ── the watch loop, under both drivers ──────────────────────────────────────


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _plan(**kw):
    base = dict(spec=SPEC, row_id="r1", token="tok", ends=frozenset({"done", "failed"}),
                running=frozenset({"running"}), grace=5.0, max_wait=100.0, poll=1.0,
                job_check_every=3, max_errors=3)
    return sj.WatchPlan(**{**base, **kw})


def _io(rows, **kw):
    seq = list(rows)

    def read():
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(item, Exception):
            raise item
        return item

    base = dict(read=read, take_back=MagicMock(return_value=False),
                job_dead=MagicMock(return_value=False), fail_dead=MagicMock())
    return sj.WatchIO(**{**base, **kw})


def _sync(rows, plan=None, **io_kw):
    clock = _Clock()
    io = _io(rows, **io_kw)
    return sj.run_watch(plan or _plan(), io, sleep=clock.sleep, clock=clock), io


def _async(rows, plan=None, **io_kw):
    clock = _Clock()
    io = _io(rows, **io_kw)

    real_sleep = asyncio.sleep

    async def _tick(s):
        clock.sleep(s)
        await real_sleep(0)

    async def _collect():
        out = []
        with patch.object(sj.asyncio, "sleep", new=_tick):
            async for item in sj.awatch(plan or _plan(), io, clock=clock):
                out.append(item)
        return out

    return asyncio.run(_collect()), io


def test_sync_driver_ends_on_a_terminal_stage():
    end, _ = _sync([{"stage": "queued"}, {"stage": "running"}, {"stage": "done"}])
    assert end.kind == sj.END and end.row["stage"] == "done"


def test_async_driver_emits_each_new_stage_once_then_the_end():
    items, _ = _async([{"stage": "queued"}, {"stage": "running"}, {"stage": "running"},
                       {"stage": "saving"}, {"stage": "done"}])
    assert [(i.kind, i.row["stage"]) for i in items] == [
        (sj.PROGRESS, "queued"), (sj.PROGRESS, "running"), (sj.PROGRESS, "saving"),
        (sj.END, "done")]


@pytest.mark.parametrize("drive", [_sync, _async])
def test_takes_back_a_queued_row_past_the_grace(drive):
    out, io = drive([{"stage": "queued", "id": "r1"}],
                    take_back=MagicMock(return_value=True))
    end = out if isinstance(out, sj.WatchEnd) else out[-1]
    assert end.kind == sj.TOOK_BACK and end.row["stage"] == "inline"
    io.take_back.assert_called_once_with()


def test_recognises_its_own_take_back_and_waits_on_anothers():
    end, _ = _sync([{"stage": "inline", "meta": {"inline_owner": "tok"}}])
    assert end.kind == sj.TOOK_BACK
    other = {"stage": "inline", "meta": {"inline_owner": "other"}}
    end, _ = _sync([other] * 3 + [{"stage": "failed"}])
    assert end.kind == sj.END and end.row["stage"] == "failed"


def test_adopts_another_requests_outcome_through_the_hook():
    other = {"stage": "inline", "meta": {"inline_owner": "other"}}
    adopt = MagicMock(side_effect=[None, {"stage": "done", "adopted": True}])
    end, _ = _sync([other], adopt=adopt)
    assert end.kind == sj.ADOPTED and end.row["adopted"] is True
    assert adopt.call_count == 2


def test_fails_a_running_row_whose_job_died():
    running = {"stage": "running", "job_id": "j1"}
    fail = MagicMock()
    end, _ = _sync([running] * 3 + [{"stage": "failed"}],
                   job_dead=MagicMock(return_value=True), fail_dead=fail)
    fail.assert_called_once_with(running)
    assert end.kind == sj.END


def test_ends_pending_at_the_max_wait_and_gone_on_a_vanished_row():
    end, _ = _sync([{"stage": "running"}], plan=_plan(max_wait=10))
    assert end.kind == sj.PENDING
    end, _ = _sync([None])
    assert end.kind == sj.GONE


@pytest.mark.parametrize("drive", [_sync, _async])
def test_consecutive_errors_end_in_timeout_and_a_good_poll_resets_them(drive):
    blip = RuntimeError("blip")
    out, _ = drive([blip])
    end = out if isinstance(out, sj.WatchEnd) else out[-1]
    assert end.kind == sj.TIMEOUT and end.row is None
    out, _ = drive([blip, blip, {"stage": "running"}] * 3 + [{"stage": "done"}])
    end = out if isinstance(out, sj.WatchEnd) else out[-1]
    assert end.kind == sj.END


def test_an_error_in_any_step_counts_as_a_blip():
    running = {"stage": "running", "job_id": "j1"}
    job_dead = MagicMock(side_effect=[RuntimeError("blip"), False, False, False])
    end, _ = _sync([running] * 12 + [{"stage": "done"}], job_dead=job_dead)
    assert end.kind == sj.END
