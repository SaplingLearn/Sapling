"""Gemini-vision OCR for pages with no extractable text layer.

Scans and photographed handwritten work carry no characters to copy out, so
Docling flags those pages (`fallback_pages`) and, with no local OCR engine
installed, returns "" for them. This backend transcribes such a page from a
rendered image instead.

Chosen over the alternatives for handwritten coursework specifically:
Tesseract is poor at handwriting, and GOT-OCR needs a ~2GB weight download and
is impractical CPU-only. Gemini already backs every other AI path in the app,
handles handwritten mathematics, and returns LaTeX.

The transcription itself is a Pydantic AI agent (`agents/ocr_vision.py`), not a
raw `genai.Client` call: one call per scanned page makes this the largest
per-document LLM spend in the app, and only a pydantic-ai run gets token/cost
attribution from Logfire's `instrument_pydantic_ai()` (ADR 0008). This module
keeps the gate, the run, and the blank-page mapping; the agent owns the prompt
and the model slot.

**Off by default** (`GEMINI_VISION_OCR_ENABLED`): it spends one LLM call per
flagged page, so enabling it is a deliberate cost decision. Pages with a normal
text layer are never flagged and so never cost anything.

Note this backend is **not deterministic** — the same image can transcribe
slightly differently across runs. See `extraction_service` for why that matters
to content-addressed chunk ids.
"""
import asyncio
import contextvars
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Coroutine

from pydantic_ai import BinaryContent
from pydantic_ai.exceptions import UnexpectedModelBehavior

from agents import WORKER_LIMITS
from agents._providers import model_name_for
from agents._run import run_agent_sync
from agents.ocr_vision import (
    BLANK_PAGE_SENTINEL,
    TRANSCRIBE_PROMPT,
    ocr_vision_agent,
)


class GeminiVisionUnavailableError(RuntimeError):
    """Raised when Gemini-vision OCR is disabled or not configured."""


def _enabled() -> bool:
    return os.getenv("GEMINI_VISION_OCR_ENABLED", "false").lower() == "true"


def _run_from_anywhere(coro: Coroutine[Any, Any, Any]) -> Any:
    """Drive an agent coroutine to completion from this synchronous seam.

    `run_agent_sync` (asyncio.run) is the house helper, but it requires a
    thread with no running loop — and the extraction stack is reached BOTH
    ways: off the loop via `asyncio.to_thread` in the streaming upload path,
    and directly on the loop from the `async def` handlers that call
    `_extract_text_or_422` / `extract_assignments_from_file`. On the latter
    `asyncio.run` raises, and `_apply_gemini_vision_fallback`'s per-page
    `except Exception: continue` would swallow it — silently turning vision
    OCR into a no-op on the main upload path.

    So when a loop is already running here, hand the coroutine to a worker
    thread that gets its own. The calling thread blocks for the duration —
    exactly as it did when this was a synchronous `genai.Client` call — so
    this is not a new loop-blocking regression, just the old one preserved.
    The context is copied across so `agent.override(...)` (tests) and the
    active OTel/Logfire span (tracing) survive the hop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run_agent_sync(coro)

    ctx = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(ctx.run, asyncio.run, coro).result()


def vision_model_name() -> str:
    """The model that would transcribe a page right now.

    Public because the OCR cache key must include it: the model changes the
    transcription, so a cache entry produced by one model must not be served
    after an operator switches to another.

    Resolved through the ADR-0008 per-task router, so the knob is
    `SAPLING_MODEL_OCR_VISION` like every other agent's. (The
    `GEMINI_VISION_OCR_MODEL` env var from this feature's first draft was a
    competing knob that bypassed the router and never shipped; it is gone.)
    """
    return model_name_for("ocr_vision")


def extract_page_with_gemini_vision(image_bytes: bytes) -> str:
    """Transcribe one rendered page image. Returns "" for a blank page.

    Raises GeminiVisionUnavailableError when disabled or unconfigured, so the
    caller can stop trying further pages. Any other exception (quota, network,
    UsageLimitExceeded) propagates for the caller to handle per page.

    Bounded by WORKER_LIMITS: this runs in a per-page loop, so an unbounded run
    would multiply any single runaway page across the whole document.
    """
    if not _enabled():
        raise GeminiVisionUnavailableError("GEMINI_VISION_OCR_ENABLED is not true")
    if not os.getenv("GEMINI_API_KEY"):
        raise GeminiVisionUnavailableError("GEMINI_API_KEY is not set")

    try:
        result = _run_from_anywhere(
            ocr_vision_agent.run(
                # Image first, then the instruction — the wire shape this was
                # measured against. Moving the instruction to a system prompt
                # makes the model emit a whole LaTeX document; see ocr_vision.
                [
                    BinaryContent(data=image_bytes, media_type="image/png"),
                    TRANSCRIBE_PROMPT,
                ],
                usage_limits=WORKER_LIMITS,
            )
        )
    except UnexpectedModelBehavior:
        # The model produced no usable text for this page (empty candidate, a
        # safety block, a response that failed output validation twice). That
        # is a page outcome, not a pipeline error — the pre-agent code returned
        # "" for the same cases, and the caller's `if text:` guard then keeps
        # whatever Docling had. Quota/network errors are NOT this class and
        # still propagate.
        return ""
    text = (result.output or "").strip()
    if text == BLANK_PAGE_SENTINEL:
        return ""
    return text
