import base64

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from db.connection import table

router = APIRouter()

ALLOWED_MIME = {
    "application/pdf",
}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/apply")
def submit_application(
    position: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    linkedin_url: str = Form(...),
    phone: str = Form(""),
    resume: UploadFile = File(...),
):
    if resume.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="Resume must be a PDF.")

    content = resume.file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Resume must be under 10 MB.")

    row = table("job_applications").insert({
        "position": position,
        "full_name": full_name,
        "email": email,
        "phone": phone or None,
        "linkedin_url": linkedin_url,
        "resume": base64.b64encode(content).decode("utf-8"),
    })

    return {"ok": True, "id": row[0]["id"] if row else None}
