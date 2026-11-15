"""Whether a flashcard generation's topic is one of the student's own graph
concepts (docs/safety/crisis-support.md).

The Flashcards page generates one concept per call, `topic` set to the
concept's name off the student's map. That name is course material the
student's graph already holds (a nursing course's "Feeling suicidal"), not
something they are saying now, so a crisis match in it makes the cards as
usual with the card beside them (`crisis_support.alongside`) instead of
blocking every Start on that concept.

Nothing from the client is trusted: the topic counts only when it names one
of the student's own `graph_nodes` (in the request's course, when it names
one). A concept the student typed into the builder ("Add your own concept")
that is not on their map, or a failed read, is screened as typed and blocks.
"""
from __future__ import annotations

import logging

from db.connection import table
from services.flashcards.context import _normalized

logger = logging.getLogger(__name__)


def _graph_concept_names(user_id: str, course_id: str | None) -> list[str]:
    filters = {"user_id": f"eq.{user_id}"}
    if course_id:
        filters["course_id"] = f"eq.{course_id}"
    rows = table("graph_nodes").select("concept_name", filters=filters) or []
    return [r.get("concept_name") or "" for r in rows if isinstance(r, dict)]


def topic_is_graph_concept(user_id: str, topic: str, course_id: str | None) -> bool:
    """True when `topic` is (up to case and spacing, as the page matches
    names) one of `user_id`'s graph concepts, in `course_id` when given.
    Read only after the crisis screen matched the topic (which authenticated
    the caller as `user_id`), so an ordinary generation never pays for it.
    Blocking: call it off the event loop. Every doubt is False."""
    key = _normalized(topic)
    if not key:
        return False
    try:
        names = _graph_concept_names(user_id, course_id)
    except Exception:  # noqa: BLE001 — a failed read means "not shown to be a concept"
        logger.warning("crisis support: a flashcard topic's concepts could not be read; it is screened as typed")
        return False
    return any(_normalized(name) == key for name in names)
