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
from services.auth_guard import get_session_user_id, require_self
from services.encryption import encrypt_if_present, encrypt_json, decrypt_if_present, decrypt_json
from services.extraction_service import extract_text_from_file
from services.gemini_service import MODEL_LITE, call_gemini_json
from services.calendar_service import save_assignments_to_db
from services.graph_service import apply_graph_update
from services.course_context_service import update_course_context
from services.achievement_service import check_achievements
from services.agent_events import SaplingEvent, sapling_event_to_sse
from services.request_context import current_request_id
from agents import WORKER_LIMITS
from agents.classifier import classifier_agent
from agents.summary import summary_agent
from agents.concept_extraction import concept_extraction_agent
from agents.syllabus_extraction import syllabus_extraction_agent
from agents.deps import SaplingDeps
from agents.document import process_document, DocumentProcessingResult
from agents.tools.graph import apply_concepts_to_graph

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB

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


def _validate_user(user_id: str) -> None:
    """Verify that the user_id corresponds to an existing user."""
    rows = table("users").select("id", filters={"id": f"eq.{user_id}"}, limit=1)
    if not rows:
        raise HTTPException(status_code=403, detail="Invalid user.")


def _coerce_str_list(value) -> list[str]:
    """Coerce LLM output into a list[str], dropping non-strings and blanks."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append(s)
    return out


def _coerce_dict_list(value) -> list[dict]:
    """Coerce LLM output into a list[dict]."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _extend_course_concepts(
    *,
    course_label: str,
    existing_concepts: list[str],
    doc_filename: str | None = None,
    doc_summary: str | None = None,
    doc_concept_notes: list[dict] | None = None,
) -> list[str]:
    """Focused LLM call: extend an existing course concept set.

    The LLM is shown the course label, every concept already in the graph,
    and (when scanning a specific document) that document's stored summary
    and concept notes. It returns new concepts to add, avoiding duplicates.
    """
    existing_block = (
        "\n".join(f"- {c}" for c in existing_concepts) if existing_concepts else "(none yet)"
    )
    doc_block = ""
    if doc_filename or doc_summary or doc_concept_notes:
        notes_block = (
            "\n".join(
                f"  - {n.get('name', '?')}: {n.get('description', '')[:200]}"
                for n in (doc_concept_notes or [])
            )
            or "  (none)"
        )
        doc_block = (
            "\nNew document being scanned:\n"
            f"  Title: {doc_filename or '(untitled)'}\n"
            f"  Summary: {doc_summary or '(none)'}\n"
            "  Concepts already extracted from this document:\n"
            f"{notes_block}\n"
        )

    prompt = (
        f"You are curating the concept set for the course \"{course_label}\".\n"
        "Concepts already in the student's graph for this course:\n"
        f"{existing_block}\n"
        f"{doc_block}"
        "Return ONLY valid JSON with no markdown or backticks:\n"
        '{ "concepts": ["...", "..."] }\n'
        "Rules:\n"
        "- Return between 0 and 15 NEW concepts that should be in this course's "
        "graph but are not in the existing list above.\n"
        "- If the existing set already covers the relevant material, return [].\n"
        "- Each concept is a short Title Case noun phrase "
        "(e.g. \"Linear Regression\", \"Big-O Analysis\").\n"
        "- Do NOT repeat or paraphrase any existing concept.\n"
        "- No assignment titles, week labels, page numbers, problem numbers, or "
        "administrative items.\n"
        "- concepts must be a JSON array of strings."
    )
    raw = call_gemini_json(prompt, model=MODEL_LITE)
    if not isinstance(raw, dict):
        return []
    return _coerce_str_list(raw.get("concepts"))


def _coerce_concept_notes(value) -> list[dict]:
    """Coerce LLM output into a list of {name, description} dicts.

    Drops entries missing either field. Names are stripped; descriptions
    preserve their markdown body verbatim so the frontend MarkdownChat
    renderer can handle math, mermaid, plots, and theorem callouts.
    """
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        desc = item.get("description")
        if not isinstance(name, str) or not isinstance(desc, str):
            continue
        name = name.strip()
        desc = desc.strip()
        if not name or not desc:
            continue
        out.append({"name": name, "description": desc})
    return out


def _process_document(filename: str, extracted_text: str) -> dict:
    """Single LLM call: classify, summarize, and extract assignments + concepts.

    Returns a normalized shape with all fields validated and coerced — callers
    can trust the types without further isinstance checks.
    """
    prompt = (
        f"You are processing a student document titled '{filename}'.\n"
        f"Content: {extracted_text[:12000]}\n"
        "Return ONLY valid JSON with no markdown or backticks:\n"
        "{\n"
        '  "category": one of ["syllabus","lecture_notes","slides","reading","assignment","study_guide","other"],\n'
        '  "summary": "2-3 sentence overview of the document",\n'
        '  "concept_notes": [{"name": "Concept Name", "description": "..."}],\n'
        '  "categories": [],\n'
        '  "assignments": []\n'
        "}\n"
        'If category is "syllabus", populate "assignments" with every deadline found:\n'
        '  {"title": "...", "due_date": "YYYY-MM-DD (assume 2026 if year missing)", '
        '"course_name": "...", "assignment_type": one of [homework,exam,reading,project,quiz,other], "notes": "..." or null}\n'
        'For non-syllabus documents, "assignments" must be [].\n'
        'If category is "syllabus", also populate "categories" with the grading-weight buckets:\n'
        '  {"name": "Exams", "weight": 40}  // weight passes through verbatim, do not normalize\n'
        'For non-syllabus documents, "categories" must be [].\n'
        "\n"
        'Populate "concept_notes" with the document\'s key concepts. Use this for ALL categories — '
        "this is the single takeaways list for the document.\n"
        "  - Syllabus: 5–15 high-level course topics drawn from the schedule, learning outcomes, or topic list.\n"
        "  - Assignment: 1–8 specific topics the assignment tests or practices.\n"
        "  - Lecture notes / slides / reading / study_guide / other: 4–12 concepts the document covers.\n"
        '  - "name" is a short Title Case noun phrase (e.g. "Linear Regression", "Big-O Analysis"). '
        "Do NOT use problem numbers, week labels, or administrative items as names. The name is what "
        "becomes the concept node in the student's knowledge graph, so it must read as a standalone topic.\n"
        '  - "description" is a 2–4 sentence explanation of the concept written for the student. '
        "It must be MARKDOWN and may use:\n"
        "      • inline math `$x^2$` and display math `$$\\int f(x)\\,dx$$`\n"
        "      • fenced ```mermaid``` blocks for diagrams\n"
        "      • fenced ```plot``` blocks for function plots (function-plot.js JSON spec)\n"
        "      • `:::theorem`, `:::definition`, `:::proof`, `:::lemma`, `:::example`, `:::note` directives\n"
        "    Use these tools only when they genuinely clarify the concept; otherwise keep it prose. "
        "Each description should align tightly with what a graph node for this concept would represent.\n"
        "\n"
        '"concept_notes" must be a JSON array of {"name": str, "description": str} objects.'
    )
    raw = call_gemini_json(prompt)
    if not isinstance(raw, dict):
        raw = {}

    category = raw.get("category")
    if category not in VALID_CATEGORIES:
        category = "other"

    summary = raw.get("summary")
    if not isinstance(summary, str):
        summary = ""

    concept_notes = _coerce_concept_notes(raw.get("concept_notes"))

    categories = _coerce_dict_list(raw.get("categories"))
    clean_categories = []
    for c in categories:
        name = c.get("name")
        weight = c.get("weight")
        if isinstance(name, str) and name.strip() and isinstance(weight, (int, float)):
            clean_categories.append({"name": name.strip(), "weight": float(weight)})

    return {
        "category": category,
        "summary": summary.strip(),
        "categories": clean_categories,
        "assignments": _coerce_dict_list(raw.get("assignments")),
        "concept_notes": concept_notes,
        "concepts": [c["name"] for c in concept_notes],
    }


@router.get("/user/{user_id}")
def list_documents(user_id: str, request: Request):
    require_self(user_id, request)
    _validate_user(user_id)
    docs = table("documents").select(
        "id,user_id,course_id,file_name,category,summary,concept_notes,created_at,processed_at",
        filters={"user_id": f"eq.{user_id}"},
        order="created_at.desc",
    ) or []
    for d in docs:
        d["summary"] = decrypt_if_present(d.get("summary"))
        notes_raw = d.get("concept_notes")
        if isinstance(notes_raw, str):
            d["concept_notes"] = decrypt_json(notes_raw)
    return {"documents": docs}


@router.delete("/doc/{document_id}")
def delete_document(document_id: str, request: Request, user_id: str | None = None):
    if user_id:
        require_self(user_id, request)
        _validate_user(user_id)
    else:
        user_id = get_session_user_id(request)
    # Ensure the document belongs to the requesting user
    docs = table("documents").select("id", filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"}, limit=1)
    if not docs:
        raise HTTPException(status_code=404, detail="Document not found.")
    table("documents").delete(filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"})
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
    docs = table("documents").select("id", filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"}, limit=1)
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
        return extract_text_from_file(file_bytes, filename, content_type)
    except Exception:
        logger.exception("Text extraction failed for '%s'", filename)
        raise HTTPException(
            status_code=422,
            detail="Could not read this document. Please try a different file.",
        )


def _existing_doc_by_request_id(user_id: str, request_id: str) -> dict | None:
    """Return an existing documents row for this user + request_id, if any.

    The request_id column may not exist in older schemas — catch that and
    return None so deployments can ship the code before the migration runs.
    Defensive against non-list return shapes (mocked DBs, partial errors)
    so a misbehaving Supabase response can't masquerade as a cache hit.
    """
    try:
        rows = table("documents").select(
            "id,user_id,course_id,file_name,category,summary,concept_notes,created_at,processed_at",
            filters={"user_id": f"eq.{user_id}", "request_id": f"eq.{request_id}"},
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
    course_id: str,
    filename: str,
    result: DocumentProcessingResult,
    request_id: str | None = None,
) -> tuple[str, dict]:
    """Insert a documents row from an orchestrator result.

    Shared by both upload_document_sync and the streaming upload_document.
    summary + concept_notes are encrypted at the insert boundary; the
    returned row carries the plaintext shape so callers can pass it
    straight back to the client without an extra decrypt step.
    ``request_id`` (when provided) is stored verbatim for idempotent
    replay detection. Returns (document_id, full_row).
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
        "course_id": course_id,
        "file_name": filename,
        "category": result.classification.category,
        "summary": encrypt_if_present(summary),
        "concept_notes": encrypt_json(concept_notes) if concept_notes is not None else None,
        "created_at": now,
        "processed_at": now,
    }
    if request_id:
        row["request_id"] = request_id
    try:
        inserted = table("documents").insert(row)
    except Exception:
        # Schema may not yet have the request_id column; retry without it
        # so deployments can ship the code before the migration runs.
        if "request_id" in row:
            row.pop("request_id", None)
            inserted = table("documents").insert(row)
        else:
            raise
    full_row = inserted[0] if inserted else row
    full_row["summary"] = summary
    full_row["concept_notes"] = concept_notes
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
            save_assignments_to_db(user_id, legacy)
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
            detail="File exceeds the 15 MB limit. Please upload a smaller file.",
        )

    extracted_text = _extract_text_or_422(file_bytes, filename, file.content_type or "")

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

    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id,
        supabase=None,
        request_id=request_id,
    )
    try:
        result: DocumentProcessingResult = await process_document(extracted_text, deps)
    except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
        logger.warning(
            "Agent guardrails tripped for '%s'; falling back to legacy",
            filename, exc_info=e,
        )
        return await _legacy_upload_pipeline(
            filename=filename, extracted_text=extracted_text,
            course_id=course_id, user_id=user_id,
            background_tasks=background_tasks,
            request_id=request_id,
        )
    except Exception:
        logger.exception(
            "Unexpected agent failure for '%s'; falling back to legacy",
            filename,
        )
        return await _legacy_upload_pipeline(
            filename=filename, extracted_text=extracted_text,
            course_id=course_id, user_id=user_id,
            background_tasks=background_tasks,
            request_id=request_id,
        )

    _save_orchestrator_syllabus(user_id=user_id, course_id=course_id,
                                filename=filename, result=result)
    _graph_backstop(user_id=user_id, course_id=course_id,
                    filename=filename, result=result)
    _, full_row = _persist_document(user_id=user_id, course_id=course_id,
                                    filename=filename, result=result,
                                    request_id=request_id)

    background_tasks.add_task(_invalidate_study_guide_cache, user_id, course_id)
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
            detail="File exceeds the 15 MB limit. Please upload a smaller file.",
        )

    # Unify the agent-trace request_id with the middleware-stamped one so
    # SSE error payloads and Logfire spans share a single correlation key.
    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())  # ultimate fallback if middleware somehow didn't run
    )
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
    extracted_text: str | None = (
        None if OCR_ASYNC_ENABLED
        else _extract_text_or_422(file_bytes, filename, file.content_type or "")
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

            # ── Phase 1: classifier (serial gate) ─────────────────────────────
            yield sapling_event_to_sse(SaplingEvent(
                type="progress", step="classify",
                message="Classifying document...",
            ))
            cls_run = await classifier_agent.run(
                extracted_text, deps=deps, usage_limits=WORKER_LIMITS,
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
                summary = summary_r.output
                concepts = concepts_r.output
                syllabus = syllabus_r.output
            else:
                summary_r, concepts_r = await asyncio.gather(summary_task, concepts_task)
                summary = summary_r.output
                concepts = concepts_r.output
                syllabus = None
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

            # ── Post-roll: side effects + persistence ─────────────────────────
            _save_orchestrator_syllabus(user_id=user_id, course_id=course_id,
                                        filename=filename, result=final_output)
            _graph_backstop(user_id=user_id, course_id=course_id,
                            filename=filename, result=final_output)
            doc_id, _ = _persist_document(user_id=user_id, course_id=course_id,
                                          filename=filename, result=final_output,
                                          request_id=request_id)

            # BackgroundTasks runs after response close — useless for SSE since
            # the stream IS the response. _spawn_post_roll uses create_task
            # but attaches a done-callback so exceptions land in the log
            # instead of disappearing.
            _spawn_post_roll(
                ("invalidate_study_guide_cache", _invalidate_study_guide_cache, user_id, course_id),
                ("update_course_context", update_course_context, course_id),
                ("check_upload_achievements", _check_upload_achievements, user_id),
            )

            yield sapling_event_to_sse(SaplingEvent(
                type="status", step="done",
                message="Saved.",
                data={"document_id": doc_id},
            ))
        except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
            logger.warning(
                "Agent guardrails tripped during stream for '%s'; falling back",
                filename, exc_info=e,
            )
            yield sapling_event_to_sse(SaplingEvent(
                type="error", step="fallback",
                message="Agent guardrails tripped; using legacy pipeline.",
                data={"request_id": request_id},
            ))
            async for sse_event in _stream_legacy_fallback(
                filename=filename, extracted_text=extracted_text,
                course_id=course_id, user_id=user_id,
                request_id=request_id,
            ):
                yield sse_event
        except Exception:
            logger.exception("Unexpected streaming failure for '%s'", filename)
            yield sapling_event_to_sse(SaplingEvent(
                type="error", step="fallback",
                message="Unexpected error during processing; using legacy pipeline.",
                data={"request_id": request_id},
            ))
            async for sse_event in _stream_legacy_fallback(
                filename=filename, extracted_text=extracted_text,
                course_id=course_id, user_id=user_id,
                request_id=request_id,
            ):
                yield sse_event

    return EventSourceResponse(event_stream())


async def _stream_legacy_fallback(
    *, filename: str, extracted_text: str, course_id: str, user_id: str,
    request_id: str | None = None,
):
    """Run _legacy_upload_pipeline and yield SSE progress/result/done events.

    Used by the streaming /upload route's exception handlers to deliver
    a document via the legacy path even when the agent pipeline trips.
    The legacy path is a single-shot Gemini call so we cannot observe
    its internal phases — instead we emit a synthetic ``progress`` event
    before kicking it off so the UI doesn't sit on a blank spinner for
    the legacy call's wall-clock latency. If the legacy path also fails,
    we yield a terminal error event so the client doesn't see a silent
    EOF mid-stream. ``request_id`` is the middleware-stamped correlation
    ID — included in any error event so callers can match the failure
    to a Logfire span, and threaded into the legacy insert so a retry
    with the same X-Request-ID is deduped.
    """
    yield sapling_event_to_sse(SaplingEvent(
        type="progress", step="fallback_processing",
        message="Falling back to single-call pipeline. Processing document...",
    ))
    try:
        legacy_response = await _legacy_upload_pipeline(
            filename=filename, extracted_text=extracted_text,
            course_id=course_id, user_id=user_id,
            request_id=request_id,
        )
    except Exception:
        logger.exception("Legacy fallback also failed for '%s'", filename)
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
    yield sapling_event_to_sse(SaplingEvent(
        type="result", step="finalize",
        message="Processing complete (legacy fallback).",
        data=legacy_response,
    ))
    yield sapling_event_to_sse(SaplingEvent(
        type="status", step="done",
        message="Saved.",
        data={"document_id": legacy_response.get("id")},
    ))


def _invalidate_study_guide_cache(user_id: str, course_id: str) -> None:
    """Background task: delete cached study guides so they regenerate fresh."""
    try:
        table("study_guides").delete(
            filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"}
        )
    except Exception:
        logger.exception(
            "Failed to invalidate study guides cache for user=%s course=%s",
            user_id, course_id,
        )


def _check_upload_achievements(user_id: str) -> None:
    """Background task: best-effort achievement check."""
    try:
        check_achievements(user_id, "documents_uploaded", {})
    except Exception:
        pass


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


async def _legacy_upload_pipeline(
    *,
    filename: str,
    extracted_text: str,
    course_id: str,
    user_id: str,
    background_tasks: BackgroundTasks | None = None,
    request_id: str | None = None,
) -> dict:
    """The pre-orchestrator upload pipeline, kept as a fallback per ADR-0001.

    Verbatim copy of the previous upload_document body from text-extraction
    onward. File validation already happened in the caller, so this function
    starts at the AI processing step.

    background_tasks is optional: in streaming-fallback contexts there is
    no FastAPI BackgroundTasks to attach to (the response IS the stream),
    so post-roll work is fired via asyncio.create_task instead.

    ``request_id`` (when provided) is stored on the documents row so a
    client retry with the same X-Request-ID can short-circuit instead of
    re-running the pipeline.
    """
    # ── AI: classify, summarize, and extract assignments (single call) ─────────
    ai = _process_document(filename, extracted_text)

    if ai["category"] == "syllabus" and ai["assignments"]:
        try:
            for a in ai["assignments"]:
                a["course_id"] = course_id
            save_assignments_to_db(user_id, ai["assignments"])
        except Exception:
            logger.exception("Assignment save failed for '%s' (best-effort)", filename)

    if ai["category"] in ("syllabus", "assignment") and ai["concepts"]:
        try:
            new_nodes = [
                {"concept_name": name, "initial_mastery": 0.0}
                for name in ai["concepts"]
            ]
            apply_graph_update(user_id, {"new_nodes": new_nodes}, course_id=course_id)
        except Exception:
            logger.exception("Concept population failed for '%s' (best-effort)", filename)

    # ── Persist to documents table ────────────────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "course_id": course_id,
        "file_name": filename,
        "category": ai["category"],
        "summary": encrypt_if_present(ai["summary"] or None),
        "concept_notes": encrypt_json(ai["concept_notes"]) if ai["concept_notes"] is not None else None,
        "created_at": now,
        "processed_at": now,
    }
    if request_id:
        row["request_id"] = request_id
    try:
        inserted = table("documents").insert(row)
    except Exception:
        # Schema may not yet have the request_id column; retry without it
        # so deployments can ship the code before the migration runs.
        if "request_id" in row:
            row.pop("request_id", None)
            inserted = table("documents").insert(row)
        else:
            raise

    if background_tasks is not None:
        background_tasks.add_task(_invalidate_study_guide_cache, user_id, course_id)
        background_tasks.add_task(update_course_context, course_id)
        background_tasks.add_task(_check_upload_achievements, user_id)
    else:
        _spawn_post_roll(
            ("invalidate_study_guide_cache", _invalidate_study_guide_cache, user_id, course_id),
            ("update_course_context", update_course_context, course_id),
            ("check_upload_achievements", _check_upload_achievements, user_id),
        )

    response = dict(inserted[0] if inserted else row)
    response["summary"] = decrypt_if_present(response.get("summary"))
    notes_raw = response.get("concept_notes")
    if isinstance(notes_raw, str):
        response["concept_notes"] = decrypt_json(notes_raw)
    response["categories"] = ai.get("categories", [])
    return response


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

    concepts = _extend_course_concepts(
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
        "id,user_id,course_id,file_name,summary,concept_notes",
        filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc = rows[0]
    course_id = doc.get("course_id")
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
