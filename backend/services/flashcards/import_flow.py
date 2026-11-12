"""The import flow's handler bodies (#118, moved from ``routes/flashcards.py``):
parse a file or a Quizlet URL into cards, generate / clean up / cloze cards
with the flashcard agent, and commit the cards the student kept.

The parsers, the scraper, the agent calls and the limiter are
``services/flashcards/importing.py``; this module is the request-level logic
over them.
"""
from __future__ import annotations

import base64

from db.connection import table
from services import events_service
from services.academics import resolve_offering
from services.achievement_service import check_achievements
from services.flashcards.cards import encrypted_card, library_doc_source_text, new_card_rows
from services.flashcards.errors import (
    InvalidRequest,
    NotFound,
    PayloadTooLarge,
    RateLimited,
    StorageError,
    Unprocessable,
    UpstreamError,
)
from services.flashcards.generation import generation_failed
from services.flashcards.importing import (
    QuizletBlocked,
    QuizletURLRejected,
    check_rate_limit,
    dedup_against_existing,
    extract_cards_from_image,
    gemini_cleanup_cards,
    gemini_cloze,
    gemini_generate_cards,
    parse_anki_apkg,
    parse_xlsx,
    scrape_quizlet_url,
)
from services.llm_budget import reraise_budget_refusal

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _claim_rate_slot(user_id: str) -> None:
    """One slot of the user's import limiter, or ``RateLimited``."""
    retry = check_rate_limit(user_id)
    if retry is not None:
        raise RateLimited(f"Rate limit hit. Try again in {retry}s.", retry_after=retry)


# ── /import/commit ───────────────────────────────────────────────────────────


def import_commit(
    user_id: str, *, course_id: str | None, topic: str, cards: list[dict], dedup: bool = True,
) -> dict:
    """Store the cards the student kept; answers ``{inserted,
    skipped_duplicates}``."""
    # The request carries an abstract course id (optional); flashcards key on
    # the offering. Resolve it (None stays None — flashcards.offering_id is
    # nullable). CREATE path: imported cards land on the CURRENT term's
    # offering by design (#141 scopes the reads only; new content belongs to
    # the term it's made in).
    offering_id = resolve_offering(course_id) if course_id else None

    skipped_count = 0
    if dedup:
        cards, skipped = dedup_against_existing(user_id, offering_id, cards, topic=topic)
        skipped_count = len(skipped)

    rows = [encrypted_card(r) for r in new_card_rows(user_id, topic, offering_id, cards)]
    if rows:
        try:
            table("flashcards").insert(rows)
        except Exception as e:
            raise StorageError(f"Insert failed: {e}") from e

    try:
        check_achievements(user_id, "flashcards_created", {"count": len(rows)})
    except Exception:
        pass

    return {"inserted": len(rows), "skipped_duplicates": skipped_count}


# ── /import/parse ────────────────────────────────────────────────────────────


def _decode_upload(payload: str) -> bytes:
    try:
        file_bytes = base64.b64decode(payload, validate=True)
    except Exception:
        raise InvalidRequest("payload must be valid base64") from None
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise PayloadTooLarge("File exceeds 5MB limit")
    return file_bytes


def _parse_file(source: str, file_bytes: bytes, options: dict | None) -> list[dict]:
    try:
        if source == "xlsx":
            return parse_xlsx(file_bytes)
        if source == "anki":
            return parse_anki_apkg(file_bytes)
        filename = (options or {}).get("filename", "image.png")
        return extract_cards_from_image(file_bytes, filename=filename)
    except ValueError as e:
        raise Unprocessable(str(e)) from e
    except Exception as e:
        # The OCR source runs the flashcard agent: a budget refusal is its own
        # 429, never a parser error.
        reraise_budget_refusal(e)
        raise UpstreamError(f"Parser error: {e}") from e


def _scrape(url: str) -> list[dict]:
    try:
        return scrape_quizlet_url(url)
    except QuizletURLRejected as e:
        raise InvalidRequest(str(e)) from e
    except QuizletBlocked as e:
        raise Unprocessable(str(e)) from e


def import_parse(source: str, payload: str, options: dict | None = None) -> dict:
    """Cards read out of an upload (``anki`` / ``xlsx`` / ``ocr``: base64 file
    bytes) or a Quizlet page (``url``). Nothing is saved."""
    if source in ("anki", "xlsx", "ocr"):
        cards = _parse_file(source, _decode_upload(payload), options)
    elif source == "url":
        cards = _scrape(payload)
    else:
        raise InvalidRequest(f"Unsupported source: {source}")
    return {"cards": cards, "errors": []}


# ── /import/generate, /import/cleanup, /import/cloze ─────────────────────────


def _source_text(user_id: str, source: str, text: str | None, document_id: str | None) -> str:
    if source == "paste":
        if not text:
            raise InvalidRequest("`text` is required for paste source")
        return text
    if not document_id:
        raise InvalidRequest("`document_id` is required for library_doc source")
    source_text = library_doc_source_text(user_id, document_id)
    if source_text is None:
        raise NotFound("Document not found")
    return source_text


def import_generate(
    user_id: str,
    *,
    source: str,
    text: str | None = None,
    document_id: str | None = None,
    count: int = 25,
    difficulty: str = "recall",
) -> dict:
    """Cards generated from pasted text or one of the user's library
    documents, for review (nothing is saved until ``import_commit``)."""
    _claim_rate_slot(user_id)
    source_text = _source_text(user_id, source, text, document_id)
    try:
        cards = gemini_generate_cards(source_text, count=count, difficulty=difficulty)
    except Exception as e:
        raise generation_failed(e) from e

    # #117 taxonomy (+ the ADR 0028 PostHog mirror): this IS the AI
    # generation (the cards come back for review; /import/commit only
    # persists what the student keeps — from any import source — so it does
    # not emit, and a generate-then-commit is counted once). Counts only.
    # Zero cards is not a generation (it would inflate the funnel).
    if cards:
        events_service.log_event(
            "flashcard.generated",
            category="usage",
            user_id=user_id,
            payload={
                "card_count": len(cards),
                "documents_used": 1 if source == "library_doc" else 0,
                "weak_concepts_used": 0,
                "via": source,
            },
        )
    return {"cards": cards}


def import_cleanup(user_id: str, cards: list[dict]) -> dict:
    """The cards, rewritten by the flashcard agent."""
    _claim_rate_slot(user_id)
    try:
        return {"cards": gemini_cleanup_cards(cards)}
    except Exception as e:
        raise generation_failed(e) from e


def import_cloze(user_id: str, paragraph: str) -> dict:
    """Cloze cards made from one paragraph."""
    _claim_rate_slot(user_id)
    try:
        return {"cards": gemini_cloze(paragraph)}
    except Exception as e:
        raise generation_failed(e) from e
