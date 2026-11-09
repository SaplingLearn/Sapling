"""The staged-job state machine, once (#116; #835/#837 addendum).

Two request paths move slow work onto the job queue the same way:
services/document_jobs.py (a queued upload, `document_uploads`) and
services/gradescope/jobs.py (a queued Gradescope sync, `gradescope_syncs`).
Each one stages a row, enqueues a job carrying only the row id, and watches
the row; the worker claims the row and records its outcome on it. This module
is the machinery both share, parameterised by a :class:`Spec` (table, job
type, the JSON column that holds the owner tokens):

* **owner tokens** — `<column>->>owner` (the worker attempt running the row:
  worker id + job attempt) and `<column>->>inline_owner` (the request that
  took the row back to run it inline). Opaque ids, never content.
* **enqueue** (:func:`enqueue`) — the job, deduped per row, and its id
  recorded on the row (best-effort: the liveness reads fall back to the
  dedupe key, :func:`job_row`).
* **take-back** (:func:`take_back`) — the compare-and-swap ``queued ->
  inline`` carrying the request's token; :func:`enqueue_or_take_back` is the
  "enqueue failed: run it here" fallback.
* **inline outcome** (:func:`finish_inline`) — a CAS on ``inline`` + the
  request's own token.
* **owner-fenced writes** — :func:`claim` (the worker's ``queued -> running``
  swap, or a re-delivered job's takeover from the previous attempt's token)
  and :func:`cas_update` (every later write: a CAS on the stage the caller
  last saw and, when given, its owner token).
* **liveness** (:data:`LIVE_JOB`, :func:`job_alive`) — whether a job will
  still run the row.
* **the watch loop** (:func:`watch_steps`) — one sans-I/O state machine
  (read, take back after the grace, adopt another request's outcome, notice a
  dead-lettered job, retry blips, give up at the max wait) driven by
  :func:`run_watch` (blocking: the Gradescope route is a plain ``def``) and
  :func:`awatch` (async: the upload SSE stream).

Every DB call goes through the ``db`` argument, which callers pass as their
own module's ``table`` (looked up at call time), so a test that patches
``services.document_jobs.table`` still sees every request. Nothing here is
decorated ``@runs_as_service``: the callers' public functions are (they are
the listed service-role opt-outs, tests/test_service_scope_allowlist.py).
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Generator

from services import jobs

logger = logging.getLogger(__name__)

QUEUED = "queued"
INLINE = "inline"

#: Job statuses that will still run the job (`failed` = waiting for a retry).
LIVE_JOB = frozenset({"queued", "running", "failed"})
#: Of those, the ones not yet running (no lease to judge).
WAITING_JOB = frozenset({"queued", "failed"})


@dataclass(frozen=True)
class Spec:
    """One staged-job table: where its rows live and which job runs them."""

    table: str
    job_type: str
    #: The plaintext JSON column that holds the owner tokens.
    owner_column: str
    #: A short noun for logs ("upload", "gradescope sync").
    label: str

    @property
    def owner_path(self) -> str:
        return f"{self.owner_column}->>owner"

    @property
    def inline_owner_path(self) -> str:
        return f"{self.owner_column}->>inline_owner"

    def dedupe_key(self, row_id: str) -> str:
        return f"{self.job_type}:{row_id}"


@dataclass
class Staged:
    id: str
    #: True when this call (re)queued the row and must enqueue its job; False
    #: when it attached to one already in flight.
    fresh: bool


# ── small pure helpers ──────────────────────────────────────────────────────


def parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def age_seconds(raw: Any) -> float | None:
    """Seconds since an ISO timestamp, or None when it is unreadable."""
    ts = parse_ts(raw)
    return None if ts is None else (datetime.now(timezone.utc) - ts).total_seconds()


def token_in(row: dict | None, column: str, key: str) -> str | None:
    """An owner token (`key`) out of the row's JSON `column`, or None."""
    value = (row or {}).get(column)
    token = value.get(key) if isinstance(value, dict) else None
    return token if isinstance(token, str) and token else None


def owner_token(job: jobs.Job | None) -> str:
    """This attempt's owner token: worker id + job attempt; outside a worker
    run (tests, a script) a unique token, which fences just as well."""
    if job is None:
        return f"direct#{uuid.uuid4().hex}"
    return f"{job.locked_by}#{job.attempt}"


def owner_match(token: str | None) -> str:
    """The PostgREST filter value matching an owner token (or its absence)."""
    return f"eq.{token}" if token else "is.null"


def job_alive(job: dict | None, *, lease_seconds: float | None = None) -> bool:
    """Whether a job will still run (or is running) its row: waiting to be
    claimed or retried, or running — under a lease its worker still renews,
    when `lease_seconds` is given (an unreadable `locked_at` reads alive)."""
    if not job:
        return False
    status = job.get("status")
    if status in WAITING_JOB:
        return True
    if status == "running":
        if lease_seconds is None:
            return True
        age = age_seconds(job.get("locked_at"))
        return age is None or age <= lease_seconds
    return False  # succeeded / dead


# ── DB steps (each through the caller's `db` = its module's `table`) ────────


def _first(rows: Any) -> dict | None:
    return rows[0] if isinstance(rows, list) and rows else None


def enqueue(spec: Spec, db: Callable, row_id: str, payload: dict) -> str | None:
    """Enqueue the row's job (deduped per row) and record its id on the row.
    Raises when the enqueue fails; the job-id write is best-effort."""
    out = jobs.enqueue(spec.job_type, payload, dedupe_key=spec.dedupe_key(row_id))
    job_id = out.get("id")
    if job_id:
        try:
            db(spec.table).update(
                {"job_id": job_id}, filters={"id": f"eq.{row_id}"},
                prefer_return_minimal=True,
            )
        except Exception:
            # Only the liveness reads use it, and they fall back to the
            # dedupe key (job_row).
            logger.warning("could not record job %s on %s %s", job_id, spec.label, row_id,
                           exc_info=True)
    return job_id


def job_row(spec: Spec, db: Callable, row_id: str, job_id: str | None,
            columns: str = "status") -> dict | None:
    """The row's job: by the id recorded on the row, or — when that
    best-effort write never landed — by its dedupe key (the newest)."""
    if job_id:
        rows = db("jobs").select(columns, filters={"id": f"eq.{job_id}"}, limit=1)
    else:
        rows = db("jobs").select(
            columns, filters={"dedupe_key": f"eq.{spec.dedupe_key(row_id)}"},
            order="created_at.desc", limit=1,
        )
    return _first(rows)


def take_back(spec: Spec, db: Callable, row_id: str, token: str,
              clear: dict | None = None) -> bool:
    """queued -> inline, for the request holding `token` to run the row
    itself (recorded as `<owner_column>.inline_owner`; `clear` columns are
    nulled with it). False when a worker already started it, another request
    took it, or it ended."""
    won = db(spec.table).update(
        {"stage": INLINE, **(clear or {}), spec.owner_column: {"inline_owner": token}},
        filters={"id": f"eq.{row_id}", "stage": f"eq.{QUEUED}"},
    )
    return bool(won)


def finish_inline(spec: Spec, db: Callable, row_id: str, token: str, data: dict) -> bool:
    """Record an inline run's outcome (`data`) on the row it took back, only
    while the row is still this request's (`inline` + its token). Never
    raises: the request already has its answer."""
    try:
        return bool(db(spec.table).update(data, filters={
            "id": f"eq.{row_id}", "stage": f"eq.{INLINE}",
            spec.inline_owner_path: f"eq.{token}",
        }))
    except Exception:
        logger.warning("could not record the inline outcome of %s %s", spec.label, row_id,
                       exc_info=True)
        return False


_ANY = object()


def cas_update(spec: Spec, db: Callable, row_id: str, data: dict, *, stage: str,
               owner: Any = _ANY) -> bool:
    """An update conditional on the row still being at `stage` — and, when
    `owner` is given, still owned by that worker token (None = no owner)."""
    filters = {"id": f"eq.{row_id}", "stage": f"eq.{stage}"}
    if owner is not _ANY:
        filters[spec.owner_path] = owner_match(owner)
    return bool(db(spec.table).update(data, filters=filters))


def claim(spec: Spec, db: Callable, row: dict, *, to_stage: str, owner: str) -> bool:
    """The worker's claim: ``queued -> to_stage`` with its owner token, or —
    for a re-delivered job whose row an earlier attempt already moved — a
    takeover from that attempt's token, so the stale attempt's next write is
    refused. False when the row moved first (taken back, or another attempt)."""
    stage = row.get("stage")
    filters = {"id": f"eq.{row['id']}", "stage": f"eq.{stage}"}
    if stage != QUEUED:
        filters[spec.owner_path] = owner_match(token_in(row, spec.owner_column, "owner"))
    return bool(db(spec.table).update(
        {"stage": to_stage, spec.owner_column: {"owner": owner}}, filters=filters,
    ))


def enqueue_or_take_back(spec: Spec, row_id: str, *, enqueue_fn: Callable[[str], Any],
                         take_back_fn: Callable[[str, str], bool], token: str) -> bool:
    """Enqueue a freshly staged row's job; when that fails, take the row back
    for this request. True only when the request now holds the row and must
    run it inline. A take-back that loses (or errors) answers False: watch
    the row — a worker has it after all, or the watch takes it back after the
    grace."""
    try:
        enqueue_fn(row_id)
        return False
    except Exception:
        logger.warning("%s enqueue failed for %s %s; running inline", spec.job_type,
                       spec.label, row_id, exc_info=True)
    try:
        return bool(take_back_fn(row_id, token))
    except Exception:
        logger.warning("take-back of %s %s failed; watching it", spec.label, row_id,
                       exc_info=True)
        return False


# ── the watch loop ──────────────────────────────────────────────────────────

#: How a watch ended (WatchEnd.kind), plus PROGRESS for a stage change.
END = "end"            # the row reached one of `ends` (done / failed)
TOOK_BACK = "inline"   # this request holds the row (took it back): run it
ADOPTED = "adopted"    # another request's inline run saved it (the adopt hook)
PENDING = "pending"    # still running at the max wait
TIMEOUT = "timeout"    # too many consecutive database errors
GONE = "gone"          # the row was deleted under the watch
PROGRESS = "progress"  # (async driver only) the row moved to a new stage


@dataclass
class WatchEnd:
    kind: str
    row: dict | None = None


@dataclass
class WatchIO:
    """The steps a watch performs, bound to one row by the caller. Each is a
    plain (blocking) function; the async driver runs it off the loop."""

    read: Callable[[], dict | None]
    take_back: Callable[[], bool]
    job_dead: Callable[[dict], bool]
    fail_dead: Callable[[dict], Any]
    #: Another request's inline run: the row to end on, or None to keep
    #: waiting. None (no hook): always keep waiting for its recorded outcome.
    adopt: Callable[[dict], dict | None] | None = None


@dataclass(frozen=True)
class WatchPlan:
    spec: Spec
    row_id: str
    token: str
    ends: frozenset
    running: frozenset
    grace: float
    max_wait: float
    poll: float
    job_check_every: int
    max_errors: int


_READ, _TAKE_BACK, _ADOPT, _JOB_DEAD, _FAIL_DEAD, _SLEEP, _EMIT = (
    "read", "take_back", "adopt", "job_dead", "fail_dead", "sleep", "emit")


def watch_steps(plan: WatchPlan, *, clock: Callable[[], float], adopts: bool,
                progress: bool) -> Generator[tuple, Any, WatchEnd]:
    """The watch as a sans-I/O generator: it yields the step to perform
    (``(name, *args)``), receives its result (or has its exception thrown in)
    and returns the :class:`WatchEnd`.

    Poll the row until it reaches one of `plan.ends`, THIS request takes it
    back (``queued`` past the grace, or a row already ``inline`` under its own
    token — a take-back whose answer was lost to a blip), another request's
    inline outcome is adopted, or `plan.max_wait`. A running row's job is
    checked every `job_check_every` polls, and a dead-lettered one is failed.
    A transient error on any step is retried on the next poll; only
    `max_errors` in a row end the watch (TIMEOUT). With `progress`, each new
    stage is emitted once."""
    spec = plan.spec
    started = clock()
    last_stage = None
    last_row: dict | None = None
    polls = 0
    errors = 0
    while True:
        elapsed = clock() - started
        try:
            row = yield (_READ,)
            if row is None:
                return WatchEnd(GONE)
            last_row = row
            stage = row.get("stage")
            if stage == QUEUED and elapsed >= plan.grace:
                if (yield (_TAKE_BACK,)):
                    logger.info("%s %s: no worker took it in %.0fs; running inline",
                                spec.label, plan.row_id, plan.grace)
                    return WatchEnd(TOOK_BACK, {**row, "stage": INLINE})
                errors = 0
                yield (_SLEEP, plan.poll)
                continue  # a worker (or another request) took it: re-read
            if stage == INLINE:
                if token_in(row, spec.owner_column, "inline_owner") == plan.token:
                    return WatchEnd(TOOK_BACK, row)
                if adopts:
                    adopted = yield (_ADOPT, row)
                    if adopted is not None:
                        return WatchEnd(ADOPTED, adopted)
            elif stage in plan.ends:
                return WatchEnd(END, row)
            elif progress and stage != last_stage:
                last_stage = stage
                yield (_EMIT, row)
            if elapsed >= plan.max_wait:
                return WatchEnd(PENDING, row)
            polls += 1
            if stage in plan.running and polls % plan.job_check_every == 0:
                if (yield (_JOB_DEAD, row)):
                    yield (_FAIL_DEAD, row)
                    errors = 0
                    continue
            errors = 0
        except Exception:
            errors += 1
            logger.warning("%s %s: status poll failed (%d in a row)", spec.label, plan.row_id,
                           errors, exc_info=True)
            if errors >= plan.max_errors or elapsed >= plan.max_wait:
                return WatchEnd(TIMEOUT, last_row)
        yield (_SLEEP, plan.poll)


def _step_fn(io: WatchIO, op: tuple) -> tuple[Callable, tuple]:
    name = op[0]
    if name == _READ:
        return io.read, ()
    if name == _TAKE_BACK:
        return io.take_back, ()
    if name == _ADOPT:
        return io.adopt, op[1:]
    if name == _JOB_DEAD:
        return io.job_dead, op[1:]
    if name == _FAIL_DEAD:
        return io.fail_dead, op[1:]
    raise ValueError(f"unknown watch step {name!r}")


def run_watch(plan: WatchPlan, io: WatchIO, *, sleep: Callable[[float], None] = time.sleep,
              clock: Callable[[], float] = time.monotonic) -> WatchEnd:
    """Drive a watch to its end, blocking (for a threadpool caller)."""
    steps = watch_steps(plan, clock=clock, adopts=io.adopt is not None, progress=False)
    send: Any = None
    exc: Exception | None = None
    while True:
        try:
            op = steps.throw(exc) if exc is not None else steps.send(send)
        except StopIteration as stop:
            return stop.value
        send, exc = None, None
        if op[0] == _SLEEP:
            sleep(op[1])
            continue
        if op[0] == _EMIT:
            continue
        fn, args = _step_fn(io, op)
        try:
            send = fn(*args)
        except Exception as e:
            exc = e


async def awatch(plan: WatchPlan, io: WatchIO, *,
                 clock: Callable[[], float] = time.monotonic) -> AsyncIterator[WatchEnd]:
    """Drive a watch on the event loop: every step runs off the loop, and
    each new stage is yielded as a PROGRESS item before the final WatchEnd."""
    steps = watch_steps(plan, clock=clock, adopts=io.adopt is not None, progress=True)
    send: Any = None
    exc: Exception | None = None
    while True:
        try:
            op = steps.throw(exc) if exc is not None else steps.send(send)
        except StopIteration as stop:
            yield stop.value
            return
        send, exc = None, None
        if op[0] == _SLEEP:
            await asyncio.sleep(op[1])
            continue
        if op[0] == _EMIT:
            yield WatchEnd(PROGRESS, op[1])
            continue
        fn, args = _step_fn(io, op)
        try:
            send = await asyncio.to_thread(fn, *args)
        except Exception as e:
            exc = e
