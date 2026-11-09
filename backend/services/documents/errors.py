"""
backend/services/documents/errors.py

Domain errors the documents package raises instead of ``HTTPException`` (no
``fastapi`` in a domain package, #118). ``routes/documents.py`` maps each to
the status code and detail the route answered with before the split.
"""
from __future__ import annotations


class DocumentError(Exception):
    """Base class: ``detail`` is the client-facing message, unchanged."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class ConceptScanFailed(DocumentError):
    """Writing the scanned concepts to the graph failed (500)."""
