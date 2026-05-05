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
from services.gemini_service import call_gemini_json
from services.assignment_dedupe import assignment_dedupe_key
from db.connection import table

logger = logging.getLogger(__name__)

PROMPT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "syllabus_extraction.txt")


def load_existing_assignment_keys(user_id: str) -> set[tuple[str, str]]:
    """All (title, due_date) keys for a user, using the same normalization as assignment_dedupe_key."""
    existing_rows = table("assignments").select(
        "title,due_date",
        filters={"user_id": f"eq.{user_id}"},
    )
    return {assignment_dedupe_key(r.get("title"), r.get("due_date")) for r in (existing_rows or [])}


def insert_new_assignments(user_id: str, assignments: list[dict]) -> int:
    """
    Insert assignments that are not already present for this user (#16).
    Same trimmed title + same calendar day (see assignment_dedupe_key) → skip.
    Returns number of rows inserted.
    """
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
        existing_keys.add(key)
        rows.append({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "title": title,
            "course_id": a.get("course_id") or None,
            "due_date": key[1],
            "assignment_type": a.get("assignment_type") or "other",
            "notes": a.get("notes"),
        })
    if rows:
        table("assignments").insert(rows)
    return len(rows)


def parse_syllabus(extracted_text: str) -> dict:
    """Use Gemini to parse assignments from extracted text.

    Legacy fallback path retained per ADR-0001. The primary path now
    runs through `_extract_via_agent` (syllabus_extraction_agent +
    syllabus_to_wire_dict). This function stays so that the agent path
    has a working degrade target when guardrails trip.
    """
    with open(PROMPT_PATH) as f:
        prompt_template = f.read()
    prompt = prompt_template + f"\n\nDOCUMENT TEXT:\n{extracted_text}"
    return call_gemini_json(prompt)


async def _extract_via_agent(
    extracted_text: str,
    *,
    user_id: str = "",
    request_id: str = "",
) -> dict:
    """Run syllabus_extraction_agent on `extracted_text` and convert
    its output to the legacy wire-format dict.

    Returns the same shape as the legacy `parse_syllabus`:
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


def save_assignments_to_db(user_id: str, assignments: list) -> int:
    """Write extracted assignment dicts to the DB (deduped via insert_new_assignments)."""
    return insert_new_assignments(user_id, assignments)


async def extract_assignments_from_file(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    *,
    user_id: str = "",
    request_id: str = "",
) -> dict:
    """Extract text from file then parse assignments via the agent
    (legacy fallback per ADR-0001).

    Async because the syllabus-extraction agent is async; callers
    must `await` this. Mirrors the orchestrator-vs-legacy fallback
    pattern in `routes/quiz.py::_quiz_via_agent` and
    `routes/learn.py::_chat_via_agent`: Pydantic-AI guardrail
    exceptions and bare exceptions degrade to the legacy
    `parse_syllabus` path so a single agent failure can't take the
    syllabus-upload feature down.
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
            "Syllabus agent guardrails tripped; falling back to legacy",
            exc_info=e,
        )
        result = parse_syllabus(text)
        result.setdefault("raw_text", text)
        result.setdefault("course_title", None)
        result.setdefault("grading_categories", [])
    except Exception:
        logger.exception(
            "Unexpected syllabus-agent failure; falling back to legacy"
        )
        result = parse_syllabus(text)
        result.setdefault("raw_text", text)
        result.setdefault("course_title", None)
        result.setdefault("grading_categories", [])

    return result


async def process_and_save_syllabus(
    file_bytes: bytes, filename: str, content_type: str, user_id: str
) -> dict:
    """Full pipeline: OCR → agent → DB save in one call."""
    result = await extract_assignments_from_file(
        file_bytes, filename, content_type,
        user_id=user_id,
    )
    assignments = result.get("assignments") or []
    saved_count = save_assignments_to_db(user_id, assignments) if assignments else 0
    return {
        "assignments": assignments,
        "saved_count": saved_count,
        "warnings": result.get("warnings") or [],
        "raw_text": result.get("raw_text") or "",
    }
