"""Postgres job queue (#116): enqueue, claim, complete, fail, and the handler
registry the worker dispatches on.

The queue is the `jobs` table (20261108095241_jobs_queue.sql); every state
change is one SQL function reached through `db.connection.rpc`, so the claim
(FOR UPDATE SKIP LOCKED, lease re-offer, dead-lettering) lives in SQL and is
tested against real SQL in tests/integration/test_jobs_queue_db.py. This
module only shapes arguments, computes the retry backoff and keeps the
registry. No DBOS (ADR 0011 keeps it off, and the plan forbids running both),
no Redis.

Delivery is AT LEAST ONCE. A job whose worker dies, or that outlives its lease,
is offered again, so a handler must be safe to run twice. Payloads are plain
JSON in an unencrypted column: ids only, never student content.

Nothing runs a job unless `python -m worker` is running. Code that moves work
onto the queue does it behind the `jobs_queue` flag (default off), and with the
flag on and no worker the work waits in `jobs` until one starts.
"""
from __future__ import annotations

import logging
import random
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from db.connection import rpc
from db.scope import runs_as_service

logger = logging.getLogger("sapling.jobs")

#: The flag that moves work onto the queue (services/feature_flags.py).
JOBS_QUEUE_FLAG = "jobs_queue"

DEFAULT_MAX_ATTEMPTS = 5
#: A claim holds its job this long; past it the job is offered again. The
#: worker claims one job at a time, so a lease starts when its work does.
DEFAULT_LEASE_SECONDS = 300
#: Retry backoff: BASE * 2**(attempt - 1), capped, with equal jitter.
BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 3600
#: last_error is cut to this (the SQL side cuts again at 2000).
MAX_ERROR_CHARS = 2000

Handler = Callable[[dict], None]

_HANDLERS: dict[str, Handler] = {}


class PermanentJobError(Exception):
    """Raised by a handler for a job that can never succeed (a malformed
    payload, say). The job goes straight to `dead` instead of retrying."""


@dataclass(frozen=True)
class Job:
    """A claimed job. `attempt` is the claim's fence: complete/fail apply only
    while the row still carries this worker and this attempt number."""

    id: str
    type: str
    payload: dict
    attempt: int
    max_attempts: int
    locked_by: str

    @classmethod
    def from_row(cls, row: dict) -> "Job":
        return cls(
            id=str(row["id"]),
            type=row["type"],
            payload=row.get("payload") or {},
            attempt=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            locked_by=row["locked_by"],
        )


# ── handler registry ────────────────────────────────────────────────────────


def job_handler(job_type: str) -> Callable[[Handler], Handler]:
    """Register `fn(payload)` as the handler for `job_type`.

    One handler per type; registering a second, different function for a type
    raises (two modules silently fighting over a type is a bug). Re-registering
    the same function is a no-op, so a module reload is harmless.
    """
    def register(fn: Handler) -> Handler:
        existing = _HANDLERS.get(job_type)
        if existing is not None and existing is not fn and (
            getattr(existing, "__qualname__", None) != getattr(fn, "__qualname__", None)
            or getattr(existing, "__module__", None) != getattr(fn, "__module__", None)
        ):
            raise ValueError(f"job type {job_type!r} already has a handler: {existing!r}")
        _HANDLERS[job_type] = fn
        return fn
    return register


#: The job the worker is running right now (set by worker/runner.py around
#: each handler call). Handlers take only the payload; one that needs to fence
#: its own writes on the claim (document_jobs: the upload row's owner) reads
#: the attempt and worker id here. None outside a worker run.
_CURRENT_JOB: ContextVar["Job | None"] = ContextVar("sapling_current_job", default=None)


def current_job() -> "Job | None":
    return _CURRENT_JOB.get()


def get_handler(job_type: str) -> Handler | None:
    return _HANDLERS.get(job_type)


def registered_types() -> list[str]:
    return sorted(_HANDLERS)


# ── backoff ─────────────────────────────────────────────────────────────────


def backoff_seconds(
    attempt: int,
    *,
    base: int = BACKOFF_BASE_SECONDS,
    cap: int = BACKOFF_CAP_SECONDS,
    rng: random.Random | None = None,
    jitter: bool = True,
) -> int:
    """Seconds to wait before retrying after failed attempt number `attempt`.

    Exponential (base, 2*base, 4*base, ...) capped at `cap`. With jitter the
    wait is drawn from [delay/2, delay], so retries of jobs that failed
    together (a provider blip) spread out instead of returning in step.
    """
    attempt = max(1, int(attempt))
    # 2**30 already dwarfs any cap; keep the exponent bounded.
    delay = min(cap, base * (2 ** min(attempt - 1, 30)))
    if not jitter or delay <= 1:
        return int(delay)
    r = rng or random
    return int(delay / 2 + r.random() * (delay / 2))


# ── queue operations ────────────────────────────────────────────────────────


@runs_as_service  # #115: jobs is a service-only table and enqueue_job is service_role-only; a request-path enqueue under db_user_scope=enforce must not run as the student
def enqueue(
    job_type: str,
    payload: dict[str, Any] | None = None,
    *,
    dedupe_key: str | None = None,
    run_after: datetime | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> dict:
    """Add a job. Returns ``{"id": <uuid>, "inserted": bool}``.

    `dedupe_key`: while a QUEUED job with this key exists, enqueueing it again
    returns that job (``inserted`` False) instead of adding one. A job already
    running does not count, so work triggered after it started is never lost.

    Raises on a database error; callers that must not fail decide what to do
    (see course_context_service.refresh_course_context, which runs the work
    inline instead).
    """
    params: dict[str, Any] = {
        "p_type": job_type,
        "p_payload": payload or {},
        "p_dedupe_key": dedupe_key,
        "p_run_after": run_after.isoformat() if run_after is not None else None,
        "p_max_attempts": max_attempts,
    }
    rows = rpc("enqueue_job", params)
    row = rows[0] if isinstance(rows, list) and rows else {}
    out = {"id": row.get("id"), "inserted": bool(row.get("inserted"))}
    logger.info(
        "job.enqueued type=%s id=%s inserted=%s dedupe_key=%s",
        job_type, out["id"], out["inserted"], dedupe_key,
    )
    return out


def claim(
    worker_id: str,
    *,
    types: list[str] | None = None,
    limit: int = 1,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> list[Job]:
    """Claim up to `limit` runnable jobs for `worker_id` (SKIP LOCKED).

    `types` limits the claim to those job types; a worker passes the types it
    has handlers for, so a job type added by a newer API image waits for a
    worker that knows it rather than failing on an older one.
    """
    rows = rpc("claim_jobs", {
        "p_worker": worker_id,
        "p_types": list(types) if types is not None else None,
        "p_limit": limit,
        "p_lease_seconds": lease_seconds,
    })
    return [Job.from_row(r) for r in (rows or [])]


def complete(job: Job) -> bool:
    """Mark `job` succeeded. False when the claim was lost (the lease ran out
    and another worker re-claimed it): that worker's run decides the row."""
    ok = rpc("complete_job", {
        "p_id": job.id, "p_worker": job.locked_by, "p_attempt": job.attempt,
    })
    return ok is True


def fail(
    job: Job,
    error: str,
    *,
    permanent: bool = False,
    rng: random.Random | None = None,
) -> str | None:
    """Record a failed attempt. Returns the job's new status: ``failed``
    (retried after the backoff), ``dead`` (out of attempts, or `permanent`),
    or None when the claim was lost."""
    status = rpc("fail_job", {
        "p_id": job.id,
        "p_worker": job.locked_by,
        "p_attempt": job.attempt,
        "p_error": (error or "")[:MAX_ERROR_CHARS],
        "p_backoff_seconds": backoff_seconds(job.attempt, rng=rng),
        "p_permanent": permanent,
    })
    return status if isinstance(status, str) else None


# ── upkeep: lease heartbeat, pruning (20261108213623_jobs_upkeep.sql) ───────


def heartbeat(job: Job) -> bool:
    """Push `job`'s lease forward (locked_at = now()). The worker calls this
    every lease/3 while a handler runs, so a long job is not re-offered to a
    second worker mid-run. Fenced like complete/fail: False means the claim is
    gone (re-claimed after the lease ran out, or reaped dead)."""
    ok = rpc("heartbeat_job", {
        "p_id": job.id, "p_worker": job.locked_by, "p_attempt": job.attempt,
    })
    return ok is True


#: A worker stops heartbeating a job after this long, so a hung handler still
#: loses its job one lease later (worker/runner.py::_Heartbeat).
MAX_HEARTBEAT_SECONDS = 3600


#: The job that prunes old `succeeded` rows (and the staging tables' terminal
#: rows, STAGING_PRUNE_FUNCTIONS). Each worker that claims it
#: enqueues it once per PRUNE_INTERVAL_SECONDS under PRUNE_JOB_TYPE as its
#: dedupe key, so any number of replicas collapse into one waiting run.
PRUNE_JOB_TYPE = "jobs.prune"
#: Keep succeeded rows this long (the admin view and debugging read them).
#: Dead letters are never pruned. The SQL floors it at 1 day.
PRUNE_AFTER_DAYS = 14
PRUNE_INTERVAL_SECONDS = 3600
#: Rows per DELETE, and DELETEs per run: one run removes at most
#: PRUNE_BATCH * PRUNE_MAX_BATCHES rows and the next run picks up the rest.
PRUNE_BATCH = 1000
PRUNE_MAX_BATCHES = 50
#: The same run also prunes the terminal rows of the in-flight staging tables
#: (document_uploads, gradescope_syncs: 20261108212226 / 20261108214227),
#: which are only a short-lived receipt once their outcome was delivered. The
#: SQL floors it at 1 day and never touches a row that is still running.
STAGING_PRUNE_AFTER_DAYS = 2
#: SQL function per staging table; each deletes terminal rows in one bounded
#: batch per call, exactly like prune_jobs.
STAGING_PRUNE_FUNCTIONS = ("prune_document_uploads", "prune_gradescope_syncs")


def prune(
    *,
    older_than_days: int = PRUNE_AFTER_DAYS,
    batch: int = PRUNE_BATCH,
    max_batches: int = PRUNE_MAX_BATCHES,
) -> int:
    """Delete `succeeded` jobs older than `older_than_days`, `batch` rows per
    statement, until a short batch (nothing older left) or `max_batches`.
    Returns how many rows went. Never touches unfinished or dead rows."""
    total = _prune_batches("prune_jobs", older_than_days, batch, max_batches)
    logger.info("job.pruned rows=%d older_than_days=%d", total, older_than_days)
    return total


def _prune_batches(function: str, older_than_days: int, batch: int, max_batches: int) -> int:
    """Call a bounded-batch prune function until a short batch or `max_batches`."""
    total = 0
    for _ in range(max(1, int(max_batches))):
        n = rpc(function, {"p_older_than_days": older_than_days, "p_limit": batch})
        n = n if isinstance(n, int) and not isinstance(n, bool) else 0
        total += n
        if n < batch:
            break
    return total


def prune_staging(
    *,
    older_than_days: int = STAGING_PRUNE_AFTER_DAYS,
    batch: int = PRUNE_BATCH,
    max_batches: int = PRUNE_MAX_BATCHES,
) -> dict[str, int]:
    """Delete terminal staging rows (STAGING_PRUNE_FUNCTIONS) older than
    `older_than_days`, each table in the same bounded loop as `prune`.
    Returns rows deleted per function. One table failing does not stop the
    others; the first error is raised after all ran, so the job retries (the
    prunes are idempotent) and dead-letters visibly if it keeps failing."""
    out: dict[str, int] = {}
    first_error: Exception | None = None
    for function in STAGING_PRUNE_FUNCTIONS:
        try:
            out[function] = _prune_batches(function, older_than_days, batch, max_batches)
        except Exception as exc:
            logger.warning("job.prune_failed function=%s", function, exc_info=True)
            first_error = first_error or exc
            continue
        logger.info("job.pruned function=%s rows=%d older_than_days=%d",
                    function, out[function], older_than_days)
    if first_error is not None:
        raise first_error
    return out


def schedule_prune(older_than_days: int = PRUNE_AFTER_DAYS) -> dict:
    """Make sure a prune run is waiting. Deduped: while one is queued this
    returns it (``inserted`` False) instead of adding another, so the first
    waiting run's retention is the one used."""
    return enqueue(PRUNE_JOB_TYPE, {"older_than_days": int(older_than_days)},
                   dedupe_key=PRUNE_JOB_TYPE, max_attempts=3)


@job_handler(PRUNE_JOB_TYPE)
def _run_prune(payload: dict) -> None:
    days = payload.get("older_than_days", PRUNE_AFTER_DAYS) if isinstance(payload, dict) else None
    if type(days) is not int:
        raise PermanentJobError(f"{PRUNE_JOB_TYPE}: older_than_days must be an integer")
    prune(older_than_days=days)
    prune_staging()
