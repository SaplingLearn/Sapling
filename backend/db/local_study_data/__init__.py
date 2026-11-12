"""The local study dataset: three classes of documents, a concept tree with
mastery, dated coursework, quiz history, flashcards, tutor sessions and study
guides, written by ``db/seed_local_study.py`` onto a developer's own account.

Content is one module per class (``cs101``, ``math210``, ``bio110``; shapes in
``spec``). The other modules turn a class into rows for one table each.
``plan`` puts them together. Nothing in this package touches the database, so
the whole dataset can be built and checked in a test.
"""
from __future__ import annotations

from datetime import datetime

from db.local_study_data import (
    bio110,
    coursework,
    cs101,
    flashcards,
    graph,
    guides,
    materials,
    math210,
    outline,
    quizzes,
    tutoring,
)
from db.local_study_data.placement import Enrolled, Placement
from db.local_study_data.spec import ClassData

CLASSES: tuple[ClassData, ...] = (cs101.CLASS, math210.CLASS, bio110.CLASS)

#: Each table's rows come from one function of a class's placement. In write
#: order: a row's parents (its concept, its attempt, its session, its exam)
#: are listed before it.
_TABLES = {
    "graph_nodes": graph.nodes,
    "graph_edges": graph.edges,
    "documents": materials.documents,
    "assignments": coursework.assignments,
    "quiz_attempts": quizzes.attempts,
    "quiz_responses": quizzes.responses,
    "quiz_context": quizzes.digests,
    "node_mastery_events": graph.mastery_events,
    "flashcards": flashcards.cards,
    "flashcard_sets": flashcards.card_sets,
    "sessions": tutoring.sessions,
    "messages": tutoring.messages,
    "study_guides": guides.study_guides,
}
TABLES: tuple[str, ...] = tuple(_TABLES)


def placements(now: datetime, owner_id: str, enrolled: dict[str, Enrolled]) -> list[Placement]:
    """One placement per class the account is enrolled in (``enrolled`` is
    keyed by class key)."""
    return [
        Placement(data=data, owner_id=owner_id, enrolled=enrolled[data.key], now=now)
        for data in CLASSES if data.key in enrolled
    ]


def plan(now: datetime, owner_id: str, enrolled: dict[str, Enrolled]) -> dict[str, list[dict]]:
    """Every row the seed writes, by table, as plaintext (the seed encrypts
    on the way in). ``now`` is an aware datetime in the student's local zone.
    The course outlines are not here: see ``outline.topics``."""
    places = placements(now, owner_id, enrolled)
    return {
        table_name: [row for place in places for row in rows_of(place)]
        for table_name, rows_of in _TABLES.items()
    }


__all__ = ["CLASSES", "TABLES", "Enrolled", "Placement", "outline", "placements", "plan"]
