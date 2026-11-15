"""
backend/services/gradebook/enrollments.py

Enrollment resolution and the gradebook's row loaders (#118: moved verbatim
out of ``routes/gradebook.py``).

The public API speaks the abstract ``course_id`` plus an optional
``semester``; ``resolve_enrollment`` turns that into the user's enrollment
row, and the loaders read the enrollment-keyed ``gradebook_categories`` /
``assignments`` rows (decrypting the 🔒 points/notes columns at read).
"""
from __future__ import annotations

from db.connection import table
from services import academics
from services.encryption import decrypt_if_present, decrypt_numeric
from services.gradebook import grades


# ── Enrollment resolution ────────────────────────────────────────────────────
# `semester` query values (term labels, with a term-id fallback) resolve via
# the shared `academics.term_id_for_label` — one mapping across the API.


def resolve_enrollment(user_id: str, course_id: str, semester: str | None) -> dict | None:
    """Resolve (user, abstract course, term) → the user's enrollment row.

    Intersect the user's offerings of the course with the target term:
    - if `semester` is given, pick the offering in that term;
    - else default to the current term's offering, falling back to the only /
      most-recent offering the user has for the course.
    Returns the full enrollments row (curve_*, letter_scale, syllabus_doc_id,
    offering_id) or None when the user has no matching enrollment.
    """
    offering_ids = academics.user_offering_ids_for_course(user_id, course_id)
    if not offering_ids:
        return None

    target_term_id = academics.term_id_for_label(semester)
    if target_term_id is None and semester is None:
        cur = academics.current_term()
        target_term_id = cur["id"] if cur else None

    chosen_offering: str | None = None
    if target_term_id:
        for oid in offering_ids:
            t = academics.term_for_offering(oid)
            if t and t.get("id") == target_term_id:
                chosen_offering = oid
                break
    # No term match (or no term resolvable): fall back to the only offering, so
    # single-section courses keep working without a semester param.
    if chosen_offering is None and semester is None and len(offering_ids) == 1:
        chosen_offering = offering_ids[0]
    if chosen_offering is None:
        return None

    rows = table("enrollments").select(
        "id,user_id,offering_id,letter_scale,syllabus_doc_id,"
        "curve_mode,curve_avg_target,curve_sd_delta",
        filters={"user_id": f"eq.{user_id}", "offering_id": f"eq.{chosen_offering}"},
        limit=1,
    )
    return rows[0] if rows else None


def course_meta(offering_id: str) -> dict:
    """Abstract course code/name + credits + term label for an offering."""
    course_id = academics.offering_course_id(offering_id)
    course = {}
    if course_id:
        rows = table("courses").select(
            "id,course_code,course_name,credits",
            filters={"id": f"eq.{course_id}"},
            limit=1,
        )
        course = rows[0] if rows else {}
    term = academics.term_for_offering(offering_id) or {}
    return {
        "course_id": course_id,
        "course_code": course.get("course_code"),
        "course_name": course.get("course_name"),
        "credits": course.get("credits"),
        "semester": term.get("label"),
    }


def load_categories(enrollment_id: str, order: str | None = None) -> list[dict]:
    return table("gradebook_categories").select(
        "id,enrollment_id,name,weight,sort_order,drop_lowest",
        filters={"enrollment_id": f"eq.{enrollment_id}"},
        order=order or "sort_order.asc",
    )


def load_assignments(enrollment_id: str, *, order: str | None = None, decrypt: bool = True) -> list[dict]:
    assigns = table("assignments").select(
        "id,enrollment_id,category_id,title,due_date,assignment_type,"
        "points_possible,points_earned,notes,source,"
        "curve_class_mean,curve_class_sd",
        filters={"enrollment_id": f"eq.{enrollment_id}"},
        order=order or "due_date.asc",
    )
    if decrypt:
        for a in assigns:
            a["points_possible"] = decrypt_numeric(a.get("points_possible"))
            a["points_earned"] = decrypt_numeric(a.get("points_earned"))
            a["notes"] = decrypt_if_present(a.get("notes"))
    return assigns


def enrollment_grade(enr: dict, cats: list[dict], assigns: list[dict]):
    """Computed (percent, letter) for an enrollment, applying curve + drop-lowest."""
    percent = grades.current_grade(
        cats,
        assigns,
        curve_mode=enr.get("curve_mode") or "raw",
        curve_avg_target=enr.get("curve_avg_target"),
        curve_sd_delta=enr.get("curve_sd_delta"),
    )
    letter = grades.letter_for(percent, enr.get("letter_scale"))
    return percent, letter


def owned_category(user_id: str, category_id: str) -> dict | None:
    """A gradebook_category by id whose enrollment belongs to `user_id`."""
    rows = table("gradebook_categories").select(
        "id,enrollment_id,name,weight,sort_order,drop_lowest",
        filters={"id": f"eq.{category_id}"},
        limit=1,
    )
    if not rows:
        return None
    cat = rows[0]
    enr = table("enrollments").select(
        "id,user_id",
        filters={"id": f"eq.{cat['enrollment_id']}", "user_id": f"eq.{user_id}"},
        limit=1,
    )
    return cat if enr else None


def owned_assignment(user_id: str, assignment_id: str) -> dict | None:
    rows = table("assignments").select(
        "id,enrollment_id,category_id",
        filters={"id": f"eq.{assignment_id}"},
        limit=1,
    )
    if not rows:
        return None
    a = rows[0]
    if not a.get("enrollment_id"):
        return None
    enr = table("enrollments").select(
        "id,user_id",
        filters={"id": f"eq.{a['enrollment_id']}", "user_id": f"eq.{user_id}"},
        limit=1,
    )
    return a if enr else None
