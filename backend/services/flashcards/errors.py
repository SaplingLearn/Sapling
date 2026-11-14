"""Domain errors the flashcards package raises instead of ``HTTPException``
(no ``fastapi`` in a domain package, #118). ``routes/flashcards.py`` maps each
class to the status code it answers with (its ``_ERROR_STATUS``); ``detail``
is the client-facing message."""
from __future__ import annotations


class FlashcardError(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


# ── Cards, generation and the import flow ────────────────────────────────────


class InvalidRequest(FlashcardError):
    """400: a field the request needed is missing or malformed."""


class NotFound(FlashcardError):
    """404: no such card or document (or it is another student's)."""


class PayloadTooLarge(FlashcardError):
    """413: the uploaded file is over the import limit."""


class Unprocessable(FlashcardError):
    """422: the file or page was read but cannot be imported."""


class RateLimited(FlashcardError):
    """429: the import limiter refused; ``retry_after`` is seconds to wait."""

    def __init__(self, detail: str, retry_after: int):
        super().__init__(detail)
        self.retry_after = retry_after


class StorageError(FlashcardError):
    """500: a card read or write failed."""


class UpstreamError(FlashcardError):
    """502: the model call or a file parser failed."""


# ── Saved sets ───────────────────────────────────────────────────────────────


class FlashcardSetError(FlashcardError):
    """Base class of the saved-set errors."""


class FlashcardSetInvalid(FlashcardSetError):
    """422: a field of the set (or of a set description) fails validation."""


class FlashcardSetNotFound(FlashcardSetError):
    """404: the set, its course or its exam is missing or is not the caller's
    (the same answer for "not there" and "not yours")."""


class FlashcardSetLimitReached(FlashcardSetError):
    """409: the caller already holds the maximum number of sets."""


class FlashcardSetRateLimited(FlashcardSetError):
    """429: too many "describe a set" requests; ``retry_after`` is seconds to
    wait."""

    def __init__(self, detail: str, retry_after: int | None = None):
        super().__init__(detail)
        self.retry_after = retry_after
