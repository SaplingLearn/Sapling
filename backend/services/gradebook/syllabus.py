"""
backend/services/gradebook/syllabus.py

Apply user-confirmed syllabus extraction to an enrollment (#118: moved
verbatim out of ``routes/gradebook.py::apply_syllabus``). The route resolves
the enrollment and maps the domain errors; this module validates the document
and the weights, then wipes + replaces the categories, inserts the deduped
assignments and stamps ``enrollments.syllabus_doc_id``.
"""
from __future__ import annotations

import uuid

from db.connection import table
from services.encryption import encrypt_if_present
from services.gradebook.errors import DocumentNotOwned, InvalidCategoryWeights


def apply_syllabus_to_enrollment(enr: dict, body) -> None:
    """Write ``body`` (a ``SyllabusApplyBody``) onto the resolved enrollment.

    Raises ``DocumentNotOwned`` when the document is not the caller's and
    ``InvalidCategoryWeights`` when non-empty categories do not sum to 100.
    """
    doc_rows = table("documents").select(
        "id,user_id",
        filters={"id": f"eq.{body.doc_id}"},
        limit=1,
    )
    if not doc_rows or doc_rows[0]["user_id"] != body.user_id:
        raise DocumentNotOwned("Document not yours")

    total = sum(c.weight for c in body.categories)
    if body.categories and abs(total - 100.0) > 0.5:
        raise InvalidCategoryWeights(f"Category weights must sum to 100% (got {total:g}%)")

    # Wipe + replace categories.
    table("gradebook_categories").delete(filters={"enrollment_id": f"eq.{enr['id']}"})
    new_cats = [
        {
            "id": str(uuid.uuid4()),
            "enrollment_id": enr["id"],
            "name": c.name,
            "weight": c.weight,
            "sort_order": c.sort_order,
            "drop_lowest": c.drop_lowest,
        }
        for c in body.categories
    ]
    if new_cats:
        table("gradebook_categories").insert(new_cats)

    # Dedupe assignments by (title, due_date) within the enrollment.
    existing = table("assignments").select(
        "title,due_date",
        filters={"enrollment_id": f"eq.{enr['id']}"},
    )
    seen = {(e.get("title", ""), e.get("due_date") or "") for e in existing}
    new_assigns = []
    for a in body.assignments:
        title = a.get("title", "")
        due = a.get("due_date") or ""
        if (title, due) in seen:
            continue
        seen.add((title, due))
        new_assigns.append({
            "id": str(uuid.uuid4()),
            "enrollment_id": enr["id"],
            "title": title,
            "due_date": a.get("due_date"),
            "assignment_type": a.get("assignment_type"),
            "notes": encrypt_if_present(a.get("notes")),
            "category_id": None,
            "points_possible": None,
            "points_earned": None,
            "source": "syllabus",
        })
    if new_assigns:
        table("assignments").insert(new_assigns)

    # Stamp the doc id on the enrollment.
    table("enrollments").update(
        {"syllabus_doc_id": body.doc_id},
        filters={"id": f"eq.{enr['id']}"},
    )
