"""Study hub reads: daily study minutes and the student's daily goal.

The app keeps no per-day study-time log, so minutes are ESTIMATED from the
timestamps it already records (one definition, used by the Study screen's
Daily Goal panel):

- quiz:       each completed quiz attempt, ``completed_at - created_at``,
              capped at ``QUIZ_CAP_MIN`` (a tab left open is not study time).
- flashcards: ``CARD_MIN`` per card whose ``last_reviewed_at`` falls on the
              day. Only a card's latest review survives, so a re-reviewed card
              moves to its newest day and older days under-count.
- tutor:      each tutor session, from ``started_at`` to its end, capped at
              ``SESSION_CAP_MIN`` and counted on the day it started. The end
              is ``ended_at`` when the student pressed "End session"; most
              never do, so otherwise it is the ``created_at`` of the session's
              last message. A session with neither (never ended, no messages)
              is not counted.

Days are the student's LOCAL days: the client passes ``tz_offset_min`` (JS
``Date#getTimezoneOffset``, minutes behind UTC).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from db.connection import MAX_ROWS, pg_quote_value, table
from services.auth_guard import require_self

logger = logging.getLogger(__name__)

router = APIRouter()

DAYS = 7
DEFAULT_GOAL_MIN = 30
QUIZ_CAP_MIN = 30.0
SESSION_CAP_MIN = 60.0
CARD_MIN = 0.5
_ROW_LIMIT = 2000
# Session ids per `in.(...)` filter (keeps the URL short) and rows per read of
# `messages` (PostgREST's cap: a larger limit comes back short, which would
# read as "that was everything").
_SESSION_ID_CHUNK = 100
_MESSAGE_PAGE = MAX_ROWS


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _span_min(start: str | None, end: str | None, cap: float) -> float:
    a, b = _ts(start), _ts(end)
    if not a or not b or b <= a:
        return 0.0
    return min((b - a).total_seconds() / 60.0, cap)


def _goal_minutes(user_id: str) -> int:
    # A missing row or a not-yet-migrated column degrades to the default rather
    # than failing the whole panel.
    try:
        rows = table("user_settings").select(
            "daily_goal_minutes", filters={"user_id": f"eq.{user_id}"}, limit=1
        ) or []
    except Exception:
        logger.warning("study: daily goal read failed user=%s", user_id, exc_info=True)
        return DEFAULT_GOAL_MIN
    value = rows[0].get("daily_goal_minutes") if rows else None
    return int(value) if value else DEFAULT_GOAL_MIN


def _last_message_at(session_ids: list[str]) -> dict[str, str]:
    """``session_id -> created_at`` of each session's LAST message.

    One read per ``_SESSION_ID_CHUNK`` sessions, newest message first, so the
    first row seen for a session is its last message. Only when a read comes
    back full (a very chatty week) are the sessions it did not reach asked for
    again. A session with no messages is simply absent. A failed read degrades
    to "no messages" for the sessions not yet answered rather than failing the
    whole panel. ``content`` (encrypted) is never selected.
    """
    last: dict[str, str] = {}
    try:
        for i in range(0, len(session_ids), _SESSION_ID_CHUNK):
            pending = session_ids[i:i + _SESSION_ID_CHUNK]
            while pending:
                rows = table("messages").select(
                    "session_id,created_at",
                    filters={"session_id": f"in.({','.join(pg_quote_value(s) for s in pending)})"},
                    order="created_at.desc",
                    limit=_MESSAGE_PAGE,
                ) or []
                for r in rows:
                    if r.get("session_id") and r.get("created_at"):
                        last.setdefault(r["session_id"], r["created_at"])
                if len(rows) < _MESSAGE_PAGE:
                    break
                unanswered = [s for s in pending if s not in last]
                if len(unanswered) == len(pending):
                    break  # a full page that answered nobody: don't spin
                pending = unanswered
    except Exception:
        logger.warning(
            "study: last-message read failed sessions=%d", len(session_ids), exc_info=True
        )
    return last


def daily_minutes(user_id: str, tz_offset_min: int = 0, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    offset = timedelta(minutes=-tz_offset_min)  # local = utc + offset
    local_today = (now + offset).date()
    first_day = local_today - timedelta(days=DAYS - 1)
    # Local midnight of the first day, expressed in UTC.
    since = datetime.combine(first_day, datetime.min.time(), tzinfo=timezone.utc) - offset
    since_iso = since.isoformat()

    buckets: dict[str, dict] = {}
    for i in range(DAYS):
        day = (first_day + timedelta(days=i)).isoformat()
        buckets[day] = {"date": day, "quiz": 0.0, "flashcards": 0.0, "tutor": 0.0,
                        "quizzes": 0, "cards": 0, "sessions": 0}

    def _bucket(value: str | None) -> dict | None:
        ts = _ts(value)
        return buckets.get((ts + offset).date().isoformat()) if ts else None

    quiz_rows = table("quiz_attempts").select(
        "created_at,completed_at",
        filters={"user_id": f"eq.{user_id}", "completed_at": f"gte.{since_iso}"},
        limit=_ROW_LIMIT,
    ) or []
    for r in quiz_rows:
        b = _bucket(r.get("completed_at"))
        if b is not None:
            b["quiz"] += _span_min(r.get("created_at"), r.get("completed_at"), QUIZ_CAP_MIN)
            b["quizzes"] += 1

    card_rows = table("flashcards").select(
        "last_reviewed_at",
        filters={"user_id": f"eq.{user_id}", "last_reviewed_at": f"gte.{since_iso}"},
        limit=_ROW_LIMIT,
    ) or []
    for r in card_rows:
        b = _bucket(r.get("last_reviewed_at"))
        if b is not None:
            b["flashcards"] += CARD_MIN
            b["cards"] += 1

    session_rows = table("sessions").select(
        "id,started_at,ended_at",
        filters={"user_id": f"eq.{user_id}", "started_at": f"gte.{since_iso}"},
        limit=_ROW_LIMIT,
    ) or []
    # Most sessions are never explicitly ended: those end at their last message.
    open_ids = [r["id"] for r in session_rows if not r.get("ended_at") and r.get("id")]
    last_message = _last_message_at(open_ids) if open_ids else {}
    for r in session_rows:
        end = r.get("ended_at") or last_message.get(r.get("id"))
        if not end:
            continue
        b = _bucket(r.get("started_at"))
        if b is not None:
            b["tutor"] += _span_min(r.get("started_at"), end, SESSION_CAP_MIN)
            b["sessions"] += 1

    days = []
    for day in sorted(buckets):
        b = buckets[day]
        quiz, cards, tutor = round(b["quiz"]), round(b["flashcards"]), round(b["tutor"])
        days.append({
            "date": day,
            "minutes": round(b["quiz"] + b["flashcards"] + b["tutor"]),
            "quiz": quiz, "flashcards": cards, "tutor": tutor,
            "quizzes": b["quizzes"], "cards": b["cards"], "sessions": b["sessions"],
        })
    return {"goal_minutes": _goal_minutes(user_id), "today": local_today.isoformat(), "days": days}


@router.get("/{user_id}/daily")
def get_daily(user_id: str, request: Request, tz_offset_min: int = 0):
    require_self(user_id, request)
    # Clamp to real-world offsets (UTC-14..UTC+12) so a junk value can't shift
    # the window by days.
    tz_offset_min = max(-14 * 60, min(tz_offset_min, 12 * 60))
    return daily_minutes(user_id, tz_offset_min)


class DailyGoalBody(BaseModel):
    minutes: int = Field(ge=5, le=600)


@router.patch("/{user_id}/daily-goal")
def set_daily_goal(user_id: str, body: DailyGoalBody, request: Request):
    require_self(user_id, request)
    table("user_settings").upsert(
        {
            "user_id": user_id,
            "daily_goal_minutes": body.minutes,
            # Bumped so /api/profile/{id}/settings' updated_at ETag stays honest.
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id",
    )
    return {"goal_minutes": body.minutes}
