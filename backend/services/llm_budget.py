"""Per-user daily LLM token budget (#119, plan phase 5). Flag: `llm_budget`.

Budgets live in `llm_budgets` (migration 20261108213311): a global default row,
plus role (roles.slug) and per-user overrides, edited at /api/admin/llm. The
SQL function `llm_budget_status(user)` resolves the user's limit (user row ->
the most generous of their role rows -> default) and sums today's (UTC)
`llm_usage.total_tokens` for them in one indexed round trip.

Enforcement is at the LLM chokepoint: `agents/_providers.py`'s resilient
models call :func:`check_before_request` before every model request, and it
refuses — with :class:`LLMBudgetExceeded`, a 429 — only when ALL hold:

* there is a session user (``request_context.current_session_user``). Work
  with no user — the index sweeper, the job worker, scripts, evals — is never
  budgeted;
* the request STARTS a run (:func:`starts_run`): a tool loop's later requests
  and pydantic-ai's output-validation retries are let through, so a run that
  began under budget is never cut off halfway (one run of overshoot is the
  price of never failing a turn after its tools wrote);
* the `llm_budget` flag is on for that user (per user: role rules and
  rollouts apply);
* the user's resolved limit is not NULL (unlimited) and today's usage has
  reached it.

Function mode (the E2E lanes, the unit lane's FunctionModels) never builds a
resilient model, so it never meets this module. A fallback model is not
checked again — it is the same run.

Fails OPEN, like the quiz spend cap (#544 F1): an unreadable flag, a status
read that errors or takes longer than ``STATUS_TIMEOUT_S`` lets the run
through with a warning. This is a cost control, not an authorization gate,
and denying every student because a usage read blipped is worse than the
spend it would save.

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
import logging
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
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
#: Bound on one status read; past it the run fails open.
STATUS_TIMEOUT_S = 2.5
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

    def __init__(self, *, limit: int, used: int, reset_at: datetime, source: str = ""):
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
def read_status(user_id: str) -> BudgetStatus:
    """One `llm_budget_status` round trip. Raises on any failure."""
    from db.connection import rpc

    return parse_status(rpc("llm_budget_status", {"p_user_id": user_id}))


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
        status = await asyncio.wait_for(
            asyncio.to_thread(read_status, user_id), timeout=STATUS_TIMEOUT_S
        )
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
    except Exception:
        return True
    parts = getattr(last, "parts", None) or ()
    return not any(isinstance(p, (BaseToolReturnPart, RetryPromptPart)) for p in parts)


async def _flag_on(user_id: str) -> bool:
    """`llm_budget` for this user, without I/O when the flag cache can answer
    and off the event loop when it can't. Any failure reads as off."""
    try:
        from services import feature_flags

        resolution = feature_flags.cached_explain(FLAG_KEY, user_id)
        if resolution is None:
            resolution = await asyncio.to_thread(feature_flags.explain, FLAG_KEY, user_id)
        return resolution.variant == "on"
    except Exception:
        logger.warning("llm_budget flag unreadable; treating as off", exc_info=True)
        return False


async def check_before_request(messages: Any) -> None:
    """Raise :class:`LLMBudgetExceeded` when this request would start a run
    for a user who has spent today's budget (see the module docstring for
    every condition). Otherwise return; never raises anything else."""
    from services.request_context import current_session_user

    user_id = current_session_user()
    if not user_id or not starts_run(messages):
        return
    if not await _flag_on(user_id):
        return
    status = await status_for(user_id)
    if status is None or not status.exceeded:
        return
    logger.warning(
        "llm budget reached: user=%s used=%d limit=%d source=%s; refusing the run",
        user_id, status.used, status.limit, status.source,
    )
    raise LLMBudgetExceeded(
        limit=status.limit, used=status.used, reset_at=status.reset_at, source=status.source,
    )
