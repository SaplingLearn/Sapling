"""The class's tutor sessions and their messages. The Study hub reads tutor
time from the MESSAGE times (``services/study/daily.py``), so each session's
messages span the minutes it lasted."""
from __future__ import annotations

from datetime import datetime, timedelta

from db.local_study_data import clock
from db.local_study_data.placement import Placement
from db.local_study_data.spec import Tutoring

#: A session held today was started this long ago and is still open.
_TODAY_MINUTES_AGO = 40

#: The exchange every session follows, in order. ``{topic}`` is the concept's
#: name and ``{definition}`` its one-sentence definition.
_LINES = (
    ("user", "Can we go through {topic} again? I keep getting stuck."),
    ("assistant", "Of course. Start from the idea itself: {definition} Which part of that stops making sense?"),
    ("user", "I follow the definition, but I lose track when I try an example."),
    ("assistant", "Then let's take one small example and walk through it one step at a time."),
    ("user", "That helps. Can I try the next one myself?"),
    ("assistant", "Go ahead. Say each step out loud as you do it, and I will stop you if one is off."),
)


def session_id(place: Placement, session: Tutoring) -> str:
    return f"{place.prefix}-sess-{session.key}"


def _started_at(place: Placement, session: Tutoring) -> datetime:
    return clock.moment(
        place.now, session.days_ago, session.hour, minutes_before_now=_TODAY_MINUTES_AGO,
    )


def _message_times(place: Placement, session: Tutoring) -> list[datetime]:
    """When each message was sent; never later than now."""
    started = _started_at(place, session)
    return [min(place.now, started + timedelta(minutes=beat)) for beat in session.beats]


def last_message_at(place: Placement, session: Tutoring) -> datetime:
    return _message_times(place, session)[-1]


def sessions(place: Placement) -> list[dict]:
    rows = []
    for session in place.data.tutoring:
        concept = place.data.concept(session.concept)
        rows.append({
            "id": session_id(place, session),
            "user_id": place.owner_id,
            "offering_id": place.enrolled.offering_id,
            "mode": session.mode,
            "topic": concept.name,
            "name": session.name,
            "summary_json": {"bullets": [
                f"Went back over {concept.name} from its definition",
                "Worked one example step by step",
            ]},
            "started_at": clock.utc(_started_at(place, session)),
            "ended_at": clock.utc(last_message_at(place, session)) if session.ended else None,
        })
    return rows


def messages(place: Placement) -> list[dict]:
    rows = []
    for session in place.data.tutoring:
        concept = place.data.concept(session.concept)
        for number, at in enumerate(_message_times(place, session), start=1):
            role, line = _LINES[(number - 1) % len(_LINES)]
            rows.append({
                "id": f"{session_id(place, session)}-msg-{number}",
                "session_id": session_id(place, session),
                "role": role,
                "content": line.format(topic=concept.name, definition=concept.definition),
                "created_at": clock.utc(at),
            })
    return rows
