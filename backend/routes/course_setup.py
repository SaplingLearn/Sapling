"""`/api/learn/setup`: the Tutor's course setup (Tutor redesign), behind the
`course_setup` flag. One thin handler
over services/course_setup.py: take the concepts the student unticked out of
the course. The dates the setup reviews go through the calendar's own routes
(/api/calendar), which the syllabus upload already wrote to."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from models import Id
from services import abuse_limits
from services.auth_guard import require_self
from services.course_setup import MAX_PER_REQUEST, course_setup_on, exclude_concepts
from services.request_limits import enforce_abuse_limit

router = APIRouter()


class ExcludeConceptsBody(BaseModel):
    user_id: Id
    course_id: Id
    node_ids: list[Id] = Field(min_length=1, max_length=MAX_PER_REQUEST)


@router.post("/exclude-concepts")
def remove_concepts(body: ExcludeConceptsBody, request: Request):
    """Remove the unticked concepts the student has not started; the answer
    names the ids removed and the ids kept (started ones)."""
    require_self(body.user_id, request)
    if not course_setup_on(body.user_id):
        raise HTTPException(status_code=404, detail="Not Found")
    enforce_abuse_limit(abuse_limits.GRAPH_EDIT, body.user_id)
    return exclude_concepts(body.user_id, body.course_id, body.node_ids)
