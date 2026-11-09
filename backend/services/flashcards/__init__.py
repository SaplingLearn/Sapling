"""Flashcards domain (#118): generation context, card reads and the import
flow. ``routes/flashcards.py`` is the HTTP layer over these."""
from services.flashcards.cards import library_doc_source_text, list_flashcards
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

__all__ = [
    "QuizletBlocked",
    "QuizletURLRejected",
    "check_rate_limit",
    "dedup_against_existing",
    "extract_cards_from_image",
    "gemini_cleanup_cards",
    "gemini_cloze",
    "gemini_generate_cards",
    "generate_flashcards",
    "library_doc_source_text",
    "list_flashcards",
    "parse_anki_apkg",
    "parse_xlsx",
    "scrape_quizlet_url",
]
