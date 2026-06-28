"""
backend/routes/gradebook.py

User-driven gradebook, semester-aware on the academics-split schema.

The public API still speaks the **abstract** ``course_id`` plus an optional
``semester`` (a term label, default = current term). Internally we resolve
``(course_id, semester)`` to the user's **enrollment** (one offering of the
course in that term) and key categories/assignments on ``enrollment_id``.

- gradebook_categories / assignments key on enrollment_id (no user_id/course_id).
- points_possible/points_earned/notes stay 🔒 TEXT: encrypt at write, decrypt at read.
- bell-curve (enrollments.curve_*) + drop-lowest (gradebook_categories.drop_lowest)
  feed the weighted-score computation in services/gradebook_service.py.
- GPA: per-semester (one term) and cumulative/transcript (credit-weighted across
  all the user's offerings of all enrolled courses).
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
    SetCurveBody,
    SyllabusApplyBody,
    CurveSettingsBody,
)
from services import academics, gradebook_service
from services.auth_guard import require_self
from services.encryption import encrypt_if_present, decrypt_if_present, decrypt_numeric

router = APIRouter()


# ── Enrollment resolution ────────────────────────────────────────────────────

def _term_id_for_semester(semester: str | None) -> str | None:
    """Map a `semester` query value to a term id.

    `semester` is a term **label** (e.g. "Spring 2026"); fall back to treating
    it as a term id directly. None → None (caller defaults to current term).
    """
    if not semester:
        return None
    rows = table("terms").select(
        "id", filters={"label": f"eq.{semester}"}, limit=1
    )
    if rows:
        return rows[0]["id"]
    # Maybe the caller already passed a term id.
    rows = table("terms").select("id", filters={"id": f"eq.{semester}"}, limit=1)
    return rows[0]["id"] if rows else None


def _resolve_enrollment(user_id: str, course_id: str, semester: str | None) -> dict | None:
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

    target_term_id = _term_id_for_semester(semester)
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


def _course_meta(offering_id: str) -> dict:
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


def _load_categories(enrollment_id: str, order: str | None = None) -> list[dict]:
    return table("gradebook_categories").select(
        "id,enrollment_id,name,weight,sort_order,drop_lowest",
        filters={"enrollment_id": f"eq.{enrollment_id}"},
        order=order or "sort_order.asc",
    )


def _load_assignments(enrollment_id: str, *, order: str | None = None, decrypt: bool = True) -> list[dict]:
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


def _enrollment_grade(enr: dict, cats: list[dict], assigns: list[dict]):
    """Computed (percent, letter) for an enrollment, applying curve + drop-lowest."""
    percent = gradebook_service.current_grade(
        cats,
        assigns,
        curve_mode=enr.get("curve_mode") or "raw",
        curve_avg_target=enr.get("curve_avg_target"),
        curve_sd_delta=enr.get("curve_sd_delta"),
    )
    letter = gradebook_service.letter_for(percent, enr.get("letter_scale"))
    return percent, letter


def _owned_category(user_id: str, category_id: str) -> dict | None:
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


def _owned_assignment(user_id: str, assignment_id: str) -> dict | None:
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


# ── GET /summary ─────────────────────────────────────────────────────────────

@router.get("/summary")
def get_summary(request: Request, user_id: str = Query(...), semester: str = Query(...)):
    """All of the user's enrolled courses for the given semester with computed
    current grade + letter, plus the term GPA."""
    require_self(user_id, request)

    term_id = _term_id_for_semester(semester)
    if not term_id:
        return {"courses": [], "gpa": None, "semester": semester}

    enrollments = table("enrollments").select(
        "id,user_id,offering_id,letter_scale,curve_mode,curve_avg_target,curve_sd_delta",
        filters={"user_id": f"eq.{user_id}"},
    ) or []

    out = []
    course_grades = []
    for enr in enrollments:
        offering_id = enr["offering_id"]
        term = academics.term_for_offering(offering_id)
        if not term or term.get("id") != term_id:
            continue
        meta = _course_meta(offering_id)
        cats = _load_categories(enr["id"])
        assigns = _load_assignments(enr["id"])
        graded = [a for a in assigns
                  if a.get("points_possible") and a.get("points_earned") is not None]
        percent, letter = _enrollment_grade(enr, cats, assigns)
        out.append({
            "course_id": meta["course_id"],
            "course_code": meta["course_code"],
            "course_name": meta["course_name"],
            "semester": meta["semester"],
            "percent": percent,
            "letter": letter,
            "graded_count": len(graded),
            "total_count": len(assigns),
        })
        course_grades.append({
            "grade_points": gradebook_service.gpa_points(percent, enr.get("letter_scale")),
            "credits": meta.get("credits"),
        })

    return {
        "courses": out,
        "gpa": gradebook_service.weighted_gpa(course_grades),
        "semester": semester,
    }


# ── GET /courses/{course_id} ─────────────────────────────────────────────────

@router.get("/courses/{course_id}")
def get_course(
    course_id: str,
    request: Request,
    user_id: str = Query(...),
    semester: str | None = Query(None),
):
    """Full gradebook for one enrollment: categories, assignments, computed grade."""
    require_self(user_id, request)

    enr = _resolve_enrollment(user_id, course_id, semester)
    if not enr:
        raise HTTPException(status_code=404, detail="Course not in your gradebook")

    meta = _course_meta(enr["offering_id"])
    cats = _load_categories(enr["id"])
    assigns = _load_assignments(enr["id"])

    # Per-category grade for the UI (respects drop_lowest, raw 0–100).
    by_cat: dict[str, list] = {c["id"]: [] for c in cats}
    for a in assigns:
        cid = a.get("category_id")
        if cid in by_cat:
            by_cat[cid].append(a)
    for c in cats:
        c["category_grade"] = gradebook_service.category_grade(
            by_cat[c["id"]], int(c.get("drop_lowest") or 0)
        )

    percent, letter = _enrollment_grade(enr, cats, assigns)
    dropped_ids = gradebook_service.all_dropped_ids(cats, assigns)

    return {
        "course_id": meta["course_id"],
        "course_code": meta["course_code"],
        "course_name": meta["course_name"],
        "semester": meta["semester"],
        "percent": percent,
        "letter": letter,
        "letter_scale": enr.get("letter_scale"),
        "curve_mode": enr.get("curve_mode") or "raw",
        "curve_avg_target": enr.get("curve_avg_target"),
        "curve_sd_delta": enr.get("curve_sd_delta"),
        "categories": cats,
        "assignments": assigns,
        "dropped_assignment_ids": dropped_ids,
    }


# ── Categories CRUD ──────────────────────────────────────────────────────────

@router.post("/courses/{course_id}/categories")
def create_category(course_id: str, body: CreateCategoryBody, request: Request):
    """Create a new grade category for the given course."""
    require_self(body.user_id, request)
    enr = _resolve_enrollment(body.user_id, course_id, body.semester)
    if not enr:
        raise HTTPException(status_code=404, detail="Course not in your gradebook")
    new_id = str(uuid.uuid4())
    inserted = table("gradebook_categories").insert({
        "id": new_id,
        "enrollment_id": enr["id"],
        "name": body.name,
        "weight": body.weight,
        "sort_order": 0,
        "drop_lowest": body.drop_lowest,
    })
    return {"category": inserted[0] if inserted else None}


@router.patch("/courses/{course_id}/categories")
def bulk_update_categories(course_id: str, body: BulkUpdateCategoriesBody, request: Request):
    """Replace all categories for a course. Validates that weights sum to 100%."""
    require_self(body.user_id, request)
    enr = _resolve_enrollment(body.user_id, course_id, body.semester)
    if not enr:
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
            updated = table("gradebook_categories").update(
                {
                    "name": c.name,
                    "weight": c.weight,
                    "sort_order": c.sort_order,
                    "drop_lowest": c.drop_lowest,
                },
                filters={"id": f"eq.{c.id}", "enrollment_id": f"eq.{enr['id']}"},
            )
            saved.extend(updated)
        else:
            new = table("gradebook_categories").insert({
                "id": str(uuid.uuid4()),
                "enrollment_id": enr["id"],
                "name": c.name,
                "weight": c.weight,
                "sort_order": c.sort_order,
                "drop_lowest": c.drop_lowest,
            })
            saved.extend(new)
    return {"categories": saved}


@router.delete("/categories/{category_id}")
def delete_category(category_id: str, request: Request, user_id: str = Query(...)):
    """Delete a category if it belongs to user_id."""
    require_self(user_id, request)
    cat = _owned_category(user_id, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    table("gradebook_categories").delete(filters={"id": f"eq.{category_id}"})
    return {"deleted": True}


# ── Assignments CRUD ─────────────────────────────────────────────────────────

@router.post("/assignments")
def create_assignment(body: CreateAssignmentBody, request: Request):
    """Create a graded assignment; encrypts points_possible, points_earned, and notes at rest."""
    require_self(body.user_id, request)
    enr = _resolve_enrollment(body.user_id, body.course_id, body.semester)
    if not enr:
        raise HTTPException(status_code=404, detail="Course not in your gradebook")
    if body.category_id and not _owned_category(body.user_id, body.category_id):
        raise HTTPException(status_code=400, detail="Category not in your gradebook")

    new_id = str(uuid.uuid4())
    inserted = table("assignments").insert({
        "id": new_id,
        "enrollment_id": enr["id"],
        "title": body.title,
        "category_id": body.category_id,
        "points_possible": encrypt_if_present(body.points_possible),
        "points_earned": encrypt_if_present(body.points_earned),
        "due_date": body.due_date,
        "assignment_type": body.assignment_type,
        "notes": encrypt_if_present(body.notes),
        "source": "manual",
        "curve_class_mean": body.curve_class_mean,
        "curve_class_sd": body.curve_class_sd,
        "curve_avg_target": body.curve_avg_target,
        "curve_sd_delta": body.curve_sd_delta,
    })
    # #126 (#18): the insert representation returns the stored ciphertext for
    # points/notes. Decrypt before returning so the client never receives
    # ciphertext, matching the read path in get_course.
    row = inserted[0] if inserted else None
    if row:
        row["points_possible"] = decrypt_numeric(row.get("points_possible"))
        row["points_earned"] = decrypt_numeric(row.get("points_earned"))
        row["notes"] = decrypt_if_present(row.get("notes"))
    return {"assignment": row}


@router.patch("/assignments/{assignment_id}")
def update_assignment_route(assignment_id: str, body: UpdateAssignmentBody, request: Request):
    """Partial-update an assignment. Encrypts any point/notes fields before writing."""
    require_self(body.user_id, request)
    if not _owned_assignment(body.user_id, assignment_id):
        raise HTTPException(status_code=404, detail="Assignment not found")
    if body.category_id and not _owned_category(body.user_id, body.category_id):
        raise HTTPException(status_code=400, detail="Category not in your gradebook")

    incoming = body.model_dump(exclude_unset=True, exclude={"user_id"})
    ALLOWED = {
        "title", "category_id", "due_date", "assignment_type",
        "curve_class_mean", "curve_class_sd", "curve_avg_target", "curve_sd_delta",
    }
    ENCRYPTED_FIELDS = {"points_possible", "points_earned", "notes"}
    patch_data = {k: v for k, v in incoming.items() if k in ALLOWED}
    for k in ENCRYPTED_FIELDS:
        if k in incoming:
            patch_data[k] = encrypt_if_present(incoming[k])
    if not patch_data:
        return {"updated": False}
    table("assignments").update(
        patch_data,
        filters={"id": f"eq.{assignment_id}"},
    )
    return {"updated": True}


@router.delete("/assignments/{assignment_id}")
def delete_assignment_route(assignment_id: str, request: Request, user_id: str = Query(...)):
    """Delete an assignment belonging to user_id."""
    require_self(user_id, request)
    if not _owned_assignment(user_id, assignment_id):
        raise HTTPException(status_code=404, detail="Assignment not found")
    table("assignments").delete(filters={"id": f"eq.{assignment_id}"})
    return {"deleted": True}


# ── POST /syllabus/apply ─────────────────────────────────────────────────────

@router.post("/syllabus/apply")
def apply_syllabus(body: SyllabusApplyBody, request: Request):
    """Apply user-confirmed extracted categories + assignments to an enrollment.

    - Validates weights sum to 100 (±0.5).
    - Validates the user owns the enrollment AND the document.
    - Wipes existing categories for the enrollment; inserts new ones.
    - Inserts assignments with source='syllabus', dedupes by (title, due_date).
    - Sets enrollments.syllabus_doc_id.
    - Returns the refreshed course detail.
    """
    require_self(body.user_id, request)
    enr = _resolve_enrollment(body.user_id, body.course_id, body.semester)
    if not enr:
        raise HTTPException(status_code=404, detail="Course not in your gradebook")

    doc_rows = table("documents").select(
        "id,user_id",
        filters={"id": f"eq.{body.doc_id}"},
        limit=1,
    )
    if not doc_rows or doc_rows[0]["user_id"] != body.user_id:
        raise HTTPException(status_code=403, detail="Document not yours")

    total = sum(c.weight for c in body.categories)
    if body.categories and abs(total - 100.0) > 0.5:
        raise HTTPException(
            status_code=400,
            detail=f"Category weights must sum to 100% (got {total:g}%)",
        )

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

    # Return the refreshed course payload so the client can swap state in.
    refreshed = get_course(body.course_id, request, user_id=body.user_id, semester=body.semester)
    return {"course": refreshed}


# ── PATCH /courses/{course_id}/scale ─────────────────────────────────────────

@router.patch("/courses/{course_id}/scale")
def set_letter_scale(course_id: str, body: SetLetterScaleBody, request: Request):
    """Override the default A/B/C… letter scale for a course. Pass scale=null to reset to default."""
    require_self(body.user_id, request)
    enr = _resolve_enrollment(body.user_id, course_id, body.semester)
    if not enr:
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

    table("enrollments").update(
        {"letter_scale": scale_payload},
        filters={"id": f"eq.{enr['id']}"},
    )
    return {"updated": True, "letter_scale": scale_payload}


# ── PATCH /courses/{course_id}/curve ─────────────────────────────────────────

@router.patch("/courses/{course_id}/curve")
def set_curve(course_id: str, body: SetCurveBody, request: Request):
    """Set the per-enrollment bell-curve policy (enrollments.curve_*)."""
    require_self(body.user_id, request)
    enr = _resolve_enrollment(body.user_id, course_id, body.semester)
    if not enr:
        raise HTTPException(status_code=404, detail="Course not in your gradebook")

    payload = {
        "curve_mode": body.curve_mode,
        "curve_avg_target": body.curve_avg_target,
        "curve_sd_delta": body.curve_sd_delta,
    }
    table("enrollments").update(payload, filters={"id": f"eq.{enr['id']}"})
    return {"updated": True, **payload}


# ── GET /gpa ─────────────────────────────────────────────────────────────────

@router.get("/gpa")
def get_gpa(request: Request, user_id: str = Query(...), semester: str | None = Query(None)):
    """Credit-weighted GPA.

    Without `semester`: cumulative/transcript GPA across **all** the user's
    offerings of all enrolled courses (all terms). With `semester`: the GPA for
    that one term only. Returns per-course grade points + the overall GPA.
    """
    require_self(user_id, request)

    term_id = _term_id_for_semester(semester) if semester else None

    enrollments = table("enrollments").select(
        "id,user_id,offering_id,letter_scale,curve_mode,curve_avg_target,curve_sd_delta",
        filters={"user_id": f"eq.{user_id}"},
    ) or []

    courses = []
    course_grades = []
    for enr in enrollments:
        offering_id = enr["offering_id"]
        if term_id:
            term = academics.term_for_offering(offering_id)
            if not term or term.get("id") != term_id:
                continue
        meta = _course_meta(offering_id)
        cats = _load_categories(enr["id"])
        assigns = _load_assignments(enr["id"])
        percent, letter = _enrollment_grade(enr, cats, assigns)
        gp = gradebook_service.gpa_points(percent, enr.get("letter_scale"))
        courses.append({
            "course_id": meta["course_id"],
            "course_code": meta["course_code"],
            "semester": meta["semester"],
            "credits": meta.get("credits"),
            "percent": percent,
            "letter": letter,
            "grade_points": gp,
        })
        course_grades.append({"grade_points": gp, "credits": meta.get("credits")})

    return {
        "gpa": gradebook_service.weighted_gpa(course_grades),
        "courses": courses,
        "semester": semester,
        "scope": "semester" if term_id else "cumulative",
    }
