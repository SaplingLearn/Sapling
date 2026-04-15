from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from services.graph_service import (
    get_graph, get_recommendations,
    get_courses, add_course, delete_course, update_course_color,
)

router = APIRouter()


@router.get("/{user_id}")
def get_user_graph(user_id: str):
    try:
        return get_graph(user_id)
    except Exception:
        return {"nodes": [], "edges": [], "stats": {
            "total_nodes": 0, "mastered": 0, "learning": 0,
            "struggling": 0, "unexplored": 0, "streak": 0, "avg_learning_velocity": 0.0,
        }}


@router.get("/{user_id}/recommendations")
def get_user_recommendations(user_id: str):
    try:
        return {"recommendations": get_recommendations(user_id)}
    except Exception:
        return {"recommendations": []}


# ── Course endpoints ──────────────────────────────────────────────────────────

class AddCourseBody(BaseModel):
    course_name: str
    color: Optional[str] = None


class UpdateCourseColorBody(BaseModel):
    color: str


@router.get("/{user_id}/courses")
def list_courses(user_id: str):
    return {"courses": get_courses(user_id)}


@router.post("/{user_id}/courses")
def create_course(user_id: str, body: AddCourseBody):
    return add_course(user_id, body.course_name, body.color)


@router.patch("/{user_id}/courses/{course_name}/color")
def set_course_color(user_id: str, course_name: str, body: UpdateCourseColorBody):
    return update_course_color(user_id, course_name, body.color)


@router.delete("/{user_id}/courses/{course_name}")
def remove_course(user_id: str, course_name: str):
    return delete_course(user_id, course_name)
