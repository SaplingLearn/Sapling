"""Per-student AI cost guard: caps, degradation ladder, rate limit (spec §3.5, §13 A20). PKG-06b.

Outside backend/learning/ (spec §2, §12): reads llm_usage, never calls a model. Every grader,
grader_second, decision, loop_tutor* and session_close run site calls ``ai_budget.check(`` first
(invariant 23) and turns ``level == "hard"`` into "no model call", never into a verdict (spec §3.5
validity rule, invariant 28). ONE paged llm_usage read since the UTC month start, cached per
server-minted request key — no lru_cache (CLAUDE.md #98); tests/conftest.py resets the module state around every test.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Literal, NamedTuple, get_args

from fastapi import Request, status
from fastapi.responses import JSONResponse

import config
from db.connection import page_all, rpc, table
from learning import params
from learning.policy import Band, BudgetLevel, Tier
from services.auth_guard import get_session_user_id
from services.events_service import log_event
from services.request_context import current_request_id, current_request_key

logger = logging.getLogger("sapling.ai_budget")

Kind = Literal["tutor", "grader", "decision", "close"]
Scope = Literal[
    "daily_usd",
    "monthly_usd",
    "daily_tokens",
    "daily_tutor_calls",
    "session_requests",
    "session_deep",
    "daily_grades",
    "rate_limit",
    "platform",
]
EventLevel = Literal["soft", "hard", "grader_cap"]

BUDGET_CAPPED_EVENT = "ai.budget_capped"  # spec §6
BUDGET_REACHED_DETAIL = "ai budget reached"  # spec §3.5 / A20 429 body
GRADE_TASKS = frozenset({"grader", "grader_second", "decision"})  # spec §3.5 STUDENT_DAILY_GRADES
RATE_LIMIT_WINDOW_S = 60  # spec §3.5: LEARN_RATE_LIMIT_PER_MIN counts rows in the last 60 s
_REQUEST_CACHE_MAX = 512  # entries; a memory bound, not a policy threshold
# † How long one cached summary may serve its request key. The key is server-minted per request
# (request_context.current_request_key, owner decision 06b g), so a client can no longer share
# one entry across requests; the expiry stays as a belt (a real request checks within seconds).
_REQUEST_CACHE_TTL_S = 5.0
_DECEMBER = 12
_USAGE_COLUMNS = "id,cost_usd,total_tokens,task,created_at"
_PLATFORM_COLUMNS = "id,cost_usd,created_at"
_USAGE_ORDER = "created_at.asc,id.asc"  # page_all needs a total order
# spec §3.5 tie order among the hard scopes (Behaviour 4: the binding scope is the latest reset)
_HARD_ORDER: tuple[Scope, ...] = (
    "daily_usd",
    "monthly_usd",
    "daily_tokens",
    "daily_tutor_calls",
    "session_requests",
    "rate_limit",
)
_USD_SCOPES: frozenset[str] = frozenset({"daily_usd", "monthly_usd"})
# The tutor-call COUNT cap (owner decision A38): its own table, written directly — never through
# events_service — so it holds when llm_usage cost reads wrong (#689) or no rows are written
# (EVENTS_LOGGING_ENABLED=false). Migration 20260929050404_learning_ai_tutor_daily_calls.sql.
_TUTOR_CALLS_TABLE = "ai_tutor_daily_calls"
_TUTOR_CALLS_RPC = "ai_budget_bump_tutor_calls"


@dataclass(frozen=True)
class BudgetDecision:
    """spec §3.5. ``tier_ceiling`` caps what policy.model_tier may choose; ``pause_novice``
    (tutor kind, hard level) = serve no check for a novice-band concept on any surface except the probe.
    ``session_capped`` = the session's tutor-request counter is at LOOP_SESSION_MAX_TUTOR_REQUESTS,
    whatever ``scope`` reports: that session stays paused past ``reset_at``, so the banner says
    "for this session" (owner decision 06b j; the copy is PKG-13's)."""

    level: BudgetLevel
    tier_ceiling: Tier
    scope: Scope | None = None
    reset_at: datetime | None = None
    pause_novice: bool = False
    session_capped: bool = False


_NORMAL = BudgetDecision(level="normal", tier_ceiling="deep")


@dataclass(frozen=True)
class _Usage:
    month_usd: Decimal
    day_usd: Decimal
    day_tokens: int
    day_grades: int
    minute_rows: int
    minute_stamps: tuple[datetime, ...]  # the window's rows, oldest first (the rate-limit reset)


class _EmitKey(NamedTuple):
    user: str
    scope: str
    level: str
    day: str


_lock = threading.Lock()
_emitted: set[_EmitKey] = set()
# key → (stamped at, summary); a None summary is a failed read, cached so the request's later
# checks fail open without another round trip
_request_cache: dict[tuple[str, str], tuple[float, _Usage | None]] = {}
_platform_checked_at: float | None = None
# (user, UTC day iso) → this process's tutor calls: the fallback when the store fails, and a floor
# under the store's count (a lost increment never lowers what this process has seen). Only
# today's keys are kept.
_tutor_calls_local: dict[tuple[str, str], int] = {}
# (request key, user, UTC day) → (stamped at, the store's count or None on a failed read): the
# tutor-call read shares _usage's per-request key and TTL (A38 fix round, m2)
_tutor_calls_cache: dict[tuple[str, str, str], tuple[float, int | None]] = {}


def _utcnow() -> datetime:
    """The module clock; tests monkeypatch it."""
    return datetime.now(timezone.utc)


def _clock() -> float:
    """Monotonic seconds for the request cache and the platform interval; tests monkeypatch it."""
    return time.monotonic()


def _emit_capped(
    user_id: str | None,
    scope: Scope,
    level: EventLevel,
    *,
    band: Band | None = None,
    spent_usd: float | None = None,
    cap_usd: float | None = None,
) -> None:
    """ai.budget_capped, at most once per process per (user, scope, level, UTC day) (spec §3.5)."""
    day = _utcnow().date().isoformat()
    key = _EmitKey(user_id or "platform", scope, level, day)
    with _lock:
        if key in _emitted:
            return
        _emitted.difference_update({k for k in _emitted if k.day != day})  # keep only today's keys
        _emitted.add(key)
    payload = {
        "user_id": user_id,
        "scope": scope,
        "band": band,
        "level": level,
        "spent_usd": spent_usd,
        "cap_usd": cap_usd,
    }
    log_event(
        BUDGET_CAPPED_EVENT,
        category="usage",
        user_id=user_id,
        payload={k: v for k, v in payload.items() if v is not None},
    )


def reset_for_tests() -> None:
    """Clear the per-process state (tests/conftest.py::_reset_ai_budget)."""
    global _platform_checked_at
    with _lock:
        _emitted.clear()
        _request_cache.clear()
        _tutor_calls_local.clear()
        _tutor_calls_cache.clear()
        _platform_checked_at = None


# ── time helpers (UTC) ────────────────────────────────────────────────────────
def _day_start(now: datetime) -> datetime:
    return now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _next_day(now: datetime) -> datetime:
    return _day_start(now) + timedelta(days=1)


def _month_start(now: datetime) -> datetime:
    return _day_start(now).replace(day=1)


def _next_month(now: datetime) -> datetime:
    start = _month_start(now)
    if start.month == _DECEMBER:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: object) -> datetime | None:
    """A PostgREST timestamptz; naive → UTC; unparseable → None (the row is skipped)."""
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str):
        try:
            ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


# ── the one usage read ────────────────────────────────────────────────────────
def _exact(value: object) -> Decimal:
    """A $ amount or a fraction as an exact decimal. llm_usage.cost_usd is numeric(12,6) and
    every cap is a decimal literal, so "≥" compares decimals: in float, 0.8 × 0.20 is
    0.16000000000000003 and ten 0.02 rows sum to 0.19999999999999998 (spend AT a threshold
    would miss it). NULL → 0."""
    return Decimal(str(value or 0))


def _daily_cap(band: Band | None) -> Decimal:
    """spec §3.5: the band's daily $ cap; novice turns run to the novice allowance."""
    multiplier = _exact(config.BUDGET_NOVICE_MULTIPLIER) if band == "novice" else 1
    return _exact(config.STUDENT_DAILY_BUDGET_USD) * multiplier


def _rate_reset(usage: _Usage, now: datetime) -> datetime:
    """When the rate limit lifts (Behaviour 4: never an early resume): once all but
    LEARN_RATE_LIMIT_PER_MIN − 1 of the window's rows have aged out, i.e. the
    (minute_rows − LEARN_RATE_LIMIT_PER_MIN + 1)-th oldest + RATE_LIMIT_WINDOW_S. With exactly the
    limit in the window that is the oldest row; concurrent calls and the events-queue lag can
    land more."""
    stamps = usage.minute_stamps
    if not stamps:
        return now + timedelta(seconds=RATE_LIMIT_WINDOW_S)
    lifts_after = min(max(len(stamps) - config.LEARN_RATE_LIMIT_PER_MIN, 0), len(stamps) - 1)
    return stamps[lifts_after] + timedelta(seconds=RATE_LIMIT_WINDOW_S)


def _spend_fields(scope: Scope, usage: _Usage | None, cap: Decimal | None = None) -> dict:
    """Behaviour 5: spent_usd = the month's $ for monthly_usd, else today's; cap_usd only for
    the $ scopes (``cap`` = the band's daily cap). Nothing when the read failed (None values
    are omitted, never zeroed). Floats: the event payload is JSON."""
    if usage is None:
        return {}
    spent = usage.month_usd if scope == "monthly_usd" else usage.day_usd
    cap_usd = None
    if scope in _USD_SCOPES:
        cap_usd = config.STUDENT_MONTHLY_BUDGET_USD if scope == "monthly_usd" else float(cap)
    return {"spent_usd": float(spent), "cap_usd": cap_usd}


def _binding(hard: dict[Scope, datetime | None]) -> Scope:
    """Behaviour 4: the triggered scope whose reset is LATEST, so a pause banner never promises
    an early resume (max keeps the first in _HARD_ORDER on a tie); session_requests (reset None)
    only when no timed scope triggered."""
    timed = [s for s in _HARD_ORDER if hard.get(s) is not None]
    if timed:
        return max(timed, key=lambda s: hard[s])
    return next(s for s in _HARD_ORDER if s in hard)


def _load_rows(user_id: str, since: datetime) -> list[dict]:
    """Every llm_usage row of the user since ``since``: one logical read, paged past max_rows."""
    return list(
        page_all(
            table("llm_usage"),
            _USAGE_COLUMNS,
            filters={"user_id": f"eq.{user_id}", "created_at": f"gte.{_iso(since)}"},
            order=_USAGE_ORDER,
        )
    )


def _summarise(rows: list[dict], now: datetime) -> _Usage:
    day0, minute0 = _day_start(now), now - timedelta(seconds=RATE_LIMIT_WINDOW_S)
    month_usd = day_usd = Decimal(0)
    day_tokens = day_grades = 0
    minute: list[datetime] = []
    for row in rows:
        ts = _parse_ts(row.get("created_at"))
        if ts is None:
            continue
        cost = _exact(row.get("cost_usd"))
        month_usd += cost
        if ts >= day0:
            day_usd += cost
            day_tokens += int(row.get("total_tokens") or 0)
            day_grades += row.get("task") in GRADE_TASKS
        if ts >= minute0:
            minute.append(ts)
    return _Usage(month_usd, day_usd, day_tokens, day_grades, len(minute), tuple(sorted(minute)))


def _usage(user_id: str) -> _Usage | None:
    """One llm_usage read per (request, user); None on a read error (fail open). A failed read
    is cached like a summary: grade() checks up to three times, and each retry of a hanging
    PostgREST would block again for up to the client's timeout (one WARNING per read)."""
    # the SERVER-minted key, never the client's X-Request-ID (owner decision 06b g)
    rkey = current_request_key()
    key = (rkey, user_id) if rkey else None
    if key is not None:
        with _lock:
            hit = _request_cache.get(key)
        if hit is not None and _clock() - hit[0] < _REQUEST_CACHE_TTL_S:
            return hit[1]
    now = _utcnow()
    summary: _Usage | None
    try:
        rows = _load_rows(user_id, _month_start(now))
    except Exception as exc:  # fail open — see HANDOFF-06b Open questions (b)
        logger.warning("ai_budget: llm_usage read failed for %s: %s", user_id, exc)
        summary = None
    else:
        summary = _summarise(rows, now)
    if key is not None:
        with _lock:
            _request_cache.pop(key, None)  # a refreshed key moves to the back of the FIFO
            if len(_request_cache) >= _REQUEST_CACHE_MAX:
                _request_cache.pop(next(iter(_request_cache)))
            _request_cache[key] = (_clock(), summary)
    return summary


# ── the tutor-call count (owner decision A38) ────────────────────────────────
def _local_calls(user_id: str, day: str, bump: bool) -> int:
    with _lock:
        stale = [k for k in _tutor_calls_local if k[1] != day]
        for k in stale:
            del _tutor_calls_local[k]
        key = (user_id, day)
        if bump:
            _tutor_calls_local[key] = _tutor_calls_local.get(key, 0) + 1
        return _tutor_calls_local.get(key, 0)


def _as_count(value: object) -> int:
    """The RPC's scalar integer (PostgREST answers a bare JSON number); anything else raises."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"unexpected tutor call count {value!r}")
    return value


def count_tutor_call(user_id: str) -> int:
    """Count one tutor model call for the student today (UTC) and return the new count. PKG-07
    calls it once per tutor run; nothing else does. The store increment is one atomic statement
    (cross-worker); if it fails, the in-process counter still counts (one WARNING), so the cap
    is never blind. Never raises for a store failure; never creates or biases evidence."""
    if not user_id:
        return 0
    day = _utcnow().date().isoformat()
    local = _local_calls(user_id, day, bump=True)
    try:
        stored = _as_count(rpc(_TUTOR_CALLS_RPC, {"p_user_id": user_id, "p_day": day}))
    except Exception as exc:
        logger.warning(
            "ai_budget: tutor call counter increment failed for %s, counting in-process: %s",
            user_id,
            exc,
        )
        return local
    _cache_tutor_calls(user_id, day, stored)  # the request's later checks see this call
    return max(stored, local)


def _tutor_calls_key(user_id: str, day: str) -> tuple[str, str, str] | None:
    rkey = current_request_key()
    return (rkey, user_id, day) if rkey else None


def _cache_tutor_calls(user_id: str, day: str, stored: int | None) -> None:
    key = _tutor_calls_key(user_id, day)
    if key is None:
        return
    with _lock:
        _tutor_calls_cache.pop(key, None)  # a refreshed key moves to the back of the FIFO
        if len(_tutor_calls_cache) >= _REQUEST_CACHE_MAX:
            _tutor_calls_cache.pop(next(iter(_tutor_calls_cache)))
        _tutor_calls_cache[key] = (_clock(), stored)


def _tutor_calls_today(user_id: str, now: datetime) -> int:
    """Today's tutor calls: the store's count, never below this process's own; this process's
    alone when the read fails (one WARNING per read). The store read is cached like _usage's:
    one per (server-minted request key, user, day) for at most _REQUEST_CACHE_TTL_S, a failed
    read included; count_tutor_call refreshes the entry with the count it wrote."""
    day = now.date().isoformat()
    local = _local_calls(user_id, day, bump=False)
    key = _tutor_calls_key(user_id, day)
    if key is not None:
        with _lock:
            hit = _tutor_calls_cache.get(key)
        if hit is not None and _clock() - hit[0] < _REQUEST_CACHE_TTL_S:
            return local if hit[1] is None else max(hit[1], local)
    stored: int | None
    try:
        rows = table(_TUTOR_CALLS_TABLE).select(
            "calls", filters={"user_id": f"eq.{user_id}", "day": f"eq.{day}"}
        )
        stored = _as_count(rows[0]["calls"]) if rows else 0
    except Exception as exc:
        logger.warning(
            "ai_budget: tutor call counter read failed for %s, using the in-process count: %s",
            user_id,
            exc,
        )
        stored = None
    _cache_tutor_calls(user_id, day, stored)
    return local if stored is None else max(stored, local)


# ── the ladder ────────────────────────────────────────────────────────────────
def _grade_decision(user_id: str, usage: _Usage | None, now: datetime) -> BudgetDecision:
    """The grader cap (spec §3.5): grading has its own cap, so a tutor-hard student still grades."""
    if usage is None or usage.day_grades < config.STUDENT_DAILY_GRADES:
        return _NORMAL
    _emit_capped(user_id, "daily_grades", "grader_cap", **_spend_fields("daily_grades", usage))
    return BudgetDecision(
        level="hard", tier_ceiling="none", scope="daily_grades", reset_at=_next_day(now)
    )


def _emit_each(
    user_id: str,
    scopes: list[Scope],
    level: EventLevel,
    band: Band | None,
    usage: _Usage | None,
    cap: Decimal,
) -> None:
    """spec §3.5: EVERY cap hit emits ai.budget_capped, not only the scope the decision reports,
    so the §10 cap_hits counts (keyed scope/level) see every cap that was reached."""
    for scope in scopes:
        _emit_capped(user_id, scope, level, band=band, **_spend_fields(scope, usage, cap))


def _spend_decision(
    user_id: str,
    kind: Kind,
    band: Band | None,
    usage: _Usage | None,
    now: datetime,
    *,
    tutor_requests: int,
    deep_requests: int,
    arm_session: bool,
    tutor_calls: int = 0,
) -> BudgetDecision:
    cap = _daily_cap(band)
    hard: dict[Scope, datetime | None] = {}
    if usage is not None:
        if usage.day_usd >= cap:
            hard["daily_usd"] = _next_day(now)
        if usage.month_usd >= _exact(config.STUDENT_MONTHLY_BUDGET_USD):
            hard["monthly_usd"] = _next_month(now)
        if usage.day_tokens >= config.STUDENT_DAILY_TOKENS:
            hard["daily_tokens"] = _next_day(now)
        if kind == "tutor" and usage.minute_rows >= config.LEARN_RATE_LIMIT_PER_MIN:
            hard["rate_limit"] = _rate_reset(usage, now)
    if kind == "tutor" and tutor_calls >= config.STUDENT_DAILY_TUTOR_CALLS:
        hard["daily_tutor_calls"] = _next_day(now)  # read outside llm_usage: holds when it fails
    if kind == "tutor" and tutor_requests >= params.LOOP_SESSION_MAX_TUTOR_REQUESTS:
        hard["session_requests"] = None
    if hard:
        scope = _binding(hard)
        _emit_each(user_id, [s for s in _HARD_ORDER if s in hard], "hard", band, usage, cap)
        # A 60-second burst pauses tutor turns but never drops novice-band concepts from review
        # or the check surfaces (spec §3.5 hard row): pause_novice needs a trigger besides it.
        return BudgetDecision(
            level="hard",
            tier_ceiling="none",
            scope=scope,
            reset_at=hard[scope],
            pause_novice=kind == "tutor" and set(hard) != {"rate_limit"},
            session_capped="session_requests" in hard,
        )
    if kind == "close":
        return _NORMAL  # one call, nothing to downgrade: the close has no soft level
    soft: list[Scope] = []
    fraction = _exact(config.STUDENT_SOFT_FRACTION)
    if usage is not None and usage.day_usd >= fraction * cap:
        soft.append("daily_usd")
    if usage is not None and usage.day_tokens >= fraction * config.STUDENT_DAILY_TOKENS:
        soft.append("daily_tokens")
    deep_cap = (
        params.LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE
        if band == "novice"
        else params.LOOP_SESSION_MAX_DEEP_REQUESTS
    )
    if deep_requests >= deep_cap:
        soft.append("session_deep")
    if not soft:
        return _NORMAL
    scope = soft[0]
    _emit_each(user_id, soft, "soft", band, usage, cap)
    if arm_session:
        return _NORMAL  # arms are exempt from downgrades; they pause at hard (spec §3.5)
    # The $- and token-based soft level never downgrades novice deep turns; only the novice
    # deep-request cap does (spec §3.5 soft row, LOOP_MODEL_TIER).
    novice_keeps_deep = band == "novice" and "session_deep" not in soft
    if band == "novice" and "session_deep" in soft:
        # Owner decision 06b(k): report the scope that CAUSED the drop to standard. For a novice
        # turn that is only ever the novice deep cap, whatever $/token soft scope came first.
        scope = "session_deep"
    return BudgetDecision(
        level="soft",
        tier_ceiling="deep" if novice_keeps_deep else "standard",
        scope=scope,
        reset_at=None if scope == "session_deep" else _next_day(now),
    )


def check(
    user_id: str,
    kind: Kind,
    band: Band | None = None,
    *,
    session_tutor_requests: int = 0,
    session_deep_requests: int = 0,
    arm_session: bool = False,
) -> BudgetDecision:
    """The degradation ladder of spec §3.5. Call it module-qualified — ``ai_budget.check(`` —
    before every grader, grader_second, decision, loop_tutor* and session_close run
    (invariant 23). ``band`` is required for ``tutor`` and ignored for the grader cap; the
    session counters are the ints PKG-07 keeps in sessions.loop_state. ``tutor`` also reads
    today's tutor-call count (``count_tutor_call``; hard at STUDENT_DAILY_TUTOR_CALLS) — one
    more read, outside llm_usage; the grader, decision and close kinds never read it."""
    if kind not in get_args(Kind):
        raise ValueError(f"ai_budget.check: unknown kind {kind!r}")
    if kind == "tutor" and band is None:
        raise ValueError("ai_budget.check: band is required for kind='tutor' (spec §3.5)")
    if band is not None and band not in get_args(Band):
        raise ValueError(f"ai_budget.check: unknown band {band!r}")
    _maybe_check_platform()
    if not user_id:
        return _NORMAL  # system actors carry no student budget
    usage, now = _usage(user_id), _utcnow()
    if kind in ("grader", "decision"):
        return _grade_decision(user_id, usage, now)
    return _spend_decision(
        user_id,
        kind,
        band,
        usage,
        now,
        tutor_requests=session_tutor_requests,
        deep_requests=session_deep_requests,
        arm_session=arm_session,
        tutor_calls=_tutor_calls_today(user_id, now) if kind == "tutor" else 0,
    )


# ── rate limit and the 429 (spec §3.5, §9, A20) ──────────────────────────────
class AIBudgetExceeded(Exception):
    """Over budget; main.py maps it to the §3.5 429 body. Raised by PKG-07 (tutor hard) and
    enforce_rate_limit."""

    def __init__(self, decision: BudgetDecision):
        super().__init__(BUDGET_REACHED_DETAIL)
        self.decision = decision


def _rate_limit_decision(user_id: str) -> tuple[BudgetDecision | None, _Usage | None]:
    usage = _usage(user_id)
    if usage is None or usage.minute_rows < config.LEARN_RATE_LIMIT_PER_MIN:
        return None, usage
    decision = BudgetDecision(
        level="hard",
        tier_ceiling="none",
        scope="rate_limit",
        reset_at=_rate_reset(usage, _utcnow()),
    )
    return decision, usage


def rate_limited(user_id: str) -> bool:
    """llm_usage rows of the user in the last RATE_LIMIT_WINDOW_S ≥ LEARN_RATE_LIMIT_PER_MIN.
    Cross-worker (it counts DB rows; Redis is off by default and services/request_limits.py is
    per-process); fails open on a read error."""
    return _rate_limit_decision(user_id)[0] is not None


def enforce_rate_limit_for(user_id: str) -> None:
    """The rate limit, callable inline where only SOME bodies of a route run a model
    (PKG-12's /review/answer checks it for kind="check" only — a self-rated flashcard
    runs none and is never rate-limited, spec §3.5)."""
    decision, usage = _rate_limit_decision(user_id)
    if decision is None:
        return
    _emit_capped(user_id, "rate_limit", "hard", **_spend_fields("rate_limit", usage))
    raise AIBudgetExceeded(decision)


def enforce_rate_limit(request: Request) -> None:
    """FastAPI dependency. PKG-07 attaches it to every model-calling /api/learn/loop/*
    route — never to GET /status or GET /sessions (spec §9). No session → 401 as today."""
    enforce_rate_limit_for(get_session_user_id(request))


async def budget_exceeded_handler(request: Request, exc: AIBudgetExceeded) -> JSONResponse:
    """HTTP 429 {"detail": "ai budget reached", "reset_at": <iso or null>} (spec §3.5, A20), plus
    the house request_id, the scope and session_capped (06b j); Retry-After (≥ 1 s) when the reset is known, rounded UP
    so a client that obeys it never retries before reset_at."""
    rid = getattr(request.state, "request_id", None) or current_request_id()
    reset_at = exc.decision.reset_at
    headers: dict[str, str] = {}
    if reset_at is not None:
        headers["Retry-After"] = str(max(1, math.ceil((reset_at - _utcnow()).total_seconds())))
    if rid:
        headers["X-Request-ID"] = rid
    content = {
        "detail": BUDGET_REACHED_DETAIL,
        "reset_at": reset_at.isoformat() if reset_at else None,
        "scope": exc.decision.scope,
        "session_capped": exc.decision.session_capped,
        "request_id": rid,
    }
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS, content=content, headers=headers
    )


# ── platform alert (alert-only; spec §3.5 PLATFORM_*) ─────────────────────────
def _spawn(fn: Callable[[], None]) -> None:
    """Off the request thread; tests replace it with an inline call."""
    threading.Thread(target=fn, name="ai-budget-platform", daemon=True).start()


def _maybe_check_platform() -> None:
    """At most one platform read per PLATFORM_CHECK_INTERVAL_S per process; none when unset."""
    global _platform_checked_at
    if config.PLATFORM_DAILY_BUDGET_USD is None:
        return
    now = _clock()
    with _lock:
        last = _platform_checked_at
        if last is not None and now - last < config.PLATFORM_CHECK_INTERVAL_S:
            return
        _platform_checked_at = now
    _spawn(_check_platform)


def _check_platform() -> None:
    """Today's spend over all users against PLATFORM_DAILY_BUDGET_USD. Never changes a decision."""
    budget = config.PLATFORM_DAILY_BUDGET_USD
    if budget is None:
        return
    try:
        rows = page_all(
            table("llm_usage"),
            _PLATFORM_COLUMNS,
            filters={"created_at": f"gte.{_iso(_day_start(_utcnow()))}"},
            order=_USAGE_ORDER,
        )
        spent = sum((_exact(row.get("cost_usd")) for row in rows), Decimal(0))
    except Exception as exc:
        logger.warning("ai_budget: platform spend read failed: %s", exc)
        return
    if spent >= _exact(config.PLATFORM_ALERT_FRACTION) * _exact(budget):
        logger.warning(
            "ai_budget: platform spend today is %s USD, at or above %s of the %s USD daily budget",
            spent,
            config.PLATFORM_ALERT_FRACTION,
            budget,
        )
        _emit_capped(None, "platform", "soft", spent_usd=float(spent), cap_usd=budget)
