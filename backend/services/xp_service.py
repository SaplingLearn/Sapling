"""The single XP award path.

Every XP grant in the product goes through `award_xp`. It writes one row to the
append-only `xp_events` ledger and then refreshes the `users.total_xp` /
`users.level` caches from it.

Idempotency is the reason this is a service and not three inline inserts: a
retried quiz submit, a re-delivered background task or a double-clicked upload
must not pay out twice. Each event carries a deterministic key backed by a
UNIQUE index; a 409 from Postgres means "already paid" and is a clean no-op,
not an error.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import httpx

from db.connection import table
from services.growth import level_for_xp

logger = logging.getLogger(__name__)


@dataclass
class XpAward:
    awarded: int
    total_xp: int
    level: int
    leveled_up: bool
    duplicate: bool = False


def idempotency_key(rule_key: str, source_type: str | None, source_id: str | None) -> str:
    return f"{rule_key}:{source_type or '-'}:{source_id or '-'}"


def _rule_amount(rule_key: str) -> int:
    rows = table("xp_rules").select(
        "key,amount,enabled", filters={"key": f"eq.{rule_key}"}
    )
    if not rows:
        logger.warning("award_xp: unknown rule_key=%s", rule_key)
        return 0
    rule = rows[0]
    if not rule.get("enabled", True):
        return 0
    return int(rule.get("amount") or 0)


def _user_state(user_id: str) -> tuple[int, int]:
    rows = table("users").select("total_xp,level", filters={"id": f"eq.{user_id}"})
    if not rows:
        return 0, 1
    return int(rows[0].get("total_xp") or 0), int(rows[0].get("level") or 1)


# supabase/config.toml sets PostgREST's `max_rows = 1000`. A page past that cap
# doesn't error — PostgREST returns 206 Partial Content, which is a 2xx, so
# db/connection.py's raise_for_status() never fires and the truncation is
# silent by construction. Same constant and same reasoning as
# services/gamification_service.py::XP_EVENTS_PAGE; keep this at or below
# max_rows and page to completion, or a heavy user's total_xp would silently
# collapse to the first page's sum.
_XP_EVENTS_PAGE = 1000


def _ledger_total(user_id: str) -> int:
    """Sum the user's entire xp_events ledger.

    `users.total_xp` is a CACHE of this sum, not an independent counter. It
    has to be recomputed rather than incremented (`prev_total + value`):
    increment is a read-modify-write with no lock, so two awards that
    interleave both read the same prev_total and the second UPDATE silently
    discards the first — permanently, since nothing reconciles the cache
    against the ledger afterwards. That drift is user-visible, because
    /activity and the xp_in_day / goal_streak achievement triggers sum
    xp_events directly while /me and the leaderboard read the cache.

    Recomputing makes the cache self-healing: whatever it drifted to, the
    next award lands it back on the ledger sum. The ledger is append-only, so
    this is always the authoritative number.

    The `created_at,id` order is required for offset paging to be correct —
    without a stable sort PostgREST can return rows in a different order
    across pages, skipping or double-counting across the page boundary.
    """
    total = 0
    seen = 0
    offset = 0
    while True:
        rows, count = table("xp_events").select_with_count(
            "amount",
            filters={"user_id": f"eq.{user_id}"},
            order="created_at.asc,id.asc",
            limit=_XP_EVENTS_PAGE,
            offset=offset,
        )
        rows = rows or []
        total += sum(int(r.get("amount") or 0) for r in rows)
        seen += len(rows)
        if not rows or seen >= count:
            break
        offset += _XP_EVENTS_PAGE
    return total


def award_xp(
    user_id: str,
    rule_key: str,
    *,
    source_type: str | None = None,
    source_id: str | None = None,
    amount: int | None = None,
) -> XpAward:
    """Grant XP once. `amount` overrides the rule (achievement rewards use it)."""
    value = amount if amount is not None else _rule_amount(rule_key)
    if value <= 0:
        total_xp, level = _user_state(user_id)
        return XpAward(awarded=0, total_xp=total_xp, level=level, leveled_up=False)

    key = idempotency_key(rule_key, source_type, source_id)
    try:
        table("xp_events").insert({
            "user_id": user_id,
            "rule_key": rule_key,
            "amount": value,
            "source_type": source_type,
            "source_id": source_id,
            "idempotency_key": key,
        })
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 409:
            raise
        # Already paid out — report current state without touching the cache.
        total_xp, level = _user_state(user_id)
        return XpAward(awarded=0, total_xp=total_xp, level=level,
                       leveled_up=False, duplicate=True)

    _prev_total, prev_level = _user_state(user_id)
    total_xp = _ledger_total(user_id)
    level = level_for_xp(total_xp)
    table("users").update(
        {"total_xp": total_xp, "level": level}, filters={"id": f"eq.{user_id}"}
    )
    leveled_up = level > prev_level

    _dispatch_xp_achievements(user_id, leveled_up=leveled_up)

    return XpAward(
        awarded=value, total_xp=total_xp, level=level,
        leveled_up=leveled_up,
    )


# Re-entrancy guard for the achievement dispatch below. check_achievements pays
# a badge's xp_reward through award_xp_safe, which would re-enter award_xp and
# dispatch again — a badge that pays enough XP to level you up would recurse.
# Thread-local (not a module global) because the app is threaded: one request's
# dispatch must not suppress another's.
_dispatch_state = threading.local()


def _dispatch_xp_achievements(user_id: str, *, leveled_up: bool) -> None:
    """Fire the achievement triggers that only an XP award can advance.

    check_achievements only evaluates triggers whose trigger_type equals the
    event_type it is handed, so a trigger type nothing dispatches is a badge
    nothing can ever earn. `level` (0044: sprout, rings, old-growth) and
    `xp_in_day` (golden-hour) are advanced by exactly this function and
    nowhere else.

    `level` only fires on an actual level-up — it is otherwise a no-op read of
    the same unchanged number on every single award.

    Recursion: check_achievements pays xp_reward via award_xp_safe, which
    re-enters award_xp. The thread-local flag makes that inner award skip its
    own dispatch, so the chain is depth-1 and cannot loop. The cost is that a
    badge payout which itself causes a level-up isn't noticed until the user's
    next award — a bounded, self-correcting delay, versus an unbounded loop.

    Post-commit side effect: the XP is already in the ledger and the cache is
    already refreshed, so nothing here may propagate an exception into the
    action that earned the XP.
    """
    if getattr(_dispatch_state, "active", False):
        return
    _dispatch_state.active = True
    try:
        from services.achievement_service import check_achievements
        if leveled_up:
            check_achievements(user_id, "level", {})
        check_achievements(user_id, "xp_in_day", {})
    except Exception:
        logger.exception("achievement dispatch failed after award user=%s", user_id)
    finally:
        _dispatch_state.active = False


def award_xp_safe(*args, **kwargs) -> XpAward | None:
    """award_xp that never raises. Use this on request paths — XP must not be
    able to fail the action that earned it."""
    try:
        return award_xp(*args, **kwargs)
    except Exception:
        logger.exception("award_xp failed rule=%s", args[1] if len(args) > 1 else kwargs.get("rule_key"))
        return None
