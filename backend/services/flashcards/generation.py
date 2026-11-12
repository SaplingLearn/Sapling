"""Generate flashcards for a topic (#118: the body of ``routes/flashcards.py``'s
``generate``): gather the grounding context, run the flashcard agent, store
the cards and answer with them."""
from __future__ import annotations

import logging

from db.connection import table
from services import events_service
from services.academics import (
    enrolled_offering_for_course,
    resolve_offering,
    term_id_for_label,
)
from services.achievement_service import check_achievements
from services.flashcards.cards import encrypted_card, new_card_rows
from services.flashcards.context import (
    _get_course_documents,
    _get_session_summary,
    _get_weak_concepts,
)
from services.flashcards.errors import StorageError, UpstreamError
from services.flashcards.importing import generate_flashcards
from services.llm_budget import reraise_budget_refusal
from services.tutor_sessions import session_owned_by

logger = logging.getLogger(__name__)


def generation_failed(exc: BaseException) -> UpstreamError:
    """The error a failed generation is answered with: the routes'
    long-standing 502 — except that a budget refusal in ``exc`` is re-raised as
    itself (``llm_budget.reraise_budget_refusal``), so main.py answers it with
    the friendly 429 the tutor and uploads use (#838)."""
    reraise_budget_refusal(exc)
    return UpstreamError(f"Gemini error: {exc}")


def _session_context(user_id: str, session_id: str | None) -> str:
    """The tutor session's summary, as optional extra context.

    The caller being ``user_id`` is not enough: the session must ALSO be
    theirs, or this decrypts a classmate's tutor summary into the prompt. The
    summary is optional enrichment, so a missing, foreign or unreadable
    session id is dropped (generate without it) rather than failing the
    request — and the ownership decision comes before anything of it is read.
    """
    if not session_id:
        return ""
    try:
        owned = session_owned_by(session_id, user_id)
    except Exception:
        logger.warning(
            "Flashcard session-ownership lookup failed; generating without session context",
            exc_info=True,
        )
        return ""
    return _get_session_summary(session_id) if owned else ""


def _card_offering(user_id: str, course_id: str | None, semester: str | None) -> str | None:
    """The offering the generated cards are filed under (None: no course was
    sent, or the id matches no offering, and the cards carry no course).

    The card list scopes by the SELECTED semester's offerings
    (``cards.list_flashcards``), so the first choice is that term's offering
    of the course: filed anywhere else, the cards vanish from the list on the
    next load and the page generates (and bills) them again. Then the offering
    the student is enrolled in, which is where their course lives when no
    semester is selected. Last, what the import route files under: the current
    term's offering, else any.
    """
    if not course_id:
        return None
    term_id = term_id_for_label(semester) if semester else None
    return (
        (resolve_offering(course_id, term_id, fallback=False) if term_id else None)
        or enrolled_offering_for_course(user_id, course_id)
        or resolve_offering(course_id)
    )


def _save(rows: list[dict]) -> None:
    try:
        for row in rows:
            table("flashcards").insert(encrypted_card(row))
    except Exception as e:
        raise StorageError(
            f"Failed to save flashcards. Has the flashcards table been created in Supabase? Error: {e}"
        ) from e


def _after_generation(user_id: str, card_count: int, documents: int, weak_concepts: int) -> None:
    """The ``flashcard.generated`` event and the achievement check."""
    # #117 taxonomy (+ the ADR 0028 PostHog mirror). Counts only — never the
    # topic or card text. Zero cards is not a generation (it would inflate the
    # funnel).
    if card_count:
        events_service.log_event(
            "flashcard.generated",
            category="usage",
            user_id=user_id,
            payload={
                "card_count": card_count,
                "documents_used": documents,
                "weak_concepts_used": weak_concepts,
                "via": "topic",
            },
        )
    try:
        check_achievements(user_id, "flashcards_created", {})
    except Exception:
        pass


def generate(
    user_id: str,
    *,
    topic: str,
    count: int = 5,
    session_id: str | None = None,
    semester: str | None = None,
    course_id: str | None = None,
) -> dict:
    """Generate AI flashcards grounded in the student's actual course material
    (their library documents for the course, term-scoped when a ``semester`` is
    selected (#141), plus the concepts they are weak on) and store them.

    Raises ``UpstreamError`` when the model call fails and ``StorageError``
    when the cards cannot be saved.
    """
    context = _session_context(user_id, session_id)
    documents = _get_course_documents(user_id, topic, semester=semester, course_id=course_id)
    weak_concepts = _get_weak_concepts(user_id, topic, course_id=course_id)
    # Generated for a course: file the cards under it, or the list cannot say
    # which course they belong to. Resolved before the model call, so a failed
    # lookup costs no generation.
    offering_id = _card_offering(user_id, course_id, semester)

    try:
        cards = generate_flashcards(
            topic=topic,
            count=count,
            context=context,
            documents=documents,
            weak_concepts=weak_concepts,
        )
    except Exception as e:
        raise generation_failed(e) from e

    # The response the frontend renders (freshly generated cards, before any
    # list re-fetch) carries these plaintext rows; `_save` writes ciphertext.
    # `course_id` is the list's derived key (the course of the card's
    # offering), not a column: every offering `_card_offering` can answer is
    # one of `course_id`.
    rows = new_card_rows(user_id, topic, offering_id, cards)
    _save(rows)
    _after_generation(user_id, len(rows), len(documents), len(weak_concepts))
    filed_under = course_id if offering_id else None
    return {
        "flashcards": [{**row, "course_id": filed_under} for row in rows],
        "context_used": {
            "documents_found": len(documents),
            "weak_concepts_found": len(weak_concepts),
        },
    }
