"""OCR and text extraction router.

Public API kept stable for every existing caller. Engine selection happens via
the OCR_ENGINE env var ("docling" default, "auto" for Docling+GOT-OCR fallback,
"tesseract" for legacy behavior).

Pages that yield no usable text (scans, photographed handwriting) are flagged by
the Docling backend as `fallback_pages`. Two optional per-page rescuers consume
that signal: GOT-OCR (OCR_ENGINE=auto + GOT_OCR_ENABLED) and Gemini vision
(GEMINI_VISION_OCR_ENABLED, any engine). Both are off by default.
"""
import hashlib
import io
import os
from typing import Tuple

from pypdf import PdfReader

from services import cache
from services.extraction_backends import tesseract_backend
from services.extraction_backends.docling_backend import (
    DoclingUnavailableError,
    extract_pdf_with_docling,
)
from services.extraction_backends.got_ocr_backend import (
    GotOcrUnavailableError,
    extract_page_with_got_ocr,
)
from services.extraction_backends.gemini_vision_backend import (
    GeminiVisionUnavailableError,
    extract_page_with_gemini_vision,
)


def _clean_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.splitlines()).strip()


def _engine() -> str:
    return os.getenv("OCR_ENGINE", "docling").lower()


def _got_ocr_enabled() -> bool:
    return os.getenv("GOT_OCR_ENABLED", "false").lower() == "true"


def _gemini_vision_enabled() -> bool:
    return os.getenv("GEMINI_VISION_OCR_ENABLED", "false").lower() == "true"


def extract_text_from_image_bytes(image_bytes: bytes, lang: str = "eng") -> str:
    engine = _engine()
    if engine == "tesseract":
        return tesseract_backend.extract_text_from_image_bytes_impl(image_bytes, lang=lang)

    try:
        text, _, _ = extract_pdf_with_docling(_image_to_pdf_bytes(image_bytes), max_pages=1)
        if text.strip():
            return text
    except DoclingUnavailableError:
        pass
    except Exception:
        pass

    return tesseract_backend.extract_text_from_image_bytes_impl(image_bytes, lang=lang)


def _image_to_pdf_bytes(image_bytes: bytes) -> bytes:
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


def extract_text_from_pdf_native(pdf_bytes: bytes, max_pages: int = 50) -> Tuple[str, int]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_count = min(len(reader.pages), max_pages)
    chunks = []
    for i in range(page_count):
        chunks.append(reader.pages[i].extract_text() or "")
    return _clean_text("\n\n".join(chunks)), page_count


def extract_text_from_pdf_ocr(
    pdf_bytes: bytes, max_pages: int = 20, lang: str = "eng"
) -> Tuple[str, int]:
    engine = _engine()

    if engine == "tesseract":
        return tesseract_backend.extract_text_from_pdf_ocr_impl(pdf_bytes, max_pages=max_pages, lang=lang)

    try:
        markdown, page_count, metadata = extract_pdf_with_docling(pdf_bytes, max_pages=max_pages)
    except DoclingUnavailableError as e:
        try:
            return tesseract_backend.extract_text_from_pdf_ocr_impl(pdf_bytes, max_pages=max_pages, lang=lang)
        except Exception as tess_err:
            raise RuntimeError(f"Docling unavailable ({e}) and tesseract fallback failed ({tess_err})") from e
    except Exception as e:
        try:
            return tesseract_backend.extract_text_from_pdf_ocr_impl(pdf_bytes, max_pages=max_pages, lang=lang)
        except Exception as tess_err:
            raise RuntimeError(f"Docling failed ({e}) and tesseract fallback failed ({tess_err})") from e

    if metadata.get("fallback_pages"):
        # GOT-OCR keeps its original gate so existing deployments are unchanged.
        if engine == "auto" and _got_ocr_enabled():
            markdown = _apply_got_ocr_fallback(pdf_bytes, markdown, metadata)
        # Gemini vision is deliberately NOT gated on engine == "auto". That gate
        # was why the signal was useless in practice: the default engine is
        # "docling", so flagged pages were detected and then silently dropped.
        elif _gemini_vision_enabled():
            markdown = _apply_gemini_vision_fallback(pdf_bytes, markdown, metadata)

    return markdown, page_count


def _apply_got_ocr_fallback(pdf_bytes: bytes, base_markdown: str, metadata: dict) -> str:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return base_markdown

    per_page = list(metadata.get("per_page_markdown", []))
    fallback_pages = metadata.get("fallback_pages", [])
    if not per_page or not fallback_pages:
        return base_markdown

    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
    except Exception:
        return base_markdown

    for idx in fallback_pages:
        if idx >= len(pdf) or idx >= len(per_page):
            continue
        try:
            page = pdf[idx]
            pil = page.render(scale=2).to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            page.close()
            got_text = extract_page_with_got_ocr(buf.getvalue(), ocr_type="format")
            if got_text:
                per_page[idx] = got_text
        except GotOcrUnavailableError:
            break
        except Exception:
            continue

    return "\n\n".join(md for md in per_page if md).strip()


def _apply_gemini_vision_fallback(
    pdf_bytes: bytes, base_markdown: str, metadata: dict
) -> str:
    """Re-transcribe flagged pages with Gemini vision, leaving others untouched.

    Mirrors _apply_got_ocr_fallback: a per-page error keeps whatever Docling
    produced for that page (better a partial document than none), while an
    unavailability error aborts the loop, since misconfiguration will not fix
    itself on page 2 and a long scan would otherwise burn a failed call per page.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return base_markdown

    per_page = list(metadata.get("per_page_markdown", []))
    fallback_pages = metadata.get("fallback_pages", [])
    if not per_page or not fallback_pages:
        return base_markdown

    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
    except Exception:
        return base_markdown

    for idx in fallback_pages:
        if idx >= len(pdf) or idx >= len(per_page):
            continue
        try:
            page = pdf[idx]
            pil = page.render(scale=2).to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            page.close()
            text = extract_page_with_gemini_vision(buf.getvalue())
            if text:
                per_page[idx] = text
        except GeminiVisionUnavailableError:
            break
        except Exception:
            continue

    return "\n\n".join(md for md in per_page if md).strip()


def extract_text_from_docx(file_bytes: bytes) -> str:
    return tesseract_backend.extract_text_from_docx_impl(file_bytes)


def extract_text_from_pptx(file_bytes: bytes) -> str:
    return tesseract_backend.extract_text_from_pptx_impl(file_bytes)


# Cached extractions can live a long time: the same file bytes produce the same
# text for a given engine config.
#
# Caveat now that Gemini vision can transcribe pages: that step is NOT
# deterministic, so two runs over the same scan can differ slightly. A cache hit
# is what keeps them stable — but `services/cache.py` is off by default and
# degrades to a clean miss, so stability must not be *depended* on. It matters
# because content-addressed chunk ids (ADR 0019) dedup on chunk text: two
# students uploading the same scanned handout only collapse into one embedding
# if they transcribe identically. Persisting OCR output content-addressed, rather
# than merely caching it, is the real fix and is not attempted here.
_OCR_CACHE_TTL = 30 * 24 * 3600  # 30 days


def _ocr_cache_key(file_bytes: bytes) -> str:
    """Content-addressed cache key for an extraction.

    Includes every flag that changes the output, so flipping a rescuer on cannot
    return text produced while it was off — otherwise enabling vision OCR would
    keep serving the empty string cached from before it existed.
    """
    return (
        f"ocr:{hashlib.sha256(file_bytes).hexdigest()}"
        f":{_engine()}:{_got_ocr_enabled()}:{_gemini_vision_enabled()}"
    )


def extract_text_from_file(file_bytes: bytes, filename: str, content_type: str) -> str:
    """Extract raw text from a PDF, DOCX, PPTX, plain-text, or image file.

    Content-addressed cache (#97): re-extracting the same bytes (re-uploads,
    retries, resubmissions) is a Redis hit instead of a full OCR run. Keyed on
    sha256(file_bytes) + the engine config, so a different engine or a changed
    file misses. No-op (and no hashing cost) when Redis isn't configured."""
    if not cache.enabled():
        return _extract_text_from_file_uncached(file_bytes, filename, content_type)
    key = _ocr_cache_key(file_bytes)
    hit = cache.get_str(key)
    if hit is not None:
        return hit
    text = _extract_text_from_file_uncached(file_bytes, filename, content_type)
    cache.set_str(key, text, ttl_seconds=_OCR_CACHE_TTL)
    return text


def _extract_text_from_file_uncached(file_bytes: bytes, filename: str, content_type: str) -> str:
    """Extract raw text from a PDF, DOCX, PPTX, plain-text, or image file."""
    lower = filename.lower()
    if content_type == "text/plain" or lower.endswith(".txt"):
        return _clean_text(file_bytes.decode("utf-8", errors="replace"))
    if content_type == "application/pdf" or lower.endswith(".pdf"):
        try:
            text, _ = extract_text_from_pdf_native(file_bytes)
            if len(text) >= 50:
                return text
        except Exception:
            pass
        text, _ = extract_text_from_pdf_ocr(file_bytes)
        return text
    if lower.endswith(".docx") or content_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        return extract_text_from_docx(file_bytes)
    if lower.endswith(".pptx") or content_type in (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ):
        return extract_text_from_pptx(file_bytes)
    else:
        return extract_text_from_image_bytes(file_bytes)
