"""
backend/services/documents/upload.py

Upload text checks and the shared failure wording (#118, moved from
routes/documents.py): the minimum usable extracted text, the unreadable /
failed details, and the per-user LLM budget's terminal SSE pair.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

from services.agent_events import SaplingEvent, sapling_event_to_sse
from services.extraction_service import extract_text_from_file
from services.llm_budget import LLMBudgetExceeded


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
logger = logging.getLogger(__name__)

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


def _budget_failed_frames(e: LLMBudgetExceeded, request_id: str | None) -> list[dict[str, str]]:
    """#119: the upload stream's terminal pair for a per-user LLM budget
    refusal (services/llm_budget.py) — the budget's own message and code."""
    return [
        sapling_event_to_sse(SaplingEvent(
            type="error", step="failed", message=e.detail,
            data={"request_id": request_id, "code": e.code, "reset_at": e.reset_at_iso},
        )),
        sapling_event_to_sse(SaplingEvent(type="status", step="done", message="Failed.")),
    ]


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
