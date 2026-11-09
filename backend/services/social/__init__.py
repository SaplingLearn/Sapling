"""
backend/services/social/ — the social domain (#118).

``routes/social.py`` keeps the caller checks and calls these:

- ``rooms``: create, public listing, join (invite / public), leave, kick.
- ``overview``: a room's overview (AI group summary) and activity feed.
- ``messages``: the room transcript, post / edit / delete, reactions.
- ``matching``: room and school study-partner matching.
- ``directory``: the school student directory + shared visibility rules.
- ``friends``: friend requests, friendships and their lists.
- ``errors``: domain errors the route maps to HTTP statuses.
"""
from __future__ import annotations

# ``rooms`` and ``directory`` first: the others import helpers back off them.
from services.social import rooms, directory  # noqa: F401  isort: skip
from services.social import errors, friends, matching, messages, overview  # noqa: F401
from services.social.errors import (  # noqa: F401
    Conflict,
    Forbidden,
    InvalidRequest,
    NotFound,
    RateLimited,
    SocialError,
    UpstreamError,
)

__all__ = [
    "Conflict",
    "Forbidden",
    "InvalidRequest",
    "NotFound",
    "RateLimited",
    "SocialError",
    "UpstreamError",
    "directory",
    "errors",
    "friends",
    "matching",
    "messages",
    "overview",
    "rooms",
]
