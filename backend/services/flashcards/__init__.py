"""Flashcards domain (#118): generation context, card reads, the import flow
and saved sets. ``routes/flashcards.py`` is the HTTP layer over these."""
from services.flashcards.cards import library_doc_source_text, list_flashcards
from services.flashcards.errors import FlashcardSetError
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
from services.flashcards.suggest import suggest_flashcard_set
from services.flashcards.sets import (
    create_flashcard_set,
    delete_flashcard_set,
    list_flashcard_sets,
    update_flashcard_set,
)

__all__ = [
    "FlashcardSetError",
    "QuizletBlocked",
    "QuizletURLRejected",
    "check_rate_limit",
    "create_flashcard_set",
    "dedup_against_existing",
    "delete_flashcard_set",
    "extract_cards_from_image",
    "gemini_cleanup_cards",
    "gemini_cloze",
    "gemini_generate_cards",
    "generate_flashcards",
    "library_doc_source_text",
    "list_flashcard_sets",
    "list_flashcards",
    "parse_anki_apkg",
    "parse_xlsx",
    "scrape_quizlet_url",
    "suggest_flashcard_set",
    "update_flashcard_set",
]
