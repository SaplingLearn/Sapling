"""Flashcards domain (#118). ``routes/flashcards.py`` is the HTTP layer over
these; each of its handlers' bodies lives here under the handler's own name.

- ``cards``: card rows (``get_flashcards`` / ``rate_card`` / ``delete_card``,
  the row a new card is stored as, the library-document read).
- ``context``: what grounds a generation (session summary, course documents,
  weak concepts).
- ``generation``: ``generate`` (topic → agent → stored cards).
- ``import_flow``: ``import_commit`` / ``import_parse`` / ``import_generate``
  / ``import_cleanup`` / ``import_cloze``.
- ``importing``: the parsers, the Quizlet scraper, the flashcard-agent calls
  and the import limiter (was ``services/flashcard_import_service.py``, which
  stays as an alias shim).
- ``sets`` / ``suggest``: saved sets, and "describe a set".
- ``errors``: domain errors ``routes/flashcards.py`` maps to HTTP statuses.
"""
from services.flashcards import cards, generation, import_flow
from services.flashcards.cards import library_doc_source_text, list_flashcards
from services.flashcards.errors import (
    FlashcardError,
    FlashcardSetError,
    FlashcardSetInvalid,
    FlashcardSetLimitReached,
    FlashcardSetNotFound,
    FlashcardSetRateLimited,
    InvalidRequest,
    NotFound,
    PayloadTooLarge,
    RateLimited,
    StorageError,
    Unprocessable,
    UpstreamError,
)
from services.flashcards.importing import (
    QuizletBlocked,
    QuizletURLRejected,
    check_rate_limit,
    dedup_against_existing,
    extract_cards_from_image,
    gemini_cleanup_cards,
    gemini_cloze,
    gemini_generate_cards,
    generate_flashcards,
    parse_anki_apkg,
    parse_xlsx,
    scrape_quizlet_url,
)
from services.flashcards.sets import (
    create_flashcard_set,
    delete_flashcard_set,
    list_flashcard_sets,
    update_flashcard_set,
)
from services.flashcards.suggest import suggest_flashcard_set

__all__ = [
    "FlashcardError",
    "FlashcardSetError",
    "FlashcardSetInvalid",
    "FlashcardSetLimitReached",
    "FlashcardSetNotFound",
    "FlashcardSetRateLimited",
    "InvalidRequest",
    "NotFound",
    "PayloadTooLarge",
    "QuizletBlocked",
    "QuizletURLRejected",
    "RateLimited",
    "StorageError",
    "Unprocessable",
    "UpstreamError",
    "cards",
    "check_rate_limit",
    "create_flashcard_set",
    "dedup_against_existing",
    "delete_flashcard_set",
    "extract_cards_from_image",
    "gemini_cleanup_cards",
    "gemini_cloze",
    "gemini_generate_cards",
    "generate_flashcards",
    "generation",
    "import_flow",
    "library_doc_source_text",
    "list_flashcard_sets",
    "list_flashcards",
    "parse_anki_apkg",
    "parse_xlsx",
    "scrape_quizlet_url",
    "suggest_flashcard_set",
    "update_flashcard_set",
]
