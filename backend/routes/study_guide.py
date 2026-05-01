"""
backend/routes/study_guide.py

Study guide generation and caching.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException, Query

from db.connection import table
from services.gemini_service import call_gemini_json

router = APIRouter()


def _generate_and_insert(user_id: str, course_id: str, exam_id: str) -> dict:
    """Generate a study guide, insert it into study_guides, and return {content, generated_at}."""
    # 1. Fetch exam info
    exams = table("assignments").select(
        "title,due_date",
        filters={"id": f"eq.{exam_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not exams:
        raise HTTPException(status_code=404, detail="Exam not found.")
    exam = exams[0]
    exam_title = exam.get("title", "")
    due_date = exam.get("due_date", "")

    # 2. Fetch documents for this user+course
    docs = table("documents").select(
        "summary,concept_notes",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    )

    # 3. Build combined context
    parts: list[str] = []
    for doc in docs:
        if doc.get("summary"):
            parts.append(f"Summary: {doc['summary']}")
        concept_notes = doc.get("concept_notes")
        if concept_notes and isinstance(concept_notes, list):
            lines = []
            for note in concept_notes:
                if not isinstance(note, dict):
                    continue
                name = note.get("name")
                desc = note.get("description")
                if not name:
                    continue
                if desc:
                    lines.append(f"- {name}: {desc}")
                else:
                    lines.append(f"- {name}")
            if lines:
                parts.append("Key Concepts:\n" + "\n".join(lines))

    combined_context = "\n\n".join(parts) if parts else "No course material available."
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 4. Call Gemini
    prompt = (
        "You are a study guide generator for a student exam prep tool.\n\n"
        f"Exam: {exam_title}\n"
        f"Due date: {due_date}\n"
        f"Today: {today}\n\n"
        f"Course material:\n{combined_context}\n\n"
        "Generate a comprehensive study guide for this exam. Break the material into clear topics. "
        "For each topic provide:\n"
        "- A topic name\n"
        "- 3-5 surface-level concept bullet points the student should understand\n"
        "- One sentence explaining why this topic matters for the exam\n\n"
        "Return ONLY a JSON object with this exact schema, no markdown fences:\n"
        "{\n"
        '  "exam": "<exam title>",\n'
        '  "due_date": "<YYYY-MM-DD>",\n'
        '  "overview": "<2-3 sentence overview of what this exam covers and how to approach it>",\n'
        '  "topics": [\n'
        "    {\n"
        '      "name": "<topic name>",\n'
        '      "importance": "<one sentence>",\n'
        '      "concepts": ["<concept>", "<concept>", ...]\n'
        "    }\n"
        "  ]\n"
        "}"
    )
    content = call_gemini_json(prompt)

    # 5. Insert into study_guides
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "course_id": course_id,
        "exam_id": exam_id,
        "generated_at": now,
        "content": content,
    }
    table("study_guides").insert(row)

    return {"content": content, "generated_at": now}


@router.get("/{user_id}/cached")
def get_cached_guides(user_id: str):
    guides = table("study_guides").select(
        "id,course_id,exam_id,generated_at,content",
        filters={"user_id": f"eq.{user_id}"},
        order="generated_at.desc",
    )
    # Enrich with course_name
    course_ids = list({g["course_id"] for g in guides})
    course_map: dict[str, str] = {}
    for cid in course_ids:
        rows = table("courses").select("id,course_name", filters={"id": f"eq.{cid}"}, limit=1)
        if rows:
            course_map[cid] = rows[0]["course_name"]

    result = []
    for g in guides:
        content = g.get("content") or {}
        result.append({
            "id": g["id"],
            "course_id": g["course_id"],
            "exam_id": g["exam_id"],
            "course_name": course_map.get(g["course_id"], ""),
            "exam_title": content.get("exam", ""),
            "overview": content.get("overview", ""),
            "generated_at": g["generated_at"],
        })
    return {"guides": result}


@router.get("/{user_id}/courses")
def get_courses(user_id: str):
    courses = table("courses").select(
        "id,course_name,color",
        filters={"user_id": f"eq.{user_id}"},
    )
    return {"courses": courses}


@router.get("/{user_id}/exams")
def get_exams(user_id: str, course_id: str = Query(...)):
    all_assignments = table("assignments").select(
        "id,title,due_date,assignment_type",
        filters={"user_id": f"eq.{user_id}"},
        order="due_date.asc",
    )

    exam_keywords = ["exam", "midterm", "final", "quiz"]
    exams = []
    for a in all_assignments:
        atype = (a.get("assignment_type") or "").lower()
        title = (a.get("title") or "").lower()
        if atype == "exam" or any(kw in title for kw in exam_keywords):
            exams.append(a)

    return {"exams": exams}


@router.get("/{user_id}/guide")
def get_guide(
    user_id: str,
    course_id: str = Query(...),
    exam_id: str = Query(...),
):
    cached = table("study_guides").select(
        "*",
        filters={
            "user_id": f"eq.{user_id}",
            "course_id": f"eq.{course_id}",
            "exam_id": f"eq.{exam_id}",
        },
        limit=1,
    )
    if cached:
        row = cached[0]
        return {"guide": row["content"], "generated_at": row["generated_at"], "cached": True}

    result = _generate_and_insert(user_id, course_id, exam_id)
    return {"guide": result["content"], "generated_at": result["generated_at"], "cached": False}


@router.post("/regenerate")
def regenerate_guide(body: dict = Body(...)):
    user_id = body.get("user_id")
    course_id = body.get("course_id")
    exam_id = body.get("exam_id")
    if not user_id or not course_id or not exam_id:
        raise HTTPException(status_code=400, detail="user_id, course_id, and exam_id are required.")

    table("study_guides").delete(
        filters={
            "user_id": f"eq.{user_id}",
            "course_id": f"eq.{course_id}",
            "exam_id": f"eq.{exam_id}",
        }
    )
    result = _generate_and_insert(user_id, course_id, exam_id)
    return {"success": True, "guide": result["content"], "generated_at": result["generated_at"]}
