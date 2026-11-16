"""
backend/routes/study_guide.py — the /api/study-guide HTTP surface.

Each handler checks the caller, calls one function of ``services/study_guides/``
and answers that package's domain errors with their own status and detail
(``docs/design/study-guide-redesign.md``, section 4). A test patches the
function on the package: ``routes.study_guide.study_guides.<name>``.
"""
from __future__ import annotations

import uuid
from contextlib import aclosing, contextmanager

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from sse_starlette.sse import EventSourceResponse
from starlette.background import BackgroundTask

from models.study_guide import AnswerBody, GenerateBody, GuidePatch, GuideRequest
from services import study_guides
from services.agent_events import SSE_CACHE_CONTROL, sapling_event_to_sse
from services.auth_guard import require_self
from services.request_context import current_request_id

router = APIRouter()


@contextmanager
def _guide_errors():
    """Answer a ``services.study_guides`` domain error with the status and
    detail it carries."""
    try:
        yield
    except study_guides.StudyGuideError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/{user_id}/guides")
async def list_guides(user_id: str, request: Request):
    # The guard can read the DB: off the event loop in an async handler (#756).
    await run_in_threadpool(require_self, user_id, request)
    with _guide_errors():
        return {"guides": await study_guides.alist_cards(user_id)}


@router.get("/{user_id}/options")
async def get_options(
    user_id: str,
    request: Request,
    course_id: str = Query(...),
    semester: str | None = Query(None),
):
    await run_in_threadpool(require_self, user_id, request)
    with _guide_errors():
        return await study_guides.aget_options(user_id, course_id, semester)


@router.post("/{user_id}/plan")
async def plan_guide(user_id: str, body: GuideRequest, request: Request):
    await run_in_threadpool(require_self, user_id, request)
    with _guide_errors():
        return await study_guides.aplan(user_id, body)


@router.post("/{user_id}/guides", status_code=201)
async def create_guide(user_id: str, body: GuideRequest, request: Request):
    await run_in_threadpool(require_self, user_id, request)
    with _guide_errors():
        return {"id": await study_guides.acreate_guide(user_id, body)}


@router.get("/{user_id}/guides/{guide_id}")
async def get_guide(user_id: str, guide_id: str, request: Request):
    await run_in_threadpool(require_self, user_id, request)
    with _guide_errors():
        return await study_guides.aget_detail(user_id, guide_id)


@router.patch("/{user_id}/guides/{guide_id}")
async def patch_guide(user_id: str, guide_id: str, body: GuidePatch, request: Request):
    await run_in_threadpool(require_self, user_id, request)
    with _guide_errors():
        return await study_guides.apatch_guide(user_id, guide_id, body)


@router.post("/{user_id}/guides/{guide_id}/generate")
async def generate_guide(user_id: str, guide_id: str, body: GenerateBody, request: Request):
    """Write the guide as a stream of events. Everything that can refuse the
    run (not found, busy, rate limited) is answered with its status before
    the stream opens; after that a failure is an ``error`` event."""
    await run_in_threadpool(require_self, user_id, request)
    with _guide_errors():
        generation = await study_guides.aprepare_generation(user_id, guide_id, body.mode)
    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )

    async def event_stream():
        # aclosing: a client that goes away closes the run at once, so its
        # claim is released then and not whenever the generator is collected.
        async with aclosing(study_guides.stream_generation(generation)) as events:
            async for event in events:
                yield sapling_event_to_sse(event)

    return EventSourceResponse(
        event_stream(),
        headers={"X-Request-ID": request_id, "Cache-Control": SSE_CACHE_CONTROL},
        # Runs however the response ends, also when the stream never started.
        background=BackgroundTask(study_guides.asettle_charge, generation),
    )


@router.post("/{user_id}/guides/{guide_id}/blocks/{block_id}/regenerate")
async def regenerate_block(user_id: str, guide_id: str, block_id: str, request: Request):
    await run_in_threadpool(require_self, user_id, request)
    with _guide_errors():
        return {"block": await study_guides.aregenerate_block(user_id, guide_id, block_id)}


@router.post("/{user_id}/guides/{guide_id}/blocks/{block_id}/answer")
async def answer_check(
    user_id: str,
    guide_id: str,
    block_id: str,
    body: AnswerBody,
    request: Request,
    background_tasks: BackgroundTasks,
):
    await run_in_threadpool(require_self, user_id, request)
    with _guide_errors():
        # The class-aggregate refresh a mastery write triggers runs after the
        # response.
        return await study_guides.aanswer_check(
            user_id, guide_id, block_id, body.option_id, defer=background_tasks.add_task,
        )
