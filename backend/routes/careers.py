import re
import uuid

import httpx
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Optional

from db.connection import SUPABASE_URL, SUPABASE_KEY, table

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

router = APIRouter()


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


def _upload_resume(file: UploadFile, content: bytes) -> str:
    """Upload a validated resume to Supabase Storage and return the path."""
    ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "pdf"
    path = f"{uuid.uuid4()}.{ext}"
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}"
    r = httpx.put(
        url,
        content=content,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": file.content_type or "application/pdf",
        },
    )
    r.raise_for_status()
    return path


@router.post("/apply")
async def apply(
    position: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    linkedin_url: str = Form(...),
    phone: str = Form(""),
    portfolio_link: str = Form(""),
    resume: Optional[UploadFile] = File(None),
):
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

    row = table("job_applications").insert({
        "position": position,
        "full_name": full_name,
        "email": email,
        "phone": (phone or "").strip() or None,
        "linkedin_url": linkedin_url,
        "portfolio_link": (portfolio_link or "").strip() or None,
        "resume": resume_path,
    })
    return {"ok": True, "id": row[0]["id"] if row else None}
