"""The class's concept tree: its nodes, its prerequisite edges and the mastery
history behind the scores."""
from __future__ import annotations

from config import get_mastery_tier
from db.local_study_data import clock, quizzes, tutoring
from db.local_study_data.placement import Placement

#: What one tutor session moved its concept by.
_TUTOR_DELTA = 0.03


def _last_studied(place: Placement, days: int | None) -> str | None:
    if days is None:
        return None
    return clock.utc(clock.moment(place.now, days, 18, minutes_before_now=30))


def nodes(place: Placement) -> list[dict]:
    return [{
        "id": place.node_id(concept.key),
        "user_id": place.owner_id,
        "course_id": place.data.course_id,
        "concept_name": concept.name,
        "subject": concept.name.split()[0],
        "mastery_score": concept.score,
        "mastery_tier": get_mastery_tier(concept.score),
        "times_studied": concept.times_studied,
        "last_studied_at": _last_studied(place, concept.last_studied),
    } for concept in place.data.concepts]


def edges(place: Placement) -> list[dict]:
    return [{
        "id": place.edge_id(needed, concept.key),
        "user_id": place.owner_id,
        "source_node_id": place.node_id(needed),
        "target_node_id": place.node_id(concept.key),
        "relationship_type": "prerequisite",
        "strength": 0.8,
    } for concept in place.data.concepts for needed in concept.needs]


def _quiz_event_type(correct: int, total: int) -> str:
    """The reading of an attempt the quiz submit records, from its score."""
    ratio = correct / total
    if ratio >= 0.7:
        return "quiz_correct"
    return "quiz_partial" if ratio >= 0.4 else "quiz_confusion"


def _quiz_events(place: Placement) -> list[dict]:
    return [{
        "id": f"{taken.attempt_id}-evt",
        "node_id": place.node_id(taken.quiz.concept),
        "delta": round(taken.after - taken.before, 4),
        "reason": f"quiz: {place.data.concept(taken.quiz.concept).name}",
        "event_type": _quiz_event_type(taken.quiz.correct, taken.quiz.total),
        "created_at": clock.utc(taken.done_at),
    } for taken in quizzes.completed(place)]


def _tutor_events(place: Placement) -> list[dict]:
    return [{
        "id": f"{tutoring.session_id(place, session)}-evt",
        "node_id": place.node_id(session.concept),
        "delta": _TUTOR_DELTA,
        "reason": f"tutor: {session.name}",
        "event_type": "tutor_interaction",
        "created_at": clock.utc(tutoring.last_message_at(place, session)),
    } for session in place.data.tutoring]


def mastery_events(place: Placement) -> list[dict]:
    """One event per finished quiz and per tutor session, dated with them."""
    return [*_quiz_events(place), *_tutor_events(place)]
