"""The Gradescope sync on the job queue (#116, plan phase 2).

With the `jobs_queue` flag on for the student, POST /api/gradescope/sync/{course}
no longer logs in to Gradescope, scrapes the course and writes the gradebook in
the request. The route resolves the link exactly as before, stages a row in
`gradescope_syncs` (20261108214227_gradescope_syncs.sql), enqueues a
``gradescope.sync`` job and waits (bounded) on that row; the worker
(`python -m worker`) runs the SAME sync body the inline route runs
(routes/gradescope.py::_sync_linked_course), which records the outcome on
`gradescope_credentials` (needs_reauth / last_attempt_at / last_sync_error /
last_synced_at) as it always has, and this module writes the counts or a fixed
error code on the staged row. The route answers from that with the inline
route's JSON and status codes, so the frontend (GradescopeSyncModal) needs no
change.

The job payload is ``{"sync_id": ...}`` and nothing else: no password, no
cookie. The worker reads the encrypted credentials from the DB, as the inline
path does.

Flag off (the default) nothing here runs: `should_queue` says no and the route
takes its unchanged inline path.

Falling back to inline, so turning the flag on never loses a sync:
  * the stage or the enqueue fails (migration not applied, PostgREST down);
  * no worker takes the job within PICKUP_GRACE_SECONDS (none running, or a
    deep backlog): the request takes the sync back with a compare-and-swap on
    ``stage`` (queued -> inline) and runs it itself. The worker does the same
    swap (queued -> running) when it starts, so exactly one of the two runs
    it; the job, if it is claimed later, sees ``inline`` and completes as a
    no-op.

Only the scrape moves. The BU SSO login (`/credentials/bu-sso`, the one path
that drives Chromium) stays in the request: it needs the student's BU password
and a live Duo tap, and the password is held in memory for that request only
and never persisted (BuSsoBody). Handing it to a worker would mean writing it
to the database.

Delivery is at least once: a re-run repeats the login + scrape, and the
gradebook upsert is keyed on (enrollment_id, gradescope_assignment_id), so a
second run updates what the first inserted.

This module mirrors services/document_jobs.py (the queued upload), so the two
read as one design. The sync body itself stays in routes/gradescope.py and is
imported lazily: teammate PRs edit that file.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from db.connection import table
from db.scope import runs_as_service
from services import jobs
from services.feature_flags import flag_on

logger = logging.getLogger(__name__)

GRADESCOPE_SYNC_JOB = "gradescope.sync"

#: How long a staged sync may sit `queued` before the request takes it back
#: and runs it inline. Long enough for a polling worker (5 s by default) to
#: pick it up; short enough that "flag on, no worker" costs one wait.
PICKUP_GRACE_SECONDS = float(os.getenv("GRADESCOPE_JOB_PICKUP_GRACE_SECONDS", "30"))
#: Longest the request waits for a claimed sync. A sync past it still finishes
#: in the worker and records its outcome on gradescope_credentials and the
#: link; the client is told to check back.
SYNC_MAX_WAIT_SECONDS = 180.0
POLL_INTERVAL_SECONDS = 1.0
#: Polls between reads of the job row (to notice a dead-lettered job).
_JOB_CHECK_EVERY = 10
#: An active (queued/running) row older than this is abandoned (its job is
#: gone or dead with nobody watching); a new sync fails it and starts over
#: instead of attaching to it forever.
ACTIVE_STALE_SECONDS = 900

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
INLINE = "inline"
ACTIVE = frozenset({QUEUED, RUNNING})
TERMINAL = frozenset({DONE, FAILED, INLINE})

#: error_code values (fixed codes; never an exception message).
ERR_NOT_CONNECTED = "not_connected"
ERR_AUTH = "auth_failed"
ERR_FETCH = "fetch_failed"
ERR_WRITE = "write_failed"
ERR_CREDS = "creds_unreadable"
ERR_WORKER = "worker_failed"

COUNT_KEYS = ("inserted", "updated", "skipped", "failed")

_STATUS_COLUMNS = "id,stage,error_code,counts,job_id"


def _routes():
    from routes import gradescope  # lazy: see the module docstring

    return gradescope


# ── request side: decide, stage, enqueue ────────────────────────────────────


def should_queue(user_id: str) -> bool:
    """Whether this sync goes through the queue: `jobs_queue` on for the
    student. Never raises (a flag-store error reads as off, the inline path)."""
    try:
        return flag_on(jobs.JOBS_QUEUE_FLAG, user_id)
    except Exception:
        logger.warning("jobs_queue flag check failed; syncing Gradescope inline", exc_info=True)
        return False


@dataclass
class Staged:
    id: str
    #: True when this call created the row and must enqueue its job; False
    #: when it attached to a sync of the same course already in flight.
    fresh: bool


def _active_row(user_id: str, enrollment_id: str) -> dict | None:
    rows = table("gradescope_syncs").select(
        "id,stage,created_at",
        filters={
            "user_id": f"eq.{user_id}",
            "enrollment_id": f"eq.{enrollment_id}",
            "stage": f"in.({QUEUED},{RUNNING})",
        },
        limit=1,
    )
    return rows[0] if isinstance(rows, list) and rows else None


def _is_stale(row: dict, now: datetime | None = None) -> bool:
    raw = row.get("created_at")
    if not raw:
        return False
    try:
        created = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return now - created > timedelta(seconds=ACTIVE_STALE_SECONDS)


@runs_as_service  # #116: gradescope_syncs is service-only (bucket E)
def stage_sync(
    *, user_id: str, enrollment_id: str, link_id: str | None, gradescope_course_id: str,
) -> Staged:
    """Stage a sync for the worker. One active sync per (user, enrollment):

    * none in flight -> insert one, ``fresh``;
    * one queued/running -> attach to it (``fresh`` False): a second click
      waits on the first sync instead of starting another login + scrape;
    * one in flight but abandoned (older than ACTIVE_STALE_SECONDS) -> fail
      it and insert a new one.

    Raises on a database error; the caller falls back to inline.
    """
    row = {
        "user_id": user_id,
        "enrollment_id": enrollment_id,
        "link_id": link_id,
        "gradescope_course_id": gradescope_course_id,
        "stage": QUEUED,
    }
    for _ in range(2):
        try:
            rows = table("gradescope_syncs").insert(row)
            return Staged(id=str(rows[0]["id"]), fresh=True)
        except Exception:
            # The partial unique index: a sync of this course is in flight.
            existing = _active_row(user_id, enrollment_id)
            if existing is None:
                raise
        if not _is_stale(existing):
            return Staged(id=str(existing["id"]), fresh=False)
        logger.warning("gradescope.sync: abandoned %s sync %s; starting a new one",
                       existing.get("stage"), existing["id"])
        table("gradescope_syncs").update(
            {"stage": FAILED, "error_code": ERR_WORKER},
            filters={"id": f"eq.{existing['id']}", "stage": f"eq.{existing['stage']}"},
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
    out = jobs.enqueue(
        GRADESCOPE_SYNC_JOB, {"sync_id": sync_id},
        dedupe_key=f"{GRADESCOPE_SYNC_JOB}:{sync_id}",
    )
    job_id = out.get("id")
    if job_id:
        try:
            table("gradescope_syncs").update(
                {"job_id": job_id}, filters={"id": f"eq.{sync_id}"},
                prefer_return_minimal=True,
            )
        except Exception:
            # Only the dead-letter check needs it; the sync itself is fine.
            logger.warning("could not record job %s on gradescope sync %s", job_id, sync_id,
                           exc_info=True)
    return job_id


@runs_as_service
def take_back(sync_id: str) -> bool:
    """queued -> inline, for the request to run the sync itself. False when a
    worker already started it (or it already ended)."""
    won = table("gradescope_syncs").update(
        {"stage": INLINE},
        filters={"id": f"eq.{sync_id}", "stage": f"eq.{QUEUED}"},
    )
    return bool(won)


@runs_as_service
def read_status(sync_id: str) -> dict | None:
    rows = table("gradescope_syncs").select(
        _STATUS_COLUMNS, filters={"id": f"eq.{sync_id}"}, limit=1,
    )
    return rows[0] if isinstance(rows, list) and rows else None


@runs_as_service
def job_status(job_id: str) -> str | None:
    rows = table("jobs").select("status", filters={"id": f"eq.{job_id}"}, limit=1)
    return rows[0].get("status") if isinstance(rows, list) and rows else None


@runs_as_service
def fail_if_running(sync_id: str, code: str) -> bool:
    """Record a terminal failure the worker could not (its job dead-lettered
    mid-run). Conditional on the row still running."""
    won = table("gradescope_syncs").update(
        {"stage": FAILED, "error_code": code},
        filters={"id": f"eq.{sync_id}", "stage": f"eq.{RUNNING}"},
    )
    return bool(won)


def stage_and_enqueue(**kwargs: Any) -> str | None:
    """Stage the sync and make sure a job will run it. Returns the sync id, or
    None when either step failed (the caller runs inline)."""
    try:
        staged = stage_sync(**kwargs)
    except Exception:
        logger.warning("gradescope sync staging failed; syncing inline", exc_info=True)
        return None
    if not staged.fresh:
        return staged.id
    try:
        enqueue_sync(staged.id)
    except Exception:
        logger.warning("gradescope.sync enqueue failed for sync %s; syncing inline",
                       staged.id, exc_info=True)
        # Ours to run now. If the swap loses, a worker already has it after all.
        return None if take_back(staged.id) else staged.id
    return staged.id


# ── request side: wait ──────────────────────────────────────────────────────


@dataclass
class Watch:
    """What a wait ended on. ``kind``: done | failed | inline | timeout."""

    kind: str = ""
    row: dict | None = None


def wait_for_sync(
    sync_id: str, *, max_wait: float | None = None, grace: float | None = None,
    poll: float | None = None, sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> Watch:
    """Poll the staged sync until it is terminal, the request takes it back
    (``inline``), or `max_wait`. Blocking: the sync route is a plain `def`
    and runs in FastAPI's threadpool, the same thread the inline sync would
    have held for the login + scrape."""
    max_wait = SYNC_MAX_WAIT_SECONDS if max_wait is None else max_wait
    grace = PICKUP_GRACE_SECONDS if grace is None else grace
    poll = POLL_INTERVAL_SECONDS if poll is None else poll
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    started = clock()
    polls = 0
    while True:
        row = read_status(sync_id)
        if row is None:  # deleted under us (enrollment or account removed)
            return Watch(FAILED, {"id": sync_id, "stage": FAILED, "error_code": ERR_WORKER})
        stage = row.get("stage")
        elapsed = clock() - started
        if stage == QUEUED and elapsed >= grace:
            if take_back(sync_id):
                logger.info("gradescope sync %s: no worker took it in %.0fs; syncing inline",
                            sync_id, grace)
                return Watch(INLINE, {**row, "stage": INLINE})
            sleep(poll)  # a worker took it in the meantime: re-read
            continue
        if stage in TERMINAL:
            return Watch(stage, row)
        if elapsed >= max_wait:
            return Watch("timeout", row)
        polls += 1
        if stage == RUNNING and row.get("job_id") and polls % _JOB_CHECK_EVERY == 0:
            if job_status(row["job_id"]) == "dead":
                fail_if_running(sync_id, ERR_WORKER)
                continue
        sleep(poll)


TIMEOUT_MESSAGE = (
    "This Gradescope sync is taking longer than usual. It will keep running; "
    "check back in a minute."
)
_REAUTH_MESSAGE = "Gradescope rejected the saved credentials. Reconnect Gradescope."
_FETCH_MESSAGE = "Couldn't reach Gradescope. Please retry shortly."
_CREDS_MESSAGE = "Stored credentials could not be read."
_FAILED_MESSAGE = "Gradescope sync failed. Please retry."


def response_for(watch: Watch):
    """The inline route's answer for a finished queued sync: the counts JSON,
    the typed JSONResponse (404 not connected / 409 reauth), or the
    HTTPException it would have raised."""
    from fastapi import HTTPException

    gsr = _routes()
    row = watch.row or {}
    if watch.kind == DONE:
        counts = row.get("counts") or {}
        return gsr.SyncResult(**{k: int(counts.get(k) or 0) for k in COUNT_KEYS}).model_dump()
    if watch.kind == "timeout":
        raise HTTPException(status_code=504, detail=TIMEOUT_MESSAGE)
    code = row.get("error_code")
    if code == ERR_NOT_CONNECTED:
        return gsr._not_connected()
    if code == ERR_AUTH:
        return gsr._gs_error(409, gsr.GS_REAUTH_REQUIRED, _REAUTH_MESSAGE)
    if code == ERR_FETCH:
        raise HTTPException(status_code=502, detail=_FETCH_MESSAGE)
    if code == ERR_WRITE:
        raise HTTPException(status_code=502, detail=gsr.SYNC_WRITE_FAILED_DETAIL)
    if code == ERR_CREDS:
        raise HTTPException(status_code=500, detail=_CREDS_MESSAGE)
    raise HTTPException(status_code=502, detail=_FAILED_MESSAGE)


def sync_via_queue(**stage_kwargs: Any):
    """POST /sync through the queue. Returns what the route returns, None when
    the caller must sync inline, or raises the HTTPException the inline route
    would have raised for the same outcome."""
    sync_id = stage_and_enqueue(**stage_kwargs)
    if sync_id is None:
        return None
    watch = wait_for_sync(sync_id)
    if watch.kind == INLINE:
        return None
    return response_for(watch)


# ── worker side ─────────────────────────────────────────────────────────────


def _update(sync_id: str, data: dict, *, stage: str | None = None) -> bool:
    """Write the row; with `stage`, only while it is still in that stage."""
    filters = {"id": f"eq.{sync_id}"}
    if stage is not None:
        filters["stage"] = f"eq.{stage}"
    return bool(table("gradescope_syncs").update(data, filters=filters))


@jobs.job_handler(GRADESCOPE_SYNC_JOB)
def _run_gradescope_sync_job(payload: dict) -> None:
    """Worker side: the inline sync body, then its outcome on the staged row.

    A sync outcome (rejected credentials, Gradescope down, nothing saved) is
    RECORDED and the job completes: the student retries, it is not retried
    behind their back. Only an unreadable/unwritable staged row raises, so the
    queue retries that."""
    sync_id = (payload or {}).get("sync_id")
    if not isinstance(sync_id, str) or not sync_id:
        raise jobs.PermanentJobError("gradescope.sync: payload has no sync_id")
    rows = table("gradescope_syncs").select(
        "id,user_id,enrollment_id,link_id,gradescope_course_id,stage",
        filters={"id": f"eq.{sync_id}"}, limit=1,
    )
    row = rows[0] if isinstance(rows, list) and rows else None
    if row is None:
        logger.info("gradescope.sync: sync %s is gone (enrollment or account deleted?)", sync_id)
        return
    stage = row.get("stage")
    if stage in TERMINAL:
        return  # the request ran it inline, or an earlier attempt finished it
    if stage == QUEUED:
        if not _update(sync_id, {"stage": RUNNING}, stage=QUEUED):
            return  # the request took it back between our read and the swap
    else:
        # A re-delivery: the attempt that moved it to `running` died or
        # outlived its lease. Run it again; the upsert keys make that safe.
        logger.warning("gradescope.sync: sync %s re-run from stage %s", sync_id, stage)
    _update(sync_id, _outcome(row))


def _outcome(row: dict) -> dict:
    """Run the inline sync body for the staged row and turn what it returned
    or raised into the row's terminal columns."""
    from fastapi import HTTPException

    gsr = _routes()
    try:
        res = gsr._sync_linked_course(
            row["user_id"], row["gradescope_course_id"], row["enrollment_id"], row.get("link_id"),
        )
    except HTTPException as e:
        if e.status_code == 502 and e.detail == gsr.SYNC_WRITE_FAILED_DETAIL:
            code = ERR_WRITE
        elif e.status_code == 502:
            code = ERR_FETCH
        elif e.status_code == 500:
            code = ERR_CREDS
        else:
            code = ERR_WORKER
        return {"stage": FAILED, "error_code": code}
    except Exception:
        logger.exception("gradescope.sync: sync %s raised", row["id"])
        return {"stage": FAILED, "error_code": ERR_WORKER}
    if isinstance(res, dict):
        return {"stage": DONE, "error_code": None,
                "counts": {k: int(res.get(k) or 0) for k in COUNT_KEYS}}
    status = getattr(res, "status_code", None)
    code = {404: ERR_NOT_CONNECTED, 409: ERR_AUTH}.get(status, ERR_WORKER)
    return {"stage": FAILED, "error_code": code}
