import logging
import re
import uuid

import httpx
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from typing import Optional

from db.connection import SUPABASE_URL, SUPABASE_KEY, table
from services import abuse_limits
from services.request_limits import enforce_abuse_limit, public_route_limit, read_within_limit_sync
from services.upload_validation import DOCX, PDF, sniff_type

logger = logging.getLogger("careers")

BUCKET = "application_resumes"

# /apply is intentionally public (anyone can apply), so the upload path must be
# bounded — otherwise it's an unauthenticated, unbounded upload + DB-write sink
# (#199). Cap size and restrict to document types, mirroring storage_service's
# avatar validation (415 unsupported / 413 too large).
MAX_RESUME_SIZE = 5 * 1024 * 1024  # 5 MB
ALLOWED_RESUME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
#: Legacy Word (.doc) files are OLE2 compound documents.
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Storage object keys are built from the uploaded filename's extension. Bound
# it: the raw value is attacker-controlled and ends up in a URL path.
MAX_EXT_LEN = 10
_EXT_RE = re.compile(r"^[A-Za-z0-9]+$")

router = APIRouter()


def _validate_resume(file: UploadFile) -> bytes:
    """Enforce content-type + size bounds and return the file bytes.

    Reads through the shared capped reader, which stops one chunk past
    MAX_RESUME_SIZE, so an oversize upload is never pulled into memory whole.
    """
    if (file.content_type or "") not in ALLOWED_RESUME_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported resume type. Allowed: PDF, DOC, DOCX.",
        )
    content = read_within_limit_sync(
        file, MAX_RESUME_SIZE, status_code=413, detail="Resume too large. Maximum size is 5 MB.",
    )
    if not content:
        raise HTTPException(status_code=400, detail="Resume file is empty.")
    # The declared type is free text: the bytes must be a PDF, a DOCX or an
    # OLE2 (legacy .doc) file too.
    if sniff_type(content) not in (PDF, DOCX) and not content.startswith(_OLE2_MAGIC):
        raise HTTPException(
            status_code=415,
            detail="Unsupported resume type. Allowed: PDF, DOC, DOCX.",
        )
    return content


def _safe_ext(filename: str | None) -> str:
    """The upload's extension, reduced to something safe to put in a URL path.

    The raw value is attacker-controlled and was previously interpolated into
    the Storage object key verbatim, so a crafted filename chose the key's
    shape (slashes, dot segments, unbounded length). Accept a short
    alphanumeric extension or fall back to `pdf`.
    """
    if not filename or "." not in filename:
        return "pdf"
    ext = filename.rsplit(".", 1)[-1].strip().lower()
    if not ext or len(ext) > MAX_EXT_LEN or not _EXT_RE.match(ext):
        return "pdf"
    return ext


def _upload_resume(file: UploadFile, content: bytes) -> str:
    """Upload a validated resume to Supabase Storage and return the path."""
    path = f"{uuid.uuid4()}.{_safe_ext(file.filename)}"
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}"
    try:
        r = httpx.put(
            url,
            content=content,
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": file.content_type or "application/pdf",
            },
            # Without a timeout this blocks a threadpool worker indefinitely
            # when Storage hangs; enough concurrent applications would then
            # starve the pool and stall unrelated requests.
            timeout=30.0,
        )
        r.raise_for_status()
    except httpx.HTTPError:
        # `raise_for_status()` / a transport error used to escape the handler
        # as an unhandled exception, answering 500 and logging a stack trace.
        # It is an upstream failure, not a bug in the request: say so.
        logger.exception("careers: resume upload to Storage failed")
        raise HTTPException(
            status_code=502,
            detail="Could not store the uploaded resume. Please try again later.",
        ) from None
    return path


# #117: a plain `def` -- FastAPI runs it in the threadpool once, so the
# spooled-file read (`read_within_limit_sync`), the Storage PUT and the
# insert never block the event loop. The form is parsed before the handler runs.
@router.post("/apply")
def apply(
    request: Request,
    position: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    linkedin_url: str = Form(...),
    phone: str = Form(""),
    portfolio_link: str = Form(""),
    resume: Optional[UploadFile] = File(None),
):
    # Public: per client address when it is a public one, else a shared ceiling
    # (request_limits.public_route_limit).
    enforce_abuse_limit(*public_route_limit(
        request, abuse_limits.CAREERS_APPLY, abuse_limits.CAREERS_APPLY_SHARED,
    ))
    position = position.strip()
    full_name = full_name.strip()
    email = email.strip()
    linkedin_url = linkedin_url.strip()
    if not position or len(position) > 200:
        raise HTTPException(status_code=422, detail="A valid position is required.")
    if not full_name or len(full_name) > 200:
        raise HTTPException(status_code=422, detail="Full name is required.")
    if not _EMAIL_RE.match(email) or len(email) > 320:
        raise HTTPException(status_code=422, detail="A valid email is required.")
    if not linkedin_url or len(linkedin_url) > 500:
        raise HTTPException(status_code=422, detail="A LinkedIn URL is required.")
    if len(phone or "") > 50:
        raise HTTPException(status_code=422, detail="That phone number is too long.")
    if len(portfolio_link or "") > 500:
        raise HTTPException(status_code=422, detail="That portfolio link is too long.")

    resume_path = None
    if resume is not None and resume.filename:
        content = _validate_resume(resume)
        resume_path = _upload_resume(resume, content)

    try:
        row = table("job_applications").insert({
            "position": position,
            "full_name": full_name,
            "email": email,
            "phone": (phone or "").strip() or None,
            "linkedin_url": linkedin_url,
            "portfolio_link": (portfolio_link or "").strip() or None,
            "resume": resume_path,
        })
    except Exception:
        # Never echo raw PostgREST/driver text to an anonymous caller: it
        # names the host, table and driver (same reasoning as #199 in
        # routes/newsletter.py).
        logger.exception("careers: application insert failed")
        raise HTTPException(
            status_code=500,
            detail="Could not submit your application. Please try again later.",
        ) from None
    return {"ok": True, "id": row[0]["id"] if row else None}
