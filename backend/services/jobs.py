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
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from db.connection import pg_quote_value, rpc, table
from db.scope import runs_as_service

logger = logging.getLogger("sapling.jobs")

#: The flag that moves work onto the queue (services/feature_flags.py).
JOBS_QUEUE_FLAG = "jobs_queue"

DEFAULT_MAX_ATTEMPTS = 5
#: The shortest lease ANY worker may claim with, and what the heartbeat is
#: paced by. claim_jobs re-offers a running row once `locked_at + p_lease_seconds`
#: has passed, where p_lease_seconds is the CLAIMER's lease, not the lease of the
#: worker running the job. So a heartbeat only protects a job if it lands more
#: often than the shortest lease any other worker claims with. The rule that
#: makes that hold for every pair of workers:
#:   1. no worker claims with a lease under MIN_LEASE_SECONDS (`claim` raises,
#:      the Worker refuses to construct, `python -m worker` exits 2 at boot);
#:   2. every worker beats every HEARTBEAT_INTERVAL_SECONDS (= MIN/3) whatever
#:      its own lease, so a live job's locked_at is never more than MIN/3 old
#:      and two beats can be lost before any claimer could see it as expired.
#: A worker's own, longer lease then only decides how soon ITS claims re-offer a
#: job whose heartbeat stopped (a crash, or a hung handler past
#: MAX_HEARTBEAT_SECONDS); the shortest lease in the fleet wins that race.
#: Change this constant only with every worker on the new image (stop the old
#: ones first): a fleet mixing two values breaks rule 2 for the old workers.
MIN_LEASE_SECONDS = 300
#: How often a running job's lease is pushed forward (worker/runner.py).
HEARTBEAT_INTERVAL_SECONDS = MIN_LEASE_SECONDS / 3
#: A claim holds its job this long; past it the job is offered again. The
#: worker claims one job at a time, so a lease starts when its work does.
DEFAULT_LEASE_SECONDS = MIN_LEASE_SECONDS
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

    Raises ValueError for a lease under MIN_LEASE_SECONDS: a shorter lease
    would re-offer jobs other workers are still running and heartbeating.
    """
    check_lease(lease_seconds)
    rows = rpc("claim_jobs", {
        "p_worker": worker_id,
        "p_types": list(types) if types is not None else None,
        "p_limit": limit,
        "p_lease_seconds": lease_seconds,
    })
    return [Job.from_row(r) for r in (rows or [])]


def check_lease(lease_seconds: int) -> None:
    """Raise ValueError unless `lease_seconds` honours MIN_LEASE_SECONDS."""
    if int(lease_seconds) < MIN_LEASE_SECONDS:
        raise ValueError(
            f"a job lease of {lease_seconds}s is under the {MIN_LEASE_SECONDS}s minimum: "
            f"workers heartbeat every {HEARTBEAT_INTERVAL_SECONDS:.0f}s, and a claimer "
            f"with a shorter lease would re-run jobs other workers are still running "
            f"(services/jobs.py MIN_LEASE_SECONDS)")


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
    every HEARTBEAT_INTERVAL_SECONDS while a handler runs, so a long job is not
    re-offered to a second worker mid-run (see MIN_LEASE_SECONDS for why the
    pace is the fleet minimum, not this worker's lease). Fenced like complete/fail: False means the claim is
    gone (re-claimed after the lease ran out, or reaped dead)."""
    ok = rpc("heartbeat_job", {
        "p_id": job.id, "p_worker": job.locked_by, "p_attempt": job.attempt,
    })
    return ok is True


#: A worker stops heartbeating a job after this long, so a hung handler still
#: loses its job one lease later (worker/runner.py::_Heartbeat).
MAX_HEARTBEAT_SECONDS = 3600


#: The job that prunes old `succeeded` rows (and the staging tables' terminal
#: rows, STAGING_PRUNE_FUNCTIONS). Every worker that claims it calls
#: `schedule_prune` once per PRUNE_INTERVAL_SECONDS, which enqueues a run only
#: when no `jobs.prune` row is waiting or running and none succeeded within the
#: interval; the enqueue is also deduped on an hourly key, so two replicas that
#: both read "nothing yet" in the same hour still add one waiting row. N
#: replicas therefore give about one prune run per interval, not N.
PRUNE_JOB_TYPE = "jobs.prune"
#: Keep succeeded rows this long (the admin view and debugging read them).
#: Dead letters are never pruned. The SQL floors it at 1 day.
#: An env var (JOBS_PRUNE_AFTER_DAYS, worker/__main__.py) tunes it rather than a
#: feature flag on purpose: this is queue upkeep, not a product feature. It only
#: ever deletes `succeeded` rows past their retention (prune_jobs refuses every
#: other status: queued/failed/running work and dead letters are untouchable),
#: no student sees it, and 0 switches the scheduling off entirely.
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


#: A prune run counts as "already happening" in these states: waiting,
#: waiting out a retry backoff, or in a worker's hands.
_PRUNE_PENDING = ("queued", "failed", "running")


def prune_dedupe_key(now: datetime) -> str:
    """`jobs.prune:<YYYYMMDDHH>` (UTC): one waiting prune per hour bucket."""
    return f"{PRUNE_JOB_TYPE}:{now.astimezone(timezone.utc):%Y%m%d%H}"


def schedule_prune(
    older_than_days: int = PRUNE_AFTER_DAYS,
    *,
    interval_seconds: float = PRUNE_INTERVAL_SECONDS,
    now: datetime | None = None,
) -> dict:
    """Make sure about one prune run happens per `interval_seconds`, however
    many workers call this.

    One read first: if a `jobs.prune` row is pending (queued, failed, running)
    or SUCCEEDED within the interval, nothing is added and that row is returned
    (``{"id", "inserted": False, "skipped": <its status>}``). Otherwise the run
    is enqueued under the hour-bucketed dedupe key (`prune_dedupe_key`), so two
    replicas racing past the read in the same hour collapse into one waiting
    row. The dedupe only covers QUEUED rows (enqueue_job), which is why the read
    has to look at running and recently succeeded ones too."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(seconds=interval_seconds)).astimezone(timezone.utc)
    recent = table("jobs").select(
        "id,status",
        filters={
            "type": f"eq.{PRUNE_JOB_TYPE}",
            "or": (f"(status.in.({','.join(_PRUNE_PENDING)}),"
                   f"and(status.eq.succeeded,updated_at.gte."
                   f"{pg_quote_value(since.strftime('%Y-%m-%dT%H:%M:%SZ'))}))"),
        },
        limit=1,
    ) or []
    if recent:
        row = recent[0]
        logger.info("job.prune_schedule_skipped id=%s status=%s", row.get("id"), row.get("status"))
        return {"id": row.get("id"), "inserted": False, "skipped": row.get("status")}
    return enqueue(PRUNE_JOB_TYPE, {"older_than_days": int(older_than_days)},
                   dedupe_key=prune_dedupe_key(now), max_attempts=3)


@job_handler(PRUNE_JOB_TYPE)
def _run_prune(payload: dict) -> None:
    days = payload.get("older_than_days", PRUNE_AFTER_DAYS) if isinstance(payload, dict) else None
    if type(days) is not int:
        raise PermanentJobError(f"{PRUNE_JOB_TYPE}: older_than_days must be an integer")
    prune(older_than_days=days)
    prune_staging()
