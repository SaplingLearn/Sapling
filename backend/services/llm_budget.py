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
rows themselves land through events_service's async queue, so the budget is
approximate by a few seconds plus the TTL either way.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from db.scope import runs_as_service

logger = logging.getLogger("sapling.llm_budget")

FLAG_KEY = "llm_budget"
ERROR_CODE = "LLM_BUDGET_EXCEEDED"

#: How long a user's status is trusted before it is read again.
STATUS_TTL_S = 30.0
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


# ── status ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BudgetStatus:
    limit: int | None  # None = unlimited
    used: int
    source: str
    reset_at: datetime

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


def clear_llm_budget_cache(user_id: str | None = None) -> None:
    """Drop cached statuses (one user's, or all). The admin budget writes call
    this; the autouse test fixture too."""
    with _cache_lock:
        if user_id is None:
            _cache.clear()
        else:
            _cache.pop(user_id, None)


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


def _remember(user_id: str, status: BudgetStatus | None) -> None:
    now = time.time()
    if status is None:
        expires = now + FAILURE_TTL_S
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
        logger.warning(
            "llm budget status unreadable for user=%s (%s); allowing the run",
            user_id, type(exc).__name__,
        )
        status = None
    _remember(user_id, status)
    return status


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
        if status is not None and status.exceeded:
            refused = status
    if state is not None:
        state[_DECISION_KEY] = (user_id, refused)
    if refused is None:
        return
    logger.warning(
        "llm budget reached: user=%s used=%d limit=%d source=%s; refusing the run",
        user_id, refused.used, refused.limit, refused.source,
    )
    raise _refusal(refused)
