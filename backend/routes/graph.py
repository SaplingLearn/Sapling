from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from services.graph_service import (
    get_graph, get_recommendations,
    get_courses, add_course, delete_course, update_course_color,
)

router = APIRouter()


@router.get("/{user_id}")
def get_user_graph(user_id: str):
    return get_graph(user_id)


@router.get("/{user_id}/recommendations")
def get_user_recommendations(user_id: str):
    return {"recommendations": get_recommendations(user_id)}


# ── Course endpoints ──────────────────────────────────────────────────────────

class AddCourseBody(BaseModel):
    course_id: str
    color: Optional[str] = None
    nickname: Optional[str] = None


class UpdateCourseColorBody(BaseModel):
    color: str


@router.get("/{user_id}/courses")
def list_courses(user_id: str):
    return {"courses": get_courses(user_id)}


@router.post("/{user_id}/courses")
def create_course(user_id: str, body: AddCourseBody):
    result = add_course(user_id, body.course_id, body.color, body.nickname)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.patch("/{user_id}/courses/{course_id}/color")
def set_course_color(user_id: str, course_id: str, body: UpdateCourseColorBody):
    return update_course_color(user_id, course_id, body.color)


@router.delete("/{user_id}/courses/{course_id}")
def remove_course(user_id: str, course_id: str):
    return delete_course(user_id, course_id)
