"""
backend/routes/documents.py

Document upload, AI processing, and library storage.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile

from db.connection import table
from services.extraction_service import extract_text_from_file
from services.gemini_service import call_gemini_json
from services.calendar_service import save_assignments_to_db
from services.graph_service import apply_graph_update

logger = logging.getLogger(__name__)

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


def _validate_user(user_id: str) -> None:
    """Verify that the user_id corresponds to an existing user."""
    rows = table("users").select("id", filters={"id": f"eq.{user_id}"}, limit=1)
    if not rows:
        raise HTTPException(status_code=403, detail="Invalid user.")


def _coerce_str_list(value) -> list[str]:
    """Coerce LLM output into a list[str], dropping non-strings and blanks."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append(s)
    return out


def _coerce_dict_list(value) -> list[dict]:
    """Coerce LLM output into a list[dict]."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _extend_course_concepts(
    *,
    course_label: str,
    existing_concepts: list[str],
    doc_filename: str | None = None,
    doc_summary: str | None = None,
    doc_takeaways: list[str] | None = None,
) -> list[str]:
    """Focused LLM call: extend an existing course concept set.

    The LLM is shown the course label, every concept already in the graph,
    and (when scanning a specific document) that document's stored summary
    and key takeaways. It returns new concepts to add, avoiding duplicates.
    """
    existing_block = (
        "\n".join(f"- {c}" for c in existing_concepts) if existing_concepts else "(none yet)"
    )
    doc_block = ""
    if doc_filename or doc_summary or doc_takeaways:
        takeaways_block = (
            "\n".join(f"  - {t}" for t in (doc_takeaways or [])) or "  (none)"
        )
        doc_block = (
            "\nNew document being scanned:\n"
            f"  Title: {doc_filename or '(untitled)'}\n"
            f"  Summary: {doc_summary or '(none)'}\n"
            "  Key takeaways:\n"
            f"{takeaways_block}\n"
        )

    prompt = (
        f"You are curating the concept set for the course \"{course_label}\".\n"
        "Concepts already in the student's graph for this course:\n"
        f"{existing_block}\n"
        f"{doc_block}"
        "Return ONLY valid JSON with no markdown or backticks:\n"
        '{ "concepts": ["...", "..."] }\n'
        "Rules:\n"
        "- Return between 0 and 15 NEW concepts that should be in this course's "
        "graph but are not in the existing list above.\n"
        "- If the existing set already covers the relevant material, return [].\n"
        "- Each concept is a short Title Case noun phrase "
        "(e.g. \"Linear Regression\", \"Big-O Analysis\").\n"
        "- Do NOT repeat or paraphrase any existing concept.\n"
        "- No assignment titles, week labels, page numbers, problem numbers, or "
        "administrative items.\n"
        "- concepts must be a JSON array of strings."
    )
    raw = call_gemini_json(prompt)
    if not isinstance(raw, dict):
        return []
    return _coerce_str_list(raw.get("concepts"))


def _process_document(filename: str, extracted_text: str) -> dict:
    """Single LLM call: classify, summarize, and extract assignments + concepts.

    Returns a normalized shape with all fields validated and coerced — callers
    can trust the types without further isinstance checks.
    """
    prompt = (
        f"You are processing a student document titled '{filename}'.\n"
        f"Content: {extracted_text[:12000]}\n"
        "Return ONLY valid JSON with no markdown or backticks:\n"
        "{\n"
        '  "category": one of ["syllabus","lecture_notes","slides","reading","assignment","study_guide","other"],\n'
        '  "summary": "2-3 sentence overview of the document",\n'
        '  "key_takeaways": ["...", "..."],\n'
        '  "flashcards": [{"question": "...", "answer": "..."}],\n'
        '  "assignments": [],\n'
        '  "concepts": []\n'
        "}\n"
        'If category is "syllabus", populate "assignments" with every deadline found:\n'
        '  {"title": "...", "due_date": "YYYY-MM-DD (assume 2026 if year missing)", '
        '"course_name": "...", "assignment_type": one of [homework,exam,reading,project,quiz,other], "notes": "..." or null}\n'
        'If category is "syllabus", also populate "concepts" with 5–15 distinct high-level topics or concepts '
        'the course will cover, drawn from the schedule, learning outcomes, or topic list. '
        'Each concept is a short noun phrase (e.g. "Linear Regression", "Big-O Analysis"). '
        "Use Title Case. Do not include assignment titles, week labels, or administrative items.\n"
        'If category is "assignment", populate "concepts" with 1–8 specific topics the assignment '
        "tests or practices, as short Title Case noun phrases. Do not include problem numbers or instructions.\n"
        'For all other categories, "concepts" must be [].\n'
        'For non-syllabus documents, "assignments" must be [].\n'
        '"key_takeaways" must be a JSON array of strings. "flashcards" must be a JSON array '
        'of objects each with "question" and "answer" string fields. "concepts" must be a JSON '
        "array of strings (no objects, no comma-separated string)."
    )
    raw = call_gemini_json(prompt)
    if not isinstance(raw, dict):
        raw = {}

    category = raw.get("category")
    if category not in VALID_CATEGORIES:
        category = "other"

    summary = raw.get("summary")
    if not isinstance(summary, str):
        summary = ""

    return {
        "category": category,
        "summary": summary.strip(),
        "key_takeaways": _coerce_str_list(raw.get("key_takeaways")),
        "flashcards": _coerce_dict_list(raw.get("flashcards")),
        "assignments": _coerce_dict_list(raw.get("assignments")),
        "concepts": _coerce_str_list(raw.get("concepts")),
    }


@router.get("/user/{user_id}")
def list_documents(user_id: str):
    _validate_user(user_id)
    docs = table("documents").select("*", filters={"user_id": f"eq.{user_id}"}, order="created_at.desc")
    return {"documents": docs}


@router.delete("/doc/{document_id}")
def delete_document(document_id: str, user_id: str | None = None):
    if user_id:
        _validate_user(user_id)
        # Ensure the document belongs to the requesting user
        docs = table("documents").select("id", filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"}, limit=1)
        if not docs:
            raise HTTPException(status_code=404, detail="Document not found.")
    table("documents").delete(filters={"id": f"eq.{document_id}"})
    return {"deleted": True}


@router.patch("/doc/{document_id}")
def update_document(document_id: str, body: dict = Body(...)):
    """Update mutable fields on a document (currently only category)."""
    user_id = body.get("user_id")
    if user_id:
        _validate_user(user_id)
        docs = table("documents").select("id", filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"}, limit=1)
        if not docs:
            raise HTTPException(status_code=404, detail="Document not found.")
    category = body.get("category")
    if category and category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category '{category}'.")
    updates = {}
    if category:
        updates["category"] = category
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update.")
    updated = table("documents").update(updates, filters={"id": f"eq.{document_id}"})
    return updated[0] if updated else {"id": document_id, **updates}


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    course_id: str = Form(...),
    user_id: str = Form(...),
):
    _validate_user(user_id)

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

    # ── AI: classify, summarize, and extract assignments (single call) ─────────
    ai = _process_document(filename, extracted_text)

    if ai["category"] == "syllabus" and ai["assignments"]:
        try:
            for a in ai["assignments"]:
                a["course_id"] = course_id
            save_assignments_to_db(user_id, ai["assignments"])
        except Exception:
            logger.exception("Assignment save failed for '%s' (best-effort)", filename)

    if ai["category"] in ("syllabus", "assignment") and ai["concepts"]:
        try:
            new_nodes = [
                {"concept_name": name, "initial_mastery": 0.0}
                for name in ai["concepts"]
            ]
            apply_graph_update(user_id, {"new_nodes": new_nodes}, course_id=course_id)
        except Exception:
            logger.exception("Concept population failed for '%s' (best-effort)", filename)

    # ── Persist to documents table ────────────────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "course_id": course_id,
        "file_name": filename,
        "category": ai["category"],
        "summary": ai["summary"] or None,
        "key_takeaways": ai["key_takeaways"],
        "flashcards": ai["flashcards"],
        "created_at": now,
        "processed_at": now,
    }
    inserted = table("documents").insert(row)

    # Invalidate any cached study guides for this user+course so they regenerate fresh
    try:
        table("study_guides").delete(
            filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"}
        )
    except Exception:
        logger.exception("Failed to invalidate study guides cache for user=%s course=%s", user_id, course_id)

    # Check for achievements after successful upload
    try:
        from services.achievement_service import check_achievements
        check_achievements(user_id, "documents_uploaded", {})
    except Exception:
        pass

    return inserted[0] if inserted else row


def _course_label(course_id: str) -> str:
    """Best-effort human label for a course (for prompts and toasts)."""
    rows = table("courses").select(
        "course_code,course_name", filters={"id": f"eq.{course_id}"}, limit=1,
    ) or []
    if not rows:
        return "Course"
    row = rows[0]
    code = (row.get("course_code") or "").strip()
    name = (row.get("course_name") or "").strip()
    if code and name:
        return f"{code} — {name}"
    return code or name or "Course"


def _scan_concepts_for_course(
    user_id: str,
    course_id: str,
    *,
    doc_filename: str | None = None,
    doc_summary: str | None = None,
    doc_takeaways: list[str] | None = None,
) -> dict:
    """Shared scan logic. Pulls existing course concepts, asks the LLM to
    extend the set, and writes new nodes via apply_graph_update."""
    existing_rows = table("graph_nodes").select(
        "id,concept_name", filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    ) or []
    existing_concepts = [r["concept_name"] for r in existing_rows if r.get("concept_name")]

    concepts = _extend_course_concepts(
        course_label=_course_label(course_id),
        existing_concepts=existing_concepts,
        doc_filename=doc_filename,
        doc_summary=doc_summary,
        doc_takeaways=doc_takeaways,
    )
    if not concepts:
        return {"concepts": [], "added": 0, "existing": len(existing_concepts)}

    before_count = len(existing_rows)
    try:
        new_nodes = [{"concept_name": name, "initial_mastery": 0.0} for name in concepts]
        apply_graph_update(user_id, {"new_nodes": new_nodes}, course_id=course_id)
    except Exception:
        logger.exception("Concept scan failed for course=%s", course_id)
        raise HTTPException(status_code=500, detail="Concept scan failed.")

    after_rows = table("graph_nodes").select(
        "id", filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    ) or []
    return {
        "concepts": concepts,
        "added": max(0, len(after_rows) - before_count),
        "existing": len(existing_concepts),
    }


@router.post("/doc/{document_id}/scan-concepts")
def scan_document_concepts(document_id: str, body: dict = Body(...)):
    """Extend the course's concept graph using one document's stored
    summary + takeaways as the seed signal."""
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required.")
    _validate_user(user_id)

    rows = table("documents").select(
        "id,user_id,course_id,file_name,summary,key_takeaways",
        filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc = rows[0]
    course_id = doc.get("course_id")
    if not course_id:
        raise HTTPException(status_code=400, detail="Document is not associated with a course.")

    return _scan_concepts_for_course(
        user_id,
        course_id,
        doc_filename=doc.get("file_name"),
        doc_summary=doc.get("summary"),
        doc_takeaways=doc.get("key_takeaways") or [],
    )


@router.post("/course/{course_id}/scan-concepts")
def scan_course_concepts(course_id: str, body: dict = Body(...)):
    """Extend the course's concept graph from the course label alone
    (and whatever is already in the graph)."""
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required.")
    _validate_user(user_id)
    return _scan_concepts_for_course(user_id, course_id)
