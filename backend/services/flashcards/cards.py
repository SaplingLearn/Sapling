"""Flashcard rows (#118, moved from ``routes/flashcards.py``): the list, rate
and delete handlers' bodies, the row a new card is stored as, and the
library-document read behind the import flow."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from db.connection import table
from services import events_service
from services.academics import offering_course_id, term_id_for_label
from services.achievement_service import check_achievements
from services.encryption import decrypt_if_present, decrypt_json, encrypt_if_present
from services.flashcards.errors import NotFound, StorageError

logger = logging.getLogger(__name__)

CARD_NOT_FOUND_DETAIL = "Flashcard not found"

#: What a failed read says when the database has no ``flashcards`` table yet.
_MISSING_TABLE_MARKERS = ("not found", "does not exist", "42p01")

#: The stored columns a listed card carries. The list adds two derived keys:
#: `course_id`, and `due_at` (always None today; see `list_flashcards`).
_CARD_FIELDS = (
    "id", "user_id", "topic", "offering_id", "front", "back", "times_reviewed",
    "last_rating", "last_reviewed_at", "created_at",
)


def list_flashcards(
    user_id: str, topic: str | None = None, semester: str | None = None
) -> list[dict]:
    """The user's cards, newest first, decrypted; ``topic`` narrows to one
    topic and ``semester`` to one term (#141). Errors propagate
    (:func:`get_flashcards` is the route's tolerant form)."""
    filters = {"user_id": f"eq.{user_id}"}
    if topic:
        filters["topic"] = f"eq.{topic}"

    # `*`, then projected to _CARD_FIELDS, so the list never names a column a
    # database may lack and never returns one it should not.
    #
    # `due_at` is the case in point. No migration in this repository adds
    # `flashcards.due_at`: it came with the reverted learning-loop series
    # (20260927035346_learning_flashcards_fsrs, with fsrs_s/fsrs_d/reps/lapses),
    # which some databases still carry and others never had. Naming it in
    # `select=` would be a PostgREST 400 on the second kind and take the whole
    # list down. And nothing writes it (`rate_card` records only the review
    # count, rating and time), so on the first kind a value left behind by that
    # series would be a card frozen "due" forever. So the stored column is not
    # read at all: every card answers `due_at: None` (the key stays, for the
    # client's type) until a scheduler owns the column.
    rows = [
        {**{field: r.get(field) for field in _CARD_FIELDS}, "due_at": None}
        for r in table("flashcards").select(
            "*", filters=filters, order="created_at.desc"
        ) or []
    ]
    for r in rows:
        r["front"] = decrypt_if_present(r.get("front"))
        r["back"] = decrypt_if_present(r.get("back"))
        # The abstract course the card's offering belongs to (the id the rest
        # of the API speaks), so the Flashcards page can show a course's cards
        # by what they belong to. It used to match on the card's TOPIC
        # containing the course's name, which hid every deck named for a
        # concept ("Recursion") the moment a course was picked. None for a card
        # with no offering.
        r["course_id"] = offering_course_id(r["offering_id"]) if r.get("offering_id") else None
    if semester:
        # Term scoping (#141). This route is user-wide (no course id), so
        # the filter works on the cards' offering: cards from the selected
        # term stay, other terms' cards are hidden, and term-LESS cards
        # (offering_id NULL — e.g. AI-generated) stay visible under any
        # selection so picking a term never strands them. An unknown label
        # degrades to term-less cards only — never a 500.
        term_id = term_id_for_label(semester)
        allowed: set[str] = set()
        if term_id:
            offs = table("course_offerings").select(
                "id", filters={"term_id": f"eq.{term_id}"}
            ) or []
            allowed = {o["id"] for o in offs if o.get("id")}
        rows = [
            r for r in rows
            if r.get("offering_id") is None or r["offering_id"] in allowed
        ]
    return rows


def get_flashcards(
    user_id: str, topic: str | None = None, semester: str | None = None
) -> list[dict]:
    """:func:`list_flashcards` as the list route answers it: no user, or a
    database with no ``flashcards`` table yet, is no cards; any other failure
    is a ``StorageError``."""
    if not user_id:
        return []
    try:
        return list_flashcards(user_id, topic, semester)
    except Exception as e:
        if any(marker in str(e).lower() for marker in _MISSING_TABLE_MARKERS):
            return []
        raise StorageError(str(e)) from e


# ── New cards ────────────────────────────────────────────────────────────────


def new_card_rows(
    user_id: str, topic: str, offering_id: str | None, cards: list[dict]
) -> list[dict]:
    """Unsaved ``flashcards`` rows for ``cards`` (``{front, back}``), front and
    back still in plaintext: :func:`encrypted_card` is what gets stored."""
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "offering_id": offering_id,
            "topic": topic,
            "front": c["front"],
            "back": c["back"],
            "times_reviewed": 0,
            "last_reviewed_at": None,
            "created_at": now,
        }
        for c in cards
    ]


def encrypted_card(row: dict) -> dict:
    """``row`` as it is written: 🔒 ``front`` / ``back``."""
    return {
        **row,
        "front": encrypt_if_present(row["front"]),
        "back": encrypt_if_present(row["back"]),
    }


# ── Rate / delete ────────────────────────────────────────────────────────────


def _own_card(user_id: str, card_id: str, columns: str) -> dict:
    """The user's card, or ``NotFound`` (the same answer for a card that does
    not exist and one that is another student's)."""
    try:
        rows = table("flashcards").select(
            columns,
            filters={"id": f"eq.{card_id}", "user_id": f"eq.{user_id}"},
            limit=1,
        )
    except Exception as e:
        raise StorageError(str(e)) from e
    if not rows:
        raise NotFound(CARD_NOT_FOUND_DETAIL)
    return rows[0]


def rate_card(user_id: str, card_id: str, rating: int) -> None:
    """Record one review of the user's card (count, rating, time)."""
    card = _own_card(user_id, card_id, "id,times_reviewed")
    table("flashcards").update(
        {
            "times_reviewed": (card["times_reviewed"] or 0) + 1,
            "last_rating": rating,
            "last_reviewed_at": datetime.now(timezone.utc).isoformat(),
        },
        filters={"id": f"eq.{card_id}", "user_id": f"eq.{user_id}"},
    )
    events_service.log_event(
        "flashcard.reviewed",
        category="usage",
        user_id=user_id,
        payload={"card_id": card_id, "rating": rating},
    )

    # The review counter is the only thing that advances `flashcards_reviewed`
    # (Quick Draw: review 100 cards), so this is its only possible dispatch
    # point. Post-commit: the review is already recorded, so a failing check
    # must not fail the rating.
    try:
        check_achievements(user_id, "flashcards_reviewed", {})
    except Exception:
        logger.exception(
            "achievement dispatch failed after card rating user=%s card=%s",
            user_id, card_id,
        )


def delete_card(user_id: str, card_id: str) -> None:
    """Delete the user's card."""
    _own_card(user_id, card_id, "id")
    table("flashcards").delete(
        filters={"id": f"eq.{card_id}", "user_id": f"eq.{user_id}"}
    )


# ── Library documents (the import flow's source text) ────────────────────────


def library_doc_source_text(user_id: str, document_id: str) -> str | None:
    """The text a library document contributes to an import generation (its
    summary plus concept notes), or None when the user has no such live
    document."""
    rows = table("documents").select(
        "id,user_id,summary,concept_notes,file_name",
        filters={
            "id": f"eq.{document_id}",
            "user_id": f"eq.{user_id}",
            "deleted_at": "is.null",
        },
        limit=1,
    )
    if not rows:
        return None
    doc = rows[0]
    doc_summary = decrypt_if_present(doc.get("summary")) or ""
    notes_raw = doc.get("concept_notes")
    if isinstance(notes_raw, str):
        try:
            doc_notes = decrypt_json(notes_raw)
        except Exception:
            doc_notes = notes_raw
    else:
        doc_notes = notes_raw or {}
    parts = [doc_summary, str(doc_notes)]
    return "\n\n".join(p for p in parts if p)
