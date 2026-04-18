"""OCR and text extraction router.

Public API kept stable for every existing caller. Engine selection happens via
the OCR_ENGINE env var ("docling" default, "auto" for Docling+GOT-OCR fallback,
"tesseract" for legacy behavior).
"""
import io
import os
from typing import Tuple

from pypdf import PdfReader

from services.extraction_backends import tesseract_backend
from services.extraction_backends.docling_backend import (
    DoclingUnavailableError,
    extract_pdf_with_docling,
)
from services.extraction_backends.got_ocr_backend import (
    GotOcrUnavailableError,
    extract_page_with_got_ocr,
)


def _clean_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.splitlines()).strip()


def _engine() -> str:
    return os.getenv("OCR_ENGINE", "docling").lower()


def _got_ocr_enabled() -> bool:
    return os.getenv("GOT_OCR_ENABLED", "false").lower() == "true"


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

    if engine == "auto" and _got_ocr_enabled() and metadata.get("fallback_pages"):
        markdown = _apply_got_ocr_fallback(pdf_bytes, markdown, metadata)

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


def extract_text_from_docx(file_bytes: bytes) -> str:
    return tesseract_backend.extract_text_from_docx_impl(file_bytes)


def extract_text_from_pptx(file_bytes: bytes) -> str:
    return tesseract_backend.extract_text_from_pptx_impl(file_bytes)


def extract_text_from_file(file_bytes: bytes, filename: str, content_type: str) -> str:
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
