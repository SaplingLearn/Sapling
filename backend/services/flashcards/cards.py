"""Flashcard rows (#118, moved from ``routes/flashcards.py``): the list, rate
and delete handlers' bodies, the row a new card is stored as, and the
library-document read behind the import flow. The list is in FSRS review
order and a rating is an FSRS review (learning-loop PKG-11 / PKG-14b: for
every student, no gate)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from db.connection import is_missing_relation, table
from learning.flashcard_fsrs import flashcard_fsrs_update
from learning.fsrs import order_due
from learning.params import FLASHCARD_RATING_TO_FSRS
from services import events_service
from services.academics import offering_course_id, term_id_for_label
from services.achievement_service import check_achievements
from services.encryption import (
    EncryptionError,
    bind,
    decrypt_if_present,
    decrypt_json,
    encrypt_if_present,
)
from services.flashcards.errors import NotFound, StorageError, Unprocessable
from services.timestamps import parse_ts

logger = logging.getLogger(__name__)

CARD_NOT_FOUND_DETAIL = "Flashcard not found"

#: The stored columns a listed card carries (the list adds the derived
#: `course_id`): the card, then its FSRS state (PKG-11, migration
#: 20260927035346_learning_flashcards_fsrs; `rate_card` writes it).
_LEGACY_LIST_COLS = (
    "id,user_id,topic,offering_id,front,back,times_reviewed,last_rating,"
    "last_reviewed_at,created_at"
)
_FSRS_LIST_COLS = ",fsrs_d,fsrs_s,due_at,reps,lapses"
#: What `rate_card` reads of the card it updates (with the loop on, its
#: offering too: the course whose retention target it is scheduled at).
_RATE_COLS = "id,times_reviewed,last_reviewed_at,fsrs_d,fsrs_s,reps,lapses"
_RATE_COLS_LOOP = _RATE_COLS + ",offering_id"
RATING_INVALID_DETAIL = "rating must be one of 1, 2, 3"


def _order_due_rows(rows: list[dict], now: datetime) -> list[dict]:
    """PKG-11: due cards in learning.fsrs.order_due's order (|R − threshold|
    ascending, spec §3.2). ADAPTER (HANDOFF-02: `order_due(items, now, *,
    stability_key="fsrs_s", last_review_key=...)`): a flashcard's stability
    is `fsrs_s` and its last review is `last_reviewed_at`. If PKG-02's
    signature changes, change THIS function only."""
    if not rows:
        return []
    return list(order_due(rows, now, last_review_key="last_reviewed_at"))


def _loop_order(rows: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    """PKG-11: (ordered rows, due rows). Due first (`due_at` <= now, in
    _order_due_rows order), then never rated on the loop path (`fsrs_s` null,
    query order), then not yet due by `due_at` ascending. A null `due_at` is
    never due."""
    due, fresh, later = [], [], []
    for r in rows:
        due_at = parse_ts(r.get("due_at"))
        if due_at is not None and due_at <= now:
            due.append(r)
        elif r.get("fsrs_s") is None:
            fresh.append(r)
        else:
            later.append(r)
    later.sort(key=lambda r: parse_ts(r.get("due_at")) or now)
    ordered_due = _order_due_rows(due, now)
    return ordered_due + fresh + later, ordered_due


def list_flashcards(
    user_id: str, topic: str | None = None, semester: str | None = None
) -> list[dict]:
    """The user's cards, newest first, decrypted; ``topic`` narrows to one
    topic and ``semester`` to one term (#141). Errors propagate
    (:func:`get_flashcards` is the route's tolerant form)."""
    filters = {"user_id": f"eq.{user_id}"}
    if topic:
        filters["topic"] = f"eq.{topic}"

    rows = table("flashcards").select(
        _LEGACY_LIST_COLS + _FSRS_LIST_COLS,
        filters=filters, order="created_at.desc"
    ) or []
    for r in rows:
        r["front"] = decrypt_if_present(r.get("front"), bind=bind("flashcards", "front", r))
        r["back"] = decrypt_if_present(r.get("back"), bind=bind("flashcards", "back", r))
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
            allowed = _offerings_in_term(
                {r["offering_id"] for r in rows if r.get("offering_id")}, term_id,
            )
        rows = [
            r for r in rows
            if r.get("offering_id") is None or r["offering_id"] in allowed
        ]
    return rows


#: Offering ids per ``in.(…)`` filter: keeps the query string bounded.
_OFFERING_ID_CHUNK = 50


def _offerings_in_term(offering_ids: set[str], term_id: str) -> set[str]:
    """Which of ``offering_ids`` belong to ``term_id``. Asked by the cards' own
    ids, never by reading the whole term: a term has more offerings than one
    PostgREST response (max_rows) holds, and an offering past the cut would
    hide its cards."""
    ids = sorted(offering_ids)
    allowed: set[str] = set()
    for i in range(0, len(ids), _OFFERING_ID_CHUNK):
        offs = table("course_offerings").select(
            "id",
            filters={
                "id": f"in.({','.join(ids[i:i + _OFFERING_ID_CHUNK])})",
                "term_id": f"eq.{term_id}",
            },
        ) or []
        allowed.update(o["id"] for o in offs if o.get("id"))
    return allowed


def get_flashcards(
    user_id: str, topic: str | None = None, semester: str | None = None,
    *, due_only: bool = False,
) -> dict:
    """:func:`list_flashcards` as the list route answers it, in FSRS review
    order (:func:`_loop_order`): ``{flashcards, due_count}``, only the due
    cards when ``due_only``. No user, or a database with no ``flashcards``
    table yet, is no cards; any other failure is a ``StorageError``."""
    if not user_id:
        return {"flashcards": [], "due_count": 0}
    try:
        rows, due = _loop_order(
            list_flashcards(user_id, topic, semester), datetime.now(timezone.utc),
        )
    except Exception as e:
        # Only the exactly-known "no such table" (PostgREST's error code, not
        # the message text, which any 404 or missing-column error can share).
        if is_missing_relation(e):
            return {"flashcards": [], "due_count": 0}  # one shape on every path
        raise StorageError(str(e)) from e
    return {"flashcards": due if due_only else rows, "due_count": len(due)}


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
    """``row`` as it is written: 🔒 ``front`` / ``back``, bound to the row's
    id (minted by :func:`new_card_rows`, M13)."""
    return {
        **row,
        "front": encrypt_if_present(row["front"], bind=bind("flashcards", "front", row)),
        "back": encrypt_if_present(row["back"], bind=bind("flashcards", "back", row)),
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


def rate_card(user_id: str, card_id: str, rating: int, *, loop_on: bool = False) -> dict:
    """Record one review of the user's card: the count, rating and time, plus
    its FSRS state (PKG-11 / PKG-14b: every rating is an FSRS review, 1/2/3 ->
    Again/Hard/Good via ``FLASHCARD_RATING_TO_FSRS``; any other value is
    ``Unprocessable``). Answers the card's next ``due_at`` and the FSRS
    rating.

    ``loop_on`` (the route's learning-loop gate, #866 K54): the card is
    scheduled at its course's retention target — the one Study's review
    schedules the same card at (``learning.review.card_retention``: an exam
    window's 0.95, a large set's 0.85). Off, the default as before: there is
    no review queue to agree with."""
    fsrs_rating = FLASHCARD_RATING_TO_FSRS.get(rating)
    if fsrs_rating is None:
        raise Unprocessable(RATING_INVALID_DETAIL)
    card = _own_card(user_id, card_id, _RATE_COLS_LOOP if loop_on else _RATE_COLS)
    now = datetime.now(timezone.utc)
    payload = {
        "times_reviewed": (card["times_reviewed"] or 0) + 1,
        "last_rating": rating,
        "last_reviewed_at": now.isoformat(),
    }
    # PKG-12 reopen: the pure helper learning/review.py shares; it returns
    # the three columns above (same values) plus the FSRS five.
    payload.update(flashcard_fsrs_update(card, rating, now=now, **_retention_kw(user_id, card, loop_on)))
    table("flashcards").update(
        payload, filters={"id": f"eq.{card_id}", "user_id": f"eq.{user_id}"},
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
    return {"due_at": payload["due_at"], "fsrs_rating": fsrs_rating}


def _retention_kw(user_id: str, card: dict, loop_on: bool) -> dict:
    """`flashcard_fsrs_update`'s retention for `rate_card` (#866 K54): the
    card's course's target with the loop on; none (the default) off."""
    if not loop_on:
        return {}
    from learning.review import card_retention  # the loop's module, only on its path

    return {"retention": card_retention(user_id, card)}


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
    doc_summary = decrypt_if_present(doc.get("summary"), bind=bind("documents", "summary", doc)) or ""
    notes_raw = doc.get("concept_notes")
    if isinstance(notes_raw, str):
        try:
            doc_notes = decrypt_json(notes_raw, bind=bind("documents", "concept_notes", doc))
        except EncryptionError:
            doc_notes = {}  # refused (moved/tampered): never the raw value
        except Exception:
            doc_notes = notes_raw
    else:
        doc_notes = notes_raw or {}
    parts = [doc_summary, str(doc_notes)]
    return "\n\n".join(p for p in parts if p)
