"""
backend/services/admin/errors.py

Domain errors the admin package raises instead of ``HTTPException`` (no
``fastapi`` in a domain package, #118). ``routes/admin.py`` maps each class to
the status code the route answered with before the split; ``detail`` is the
client-facing message, unchanged.
"""
from __future__ import annotations


class AdminError(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class InvalidRequest(AdminError):
    """400: nothing to update, a bad value, undecodable input."""


class NotFound(AdminError):
    """404: the row the request names does not exist."""


class Conflict(AdminError):
    """409: the write would break an invariant (last admin, self-revoke, …)."""


class Unprocessable(AdminError):
    """422: a value outside the column's CHECK constraint."""
