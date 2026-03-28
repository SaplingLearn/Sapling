import uuid

import httpx
from fastapi import APIRouter, UploadFile, File, Form
from typing import Optional

from db.connection import SUPABASE_URL, SUPABASE_KEY, table

BUCKET = "application_resumes"

router = APIRouter()


def _upload_resume(file: UploadFile) -> str:
    """Upload PDF to Supabase Storage and return the storage path."""
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "pdf"
    path = f"{uuid.uuid4()}.{ext}"
    content = file.file.read()
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
    resume: Optional[UploadFile] = File(None),
):
    resume_path = _upload_resume(resume) if resume else None
    row = table("job_applications").insert({
        "position": position,
        "full_name": full_name,
        "email": email,
        "phone": phone or None,
        "linkedin_url": linkedin_url,
        "resume": resume_path,
    })
    return {"ok": True, "id": row[0]["id"] if row else None}
