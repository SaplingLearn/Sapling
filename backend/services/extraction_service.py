"""OCR and text extraction router.

Public API kept stable for every existing caller. Engine selection happens via
the OCR_ENGINE env var ("docling" default, "auto" for Docling+GOT-OCR fallback,
"tesseract" for legacy behavior).

Pages that yield no usable text (scans, photographed handwriting) are flagged by
the Docling backend as `fallback_pages`. Two optional per-page rescuers consume
that signal: GOT-OCR (OCR_ENGINE=auto + GOT_OCR_ENABLED) and Gemini vision
(GEMINI_VISION_OCR_ENABLED). Both are off by default.

Neither rescuer applies to *every* engine: `fallback_pages` is produced only by
the Docling backend, so an OCR_ENGINE=tesseract run — and any run where Docling
raised and tesseract took over — has no per-page signal to rescue. The real
scope is "docling or auto, and Docling succeeded". When both rescuers are
enabled they run in sequence, GOT-OCR first (local, free), then vision over the
pages GOT-OCR could not fill.
"""
import hashlib
import io
import logging
import os
from typing import Callable, Tuple

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
    vision_model_name,
)

logger = logging.getLogger(__name__)


def _clean_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.splitlines()).strip()


def _engine() -> str:
    return os.getenv("OCR_ENGINE", "docling").lower()


def _got_ocr_enabled() -> bool:
    return os.getenv("GOT_OCR_ENABLED", "false").lower() == "true"


def _gemini_vision_enabled() -> bool:
    return os.getenv("GEMINI_VISION_OCR_ENABLED", "false").lower() == "true"


# Per-document ceiling on metered vision transcriptions. One flagged page is one
# LLM call, and nothing upstream bounds how many pages a single document can
# flag: `routes/extract.py` allows up to `min(max_pages, 50)` and the upload path
# in `routes/documents.py` defaults to 20 with no rate limit at all. The #182
# rate limit (10 requests / 60s on /api/extract/*) was sized when a request meant
# one bounded LOCAL OCR run, so it is not a cost control for this. 10 keeps the
# worst case at 10 metered calls per document — enough to carry a typical
# handwritten problem set into the classify prompt, low enough that a mass upload
# cannot quietly run up a bill. Operators who want a whole 20-page scan
# transcribed raise it deliberately.
_DEFAULT_VISION_MAX_PAGES = 10


def _gemini_vision_max_pages() -> int:
    raw = os.getenv("GEMINI_VISION_OCR_MAX_PAGES", "").strip()
    if not raw:
        return _DEFAULT_VISION_MAX_PAGES
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning(
            "GEMINI_VISION_OCR_MAX_PAGES=%r is not an integer; using %d",
            raw,
            _DEFAULT_VISION_MAX_PAGES,
        )
        return _DEFAULT_VISION_MAX_PAGES


def _capped_vision_pages(pages: list) -> list:
    """Trim the vision worklist to the per-document cap, saying so out loud.

    A silent cap reads downstream as "we OCR'd the whole document" when we did
    not, so the pages left behind are named in the log.
    """
    cap = _gemini_vision_max_pages()
    pages = list(pages)
    if len(pages) <= cap:
        return pages
    logger.warning(
        "Gemini vision OCR capped at %d of %d page(s) needing transcription; "
        "%d page(s) left as Docling extracted them "
        "(raise GEMINI_VISION_OCR_MAX_PAGES to transcribe more)",
        cap,
        len(pages),
        len(pages) - cap,
    )
    return pages[:cap]


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

    per_page = list(metadata.get("per_page_markdown") or [])
    flagged = list(metadata.get("fallback_pages") or [])
    if flagged and per_page:
        rescued: set = set()
        rewritten = False

        # GOT-OCR keeps its original gate so existing deployments are unchanged.
        if engine == "auto" and _got_ocr_enabled():
            result = _apply_got_ocr_fallback(pdf_bytes, per_page, flagged)
            if result is not None:
                per_page, rescued = result
                rewritten = True

        # Gemini vision is deliberately NOT gated on engine == "auto". That gate
        # was why the signal was useless in practice: the default engine is
        # "docling", so flagged pages were detected and then silently dropped.
        #
        # It runs AFTER GOT-OCR rather than instead of it. As an `elif`, enabling
        # both meant vision never ran at all — including on the pages GOT-OCR
        # failed to fill, which recreates the exact "signal computed then
        # dropped" bug this code exists to fix. GOT-OCR goes first because it is
        # local and free; vision only sees what it left unrescued, so nothing is
        # transcribed (or paid for) twice.
        if _gemini_vision_enabled():
            pending = [idx for idx in flagged if idx not in rescued]
            result = _apply_gemini_vision_fallback(pdf_bytes, per_page, pending)
            if result is not None:
                per_page, _ = result
                rewritten = True

        if rewritten:
            markdown = _join_pages(per_page)

    return markdown, page_count


def _join_pages(per_page: list) -> str:
    return "\n\n".join(md for md in per_page if md).strip()


def _rescue_flagged_pages(
    pdf_bytes: bytes,
    per_page: list,
    pages: list,
    transcribe: Callable[[bytes], str],
    unavailable_error: type,
) -> tuple | None:
    """Re-transcribe `pages` with `transcribe`, leaving every other page alone.

    Shared by both rescuers so they can run in sequence over one per-page list.
    The second stage has to know which pages the first one actually filled, and
    a joined-markdown return value cannot express that — hence the explicit
    (per-page markdown, indices replaced) pair. Returns None when the rescuer
    could not run at all (no pypdfium2, unreadable PDF), in which case the caller
    keeps the markdown it already had.

    A per-page error keeps whatever Docling produced for that page (better a
    partial document than none), while an unavailability error aborts the loop,
    since misconfiguration will not fix itself on page 2 and a long scan would
    otherwise burn a failed call per page.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None

    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
    except Exception:
        return None

    per_page = list(per_page)
    rescued: set = set()
    for idx in pages:
        if idx >= len(pdf) or idx >= len(per_page):
            continue
        try:
            page = pdf[idx]
            pil = page.render(scale=2).to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            page.close()
            text = transcribe(buf.getvalue())
            if text:
                per_page[idx] = text
                rescued.add(idx)
        except unavailable_error:
            break
        except Exception:
            continue

    return per_page, rescued


def _apply_got_ocr_fallback(pdf_bytes: bytes, per_page: list, pages: list) -> tuple | None:
    """GOT-OCR stage: local OCR over the pages Docling flagged.

    Behavior is unchanged from when this owned its own loop — same gate, same
    pages, same per-page/unavailable error handling. Only the return shape moved,
    from a joined document to (per-page markdown, indices replaced), so the
    vision stage can run after it on the pages it did not fill.
    """
    return _rescue_flagged_pages(
        pdf_bytes,
        per_page,
        pages,
        lambda image: extract_page_with_got_ocr(image, ocr_type="format"),
        GotOcrUnavailableError,
    )


def _apply_gemini_vision_fallback(
    pdf_bytes: bytes, per_page: list, pages: list
) -> tuple | None:
    """Vision stage: re-transcribe still-empty pages, leaving others untouched.

    Capped at GEMINI_VISION_OCR_MAX_PAGES pages per document — every page here
    is a metered LLM call, and how many there are is decided by the uploaded
    file, not by anything this process controls.
    """
    pages = _capped_vision_pages(pages)
    if not pages:
        return None
    return _rescue_flagged_pages(
        pdf_bytes,
        per_page,
        pages,
        lambda image: extract_page_with_gemini_vision(image),
        GeminiVisionUnavailableError,
    )


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
# degrades to a clean miss, so stability must not be *depended* on.
#
# Today that instability is invisible downstream: `rag_service` derives chunk ids
# from f"{doc_id}::{i}::{chunk_text}" with a fresh uuid4 doc_id per upload, so
# two uploads of the same scan never dedup no matter how identically they
# transcribe. It starts to matter under PR #352, which re-keys chunk ids on
# f"{course_code}::{chunk_text}" — from then on, two students uploading the same
# scanned handout collapse into one embedding only if the transcriptions match.
# Persisting OCR output content-addressed, rather than merely caching it, is the
# real fix and is not attempted here.
_OCR_CACHE_TTL = 30 * 24 * 3600  # 30 days


def _ocr_cache_key(file_bytes: bytes) -> str:
    """Content-addressed cache key for an extraction.

    Carries the engine and both rescuer flags, so flipping a rescuer on cannot
    return text produced while it was off — otherwise enabling vision OCR would
    keep serving the empty string cached from before it existed. With vision on
    it also carries the vision model and the per-document page cap, both of which
    change the transcription.

    Deliberately not exhaustive: GOT_OCR_MODEL_PATH also changes the output and
    is NOT in the key, so swapping GOT-OCR weights keeps serving the old weights'
    text for the rest of the 30-day TTL. The vision knobs are likewise mixed in
    only while vision is enabled — both omissions exist to avoid invalidating
    every entry of the configurations that do not use those knobs.
    """
    key = (
        f"ocr:{hashlib.sha256(file_bytes).hexdigest()}"
        f":{_engine()}:{_got_ocr_enabled()}:{_gemini_vision_enabled()}"
    )
    if _gemini_vision_enabled():
        key += f":{vision_model_name()}:{_gemini_vision_max_pages()}"
    return key


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
