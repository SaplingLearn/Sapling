"""Who owns a tutor session.

`require_self(body.user_id)` only proves the caller IS `body.user_id`; it
says nothing about a `session_id` in the same request. Any route that
takes a tutor session id from the client answers "is this the caller's
session?" here, before it reads, decrypts or writes anything keyed on it.

PENDING_SESSIONS lives here (not in routes/learn.py) so non-tutor routes
can apply the same rule without importing a router module. A session is
pending between start-session and the first chat turn: it has no
`sessions` row yet, only this in-process record of who started it.

Lifecycle (#761):

    pending --first turn--> live (row, ended_at NULL) --end--> ended
       |                                                  (ended_at set;
       +--end / delete / TTL / size cap--> gone            turns -> 409)

A pending entry is bounded in time and count (``stash_pending``): it holds a
plaintext greeting in process memory, and a session nobody chats in must not
live for the life of the worker. A discard (end-session or delete) leaves a
short-lived tombstone, so a turn that passed its ownership check just before
the discard answers 409/404 instead of carrying on as if the session row
existed.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import HTTPException

from db.connection import table

# Maps session_id -> pending payload (cleared on first chat, end-session
# discard, delete, or eviction by ``stash_pending``). Write it through
# ``stash_pending`` so the TTL/size bound holds; reads may use it directly.
PENDING_SESSIONS: dict[str, dict] = {}

SESSION_NOT_FOUND = "Session not found"

#: A pending session nobody chatted in for this long is dropped on the next
#: stash. Long enough for a tab left open over a lecture; short enough that a
#: greeting doesn't sit in memory for the life of the worker.
PENDING_TTL_SECONDS = 12 * 60 * 60
#: Hard cap on pending entries (and on tombstones) per process; oldest go first.
PENDING_MAX_ENTRIES = 2000
#: How long a discard is remembered. Covers any turn already in flight (an
#: agent turn is bounded well under this) without growing without bound.
DISCARD_TOMBSTONE_TTL_SECONDS = 10 * 60

#: The typed code a turn on an ended session answers with (409). It rides the
#: error body as ``error.code`` (services/quiz_errors.py::error_content), which
#: the frontend's ``ApiError.code`` already reads.
SESSION_ENDED_CODE = "SESSION_ENDED"
SESSION_ENDED_MESSAGE = (
    "This tutoring session has ended. Start a new session to keep learning."
)

# Stamped on each payload by ``stash_pending``; private, never sent anywhere.
_STASHED_AT = "_stashed_at"

# session_id -> (user_id, reason, discarded_at). reason: "ended" | "deleted".
_DISCARDED: dict[str, tuple[str, str, float]] = {}
_STATE_GUARD = threading.Lock()


def _now() -> float:
    """Module-level clock so tests can move time."""
    return time.monotonic()


def stash_pending(session_id: str, payload: dict) -> None:
    """Record a freshly started session as pending, enforcing the bounds.

    Expired entries (older than ``PENDING_TTL_SECONDS``) are dropped, then the
    oldest are evicted until there is room under ``PENDING_MAX_ENTRIES``. Dicts
    keep insertion order, so "oldest" is the front of the dict. An evicted
    session answers 404 on its first turn, like any unknown id.
    """
    now = _now()
    with _STATE_GUARD:
        cutoff = now - PENDING_TTL_SECONDS
        # Snapshot first: other threads pop entries without this guard (the
        # pops are atomic), and iterating the live dict would race them.
        for sid in [
            sid for sid, p in list(PENDING_SESSIONS.items())
            if p.get(_STASHED_AT, now) < cutoff
        ]:
            PENDING_SESSIONS.pop(sid, None)
        overflow = len(PENDING_SESSIONS) - PENDING_MAX_ENTRIES + 1
        if overflow > 0:
            for sid in list(PENDING_SESSIONS)[:overflow]:
                PENDING_SESSIONS.pop(sid, None)
        PENDING_SESSIONS[session_id] = {**payload, _STASHED_AT: now}


def discard_pending(session_id: str, *, user_id: str, reason: str) -> dict | None:
    """Pop ``session_id``'s pending entry and leave a tombstone saying why
    (``"ended"`` or ``"deleted"``). Returns the popped payload, or None.

    Callers hold ``materialization_lock(session_id)``. The tombstone is left
    even when there was nothing to pop: a session that materialised while the
    caller waited is still being ended or deleted, and a turn that already
    passed its ownership check must not write into it.
    """
    now = _now()
    with _STATE_GUARD:
        popped = PENDING_SESSIONS.pop(session_id, None)
        cutoff = now - DISCARD_TOMBSTONE_TTL_SECONDS
        for sid in [sid for sid, t in _DISCARDED.items() if t[2] < cutoff]:
            del _DISCARDED[sid]
        _DISCARDED.pop(session_id, None)  # re-insert at the back
        while len(_DISCARDED) >= PENDING_MAX_ENTRIES:
            del _DISCARDED[next(iter(_DISCARDED))]
        _DISCARDED[session_id] = (user_id, reason, now)
    return popped


def discarded_reason(session_id: str | None, user_id: str | None = None) -> str | None:
    """``"ended"`` / ``"deleted"`` if ``session_id`` was discarded within the
    tombstone TTL (by ``user_id``, when one is given), else None."""
    if not session_id:
        return None
    t = _DISCARDED.get(session_id)
    if t is None or t[2] < _now() - DISCARD_TOMBSTONE_TTL_SECONDS:
        return None
    if user_id is not None and t[0] != user_id:
        return None
    return t[1]


def session_ended_error() -> HTTPException:
    """The one 409 for a turn on an ended session (code SESSION_ENDED)."""
    exc = HTTPException(status_code=409, detail=SESSION_ENDED_MESSAGE)
    exc.code = SESSION_ENDED_CODE  # main.py's handler puts it in the body
    return exc


def raise_if_discarded(session_id: str | None, user_id: str | None = None) -> None:
    """409 SESSION_ENDED for an ended discard, 404 for a deleted one."""
    reason = discarded_reason(session_id, user_id)
    if reason == "ended":
        raise session_ended_error()
    if reason is not None:
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)


async def araise_if_discarded(session_id: str | None, user_id: str | None = None) -> None:
    """:func:`raise_if_discarded` for event-loop callers (#117 wave 3)."""
    raise_if_discarded(session_id, user_id)


def _raise_unless_open(rows: list) -> None:
    if not rows:
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)
    if rows[0].get("ended_at"):
        raise session_ended_error()


def require_session_open(session_id: str) -> None:
    """Before a turn runs on a materialised session: 409 SESSION_ENDED if it
    has ended, 404 if its row is gone (deleted since the ownership check)."""
    _raise_unless_open(table("sessions").select(
        "ended_at", filters={"id": f"eq.{session_id}"}, limit=1
    ))


async def arequire_session_open(session_id: str) -> None:
    """:func:`require_session_open` over the async seam (#117 wave 3)."""
    _raise_unless_open(await table("sessions").aselect(
        "ended_at", filters={"id": f"eq.{session_id}"}, limit=1
    ))

# Per-session locks serialising every pending -> materialised/discarded
# transition. PENDING_SESSIONS is a plain module dict, so it is per-process:
# a pending session is only ever visible to the worker that started it, and a
# per-process lock is exactly the right scope (no cross-worker locking).
# Each entry is [lock, holders]; it exists only while some request holds or
# waits on it, so the registry is bounded by in-flight requests.
_MATERIALIZATION_LOCKS: dict[str, list] = {}
_MATERIALIZATION_LOCKS_GUARD = threading.Lock()


@contextmanager
def materialization_lock(session_id: str) -> Iterator[None]:
    """Hold ``session_id``'s materialisation lock for the ``with`` body.

    Sync tutor routes run in FastAPI's threadpool, so two requests for one
    pending session can overlap. Whoever holds this lock is the only one
    allowed to read-then-act on that session's PENDING_SESSIONS entry; the
    others wait, then re-check. The entry is dropped when the last holder or
    waiter leaves, including on an exception.
    """
    with _MATERIALIZATION_LOCKS_GUARD:
        entry = _MATERIALIZATION_LOCKS.get(session_id)
        if entry is None:
            entry = _MATERIALIZATION_LOCKS[session_id] = [threading.Lock(), 0]
        entry[1] += 1
    try:
        with entry[0]:
            yield
    finally:
        with _MATERIALIZATION_LOCKS_GUARD:
            entry[1] -= 1
            if entry[1] == 0:
                del _MATERIALIZATION_LOCKS[session_id]


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
    return _row_owned_by(table("sessions").select(
        "user_id", filters={"id": f"eq.{session_id}"}, limit=1
    ), user_id)


def _row_owned_by(rows: list, user_id: str) -> bool:
    owner = rows[0].get("user_id") if rows else None
    return bool(owner) and owner == user_id


async def asession_owned_by(
    session_id: str | None, user_id: str | None, *, allow_pending: bool = True
) -> bool:
    """:func:`session_owned_by` over the async seam (#117 wave 3)."""
    if not session_id or not user_id:
        return False
    pending = PENDING_SESSIONS.get(session_id)
    if pending is not None:
        return allow_pending and pending.get("user_id") == user_id
    return _row_owned_by(await table("sessions").aselect(
        "user_id", filters={"id": f"eq.{session_id}"}, limit=1
    ), user_id)


def require_session_owner(
    session_id: str | None, user_id: str | None, *, allow_pending: bool = True
) -> None:
    """404 unless ``session_id`` is ``user_id``'s tutor session.

    Missing and foreign sessions answer the same 404, never 403, so session
    ids can't be probed.
    """
    if not session_owned_by(session_id, user_id, allow_pending=allow_pending):
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)


async def arequire_session_owner(
    session_id: str | None, user_id: str | None, *, allow_pending: bool = True
) -> None:
    """:func:`require_session_owner` over the async seam (#117 wave 3)."""
    if not await asession_owned_by(session_id, user_id, allow_pending=allow_pending):
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)


def _parse_utc(iso: str) -> datetime:
    parsed = datetime.fromisoformat(iso)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def elapsed_minutes(started_at_iso: str, *, until: str | None = None) -> int:
    """Whole minutes since ``started_at_iso``, robust to both timestamp shapes
    in the wild: tz-aware ISO (TIMESTAMPTZ reads via PostgREST, and every write
    after the #248 sweep) and legacy naive strings (pre-sweep ``utcnow()``
    writes), which are UTC by construction. The old inline
    ``utcnow() - fromisoformat(...)`` raised TypeError on the aware shape and
    silently reported 0. Returns 0 for anything unparseable. ``until`` (an
    ISO timestamp, e.g. the stored ended_at) replaces "now" as the end."""
    try:
        started = _parse_utc(started_at_iso)
        end = _parse_utc(until) if until else datetime.now(timezone.utc)
        return int((end - started).total_seconds() / 60)
    except Exception:
        return 0
