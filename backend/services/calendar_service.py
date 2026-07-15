import logging
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior

from agents.deps import SaplingDeps
from agents.syllabus_extraction import syllabus_extraction_agent
from agents.tools.syllabus_adapter import syllabus_to_wire_dict
from services.extraction_service import extract_text_from_file
from services.assignment_dedupe import assignment_dedupe_key
from services.encryption import encrypt_if_present
from db.connection import table

logger = logging.getLogger(__name__)


def load_existing_assignment_keys(user_id: str) -> set:
    from services.academics import user_enrollment_ids
    enrollments = user_enrollment_ids(user_id)
    if not enrollments:
        return set()
    ids = ",".join(e["id"] for e in enrollments)
    existing_rows = table("assignments").select(
        "title,due_date", filters={"enrollment_id": f"in.({ids})"},
    )
    return {assignment_dedupe_key(r.get("title"), r.get("due_date")) for r in (existing_rows or [])}


def insert_new_assignments(user_id: str, assignments: list[dict], *, source: str = "manual") -> int:
    """Insert assignments (deduped per the user's enrollment set, #16) on the
    enrollment-keyed schema. Each assignment must carry a ``course_id`` — it is
    resolved to the user's enrollment (created if missing). Returns rows inserted."""
    from services.academics import enrollment_id_for
    existing_keys = load_existing_assignment_keys(user_id)
    rows = []
    for a in assignments:
        title = (a.get("title") or "").strip()
        due_raw = (a.get("due_date") or "").strip()
        if not title or not due_raw:
            continue
        key = assignment_dedupe_key(title, due_raw)
        if key in existing_keys:
            continue
        course_id = a.get("course_id")
        enrollment_id = enrollment_id_for(user_id, course_id, create=True) if course_id else None
        if not enrollment_id:
            continue  # decision: every assignment is course-tied
        existing_keys.add(key)
        rows.append({
            "id": str(uuid.uuid4()),
            "enrollment_id": enrollment_id,
            "title": title,
            "due_date": key[1],
            "assignment_type": a.get("assignment_type") or "other",
            "notes": encrypt_if_present(a.get("notes")),  # #126: encrypt at write
            "source": source,
        })
    if rows:
        table("assignments").insert(rows)
    return len(rows)


def _degraded_result(text: str) -> dict:
    """Graceful degrade when the extraction agent fails. Returns the legacy
    wire shape with no assignments and a user-facing warning — deliberately
    NOT a second LLM call (the raw-Gemini fallback was retired in #144)."""
    return {
        "assignments": [],
        "warnings": [
            "Assignment extraction is temporarily unavailable. Please try again."
        ],
        "raw_text": text,
        "course_title": None,
        "grading_categories": [],
    }


async def _extract_via_agent(
    extracted_text: str,
    *,
    user_id: str = "",
    request_id: str = "",
) -> dict:
    """Run syllabus_extraction_agent on `extracted_text` and convert
    its output to the legacy wire-format dict.

    Returns the legacy wire-format dict:
    {"assignments": [...], "warnings": [...], "raw_text": str,
     "course_title": str | None, "grading_categories": [...]}.

    `course_id` and `session_id` don't apply to syllabus extraction —
    the agent doesn't read them for this output type. `user_id` is
    threaded through SaplingDeps for span correlation only; the
    extraction itself is user-agnostic (the user-scoped dedup-write
    step happens later in `process_and_save_syllabus`).
    """
    deps = SaplingDeps(
        user_id=user_id or "anonymous",
        course_id=None,
        supabase=None,
        request_id=request_id or "",
    )
    result = await syllabus_extraction_agent.run(extracted_text, deps=deps)
    return syllabus_to_wire_dict(result.output, raw_text=extracted_text)


def save_assignments_to_db(user_id: str, assignments: list, *, source: str = "syllabus") -> int:
    """Write extracted assignment dicts (deduped via insert_new_assignments)."""
    return insert_new_assignments(user_id, assignments, source=source)


async def extract_assignments_from_file(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    *,
    user_id: str = "",
    request_id: str = "",
) -> dict:
    """Extract text from a file, then parse assignments via
    `syllabus_extraction_agent`.

    Async because the agent is async; callers must `await` this. The
    raw-Gemini legacy fallback was retired in #144: Pydantic-AI guardrail
    exceptions and bare exceptions now degrade to `_degraded_result` (empty
    assignments + a warning, no second LLM call) so a single agent failure
    can't take the syllabus-upload feature down.
    """
    text = extract_text_from_file(file_bytes, filename, content_type)
    if not text.strip():
        return {
            "assignments": [],
            "warnings": ["No text could be extracted from the file."],
            "raw_text": "",
        }

    try:
        result = await _extract_via_agent(
            text, user_id=user_id, request_id=request_id
        )
    except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
        logger.warning(
            "Syllabus agent guardrails tripped; degrading to empty result",
            exc_info=e,
        )
        result = _degraded_result(text)
    except Exception:
        logger.exception(
            "Unexpected syllabus-agent failure; degrading to empty result"
        )
        result = _degraded_result(text)

    return result


async def process_and_save_syllabus(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    user_id: str,
    *,
    request_id: str = "",
) -> dict:
    """Full pipeline: OCR → agent → DB save in one call.

    `request_id` is optional so existing callers (the live-DB tests in
    `test_ocr_pipeline.py`) keep working unchanged. Routes that wire
    this should pass their `request.state.request_id` through so
    Logfire spans correlate the syllabus run with the user-facing
    request.
    """
    result = await extract_assignments_from_file(
        file_bytes, filename, content_type,
        user_id=user_id,
        request_id=request_id,
    )
    assignments = result.get("assignments") or []
    saved_count = save_assignments_to_db(user_id, assignments) if assignments else 0
    return {
        "assignments": assignments,
        "saved_count": saved_count,
        "warnings": result.get("warnings") or [],
        "raw_text": result.get("raw_text") or "",
    }
