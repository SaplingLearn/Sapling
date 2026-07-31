"""
backend/routes/documents.py

Document upload, AI processing, and library storage.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

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
from services.academics import offering_course_id, resolve_offering
from services.auth_guard import get_session_user_id, require_self
from services.encryption import encrypt_if_present, encrypt_json, decrypt_if_present, decrypt_json
from services.document_dedup import (
    chunks_already_exist,
    file_sha256,
    find_duplicate,
)
from services.extraction_service import extract_text_from_file
from services.calendar_service import save_assignments_to_db
from services.graph_service import apply_graph_update
from services.course_context_service import update_course_context
from services.achievement_service import check_achievements
from services.agent_events import SSE_CACHE_CONTROL, SaplingEvent, sapling_event_to_sse
from services.request_context import current_request_id
from services.durable import workflow_id
from agents import WORKER_LIMITS
from agents._providers import model_mode
from agents.classifier import classifier_agent
from agents.summary import summary_agent
from agents.concept_extraction import concept_extraction_agent
from agents.syllabus_extraction import syllabus_extraction_agent
from agents.deps import SaplingDeps
from agents.document import process_document, DocumentProcessingResult
from agents.tools.graph import apply_concepts_to_graph
from agents._run import run_agent_sync
from agents.concept_scan import concept_scan_agent
from agents.usage import record_agent_usage

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

# Minimum usable extracted text, in stripped characters. Below this a document
# carries nothing to classify or summarize, and sending it to the model
# produces a *fabrication* rather than an error: the classify prompt's JSON
# schema requires a summary and a concept list with no "insufficient content"
# escape hatch, so an empty `Content:` block makes the model invent a plausible
# document. Those invented concepts then flow into the course's shared
# knowledge graph, where they mislead every enrolled student.
#
# Matches the 50-char floor that
# `extraction_service._extract_text_from_file_uncached` already applies when
# deciding whether native PDF text is worth keeping.
MIN_EXTRACTED_CHARS = 50

# Shown for both the sync 422 and the SSE error event. Names the likely cause
# (a scanned/image-only file) and the concrete fix.
UNREADABLE_DOCUMENT_DETAIL = (
    "No text could be read from this document. It looks like a scanned or "
    "image-only file, so there is nothing to analyze. Try uploading a version "
    "with selectable text."
)

# 502 detail for agent-pipeline failures on /upload/sync (#151b — the ADR-0001
# legacy fallback is gone, see ADR 0024). Retry-friendly on purpose: nothing
# was persisted, and the client mints a fresh X-Request-ID per attempt, so a
# retry re-runs the pipeline instead of replaying the failure.
UPLOAD_FAILED_DETAIL = (
    "Document processing failed and nothing was saved. Please try uploading "
    "the file again."
)


def _has_usable_text(text: str | None) -> bool:
    """True when extraction produced enough text to be worth analyzing."""
    return len((text or "").strip()) >= MIN_EXTRACTED_CHARS


def _validate_user(user_id: str) -> None:
    """Verify that the user_id corresponds to an existing user."""
    rows = table("users").select("id", filters={"id": f"eq.{user_id}"}, limit=1)
    if not rows:
        raise HTTPException(status_code=403, detail="Invalid user.")


def _scan_user_message(
    *,
    course_label: str,
    existing_concepts: list[str],
    doc_filename: str | None = None,
    doc_summary: str | None = None,
    doc_concept_notes: list[dict] | None = None,
) -> str:
    """Build the concept_scan agent's user message: course label + existing
    concepts + (optional) document context."""
    existing_block = (
        "\n".join(f"- {c}" for c in existing_concepts) if existing_concepts else "(none yet)"
    )
    lines = [
        f'Course: "{course_label}"',
        "Concepts already in the graph:",
        existing_block,
    ]
    if doc_filename or doc_summary or doc_concept_notes:
        notes_block = (
            "\n".join(
                f"  - {n.get('name', '?')}: {n.get('description', '')[:200]}"
                for n in (doc_concept_notes or [])
            )
            or "  (none)"
        )
        lines += [
            "",
            "New document being scanned:",
            f"  Title: {doc_filename or '(untitled)'}",
            f"  Summary: {doc_summary or '(none)'}",
            "  Concepts already extracted from this document:",
            notes_block,
        ]
    return "\n".join(lines)


async def _extend_via_agent(
    *,
    user_id: str,
    course_id: str,
    course_label: str,
    existing_concepts: list[str],
    doc_filename: str | None = None,
    doc_summary: str | None = None,
    doc_concept_notes: list[dict] | None = None,
) -> list[str]:
    """Run concept_scan_agent and return new concept names. Raises on agent
    failure; the sync dispatcher (_extend_concepts) degrades to []."""
    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id,
        supabase=None,
        request_id=current_request_id() or str(uuid.uuid4()),
    )
    message = _scan_user_message(
        course_label=course_label,
        existing_concepts=existing_concepts,
        doc_filename=doc_filename,
        doc_summary=doc_summary,
        doc_concept_notes=doc_concept_notes,
    )
    result = record_agent_usage(
        await concept_scan_agent.run(
            message, deps=deps, usage_limits=WORKER_LIMITS,
        ),
        feature="document", task="concept_scan",
    )
    return list(result.output.concepts)


def _extend_concepts(
    user_id: str,
    course_id: str,
    *,
    course_label: str,
    existing_concepts: list[str],
    doc_filename: str | None = None,
    doc_summary: str | None = None,
    doc_concept_notes: list[dict] | None = None,
) -> list[str]:
    """Concept extension via concept_scan_agent — the only scan path since
    #151b (ADR 0024 retired the legacy call_gemini_json fallback).

    Sync entry point for the sync /scan-concepts handlers: drives the async
    agent via run_agent_sync. Best-effort enrichment (D4): any agent failure
    degrades to "no new concepts" with a warning log, so the scan response
    reports {"concepts": [], "added": 0, "existing": N} instead of 500ing a
    route whose whole job is optional graph enrichment.
    """
    try:
        return run_agent_sync(
            _extend_via_agent(
                user_id=user_id,
                course_id=course_id,
                course_label=course_label,
                existing_concepts=existing_concepts,
                doc_filename=doc_filename,
                doc_summary=doc_summary,
                doc_concept_notes=doc_concept_notes,
            )
        )
    except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
        logger.warning(
            "concept_scan agent guardrails tripped; degrading to no new concepts",
            exc_info=e,
        )
    except Exception:
        logger.warning(
            "concept_scan agent failed; degrading to no new concepts",
            exc_info=True,
        )
    return []


@router.get("/user/{user_id}")
def list_documents(user_id: str, request: Request):
    require_self(user_id, request)
    _validate_user(user_id)
    docs = table("documents").select(
        "id,user_id,offering_id,file_name,category,summary,concept_notes,created_at,processed_at",
        filters={"user_id": f"eq.{user_id}", "deleted_at": "is.null"},
        order="created_at.desc",
    ) or []
    # The row keys on the OFFERING (0025); the HTTP boundary keeps the
    # abstract course_id (#435 — Library.tsx filters/labels on d.course_id).
    # Resolve each unique offering_id once (mirrors routes/learn.py's
    # list_sessions offering_to_course pattern), not once per row.
    offering_to_course: dict[str, str | None] = {}
    for d in docs:
        d["summary"] = decrypt_if_present(d.get("summary"))
        notes_raw = d.get("concept_notes")
        if isinstance(notes_raw, str):
            try:
                d["concept_notes"] = decrypt_json(notes_raw)
            except Exception:
                # decrypt_json re-raises when both decrypt AND plaintext
                # parse fail (a genuinely corrupted row) — degrade that one
                # row instead of 500ing the whole list (matches
                # _existing_doc_by_request_id and scan_document_concepts).
                logger.warning(
                    "concept_notes decrypt failed for document %s; degrading to []",
                    d.get("id"),
                )
                d["concept_notes"] = []
        off_id = d.get("offering_id")
        if off_id and off_id not in offering_to_course:
            offering_to_course[off_id] = offering_course_id(off_id)
        d["course_id"] = offering_to_course.get(off_id)
    return {"documents": docs}


@router.delete("/doc/{document_id}")
def delete_document(document_id: str, request: Request, user_id: str | None = None):
    if user_id:
        require_self(user_id, request)
        _validate_user(user_id)
    else:
        user_id = get_session_user_id(request)
    # Ensure the document belongs to the requesting user (and isn't already
    # soft-deleted)
    docs = table("documents").select(
        "id",
        filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}", "deleted_at": "is.null"},
        limit=1,
    )
    if not docs:
        raise HTTPException(status_code=404, detail="Document not found.")
    # Soft delete (0025): stamp deleted_at; reads filter it out. The
    # enrollments.syllabus_doc_id FK (ON DELETE SET NULL) stays intact.
    table("documents").update(
        {"deleted_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"},
    )
    return {"deleted": True}


@router.patch("/doc/{document_id}")
def update_document(document_id: str, request: Request, body: dict = Body(...)):
    """Update mutable fields on a document (currently only category)."""
    category = body.get("category")
    if category and category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category '{category}'.")
    updates = {}
    if category:
        updates["category"] = category
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update.")
    user_id = body.get("user_id")
    if user_id:
        require_self(user_id, request)
        _validate_user(user_id)
    else:
        user_id = get_session_user_id(request)
    docs = table("documents").select(
        "id",
        filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}", "deleted_at": "is.null"},
        limit=1,
    )
    if not docs:
        raise HTTPException(status_code=404, detail="Document not found.")
    updated = table("documents").update(updates, filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"})
    return updated[0] if updated else {"id": document_id, **updates}


def _extract_text_or_422(file_bytes: bytes, filename: str, content_type: str) -> str:
    """Run synchronous text extraction. Convert any failure into a clean
    HTTP 422 with a friendly detail instead of a bubbled-up 500.

    The async-OCR path (OCR_ASYNC_ENABLED=true) handles its own failures
    via SSE error events; this helper is for the synchronous default
    path on /upload/sync and on /upload when the flag is off.
    """
    try:
        text = extract_text_from_file(file_bytes, filename, content_type)
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


def _existing_doc_by_request_id(user_id: str, request_id: str) -> dict | None:
    """Return an existing documents row for this user + request_id, if any.

    The request_id column may not exist in older schemas — catch that and
    return None so deployments can ship the code before the migration runs.
    Defensive against non-list return shapes (mocked DBs, partial errors)
    so a misbehaving Supabase response can't masquerade as a cache hit.
    """
    try:
        rows = table("documents").select(
            "id,user_id,offering_id,file_name,category,summary,concept_notes,created_at,processed_at",
            filters={
                "user_id": f"eq.{user_id}",
                "request_id": f"eq.{request_id}",
                "deleted_at": "is.null",
            },
            limit=1,
        )
    except Exception:
        return None
    if not isinstance(rows, list) or not rows:
        return None
    first = rows[0]
    if not isinstance(first, dict):
        return None
    row = dict(first)
    row["summary"] = decrypt_if_present(row.get("summary"))
    notes_raw = row.get("concept_notes")
    if isinstance(notes_raw, str):
        try:
            row["concept_notes"] = decrypt_json(notes_raw)
        except Exception:
            row["concept_notes"] = []
    return row


def _persist_document(
    *,
    user_id: str,
    offering_id: str,
    filename: str,
    result: DocumentProcessingResult,
    request_id: str | None = None,
    course_id: str | None = None,
    char_count: int | None = None,
    file_hash: str | None = None,
) -> tuple[str, dict]:
    """Insert a documents row from an orchestrator result.

    Shared by both upload_document_sync and the streaming upload_document.
    The document keys on the OFFERING (0025), not the abstract course.
    summary + concept_notes are encrypted at the insert boundary; the
    returned row carries the plaintext shape so callers can pass it
    straight back to the client without an extra decrypt step.
    ``request_id`` (when provided) is stored verbatim for idempotent
    replay detection. ``file_hash`` is the SHA-256 of the uploaded bytes; it
    is what lets the NEXT upload of this file skip OCR and re-indexing, so a
    row written without it is invisible to file-level dedup.
    ``course_id``/``char_count`` only feed the
    document.processed observability event (#117); they are not persisted
    on the row. Returns (document_id, full_row).
    """
    now = datetime.now(timezone.utc).isoformat()
    concept_notes = [
        {"name": c.name, "description": c.description}
        for c in result.concepts.concepts
    ]
    summary = result.summary.abstract or None
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "offering_id": offering_id,
        "file_name": filename,
        "category": result.classification.category,
        "summary": encrypt_if_present(summary),
        "concept_notes": encrypt_json(concept_notes) if concept_notes is not None else None,
        "created_at": now,
        "processed_at": now,
    }
    if request_id:
        row["request_id"] = request_id
    if file_hash:
        row["file_sha256"] = file_hash
    try:
        inserted = table("documents").insert(row)
    except Exception:
        # Schema may not yet have the request_id / file_sha256 columns; retry
        # without them so deployments can ship the code before the migration
        # runs. Drop both in one retry — the insert already failed once, and a
        # per-column ladder would cost an extra round-trip per missing column.
        if "request_id" in row or "file_sha256" in row:
            row.pop("request_id", None)
            row.pop("file_sha256", None)
            inserted = table("documents").insert(row)
        else:
            raise
    full_row = inserted[0] if inserted else row
    full_row["summary"] = summary
    full_row["concept_notes"] = concept_notes
    # #117: one document.processed per persisted document, covering both the
    # sync and the streaming agent path. Ids/counts only — never the text,
    # summary, or concept notes.
    events_service.log_event(
        "document.processed",
        category="usage",
        user_id=user_id,
        request_id=request_id,
        payload={
            "document_id": full_row["id"],
            "category": result.classification.category,
            "course_id": course_id,
            "char_count": char_count,
        },
    )
    return full_row["id"], full_row


def _grading_categories_from(result: DocumentProcessingResult) -> list[dict]:
    """Map orchestrator GradingCategory -> legacy {name, weight} shape.

    Returns [] for non-syllabus documents or when the syllabus did not
    state a grading breakdown — matches the legacy pipeline's contract
    so the frontend's category-rendering branch sees the same shape.
    """
    if not (result.classification.is_syllabus and result.syllabus
            and result.syllabus.grading_categories):
        return []
    return [
        {"name": c.name, "weight": float(c.weight)}
        for c in result.syllabus.grading_categories
    ]


def _save_orchestrator_syllabus(*, user_id: str, course_id: str, filename: str,
                                result: DocumentProcessingResult) -> None:
    """Map SyllabusAssignment -> legacy assignments shape and persist.

    Drops entries with due_date=None per the no-invent contract.
    Best-effort: any error is logged and swallowed.
    """
    if not (result.classification.is_syllabus and result.syllabus
            and result.syllabus.assignments):
        return
    legacy: list[dict] = []
    for a in result.syllabus.assignments:
        if a.due_date is None:
            continue
        legacy.append({
            "title": a.title,
            "due_date": a.due_date.isoformat(),
            "course_id": course_id,
            "course_name": result.syllabus.course_title,
            "assignment_type": "other",
            "notes": a.description,
        })
    if legacy:
        try:
            save_assignments_to_db(user_id, legacy, source="syllabus")
        except Exception:
            logger.exception("Assignment save failed for '%s' (best-effort)", filename)


def _graph_backstop(*, user_id: str, course_id: str, filename: str,
                    result: DocumentProcessingResult) -> None:
    """Apply graph update if the orchestrator skipped its tool call."""
    if result.graph_updated:
        return
    if result.classification.category not in ("syllabus", "assignment"):
        return
    try:
        new_nodes = [
            {"concept_name": c.name, "initial_mastery": 0.0}
            for c in result.concepts.concepts
        ]
        apply_graph_update(user_id, {"new_nodes": new_nodes}, course_id=course_id)
    except Exception:
        logger.exception("Graph backstop failed for '%s' (best-effort)", filename)


@router.post("/upload/sync")
async def upload_document_sync(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    course_id: str = Form(...),
    user_id: str = Form(...),
):
    """Non-streaming JSON upload. Original behavior preserved here so any
    frontend that hasn't migrated to the SSE /upload route keeps working."""
    require_self(user_id, request)
    _validate_user(user_id)

    # ── Validation ────────────────────────────────────────────────────────────
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

    # File-level dedup: the same deck arrives from many students under many
    # filenames. The fingerprint covers the bytes only, so a rename still
    # matches. A twin means the text is already stored — skip OCR, the slowest
    # step on this path. The lookup is global because extraction is a pure
    # function of the bytes; whether the shared CHUNKS can be reused is a
    # course-scoped question, answered on the streaming route which indexes.
    file_hash = file_sha256(file_bytes)
    twin = find_duplicate(file_hash)
    if twin:
        logger.info(
            "Duplicate upload '%s' matches document %s — reusing extracted text",
            filename, twin.get("id"),
        )
        extracted_text = twin["extracted_text"]
    else:
        extracted_text = _extract_text_or_422(file_bytes, filename, file.content_type or "")

    # The upload form sends the ABSTRACT course id; documents key on the
    # OFFERING. Resolve to the current-term offering once (create=True so a
    # fresh upload lands in the real semester). The abstract course_id stays
    # the key for the graph + course-context + calendar side effects below.
    offering_id = resolve_offering(course_id, create=True)

    # ── AI: orchestrator (parallel workers + tool-driven graph update) ────────
    # Unify with the middleware-stamped request ID so agent traces and
    # client-facing error payloads share the same correlation key.
    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())  # ultimate fallback if middleware somehow didn't run
    )

    # Idempotency: if the client retries with the same X-Request-ID,
    # short-circuit to the previously persisted document instead of
    # re-running the orchestrator.
    existing = _existing_doc_by_request_id(user_id, request_id)
    if existing:
        response = dict(existing)
        response.setdefault("categories", [])
        return response

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
            "char_count": len(extracted_text),
        },
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
    _, full_row = await asyncio.to_thread(
        _persist_document, user_id=user_id, offering_id=offering_id,
        filename=filename, result=result, request_id=request_id,
        course_id=course_id, char_count=len(extracted_text),
        file_hash=file_hash,
    )

    background_tasks.add_task(_invalidate_study_guide_cache, user_id, offering_id)
    background_tasks.add_task(update_course_context, course_id)
    background_tasks.add_task(_check_upload_achievements, user_id)

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
    require_self(user_id, request)
    _validate_user(user_id)

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

    # Unify the agent-trace request_id with the middleware-stamped one so
    # SSE error payloads and Logfire spans share a single correlation key.
    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())  # ultimate fallback if middleware somehow didn't run
    )
    # Documents key on the offering (0025); the graph + course-context key on
    # the abstract course id (kept in SaplingDeps for the agent's graph tools).
    offering_id = resolve_offering(course_id, create=True)
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
    # File-level dedup (see the /upload/sync twin of this block). A hit here
    # means the text is already stored, so extraction is skipped on BOTH OCR
    # strategies: setting extracted_text non-None also short-circuits the
    # async `if extracted_text is None:` phase below.
    file_hash = file_sha256(file_bytes)
    twin = find_duplicate(file_hash)
    if twin:
        logger.info(
            "Duplicate upload '%s' matches document %s — reusing extracted text",
            filename, twin.get("id"),
        )
    extracted_text: str | None = (
        twin["extracted_text"] if twin
        else (
            None if OCR_ASYNC_ENABLED
            else _extract_text_or_422(file_bytes, filename, file.content_type or "")
        )
    )

    async def event_stream():
        nonlocal extracted_text
        try:
            yield sapling_event_to_sse(SaplingEvent(
                type="status", step="start",
                message="Document received. Processing...",
            ))

            # Idempotency: a client retry with the same X-Request-ID
            # should not re-run the orchestrator. Emit a result+done pair
            # built from the previously persisted row instead.
            existing = _existing_doc_by_request_id(user_id, request_id)
            if existing:
                yield sapling_event_to_sse(SaplingEvent(
                    type="result", step="finalize",
                    message="Already processed (idempotent replay).",
                    data=existing,
                ))
                yield sapling_event_to_sse(SaplingEvent(
                    type="status", step="done",
                    message="Saved.",
                    data={"document_id": existing.get("id"), "request_id": request_id},
                ))
                return

            # #117: one document.upload per accepted upload attempt — AFTER
            # the idempotent-replay short-circuit (PR #465 review), so an
            # X-Request-ID retry doesn't inflate the count. char_count is
            # unknown (None) when OCR_ASYNC_ENABLED defers extraction below —
            # document.processed carries the real count once extraction ran.
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

            # ── Phase 0: text extraction (when OCR_ASYNC_ENABLED) ─────────────
            # Failures here can NOT fall through to the legacy fallback —
            # the legacy path uses the same extractor, and would crash on
            # `extracted_text=None`. Emit a terminal error+done pair and
            # return so the client gets a clean failure instead of a
            # double-fault.
            if extracted_text is None:
                yield sapling_event_to_sse(SaplingEvent(
                    type="progress", step="extracting_text",
                    message="Extracting text from document...",
                ))
                try:
                    extracted_text = await asyncio.to_thread(
                        extract_text_from_file, file_bytes, filename,
                        file.content_type or "",
                    )
                except Exception:
                    logger.exception(
                        "Async text extraction failed for '%s'", filename,
                    )
                    yield sapling_event_to_sse(SaplingEvent(
                        type="error", step="failed",
                        message="Could not read this document. Please try a different file.",
                        data={"request_id": request_id},
                    ))
                    yield sapling_event_to_sse(SaplingEvent(
                        type="status", step="done",
                        message="Failed.",
                    ))
                    return
                yield sapling_event_to_sse(SaplingEvent(
                    type="progress", step="extracted_text",
                    message=f"Extracted {len(extracted_text):,} chars.",
                ))
                # Extraction can succeed and still yield nothing usable -- a
                # rasterized PDF has no text layer, so the except branch above
                # never fires. Stop here rather than asking the model to
                # summarize an empty document, which it answers by inventing
                # one (see MIN_EXTRACTED_CHARS). Same terminal error+done pair
                # as the extraction-failure path, so clients need no new case.
                if not _has_usable_text(extracted_text):
                    logger.warning(
                        "Async extraction yielded %d usable chars for '%s' - "
                        "rejecting as unreadable",
                        len((extracted_text or "").strip()), filename,
                    )
                    yield sapling_event_to_sse(SaplingEvent(
                        type="error", step="failed",
                        message=UNREADABLE_DOCUMENT_DETAIL,
                        data={"request_id": request_id},
                    ))
                    yield sapling_event_to_sse(SaplingEvent(
                        type="status", step="done",
                        message="Failed.",
                    ))
                    return

            # ── Phase 1: classifier (serial gate) ─────────────────────────────
            yield sapling_event_to_sse(SaplingEvent(
                type="progress", step="classify",
                message="Classifying document...",
            ))
            cls_run = record_agent_usage(
                await classifier_agent.run(
                    extracted_text, deps=deps, usage_limits=WORKER_LIMITS,
                ),
                feature="document", task="classifier",
            )
            classification = cls_run.output
            yield sapling_event_to_sse(SaplingEvent(
                type="progress", step="classified",
                message=f"Classified as {classification.category}.",
                data={
                    "category": classification.category,
                    "is_syllabus": classification.is_syllabus,
                },
            ))

            # ── Phase 2: workers in parallel ──────────────────────────────────
            yield sapling_event_to_sse(SaplingEvent(
                type="progress", step="extract",
                message="Extracting summary, concepts"
                        + (" and syllabus" if classification.is_syllabus else "")
                        + " in parallel...",
            ))
            summary_task = summary_agent.run(
                extracted_text, deps=deps, usage_limits=WORKER_LIMITS,
            )
            concepts_task = concept_extraction_agent.run(
                extracted_text, deps=deps, usage_limits=WORKER_LIMITS,
            )
            if classification.is_syllabus:
                syllabus_task = syllabus_extraction_agent.run(
                    extracted_text, deps=deps, usage_limits=WORKER_LIMITS,
                )
                summary_r, concepts_r, syllabus_r = await asyncio.gather(
                    summary_task, concepts_task, syllabus_task,
                )
                record_agent_usage(syllabus_r, feature="document", task="syllabus")
                summary = summary_r.output
                concepts = concepts_r.output
                syllabus = syllabus_r.output
            else:
                summary_r, concepts_r = await asyncio.gather(summary_task, concepts_task)
                summary = summary_r.output
                concepts = concepts_r.output
                syllabus = None
            record_agent_usage(summary_r, feature="document", task="summary")
            record_agent_usage(concepts_r, feature="document", task="concepts")
            yield sapling_event_to_sse(SaplingEvent(
                type="progress", step="extracted",
                message=f"Extracted {len(concepts.concepts)} concept(s).",
            ))

            # ── Phase 3: graph update (direct call, no agent loop) ──────────────
            yield sapling_event_to_sse(SaplingEvent(
                type="progress", step="graph_update",
                message="Merging concepts into the course graph...",
            ))
            concept_names = [c.name for c in concepts.concepts]
            merged = await apply_concepts_to_graph(user_id, course_id, concept_names)
            graph_updated = merged > 0
            yield sapling_event_to_sse(SaplingEvent(
                type="progress", step="graph_updated",
                message=f"Merged {merged} concept(s).",
            ))

            # ── Compose final result + emit ──────────────────────────────────
            final_output = DocumentProcessingResult(
                classification=classification,
                summary=summary,
                concepts=concepts,
                syllabus=syllabus,
                graph_updated=graph_updated,
            )
            yield sapling_event_to_sse(SaplingEvent(
                type="result", step="finalize",
                message="Processing complete.",
                data=final_output.model_dump(mode="json"),
            ))
        except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
            # Terminal (#151b): `step="fallback"` left the SSE vocabulary
            # with the legacy pipeline (ADR 0024). Emit the exact
            # error:failed + status:done tail the deleted fallback used on
            # double-failure, so clients need no new case. Retry is safe —
            # nothing was persisted, and a retry mints a fresh X-Request-ID.
            logger.warning(
                "Agent guardrails tripped during stream for '%s'; failing",
                filename, exc_info=e,
            )
            yield sapling_event_to_sse(SaplingEvent(
                type="error", step="failed",
                message="Document processing failed. Please try again.",
                data={"request_id": request_id} if request_id else None,
            ))
            yield sapling_event_to_sse(SaplingEvent(
                type="status", step="done",
                message="Failed.",
            ))
            return
        except Exception:
            # Same terminal tail; a bare exception is a bug, so keep the
            # full exception log where the guardrail branch logs a WARNING.
            logger.exception("Unexpected streaming failure for '%s'", filename)
            yield sapling_event_to_sse(SaplingEvent(
                type="error", step="failed",
                message="Document processing failed. Please try again.",
                data={"request_id": request_id} if request_id else None,
            ))
            yield sapling_event_to_sse(SaplingEvent(
                type="status", step="done",
                message="Failed.",
            ))
            return

        # ── Post-roll: side effects + persistence (#132 item 11) ──────────
        # Runs AFTER the terminal `result` event is on the wire, in its own
        # try/except. A post-result failure still emits the terminal
        # error:failed + status:done pair and NEVER a second result — the
        # client already holds the processed document, and every emitter in
        # this generator sends at most one result per stream. The legacy
        # fallback this separation used to guard against re-triggering
        # (result → error → result → done, plus a second model call) is
        # GONE (#151b, ADR 0024); the separate try/except now simply keeps
        # the post-result failure tail identical to the pre-result failure
        # branches above. #154 builds on this structure — keep persistence
        # in the post-roll, after the result event.
        try:
            # Synchronous PostgREST writes — threaded so they don't block
            # the event loop serving this (and every other) SSE stream
            # (#132 item 22; same pattern as the async-OCR extraction above).
            await asyncio.to_thread(
                _save_orchestrator_syllabus,
                user_id=user_id, course_id=course_id,
                filename=filename, result=final_output,
            )
            await asyncio.to_thread(
                _graph_backstop,
                user_id=user_id, course_id=course_id,
                filename=filename, result=final_output,
            )
            doc_id, _ = await asyncio.to_thread(
                _persist_document,
                user_id=user_id, offering_id=offering_id,
                filename=filename, result=final_output,
                request_id=request_id,
                course_id=course_id,
                char_count=len(extracted_text) if extracted_text is not None else None,
                file_hash=file_hash,
            )

            # BackgroundTasks runs after response close — useless for SSE since
            # the stream IS the response. _spawn_post_roll uses create_task
            # but attaches a done-callback so exceptions land in the log
            # instead of disappearing.
            post_roll: list[tuple] = [
                ("invalidate_study_guide_cache", _invalidate_study_guide_cache, user_id, offering_id),
                ("update_course_context", update_course_context, course_id),
                ("check_upload_achievements", _check_upload_achievements, user_id),
            ]
            # The shared corpus is deduplicated by content, so a file already
            # indexed for THIS course would re-embed every chunk only to upsert
            # it onto the rows that already exist. Skip the work entirely.
            # A twin from another course still indexes: chunk ids are
            # course-scoped, so its chunks do not serve this course.
            if chunks_already_exist(twin, offering_id):
                logger.info(
                    "Chunks for '%s' already indexed under offering %s — skipping re-index",
                    filename, offering_id,
                )
            else:
                post_roll.append(
                    ("index_document_chunks", _index_document_chunks, doc_id, course_id, user_id, extracted_text, classification.category, getattr(summary, "abstract", "")),
                )
            _spawn_post_roll(*post_roll)
        except Exception:
            logger.exception(
                "Post-result persistence failed for '%s' — result already "
                "sent, so no legacy fallback (it would re-run the pipeline "
                "and emit a second result)", filename,
            )
            yield sapling_event_to_sse(SaplingEvent(
                type="error", step="failed",
                message="The document was processed but could not be saved. "
                        "Please try uploading it again.",
                data={"request_id": request_id} if request_id else None,
            ))
            yield sapling_event_to_sse(SaplingEvent(
                type="status", step="done",
                message="Failed.",
            ))
            return

        yield sapling_event_to_sse(SaplingEvent(
            type="status", step="done",
            message="Saved.",
            data={"document_id": doc_id},
        ))

    return EventSourceResponse(
        event_stream(), headers={"Cache-Control": SSE_CACHE_CONTROL}
    )


def _invalidate_study_guide_cache(user_id: str, offering_id: str) -> None:
    """Background task: delete cached study guides so they regenerate fresh.

    Study guides key on the offering (0025), matching the documents that
    feed them.
    """
    try:
        table("study_guides").delete(
            filters={"user_id": f"eq.{user_id}", "offering_id": f"eq.{offering_id}"}
        )
    except Exception:
        logger.exception(
            "Failed to invalidate study guides cache for user=%s offering=%s",
            user_id, offering_id,
        )


def _check_upload_achievements(user_id: str) -> None:
    """Background task: best-effort achievement check."""
    try:
        check_achievements(user_id, "documents_uploaded", {})
    except Exception:
        pass


def _index_document_chunks(
    doc_id: str,
    course_id: str,      # Sapling UUID — resolved to BU code internally
    user_id: str,
    extracted_text: str,
    category: str,
    doc_summary: str = "",
) -> None:
    """Chunk, embed, and upsert a document into course_chunks.

    Runs in a background thread via _spawn_post_roll after the document
    is persisted, so it never blocks the SSE stream.
    """
    import time
    from services.chunker import chunk_for_category
    from services.rag_service import embed_document_text, index_document_chunks
    from services.encryption import encrypt_if_present

    MIN_COURSE_RELEVANCE = 0.35

    try:
        # Resolve BU course code from Sapling UUID
        rows = table("courses").select(
            "course_code", filters={"id": f"eq.{course_id}"}, limit=1
        )
        bu_course_id = (rows[0].get("course_code") or course_id) if rows else course_id

        chunks = chunk_for_category(extracted_text, category)
        if not chunks:
            return

        # Store raw extracted text on the document row (best-effort)
        try:
            table("documents").update(
                {"extracted_text": encrypt_if_present(extracted_text)},
                filters={"id": f"eq.{doc_id}"},
            )
        except Exception:
            logger.warning("[RAG] could not store extracted_text for doc %s", doc_id)

        # Relevance gate: skip docs that are off-topic for the course. The
        # embedding-based check below routes through services.rag_service
        # (#413) — the shared lazy client behind the #439 model_mode() gate —
        # catalog_rows itself is a plain Supabase read (not gated) so the gate
        # is only ever skipped when there's actually a catalog embedding to
        # compare against.
        catalog_rows = table("course_chunks").select(
            "embedding",
            filters={"course_id": f"eq.{bu_course_id}", "category": "eq.catalog"},
            limit=1,
        )
        if catalog_rows and catalog_rows[0].get("embedding"):
            if model_mode() != "real":
                # #439: no google.genai.Client in non-real mode. Raising here
                # (instead of silently skipping the gate) reproduces the exact
                # behavior a real embed-call failure already produced: the
                # outer `except` below aborts indexing and logs
                # "_index_document_chunks failed for doc %s" — the line
                # e2e_oracles/logscan.py's ALLOWLIST already expects. Function
                # mode is now that same no-op, by design, not by accident of a
                # swallowed exception.
                raise RuntimeError(
                    "RAG relevance-gate embedding skipped: "
                    "SAPLING_MODEL_MODE != 'real' (#439)"
                )

            # #413: no raw genai.Client here — a keyless run used to construct
            # Client(api_key="") whose ValueError the outer `except` swallowed
            # into a silent no-index degrade. rag_service's shared lazy client
            # (dummy-key fallback + timeout) fails at call time with a clear
            # API error instead, on the same degrade path.
            catalog_vec = catalog_rows[0]["embedding"]
            sample_text = doc_summary or chunks[0]
            doc_sample_vec = embed_document_text(sample_text)
            time.sleep(1.5)
            dot = sum(a * b for a, b in zip(doc_sample_vec, catalog_vec))
            if dot < MIN_COURSE_RELEVANCE:
                logger.warning(
                    "[RAG] doc %s skipped — relevance to %s is %.3f (< %.2f)",
                    doc_id, bu_course_id, dot, MIN_COURSE_RELEVANCE,
                )
                return

        count = index_document_chunks(
            course_code=bu_course_id,
            doc_id=doc_id,
            uploader_id=user_id,
            chunks=chunks,
        )
        logger.info("[RAG] indexed %d chunks for doc %s", count, doc_id)

    except Exception:
        logger.exception("[RAG] _index_document_chunks failed for doc %s", doc_id)


def _spawn_post_roll(*tasks: tuple) -> None:
    """Fire-and-forget post-roll work for SSE / non-FastAPI-BackgroundTasks
    contexts. Each tuple is (label, callable, *args). Exceptions in the
    spawned task are logged via a done-callback so they don't disappear
    silently the way bare asyncio.create_task(...) lets them.
    """
    for label, fn, *args in tasks:
        task = asyncio.create_task(asyncio.to_thread(fn, *args))
        task.add_done_callback(lambda t, _label=label: _log_post_roll_exc(t, _label))


def _log_post_roll_exc(task: "asyncio.Task", label: str) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Post-roll task '%s' failed: %s", label, exc, exc_info=exc)


def _course_label(course_id: str) -> str:
    """Best-effort human label for a course (for prompts and toasts)."""
    rows = table("courses").select(
        "course_code,course_name", filters={"id": f"eq.{course_id}"}, limit=1,
    ) or []
    if not rows:
        return "Course"
    row = rows[0]
    code = (row.get("course_code") or "").strip()
    name = (row.get("course_name") or "").strip()
    if code and name:
        return f"{code} — {name}"
    return code or name or "Course"


def _scan_concepts_for_course(
    user_id: str,
    course_id: str,
    *,
    doc_filename: str | None = None,
    doc_summary: str | None = None,
    doc_concept_notes: list[dict] | None = None,
) -> dict:
    """Shared scan logic. Pulls existing course concepts, asks the LLM to
    extend the set, and writes new nodes via apply_graph_update."""
    existing_rows = table("graph_nodes").select(
        "id,concept_name", filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    ) or []
    existing_concepts = [r["concept_name"] for r in existing_rows if r.get("concept_name")]

    concepts = _extend_concepts(
        user_id,
        course_id,
        course_label=_course_label(course_id),
        existing_concepts=existing_concepts,
        doc_filename=doc_filename,
        doc_summary=doc_summary,
        doc_concept_notes=doc_concept_notes,
    )
    if not concepts:
        return {"concepts": [], "added": 0, "existing": len(existing_concepts)}

    before_count = len(existing_rows)
    try:
        new_nodes = [{"concept_name": name, "initial_mastery": 0.0} for name in concepts]
        apply_graph_update(user_id, {"new_nodes": new_nodes}, course_id=course_id)
    except Exception:
        logger.exception("Concept scan failed for course=%s", course_id)
        raise HTTPException(status_code=500, detail="Concept scan failed.")

    after_rows = table("graph_nodes").select(
        "id", filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    ) or []
    return {
        "concepts": concepts,
        "added": max(0, len(after_rows) - before_count),
        "existing": len(existing_concepts),
    }


@router.post("/doc/{document_id}/scan-concepts")
def scan_document_concepts(document_id: str, request: Request, body: dict = Body(...)):
    """Extend the course's concept graph using one document's stored
    summary + takeaways as the seed signal."""
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required.")
    require_self(user_id, request)
    _validate_user(user_id)

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

    doc_summary = decrypt_if_present(doc.get("summary"))
    notes_raw = doc.get("concept_notes")
    if isinstance(notes_raw, str):
        try:
            doc_concept_notes = decrypt_json(notes_raw)
        except Exception:
            doc_concept_notes = []
    else:
        doc_concept_notes = notes_raw or []

    return _scan_concepts_for_course(
        user_id,
        course_id,
        doc_filename=doc.get("file_name"),
        doc_summary=doc_summary,
        doc_concept_notes=doc_concept_notes
    )


@router.post("/course/{course_id}/scan-concepts")
def scan_course_concepts(course_id: str, request: Request, body: dict = Body(...)):
    """Extend the course's concept graph from the course label alone
    (and whatever is already in the graph)."""
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required.")
    require_self(user_id, request)
    _validate_user(user_id)
    return _scan_concepts_for_course(user_id, course_id)
