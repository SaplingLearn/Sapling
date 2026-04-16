import uuid

from fastapi import APIRouter, HTTPException

from db.connection import table
from models import OnboardingBody

router = APIRouter()


@router.post("/profile")
def save_onboarding_profile(body: OnboardingBody):
    """Save the onboarding form data for an existing user."""

    # Verify user exists
    user = table("users").select("id", filters={"id": f"eq.{body.user_id}"})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update user profile fields
    name = f"{body.first_name} {body.last_name}".strip()
    table("users").update(
        {
            "name": name,
            "first_name": body.first_name,
            "last_name": body.last_name,
            "class_year": body.year,
            "majors": body.majors,
            "minors": body.minors,
            "learning_style": body.learning_style,
        },
        filters={"id": f"eq.{body.user_id}"},
    )

    # Upsert courses and enroll the user
    course_ids = []
    for course_name in body.courses:
        course_name = course_name.strip()
        if not course_name:
            continue

        # Check if a course with this name already exists at BU
        existing = table("courses").select(
            "id",
            filters={
                "course_name": f"eq.{course_name}",
                "school": "eq.Boston University",
            },
        )

        if existing:
            course_id = existing[0]["id"]
        else:
            course_id = str(uuid.uuid4())
            table("courses").insert({
                "id": course_id,
                "course_code": course_name,
                "course_name": course_name,
                "school": "Boston University",
            })

        # Enroll user if not already enrolled
        enrolled = table("user_courses").select(
            "id",
            filters={
                "user_id": f"eq.{body.user_id}",
                "course_id": f"eq.{course_id}",
            },
        )
        if not enrolled:
            table("user_courses").insert({
                "id": str(uuid.uuid4()),
                "user_id": body.user_id,
                "course_id": course_id,
            })

        course_ids.append(course_id)

    return {
        "user_id": body.user_id,
        "courses_linked": course_ids,
    }
