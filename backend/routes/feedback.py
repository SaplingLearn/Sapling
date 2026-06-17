import logging
import uuid

import httpx
from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from db.connection import SUPABASE_URL, SUPABASE_KEY, table
from models import SubmitFeedbackBody, SubmitIssueReportBody
from services.auth_guard import get_session_user_id
from services.request_limits import read_within_limit

logger = logging.getLogger(__name__)

router = APIRouter()

# #231: issue-report screenshots upload here. They used to be written by the
# frontend with the public anon key; this endpoint moves the write server-side
# (service role) so the bucket can be made private.
ISSUE_BUCKET = "issues-media-files"
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_SCREENSHOT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


@router.post("/feedback")
def submit_feedback(body: SubmitFeedbackBody):
    table("feedback").insert({
        "user_id": body.user_id,
        "type": body.type,
        "rating": body.rating,
        "selected_options": body.selected_options,
        "comment": body.comment,
        "session_id": body.session_id,
        "topic": body.topic,
    })
    return {"ok": True}


@router.post("/issue-reports")
def submit_issue_report(body: SubmitIssueReportBody):
    table("issue_reports").insert({
        "user_id": body.user_id,
        "topic": body.topic,
        "description": body.description,
        "screenshot_urls": body.screenshot_urls,
    })
    return {"ok": True}


@router.post("/issue-reports/screenshot")
async def upload_issue_screenshot(request: Request, file: UploadFile = File(...)):
    """Auth-gated, server-side upload for issue-report screenshots (#231).

    Replaces the frontend's direct anon-key upload to issues-media-files so the
    bucket can be made private (Phase 2b). Validates type + size (the #220/#229
    pattern), uploads with the service role, and returns the storage PATH (not a
    public URL); the path is stored in issue_reports.screenshot_urls and reviewed
    via the dashboard / a signed URL.
    """
    user_id = get_session_user_id(request)  # 401 if unauthenticated
    if (file.content_type or "") not in ALLOWED_SCREENSHOT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported image type. Allowed: PNG, JPEG, WEBP, GIF.",
        )
    content = await read_within_limit(file, MAX_SCREENSHOT_BYTES)  # 413 if oversize
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")
    ext = (
        file.filename.rsplit(".", 1)[-1]
        if file.filename and "." in file.filename
        else "png"
    )
    path = f"{user_id}/{uuid.uuid4()}.{ext}"
    url = f"{SUPABASE_URL}/storage/v1/object/{ISSUE_BUCKET}/{path}"
    r = httpx.put(
        url,
        content=content,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": file.content_type or "application/octet-stream",
        },
        timeout=30.0,
    )
    if r.status_code not in (200, 201):
        # Surface the real Supabase response so the failure is debuggable
        # without server access (mirrors storage_service.upload_avatar). We
        # only show the truncated upstream body — never the URL or headers
        # (the latter contains the service-role key).
        body_text = (r.text or "").strip()[:500]
        logger.warning(
            "upload_issue_screenshot: Supabase storage rejected upload "
            "user=%s status=%d body=%s",
            user_id, r.status_code, body_text,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Screenshot upload failed (Supabase {r.status_code}): {body_text or 'no body'}",
        )
    return {"path": path}
