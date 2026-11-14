"""The class's uploaded documents, and each one's text as a study guide's
writer reads it."""
from __future__ import annotations

from datetime import timedelta

from db.local_study_data import clock
from db.local_study_data.placement import Placement
from db.local_study_data.spec import ClassData, Material


def concept_notes(data: ClassData, material: Material) -> list[dict]:
    """``documents.concept_notes``: the concepts the document teaches."""
    concepts = [data.concept(key) for key in material.concepts]
    return [{"name": concept.name, "description": concept.definition} for concept in concepts]


def body(material: Material) -> str:
    return "\n\n".join(material.text)


def source_text(data: ClassData, material: Material) -> str:
    """The document as ``services.study_guides.materials`` hands it to a
    guide's writer and to the citation check: its summary, its concept notes,
    then its text."""
    notes = "\n".join(f"- {n['name']}: {n['description']}" for n in concept_notes(data, material))
    return "\n\n".join([f"Summary: {material.summary}", f"Key concepts:\n{notes}", body(material)])


def documents(place: Placement) -> list[dict]:
    rows = []
    for material in place.data.materials:
        created = clock.uploaded(place.now, material.days_ago)
        rows.append({
            "id": place.document_id(material.key),
            "user_id": place.owner_id,
            "offering_id": place.enrolled.offering_id,
            "file_name": material.file_name,
            "category": material.category,
            "summary": material.summary,
            "concept_notes": concept_notes(place.data, material),
            "extracted_text": body(material),
            "created_at": clock.utc(created),
            "processed_at": clock.utc(created + timedelta(minutes=1)),
        })
    return rows
