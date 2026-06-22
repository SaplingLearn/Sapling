import os
import sys

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile

from services.extraction_service import (
    extract_text_from_image_bytes,
    extract_text_from_pdf_native,
    extract_text_from_pdf_ocr,
)
from services.extraction_backends.docling_backend import docling_available
from services.extraction_backends.got_ocr_backend import got_ocr_available
from services.extraction_backends.tesseract_backend import tesseract_available
from services.auth_guard import get_session_user_id
from services.request_limits import check_rate_limit, read_within_limit

router = APIRouter()

# #182: these endpoints run multi-second Docling/tesseract OCR. They were
# unauthenticated, unbounded, and unthrottled — an anonymous caller could drive
# unbounded OCR load/cost. Require a session, cap upload size, and rate-limit.
MAX_OCR_BYTES = 20 * 1024 * 1024  # 20 MB
_OCR_RATE_LIMIT = 10              # requests...
_OCR_RATE_WINDOW = 60             # ...per 60s, per user


def _enforce_ocr_limits(request: Request) -> str:
    """Require an authenticated session (401) and a per-user rate limit (429).
    Returns the authenticated user_id."""
    user_id = get_session_user_id(request)
    retry = check_rate_limit(f"ocr:{user_id}", limit=_OCR_RATE_LIMIT, window_sec=_OCR_RATE_WINDOW)
    if retry is not None:
        # NB: the app's global HTTPException handler (main.py) doesn't forward
        # exc.headers, so the retry budget is conveyed in the detail string
        # rather than a Retry-After header.
        raise HTTPException(
            status_code=429,
            detail=f"Too many OCR requests. Retry in {retry}s.",
        )
    return user_id


def _ocr_unavailable_error(detail: str) -> HTTPException:
    """Log OCR error to terminal and return a 503 the frontend can display."""
    print(f"\n[OCR UNAVAILABLE] {detail}", file=sys.stderr)
    print("[OCR UNAVAILABLE] Install tesseract-ocr to enable OCR features.\n", file=sys.stderr)
    return HTTPException(
        status_code=503,
        detail=f"OCR not available on this machine: {detail}. Install tesseract-ocr to enable PDF/image scanning.",
    )

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
ALLOWED_PDF_TYPES = {"application/pdf"}


@router.get("/health")
def extraction_health():
    tess_ok, tess_ver = tesseract_available()
    docling_ok, docling_ver = docling_available()
    return {
        "tesseract_available": tess_ok,
        "tesseract_version": tess_ver,
        "docling_available": docling_ok,
        "docling_version": docling_ver,
        "got_ocr_available": got_ocr_available(),
        "active_engine": os.getenv("OCR_ENGINE", "docling").lower(),
    }


@router.post("/pdf")
async def extract_pdf(
    request: Request,
    file: UploadFile = File(...),
    force_ocr: bool = Query(False),
    max_pages: int = Query(25, ge=1, le=200),
    lang: str = Query("eng"),
):
    _enforce_ocr_limits(request)  # 401 unauthenticated, 429 rate-limited (#182)
    if file.content_type not in ALLOWED_PDF_TYPES:
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    pdf_bytes = await read_within_limit(file, MAX_OCR_BYTES)  # 413 if oversize (#182)
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    warnings = []
    text = ""
    page_count = 0
    method = "pdf_text"

    if not force_ocr:
        try:
            text, page_count = extract_text_from_pdf_native(pdf_bytes, max_pages=max_pages)
        except Exception as e:
            warnings.append(f"Native extraction failed: {e}")

    if force_ocr or len(text) < 50:
        try:
            text, page_count = extract_text_from_pdf_ocr(
                pdf_bytes, max_pages=min(max_pages, 50), lang=lang
            )
            method = "pdf_ocr"
            if not force_ocr and text:
                warnings.append("Native text was short; OCR fallback used")
        except RuntimeError as e:
            raise _ocr_unavailable_error(str(e))
        except Exception as e:
            # Tesseract binary missing raises TesseractNotFoundError (an OSError subclass)
            err = str(e)
            if "tesseract" in err.lower() or "not found" in err.lower():
                raise _ocr_unavailable_error(err)
            raise HTTPException(status_code=500, detail=f"PDF OCR failed: {e}")

    return {
        "source_type": "pdf",
        "method": method,
        "text": text,
        "warnings": warnings,
        "metadata": {"filename": file.filename, "pages_processed": page_count},
    }


@router.post("/image")
async def extract_image(
    request: Request,
    file: UploadFile = File(...),
    lang: str = Query("eng"),
):
    _enforce_ocr_limits(request)  # 401 unauthenticated, 429 rate-limited (#182)
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only PNG/JPG/WEBP images are supported")
    image_bytes = await read_within_limit(file, MAX_OCR_BYTES)  # 413 if oversize (#182)
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        text = extract_text_from_image_bytes(image_bytes, lang=lang)
        return {
            "source_type": "image",
            "method": "image_ocr",
            "text": text,
            "warnings": [] if text else ["No text found in image"],
            "metadata": {"filename": file.filename},
        }
    except RuntimeError as e:
        raise _ocr_unavailable_error(str(e))
    except Exception as e:
        err = str(e)
        if "tesseract" in err.lower() or "not found" in err.lower():
            raise _ocr_unavailable_error(err)
        raise HTTPException(status_code=500, detail=f"Image extraction failed: {e}")
