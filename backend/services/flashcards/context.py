"""Grounding context for flashcard generation (#118, moved from
``routes/flashcards.py``): the tutor session summary, the course's library
documents and the student's weak concepts."""
from __future__ import annotations

import json
import logging

from learning.bkt import is_weak
from db.connection import table
from services.academics import (
    course_offering_ids,
    resolve_offering,
    term_id_for_label,
    user_enrolled_course_ids,
)
from services.encryption import decrypt_if_present, decrypt_json

logger = logging.getLogger(__name__)


def _get_session_summary(session_id: str) -> str:
    try:
        rows = table("sessions").select(
            "summary_json", filters={"id": f"eq.{session_id}"}, limit=1
        )
        if not rows or not rows[0].get("summary_json"):
            return ""
        raw = rows[0]["summary_json"]
        if isinstance(raw, str):
            try:
                return json.dumps(decrypt_json(raw))
            except Exception:
                return raw
        return json.dumps(raw)
    except Exception:
        return ""


# Grounding reads at most this many of the course's documents, newest first:
# the prompt inlines every summary + concept list it is handed.
_COURSE_DOC_LIMIT = 50
_COURSE_DOC_COLS = "file_name,category,summary,concept_notes"


def _enrolled_course_by_name(user_id: str, course_name: str) -> str | None:
    """The abstract id of the course named ``course_name`` that the user is
    enrolled in, or None.

    Catalog names are not unique (0020: `courses` is the abstract catalog,
    with no user_id column), so the match is restricted to the user's
    enrolled courses and, if several same-named ones remain, the lowest id
    wins — deterministic, one bounded read, no per-candidate lookups."""
    enrolled = user_enrolled_course_ids(user_id)
    if not enrolled:
        return None
    rows = table("courses").select(
        "id",
        filters={
            "course_name": f"eq.{course_name}",
            "id": f"in.({','.join(sorted(enrolled))})",
        },
        order="id.asc",
        limit=1,
    ) or []
    return rows[0]["id"] if rows else None


def _get_course_documents(
    user_id: str,
    course_name: str,
    semester: str | None = None,
    course_id: str | None = None,
) -> list[dict]:
    """
    Return the user's own library documents grounding generation for a course.

    The course: ``course_id`` when the client sent it (the Study screen
    always does for a selected course); otherwise ``course_name`` matched
    against the courses the user is ENROLLED in (see
    :func:`_enrolled_course_by_name`).

    The documents (keyed on the offering, 0025), always filtered to the
    user's own rows:
    - with a ``semester`` (#141): STRICTLY that term's offering — a term with
      no offering contributes nothing;
    - without one: every offering of the course (``course_offering_ids``),
      because uploads are stamped with the CURRENT term's offering at upload
      time, so a single-offering read loses last term's notes at rollover.

    Unenrolled courses: an explicit ``course_id`` still reads the student's
    own documents in that course's offerings (they uploaded them; unenrolling
    does not unshare their own notes from them). The name-match path only
    sees enrolled courses, because a bare name cannot be told apart from a
    same-named course elsewhere.

    No course (a free-text topic, or a name the user is not enrolled in) →
    NO documents, with or without a semester. This used to fall back to every
    document the user owns, which grounded a topic in unrelated courses.
    Lookup failures are logged and degrade to no documents, so generation
    still works.
    """
    try:
        if not course_id:
            course_id = _enrolled_course_by_name(user_id, course_name)
            if course_id is None:
                logger.info(
                    "flashcard generate: topic matches no enrolled course; "
                    "generating without library documents"
                )
                return []
        if semester:
            term_id = term_id_for_label(semester)
            offering_id = (
                resolve_offering(course_id, term_id, fallback=False) if term_id else None
            )
            offering_ids = [offering_id] if offering_id else []
        else:
            # None = could not tell (logged by academics); [] = no offerings.
            offering_ids = course_offering_ids(course_id) or []
        if not offering_ids:
            return []
        docs = table("documents").select(
            _COURSE_DOC_COLS,
            filters={
                "user_id": f"eq.{user_id}",
                "offering_id": f"in.({','.join(offering_ids)})",
                "deleted_at": "is.null",
            },
            order="created_at.desc",
            limit=_COURSE_DOC_LIMIT,
        ) or []
        for d in docs:
            d["summary"] = decrypt_if_present(d.get("summary"))
            notes_raw = d.get("concept_notes")
            if isinstance(notes_raw, str):
                d["concept_notes"] = decrypt_json(notes_raw)
        return docs
    except Exception:
        logger.warning(
            "flashcard generate: could not load course documents; "
            "generating without them", exc_info=True,
        )
        return []


def _unit(score) -> float:
    """A stored mastery score clamped to [0, 1] (tier_for rejects anything
    outside it; old rows occasionally drift)."""
    try:
        return max(0.0, min(1.0, float(score or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _get_weak_concepts(user_id: str, course_name: str) -> list[str]:
    """
    Return concept names the student is weak on — below the "learning" floor
    of `learning.bkt.tier_for` (PKG-14b), i.e. "struggling" or "unexplored".

    Was a local `< 0.4` (#557), which is not any tier boundary: concepts in
    [0.4, 0.45) read as "struggling" on the Tree but were never offered for
    practice here — the surface whose entire job is drilling weak concepts
    silently skipped a slice of them.
    """
    try:
        rows = table("graph_nodes").select(
            "concept_name,mastery_score",
            filters={"user_id": f"eq.{user_id}", "subject": f"eq.{course_name}"},
        )
        if not rows:
            # Try without subject filter — return all low-mastery concepts
            rows = table("graph_nodes").select(
                "concept_name,mastery_score",
                filters={"user_id": f"eq.{user_id}"},
            )
        weak = sorted(
            (r for r in (rows or []) if is_weak(_unit(r.get("mastery_score")))),
            key=lambda r: r.get("mastery_score") or 0,
        )
        # Weakest first, THEN cap. The cap used to truncate in PostgREST row
        # order, which was survivable while the floor was 0.4 and is not now
        # that #557 widened it to 0.45: the newly-admitted [0.4, 0.45)
        # concepts could displace 0.0-0.1 ones purely on row order, leaving
        # the surface whose job is drilling the weakest concepts drilling the
        # least-weak of the weak.
        return [r["concept_name"] for r in weak[:15]]
    except Exception:
        return []
