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


@router.post("/courses/{course_id}/categories")
def create_category(course_id: str, body: CreateCategoryBody, request: Request):
    require_self(body.user_id, request)
    if not _user_owns_course(body.user_id, course_id):
        raise HTTPException(status_code=404, detail="Course not in your gradebook")
    new_id = str(uuid.uuid4())
    inserted = table("course_categories").insert({
        "id": new_id,
        "user_id": body.user_id,
        "course_id": course_id,
        "name": body.name,
        "weight": body.weight,
        "sort_order": 0,
    })
    return {"category": inserted[0] if inserted else None}


@router.patch("/courses/{course_id}/categories")
def bulk_update_categories(course_id: str, body: BulkUpdateCategoriesBody, request: Request):
    require_self(body.user_id, request)
    if not _user_owns_course(body.user_id, course_id):
        raise HTTPException(status_code=404, detail="Course not in your gradebook")

    total = sum(c.weight for c in body.categories)
    if abs(total - 100.0) > 0.5:
        raise HTTPException(
            status_code=400,
            detail=f"Category weights must sum to 100% (got {total:g}%)",
        )

    saved = []
    for c in body.categories:
        if c.id:
            updated = table("course_categories").update(
                {"name": c.name, "weight": c.weight, "sort_order": c.sort_order},
                filters={"id": f"eq.{c.id}", "user_id": f"eq.{body.user_id}"},
            )
            saved.extend(updated)
        else:
            new = table("course_categories").insert({
                "id": str(uuid.uuid4()),
                "user_id": body.user_id,
                "course_id": course_id,
                "name": c.name,
                "weight": c.weight,
                "sort_order": c.sort_order,
            })
            saved.extend(new)
    return {"categories": saved}


@router.delete("/categories/{category_id}")
def delete_category(category_id: str, request: Request, user_id: str = Query(...)):
    require_self(user_id, request)
    cat = _user_owns_category(user_id, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    table("course_categories").delete(filters={"id": f"eq.{category_id}"})
    return {"deleted": True}


def _user_owns_assignment(user_id: str, assignment_id: str) -> dict | None:
    rows = table("assignments").select(
        "*",
        filters={"id": f"eq.{assignment_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    )
    return rows[0] if rows else None


@router.post("/assignments")
def create_assignment(body: CreateAssignmentBody, request: Request):
    require_self(body.user_id, request)
    if not _user_owns_course(body.user_id, body.course_id):
        raise HTTPException(status_code=404, detail="Course not in your gradebook")
    if body.category_id and not _user_owns_category(body.user_id, body.category_id):
        raise HTTPException(status_code=400, detail="Category not in your gradebook")

    new_id = str(uuid.uuid4())
    inserted = table("assignments").insert({
        "id": new_id,
        "user_id": body.user_id,
        "course_id": body.course_id,
        "title": body.title,
        "category_id": body.category_id,
        "points_possible": body.points_possible,
        "points_earned": body.points_earned,
        "due_date": body.due_date,
        "assignment_type": body.assignment_type,
        "notes": body.notes,
        "source": "manual",
    })
    return {"assignment": inserted[0] if inserted else None}


@router.patch("/assignments/{assignment_id}")
def update_assignment_route(assignment_id: str, body: UpdateAssignmentBody, request: Request):
    require_self(body.user_id, request)
    if not _user_owns_assignment(body.user_id, assignment_id):
        raise HTTPException(status_code=404, detail="Assignment not found")
    if body.category_id and not _user_owns_category(body.user_id, body.category_id):
        raise HTTPException(status_code=400, detail="Category not in your gradebook")

    patch_data = body.model_dump(exclude_unset=True, exclude={"user_id"})
    if not patch_data:
        return {"updated": False}
    table("assignments").update(
        patch_data,
        filters={"id": f"eq.{assignment_id}", "user_id": f"eq.{body.user_id}"},
    )
    return {"updated": True}


@router.delete("/assignments/{assignment_id}")
def delete_assignment_route(assignment_id: str, request: Request, user_id: str = Query(...)):
    require_self(user_id, request)
    if not _user_owns_assignment(user_id, assignment_id):
        raise HTTPException(status_code=404, detail="Assignment not found")
    table("assignments").delete(
        filters={"id": f"eq.{assignment_id}", "user_id": f"eq.{user_id}"},
    )
    return {"deleted": True}


@router.patch("/courses/{course_id}/scale")
def set_letter_scale(course_id: str, body: SetLetterScaleBody, request: Request):
    require_self(body.user_id, request)
    if not _user_owns_course(body.user_id, course_id):
        raise HTTPException(status_code=404, detail="Course not in your gradebook")

    scale_payload = None
    if body.scale is not None:
        prev_min = float("inf")
        for tier in body.scale:
            if tier.min > prev_min:
                raise HTTPException(
                    status_code=400,
                    detail="Letter scale tiers must be ordered descending by min",
                )
            prev_min = tier.min
        scale_payload = [tier.model_dump() for tier in body.scale]

    table("user_courses").update(
        {"letter_scale": scale_payload},
        filters={"user_id": f"eq.{body.user_id}", "course_id": f"eq.{course_id}"},
    )
    return {"updated": True, "letter_scale": scale_payload}
