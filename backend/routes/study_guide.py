"""
backend/routes/study_guide.py

Study guide generation and caching.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException, Query, Request

from agents._run import run_agent_sync
from agents.deps import SaplingDeps
from agents.study_guide import study_guide_agent
from agents.usage import record_agent_usage
from db.connection import table
from services.academics import (
    offering_course_id,
    resolve_offering,
    user_enrollment_ids,
    user_offering_ids_for_course,
)
from services.graph_service import get_courses as graph_get_courses
from services.auth_guard import require_self
from services.encryption import decrypt_if_present, decrypt_json
from services.http_cache import cached_json, conditional, make_etag
from services.request_context import current_request_id

router = APIRouter()


def _course_enrollment_ids(user_id: str, course_id: str) -> list[str]:
    """The user's enrollment ids for the given abstract ``course_id``.

    The ``assignments`` table is enrollment-keyed (the gradebook table has no
    ``user_id``/``course_id`` column — see routes/gradebook.py). The HTTP
    boundary speaks the abstract course id, so we resolve
    course → the user's offering(s) of it → their enrollment rows, mirroring
    routes/calendar.py::_read_assignments.
    """
    course_offerings = set(user_offering_ids_for_course(user_id, course_id))
    if not course_offerings:
        return []
    return [
        e["id"]
        for e in user_enrollment_ids(user_id)
        if e.get("offering_id") in course_offerings
    ]


def _generate_and_insert(user_id: str, offering_id: str, exam_id: str) -> dict:
    """Generate a study guide, insert it into study_guides, and return
    {content, generated_at}.

    Study guides + the documents that feed them key on the OFFERING (0025);
    the caller resolves the abstract course id to an offering first.
    """
    # 1. Fetch exam info. Assignments key on enrollment_id (no user_id/course_id
    #    column); scope to the user's own enrollments so one user can't generate a
    #    guide off another's exam.
    enrollment_ids = [e["id"] for e in user_enrollment_ids(user_id)]
    exams = (
        table("assignments").select(
            "id,enrollment_id,title,due_date,assignment_type",
            filters={
                "id": f"eq.{exam_id}",
                "enrollment_id": f"in.({','.join(enrollment_ids)})",
            },
            limit=1,
        )
        if enrollment_ids
        else []
    )
    if not exams:
        # The frontend renders this detail verbatim, so it has to read like
        # guidance rather than a status line.
        raise HTTPException(
            status_code=404,
            detail="Exam not found. It may have been deleted — pick another exam.",
        )
    exam = exams[0]
    exam_title = exam.get("title", "")
    due_date = exam.get("due_date", "")

    # 2. Fetch documents for this user+offering
    docs = table("documents").select(
        "summary,concept_notes",
        filters={
            "user_id": f"eq.{user_id}",
            "offering_id": f"eq.{offering_id}",
            "deleted_at": "is.null",
        },
    ) or []

    # 3. Build combined context
    parts: list[str] = []
    for doc in docs:
        summary = decrypt_if_present(doc.get("summary"))
        if summary:
            parts.append(f"Summary: {summary}")
        notes_raw = doc.get("concept_notes")
        if isinstance(notes_raw, str):
            try:
                concept_notes = decrypt_json(notes_raw)
            except Exception:
                concept_notes = notes_raw
        else:
            concept_notes = notes_raw
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

    # 4. Generate the study guide via the study_guide agent. The agent owns the
    #    persona + output schema; the user message carries the exam context.
    user_message = (
        f"Exam: {exam_title}\n"
        f"Due date: {due_date}\n"
        f"Today: {today}\n\n"
        f"Course material:\n{combined_context}"
    )
    # course_id/session are unused by this toolless agent; deps satisfies the type.
    from db.connection import _client  # opaque pass-through for SaplingDeps
    deps = SaplingDeps(
        user_id=user_id,
        course_id=None,
        supabase=_client,
        request_id=current_request_id() or "",
    )
    try:
        result = record_agent_usage(
            run_agent_sync(study_guide_agent.run(user_message, deps=deps)),
            feature="study_guide", task="study_guide", user_id=user_id,
        )
    except Exception as e:  # generation/transport failure → 502, not a raw 500
        raise HTTPException(
            status_code=502, detail="Study guide generation failed."
        ) from e
    content = result.output.model_dump()

    # 5. Insert into study_guides
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "offering_id": offering_id,
        "exam_id": exam_id,
        "generated_at": now,
        "content": content,
    }
    table("study_guides").insert(row)

    return {"content": content, "generated_at": now}


@router.get("/{user_id}/cached")
def get_cached_guides(user_id: str, request: Request):
    require_self(user_id, request)
    guides = table("study_guides").select(
        "id,offering_id,exam_id,generated_at,content",
        filters={"user_id": f"eq.{user_id}"},
        order="generated_at.desc",
    )
    # ETag from the guides' (id, generated_at) — regenerate replaces rows with a
    # fresh id + timestamp, so this captures add/remove/regenerate. A matching
    # If-None-Match returns 304 and skips the per-offering course enrichment below.
    etag = make_etag("guides", user_id, *sorted(f"{g['id']}:{g.get('generated_at')}" for g in guides))
    not_modified = conditional(request, etag)
    if not_modified is not None:
        return not_modified

    # Each guide keys on an offering; the frontend speaks abstract course ids.
    # Map each offering → its abstract course id, then enrich with course_name.
    offering_to_course: dict[str, str | None] = {}
    course_map: dict[str, str] = {}
    for g in guides:
        off_id = g.get("offering_id")
        if off_id and off_id not in offering_to_course:
            cid = offering_course_id(off_id)
            offering_to_course[off_id] = cid
            if cid and cid not in course_map:
                rows = table("courses").select(
                    "id,course_name", filters={"id": f"eq.{cid}"}, limit=1
                )
                if rows:
                    course_map[cid] = rows[0]["course_name"]

    result = []
    for g in guides:
        content = g.get("content") or {}
        course_id = offering_to_course.get(g.get("offering_id"))
        result.append({
            "id": g["id"],
            "course_id": course_id,
            "exam_id": g["exam_id"],
            "course_name": course_map.get(course_id or "", ""),
            "exam_title": content.get("exam", ""),
            "overview": content.get("overview", ""),
            "generated_at": g["generated_at"],
        })
    return cached_json({"guides": result}, etag)


@router.get("/{user_id}/courses")
def get_courses(user_id: str, request: Request):
    require_self(user_id, request)
    # The frontend enumerates courses via /api/graph/{user_id}/courses, so this
    # endpoint is currently unreachable from the UI. Kept alive (and off the old
    # non-existent courses.user_id filter that 500'd) by delegating to the same
    # enrollment-resolving helper the graph endpoint uses.
    return {"courses": graph_get_courses(user_id)}


@router.get("/{user_id}/exams")
def get_exams(user_id: str, request: Request, course_id: str = Query(...)):
    require_self(user_id, request)
    enrollment_ids = _course_enrollment_ids(user_id, course_id)
    if not enrollment_ids:
        return {"exams": []}
    all_assignments = table("assignments").select(
        "id,title,due_date,assignment_type",
        filters={"enrollment_id": f"in.({','.join(enrollment_ids)})"},
        order="due_date.asc",
    ) or []

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
    request: Request,
    course_id: str = Query(...),
    exam_id: str = Query(...),
):
    require_self(user_id, request)
    # The query param is the abstract course id; study guides key on the
    # offering. Resolve to the current-term offering for cache + generation.
    offering_id = resolve_offering(course_id)
    cached = table("study_guides").select(
        "id,user_id,offering_id,exam_id,content,generated_at",
        filters={
            "user_id": f"eq.{user_id}",
            "offering_id": f"eq.{offering_id}",
            "exam_id": f"eq.{exam_id}",
        },
        limit=1,
    )
    if cached:
        row = cached[0]
        return {"guide": row["content"], "generated_at": row["generated_at"], "cached": True}

    result = _generate_and_insert(user_id, offering_id, exam_id)
    return {"guide": result["content"], "generated_at": result["generated_at"], "cached": False}


@router.post("/regenerate")
def regenerate_guide(request: Request, body: dict = Body(...)):
    user_id = body.get("user_id")
    course_id = body.get("course_id")
    exam_id = body.get("exam_id")
    if not user_id or not course_id or not exam_id:
        raise HTTPException(status_code=400, detail="user_id, course_id, and exam_id are required.")
    require_self(user_id, request)

    offering_id = resolve_offering(course_id)
    table("study_guides").delete(
        filters={
            "user_id": f"eq.{user_id}",
            "offering_id": f"eq.{offering_id}",
            "exam_id": f"eq.{exam_id}",
        }
    )
    result = _generate_and_insert(user_id, offering_id, exam_id)
    return {"success": True, "guide": result["content"], "generated_at": result["generated_at"]}
