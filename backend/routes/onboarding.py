import uuid

from fastapi import APIRouter, HTTPException, Query, Request

from db.connection import table
from models import OnboardingBody
from services.academics import resolve_offering
from services.auth_guard import require_self
from services.encryption import encrypt_if_present

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
    name = f"{body.first_name} {body.last_name}".strip()
    table("users").update(
        {
            "name": encrypt_if_present(name),
            "first_name": encrypt_if_present(body.first_name),
            "last_name": encrypt_if_present(body.last_name),
            "year": body.year,
            "majors": body.majors,
            "minors": body.minors,
            "learning_style": body.learning_style,
            "onboarding_completed": True,
        },
        filters={"id": f"eq.{body.user_id}"},
    )

    # Enroll user in selected courses (resolve each abstract course → current-term offering)
    enrolled_ids = []
    for course_id in body.course_ids:
        # Verify abstract course exists in the catalog
        course = table("courses").select("id", filters={"id": f"eq.{course_id}"})
        if not course:
            continue

        # Resolve the abstract course to a current-term offering, creating a
        # NULL-section offering if the catalog lacks one for this term.
        offering_id = resolve_offering(course_id, create=True)
        if not offering_id:
            continue

        # Enroll if not already enrolled in this offering
        existing = table("enrollments").select(
            "id",
            filters={
                "user_id": f"eq.{body.user_id}",
                "offering_id": f"eq.{offering_id}",
            },
        )
        if not existing:
            table("enrollments").insert({
                "id": str(uuid.uuid4()),
                "user_id": body.user_id,
                "offering_id": offering_id,
            })

        enrolled_ids.append(course_id)  # response still reports abstract course ids

    return {
        "user_id": body.user_id,
        "courses_linked": enrolled_ids,
    }
