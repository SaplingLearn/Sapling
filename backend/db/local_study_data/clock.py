"""Dates for the local study dataset. Everything is dated relative to ``now``
(an aware datetime in the student's local zone), so a re-run on a later day
moves the same rows forward with it."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

#: A document "uploaded N days ago" was uploaded this many hours earlier
#: still, so its order against a guide made a whole number of hours ago never
#: depends on the time of day the seed runs.
UPLOAD_LEAD_HOURS = 3


def utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def hours_ago(now: datetime, hours: float) -> datetime:
    return now - timedelta(hours=hours)


def uploaded(now: datetime, days_ago: int) -> datetime:
    """When a document uploaded ``days_ago`` days back was created."""
    return hours_ago(now, days_ago * 24 + UPLOAD_LEAD_HOURS)


def due_day(now: datetime, in_days: int) -> str:
    """The local date ``in_days`` from today, as ``YYYY-MM-DD``."""
    return (now.date() + timedelta(days=in_days)).isoformat()


def moment(now: datetime, days_ago: int, hour: int, *, minutes_before_now: int = 0) -> datetime:
    """A point in the student's local day ``days_ago`` days back.

    Earlier days sit at a fixed clock hour. Today is anchored to ``now``
    instead (``minutes_before_now``), because a fixed hour could be in the
    future."""
    if days_ago == 0:
        at = now - timedelta(minutes=minutes_before_now)
        if at.date() == now.date():
            return at
        # Run just after midnight: "N minutes ago" was yesterday, which would
        # leave today empty. Pin it to the first seconds of today instead.
        return min(now, datetime.combine(now.date(), time(0, 0, 30), tzinfo=now.tzinfo))
    day = (now - timedelta(days=days_ago)).date()
    return datetime.combine(day, time(hour, 0), tzinfo=now.tzinfo)
