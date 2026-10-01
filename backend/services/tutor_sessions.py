"""Who owns a tutor session.

`require_self(body.user_id)` only proves the caller IS `body.user_id`; it
says nothing about a `session_id` in the same request. Any route that
takes a tutor session id from the client answers "is this the caller's
session?" here, before it reads, decrypts or writes anything keyed on it.

PENDING_SESSIONS lives here (not in routes/learn.py) so non-tutor routes
can apply the same rule without importing a router module. A session is
pending between start-session and the first chat turn: it has no
`sessions` row yet, only this in-process record of who started it.
"""
from __future__ import annotations

from fastapi import HTTPException

from db.connection import table

# Maps session_id -> pending payload (cleared on first chat, end-session discard, or delete).
PENDING_SESSIONS: dict[str, dict] = {}

SESSION_NOT_FOUND = "Session not found"


def session_owned_by(
    session_id: str | None, user_id: str | None, *, allow_pending: bool = True
) -> bool:
    """True only if ``session_id`` is ``user_id``'s tutor session.

    A pending session counts only when PENDING_SESSIONS recorded the same
    user, and only with ``allow_pending`` (a caller that needs a real
    ``sessions`` row, e.g. for a foreign key, passes False). A NULL owner
    or an empty caller id never matches.
    """
    if not session_id or not user_id:
        return False
    pending = PENDING_SESSIONS.get(session_id)
    if pending is not None:
        return allow_pending and pending.get("user_id") == user_id
    rows = table("sessions").select(
        "user_id", filters={"id": f"eq.{session_id}"}, limit=1
    )
    owner = rows[0].get("user_id") if rows else None
    return bool(owner) and owner == user_id


def require_session_owner(
    session_id: str | None, user_id: str | None, *, allow_pending: bool = True
) -> None:
    """404 unless ``session_id`` is ``user_id``'s tutor session.

    Missing and foreign sessions answer the same 404, never 403, so session
    ids can't be probed.
    """
    if not session_owned_by(session_id, user_id, allow_pending=allow_pending):
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)
