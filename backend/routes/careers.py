from fastapi import APIRouter, UploadFile, File, Form
from typing import Optional

from db.connection import table

router = APIRouter()


@router.post("/apply")
async def apply(
    position: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    linkedin_url: str = Form(...),
    phone: str = Form(""),
    resume: Optional[UploadFile] = File(None),
):
    row = table("job_applications").insert({
        "position": position,
        "full_name": full_name,
        "email": email,
        "phone": phone or None,
        "linkedin_url": linkedin_url,
        "resume": resume.filename if resume else None,
    })
    return {"ok": True, "id": row[0]["id"] if row else None}
