"""Course and offering resolution for a tutor session (#118, moved verbatim
from routes/learn.py): topic -> abstract course, session -> offering -> course,
the course's code/name, its BU catalog chunk, and the offering a new session
row keys on.

`_get_catalog_chunk` is also the quiz's catalog read (services/quiz/grounding.py
imports it through ``services.tutor``).
"""
from __future__ import annotations

import logging

from starlette.concurrency import run_in_threadpool

from db.connection import table
from models import StartSessionBody
from services.academics import offering_course_id, require_course_enrollment, resolve_offering
from services.encryption import bind, decrypt_if_present

logger = logging.getLogger(__name__)


#: The reads `_get_course_id_for_topic` (and its sync twin) make, in order:
#: the student's enrolled courses (matched on code / name / subject-root
#: label), then their graph nodes by concept name, then by the legacy subject.
_ENROLLED_COLUMNS = (
    "offering_id,course_offerings!inner(course_id,courses!inner(course_code,course_name))"
)


def _topic_reads(topic_trim: str, user_id: str) -> tuple[tuple[str, str, dict, int | None], ...]:
    """(table, columns, filters, limit) per read, in the order they are tried."""
    mine = {"user_id": f"eq.{user_id}"}
    return (
        ("enrollments", _ENROLLED_COLUMNS, mine, None),
        ("graph_nodes", "course_id", {**mine, "concept_name": f"eq.{topic_trim}"}, 10),
        # Legacy support: the subject field.
        ("graph_nodes", "course_id", {**mine, "subject": f"eq.{topic_trim}"}, 1),
    )


def _course_from(step: int, rows, topic_trim: str) -> tuple[bool, str | None]:
    """(found, abstract course id) for one read's rows."""
    if step == 0:
        return _enrolled_course_match(rows or [], topic_trim)
    for row in rows or []:
        if row.get("course_id"):
            return True, row["course_id"]
    return False, None


def _enrollment_read_failed(topic_trim: str, user_id: str, exc: Exception) -> None:
    # Never the topic itself: it is the student's typed text.
    logger.warning(
        "Failed to resolve course_id for topic (%d chars) user_id=%r: %s",
        len(topic_trim), user_id, type(exc).__name__,
    )


def _select_kwargs(filters: dict, limit: int | None) -> dict:
    return {"filters": filters, **({"limit": limit} if limit else {})}


async def _get_course_id_for_topic(topic: str, user_id: str) -> str:
    """
    Find the course_id associated with a topic/concept for a user.
    First checks if topic matches a course_code or course_name,
    then falls back to finding via graph_nodes.

    Enrollment keys on an offering; the abstract course (which the session and
    knowledge graph key on) sits behind offering_id → course_offerings.course_id
    → courses, so the topic is matched against the abstract course's code/name.
    A failed enrollment read is logged and the graph fallbacks still run.
    """
    topic_trim = (topic or "").strip()
    if not topic_trim:
        return ""
    for step, (name, columns, filters, limit) in enumerate(_topic_reads(topic_trim, user_id)):
        try:
            rows = await table(name).aselect(columns, **_select_kwargs(filters, limit))
            found, course_id = _course_from(step, rows, topic_trim)
        except Exception as exc:
            if step:  # only the enrollment read is best-effort
                raise
            _enrollment_read_failed(topic_trim, user_id, exc)
            continue
        if found:
            return course_id
    return ""


def _enrolled_course_match(enrolled, topic_trim: str) -> tuple[bool, str | None]:
    """(matched, abstract course id) for the first enrolled course whose code,
    name or graph subject-root label is the topic. Shared by
    `_get_course_id_for_topic` and its sync twin."""
    for row in enrolled:
        offering = row.get("course_offerings", {})
        if not isinstance(offering, dict):
            continue
        abstract_course_id = offering.get("course_id")
        course = offering.get("courses", {}) if isinstance(offering.get("courses"), dict) else {}
        course_code = course.get("course_code", "") or ""
        course_name = course.get("course_name", "") or ""

        # Match on course_code (exact or case-insensitive)
        if course_code and topic_trim.upper() == course_code.upper():
            return True, abstract_course_id
        # Match on course_name
        if course_name and topic_trim.lower() == course_name.lower():
            return True, abstract_course_id
        # Same label as graph subject roots (graph_service)
        label = f"{course_code} - {course_name}" if course_code else course_name
        if label and topic_trim == label:
            return True, abstract_course_id
    return False, None


def _get_course_id_for_topic_sync(topic: str, user_id: str) -> str:
    """`_get_course_id_for_topic` for sync callers: the learning loop's
    session opener, which resolves the course in sync code. The same reads
    (`_topic_reads`), the same matching (`_course_from`), the same logging."""
    topic_trim = (topic or "").strip()
    if not topic_trim:
        return ""
    for step, (name, columns, filters, limit) in enumerate(_topic_reads(topic_trim, user_id)):
        try:
            rows = table(name).select(columns, **_select_kwargs(filters, limit))
            found, course_id = _course_from(step, rows, topic_trim)
        except Exception as exc:
            if step:  # only the enrollment read is best-effort
                raise
            _enrollment_read_failed(topic_trim, user_id, exc)
            continue
        if found:
            return course_id
    return ""


async def _get_session_offering_id(session_id: str) -> str:
    """Get the offering_id a session is scoped to, if any.

    Sessions key on the offering (0025); the abstract course id (the graph
    key) is derived from it via ``offering_course_id`` where needed.
    """
    rows = await table("sessions").aselect("offering_id", filters={"id": f"eq.{session_id}"}, limit=1)
    if rows and rows[0].get("offering_id"):
        return rows[0]["offering_id"]
    return ""


async def _session_course_id(session_id: str) -> str | None:
    """The abstract course (the graph key) behind a session's offering."""
    offering_id = await _get_session_offering_id(session_id)
    return await run_in_threadpool(offering_course_id, offering_id) if offering_id else ""


def _get_course_info(course_id: str) -> dict:
    """Get course info (code and name) for a course_id."""
    if not course_id:
        return {"course_code": "", "course_name": ""}
    try:
        rows = table("courses").select(
            "course_code,course_name",
            filters={"id": f"eq.{course_id}"},
            limit=1,
        )
        if rows:
            return {
                "course_code": rows[0].get("course_code", ""),
                "course_name": rows[0].get("course_name", ""),
            }
    except Exception as e:
        logger.warning("Failed to load course info for course_id=%r: %s", course_id, e)
    return {"course_code": "", "course_name": ""}


def _get_catalog_chunk(course_code: str) -> str:
    """Return the catalog chunk_text for a BU course code, or empty string.

    Fetches up to 5 catalog chunks and returns the longest one — handles
    courses that were scraped from multiple listing pages (duplicates with
    slightly different content) by preferring the most complete entry.
    """
    if not course_code:
        return ""
    try:
        rows = table("course_chunks").select(
            "id,chunk_text",
            filters={"course_id": f"eq.{course_code}", "category": "eq.catalog"},
            limit=5,
        )
        # Decrypt BEFORE the "Prerequisites:" test and the longest-chunk choice
        # below (#484): both read the text, and against ciphertext the first
        # would never match and the second would compare base64 lengths.
        for row in rows or []:
            row["chunk_text"] = decrypt_if_present(
                row.get("chunk_text"), bind=bind("course_chunks", "chunk_text", row),
            ) or ""
        if rows:
            # Prefer a chunk that has an explicit Prerequisites line; fall back
            # to the longest chunk. Handles courses scraped from two listing
            # pages where one entry has prerequisites and one doesn't.
            with_prereq = [r for r in rows if "Prerequisites:" in r.get("chunk_text", "")]
            candidates = with_prereq if with_prereq else rows
            return max(candidates, key=lambda r: len(r.get("chunk_text", "")))["chunk_text"]
    except Exception as e:
        logger.warning("[RAG] Failed to load catalog chunk for %r: %s", course_code, e)
    return ""


def _session_offering(body: StartSessionBody, course_id: str) -> str:
    """The offering a new session row keys on. A client-named
    ``body.course_id`` passes the #115 enrollment gate (404 unless the student
    is enrolled) and lands on the offering it returns; a topic-derived course
    keeps the current-term resolution."""
    if body.course_id:
        return require_course_enrollment(body.user_id, body.course_id)
    return resolve_offering(course_id, create=True) if course_id else ""
