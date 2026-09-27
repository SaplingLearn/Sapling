"""Per-student AI cost guard: caps, degradation ladder, rate limit (spec §3.5, §13 A20). PKG-06b.

Outside backend/learning/ (spec §2, §12): reads llm_usage, never calls a model. Every grader,
grader_second, decision, loop_tutor* and session_close run site calls ``ai_budget.check(`` first
(invariant 23) and turns ``level == "hard"`` into "no model call", never into a verdict (spec §3.5
validity rule, invariant 28). ONE paged llm_usage read since the UTC month start, cached per request
id — no lru_cache (CLAUDE.md #98); tests/conftest.py resets the module state around every test.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Literal, NamedTuple, get_args

from fastapi import Request, status
from fastapi.responses import JSONResponse

import config
from db.connection import page_all, table
from learning import params
from learning.policy import Band, BudgetLevel, Tier
from services.auth_guard import get_session_user_id
from services.events_service import log_event
from services.request_context import current_request_id

logger = logging.getLogger("sapling.ai_budget")

Kind = Literal["tutor", "grader", "decision", "close"]
Scope = Literal[
    "daily_usd",
    "monthly_usd",
    "daily_tokens",
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
# † How long one cached summary may serve its request id. RequestIDMiddleware trusts a
# caller-supplied X-Request-ID, so a client re-sending one id on every request would otherwise
# be judged forever on its first summary; a real request makes its checks within seconds.
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
    "session_requests",
    "rate_limit",
)
_USD_SCOPES: frozenset[str] = frozenset({"daily_usd", "monthly_usd"})


@dataclass(frozen=True)
class BudgetDecision:
    """spec §3.5. ``tier_ceiling`` caps what policy.model_tier may choose; ``pause_novice``
    (tutor kind, hard level) = serve no check for a novice-band concept on any surface except the probe."""

    level: BudgetLevel
    tier_ceiling: Tier
    scope: Scope | None = None
    reset_at: datetime | None = None
    pause_novice: bool = False


_NORMAL = BudgetDecision(level="normal", tier_ceiling="deep")


@dataclass(frozen=True)
class _Usage:
    month_usd: Decimal
    day_usd: Decimal
    day_tokens: int
    day_grades: int
    minute_rows: int
    minute_oldest: datetime | None


class _EmitKey(NamedTuple):
    user: str
    scope: str
    level: str
    day: str


_lock = threading.Lock()
_emitted: set[_EmitKey] = set()
_request_cache: dict[tuple[str, str], tuple[float, _Usage]] = {}  # key → (stamped at, summary)
_platform_checked_at: float | None = None


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
    return (usage.minute_oldest or now) + timedelta(seconds=RATE_LIMIT_WINDOW_S)


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
    day_tokens = day_grades = minute_rows = 0
    oldest: datetime | None = None
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
            minute_rows += 1
            oldest = ts if oldest is None or ts < oldest else oldest
    return _Usage(month_usd, day_usd, day_tokens, day_grades, minute_rows, oldest)


def _usage(user_id: str) -> _Usage | None:
    """One llm_usage read per (request, user); None on a read error (fail open)."""
    rid = current_request_id()
    key = (rid, user_id) if rid else None
    if key is not None:
        with _lock:
            hit = _request_cache.get(key)
        if hit is not None and _clock() - hit[0] < _REQUEST_CACHE_TTL_S:
            return hit[1]
    now = _utcnow()
    try:
        rows = _load_rows(user_id, _month_start(now))
    except Exception as exc:  # fail open — see HANDOFF-06b Open questions (b)
        logger.warning("ai_budget: llm_usage read failed for %s: %s", user_id, exc)
        return None
    summary = _summarise(rows, now)
    if key is not None:
        with _lock:
            _request_cache.pop(key, None)  # a refreshed key moves to the back of the FIFO
            if len(_request_cache) >= _REQUEST_CACHE_MAX:
                _request_cache.pop(next(iter(_request_cache)))
            _request_cache[key] = (_clock(), summary)
    return summary


# ── the ladder ────────────────────────────────────────────────────────────────
def _grade_decision(user_id: str, usage: _Usage | None, now: datetime) -> BudgetDecision:
    """The grader cap (spec §3.5): grading has its own cap, so a tutor-hard student still grades."""
    if usage is None or usage.day_grades < config.STUDENT_DAILY_GRADES:
        return _NORMAL
    _emit_capped(user_id, "daily_grades", "grader_cap", **_spend_fields("daily_grades", usage))
    return BudgetDecision(
        level="hard", tier_ceiling="none", scope="daily_grades", reset_at=_next_day(now)
    )


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
    if kind == "tutor" and tutor_requests >= params.LOOP_SESSION_MAX_TUTOR_REQUESTS:
        hard["session_requests"] = None
    if hard:
        scope = _binding(hard)
        _emit_capped(user_id, scope, "hard", band=band, **_spend_fields(scope, usage, cap))
        # A 60-second burst pauses tutor turns but never drops novice-band concepts from review
        # or the check surfaces (spec §3.5 hard row): pause_novice needs a trigger besides it.
        return BudgetDecision(
            level="hard",
            tier_ceiling="none",
            scope=scope,
            reset_at=hard[scope],
            pause_novice=kind == "tutor" and set(hard) != {"rate_limit"},
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
    _emit_capped(user_id, scope, "soft", band=band, **_spend_fields(scope, usage, cap))
    if arm_session:
        return _NORMAL  # arms are exempt from downgrades; they pause at hard (spec §3.5)
    # The $- and token-based soft level never downgrades novice deep turns; only the novice
    # deep-request cap does (spec §3.5 soft row, LOOP_MODEL_TIER).
    novice_keeps_deep = band == "novice" and "session_deep" not in soft
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
    session counters are the ints PKG-07 keeps in sessions.loop_state."""
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
    the house request_id and the scope; Retry-After (≥ 1 s) when the reset is known."""
    rid = getattr(request.state, "request_id", None) or current_request_id()
    reset_at = exc.decision.reset_at
    headers: dict[str, str] = {}
    if reset_at is not None:
        headers["Retry-After"] = str(max(1, int((reset_at - _utcnow()).total_seconds())))
    if rid:
        headers["X-Request-ID"] = rid
    content = {
        "detail": BUDGET_REACHED_DETAIL,
        "reset_at": reset_at.isoformat() if reset_at else None,
        "scope": exc.decision.scope,
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
