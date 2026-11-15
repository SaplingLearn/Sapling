"""
backend/services/gradescope/errors.py

Domain errors the Gradescope package raises instead of ``HTTPException`` (no
``fastapi`` in a domain package, #118). ``routes/gradescope.py`` maps each to
the status code and detail the route answered with before the split.
"""
from __future__ import annotations


class GradescopeCredsError(Exception):
    """The stored credentials cannot be used: they would not decrypt, or a
    password-mode row lacks its email/password. ``detail`` is the
    client-facing message, unchanged; the route answers it as a 500."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class GradescopeLinkError(Exception):
    """A course link cannot be resolved or written. ``detail`` is the
    client-facing message, unchanged; the route maps each subclass to the
    status it answered with before the split."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class CourseNotFound(GradescopeLinkError):
    """The user has no enrollment in the Sapling course (404)."""


class NoCourseLink(GradescopeLinkError):
    """No Gradescope course is linked to the Sapling course (400)."""


class AmbiguousEnrollment(GradescopeLinkError):
    """More than one enrollment matches the semester (409)."""


class AmbiguousLink(GradescopeLinkError):
    """More than one link matches and the current term does not settle it (409)."""
