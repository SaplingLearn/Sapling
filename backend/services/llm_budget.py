"""Per-user daily LLM token budget (#119, plan phase 5). Flag: `llm_budget`.

Budgets live in `llm_budgets` (migration 20261108213311): a global default row,
plus role (roles.slug) and per-user overrides, edited at /api/admin/llm. The
SQL function `llm_budget_status(user)` resolves the user's limit (user row ->
the most generous of their role rows -> default) and sums today's (UTC)
`llm_usage.total_tokens` for them in one indexed round trip. Usage rows are
attributed to the acting user even when the caller names nobody
(events_service.log_llm_usage), so the upload pipeline, concept scans and
vision OCR count too.

Enforcement is at the LLM chokepoint: `agents/_providers.py`'s resilient
models call :func:`check_before_request` before every model request, and it
refuses — with :class:`LLMBudgetExceeded`, a 429 — only when ALL hold:

* there is an acting user (``request_context.current_acting_user``): the
  request's session user, or the student a job handler runs for
  (``request_context.acting_for`` — the upload pipeline and the Gradescope
  sync on the job queue). Work with no user — the index sweeper, scripts,
  evals — is never budgeted;
* the work is FOREGROUND: code inside :func:`background_work` (post-response
  BackgroundTasks such as quiz submit's context update, the observe-only
  tutor router) is never refused;
* the request STARTS a run (:func:`starts_run`): a tool loop's later requests,
  pydantic-ai's output-validation retries and its re-send after an empty
  response are let through, so a run that began under budget is never cut
  off halfway (one run of overshoot is the price of never failing a turn
  after its tools wrote);
* the unit of work has not decided yet. **The budget is decided ONCE per
  unit of work** — one HTTP request, or one job handler run — by the first
  run that reaches the gate, and recorded on the work's shared state (the
  request's ``scope["state"]``, which its handler, threadpool Depends,
  detached tasks and BackgroundTasks all share; or the ``acting_for`` scope).
  Every later run in the same unit reuses that decision without another
  read: learn.py's textless-turn continuation, a second agent in the same
  pipeline, the vision OCR's next page, a background task after an allowed
  foreground. So a turn the gate let start is never refused half-way through
  its own continuations; a unit that was refused stays refused;
* the `llm_budget` flag is on for that user (per user: role rules and
  rollouts apply);
* the user's resolved limit is not NULL (unlimited) and today's usage has
  reached it.

Function mode (the E2E lanes, the unit lane's FunctionModels) never builds a
resilient model, so it never meets this module. A fallback model is not
checked again — it is the same run.

Fails OPEN, like the quiz spend cap (#544 F1): an unreadable flag, a status
read that errors or takes longer than ``STATUS_TIMEOUT_S`` (the RPC's own
per-call timeout, so no thread outlives it) lets the run through with a
warning. This is a cost control, not an authorization gate, and denying every
student because a usage read blipped is worse than the spend it would save.

Caching (CLAUDE.md, #98): a per-process, per-user TTL cache of the status —
``STATUS_TTL_S`` (never past the user's reset time), ``FAILURE_TTL_S`` for a
failed read so a DB brownout costs one bounded wait per user per window, not
one per run. Invalidation: the admin budget writes call
:func:`clear_llm_budget_cache`; other workers converge within the TTL. Usage
rows themselves land through events_service's async queue, so the database
alone is behind by a few seconds plus the TTL.

Race safety (sec2 M4): that lag let N parallel first requests all read the
same "under budget" status and all start. :func:`_admit` makes the decision
check-and-reserve under one lock: each admitted run reserves
``RESERVE_TOKENS_PER_RUN`` in process memory, and later decisions add every
reservation not yet visible in the status they read. A run whose usage row
has been queued (``note_usage_recorded``, called by ``log_llm_usage``) is
settled: it stops counting once a status read is ``SETTLE_LAG_S`` past the
queueing, since its real usage is in ``used`` by then. A run still in flight
counts until it settles, or for at most ``LAND_LAG_S`` if it never reports.
With R tokens left, a burst admits about
R / RESERVE_TOKENS_PER_RUN runs, not N. A failed read falls back to the
user's last good status of the day (plus reservations) instead of failing
fully open; only a user never read today fails open.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import math
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from db.scope import runs_as_service

logger = logging.getLogger("sapling.llm_budget")

FLAG_KEY = "llm_budget"
ERROR_CODE = "LLM_BUDGET_EXCEEDED"

#: How long a user's status is trusted before it is read again. Short: the
#: in-process reservations below cover the gap between reads, and one indexed
#: RPC per active user per 10 s is cheap while the flag is on.
STATUS_TTL_S = 10.0
#: Tokens one admitted run is assumed to spend until its usage row lands (a
#: Sonnet tutor turn with RAG and a tool loop is ~10-40K, a quiz ~20-30K).
RESERVE_TOKENS_PER_RUN = 20_000
#: How long after a status read a run's own usage may still be missing from
#: it: the run's length plus events_service's async usage queue. A
#: reservation older than (read time - this) is taken to be in `used`.
LAND_LAG_S = 120.0
#: How long after a run's usage row is QUEUED it may still be missing from a
#: status read (events_service flushes about once a second; the rest is slack).
SETTLE_LAG_S = 15.0
#: How long a FAILED status read is remembered (the run fails open meanwhile).
FAILURE_TTL_S = 10.0
#: Bound on one status read (the RPC's per-call HTTP timeout); past it the
#: run fails open.
STATUS_TIMEOUT_S = 2.0
#: Cache size bound (oldest entries go first).
_CACHE_MAX = 4096


class LLMBudgetExceeded(HTTPException):
    """The user has spent today's token budget. A 429 with a student-readable
    `detail`, `Retry-After` until the UTC reset, and `code` / `reset_at` for
    clients that want them (main.py's handler adds `error.reset_at`).

    An HTTPException on purpose: routes already let HTTPException through
    their broad `except Exception -> 502` (learn's `_agent_turn_or_http_error`,
    quiz generation, notes), so it reaches the client as itself instead of as
    "the tutor had trouble". The SSE tutor maps it to a terminal `error`
    event (services/chat_stream.py)."""

    def __init__(self, *, limit: int | None, used: int | None, reset_at: datetime,
                 source: str = ""):
        self.limit = limit
        self.used = used
        self.reset_at = reset_at
        self.source = source
        self.code = ERROR_CODE
        seconds = max(1, math.ceil((reset_at - datetime.now(timezone.utc)).total_seconds()))
        super().__init__(
            status_code=429,
            detail=user_message(reset_at),
            headers={"Retry-After": str(seconds)},
        )

    @property
    def reset_at_iso(self) -> str:
        return self.reset_at.astimezone(timezone.utc).isoformat()

    def __reduce__(self):
        # Keyword-only __init__: the default reduce would call it with
        # HTTPException's positional args. Pickled across the job worker /
        # DBOS boundary like _resilience's ForcedOutageError.
        return _rebuild_budget_error, (self.limit, self.used, self.reset_at, self.source)


def _rebuild_budget_error(limit, used, reset_at, source) -> LLMBudgetExceeded:
    return LLMBudgetExceeded(limit=limit, used=used, reset_at=reset_at, source=source)


def next_reset(now: datetime | None = None) -> datetime:
    """The next UTC midnight — when every daily budget resets (the same
    boundary `llm_budget_status` reports)."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


def user_message(reset_at: datetime, *, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    hours = (reset_at - now).total_seconds() / 3600
    when = "in under an hour" if hours < 1 else f"in about {math.ceil(hours)} hour" + (
        "" if math.ceil(hours) == 1 else "s"
    )
    return (
        "You've reached today's limit for AI features. It resets at midnight UTC "
        f"({when})."
    )


def budget_error_in(exc: BaseException | None) -> LLMBudgetExceeded | None:
    """The LLMBudgetExceeded inside `exc` — itself, its cause/context chain, or
    an ExceptionGroup member — or None."""
    seen: set[int] = set()
    stack = [exc]
    while stack:
        cur = stack.pop()
        if cur is None or id(cur) in seen:
            continue
        seen.add(id(cur))
        if isinstance(cur, LLMBudgetExceeded):
            return cur
        if isinstance(cur, BaseExceptionGroup):
            stack.extend(cur.exceptions)
        stack.extend((cur.__cause__, cur.__context__))
    return None


def reraise_budget_refusal(exc: BaseException | None) -> None:
    """Re-raise the budget refusal inside `exc` (:func:`budget_error_in`), else
    return. For a route's broad failure ``except`` (the one that maps model /
    transport errors to its generic 502), called first::

        except Exception as e:
            llm_budget.reraise_budget_refusal(e)
            raise HTTPException(502, ...) from e

    so a refused run reaches the student as the friendly 429 (main.py's
    LLMBudgetExceeded handler: `error.code` = ERROR_CODE, `error.reset_at`,
    `Retry-After`) the tutor and uploads answer with, not as "generation
    failed". Quiz routes convert the refusal to their own coded 429 instead."""
    refusal = budget_error_in(exc)
    if refusal is not None:
        raise refusal


# ── status ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BudgetStatus:
    limit: int | None  # None = unlimited
    used: int
    source: str
    reset_at: datetime
    #: time.time() of the read this came from (0: unknown, so every live
    #: reservation counts on top of it).
    read_at: float = field(default=0.0, compare=False)

    @property
    def exceeded(self) -> bool:
        return self.limit is not None and self.used >= self.limit


def _parse_ts(raw: Any) -> datetime:
    ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def parse_status(payload: Any) -> BudgetStatus:
    """The `llm_budget_status` JSON (PostgREST returns a scalar function's
    value bare; tolerate a one-element list too)."""
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if isinstance(payload, dict) and "llm_budget_status" in payload:
        payload = payload["llm_budget_status"]
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected llm_budget_status payload: {type(payload).__name__}")
    limit = payload.get("limit")
    return BudgetStatus(
        limit=None if limit is None else int(limit),
        used=int(payload.get("used") or 0),
        source=str(payload.get("source") or "none"),
        reset_at=_parse_ts(payload["reset_at"]),
    )


@runs_as_service  # #115: llm_usage / llm_budgets are service-only (bucket E)
def read_status(user_id: str, *, timeout: float | None = None) -> BudgetStatus:
    """One `llm_budget_status` round trip, bounded by `timeout` (None: the
    client default). Raises on any failure."""
    from db.connection import rpc

    return parse_status(rpc("llm_budget_status", {"p_user_id": user_id}, timeout=timeout))


_cache: dict[str, tuple[float, BudgetStatus | None]] = {}
_cache_lock = threading.Lock()
#: The last status each user's read RETURNED (until its reset): what a failed
#: read falls back to instead of failing fully open.
_last_good: dict[str, BudgetStatus] = {}
#: Each run admitted per user and not yet known to be in a read, as
#: [admitted_at, settled_at | None] (settled = its usage row was queued).
_reservations: dict[str, list[list[float | None]]] = {}


def clear_llm_budget_cache(user_id: str | None = None) -> None:
    """Drop cached statuses, last good reads and reservations (one user's, or
    all). The admin budget writes call this; the autouse test fixture too."""
    with _cache_lock:
        if user_id is None:
            _cache.clear()
            _last_good.clear()
            _reservations.clear()
        else:
            _cache.pop(user_id, None)
            _last_good.pop(user_id, None)
            _reservations.pop(user_id, None)


def _cached(user_id: str) -> tuple[bool, BudgetStatus | None]:
    with _cache_lock:
        hit = _cache.get(user_id)
        if hit is None:
            return False, None
        expires, status = hit
        if time.time() >= expires:
            _cache.pop(user_id, None)
            return False, None
        return True, status


def _remember(user_id: str, status: BudgetStatus | None, *, failed: bool = False) -> None:
    now = time.time()
    if status is None or failed:
        expires = min(now + FAILURE_TTL_S,
                      status.reset_at.timestamp() if status is not None else math.inf)
    else:
        expires = min(now + STATUS_TTL_S, status.reset_at.timestamp())
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX and user_id not in _cache:
            _cache.pop(next(iter(_cache)), None)
        _cache[user_id] = (expires, status)


async def status_for(user_id: str) -> BudgetStatus | None:
    """The user's status (cached), or None when it could not be read in time
    (the caller fails open)."""
    hit, status = _cached(user_id)
    if hit:
        return status
    try:
        # Bounded by the RPC's own timeout, not asyncio.wait_for around the
        # thread: a wait_for would return on time but leave the thread (and
        # its HTTP call) running past it, one leaked thread per slow read.
        status = await asyncio.to_thread(read_status, user_id, timeout=STATUS_TIMEOUT_S)
    except Exception as exc:
        # Not fully open when this user has been read today: the last good
        # status plus every reservation since still bounds a burst.
        status = _last_good_for(user_id)
        logger.warning(
            "llm budget status unreadable for user=%s (%s); %s",
            user_id, type(exc).__name__,
            "allowing the run" if status is None else "using the last good read",
        )
        _remember(user_id, status, failed=True)
        return status
    status = replace(status, read_at=time.time())
    with _cache_lock:
        _last_good[user_id] = status
        if len(_last_good) > _CACHE_MAX:
            _last_good.pop(next(iter(_last_good)), None)
    _remember(user_id, status)
    return status


def _last_good_for(user_id: str) -> BudgetStatus | None:
    with _cache_lock:
        status = _last_good.get(user_id)
    if status is None or time.time() >= status.reset_at.timestamp():
        return None
    return status


def _admit(user_id: str, status: BudgetStatus) -> BudgetStatus | None:
    """Check-and-reserve, atomically: None when the run may start (and one
    reservation is recorded), else the status to refuse with (``used``
    including the reservations). One lock around both, so N parallel first
    requests cannot all read "under budget" off the same cached status:
    each sees the reservations of the ones admitted before it.

    Per process: two replicas each admit their own share between status
    reads, but every read brings in the other's landed usage."""
    if status.limit is None:
        return None
    now = time.time()
    read_at = status.read_at or now
    with _cache_lock:
        live = [r for r in _reservations.get(user_id, ()) if _pending(r, now=now, read_at=read_at)]
        used = status.used + len(live) * RESERVE_TOKENS_PER_RUN
        if used >= status.limit:
            _reservations[user_id] = live
            return replace(status, used=used)
        live.append([now, None])
        _reservations[user_id] = live
    return None


def _pending(reservation: list[float | None], *, now: float, read_at: float) -> bool:
    """Is this reservation's usage still missing from a status read at
    ``read_at``? In flight: yes, up to LAND_LAG_S (a run that never reports
    its usage stops counting then). Settled: only while its row may not
    have landed before the read."""
    admitted_at, settled_at = reservation
    if settled_at is None:
        return admitted_at > now - LAND_LAG_S
    return settled_at > read_at - SETTLE_LAG_S


def note_usage_recorded(user_id: str | None) -> None:
    """A foreground run for ``user_id`` just queued its usage row: settle its
    reservation (the oldest unsettled one), so a status read past
    SETTLE_LAG_S stops counting it on top of the real usage. Never raises."""
    if not user_id or _BACKGROUND.get():
        return
    now = time.time()
    with _cache_lock:
        for reservation in _reservations.get(user_id, ()):
            if reservation[1] is None:
                reservation[1] = now
                return


# ── the gate ────────────────────────────────────────────────────────────────


def starts_run(messages: Any) -> bool:
    """Is this model request the FIRST of an agent run? The last message of
    every later request in a run carries a tool return (the tool loop) or a
    retry prompt (output validation); the first carries the user prompt /
    instructions."""
    from pydantic_ai.messages import BaseToolReturnPart, RetryPromptPart

    try:
        last = messages[-1] if messages else None
        earlier = len(messages) > 1
    except Exception:
        return True
    parts = getattr(last, "parts", None) or ()
    if not parts and earlier:
        # pydantic-ai's re-send after an empty model response is an EMPTY
        # ModelRequest(parts=[]) appended to the run's own messages: the same
        # run asking again, not a new one.
        return False
    return not any(isinstance(p, (BaseToolReturnPart, RetryPromptPart)) for p in parts)


async def _flag_on(user_id: str) -> bool:
    """`llm_budget` for this user, without I/O when the flag cache can answer
    and off the event loop when it can't. Any failure reads as off."""
    try:
        from services import feature_flags

        resolution = await feature_flags.explain_off_loop(FLAG_KEY, user_id)
        return resolution.variant == "on"
    except Exception:
        logger.warning("llm_budget flag unreadable; treating as off", exc_info=True)
        return False


#: Set inside :func:`background_work`: nothing there is ever refused.
_BACKGROUND: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "sapling_llm_budget_background", default=False,
)
#: Key of the one-per-unit-of-work decision on the work's shared state:
#: (user_id, None) = allowed, (user_id, BudgetStatus) = refused.
_DECISION_KEY = "llm_budget_decision"


@contextlib.contextmanager
def background_work():
    """Mark the block as post-response / background LLM work: the budget never
    refuses it (only foreground work is refused — a refusal after the
    response has gone has nobody to tell, and would only lose the write the
    student's foreground work paid for). Its tokens still count."""
    token = _BACKGROUND.set(True)
    try:
        yield
    finally:
        _BACKGROUND.reset(token)


def _refusal(status: BudgetStatus) -> LLMBudgetExceeded:
    return LLMBudgetExceeded(
        limit=status.limit, used=status.used, reset_at=status.reset_at, source=status.source,
    )


async def check_before_request(messages: Any) -> None:
    """Raise :class:`LLMBudgetExceeded` when this request would start a
    foreground run for a user who has spent today's budget, deciding at most
    once per unit of work (see the module docstring for every condition).
    Otherwise return; never raises anything else."""
    from services.request_context import current_acting_user, current_work_state

    if _BACKGROUND.get():
        return
    user_id = current_acting_user()
    if not user_id or not starts_run(messages):
        return
    state = current_work_state()
    prior = state.get(_DECISION_KEY) if state is not None else None
    if isinstance(prior, tuple) and len(prior) == 2 and prior[0] == user_id:
        if prior[1] is None:
            return  # this request/job already passed the gate
        raise _refusal(prior[1])
    refused: BudgetStatus | None = None
    if await _flag_on(user_id):
        status = await status_for(user_id)
        if status is not None:
            refused = _admit(user_id, status)
    if state is not None:
        state[_DECISION_KEY] = (user_id, refused)
    if refused is None:
        return
    logger.warning(
        "llm budget reached: user=%s used=%d limit=%d source=%s; refusing the run",
        user_id, refused.used, refused.limit, refused.source,
    )
    raise _refusal(refused)
