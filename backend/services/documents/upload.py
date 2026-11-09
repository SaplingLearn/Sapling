"""
backend/services/documents/upload.py

Upload text checks and the shared failure wording (#118, moved from
routes/documents.py): the minimum usable extracted text, the unreadable /
failed details, and the per-user LLM budget's terminal SSE pair.
"""
from __future__ import annotations

from services.agent_events import SaplingEvent, sapling_event_to_sse
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


def _budget_failed_frames(e: LLMBudgetExceeded, request_id: str | None) -> list[str]:
    """#119: the upload stream's terminal pair for a per-user LLM budget
    refusal (services/llm_budget.py) — the budget's own message and code."""
    return [
        sapling_event_to_sse(SaplingEvent(
            type="error", step="failed", message=e.detail,
            data={"request_id": request_id, "code": e.code, "reset_at": e.reset_at_iso},
        )),
        sapling_event_to_sse(SaplingEvent(type="status", step="done", message="Failed.")),
    ]
