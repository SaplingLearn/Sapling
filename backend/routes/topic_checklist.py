"""Authenticated checklist reads, generation and explicit review checkmarks."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, StrictBool
from uuid import UUID

from services.auth_guard import require_self
from services.topic_checklist_service import get_checklist, refresh_checklist, set_reviewed
from services import study_plan_service as plans

router = APIRouter()


@router.get("/{user_id}/courses/{course_id}/plans/sources")
def plan_sources(user_id: str, course_id: str, request: Request, semester: str | None = None):
    require_self(user_id, request)
    return plans.list_sources(user_id, course_id, semester)


@router.get("/{user_id}/courses/{course_id}/plans")
def read_plans(user_id: str, course_id: str, request: Request, semester: str | None = None):
    require_self(user_id, request)
    return plans.list_plans(user_id, course_id, semester)


@router.post("/{user_id}/courses/{course_id}/plans", status_code=201)
def create_plan(user_id: str, course_id: str, body: plans.PlanCreate, request: Request, semester: str | None = None):
    require_self(user_id, request)
    return plans.create_plan(user_id, course_id, body, semester)


@router.patch("/{user_id}/courses/{course_id}/plans/{plan_id}")
def update_plan(user_id: str, course_id: str, plan_id: UUID, body: plans.PlanUpdate, request: Request, semester: str | None = None):
    require_self(user_id, request)
    return plans.update_plan(user_id, course_id, plan_id, body, semester)


@router.delete("/{user_id}/courses/{course_id}/plans/{plan_id}")
def delete_plan(user_id: str, course_id: str, plan_id: UUID, request: Request, semester: str | None = None):
    require_self(user_id, request)
    return plans.delete_plan(user_id, course_id, plan_id, semester)


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
