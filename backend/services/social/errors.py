"""
backend/services/social/errors.py

Domain errors the social package raises instead of ``HTTPException`` (no
``fastapi`` in a domain package, #118). ``routes/social.py`` maps each class
to the status code the route answered with before the split; ``detail`` is
the client-facing message, unchanged.
"""
from __future__ import annotations


class SocialError(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class InvalidRequest(SocialError):
    """400."""


class Forbidden(SocialError):
    """403: not a member, not the owner, not your message/request, banned."""


class NotFound(SocialError):
    """404: no such room / message / request (or one in another room)."""


class Conflict(SocialError):
    """409: the transition lost a race or is no longer possible."""


class RateLimited(SocialError):
    """429: the decline cooldown has not lifted."""


class UpstreamError(SocialError):
    """502: the matching model call failed."""
