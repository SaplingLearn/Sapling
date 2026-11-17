import hashlib
import logging
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field, ValidationError
from typing import Optional
from pydantic_ai.exceptions import AgentRunError

from services import abuse_limits, cache, llm_budget
from services.academics import require_course_enrollment
from services.auth_guard import guard_off_loop, require_self
from services.flashcards.concept_topic import topic_is_graph_concept
from services.request_limits import enforce_abuse_limit
from services.graph_service import (
    aget_graph, aget_recommendations, aget_courses,
    add_course, delete_course, update_course_color,
    add_node, delete_node, update_node_color,
)
from services.request_context import current_request_id
from agents import WORKER_LIMITS
from agents._providers import UnregisteredHandlerError, model_mode, model_name_for
from agents._run import run_agent_sync
from agents.deps import SaplingDeps
from agents.concept_describe import PROMPT_VERSION, concept_describe_agent, build_message
from agents.usage import record_agent_usage
from models import Id, ShortText

logger = logging.getLogger(__name__)

#: The 502 a failed concept description answers with. Never the exception
#: text (model/transport errors can name hosts, keys or prompts); that is
#: logged under the request id instead.
DESCRIBE_FAILED_DETAIL = "Couldn't describe this concept right now. Try again in a moment."

router = APIRouter()

# #117 (docs/design/async-db-client.md §4.1 wave 1): the read handlers are
# `async def` over the graph_service `a*` twins; the write and LLM handlers
# stay plain `def` (FastAPI runs them in the threadpool) until their service
# functions have async forms.


@router.get("/{user_id}")
async def get_user_graph(user_id: str, request: Request, semester: str | None = Query(None)):
    await guard_off_loop(require_self, user_id, request)
    return await aget_graph(user_id, semester)


@router.get("/{user_id}/recommendations")
async def get_user_recommendations(
    user_id: str, request: Request, semester: str | None = Query(None),
):
    await guard_off_loop(require_self, user_id, request)
    return {"recommendations": await aget_recommendations(user_id, semester)}


# ── Course endpoints ──────────────────────────────────────────────────────────

class AddCourseBody(BaseModel):
    course_id: Id
    color: Optional[str] = Field(default=None, max_length=64)
    nickname: Optional[ShortText] = None
    # Semester label to enroll into (the active tab in the Courses & Semesters
    # hub). Omitted → the backend falls back to the current term.
    term: Optional[ShortText] = None


class UpdateCourseColorBody(BaseModel):
    color: str = Field(max_length=64)


class UpdateNodeColorBody(BaseModel):
    color: Optional[str] = Field(default=None, max_length=64)


class ConceptDescriptionBody(BaseModel):
    # The route truncates to _MAX_CONCEPT_LEN / _MAX_COURSE_LABEL_LEN; these
    # bounds only cap what is parsed at all.
    concept: str = Field(max_length=2000)
    course_label: Optional[str] = Field(default=None, max_length=2000)


@router.get("/{user_id}/courses")
async def list_courses(user_id: str, request: Request):
    await guard_off_loop(require_self, user_id, request)
    return {"courses": await aget_courses(user_id)}


@router.post("/{user_id}/courses")
def create_course(user_id: str, body: AddCourseBody, request: Request):
    require_self(user_id, request)
    enforce_abuse_limit(abuse_limits.GRAPH_EDIT, user_id)  # may re-summarise inline
    result = add_course(user_id, body.course_id, body.color, body.nickname, body.term)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.patch("/{user_id}/courses/{course_id}/color")
def set_course_color(user_id: str, course_id: str, body: UpdateCourseColorBody, request: Request):
    require_self(user_id, request)
    return update_course_color(user_id, course_id, body.color)


@router.delete("/{user_id}/courses/{course_id}")
def remove_course(
    user_id: str, course_id: str, request: Request, term: Optional[str] = None,
):
    """Drop the course for ONE term (``?term=<label>``; default: the current
    term). Other terms' enrollments — and their gradebooks — survive (#766)."""
    require_self(user_id, request)
    enforce_abuse_limit(abuse_limits.GRAPH_EDIT, user_id)
    result = delete_course(user_id, course_id, term)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Node endpoints ───────────────────────────────────────────────────────────

class AddNodeBody(BaseModel):
    """Body for manually adding a single concept node (#330).

    ``course_id`` is required as a PRODUCT rule, not a storage one: a manual
    concept always belongs to a course, and the graph is course-scoped
    everywhere else. (The 0023 constraint is UNIQUE NULLS NOT DISTINCT, so a
    courseless node would in fact collide with any other courseless node of
    the same name rather than duplicate — a confusing merge either way.)
    ``anchor_node_id`` optionally links the new node to an existing one (the
    client defaults it to the focused concept/root).
    """
    concept_name: ShortText
    course_id: Id
    anchor_node_id: Optional[Id] = None


@router.post("/{user_id}/nodes")
def create_node(user_id: str, body: AddNodeBody, request: Request):
    require_self(user_id, request)
    enforce_abuse_limit(abuse_limits.GRAPH_EDIT, user_id)
    if not body.concept_name.strip():
        raise HTTPException(status_code=422, detail="concept_name must be non-empty")
    if not body.course_id.strip():
        raise HTTPException(status_code=422, detail="course_id is required")
    # #115's rule, which this route was missing: a course-keyed write needs
    # the student to be IN the course. Every other one already gates here
    # (documents, notes, learn/start-session, scan-concepts) — a graph node is
    # the same shape of write and was the one that slipped through.
    #
    # It also fixes a 500. `graph_nodes.course_id` is a FOREIGN KEY to
    # courses(id), and the route only checked that the string was non-empty,
    # so a course id naming nothing reached the upsert, violated the
    # constraint, and surfaced as an unhandled 500 instead of "no such
    # course". Verified against the running app before this was added.
    require_course_enrollment(user_id, body.course_id)
    return add_node(
        user_id, body.concept_name, body.course_id, anchor_node_id=body.anchor_node_id,
    )


@router.delete("/{user_id}/nodes/{node_id}")
def remove_node(user_id: str, node_id: str, request: Request):
    require_self(user_id, request)
    enforce_abuse_limit(abuse_limits.GRAPH_EDIT, user_id)
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
# A description depends only on the concept and its course label, not on who
# asks, so one cached sentence serves every student (#97's Redis cache; a
# no-op without REDIS_URL). Keyed on the model mode, the model and the prompt
# version too, so function-mode stand-ins never land under a real model's key
# and a model swap or a prompt edit re-writes instead of serving stale text.
_DESCRIPTION_CACHE_TTL = 30 * 24 * 3600


def _description_cache_key(concept: str, course_label: str | None) -> str:
    subject = f"{concept.casefold()}|{(course_label or '').casefold()}"
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()
    return (
        f"concept_desc:v2:{model_mode()}:{model_name_for('concept_describe')}"
        f":{PROMPT_VERSION}:{digest}"
    )


@router.post("/{user_id}/concept-description")
def describe_concept(user_id: str, body: ConceptDescriptionBody, request: Request):
    """Generate a one-sentence, student-facing description for a concept.

    Backs the knowledge-map rail's focus card for concepts without a stored
    description. Tool-less LLM call — the concept name and course label are
    handed straight to the agent.
    """
    require_self(user_id, request)
    enforce_abuse_limit(abuse_limits.CONCEPT_DESCRIBE, user_id)
    concept = body.concept.strip()[:_MAX_CONCEPT_LEN]
    if not concept:
        raise HTTPException(status_code=400, detail="concept is required")
    course_label = (body.course_label or "").strip()[:_MAX_COURSE_LABEL_LEN] or None
    cache_key = _description_cache_key(concept, course_label) if cache.enabled() else None
    if cache_key and (hit := cache.get_str(cache_key)):
        return {"description": hit}
    # Every caller describes one of the student's OWN concepts (the map's
    # focus card, the quiz home's rows); anything else would make this a
    # free general-purpose model call.
    if not topic_is_graph_concept(user_id, concept, None):
        raise HTTPException(status_code=404, detail="That concept isn't on your map.")
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
        #
        # A budget refusal (#119) is its own 429 (LLMBudgetExceeded is an
        # HTTPException, so it is not caught here); one wrapped inside a caught
        # error is re-raised so it is never mislabelled as an agent failure.
        llm_budget.reraise_budget_refusal(e)
        logger.warning("concept-description agent failed [request_id=%s]: %s",
                       current_request_id(), e, exc_info=True)
        raise HTTPException(status_code=502, detail=DESCRIBE_FAILED_DETAIL) from e
    description = result.output.description
    if cache_key and description.strip():
        cache.set_str(cache_key, description, ttl_seconds=_DESCRIPTION_CACHE_TTL)
    return {"description": description}
