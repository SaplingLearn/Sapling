import logging
import re
import uuid

import httpx
from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from typing import Optional

from db.connection import SUPABASE_URL, SUPABASE_KEY, table
from services.client_ip import client_ip
from services.request_limits import check_rate_limit

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
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# /apply is public by design, so it is an UNAUTHENTICATED write sink: every
# call inserts a `job_applications` row and can PUT a 5 MB object into the
# resumes bucket. Size and type were already bounded (#199) but call RATE was
# not, so one script could fill the table and the bucket unattended. There is
# no user id to key on here (see services/client_ip.py's caveat about what an
# IP is and is not good for) — this is abuse dampening, not authorization.
_APPLY_RATE_LIMIT = 5     # applications...
_APPLY_RATE_WINDOW = 3600  # ...per hour, per caller

# Storage object keys are built from the uploaded filename's extension. Bound
# it: the raw value is attacker-controlled and ends up in a URL path.
MAX_EXT_LEN = 10
_EXT_RE = re.compile(r"^[A-Za-z0-9]+$")

router = APIRouter()


def _enforce_apply_limit(request: Request) -> None:
    retry = check_rate_limit(
        f"careers-apply:{client_ip(request)}",
        limit=_APPLY_RATE_LIMIT,
        window_sec=_APPLY_RATE_WINDOW,
    )
    if retry is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many applications submitted. Please try again later.",
            headers={"Retry-After": str(retry)},
        )


def _validate_resume(file: UploadFile) -> bytes:
    """Enforce content-type + size bounds and return the file bytes.

    Reads at most MAX_RESUME_SIZE + 1 bytes so an oversize upload can't be
    pulled fully into memory before we reject it.
    """
    if (file.content_type or "") not in ALLOWED_RESUME_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported resume type. Allowed: PDF, DOC, DOCX.",
        )
    content = file.file.read(MAX_RESUME_SIZE + 1)
    if len(content) > MAX_RESUME_SIZE:
        raise HTTPException(status_code=413, detail="Resume too large. Maximum size is 5 MB.")
    if not content:
        raise HTTPException(status_code=400, detail="Resume file is empty.")
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
        )
    return path


# #117: a plain `def` -- FastAPI runs it in the threadpool once, so the
# spooled-file read (`file.file.read`), the Storage PUT and the insert never
# block the event loop. The form is parsed before the handler runs.
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
    _enforce_apply_limit(request)
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
        )
    return {"ok": True, "id": row[0]["id"] if row else None}
