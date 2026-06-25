"""services/academics.py

Term / offering / enrollment resolution for the academics-split schema.

The public API speaks in **abstract** course ids (the catalog), while the
storage layer keys enrollments and class artifacts on a **course_offering**
(a course taught in a specific term). These helpers bridge the two:

- the knowledge graph stays on the abstract ``course_id`` (cumulative mastery),
- enrollments / gradebook / analytics resolve to an ``offering_id`` per term.

"Current term" is date-derived: the term whose ``[start_date, end_date]``
contains today. When today falls outside every seeded range we fall back to the
latest term by ``sort_key`` so resolution never dead-ends.
"""
from __future__ import annotations

import uuid
from datetime import date

from db.connection import table


def current_term(today: date | None = None) -> dict | None:
    """The current term row, or None if no terms are seeded.

    Date-derived: today ∈ [start_date, end_date]. Falls back to the most recent
    term (highest sort_key) so a date in a gap between terms still resolves.
    """
    d = (today or date.today()).isoformat()
    rows = table("terms").select(
        "*",
        filters={"start_date": f"lte.{d}", "end_date": f"gte.{d}"},
        order="sort_key.desc",
        limit=1,
    )
    if rows:
        return rows[0]
    latest = table("terms").select("*", order="sort_key.desc", limit=1)
    return latest[0] if latest else None


def list_terms() -> list[dict]:
    """All terms, most recent first — backs GET /api/semesters."""
    return table("terms").select(
        "id,term,year,label,start_date,end_date,sort_key",
        order="sort_key.desc",
    ) or []


def resolve_offering(
    course_id: str,
    term_id: str | None = None,
    *,
    create: bool = False,
) -> str | None:
    """Return the offering id for (course, term).

    ``term_id`` defaults to the current term. If no matching offering exists:
    - ``create=True`` inserts one (NULL section) and returns its id, so a fresh
      enrollment lands in the real current semester instead of a legacy term;
    - ``create=False`` falls back to any existing offering of the course.
    Returns None only when the course has no offering and we can't/shouldn't make one.
    """
    if not course_id:
        return None
    if not term_id:
        t = current_term()
        term_id = t["id"] if t else None

    if term_id:
        rows = table("course_offerings").select(
            "id",
            filters={"course_id": f"eq.{course_id}", "term_id": f"eq.{term_id}"},
            order="created_at.asc",
            limit=1,
        )
        if rows:
            return rows[0]["id"]

    if create and term_id:
        new_id = str(uuid.uuid4())
        table("course_offerings").insert(
            {"id": new_id, "course_id": course_id, "term_id": term_id}
        )
        return new_id

    # No offering in the target term and not creating — fall back to any offering
    # of this course so reads still resolve to something sensible.
    any_off = table("course_offerings").select(
        "id", filters={"course_id": f"eq.{course_id}"}, limit=1
    )
    return any_off[0]["id"] if any_off else None


def offering_course_id(offering_id: str) -> str | None:
    """The abstract course id an offering belongs to (offering → graph bridge)."""
    if not offering_id:
        return None
    rows = table("course_offerings").select(
        "course_id", filters={"id": f"eq.{offering_id}"}, limit=1
    )
    return rows[0]["course_id"] if rows else None


def user_offering_ids_for_course(user_id: str, course_id: str) -> list[str]:
    """The offerings of an abstract course that ``user_id`` is enrolled in.

    Two-step (offerings of the course, then the user's enrollments intersected)
    to avoid fragile PostgREST embedded-filter syntax.
    """
    offs = table("course_offerings").select(
        "id", filters={"course_id": f"eq.{course_id}"}
    ) or []
    off_ids = {o["id"] for o in offs}
    if not off_ids:
        return []
    enr = table("enrollments").select(
        "offering_id", filters={"user_id": f"eq.{user_id}"}
    ) or []
    return [e["offering_id"] for e in enr if e.get("offering_id") in off_ids]


def term_for_offering(offering_id: str) -> dict | None:
    """The term row for an offering (for semester labels)."""
    if not offering_id:
        return None
    rows = table("course_offerings").select(
        "term_id", filters={"id": f"eq.{offering_id}"}, limit=1
    )
    if not rows:
        return None
    term_id = rows[0].get("term_id")
    if not term_id:
        return None
    terms = table("terms").select("*", filters={"id": f"eq.{term_id}"}, limit=1)
    return terms[0] if terms else None
