"""Daily study-streak maintenance.

`users.streak_count` existed since the baseline schema but nothing ever advanced
it — it was initialised to 0 and only read. This is the writer. Call it once per
day of activity, from the same post-commit hook that awards XP.

Days are UTC calendar days, matching `users.last_active_date` (a DATE since 0024).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from db.connection import table
from db.scope import runs_as_service

logger = logging.getLogger(__name__)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def effective_streak(row: dict | None, today: date | None = None) -> int:
    """The streak as of `today`, from a users row's `streak_count` +
    `last_active_date` (#767).

    touch_streak is the only writer and only runs on activity, so a broken
    streak is not reset until the student is next active: the stored
    `streak_count` of someone last seen a week ago still reads 12. Every reader
    must go through this instead of `streak_count` — a streak whose last
    active day is before yesterday is 0. Yesterday still counts: the student
    can extend it today. Same UTC calendar days as touch_streak; a missing
    `last_active_date` is "never active", so 0.
    """
    if not row:
        return 0
    streak = int(row.get("streak_count") or 0)
    last_raw = row.get("last_active_date")
    if not streak or not last_raw:
        return 0
    last = date.fromisoformat(str(last_raw)[:10])
    if last < (today or _today()) - timedelta(days=1):
        return 0
    return streak


@runs_as_service  # #115: writes users streak columns (service-only)
def touch_streak(user_id: str) -> int:
    """Advance the streak for today's activity. Idempotent within a day."""
    rows = table("users").select(
        "last_active_date,streak_count,longest_streak",
        filters={"id": f"eq.{user_id}"},
    )
    if not rows:
        return 0
    row = rows[0]
    today = _today()
    streak = int(row.get("streak_count") or 0)
    longest = int(row.get("longest_streak") or 0)

    last_raw = row.get("last_active_date")
    last = date.fromisoformat(last_raw[:10]) if last_raw else None

    if last == today:
        return streak                      # already counted today
    if last == today - timedelta(days=1):
        streak += 1                        # consecutive day
    else:
        streak = 1                         # first day, or the streak broke

    table("users").update(
        {
            "streak_count": streak,
            "longest_streak": max(longest, streak),
            "last_active_date": today.isoformat(),
        },
        filters={"id": f"eq.{user_id}"},
    )
    return streak


def touch_streak_safe(user_id: str) -> int | None:
    """touch_streak that never raises — request paths use this."""
    try:
        return touch_streak(user_id)
    except Exception:
        logger.exception("touch_streak failed user=%s", user_id)
        return None
