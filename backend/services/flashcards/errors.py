"""Domain errors the flashcards package raises instead of ``HTTPException``
(no ``fastapi`` in a domain package, #118). ``routes/flashcards.py`` answers
each with its ``status_code`` and ``detail``."""
from __future__ import annotations


class FlashcardSetError(Exception):
    """Base class: ``detail`` is the client-facing message."""

    status_code = 400

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class FlashcardSetInvalid(FlashcardSetError):
    """A field of the set fails validation (422)."""

    status_code = 422


class FlashcardSetNotFound(FlashcardSetError):
    """The set, its course or its exam is missing or is not the caller's
    (404: the same answer for "not there" and "not yours")."""

    status_code = 404


class FlashcardSetLimitReached(FlashcardSetError):
    """The caller already holds the maximum number of sets (409)."""

    status_code = 409


class FlashcardSetRateLimited(FlashcardSetError):
    """Too many "describe a set" requests in a minute (429)."""

    status_code = 429
