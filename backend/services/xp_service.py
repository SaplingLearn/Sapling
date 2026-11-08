"""The single XP award path.

Every XP grant in the product goes through `award_xp`. It writes one row to the
append-only `xp_events` ledger and then refreshes the `users.total_xp` /
`users.level` caches from it.

Idempotency is the reason this is a service and not three inline inserts: a
retried quiz submit, a re-delivered background task or a double-clicked upload
must not pay out twice. Each event carries a deterministic key backed by a
UNIQUE (user_id, idempotency_key) index; a 409 from Postgres means "already
paid" and is a clean no-op, not an error.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import httpx

from db.connection import MAX_ROWS, page_all, table
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
    """The event's identity WITHIN one student's ledger.

    The user is deliberately not part of the string: uniqueness is scoped by
    the (user_id, idempotency_key) constraint instead. Until
    20261108063442_xp_events_per_user_idempotency the constraint was on this
    key alone, and a source shared across students (an achievement id) paid
    only the first student to earn it.
    """
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


# The paging loop and the reason for it now live in db/connection.py::page_all
# (PostgREST truncates past max_rows with a 206 — a 2xx, so nothing raises).
# This alias only names the page size for the tests that assert on it; without
# paging, a heavy user's total_xp would silently collapse to the first page's
# sum.
_XP_EVENTS_PAGE = MAX_ROWS


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
    return sum(
        int(r.get("amount") or 0)
        for r in page_all(
            table("xp_events"), "amount",
            filters={"user_id": f"eq.{user_id}"},
            order="created_at.asc,id.asc",
            page=_XP_EVENTS_PAGE,
        )
    )


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

    total_xp, level, leveled_up = _refresh_cache(user_id)

    _dispatch_xp_achievements(user_id, leveled_up=leveled_up)

    return XpAward(
        awarded=value, total_xp=total_xp, level=level,
        leveled_up=leveled_up,
    )


# Compare-and-set attempts before giving up on refreshing the cache. Each
# failed attempt means another award for this user landed between our read and
# our write, so contention this deep is a burst from one user; whatever we
# leave stale, their next award recomputes from the ledger.
_CACHE_CAS_ATTEMPTS = 5


def _refresh_cache(user_id: str) -> tuple[int, int, bool]:
    """Refresh users.total_xp/level from the ledger as a compare-and-set
    (#767). Returns (total_xp, level, leveled_up).

    The ledger insert and this cache write are separate statements, and two
    concurrent awards used to race between them: each read prev_level, each
    summed the ledger, and the writes landed in either order — so a stale,
    LOWER total could overwrite a newer one, and the same level-up could be
    reported by both awards (or after a regressed write, twice over time).

    The UPDATE is conditioned on `total_xp` still being the value we read. If
    another award moved it first, the PATCH matches no row and we re-read and
    retry. So the cache only ever moves forward from a state we observed, and
    `leveled_up` compares against the level of the row we actually replaced:
    each crossing of a level boundary is reported by exactly one award (the
    one whose write crossed it), even when that write also carries a
    concurrent award's XP. Ledger amounts are always positive (award_xp is the
    only writer and refuses value <= 0), so a re-read sum is never lower than
    one a competing writer already cached.
    """
    total_xp, level = 0, 1
    for _ in range(_CACHE_CAS_ATTEMPTS):
        rows = table("users").select("total_xp,level", filters={"id": f"eq.{user_id}"})
        if not rows:
            total_xp = _ledger_total(user_id)
            return total_xp, level_for_xp(total_xp), False
        raw_prev = rows[0].get("total_xp")
        prev_total = int(raw_prev or 0)
        prev_level = int(rows[0].get("level") or 1)

        total_xp = _ledger_total(user_id)
        level = level_for_xp(total_xp)
        if total_xp == prev_total and level == prev_level:
            # A concurrent award already landed exactly this state (it
            # reported any level-up). Nothing to write.
            return total_xp, level, False

        updated = table("users").update(
            {"total_xp": total_xp, "level": level},
            filters={
                "id": f"eq.{user_id}",
                "total_xp": "is.null" if raw_prev is None else f"eq.{raw_prev}",
            },
        )
        if updated:
            return total_xp, level, level > prev_level
    logger.warning(
        "award_xp: cache CAS lost %d times user=%s; left for the next award",
        _CACHE_CAS_ATTEMPTS, user_id,
    )
    return total_xp, level, False


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
