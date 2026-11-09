"""
backend/services/gradebook/errors.py

Domain errors the gradebook package raises instead of ``HTTPException``
(no ``fastapi`` in a domain package, #118). ``routes/gradebook.py`` maps each
to the status code and detail the route answered with before the split.
"""
from __future__ import annotations


class GradebookError(Exception):
    """Base class: ``detail`` is the client-facing message, unchanged."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class DocumentNotOwned(GradebookError):
    """The syllabus document is missing or belongs to someone else (403)."""


class InvalidCategoryWeights(GradebookError):
    """Category weights do not sum to 100% (±0.5) (400)."""
