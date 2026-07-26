"""Gemini-vision OCR for pages with no extractable text layer.

Scans and photographed handwritten work carry no characters to copy out, so
Docling flags those pages (`fallback_pages`) and, with no local OCR engine
installed, returns "" for them. This backend transcribes such a page from a
rendered image instead.

Chosen over the alternatives for handwritten coursework specifically:
Tesseract is poor at handwriting, and GOT-OCR needs a ~2GB weight download and
is impractical CPU-only. Gemini already backs every other AI path in the app,
handles handwritten mathematics, and returns LaTeX.

**Off by default** (`GEMINI_VISION_OCR_ENABLED`): it spends one LLM call per
flagged page, so enabling it is a deliberate cost decision. Pages with a normal
text layer are never flagged and so never cost anything.

Note this backend is **not deterministic** — the same image can transcribe
slightly differently across runs. See `extraction_service` for why that matters
to content-addressed chunk ids.
"""
import os

_TIMEOUT_MS = 60_000
_DEFAULT_MODEL = "gemini-2.5-flash"

# Returned verbatim by the model for an empty page; mapped to "" so the
# sentinel never becomes indexed course material.
_BLANK_SENTINEL = "[BLANK PAGE]"

_PROMPT = (
    "Transcribe ALL content from this document page exactly as written, "
    "including handwritten work. Use LaTeX for mathematics ($...$ inline, "
    "$$...$$ display). Preserve problem numbers, part labels, and reading "
    "order. Do not solve, explain, summarize, or add commentary — transcribe "
    "only what is present. If the page is genuinely blank, reply with exactly: "
    f"{_BLANK_SENTINEL}"
)


class GeminiVisionUnavailableError(RuntimeError):
    """Raised when Gemini-vision OCR is disabled or not configured."""


def _enabled() -> bool:
    return os.getenv("GEMINI_VISION_OCR_ENABLED", "false").lower() == "true"


def _model() -> str:
    return os.getenv("GEMINI_VISION_OCR_MODEL", _DEFAULT_MODEL)


def _client():
    """Build a genai client. Separate function so tests can patch it."""
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError as e:  # pragma: no cover - dependency is in requirements
        raise GeminiVisionUnavailableError(f"google-genai not installed: {e}") from e
    return genai.Client(
        api_key=os.getenv("GEMINI_API_KEY", ""),
        # Bounded: this runs inside the upload pipeline, so a stalled call must
        # not hang the request indefinitely.
        http_options=genai_types.HttpOptions(timeout=_TIMEOUT_MS),
    )


def extract_page_with_gemini_vision(image_bytes: bytes) -> str:
    """Transcribe one rendered page image. Returns "" for a blank page.

    Raises GeminiVisionUnavailableError when disabled or unconfigured, so the
    caller can stop trying further pages. Any other exception (quota, network)
    propagates for the caller to handle per page.
    """
    if not _enabled():
        raise GeminiVisionUnavailableError("GEMINI_VISION_OCR_ENABLED is not true")
    if not os.getenv("GEMINI_API_KEY"):
        raise GeminiVisionUnavailableError("GEMINI_API_KEY is not set")

    from google.genai import types as genai_types

    client = _client()
    resp = client.models.generate_content(
        model=_model(),
        contents=[
            genai_types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            _PROMPT,
        ],
    )
    text = (getattr(resp, "text", None) or "").strip()
    if text == _BLANK_SENTINEL:
        return ""
    return text
