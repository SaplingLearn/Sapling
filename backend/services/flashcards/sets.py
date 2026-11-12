"""Saved flashcard sets: a name, a course, concept names and a couple of
options (the Flashcards home screen). ``routes/flashcards.py`` is the HTTP
layer over these.

A set owns no cards: the client matches ``flashcards`` rows to a set's
concepts by topic name. ``name`` and ``concepts`` are stored in plaintext, like
``flashcards.topic`` and ``graph_nodes.concept_name`` (labels, not study
content); see the table's migration, ``20261112060028_flashcard_sets.sql``.

Every read and write is filtered by ``user_id``, so another student's set
answers exactly like one that does not exist (404).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from db.connection import table
from services.academics import (
    COURSE_NOT_ENROLLED_DETAIL,
    is_enrolled_in_course,
    scoped_user_enrollments,
)
from services.flashcards.errors import (
    FlashcardSetInvalid,
    FlashcardSetLimitReached,
    FlashcardSetNotFound,
)

NAME_MAX = 80
CONCEPTS_MAX = 100
CONCEPT_NAME_MAX = 120
#: Sets one student may hold. Checked before the insert, not atomically with
#: it: two creates racing at the limit can both land. It is a bound on clutter,
#: not a quota anything else depends on.
MAX_SETS_PER_USER = 100

#: The options a set carries, with the value a missing key reads as.
OPTION_DEFAULTS: dict[str, bool] = {"only_due": False, "shuffle": True}

SET_NOT_FOUND_DETAIL = "Flashcard set not found."
EXAM_NOT_FOUND_DETAIL = "Exam not found."

_COLUMNS = "id,user_id,course_id,name,concepts,options,exam_id,created_at,updated_at"


# ── Validation ───────────────────────────────────────────────────────────────


def _clean_name(value: Any) -> str:
    name = value.strip() if isinstance(value, str) else ""
    if not 1 <= len(name) <= NAME_MAX:
        raise FlashcardSetInvalid(f"name must be 1 to {NAME_MAX} characters.")
    return name


def _clean_concepts(value: Any) -> list[str]:
    """Trimmed concept names, de-duplicated case-insensitively (the first
    spelling wins), in the order sent. The 1-100 bound is on the list as sent."""
    if not isinstance(value, list) or not 1 <= len(value) <= CONCEPTS_MAX:
        raise FlashcardSetInvalid(f"concepts must list 1 to {CONCEPTS_MAX} concept names.")
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        concept = item.strip() if isinstance(item, str) else ""
        if not 1 <= len(concept) <= CONCEPT_NAME_MAX:
            raise FlashcardSetInvalid(
                f"each concept name must be 1 to {CONCEPT_NAME_MAX} characters."
            )
        key = concept.casefold()
        if key not in seen:
            seen.add(key)
            out.append(concept)
    return out


def _clean_options(value: Any) -> dict[str, bool]:
    """The options a request sent: only the known keys, only booleans. An
    unknown key or a non-boolean value is refused (never silently dropped), so
    a client typo cannot look like a saved preference."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise FlashcardSetInvalid("options must be an object.")
    unknown = sorted(str(k) for k in value if k not in OPTION_DEFAULTS)
    if unknown:
        raise FlashcardSetInvalid(
            f"unknown option(s): {', '.join(unknown)}. Allowed: {', '.join(OPTION_DEFAULTS)}."
        )
    for key, flag in value.items():
        if not isinstance(flag, bool):
            raise FlashcardSetInvalid(f"option {key} must be true or false.")
    return dict(value)


def _options(stored: Any) -> dict[str, bool]:
    """Both option keys, whatever is stored: a missing, non-boolean or unknown
    stored value reads as the default."""
    stored = stored if isinstance(stored, dict) else {}
    return {
        key: stored[key] if isinstance(stored.get(key), bool) else default
        for key, default in OPTION_DEFAULTS.items()
    }


def _require_own_exam(user_id: str, course_id: str, exam_id: Any) -> str:
    """``exam_id`` must name an assignment in one of the caller's enrollments
    in the set's course. There is no foreign key (an exam can be deleted on its
    own later); this only stops a set from being pointed at an assignment that
    is not the caller's."""
    if not isinstance(exam_id, str) or not exam_id.strip():
        raise FlashcardSetInvalid("exam_id must be an assignment id or null.")
    exam_id = exam_id.strip()
    enrollment_ids = [
        e["id"] for e in scoped_user_enrollments(user_id, course_id=course_id) if e.get("id")
    ]
    rows = table("assignments").select(
        "id",
        filters={"id": f"eq.{exam_id}", "enrollment_id": f"in.({','.join(enrollment_ids)})"},
        limit=1,
    ) if enrollment_ids else []
    if not rows:
        raise FlashcardSetNotFound(EXAM_NOT_FOUND_DETAIL)
    return exam_id


# ── Shape ────────────────────────────────────────────────────────────────────


def _public(row: dict) -> dict:
    """One stored row as the API's ``Set``."""
    concepts = row.get("concepts")
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "course_id": row.get("course_id"),
        "concepts": [c for c in concepts if isinstance(c, str)] if isinstance(concepts, list) else [],
        "options": _options(row.get("options")),
        "exam_id": row.get("exam_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _own_set(user_id: str, set_id: str) -> dict:
    rows = table("flashcard_sets").select(
        _COLUMNS, filters={"id": f"eq.{set_id}", "user_id": f"eq.{user_id}"}, limit=1,
    )
    if not rows:
        raise FlashcardSetNotFound(SET_NOT_FOUND_DETAIL)
    return rows[0]


# ── Operations ───────────────────────────────────────────────────────────────


def list_flashcard_sets(user_id: str, course_id: str | None = None) -> list[dict]:
    """The user's sets, most recently updated first; ``course_id`` narrows to
    one course."""
    filters = {"user_id": f"eq.{user_id}"}
    if course_id:
        filters["course_id"] = f"eq.{course_id}"
    rows = table("flashcard_sets").select(
        _COLUMNS, filters=filters, order="updated_at.desc,id.desc",
    ) or []
    return [_public(r) for r in rows]


def create_flashcard_set(
    user_id: str,
    *,
    name: str,
    course_id: str,
    concepts: list[str],
    options: dict | None = None,
    exam_id: str | None = None,
) -> dict:
    """Save a new set. Raises ``FlashcardSetInvalid`` (a field),
    ``FlashcardSetNotFound`` (not enrolled in the course, or the exam is not
    the caller's) or ``FlashcardSetLimitReached``."""
    name = _clean_name(name)
    concepts = _clean_concepts(concepts)
    stored_options = {**OPTION_DEFAULTS, **_clean_options(options)}
    if not isinstance(course_id, str) or not course_id.strip():
        raise FlashcardSetInvalid("course_id is required.")
    course_id = course_id.strip()
    if not is_enrolled_in_course(user_id, course_id):
        raise FlashcardSetNotFound(COURSE_NOT_ENROLLED_DETAIL)
    if exam_id is not None:
        exam_id = _require_own_exam(user_id, course_id, exam_id)

    held = table("flashcard_sets").select(
        "id", filters={"user_id": f"eq.{user_id}"}, limit=MAX_SETS_PER_USER,
    ) or []
    if len(held) >= MAX_SETS_PER_USER:
        raise FlashcardSetLimitReached(
            f"You can save up to {MAX_SETS_PER_USER} flashcard sets. Delete one to add another."
        )

    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "course_id": course_id,
        "name": name,
        "concepts": concepts,
        "options": stored_options,
        "exam_id": exam_id,
        "created_at": now,
        "updated_at": now,
    }
    saved = table("flashcard_sets").insert(row)
    return _public(saved[0] if saved else row)


def _patch_for(user_id: str, current: dict, changes: dict) -> dict[str, Any]:
    """The validated columns ``changes`` writes to the stored row ``current``."""
    patch: dict[str, Any] = {}
    if "name" in changes:
        patch["name"] = _clean_name(changes["name"])
    if "concepts" in changes:
        patch["concepts"] = _clean_concepts(changes["concepts"])
    # `options: null` changes nothing (on create it means "the defaults"), so
    # it must not count as a write and bump the set to the top of the list.
    if changes.get("options") is not None:
        patch["options"] = {**_options(current.get("options")), **_clean_options(changes["options"])}
    if "exam_id" in changes:
        exam_id = changes["exam_id"]
        patch["exam_id"] = (
            None if exam_id is None
            else _require_own_exam(user_id, current.get("course_id") or "", exam_id)
        )
    return patch


def update_flashcard_set(user_id: str, set_id: str, changes: dict) -> dict:
    """Change the fields present in ``changes`` (``name``, ``concepts``,
    ``options``, ``exam_id``) and nothing else. ``exam_id: None`` clears the
    exam; ``options`` is merged over the stored options, so sending one key
    leaves the other as it was. Raises ``FlashcardSetNotFound`` when the set is
    not this user's."""
    current = _own_set(user_id, set_id)
    patch = _patch_for(user_id, current, changes)
    if not patch:
        return _public(current)

    # The table's BEFORE UPDATE trigger stamps updated_at as well; sending it
    # keeps the "most recently updated first" order true for any writer.
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated = table("flashcard_sets").update(
        patch, filters={"id": f"eq.{set_id}", "user_id": f"eq.{user_id}"},
    )
    if not updated:
        # Deleted between the read and the write.
        raise FlashcardSetNotFound(SET_NOT_FOUND_DETAIL)
    return _public(updated[0])


def delete_flashcard_set(user_id: str, set_id: str) -> None:
    """Delete one of the user's sets (no card is touched). Raises
    ``FlashcardSetNotFound`` when the set is not this user's."""
    _own_set(user_id, set_id)
    table("flashcard_sets").delete(
        filters={"id": f"eq.{set_id}", "user_id": f"eq.{user_id}"},
    )


__all__ = [
    "MAX_SETS_PER_USER",
    "OPTION_DEFAULTS",
    "create_flashcard_set",
    "delete_flashcard_set",
    "list_flashcard_sets",
    "update_flashcard_set",
]
