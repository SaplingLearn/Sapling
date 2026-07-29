import uuid

import httpx
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, ValidationError
from typing import Optional
from pydantic_ai.exceptions import AgentRunError

from services.auth_guard import require_self
from services.graph_service import (
    get_graph, get_recommendations,
    get_courses, add_course, delete_course, update_course_color,
    delete_node, update_node_color,
)
from services.request_context import current_request_id
from agents import WORKER_LIMITS
from agents._providers import UnregisteredHandlerError
from agents._run import run_agent_sync
from agents.deps import SaplingDeps
from agents.concept_describe import concept_describe_agent, build_message
from agents.usage import record_agent_usage

router = APIRouter()


@router.get("/{user_id}")
def get_user_graph(user_id: str, request: Request, semester: str | None = Query(None)):
    require_self(user_id, request)
    return get_graph(user_id, semester)


@router.get("/{user_id}/recommendations")
def get_user_recommendations(user_id: str, request: Request, semester: str | None = Query(None)):
    require_self(user_id, request)
    return {"recommendations": get_recommendations(user_id, semester)}


# ── Course endpoints ──────────────────────────────────────────────────────────

class AddCourseBody(BaseModel):
    course_id: str
    color: Optional[str] = None
    nickname: Optional[str] = None
    # Semester label to enroll into (the active tab in the Courses & Semesters
    # hub). Omitted → the backend falls back to the current term.
    term: Optional[str] = None


class UpdateCourseColorBody(BaseModel):
    color: str


class UpdateNodeColorBody(BaseModel):
    color: Optional[str] = None


class ConceptDescriptionBody(BaseModel):
    concept: str
    course_label: Optional[str] = None


@router.get("/{user_id}/courses")
def list_courses(user_id: str, request: Request):
    require_self(user_id, request)
    return {"courses": get_courses(user_id)}


@router.post("/{user_id}/courses")
def create_course(user_id: str, body: AddCourseBody, request: Request):
    require_self(user_id, request)
    result = add_course(user_id, body.course_id, body.color, body.nickname, body.term)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.patch("/{user_id}/courses/{course_id}/color")
def set_course_color(user_id: str, course_id: str, body: UpdateCourseColorBody, request: Request):
    require_self(user_id, request)
    return update_course_color(user_id, course_id, body.color)


@router.delete("/{user_id}/courses/{course_id}")
def remove_course(user_id: str, course_id: str, request: Request):
    require_self(user_id, request)
    return delete_course(user_id, course_id)


# ── Node endpoints ───────────────────────────────────────────────────────────

@router.delete("/{user_id}/nodes/{node_id}")
def remove_node(user_id: str, node_id: str, request: Request):
    require_self(user_id, request)
    result = delete_node(user_id, node_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.patch("/{user_id}/nodes/{node_id}/color")
def set_node_color(user_id: str, node_id: str, body: UpdateNodeColorBody, request: Request):
    require_self(user_id, request)
    result = update_node_color(user_id, node_id, body.color)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Concept description (LLM) ─────────────────────────────────────────────────

# Bound the free-text handed to the agent. Concept names/course labels are short
# in practice; caps keep a pathological payload from bloating the prompt.
_MAX_CONCEPT_LEN = 200
_MAX_COURSE_LABEL_LEN = 120


@router.post("/{user_id}/concept-description")
def describe_concept(user_id: str, body: ConceptDescriptionBody, request: Request):
    """Generate a one-sentence, student-facing description for a concept.

    Backs the knowledge-map rail's focus card for concepts without a stored
    description. Tool-less LLM call — the concept name and course label are
    handed straight to the agent.
    """
    require_self(user_id, request)
    concept = body.concept.strip()[:_MAX_CONCEPT_LEN]
    if not concept:
        raise HTTPException(status_code=400, detail="concept is required")
    course_label = (body.course_label or "").strip()[:_MAX_COURSE_LABEL_LEN] or None
    deps = SaplingDeps(
        user_id=user_id,
        course_id=None,
        supabase=None,
        request_id=current_request_id() or str(uuid.uuid4()),
    )
    try:
        result = record_agent_usage(
            run_agent_sync(
                concept_describe_agent.run(
                    build_message(concept, course_label),
                    deps=deps,
                    usage_limits=WORKER_LIMITS,
                )
            ),
            feature="graph", task="concept_describe", user_id=user_id,
        )
    except (AgentRunError, httpx.HTTPError, ValidationError, UnregisteredHandlerError) as e:
        # Model / transport / output-validation failures are upstream problems —
        # surface them as 502. UnregisteredHandlerError covers the
        # SAPLING_MODEL_MODE=function seam (agents/_providers.py::_dispatch)
        # raising when no handler is registered for 'concept_describe' (#446):
        # a misconfigured seam shouldn't 500 the route, it should degrade the
        # same way an upstream model failure does. Deliberately NOT the bare
        # `LookupError` builtin here (#446 PR review): that base class also
        # covers KeyError/IndexError, and a bare `LookupError` catch would
        # silently downgrade an unrelated KeyError/IndexError bug elsewhere in
        # the agent-run path to this 502 instead of the generic 500. Anything
        # else propagates to the generic handler.
        raise HTTPException(
            status_code=502, detail=f"concept-description agent failed: {e}"
        ) from e
    return {"description": result.output.description}
