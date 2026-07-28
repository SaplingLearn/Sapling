"""Page-image OCR agent.

Transcribes one rendered page image — a scan or a photo of handwritten work —
that carries no extractable text layer. Backs
`services/extraction_backends/gemini_vision_backend.py`, which owns the
enablement gate and the image rendering; this module owns the prompt, the
model slot, and the output contract.

Toolless and user-agnostic, like `course_summary`/`quiz_context`/`flashcard`:
the extraction seam (`extract_page_with_gemini_vision(image_bytes)`) has no
user or course in scope, so there is no `SaplingDeps` to thread and the agent
is typed `Agent[None, str]` rather than faking one.

Why an agent rather than a raw `genai.Client` call: this is the single most
expensive LLM call per document (one call per scanned page), and only a
pydantic-ai run is visible to Logfire's `instrument_pydantic_ai()` token/cost
attribution (ADR 0008). A raw client call would be the one spend the cost
dashboard cannot see. Model selection likewise goes through
`_providers.model_for` so `SAPLING_MODEL_OCR_VISION` is the only knob.
"""

from __future__ import annotations

import hashlib

from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModelSettings

from agents._providers import _model_mode, model_for, model_name_for


# The model is asked to return this verbatim for an empty page. Public because
# the backend maps it to "" — the sentinel must never become indexed course
# material — and the mapping has to agree with the prompt that produces it.
BLANK_PAGE_SENTINEL = "[BLANK PAGE]"


# Sent as the USER turn, next to the image — deliberately NOT as system_prompt.
#
# Measured against a rasterized syllabus (known ground truth): as a system
# prompt, "Use LaTeX for mathematics" reads as a document-format directive and
# gemini-2.5-flash returns a whole LaTeX FILE — \documentclass, five \usepackage
# lines, \begin{document}, a tabular. 743 chars for a page whose content is 358.
# The same prompt in the user turn returns clean Markdown, which is what the
# rest of the pipeline expects.
#
# That preamble is not cosmetic: extracted_text feeds the classify/summary/
# concept prompts and is chunked into course_chunks for RAG, so "amsmath" and
# "booktabs" become candidate concepts on a graph shared by every student in
# the course — the same class of pollution this whole feature exists to stop.
TRANSCRIBE_PROMPT = (
    "Transcribe ALL content from this document page exactly as written, "
    "including handwritten work. Use LaTeX for mathematics ($...$ inline, "
    "$$...$$ display). Preserve problem numbers, part labels, and reading "
    "order. Do not solve, explain, summarize, or add commentary — transcribe "
    "only what is present. If the page is genuinely blank, reply with exactly: "
    f"{BLANK_PAGE_SENTINEL}"
)
_PROMPT_HASH = hashlib.sha256(TRANSCRIBE_PROMPT.encode("utf-8")).hexdigest()[:12]


# Bounded on purpose: this runs inside the upload pipeline, so a stalled call
# must not hang the request indefinitely. `ModelSettings.timeout` is seconds;
# GoogleModel converts it to the google-genai HttpOptions timeout in ms.
_OCR_VISION_SETTINGS = GoogleModelSettings(timeout=60.0)


ocr_vision_agent = Agent[None, str](
    model=model_for("ocr_vision"),
    output_type=str,
    model_settings=_OCR_VISION_SETTINGS,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "ocr_vision"},
)


def fresh_ocr_vision_model():
    """A model bound to no prior event loop, for one `run_agent_sync` call.

    `_providers._provider` is a module-level GoogleProvider, so its async httpx
    client binds to the first loop `asyncio.run` creates and dies with it:
    call 1 succeeds, call 2 raises `RuntimeError: Event loop is closed`,
    call 3 succeeds. Measured exactly that way against the live API.

    Every `run_agent_sync` caller shares this (#354; the sweep is open in PR
    #358), but transcription is the only one that runs in a LOOP — a 10-page
    scan alternates success/failure page by page, and
    `_apply_gemini_vision_fallback`'s per-page `except Exception: continue`
    keeps Docling's text without a word, so half a document silently degrades.
    That is the difference between a latent bug and an unusable feature, which
    is why this path does not wait for #358.

    Scoped deliberately: a fresh provider for THIS agent's runs only, passed as
    a per-run `model=` override. It leaves the shared `_provider` untouched, so
    it cannot conflict with whatever #358 lands.

    Returns None when SAPLING_MODEL_MODE is not 'real' — the FunctionModel seam
    builds no client, has no loop affinity, and must not be overridden.
    """
    if _model_mode() != "real":
        return None
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    from config import GEMINI_API_KEY

    return GoogleModel(
        model_name_for("ocr_vision"),
        provider=GoogleProvider(api_key=GEMINI_API_KEY or "dummy-key-for-import"),
    )
