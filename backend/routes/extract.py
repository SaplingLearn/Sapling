import logging
import os
import sys

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from starlette.concurrency import run_in_threadpool

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
from services.request_context import current_request_id
from services.upload_validation import PDF, sniff_image, sniff_type

logger = logging.getLogger(__name__)

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
        # main.py's HTTPException handler forwards exc.headers as of #544, so
        # the budget rides in a real Retry-After. It stays in the detail
        # string too — clients that only surface the message keep working.
        raise HTTPException(
            status_code=429,
            detail=f"Too many OCR requests. Retry in {retry}s.",
            headers={"Retry-After": str(retry)},
        )
    return user_id


#: What a client reads when OCR is not installed or a run fails. Never the
#: exception text (it names binaries, paths and library internals); that is
#: logged under the request id.
OCR_UNAVAILABLE_DETAIL = "Text scanning isn't available right now. Try again later."
PDF_OCR_FAILED_DETAIL = "We couldn't read text from this PDF. Try a different file."
IMAGE_OCR_FAILED_DETAIL = "We couldn't read text from this image. Try a different file."


def _ocr_unavailable_error(detail: str) -> HTTPException:
    """Log the OCR error server-side and return a generic 503."""
    logger.warning("OCR unavailable [request_id=%s]: %s", current_request_id(), detail)
    print("[OCR UNAVAILABLE] Install tesseract-ocr to enable OCR features.", file=sys.stderr)
    return HTTPException(status_code=503, detail=OCR_UNAVAILABLE_DETAIL)

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
    # #182: 401 unauthenticated, 429 rate-limited. Off the loop (#117): the
    # session check can read the account and the limiter can be a DB call.
    await run_in_threadpool(_enforce_ocr_limits, request)
    if file.content_type not in ALLOWED_PDF_TYPES:
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    pdf_bytes = await read_within_limit(file, MAX_OCR_BYTES)  # 413 if oversize (#182)
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    if sniff_type(pdf_bytes) != PDF:  # the bytes, not the declared type
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    warnings = []
    text = ""
    page_count = 0
    method = "pdf_text"

    if not force_ocr:
        try:
            text, page_count = extract_text_from_pdf_native(pdf_bytes, max_pages=max_pages)
        except Exception:
            logger.warning("native PDF extraction failed [request_id=%s]",
                           current_request_id(), exc_info=True)
            warnings.append("Native text extraction failed; scanned the pages instead.")

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
            logger.exception("PDF OCR failed [request_id=%s]", current_request_id())
            raise HTTPException(status_code=500, detail=PDF_OCR_FAILED_DETAIL)

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
    # #182: 401 unauthenticated, 429 rate-limited. Off the loop (#117): the
    # session check can read the account and the limiter can be a DB call.
    await run_in_threadpool(_enforce_ocr_limits, request)
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only PNG/JPG/WEBP images are supported")
    image_bytes = await read_within_limit(file, MAX_OCR_BYTES)  # 413 if oversize (#182)
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    if sniff_image(image_bytes) not in ALLOWED_IMAGE_TYPES:  # the bytes, not the declared type
        raise HTTPException(status_code=400, detail="Only PNG/JPG/WEBP images are supported")

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
        logger.exception("image OCR failed [request_id=%s]", current_request_id())
        raise HTTPException(status_code=500, detail=IMAGE_OCR_FAILED_DETAIL)
