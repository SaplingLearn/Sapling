"""Authenticated checklist reads, generation and explicit review checkmarks."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, StrictBool

from services.auth_guard import require_self
from services.topic_checklist_service import get_checklist, refresh_checklist, set_reviewed

router = APIRouter()


class ReviewBody(BaseModel):
    checked: StrictBool


@router.get("/{user_id}/courses/{course_id}")
def read(user_id: str, course_id: str, request: Request, semester: str | None = None):
    require_self(user_id, request)
    return get_checklist(user_id, course_id, semester)


@router.post("/{user_id}/courses/{course_id}/refresh")
def refresh(user_id: str, course_id: str, request: Request, semester: str | None = None):
    require_self(user_id, request)
    return refresh_checklist(user_id, course_id, semester)


@router.patch("/{user_id}/courses/{course_id}/topics/{topic_id}")
def review(user_id: str, course_id: str, topic_id: str, body: ReviewBody, request: Request, semester: str | None = None):
    require_self(user_id, request)
    return set_reviewed(user_id, course_id, topic_id, body.checked, semester)
