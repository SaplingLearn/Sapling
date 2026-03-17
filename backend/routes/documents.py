"""
backend/routes/documents.py

Document upload, AI processing, and library storage.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from db.connection import table
from services.extraction_service import extract_text_from_file
from services.gemini_service import call_gemini_json
from services.calendar_service import extract_assignments_from_file, save_assignments_to_db

router = APIRouter()

MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx"}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

VALID_CATEGORIES = {
    "syllabus", "lecture_notes", "slides", "reading",
    "assignment", "study_guide", "other",
}


def _classify_and_summarize(filename: str, extracted_text: str) -> dict:
    prompt = (
        f"You are processing a student document titled '{filename}'.\n"
        f"Content: {extracted_text[:12000]}\n"
        "Return ONLY valid JSON with no markdown or backticks:\n"
        "{\n"
        '  "category": one of ["syllabus","lecture_notes","slides","reading","assignment","study_guide","other"],\n'
        '  "summary": "2-3 sentence overview of the document",\n'
        '  "key_takeaways": ["...", "..."],\n'
        '  "flashcards": [{"question": "...", "answer": "..."}]\n'
        "}"
    )
    result = call_gemini_json(prompt)
    # Sanitize category in case Gemini returns something unexpected
    if result.get("category") not in VALID_CATEGORIES:
        result["category"] = "other"
    return result


@router.get("/{user_id}")
def list_documents(user_id: str):
    docs = table("documents").select("*", filters={"user_id": f"eq.{user_id}"}, order="created_at.desc")
    return {"documents": docs}


@router.delete("/{document_id}")
def delete_document(document_id: str):
    table("documents").delete(filters={"id": f"eq.{document_id}"})
    return {"deleted": True}


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    course_id: str = Form(...),
    user_id: str = Form(...),
):
    # ── Validation ────────────────────────────────────────────────────────────
    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in ALLOWED_EXTENSIONS and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext or file.content_type}'. Only PDF, DOCX, and PPTX are accepted.",
        )

    file_bytes = await file.read()

    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="File exceeds the 15 MB limit. Please upload a smaller file.",
        )

    # ── Text extraction ───────────────────────────────────────────────────────
    extracted_text = extract_text_from_file(file_bytes, filename, file.content_type or "")

    # ── AI classification + summarization ─────────────────────────────────────
    ai = _classify_and_summarize(filename, extracted_text)

    # ── If syllabus: also run assignment extraction ───────────────────────────
    if ai.get("category") == "syllabus":
        try:
            result = extract_assignments_from_file(file_bytes, filename, file.content_type or "")
            assignments = result.get("assignments") or []
            if assignments:
                save_assignments_to_db(user_id, assignments)
        except Exception:
            pass  # assignment extraction is best-effort; don't fail the upload

    # ── Persist to documents table ────────────────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "course_id": course_id,
        "file_name": filename,
        "category": ai.get("category", "other"),
        "summary": ai.get("summary"),
        "key_takeaways": ai.get("key_takeaways"),
        "flashcards": ai.get("flashcards"),
        "created_at": now,
        "processed_at": now,
    }
    inserted = table("documents").insert(row)
    return inserted[0] if inserted else row
