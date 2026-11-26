"""The import flow's handler bodies (#118, moved from ``routes/flashcards.py``):
parse a file or a Quizlet URL into cards, generate / clean up / cloze cards
with the flashcard agent, and commit the cards the student kept.

The parsers, the scraper, the agent calls and the limiter are
``services/flashcards/importing.py``; this module is the request-level logic
over them.
"""
from __future__ import annotations

import base64
import logging

from db.connection import table
from services import events_service
from services.academics import resolve_offering
from services.achievement_service import check_achievements
from services.flashcards.cards import encrypted_card, library_doc_source_text, new_card_rows
from services.flashcards.errors import (
    FlashcardError,
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
from services.flashcards.integrity import card_guard, cleanup_withheld, screened, with_withheld
from services.llm_budget import reraise_budget_refusal
from services.upload_validation import GIF, JPEG, PDF, PNG, WEBP, sniff_type

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

#: Card text (every front and back) one cleanup may send (audit Z01): the
#: same bound as a pasted generate source. The model rewrites the whole deck
#: in one reply, so a larger deck cannot come back anyway, and the integrity
#: guard folds and indexes all of this text before any refusal.
CLEANUP_MAX_CHARS = 200_000


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
        logger.warning("flashcards_created achievement check failed", exc_info=True)

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


#: What the OCR source accepts, by the file's BYTES (the PhotoTab picker
#: offers images and PDFs). The client's `options.filename` is never used:
#: the extraction router picks its parser from the name, so a lying name
#: would route a file to a parser it was not checked for.
_OCR_TYPES = {PNG: "png", JPEG: "jpg", GIF: "gif", WEBP: "webp", PDF: "pdf"}


def _ocr_filename(file_bytes: bytes) -> str:
    """A name whose extension is the type the bytes ARE, or Unprocessable."""
    ext = _OCR_TYPES.get(sniff_type(file_bytes))
    if ext is None:
        raise Unprocessable("Upload a photo (PNG, JPG, GIF or WebP) or a PDF.")
    return f"import.{ext}"


def _parse_file(
    source: str, file_bytes: bytes, user_id: str, loop_on: bool,
) -> tuple[list[dict], int]:
    """The file's cards and how many the integrity guard withheld (OCR only)."""
    # Before the try: its refusal is the student's file, not a parser error.
    ocr_name = _ocr_filename(file_bytes) if source == "ocr" else ""
    try:
        if source == "xlsx":
            return parse_xlsx(file_bytes), 0
        if source == "anki":
            return parse_anki_apkg(file_bytes), 0
        # spec §13 A125: the photographed page's text is what this request
        # sends the card model — guarded once it is text, before the model
        guards: list = []
        cards = extract_cards_from_image(
            file_bytes,
            filename=ocr_name,
            screen=lambda text: guards.append(card_guard(user_id, (text,), active=loop_on)),
        )
        return screened(guards[0], cards) if guards else (cards, 0)
    except FlashcardError:
        raise
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


def import_parse(
    user_id: str,
    source: str,
    payload: str,
    options: dict | None = None,
    *,
    loop_on: bool = False,
) -> dict:
    """Cards read out of an upload (``anki`` / ``xlsx`` / ``ocr``: base64 file
    bytes) or a Quizlet page (``url``). Nothing is saved. Charged to the
    import limiter like its siblings: every source parses an attacker-shaped
    file or fetches a page, and ``ocr`` runs OCR and the flashcard agent.
    ``loop_on`` (the route's learning-loop gate) guards the OCR text (spec
    §13 A125)."""
    _claim_rate_slot(user_id)
    withheld = 0
    if source in ("anki", "xlsx", "ocr"):
        cards, withheld = _parse_file(source, _decode_upload(payload), user_id, loop_on)
    elif source == "url":
        cards = _scrape(payload)
    else:
        raise InvalidRequest(f"Unsupported source: {source}")
    return with_withheld({"cards": cards, "errors": []}, withheld)


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
    loop_on: bool = False,
) -> dict:
    """Cards generated from pasted text or one of the user's library
    documents, for review (nothing is saved until ``import_commit``).

    Spec §13 A125 (``loop_on``: the route's learning-loop gate): pasted text is
    guarded both ways; a library document is stored course material, not
    request text, so it is not."""
    _claim_rate_slot(user_id)
    source_text = _source_text(user_id, source, text, document_id)
    guard = card_guard(user_id, (source_text,), active=loop_on) if source == "paste" else None
    try:
        cards = gemini_generate_cards(source_text, count=count, difficulty=difficulty)
    except Exception as e:
        raise generation_failed(e) from e
    withheld = 0
    if guard is not None:
        cards, withheld = screened(guard, cards)

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
    return with_withheld({"cards": cards}, withheld)


def import_cleanup(user_id: str, cards: list[dict], *, loop_on: bool = False) -> dict:
    """The cards, rewritten by the flashcard agent. Spec §13 A125: the cards'
    own text is what this request sends the model (guarded); a cleaned card
    stating a posed check's key withholds the cleanup whole, and the student's
    own cards come back as they sent them — a cleanup never loses a card.
    A deck over ``CLEANUP_MAX_CHARS`` is a 413 before anything runs."""
    if sum(len(c["front"]) + len(c["back"]) for c in cards) > CLEANUP_MAX_CHARS:
        raise PayloadTooLarge("Too many cards to clean up at once. Clean up a smaller part of the deck.")
    _claim_rate_slot(user_id)
    guard = card_guard(user_id, [t for c in cards for t in (c["front"], c["back"])], active=loop_on)
    try:
        out = gemini_cleanup_cards(cards)
    except Exception as e:
        raise generation_failed(e) from e
    withheld = cleanup_withheld(guard, out)
    return {"cards": cards, "withheld": withheld} if withheld else {"cards": out}


def import_cloze(user_id: str, paragraph: str, *, loop_on: bool = False) -> dict:
    """Cloze cards made from one paragraph (guarded both ways, spec §13 A125)."""
    _claim_rate_slot(user_id)
    guard = card_guard(user_id, (paragraph,), active=loop_on)
    try:
        cards = gemini_cloze(paragraph)
    except Exception as e:
        raise generation_failed(e) from e
    cards, withheld = screened(guard, cards)
    return with_withheld({"cards": cards}, withheld)
