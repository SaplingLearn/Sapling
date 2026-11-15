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

from db.connection import like_literal, pg_quote_value, table
from services.flashcards.context import _normalized

logger = logging.getLogger(__name__)

#: How many candidate rows one lookup reads. The name filter leaves only
#: spellings of one name (case twins, stray spacing between its words), so
#: this is generous; it exists so the read can never reach PostgREST's
#: max-rows cap and drop the matching node the way an unfiltered read of a
#: large graph could.
_CANDIDATE_LIMIT = 50


def _name_pattern(key: str) -> str:
    """An ``ilike`` pattern for a normalized name: each word verbatim (LIKE's
    metacharacters escaped), any run of characters between words, so a stored
    "Feeling  Suicidal" is a candidate for "feeling suicidal". A superset of
    the real match (PostgREST also turns ``*`` into a wildcard), which the
    caller narrows in Python."""
    return "%".join(like_literal(word) for word in key.split(" "))


def _graph_concept_names(user_id: str, course_id: str | None, key: str) -> list[str]:
    """The student's concept names that may equal the normalized `key`,
    filtered server-side and bounded."""
    filters = {"user_id": f"eq.{user_id}"}
    if course_id:
        filters["course_id"] = f"eq.{course_id}"
    filters["or"] = f"(concept_name.ilike.{pg_quote_value(_name_pattern(key))})"
    rows = table("graph_nodes").select("concept_name", filters=filters, limit=_CANDIDATE_LIMIT) or []
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
        names = _graph_concept_names(user_id, course_id, key)
    except Exception:  # noqa: BLE001 — a failed read means "not shown to be a concept"
        logger.warning("crisis support: a flashcard topic's concepts could not be read; it is screened as typed")
        return False
    return any(_normalized(name) == key for name in names)
