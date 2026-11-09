"""
backend/routes/documents.py

Document upload, AI processing, and library storage.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid

# Feature flag — when true, the streaming /upload route runs OCR off the
# request critical path via asyncio.to_thread, so the SSE stream opens
# immediately and the user sees a `progress:extracting_text` event while
# OCR runs in a thread instead of blocking the route.
#
# This is the lightweight version of ADR 0010's two-phase upload — it
# moves OCR off the synchronous request path WITHOUT requiring a queue
# or a separate worker tier. Crash recovery still depends on DBOS
# (services/durable.py) being enabled.
#
# Default off until validated under production load. Flip via env var:
#   OCR_ASYNC_ENABLED=true
OCR_ASYNC_ENABLED = os.getenv("OCR_ASYNC_ENABLED", "false").lower() == "true"

from fastapi import APIRouter, BackgroundTasks, Body, File, Form, HTTPException, Request, UploadFile
from sse_starlette.sse import EventSourceResponse
from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior

from db.connection import table
from services import events_service
from services.academics import offering_course_id, require_course_enrollment
from services.auth_guard import get_session_user_id, require_self, guard_off_loop
from services.encryption import decrypt_if_present, decrypt_json
from services.extraction_service import extract_text_from_file
from services.agent_events import SSE_CACHE_CONTROL
from services.request_context import current_request_id
from services.durable import workflow_id
from services.document_indexing import schedule_document_index
from services import document_jobs
from services.llm_budget import LLMBudgetExceeded
from services.documents.errors import ConceptScanFailed
# The upload's persistence, post-roll side effects, concept scan and SSE event
# stream live in services/documents/ (#118); every moved name stays importable
# (and patchable, via tests/doc_patches.py) here.
from services.documents.upload import (  # noqa: F401  (re-export, #118)
    MIN_EXTRACTED_CHARS,
    UNREADABLE_DOCUMENT_DETAIL,
    UPLOAD_FAILED_DETAIL,
    _budget_failed_frames,
    _has_usable_text,
)
from services.documents.persistence import (  # noqa: F401  (re-export, #118)
    _DROPPABLE_COLUMNS,
    _MISSING_COLUMN_MARKERS,
    _existing_doc_by_request_id,
    _graph_backstop,
    _grading_categories_from,
    _missing_column,
    _persist_document,
    _replay_result_payload,
    _save_orchestrator_syllabus,
    _stored_confidence,
)
from services.documents.post_roll import (  # noqa: F401  (re-export, #118)
    POST_ROLL_DRAIN_TIMEOUT_S,
    _POST_ROLL_TASKS,
    _check_upload_achievements,
    _invalidate_study_guide_cache,
    _log_post_roll_exc,
    _refresh_course_context,
    _spawn_post_roll,
    drain_post_roll,
)
from services.documents.scan import (  # noqa: F401  (re-export, #118)
    _course_label,
    _extend_concepts,
    _extend_via_agent,
    _scan_concepts_for_course,
    _scan_user_message,
)
from services.documents.library import (  # noqa: F401  (re-export, #118)
    _courses_for_offerings,
    list_user_documents,
    soft_delete_document,
    update_document_row,
)
from services.documents.stream import upload_event_stream

from agents.deps import SaplingDeps
from agents.document import process_document, DocumentProcessingResult

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx"}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

VALID_CATEGORIES = {
    "syllabus", "lecture_notes", "slides", "reading",
    "assignment", "study_guide", "other",
}


async def _validate_user(user_id: str) -> None:
    """Verify that the user_id corresponds to an existing user (#117: async)."""
    rows = await table("users").aselect("id", filters={"id": f"eq.{user_id}"}, limit=1)
    if not rows:
        raise HTTPException(status_code=403, detail="Invalid user.")


def _validate_user_sync(user_id: str) -> None:
    """`_validate_user` for the plain-`def` scan handlers (threadpool)."""
    rows = table("users").select("id", filters={"id": f"eq.{user_id}"}, limit=1)
    if not rows:
        raise HTTPException(status_code=403, detail="Invalid user.")


@router.get("/user/{user_id}")
async def list_documents(user_id: str, request: Request):
    await guard_off_loop(require_self, user_id, request)
    await _validate_user(user_id)
    return {"documents": await list_user_documents(user_id)}


async def _session_or_self(user_id: str | None, request: Request) -> str:
    """The acting user: `user_id` (the session's own, existing) or the session's."""
    if user_id:
        await guard_off_loop(require_self, user_id, request)
        await _validate_user(user_id)
        return user_id
    return await guard_off_loop(get_session_user_id, request)


async def _require_owned_document(document_id: str, user_id: str) -> None:
    """404 unless the document is this user's and not soft-deleted."""
    docs = await table("documents").aselect(
        "id",
        filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}", "deleted_at": "is.null"},
        limit=1,
    )
    if not docs:
        raise HTTPException(status_code=404, detail="Document not found.")


@router.delete("/doc/{document_id}")
async def delete_document(document_id: str, request: Request, user_id: str | None = None):
    user_id = await _session_or_self(user_id, request)
    await _require_owned_document(document_id, user_id)
    await soft_delete_document(document_id, user_id)
    return {"deleted": True}


@router.patch("/doc/{document_id}")
async def update_document(document_id: str, request: Request, body: dict = Body(...)):
    """Update mutable fields on a document (currently only category)."""
    category = body.get("category")
    if category and category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category '{category}'.")
    updates = {}
    if category:
        updates["category"] = category
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update.")
    user_id = await _session_or_self(body.get("user_id"), request)
    await _require_owned_document(document_id, user_id)
    return await update_document_row(document_id, user_id, updates)


def _extract_text_or_422(file_bytes: bytes, filename: str, content_type: str) -> str:
    """Run synchronous text extraction. Convert any failure into a clean
    HTTP 422 with a friendly detail instead of a bubbled-up 500.

    The async-OCR path (OCR_ASYNC_ENABLED=true) handles its own failures
    via SSE error events; this helper is for the synchronous default
    path on /upload/sync and on /upload when the flag is off.
    """
    try:
        text = extract_text_from_file(file_bytes, filename, content_type)
    except LLMBudgetExceeded:
        raise  # #119: vision OCR refused by the per-user LLM budget -> the 429
    except Exception:
        logger.exception("Text extraction failed for '%s'", filename)
        raise HTTPException(
            status_code=422,
            detail="Could not read this document. Please try a different file.",
        )
    # Extraction can "succeed" and return nothing -- a rasterized PDF has no
    # text layer, so there is no exception to catch. Reject here rather than
    # letting an empty document reach the model (see MIN_EXTRACTED_CHARS).
    if not _has_usable_text(text):
        logger.warning(
            "Extraction yielded %d usable chars for '%s' - rejecting as unreadable",
            len((text or "").strip()), filename,
        )
        raise HTTPException(status_code=422, detail=UNREADABLE_DOCUMENT_DETAIL)
    return text


def _upload_request_id(request: Request) -> str:
    """The middleware-stamped request id, so agent traces, Logfire spans and
    client-facing error payloads share one correlation key."""
    return (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())  # ultimate fallback if middleware somehow didn't run
    )


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    """(filename, bytes) of an accepted upload: 400 on a type or size the
    routes refuse."""
    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext or file.content_type}'. Only PDF, DOCX, and PPTX are accepted.",
        )
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File exceeds the {MAX_FILE_SIZE // (1024 * 1024)} MB limit. "
                "Please upload a smaller file."
            ),
        )
    return filename, file_bytes


@router.post("/upload/sync")
@document_jobs.records_inline_outcome  # #116: a queued upload taken back records its outcome
async def upload_document_sync(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    course_id: str = Form(...),
    user_id: str = Form(...),
):
    """Non-streaming JSON upload. Original behavior preserved here so any
    frontend that hasn't migrated to the SSE /upload route keeps working."""
    await guard_off_loop(require_self, user_id, request)
    await _validate_user(user_id)

    request_id = _upload_request_id(request)

    # Idempotency: if the client retries with the same X-Request-ID,
    # short-circuit to the previously persisted document instead of
    # re-running the orchestrator. BEFORE the enrollment gate (#115 review):
    # a retry of an upload that already completed returns the stored row
    # even if the course was dropped since. Threaded: a sync PostgREST trip.
    existing = await asyncio.to_thread(_existing_doc_by_request_id, user_id, request_id)
    if existing:
        response = dict(existing)
        response.setdefault("categories", [])
        return response

    # #115: only into a course the uploader is enrolled in (else 404). The
    # upload form sends the ABSTRACT course id; documents key on the
    # OFFERING — the uploader's own enrolled one, which the gate returns (so
    # the check and the write agree on the term). The abstract course_id
    # stays the key for the graph + course-context + calendar side effects.
    offering_id = await asyncio.to_thread(require_course_enrollment, user_id, course_id)

    filename, file_bytes = await _read_upload(file)

    # #116: with `jobs_queue` on for the uploader, extraction runs on the
    # worker (document_jobs); off, it runs here exactly as before.
    queued = await asyncio.to_thread(document_jobs.should_queue, user_id, len(file_bytes))
    extracted_text = None if queued else await asyncio.to_thread(  # #117: OCR off the loop
        _extract_text_or_422, file_bytes, filename, file.content_type or "",
    )

    # ── AI: orchestrator (parallel workers + tool-driven graph update) ────────
    # #117: one document.upload per accepted upload attempt — AFTER the
    # idempotency short-circuit (PR #465 review), so an X-Request-ID retry of
    # an already-persisted upload doesn't inflate the count. Counts only —
    # the extracted text itself never enters a payload.
    events_service.log_event(
        "document.upload",
        category="usage",
        user_id=user_id,
        request_id=request_id,
        payload={
            "course_id": course_id,
            "offering_id": offering_id,
            "char_count": len(extracted_text) if extracted_text is not None else None,
        },
    )

    if queued:
        # Same JSON / HTTP errors as below, computed by the worker. None: the
        # queue could not take it (enqueue failed, no worker picked it up),
        # so it runs here after all.
        response = await document_jobs.sync_via_queue(
            user_id=user_id, offering_id=offering_id, course_id=course_id,
            request_id=request_id, filename=filename,
            content_type=file.content_type, file_bytes=file_bytes,
        )
        if response is not None:
            return response
        extracted_text = await asyncio.to_thread(
            _extract_text_or_422, file_bytes, filename, file.content_type or "",
        )

    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id,
        supabase=None,
        request_id=request_id,
    )
    # Failure mapping (#151b): the agent pipeline is the ONLY pipeline — the
    # ADR-0001 legacy fallback is gone (ADR 0024). Nothing has been persisted
    # at this point and the client mints a fresh X-Request-ID per attempt, so
    # both branches surface a retry-friendly 502: guardrail trips (budget /
    # degenerate output) log at WARNING, anything else is a bug and logs the
    # full exception.
    # Scope the DBOS workflow id to user_id + request_id, not request_id
    # alone: X-Request-ID is client-supplied, so an unscoped id would let
    # one user's replay attach to another user's in-flight/completed
    # workflow (state poisoning). No-op (nullcontext) when DBOS is off.
    try:
        with workflow_id(f"doc:{user_id}:{request_id}"):
            result: DocumentProcessingResult = await process_document(extracted_text, deps)
    except LLMBudgetExceeded:
        raise  # #119: the 429 itself, not "upload failed" (services/llm_budget.py)
    except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
        logger.warning(
            "Agent guardrails tripped for '%s'; returning 502",
            filename, exc_info=e,
        )
        raise HTTPException(status_code=502, detail=UPLOAD_FAILED_DETAIL) from e
    except Exception as e:
        logger.exception(
            "Unexpected agent failure for '%s'; returning 502",
            filename,
        )
        raise HTTPException(status_code=502, detail=UPLOAD_FAILED_DETAIL) from e

    # async def route: these are synchronous PostgREST round-trips — keep them
    # off the event loop, same as the SSE generator's post-roll (#132 item 22).
    await asyncio.to_thread(
        _save_orchestrator_syllabus, user_id=user_id, course_id=course_id,
        filename=filename, result=result,
    )
    await asyncio.to_thread(
        _graph_backstop, user_id=user_id, course_id=course_id,
        filename=filename, result=result,
    )
    try:
        doc_id, full_row = await asyncio.to_thread(
            _persist_document, user_id=user_id, offering_id=offering_id,
            filename=filename, result=result, request_id=request_id,
            course_id=course_id, char_count=len(extracted_text),
            extracted_text=extracted_text,
        )
    except Exception:
        # #759/#116: a duplicate of this request saved it first (the unique
        # (user_id, request_id) index refused this insert): answer with that
        # row, as the replay at the top would have, instead of a 500.
        winner = await asyncio.to_thread(_existing_doc_by_request_id, user_id, request_id)
        if not winner or not winner.get("id"):
            raise
        response = dict(winner)
        response.setdefault("categories", [])
        return response

    background_tasks.add_task(_invalidate_study_guide_cache, user_id, offering_id)
    # update_course_context aggregates an OFFERING's enrollments (#759: the
    # abstract course id matched none, so it only cleared the cache).
    background_tasks.add_task(_refresh_course_context, offering_id, user_id)
    background_tasks.add_task(_check_upload_achievements, user_id)
    # #482: this route never indexed. Gradebook syllabus uploads come through
    # it, so none of them reached RAG. Same entry point as the streaming route.
    background_tasks.add_task(schedule_document_index, doc_id, user_id)

    response = dict(full_row)
    response["categories"] = _grading_categories_from(result)
    return response


@router.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    course_id: str = Form(...),
    user_id: str = Form(...),
):
    """Streaming SSE upload. Emits status/progress/result/error events
    while the orchestrator pipeline runs, then a final 'done' status with
    the persisted document_id once side-effects complete.

    Validation/extraction errors fail with normal HTTP 4xx before the
    stream opens. Errors during the stream surface as type='error' SSE
    events; the client should NOT auto-retry against this route.
    """
    await guard_off_loop(require_self, user_id, request)
    await _validate_user(user_id)

    request_id = _upload_request_id(request)
    # Idempotency: a client retry with the same X-Request-ID should not
    # re-run the orchestrator; the stream replays the persisted row instead.
    # Looked up BEFORE the enrollment gate (#115 review), so a retry of an
    # upload that already completed still gets its document. Threaded: a
    # sync PostgREST round trip on the loop stalls every other open stream.
    existing = await asyncio.to_thread(_existing_doc_by_request_id, user_id, request_id)
    # #115: only into a course the uploader is enrolled in (else 404).
    # Documents key on the offering (0025) — the uploader's own enrolled one,
    # which the gate returns so the check and the write agree on the term;
    # the graph + course-context key on the abstract course id (kept in
    # SaplingDeps for the agent's graph tools).
    offering_id = (
        None if existing
        else await asyncio.to_thread(require_course_enrollment, user_id, course_id)
    )

    filename, file_bytes = await _read_upload(file)

    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id,
        supabase=None,
        request_id=request_id,
    )

    # OCR strategy: with OCR_ASYNC_ENABLED, run extraction inside the SSE
    # context so the stream opens immediately and the user sees a
    # progress:extracting_text event while OCR runs in a thread. Default
    # behavior is unchanged (synchronous extraction before stream opens)
    # so existing tests and clients keep working.
    # #116: `jobs_queue` on for the uploader moves extraction and the agents
    # to the worker; the stream below watches the job instead. If the queue
    # cannot take it, the in-stream extraction (Phase 0) runs it here.
    # A replayed upload (same X-Request-ID, already saved) never queues.
    queued = False if existing else await asyncio.to_thread(
        document_jobs.should_queue, user_id, len(file_bytes))
    extracted_text: str | None = (
        None if OCR_ASYNC_ENABLED or existing or queued
        else await asyncio.to_thread(  # #117: OCR off the event loop
            _extract_text_or_422, file_bytes, filename, file.content_type or "",
        )
    )

    return EventSourceResponse(
        # #116: a queued upload this request took back records its outcome.
        document_jobs.record_inline_outcome(upload_event_stream(
            existing=existing, user_id=user_id, course_id=course_id,
            offering_id=offering_id, request_id=request_id, filename=filename,
            content_type=file.content_type, file_bytes=file_bytes, deps=deps,
            queued=queued, extracted_text=extracted_text,
        )),
        headers={"Cache-Control": SSE_CACHE_CONTROL},
    )


@router.post("/doc/{document_id}/scan-concepts")
def scan_document_concepts(document_id: str, request: Request, body: dict = Body(...)):
    """Extend the course's concept graph using one document's stored
    summary + takeaways as the seed signal."""
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required.")
    require_self(user_id, request)
    _validate_user_sync(user_id)

    rows = table("documents").select(
        "id,user_id,offering_id,file_name,summary,concept_notes",
        filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}", "deleted_at": "is.null"},
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc = rows[0]
    # The document keys on the offering; the concept graph keys on the
    # abstract course. Resolve offering → abstract course before scanning.
    course_id = offering_course_id(doc.get("offering_id"))
    if not course_id:
        raise HTTPException(status_code=400, detail="Document is not associated with a course.")
    # #115: the scan writes the course's graph and spends model quota, so —
    # like /course/{id}/scan-concepts — the caller must still be enrolled in
    # the course (a dropped course's document is readable, not scannable).
    require_course_enrollment(user_id, course_id)

    doc_summary = decrypt_if_present(doc.get("summary"))
    notes_raw = doc.get("concept_notes")
    if isinstance(notes_raw, str):
        try:
            doc_concept_notes = decrypt_json(notes_raw)
        except Exception:
            doc_concept_notes = []
    else:
        doc_concept_notes = notes_raw or []

    try:
        return _scan_concepts_for_course(
            user_id,
            course_id,
            doc_filename=doc.get("file_name"),
            doc_summary=doc_summary,
            doc_concept_notes=doc_concept_notes
        )
    except ConceptScanFailed as e:
        raise HTTPException(status_code=500, detail=e.detail)


@router.post("/course/{course_id}/scan-concepts")
def scan_course_concepts(course_id: str, request: Request, body: dict = Body(...)):
    """Extend the course's concept graph from the course label alone
    (and whatever is already in the graph)."""
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required.")
    require_self(user_id, request)
    _validate_user_sync(user_id)
    require_course_enrollment(user_id, course_id)  # #115
    try:
        return _scan_concepts_for_course(user_id, course_id)
    except ConceptScanFailed as e:
        raise HTTPException(status_code=500, detail=e.detail)
