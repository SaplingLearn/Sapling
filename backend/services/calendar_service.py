import logging
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior

from agents import WORKER_LIMITS
from agents.deps import SaplingDeps
from agents.syllabus_extraction import syllabus_extraction_agent
from agents.tools.syllabus_adapter import syllabus_to_wire_dict
from agents.usage import record_agent_usage
from services.extraction_service import extract_text_from_file
from services.assignment_dedupe import assignment_dedupe_key
from services.encryption import encrypt_if_present
from db.connection import table

logger = logging.getLogger(__name__)


#: Why a row of a save was not written. A skip's ``reason`` is always one of
#: these fixed codes, never free text (nothing about another row or course).
SKIP_DUPLICATE = "duplicate"
SKIP_NO_ENROLLMENT = "no_enrollment"


def load_existing_assignment_keys(enrollment_ids) -> set[tuple[str, str, str]]:
    """``(enrollment_id, title, day)`` of every assignment in those enrollments,
    title and day normalized by ``assignment_dedupe_key``. ``title`` and
    ``due_date`` are plaintext columns (only notes and points are encrypted),
    so they compare as stored."""
    ids = sorted({e for e in enrollment_ids if e})
    if not ids:
        return set()
    existing_rows = table("assignments").select(
        "enrollment_id,title,due_date", filters={"enrollment_id": f"in.({','.join(ids)})"},
    )
    return {
        (r.get("enrollment_id"), *assignment_dedupe_key(r.get("title"), r.get("due_date")))
        for r in (existing_rows or [])
    }


def save_new_assignments(user_id: str, assignments: list[dict], *, source: str = "manual") -> dict:
    """Insert assignments on the enrollment-keyed schema and say what was left
    out: ``{"saved_count", "skipped_count", "skipped": [{"title", "due_date",
    "reason"}]}``, skips in request order.

    Each assignment must carry a ``course_id``: it is resolved to the user's
    EXISTING enrollment. A calendar/syllabus write never creates an enrollment
    (#766): with ``create=True`` a save for a course the student had dropped
    silently re-enrolled them. An assignment for a course the student isn't
    enrolled in, or with no course, is skipped as ``no_enrollment``.

    A duplicate (#16) is the same trimmed title on the same calendar day IN
    THE SAME ENROLLMENT, already stored or earlier in this batch. The key was
    user-wide while assignments were keyed on ``user_id`` with a free-text
    course name; since they hang off an enrollment, a "Final Exam" on one day
    in two courses is two assignments, and the user-wide key dropped the
    second without a word. Skipped as ``duplicate``.

    A row with no title or no due date is dropped uncounted, as before."""
    from services.academics import enrollment_id_for
    dated = []
    for a in assignments:
        title, day = assignment_dedupe_key(a.get("title"), a.get("due_date"))
        if title and day:
            dated.append((title, day, a))
    enrollment_of = {
        course_id: enrollment_id_for(user_id, course_id, create=False)
        for course_id in dict.fromkeys(a.get("course_id") for _, _, a in dated)
        if course_id
    }
    existing_keys = load_existing_assignment_keys(enrollment_of.values())
    rows = []
    skipped = []
    for title, day, a in dated:
        enrollment_id = enrollment_of.get(a.get("course_id"))
        key = (enrollment_id, title, day)
        reason = (
            SKIP_NO_ENROLLMENT if not enrollment_id  # decision: every assignment is course-tied
            else SKIP_DUPLICATE if key in existing_keys
            else None
        )
        if reason:
            skipped.append({"title": title, "due_date": day, "reason": reason})
            continue
        existing_keys.add(key)
        rows.append({
            "id": str(uuid.uuid4()),
            "enrollment_id": enrollment_id,
            "title": title,
            "due_date": day,
            "assignment_type": a.get("assignment_type") or "other",
            "notes": encrypt_if_present(a.get("notes")),  # #126: encrypt at write
            "source": source,
        })
    not_enrolled = sorted(c for c, e in enrollment_of.items() if not e)
    if not_enrolled:
        logger.info(
            "calendar: skipped assignments for %d course(s) user=%s is not "
            "enrolled in: %s", len(not_enrolled), user_id, not_enrolled,
        )
    if rows:
        table("assignments").insert(rows)
    return {"saved_count": len(rows), "skipped_count": len(skipped), "skipped": skipped}


def insert_new_assignments(user_id: str, assignments: list[dict], *, source: str = "manual") -> int:
    """:func:`save_new_assignments`, answering only the number of rows inserted."""
    return save_new_assignments(user_id, assignments, source=source)["saved_count"]


def _degraded_result(text: str, *, warning: str | None = None) -> dict:
    """Graceful degrade when the extraction agent fails. Returns the legacy
    wire shape with no assignments and a user-facing warning — deliberately
    NOT a second LLM call (the raw-Gemini fallback was retired in #144).

    `warning` overrides the default message so callers can distinguish a
    deterministic failure (e.g. the syllabus is too long for the worker
    token budget, where retrying the same document fails identically) from a
    transient one. When None, the generic "temporarily unavailable / try
    again" message is used.
    """
    return {
        "assignments": [],
        "warnings": [
            warning
            or "Assignment extraction is temporarily unavailable. Please try again."
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
    result = record_agent_usage(
        await syllabus_extraction_agent.run(
            extracted_text, deps=deps, usage_limits=WORKER_LIMITS
        ),
        feature="document", task="syllabus", user_id=user_id,
    )
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
    except UsageLimitExceeded as e:
        # Deterministic for this document — the syllabus exceeds the worker
        # token budget, so re-uploading the same file fails identically. Tell
        # the user to shorten/split it rather than "try again" (#329).
        logger.warning(
            "Syllabus exceeded the worker token budget; degrading to empty result",
            exc_info=e,
        )
        result = _degraded_result(
            text,
            warning=(
                "This syllabus is too long to process automatically. "
                "Try uploading a shorter document, or split it into "
                "multiple files."
            ),
        )
    except UnexpectedModelBehavior as e:
        # A model hiccup, not a doc-size problem — degrade generically (a retry
        # is reasonable). #144: degrade rather than 5xx to keep syllabus upload
        # available on a single model failure.
        logger.warning(
            "Syllabus agent returned unexpected model behavior; degrading to "
            "empty result",
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
