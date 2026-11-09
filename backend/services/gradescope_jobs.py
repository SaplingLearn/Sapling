"""The Gradescope sync on the job queue (#116, plan phase 2).

With the `jobs_queue` flag on for the student, POST /api/gradescope/sync/{course}
no longer logs in to Gradescope, scrapes the course and writes the gradebook in
the request. The route resolves the link exactly as before, stages a row in
`gradescope_syncs` (20261108214227_gradescope_syncs.sql), enqueues a
``gradescope.sync`` job and waits (bounded) on that row; the worker
(`python -m worker`) runs the SAME sync body the inline route runs
(routes/gradescope.py::_run_linked_sync), which records the outcome on
`gradescope_credentials` (needs_reauth / last_attempt_at / last_sync_error /
last_synced_at) as it always has, and this module writes the counts or a fixed
error code on the staged row.

Outcomes are typed where they happen: the sync body returns a `SyncOutcome`
(counts, or one of the ERR_* codes) and `response_for_outcome` is the ONE
mapping from an outcome to the HTTP answer, used by the inline route, by a
request that runs a staged sync itself, and for an outcome read back off the
row. A code never comes from parsing an HTTP status or detail.

The request waits at most SYNC_MAX_WAIT_SECONDS for an outcome. A sync still
running past that is answered ``202 {"pending": true, ...}`` and keeps
running; the client polls GET /api/gradescope/sync/{course}/status (the
latest staged sync of that course: 202 while it runs, then exactly the answer
the POST would have given). A watch that cannot read the row (repeated
database errors) ends with the 504 "still running" answer, which the client
treats the same way.

The job payload is ``{"sync_id": ...}`` and nothing else: no password, no
cookie. The worker reads the encrypted credentials from the DB, as the inline
path does. The row holds ids, counts, fixed codes and opaque owner tokens
(`counts.owner` / `counts.inline_owner` while the sync is active) — never
Gradescope text, so a queued failure answers with its code's fixed message
where the inline route would echo Gradescope's own wording (login and fetch
errors); status and error code are the same either way.

Flag off (the default) nothing here runs: `should_queue` says no and the route
takes its unchanged inline path.

Falling back to inline, so turning the flag on never loses a sync:
  * staging fails (migration not applied, PostgREST down): plain inline;
  * the enqueue fails, or no worker takes the job within
    PICKUP_GRACE_SECONDS (none running, or a deep backlog): a watching request
    takes the sync back with a compare-and-swap ``queued -> inline`` carrying
    its own token (`counts.inline_owner`) and runs it itself. The worker does
    the same swap (``queued -> running``) when it starts, so exactly one of
    them runs it; the job, if claimed later, sees ``inline`` and is a no-op.

Two requests on one sync (a second click while the first is in flight
attaches to the same row): only the request holding the take-back token runs
the sync inline, and it records its outcome on the row (a CAS on ``inline`` +
its token). Every other watcher waits for that outcome and answers with it;
it never runs the sync a second time (no second login, no second
last_sync_* write).

Worker writes are fenced on an owner token (`counts.owner` = worker id + job
attempt): the claim records it, and the terminal write is a CAS on
``running`` + that token. A re-delivered job (its earlier attempt died or
outlived its lease; the worker's heartbeat keeps a LIVE run's lease) takes
the row over by swapping the previous token for its own, so a stale attempt's
late write is refused instead of overwriting the newer outcome. Before it
writes anything the worker re-reads the course link; a link that was removed
or re-pointed ends the sync as ``link_changed`` with nothing written.

An active row is abandoned — failed, so a new sync can start — only when its
job is not alive: no job (by the row's job_id, or the job's dedupe key), a
dead or finished job, or a running job whose lease ran out (no heartbeat). A
live queued/running sync is never failed by a new request.

Only the scrape moves. The BU SSO login (`/credentials/bu-sso`, the one path
that drives Chromium) stays in the request: it needs the student's BU password
and a live Duo tap, and the password is held in memory for that request only
and never persisted (BuSsoBody). Handing it to a worker would mean writing it
to the database.

Delivery is at least once: a re-run repeats the login + scrape, and the
gradebook upsert is keyed on (enrollment_id, gradescope_assignment_id), so a
second run updates what the first inserted.

This module and services/document_jobs.py (the queued upload) share the
staged-job machinery in services/staged_jobs.py (stage CAS, take-back,
owner-fenced claim and writes, liveness, the watch loop). The sync body itself
stays in routes/gradescope.py and is imported lazily: teammate PRs edit that
file.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from db.connection import table
from db.scope import runs_as_service
from services import jobs, staged_jobs
from services.feature_flags import flag_on

logger = logging.getLogger(__name__)

GRADESCOPE_SYNC_JOB = "gradescope.sync"

#: How long a staged sync may sit `queued` before the request takes it back
#: and runs it inline. Long enough for a polling worker (5 s by default) to
#: pick it up; short enough that "flag on, no worker" costs one wait.
PICKUP_GRACE_SECONDS = float(os.getenv("GRADESCOPE_JOB_PICKUP_GRACE_SECONDS", "30"))
#: Longest a request holds its threadpool thread watching a sync someone else
#: runs (the worker, or another request). Past it the answer is 202 pending
#: and the client polls the status route; the sync keeps running.
SYNC_MAX_WAIT_SECONDS = 60.0
POLL_INTERVAL_SECONDS = 1.0
#: Polls between reads of the job row (to notice a dead-lettered job).
_JOB_CHECK_EVERY = 10
#: Consecutive polls a watch may fail (PostgREST blips) before it gives up
#: with the 504 "still running" answer. Any successful poll resets the count.
_MAX_DB_ERRORS = 10
#: The worker's lease (worker/__main__.py reads the same variable). A running
#: job not heartbeated for this long belongs to a dead worker.
_LEASE_SECONDS = float(os.getenv("JOBS_LEASE_SECONDS", str(jobs.DEFAULT_LEASE_SECONDS)))
#: An `inline` row this old belongs to a request that died without recording
#: an outcome (a crash, a deploy); the status route reports it as abandoned.
INLINE_STALE_SECONDS = 900.0

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
INLINE = "inline"
ACTIVE = frozenset({QUEUED, RUNNING})
#: Stages the WORKER never runs from. For a watcher `inline` is not an end:
#: it means "a request runs it", and that request records done/failed.
TERMINAL = frozenset({DONE, FAILED, INLINE})
#: What a watch can end on besides a row stage.
PENDING = "pending"   # still running past the wait: 202
TIMEOUT = "timeout"   # the row could not be read: 504

#: error_code values (fixed codes; never an exception message).
ERR_NOT_CONNECTED = "not_connected"
ERR_AUTH = "auth_failed"
ERR_FETCH = "fetch_failed"
ERR_WRITE = "write_failed"
ERR_CREDS = "creds_unreadable"
ERR_CREDS_INCOMPLETE = "creds_incomplete"
ERR_LINK_CHANGED = "link_changed"
ERR_INTERNAL = "internal_error"
ERR_WORKER = "worker_failed"
ERR_ABANDONED = "abandoned"

COUNT_KEYS = ("inserted", "updated", "skipped", "failed")

_STATUS_COLUMNS = "id,stage,error_code,counts,job_id,updated_at"
#: The staged-job machinery (services/staged_jobs.py): the owner tokens live
#: in the plaintext `counts` while a sync is active (opaque ids, never
#: content) — the worker attempt running it (`owner`), and the request that
#: took it back to run inline (`inline_owner`).
SPEC = staged_jobs.Spec(table="gradescope_syncs", job_type=GRADESCOPE_SYNC_JOB,
                        owner_column="counts", label="gradescope sync")


def _routes():
    from routes import gradescope  # lazy: see the module docstring

    return gradescope


_age_seconds = staged_jobs.age_seconds


def _token_of(row: dict | None, key: str) -> str | None:
    return staged_jobs.token_in(row, SPEC.owner_column, key)


# ── outcomes: one type, one mapping to the HTTP answer ──────────────────────


@dataclass(frozen=True)
class SyncOutcome:
    """What one run of the sync body came to: the counts, or a fixed code.

    Classified where it happens (routes/gradescope.py::_run_linked_sync and
    the worker's own checks), never parsed back out of an HTTP response.
    `message` is the inline answer's wording when it carries Gradescope's own
    text (a rejected login, a failed fetch); it is never stored, so an
    outcome read back off the row answers with the code's fixed message."""

    error_code: str | None = None
    counts: dict | None = None
    message: str | None = None

    @classmethod
    def done(cls, *, inserted: int, updated: int, skipped: int, failed: int) -> "SyncOutcome":
        return cls(counts={"inserted": inserted, "updated": updated,
                           "skipped": skipped, "failed": failed})

    @classmethod
    def failed(cls, code: str, message: str | None = None) -> "SyncOutcome":
        return cls(error_code=code, message=message)

    @classmethod
    def from_row(cls, row: dict) -> "SyncOutcome":
        if row.get("stage") == DONE:
            counts = row.get("counts") if isinstance(row.get("counts"), dict) else {}
            return cls.done(**{k: int(counts.get(k) or 0) for k in COUNT_KEYS})
        return cls.failed(row.get("error_code") or ERR_WORKER)

    def row_fields(self) -> dict:
        """The terminal columns for the staged row (owner tokens dropped)."""
        if self.error_code is None:
            counts = self.counts or {}
            return {"stage": DONE, "error_code": None,
                    "counts": {k: int(counts.get(k) or 0) for k in COUNT_KEYS}}
        return {"stage": FAILED, "error_code": self.error_code, "counts": None}


_REAUTH_MESSAGE = "Gradescope rejected the saved credentials. Reconnect Gradescope."
_FETCH_MESSAGE = "Couldn't reach Gradescope. Please retry shortly."
_CREDS_MESSAGE = "Stored credentials could not be read."
_CREDS_INCOMPLETE_MESSAGE = "Password-mode creds missing email/password"
#: The sync route's own answer for a course with no Gradescope link (pinned
#: equal to the literal in routes/gradescope.py::sync_course by a test).
NO_LINK_MESSAGE = "No Gradescope course is linked to this Sapling course"
#: What main.py's unhandled-exception handler answers for an inline crash.
_INTERNAL_MESSAGE = "Internal server error."
_FAILED_MESSAGE = "Gradescope sync failed. Please retry."
TIMEOUT_MESSAGE = (
    "This Gradescope sync is taking longer than usual. It will keep running; "
    "check back in a minute."
)


def response_for_outcome(outcome: SyncOutcome):
    """The sync route's answer for an outcome: the counts JSON, the typed
    JSONResponse (404 not connected / 409 reauth), or the HTTPException the
    inline route raises. The inline route (flag off) answers through this
    too, so the two paths cannot drift."""
    from fastapi import HTTPException

    gsr = _routes()
    code = outcome.error_code
    if code is None:
        counts = outcome.counts or {}
        return gsr.SyncResult(**{k: int(counts.get(k) or 0) for k in COUNT_KEYS}).model_dump()
    if code == ERR_NOT_CONNECTED:
        return gsr._not_connected()
    if code == ERR_AUTH:
        return gsr._gs_error(409, gsr.GS_REAUTH_REQUIRED, outcome.message or _REAUTH_MESSAGE)
    if code == ERR_FETCH:
        detail = outcome.message if outcome.message is not None else _FETCH_MESSAGE
        raise HTTPException(status_code=502, detail=detail)
    if code == ERR_WRITE:
        raise HTTPException(status_code=502, detail=gsr.SYNC_WRITE_FAILED_DETAIL)
    if code == ERR_CREDS:
        raise HTTPException(status_code=500, detail=_CREDS_MESSAGE)
    if code == ERR_CREDS_INCOMPLETE:
        raise HTTPException(status_code=500, detail=_CREDS_INCOMPLETE_MESSAGE)
    if code == ERR_LINK_CHANGED:
        raise HTTPException(status_code=400, detail=NO_LINK_MESSAGE)
    if code == ERR_INTERNAL:
        raise HTTPException(status_code=500, detail=_INTERNAL_MESSAGE)
    raise HTTPException(status_code=502, detail=_FAILED_MESSAGE)


def pending_response(row: dict):
    """202: the sync is still running; poll the status route."""
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=202, content={
        "pending": True, "sync_id": str(row.get("id") or ""),
        "stage": row.get("stage") or QUEUED, "detail": TIMEOUT_MESSAGE,
    })


# ── request side: decide, stage, enqueue ────────────────────────────────────


def should_queue(user_id: str) -> bool:
    """Whether this sync goes through the queue: `jobs_queue` on for the
    student. Never raises (a flag-store error reads as off, the inline path)."""
    try:
        return flag_on(jobs.JOBS_QUEUE_FLAG, user_id)
    except Exception:
        logger.warning("jobs_queue flag check failed; syncing Gradescope inline", exc_info=True)
        return False


#: `fresh`: this call created the row and must enqueue its job; False when it
#: attached to a sync of the same course already in flight.
Staged = staged_jobs.Staged


def _active_row(user_id: str, enrollment_id: str) -> dict | None:
    rows = table("gradescope_syncs").select(
        "id,stage,job_id,updated_at",
        filters={
            "user_id": f"eq.{user_id}",
            "enrollment_id": f"eq.{enrollment_id}",
            "stage": f"in.({','.join(sorted(ACTIVE))})",
        },
        limit=1,
    )
    return rows[0] if isinstance(rows, list) and rows else None


def _job_row(sync_id: str, job_id: str | None) -> dict | None:
    """The sync's `gradescope.sync` job: by the id recorded on the row, or —
    when that best-effort write never landed — by its dedupe key (newest)."""
    return staged_jobs.job_row(SPEC, table, sync_id, job_id, "status,locked_at")


def _job_alive(job: dict | None) -> bool:
    """Whether a job will still run (or is running) the sync: waiting to be
    claimed or retried, or running under a lease its worker still renews."""
    return staged_jobs.job_alive(job, lease_seconds=_LEASE_SECONDS)


def _abandoned(row: dict) -> bool:
    """Whether an active sync is abandoned — nothing will ever finish it — so
    a new sync may fail it and start over. Judged by its JOB, never by the
    row's age alone:

    * ``queued`` past the pickup grace with no live job: the request that
      staged it died before enqueueing (or its job is gone);
    * ``running`` whose job is not alive: dead, finished without recording
      (a refused write), missing, or running under an expired lease.

    A lookup error reads as "alive" (attach): a live sync is never failed."""
    stage = row.get("stage")
    try:
        if stage == QUEUED:
            age = _age_seconds(row.get("updated_at"))
            if age is None or age <= PICKUP_GRACE_SECONDS:
                return False
        elif stage != RUNNING:
            return False
        return not _job_alive(_job_row(str(row["id"]), row.get("job_id")))
    except Exception:
        logger.warning("gradescope sync %s: liveness check failed; attaching", row.get("id"),
                       exc_info=True)
        return False


@runs_as_service  # #116: gradescope_syncs is service-only (bucket E)
def stage_sync(
    *, user_id: str, enrollment_id: str, link_id: str | None, gradescope_course_id: str,
) -> Staged:
    """Stage a sync for the worker. One active sync per (user, enrollment):

    * none in flight -> insert one, ``fresh``;
    * one queued/running -> attach to it (``fresh`` False): a second click
      waits on the first sync instead of starting another login + scrape;
    * one in flight but abandoned (`_abandoned`: its job is not alive) ->
      fail it (a CAS on the stage and `updated_at` it was judged at) and
      insert a new one.

    Raises on a database error; the caller falls back to inline.
    """
    row = {
        "user_id": user_id,
        "enrollment_id": enrollment_id,
        "link_id": link_id,
        "gradescope_course_id": gradescope_course_id,
        "stage": QUEUED,
    }
    for attempt in range(2):
        try:
            rows = table("gradescope_syncs").insert(row)
            return Staged(id=str(rows[0]["id"]), fresh=True)
        except Exception:
            # The partial unique index: a sync of this course is in flight.
            existing = _active_row(user_id, enrollment_id)
            if existing is None:
                if attempt == 0:
                    continue  # it ended between the insert and the read: retry
                raise
        if not _abandoned(existing):
            return Staged(id=str(existing["id"]), fresh=False)
        logger.warning("gradescope.sync: abandoned %s sync %s (job not alive); starting a new one",
                       existing.get("stage"), existing["id"])
        filters = {"id": f"eq.{existing['id']}", "stage": f"eq.{existing['stage']}"}
        if existing.get("updated_at"):
            filters["updated_at"] = f"eq.{existing['updated_at']}"
        table("gradescope_syncs").update(
            {"stage": FAILED, "error_code": ERR_ABANDONED, "counts": None}, filters=filters,
        )
    raise RuntimeError("gradescope.sync: could not stage a sync")


@runs_as_service  # #116: jobs + gradescope_syncs are service-only
def enqueue_sync(sync_id: str) -> str | None:
    """Enqueue the worker's job for a staged sync. Raises on failure.

    The payload is the row id only (never credentials). The dedupe key is per
    staged sync: `stage_sync` already collapses repeat syncs of one course into
    one row, and a per-student key would merge two different courses' syncs
    into one job.
    """
    return staged_jobs.enqueue(SPEC, table, sync_id, {"sync_id": sync_id})


@runs_as_service
def take_back(sync_id: str, token: str) -> bool:
    """queued -> inline, for the request holding `token` to run the sync
    itself (recorded as `counts.inline_owner`). False when a worker already
    started it, another request took it, or it ended."""
    return staged_jobs.take_back(SPEC, table, sync_id, token)


@runs_as_service
def finish_inline(sync_id: str, token: str, outcome: SyncOutcome) -> bool:
    """Record an inline run's outcome on the row it took back, only while the
    row is still this request's (`inline` + its token). Never raises: the
    request already has its answer; a watcher that misses it ends pending."""
    return staged_jobs.finish_inline(SPEC, table, sync_id, token, outcome.row_fields())


@runs_as_service
def read_status(sync_id: str) -> dict | None:
    rows = table("gradescope_syncs").select(
        _STATUS_COLUMNS, filters={"id": f"eq.{sync_id}"}, limit=1,
    )
    return rows[0] if isinstance(rows, list) and rows else None


@runs_as_service
def latest_sync(user_id: str, enrollment_ids: list[str]) -> dict | None:
    """The student's most recent staged sync among these enrollments (the
    status route's read)."""
    if not enrollment_ids:
        return None
    rows = table("gradescope_syncs").select(
        _STATUS_COLUMNS,
        filters={"user_id": f"eq.{user_id}",
                 "enrollment_id": f"in.({','.join(enrollment_ids)})"},
        order="created_at.desc", limit=1,
    )
    return rows[0] if isinstance(rows, list) and rows else None


@runs_as_service
def job_status(sync_id: str, job_id: str | None = None) -> str | None:
    job = _job_row(sync_id, job_id)
    return job.get("status") if job else None


@runs_as_service
def fail_if_running(sync_id: str, owner: str | None, code: str) -> bool:
    """Record a terminal failure the worker could not (its job dead-lettered
    mid-run). Conditional on the row still running under the owner the
    caller saw."""
    return staged_jobs.cas_update(
        SPEC, table, sync_id, {"stage": FAILED, "error_code": code, "counts": None},
        stage=RUNNING, owner=owner,
    )


# ── request side: wait ──────────────────────────────────────────────────────


@dataclass
class Watch:
    """What a wait ended on. ``kind``: done | failed | inline (this request
    holds the take-back and runs it) | pending (past the wait) | timeout (the
    row could not be read)."""

    kind: str = ""
    row: dict | None = None


def wait_for_sync(
    sync_id: str, *, token: str, max_wait: float | None = None, grace: float | None = None,
    poll: float | None = None, sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> Watch:
    """Poll the staged sync until it is done/failed, THIS request takes it
    back (``inline`` with `token`: run it), or `max_wait` (``pending``).

    An ``inline`` row another request took back is not an end: that request
    records its outcome on the row, and this watch answers with it. A
    transient database error on any read or swap is retried on the next poll;
    only `_MAX_DB_ERRORS` in a row end the watch (``timeout``). Blocking: the
    sync route is a plain `def` and runs in FastAPI's threadpool."""
    plan = staged_jobs.WatchPlan(
        spec=SPEC, row_id=sync_id, token=token, ends=frozenset({DONE, FAILED}),
        running=frozenset({RUNNING}),
        grace=PICKUP_GRACE_SECONDS if grace is None else grace,
        max_wait=SYNC_MAX_WAIT_SECONDS if max_wait is None else max_wait,
        poll=POLL_INTERVAL_SECONDS if poll is None else poll,
        job_check_every=_JOB_CHECK_EVERY, max_errors=_MAX_DB_ERRORS,
    )
    io = staged_jobs.WatchIO(
        read=lambda: read_status(sync_id),
        take_back=lambda: take_back(sync_id, token),
        job_dead=lambda row: job_status(sync_id, row.get("job_id")) == "dead",
        fail_dead=lambda row: fail_if_running(sync_id, _token_of(row, "owner"), ERR_WORKER),
    )
    end = staged_jobs.run_watch(plan, io, sleep=sleep or time.sleep,
                                clock=clock or time.monotonic)
    if end.kind == staged_jobs.GONE:  # deleted under us (enrollment or account removed)
        return Watch(FAILED, {"id": sync_id, "stage": FAILED, "error_code": ERR_WORKER})
    if end.kind == staged_jobs.TOOK_BACK:
        return Watch(INLINE, end.row)
    if end.kind == staged_jobs.END:
        return Watch(end.row["stage"], end.row)
    return Watch(PENDING if end.kind == staged_jobs.PENDING else TIMEOUT, end.row)


def response_for(watch: Watch):
    """The route's answer for how a watch ended (not ``inline``)."""
    from fastapi import HTTPException

    row = watch.row or {}
    if watch.kind in (DONE, FAILED):
        return response_for_outcome(SyncOutcome.from_row(row))
    if watch.kind == PENDING:
        return pending_response(row)
    raise HTTPException(status_code=504, detail=TIMEOUT_MESSAGE)


def _run_inline(sync_id: str, token: str, *, user_id: str, enrollment_id: str,
                link_id: str | None, gradescope_course_id: str):
    """Run a sync this request took back, record the outcome on the row for
    any other watcher, and answer with that recorded outcome — so every
    request watching one staged sync gets the same answer (by code: the row
    keeps no Gradescope text)."""
    gsr = _routes()
    try:
        outcome = gsr._run_linked_sync(
            user_id, gradescope_course_id, enrollment_id, link_id,
            still_linked=lambda: link_unchanged(link_id, gradescope_course_id, enrollment_id),
        )
    except BaseException:
        finish_inline(sync_id, token, SyncOutcome.failed(ERR_INTERNAL))
        raise  # answered by main.py's handler: the same 500 an inline crash gets
    finish_inline(sync_id, token, outcome)
    return response_for_outcome(SyncOutcome.from_row(outcome.row_fields()))


def sync_via_queue(*, user_id: str, enrollment_id: str, link_id: str | None,
                   gradescope_course_id: str):
    """POST /sync through the queue. Returns what the route returns (or
    raises the HTTPException it would raise), or None when staging failed and
    the caller must sync inline itself (nothing staged)."""
    kwargs = dict(user_id=user_id, enrollment_id=enrollment_id, link_id=link_id,
                  gradescope_course_id=gradescope_course_id)
    try:
        staged = stage_sync(**kwargs)
    except Exception:
        logger.warning("gradescope sync staging failed; syncing inline", exc_info=True)
        return None
    token = uuid.uuid4().hex
    if staged.fresh and staged_jobs.enqueue_or_take_back(
        SPEC, staged.id, enqueue_fn=enqueue_sync, take_back_fn=take_back, token=token,
    ):
        return _run_inline(staged.id, token, **kwargs)  # ours to run now
    watch = wait_for_sync(staged.id, token=token)
    if watch.kind == INLINE:
        return _run_inline(staged.id, token, **kwargs)
    return response_for(watch)


def status_response(row: dict | None):
    """GET /sync/{course}/status: the latest staged sync as the POST would
    have answered it, 202 while it runs, None when there is none (404)."""
    if row is None:
        return None
    stage = row.get("stage")
    if stage in (DONE, FAILED):
        return response_for_outcome(SyncOutcome.from_row(row))
    if stage == INLINE:
        age = _age_seconds(row.get("updated_at"))
        if age is not None and age > INLINE_STALE_SECONDS:
            # The request running it died without recording an outcome.
            return response_for_outcome(SyncOutcome.failed(ERR_ABANDONED))
    return pending_response(row)


# ── worker side ─────────────────────────────────────────────────────────────


def link_unchanged(link_id: str | None, gradescope_course_id: str, enrollment_id: str) -> bool:
    """Whether the course link the sync was staged from still exists and still
    points at the same Gradescope course and enrollment. Raises on a
    database error (nothing is written on a raise either)."""
    if not link_id:
        return True  # nothing to compare against (not staged from a link row)
    rows = table("gradescope_course_links").select(
        "gradescope_course_id,enrollment_id", filters={"id": f"eq.{link_id}"}, limit=1,
    )
    link = rows[0] if isinstance(rows, list) and rows else None
    return bool(link) and (
        str(link.get("gradescope_course_id")) == str(gradescope_course_id)
        and str(link.get("enrollment_id")) == str(enrollment_id)
    )


@jobs.job_handler(GRADESCOPE_SYNC_JOB)
def _run_gradescope_sync_job(payload: dict) -> None:
    """Worker side: the inline sync body, then its outcome on the staged row.

    A sync outcome (rejected credentials, Gradescope down, nothing saved, the
    link gone) is RECORDED and the job completes: the student retries, it is
    not retried behind their back. Only an unreadable/unwritable staged row
    raises, so the queue retries that."""
    sync_id = (payload or {}).get("sync_id")
    if not isinstance(sync_id, str) or not sync_id:
        raise jobs.PermanentJobError("gradescope.sync: payload has no sync_id")
    rows = table("gradescope_syncs").select(
        "id,user_id,enrollment_id,link_id,gradescope_course_id,stage,counts",
        filters={"id": f"eq.{sync_id}"}, limit=1,
    )
    row = rows[0] if isinstance(rows, list) and rows else None
    if row is None:
        logger.info("gradescope.sync: sync %s is gone (enrollment or account deleted?)", sync_id)
        return
    stage = row.get("stage")
    if stage in TERMINAL:
        return  # the request ran it inline, or an earlier attempt finished it
    owner = staged_jobs.owner_token(jobs.current_job())
    # queued -> running; or a re-delivery: the attempt that moved it to
    # `running` died or outlived its lease (the heartbeat keeps a live run's
    # lease). Take it over from that attempt's token, so its late write is
    # refused.
    if not staged_jobs.claim(SPEC, table, row, to_stage=RUNNING, owner=owner):
        return  # the request took it back, or another attempt moved it, first
    if stage != QUEUED:
        logger.warning("gradescope.sync: sync %s taken over from stage %s (owner %s)",
                       sync_id, stage, _token_of(row, "owner"))
    # #119: the sync is the student's work: anything it attributes or
    # budgets (llm_usage rows, the per-user LLM budget) sees them, as on the
    # inline path. Reset on exit so the worker's next job never inherits it.
    from services.request_context import acting_for

    with acting_for(row.get("user_id")):
        outcome = _worker_outcome(row)
    if not staged_jobs.cas_update(SPEC, table, sync_id, outcome.row_fields(),
                                  stage=RUNNING, owner=owner):
        logger.info("gradescope.sync: sync %s moved on under this attempt; not recording %s",
                    sync_id, outcome.error_code or DONE)


def _worker_outcome(row: dict) -> SyncOutcome:
    """Run the inline sync body for the staged row. The link is checked
    before the login (no point scraping for a link that is gone) and again
    right before the first write (`still_linked`)."""
    gsr = _routes()
    link_id, gs_course, enrollment = (
        row.get("link_id"), row["gradescope_course_id"], row["enrollment_id"])

    def _still_linked() -> bool:
        return link_unchanged(link_id, gs_course, enrollment)

    try:
        if not _still_linked():
            return SyncOutcome.failed(ERR_LINK_CHANGED)
        return gsr._run_linked_sync(row["user_id"], gs_course, enrollment, link_id,
                                    still_linked=_still_linked)
    except Exception:
        logger.exception("gradescope.sync: sync %s raised", row["id"])
        return SyncOutcome.failed(ERR_INTERNAL)
