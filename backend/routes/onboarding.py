import uuid

from fastapi import APIRouter, HTTPException, Query, Request

from db.connection import table
from models import OnboardingBody
from services.auth_guard import require_self

router = APIRouter()


@router.get("/courses")
def search_courses(request: Request, q: str = Query("", min_length=0)):
    """Search courses by name or code. Returns all if q is empty."""
    filters = {}
    if q.strip():
        filters["or"] = f"(course_name.ilike.%{q}%,course_code.ilike.%{q}%)"

    rows = table("courses").select(
        "id,course_code,course_name",
        filters=filters,
        order="course_name.asc",
        limit=20,
    )
    return {"courses": rows}


@router.post("/profile")
def save_onboarding_profile(body: OnboardingBody, request: Request):
    """Save the onboarding form data for an existing user."""
    require_self(body.user_id, request)

    # Verify user exists
    user = table("users").select("id", filters={"id": f"eq.{body.user_id}"})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update user profile fields
    name = f"{body.first_name} {body.last_name}".strip()  # ENCRYPTED LATER
    table("users").update(
        {
            "name": name,  # ENCRYPTED LATER
            "first_name": body.first_name,  # ENCRYPTED LATER
            "last_name": body.last_name,  # ENCRYPTED LATER
            "year": body.year,
            "majors": body.majors,
            "minors": body.minors,
            "learning_style": body.learning_style,
            "onboarding_completed": True,
        },
        filters={"id": f"eq.{body.user_id}"},
    )

    # Enroll user in selected courses
    enrolled_ids = []
    for course_id in body.course_ids:
        # Verify course exists
        course = table("courses").select("id", filters={"id": f"eq.{course_id}"})
        if not course:
            continue

        # Enroll if not already enrolled
        existing = table("user_courses").select(
            "id",
            filters={
                "user_id": f"eq.{body.user_id}",
                "course_id": f"eq.{course_id}",
            },
        )
        if not existing:
            table("user_courses").insert({
                "id": str(uuid.uuid4()),
                "user_id": body.user_id,
                "course_id": course_id,
            })

        enrolled_ids.append(course_id)

    return {
        "user_id": body.user_id,
        "courses_linked": enrolled_ids,
    }
