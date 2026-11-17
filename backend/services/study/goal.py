"""The student's daily study goal, in minutes (#118; the body of
``routes/study.py::set_daily_goal`` and the goal read behind ``get_daily``).

Stored on ``user_settings.daily_goal_minutes`` (migration 20261108225631:
``INT NOT NULL DEFAULT 30``, ``CHECK BETWEEN 5 AND 600``). The bounds and the
default below mirror that column; ``routes/study.py`` validates the PATCH body
against the same two bounds, so an out-of-range goal is a 422 and never a raw
CHECK violation.

Nothing caches this column: ``GET /api/profile/{id}/settings`` does not carry
it (``services/profile/users.py::_SETTINGS_COLS``) and the analytics-consent
cache keys on ``analytics_opt_out`` alone, so the write has nothing to
invalidate.
"""
from __future__ import annotations

import logging

import httpx

from db.connection import table

logger = logging.getLogger(__name__)

DEFAULT_GOAL_MIN = 30
MIN_GOAL_MIN = 5
MAX_GOAL_MIN = 600


def _goal_or_default(value: object) -> int:
    """A stored goal, or the default for anything the column cannot hold.

    ``None`` is a missing row. The rest (a bool, a string, a number outside
    the CHECK's range) cannot come out of the column as migrated; they fall
    back to the default instead of reaching the client as a goal of ``0`` or
    a 500.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_GOAL_MIN
    return value if MIN_GOAL_MIN <= value <= MAX_GOAL_MIN else DEFAULT_GOAL_MIN


def read_daily_goal(user_id: str) -> int:
    """The student's goal in minutes; the column default when they have no
    ``user_settings`` row yet (the row is created lazily).

    The goal is secondary to the minutes it sits beside, so a PostgREST
    failure (an error status or a transport error) degrades to the default,
    with a warning, rather than failing the whole panel. Anything else (a bug
    in this code, a refused user-scoped token) is not a database blip and
    propagates.
    """
    try:
        rows = table("user_settings").select(
            "daily_goal_minutes", filters={"user_id": f"eq.{user_id}"}, limit=1
        ) or []
    except httpx.HTTPError:
        logger.warning("study: daily goal read failed user=%s", user_id, exc_info=True)
        return DEFAULT_GOAL_MIN
    return _goal_or_default(rows[0].get("daily_goal_minutes") if rows else None)


def set_daily_goal(user_id: str, minutes: int) -> dict:
    """Store the goal and answer ``{"goal_minutes": minutes}``.

    One upsert on the ``user_id`` key: a student who has never opened
    Settings has no row yet, and the insert then takes every other column's
    default, exactly as ``services/profile/users.py::_get_or_create_row``
    creates it. On a conflict PostgREST updates only the columns in the
    payload, so no other setting is touched. ``updated_at`` is the database's
    to set (column default on insert, ``trg_user_settings_updated_at`` on
    update).
    """
    table("user_settings").upsert(
        {"user_id": user_id, "daily_goal_minutes": minutes},
        on_conflict="user_id",
        columns="user_id,daily_goal_minutes",
    )
    return {"goal_minutes": minutes}
