"""Estimated daily study minutes (#118; the body of
``routes/study.py::get_daily``).

The app keeps no per-day study-time log, so minutes are ESTIMATED from the
timestamps it already records (one definition, used by the Study screen's
Daily Goal panel):

- quiz:       each completed quiz attempt, ``completed_at - created_at``,
              capped at ``QUIZ_CAP_MIN`` (a tab left open is not study time)
              and counted on the day it was completed.
- flashcards: ``CARD_MIN`` per card whose ``last_reviewed_at`` falls on the
              day. Only a card's latest review survives, so a re-reviewed card
              moves to its newest day and older days under-count.
- tutor:      from the student's tutor MESSAGES (theirs and the tutor's
              replies). For each session, each local day it has messages on
              counts the time from its first to its last message that day,
              capped at ``SESSION_CAP_MIN``. So a chat kept open for weeks
              counts on every day it is used, and one that runs past midnight
              is split between the two days (the pause across midnight itself
              is not counted). A day with a single message in a session has
              no measurable length: the session is counted, with 0 minutes.
              ``sessions.started_at`` / ``ended_at`` are not used: "End
              session" is rarely pressed, and a start time says nothing about
              the days after it.

Days are the student's LOCAL days: the client passes ``tz_offset_min`` (JS
``Date#getTimezoneOffset``: minutes BEHIND UTC, so New York in winter is
``300`` and Tokyo is ``-540``). The offset is one fixed number for the whole
window, so in a week with a daylight-saving change the days before the change
are cut an hour off local midnight.

Rounding keeps a day consistent with itself. Each part (quiz, flashcards,
tutor) is rounded half up to whole minutes, and any part with time in it
shows at least 1 (one reviewed card is half a minute, not "0 min"). The day's
``minutes`` is the SUM of the three rounded parts, so the total the goal is
measured against always equals the breakdown beside it.

Each source is one paged read (``db.connection.page_all``), newest first:
PostgREST caps a response at ``MAX_ROWS`` and reports the cut as a success, so
a single read would silently drop everything past the cap. A read stops at
``_MAX_SOURCE_ROWS`` (logged); being newest first, what it gives up is the
oldest part of the window. The source reads are the panel, so a failure there
fails the request; the goal read (``goal.py``) degrades instead.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from itertools import islice

from db.connection import MAX_ROWS, page_all, table
from services.study.goal import read_daily_goal

logger = logging.getLogger(__name__)

DAYS = 7
QUIZ_CAP_MIN = 30.0
SESSION_CAP_MIN = 60.0
CARD_MIN = 0.5

# ``Date#getTimezoneOffset`` for the two ends of the real world: UTC+14 (Line
# Islands) is -840 and UTC-12 (Baker Island) is +720. The sign is flipped from
# the zone's name because the value is minutes BEHIND UTC.
TZ_OFFSET_MIN_LOWEST = -14 * 60
TZ_OFFSET_MIN_HIGHEST = 12 * 60

# The most rows one source read will take. Far above a real week (it is 20
# pages of quiz attempts, reviewed cards or tutor messages for ONE student in
# seven days); it only keeps a runaway account from paging without end.
_MAX_SOURCE_ROWS = 20 * MAX_ROWS

#: One timestamped piece of study: (the timestamp whose local day it counts
#: on, estimated minutes).
Span = tuple[str | None, float]


# ── timestamps ───────────────────────────────────────────────────────────────

def _ts(value: str | None) -> datetime | None:
    """A PostgREST timestamp as an aware datetime; ``None`` if unreadable."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _span_min(start: str | None, end: str | None, cap: float) -> float:
    """Minutes from ``start`` to ``end``, at most ``cap``; 0 when either is
    missing or the end is not after the start."""
    a, b = _ts(start), _ts(end)
    if not a or not b or b <= a:
        return 0.0
    return min((b - a).total_seconds() / 60.0, cap)


# ── the window ───────────────────────────────────────────────────────────────

def clamp_tz_offset(tz_offset_min: int) -> int:
    """``tz_offset_min`` held to real-world offsets (UTC+14..UTC-12), so a
    junk value cannot shift the window by days."""
    return max(TZ_OFFSET_MIN_LOWEST, min(tz_offset_min, TZ_OFFSET_MIN_HIGHEST))


@dataclass(frozen=True)
class Window:
    """The ``DAYS`` local days ending on the student's today."""

    #: Added to a UTC time to get the student's local time.
    offset: timedelta
    #: The student's local today (the last of ``days``).
    today: date
    #: Local midnight of the first day, in UTC: the lower bound of every read.
    since: datetime

    @property
    def days(self) -> list[str]:
        """The window's local dates (ISO), oldest first."""
        first = self.today - timedelta(days=DAYS - 1)
        return [(first + timedelta(days=i)).isoformat() for i in range(DAYS)]

    def local_day(self, value: str | None) -> str | None:
        """The local date (ISO) a stored timestamp falls on."""
        ts = _ts(value)
        return (ts + self.offset).date().isoformat() if ts else None


def _window(tz_offset_min: int, now: datetime) -> Window:
    offset = timedelta(minutes=-tz_offset_min)
    today = (now + offset).date()
    first_midnight = datetime.combine(
        today - timedelta(days=DAYS - 1), time.min, tzinfo=timezone.utc
    )
    return Window(offset=offset, today=today, since=first_midnight - offset)


# ── the three sources ────────────────────────────────────────────────────────

def _window_rows(name: str, columns: str, filters: dict, stamp: str) -> list[dict]:
    """Every row of ``name`` matching ``filters``, newest ``stamp`` first, up
    to ``_MAX_SOURCE_ROWS``. ``id`` breaks ties, so the order is total and
    offset paging cannot skip or repeat a row."""
    rows = list(islice(
        page_all(table(name), columns, filters=filters, order=f"{stamp}.desc,id.desc"),
        _MAX_SOURCE_ROWS + 1,
    ))
    if len(rows) > _MAX_SOURCE_ROWS:
        logger.warning(
            "study: %s read stopped at %d rows; the oldest days under-count",
            name, _MAX_SOURCE_ROWS,
        )
        del rows[_MAX_SOURCE_ROWS:]
    return rows


def _since(since: datetime) -> str:
    return f"gte.{since.isoformat()}"


def _quiz_spans(user_id: str, since: datetime) -> list[Span]:
    rows = _window_rows(
        "quiz_attempts", "created_at,completed_at",
        {"user_id": f"eq.{user_id}", "completed_at": _since(since)}, "completed_at",
    )
    return [
        (r.get("completed_at"),
         _span_min(r.get("created_at"), r.get("completed_at"), QUIZ_CAP_MIN))
        for r in rows
    ]


def _card_spans(user_id: str, since: datetime) -> list[Span]:
    rows = _window_rows(
        "flashcards", "last_reviewed_at",
        {"user_id": f"eq.{user_id}", "last_reviewed_at": _since(since)}, "last_reviewed_at",
    )
    return [(r.get("last_reviewed_at"), CARD_MIN) for r in rows]


def _tutor_messages(user_id: str, since: datetime) -> list[dict]:
    """``{session_id, created_at}`` of every message since ``since`` in one of
    the student's tutor sessions.

    ``messages`` has no ``user_id``: the student is reached through the
    session it belongs to (``sessions!inner`` + a filter on the embedded
    ``user_id``), which keeps this one paged read however many sessions the
    student has. ``content`` (encrypted) is never selected.
    """
    return _window_rows(
        "messages", "session_id,created_at,sessions!inner(user_id)",
        {"sessions.user_id": f"eq.{user_id}", "created_at": _since(since)}, "created_at",
    )


def _session_day_spans(messages: list[dict], window: Window) -> list[Span]:
    """One span per (session, local day): first to last message that day,
    capped at ``SESSION_CAP_MIN``. Order of ``messages`` does not matter."""
    first_last: dict[tuple[str, str], tuple[datetime, datetime]] = {}
    for m in messages:
        at, session_id = _ts(m.get("created_at")), m.get("session_id")
        if at is None or not session_id:
            continue
        key = (session_id, (at + window.offset).date().isoformat())
        first, last = first_last.get(key, (at, at))
        first_last[key] = (min(first, at), max(last, at))
    return [
        (first.isoformat(), min((last - first).total_seconds() / 60.0, SESSION_CAP_MIN))
        for first, last in first_last.values()
    ]


def _tutor_spans(user_id: str, window: Window) -> list[Span]:
    return _session_day_spans(_tutor_messages(user_id, window.since), window)


# ── buckets and the wire shape ───────────────────────────────────────────────

def _empty_buckets(window: Window) -> dict[str, dict]:
    """One unrounded tally per local day, keyed by ISO date, oldest first."""
    return {
        day: {"date": day, "quiz": 0.0, "flashcards": 0.0, "tutor": 0.0,
              "quizzes": 0, "cards": 0, "sessions": 0}
        for day in window.days
    }


def _tally(buckets: dict[str, dict], window: Window, spans: list[Span],
           minutes_key: str, count_key: str) -> None:
    """Add each span to its local day's bucket. A span outside the window, or
    with an unreadable timestamp, is dropped."""
    for stamp, minutes in spans:
        bucket = buckets.get(window.local_day(stamp) or "")
        if bucket is not None:
            bucket[minutes_key] += minutes
            bucket[count_key] += 1


def _whole_minutes(minutes: float) -> int:
    """A part's minutes as shown: rounded half up, and never 0 for a part
    with time in it. (``round()`` rounds half to even: one reviewed card, 0.5
    min, read as 0, and five cards, 2.5 min, as 2.)"""
    if minutes <= 0:
        return 0
    return max(1, int(minutes + 0.5))


def _day_payload(bucket: dict) -> dict:
    """One day of the response. Key order is the wire contract
    (``frontend/src/lib/studyApi.ts::StudyDay``). ``minutes`` is the sum of
    the rounded parts, so the total always equals its breakdown."""
    quiz = _whole_minutes(bucket["quiz"])
    cards = _whole_minutes(bucket["flashcards"])
    tutor = _whole_minutes(bucket["tutor"])
    return {
        "date": bucket["date"],
        "minutes": quiz + cards + tutor,
        "quiz": quiz,
        "flashcards": cards,
        "tutor": tutor,
        "quizzes": bucket["quizzes"],
        "cards": bucket["cards"],
        "sessions": bucket["sessions"],
    }


def get_daily(user_id: str, tz_offset_min: int = 0, now: datetime | None = None) -> dict:
    """The Daily Goal panel: the goal, the student's local today, and the
    estimated minutes of each of the last ``DAYS`` local days, oldest first.

    ``now`` is the clock (UTC), a parameter so tests can pin it.
    """
    window = _window(clamp_tz_offset(tz_offset_min), now or datetime.now(timezone.utc))
    buckets = _empty_buckets(window)
    _tally(buckets, window, _quiz_spans(user_id, window.since), "quiz", "quizzes")
    _tally(buckets, window, _card_spans(user_id, window.since), "flashcards", "cards")
    _tally(buckets, window, _tutor_spans(user_id, window), "tutor", "sessions")
    return {
        "goal_minutes": read_daily_goal(user_id),
        "today": window.today.isoformat(),
        "days": [_day_payload(b) for b in buckets.values()],
    }
