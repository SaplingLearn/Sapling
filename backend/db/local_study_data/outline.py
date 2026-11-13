"""The class's course outline (a ``TopicOutline`` payload): its units, the
concepts under each, and which exams cover them.

The Study hub names its roadmap columns after the units, and reads an exam's
readiness from the concepts linked to it here. The outline as SERVED attaches
an exam to a topic only while the exam is ahead (today to thirty days out,
``topic_checklist_service.present``), so an exam already sat is linked here
and still reads as the whole course on the hub.
"""
from __future__ import annotations

from db.local_study_data import coursework
from db.local_study_data.placement import Placement
from db.local_study_data.spec import Assessment, Concept

_UNIT_IMPORTANCE = 0.9
_CONCEPT_IMPORTANCE = 0.8


def _source_ids(place: Placement, concept_keys: set[str]) -> list[str]:
    """The outline's evidence for these concepts: the documents that teach
    them, or the first document (the syllabus) when none does."""
    teaching = [m for m in place.data.materials if concept_keys & set(m.concepts)]
    return [f"document:{place.document_id(m.key)}" for m in teaching or place.data.materials[:1]]


def _covers(assessment: Assessment, concept: Concept) -> bool:
    return concept.unit in assessment.covers or concept.key in assessment.concepts


def _earlier_exam_ids(place: Placement, concept: Concept) -> list[str]:
    """The exams the account already had that cover the concept, under the
    ids they have. One the account does not have is left out."""
    return [
        place.enrolled.exams[title] for title, keys in place.data.earlier_exams.items()
        if concept.key in keys and title in place.enrolled.exams
    ]


def _exam_ids(place: Placement, concept: Concept) -> list[str]:
    seeded = [
        place.assessment_id(a.key) for a in place.data.assessments
        if coursework.is_exam(a) and _covers(a, concept)
    ]
    return [*_earlier_exam_ids(place, concept), *seeded]


def _unit_topic(place: Placement, unit: str, concepts: list[Concept]) -> dict:
    return {
        "name": unit,
        "description": f"{unit}: the concepts this part of the course builds.",
        "parent": "",
        "prerequisites": [],
        "source_ids": _source_ids(place, {concept.key for concept in concepts}),
        "assessment_ids": [],
        "importance": _UNIT_IMPORTANCE,
    }


def _concept_topic(place: Placement, concept: Concept) -> dict:
    return {
        "name": concept.name,
        "description": concept.definition,
        "parent": concept.unit,
        "prerequisites": [place.data.concept(key).name for key in concept.needs],
        "source_ids": _source_ids(place, {concept.key}),
        "assessment_ids": _exam_ids(place, concept),
        "importance": _CONCEPT_IMPORTANCE,
    }


def topics(place: Placement) -> list[dict]:
    """Each unit, followed by its concepts."""
    out = []
    for unit in dict.fromkeys(concept.unit for concept in place.data.concepts):
        concepts = [concept for concept in place.data.concepts if concept.unit == unit]
        out.append(_unit_topic(place, unit, concepts))
        out.extend(_concept_topic(place, concept) for concept in concepts)
    return out
