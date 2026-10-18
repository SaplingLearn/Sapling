"""Reading stored timestamps back, safely.

One rule, in one place. `routes/quiz.py` worked it out first and documented
the trap; `services/quiz_signals.py` then reached back UP into the route to
borrow it, which is the wrong direction (a service importing a route) and the
usual way the second copy of a rule ends up without the fix.

There are two more copies in the tree (`routes/gamification.py`,
`services/achievement_service.py`). They are deliberately left alone here —
converting them is unrelated to the change that needed this module — but this
is where they should land.
"""

from __future__ import annotations

from datetime import datetime, timezone


def parse_ts(value) -> datetime | None:
    """Parse a stored timestamp to an AWARE datetime, or None.

    Naive values (an out-of-band write, a hand-edited row) are assumed UTC
    rather than left naive: comparing a naive datetime against an aware one
    raises TypeError, which an `except ValueError` around the parse does not
    catch — it would 500 the reader rather than degrade it.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def calendar_days_since(value, *, now: datetime | None = None) -> int | None:
    """Whole CALENDAR days between a stored timestamp and now (UTC), or None.

    Calendar, not elapsed-24h-periods: every surface that renders one of these
    numbers says "today"/"yesterday"/"N days ago", and the exam-proximity line
    one sentence away in the same prompt counts calendar days
    (`(due - today).days`). Bucketing by 86400-second periods puts the two a
    day out from each other whenever a stamp is more than a few hours old —
    23:00 last night is "0 days ago" by elapsed time and "yesterday" to a
    reader.

    Clamped at 0: clock skew on a just-written row would otherwise produce
    "-1 days ago", which reads as a data bug in a prompt.
    """
    parsed = parse_ts(value)
    if parsed is None:
        return None
    today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    return max(0, (today - parsed.astimezone(timezone.utc).date()).days)
