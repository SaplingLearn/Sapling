"""
backend/routes/gradebook.py

User-driven gradebook: categories with weights, graded assignments,
per-course letter-scale override, syllabus-apply.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request

from db.connection import table
from models import (
    CreateCategoryBody,
    BulkUpdateCategoriesBody,
    CreateAssignmentBody,
    UpdateAssignmentBody,
    SetLetterScaleBody,
    SyllabusApplyBody,
)
from services import gradebook_service
from services.auth_guard import require_self

router = APIRouter()


def _user_owns_course(user_id: str, course_id: str) -> bool:
    rows = table("user_courses").select(
        "id",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        limit=1,
    )
    return bool(rows)


def _user_owns_category(user_id: str, category_id: str) -> dict | None:
    rows = table("course_categories").select(
        "*",
        filters={"id": f"eq.{category_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    )
    return rows[0] if rows else None


@router.get("/summary")
def get_summary(request: Request, user_id: str = Query(...), semester: str = Query(...)):
    """Return all enrolled courses for the given semester with computed
    current grade + letter."""
    require_self(user_id, request)

    enrollments = table("user_courses").select(
        "course_id,letter_scale,courses!inner(id,course_code,course_name,semester)",
        filters={
            "user_id": f"eq.{user_id}",
            "courses.semester": f"eq.{semester}",
        },
    )
    if not enrollments:
        return {"courses": []}

    course_ids = [e["course_id"] for e in enrollments]
    in_clause = "in.(" + ",".join(course_ids) + ")"

    cats = table("course_categories").select(
        "*",
        filters={"user_id": f"eq.{user_id}", "course_id": in_clause},
    )
    assigns = table("assignments").select(
        "id,course_id,category_id,points_possible,points_earned",
        filters={"user_id": f"eq.{user_id}", "course_id": in_clause},
    )

    cats_by_course: dict[str, list] = {cid: [] for cid in course_ids}
    for c in cats:
        cats_by_course.setdefault(c["course_id"], []).append(c)
    assigns_by_course: dict[str, list] = {cid: [] for cid in course_ids}
    for a in assigns:
        assigns_by_course.setdefault(a["course_id"], []).append(a)

    out = []
    for e in enrollments:
        cid = e["course_id"]
        course = e["courses"]
        course_assigns = assigns_by_course[cid]
        graded = [a for a in course_assigns
                  if a.get("points_possible") and a.get("points_earned") is not None]
        percent = gradebook_service.current_grade(cats_by_course[cid], course_assigns)
        letter = gradebook_service.letter_for(percent, e.get("letter_scale"))
        out.append({
            "course_id": cid,
            "course_code": course["course_code"],
            "course_name": course["course_name"],
            "semester": course["semester"],
            "percent": percent,
            "letter": letter,
            "graded_count": len(graded),
            "total_count": len(course_assigns),
        })
    return {"courses": out}


@router.get("/courses/{course_id}")
def get_course(course_id: str, request: Request, user_id: str = Query(...)):
    """Full gradebook for one course: categories, assignments, computed grade."""
    require_self(user_id, request)

    enrollment = table("user_courses").select(
        "course_id,letter_scale,courses!inner(id,course_code,course_name,semester)",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        limit=1,
    )
    if not enrollment:
        raise HTTPException(status_code=404, detail="Course not in your gradebook")
    course = enrollment[0]["courses"]
    letter_scale = enrollment[0].get("letter_scale")

    cats = table("course_categories").select(
        "*",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        order="sort_order.asc",
    )
    assigns = table("assignments").select(
        "*",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        order="due_date.asc",
    )

    # Per-category grade for the UI.
    by_cat: dict[str, list] = {c["id"]: [] for c in cats}
    for a in assigns:
        cid = a.get("category_id")
        if cid in by_cat:
            by_cat[cid].append(a)
    for c in cats:
        c["category_grade"] = gradebook_service.category_grade(by_cat[c["id"]])

    percent = gradebook_service.current_grade(cats, assigns)
    letter = gradebook_service.letter_for(percent, letter_scale)

    return {
        "course_id": course["id"],
        "course_code": course["course_code"],
        "course_name": course["course_name"],
        "semester": course["semester"],
        "percent": percent,
        "letter": letter,
        "letter_scale": letter_scale,
        "categories": cats,
        "assignments": assigns,
    }
