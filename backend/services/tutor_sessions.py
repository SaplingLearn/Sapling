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

Two replicas (#117): process memory is invisible to the other replica, so a
session started on one 404s on the other and an end/delete there does not
stop it. With the ``stateless_tutor_sessions`` flag on (global, default off)
new pending sessions and tombstones live in the service-only
``tutor_pending_sessions`` table instead (migration
20261109024225_tutor_pending_sessions.sql): the first turn materialises in
ONE transaction (``materialize_tutor_session``), so the per-process lock is
not needed there, and a discard is one atomic call
(``discard_tutor_session``). The same TTLs and cap apply, across replicas.
An entry is looked up where it was stashed: memory first (a session started
before the flag went on finishes there), then the table when the flag is on.
Flag off = the in-memory store exactly as before; no table is touched.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from db.async_connection import arpc
from db.connection import rpc, table
from db.scope import runs_as_service
from services.encryption import decrypt_if_present, encrypt_if_present

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


# ── Postgres store (flag `stateless_tutor_sessions` on) ─────────────────────

FLAG_KEY = "stateless_tutor_sessions"
STORE_TABLE = "tutor_pending_sessions"
_STORE_COLS = (
    "session_id,user_id,state,mode,topic,course_id,offering_id,"
    "use_shared_context,assistant_reply,stashed_at,discarded_at"
)


def stored() -> bool:
    """Whether new pending sessions go to the table. Fails closed (memory)."""
    try:
        from services.feature_flags import flag_on

        return flag_on(FLAG_KEY, None)
    except Exception:
        return False


async def astored() -> bool:
    """:func:`stored` without a blocking read on the loop: the cached flag
    snapshot when it can answer, else one hop to a worker thread."""
    try:
        from services.feature_flags import cached_explain

        res = cached_explain(FLAG_KEY, None)
    except Exception:
        res = None
    if res is not None:
        return res.variant == "on"
    return await asyncio.to_thread(stored)


def _within(ts: str | None, seconds: int) -> bool:
    """Whether the stored timestamp ``ts`` is less than ``seconds`` old."""
    if not ts:
        return False
    at = datetime.fromisoformat(ts)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at >= datetime.now(timezone.utc) - timedelta(seconds=seconds)


def _view(row: dict | None, user_id: str | None = None) -> tuple[dict | None, str | None]:
    """(live pending payload, live tombstone reason for ``user_id``) of a
    store row; an expired pending row or tombstone reads as absent."""
    if not row:
        return None, None
    if row.get("state") == "pending":
        if not _within(row.get("stashed_at"), PENDING_TTL_SECONDS):
            return None, None
        return {
            "user_id": row.get("user_id"),
            "mode": row.get("mode"),
            "topic": row.get("topic"),
            "course_id": row.get("course_id"),
            "offering_id": row.get("offering_id"),
            "use_shared_context": row.get("use_shared_context"),
            "assistant_reply": decrypt_if_present(row.get("assistant_reply")),
        }, None
    if not _within(row.get("discarded_at"), DISCARD_TOMBSTONE_TTL_SECONDS):
        return None, None
    if user_id is not None and row.get("user_id") != user_id:
        return None, None
    return None, row.get("state")


@runs_as_service  # tutor_pending_sessions is service-only (RLS bucket E)
def _store_row(session_id: str) -> dict | None:
    rows = table(STORE_TABLE).select(
        _STORE_COLS, filters={"session_id": f"eq.{session_id}"}, limit=1
    )
    return rows[0] if rows else None


@runs_as_service
async def _astore_row(session_id: str) -> dict | None:
    rows = await table(STORE_TABLE).aselect(
        _STORE_COLS, filters={"session_id": f"eq.{session_id}"}, limit=1
    )
    return rows[0] if rows else None


def _stash_params(session_id: str, payload: dict) -> dict:
    return {
        "p_session_id": session_id,
        "p_user_id": payload["user_id"],
        "p_mode": payload["mode"],
        "p_topic": payload["topic"],
        "p_course_id": payload.get("course_id"),
        "p_offering_id": payload.get("offering_id"),
        "p_use_shared_context": bool(payload.get("use_shared_context", True)),
        # The messages.content format: materialisation copies it as is.
        "p_assistant_reply": encrypt_if_present(payload["assistant_reply"]),
        "p_graph_update": payload.get("graph_update") or None,
        "p_ttl_seconds": PENDING_TTL_SECONDS,
        "p_tombstone_ttl_seconds": DISCARD_TOMBSTONE_TTL_SECONDS,
        "p_max_entries": PENDING_MAX_ENTRIES,
    }


@runs_as_service
def _store_stash(session_id: str, payload: dict) -> None:
    rpc("stash_tutor_session", _stash_params(session_id, payload))


@runs_as_service
async def _astore_stash(session_id: str, payload: dict) -> None:
    await arpc("stash_tutor_session", _stash_params(session_id, payload))


@runs_as_service
def _store_discard(session_id: str, user_id: str, reason: str, *, only_if_pending: bool) -> bool:
    out = rpc("discard_tutor_session", {
        "p_session_id": session_id,
        "p_user_id": user_id,
        "p_reason": reason,
        "p_only_if_pending": only_if_pending,
        "p_ttl_seconds": PENDING_TTL_SECONDS,
    })
    return bool(out[0] if isinstance(out, list) and out else out)


@runs_as_service
def _store_rename(session_id: str, topic: str) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=PENDING_TTL_SECONDS)
    return bool(table(STORE_TABLE).update(
        {"topic": topic},
        filters={
            "session_id": f"eq.{session_id}",
            "state": "eq.pending",
            "stashed_at": f"gte.{cutoff.isoformat()}",
        },
    ))


@runs_as_service
async def amaterialize_stored(session_id: str, user_id: str) -> bool:
    """The first turn of a table-held pending session, in one call (flag on).

    True when THIS call wrote the ``sessions`` row and the greeting (it logs
    ``session.started``); False when the session is not pending (never was,
    expired, or another turn materialised it first). Raises 409
    SESSION_ENDED / 404 for the caller's ended / deleted tombstone, and 404
    for another student's pending session.
    """
    from services import events_service

    rows = await arpc("materialize_tutor_session", {
        "p_session_id": session_id,
        "p_user_id": user_id,
        "p_ttl_seconds": PENDING_TTL_SECONDS,
        "p_tombstone_ttl_seconds": DISCARD_TOMBSTONE_TTL_SECONDS,
    })
    row = rows[0] if isinstance(rows, list) and rows else {}
    outcome = row.get("outcome")
    if outcome == "ended":
        raise session_ended_error()
    if outcome in ("deleted", "foreign"):
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)
    if outcome != "materialized":
        return False
    # #117: session.started once the lazy row materialises; the topic is free
    # text -> content= (fingerprint only), as in routes/learn._consume_pending.
    events_service.log_event(
        "session.started",
        category="usage",
        user_id=user_id,
        payload={
            "session_id": session_id,
            "mode": row.get("session_mode"),
            "offering_id": row.get("session_offering_id"),
        },
        content=row.get("session_topic"),
    )
    return True


# ── The store API (memory, or the table with the flag on) ───────────────────

def get_pending(session_id: str | None) -> dict | None:
    """``session_id``'s live pending payload, or None."""
    pending = PENDING_SESSIONS.get(session_id) if session_id else None
    if pending is None and session_id and stored():
        pending = _view(_store_row(session_id))[0]
    return pending


async def aget_pending(session_id: str | None) -> dict | None:
    """:func:`get_pending` over the async seam."""
    pending = PENDING_SESSIONS.get(session_id) if session_id else None
    if pending is None and session_id and await astored():
        pending = _view(await _astore_row(session_id))[0]
    return pending


async def astash_pending(session_id: str, payload: dict) -> None:
    """:func:`stash_pending` for event-loop callers."""
    if await astored():
        await _astore_stash(session_id, payload)
    else:
        stash_pending(session_id, payload)


def row_may_exist(pending: dict | None) -> bool:
    """True when the session has (or may have) a ``sessions`` row: it is not
    pending at all, or materialisation already attempted the row write."""
    return pending is None or bool(pending.get("_row_may_exist"))


def discard_if_pending(
    session_id: str, *, user_id: str, reason: str, always: bool = False
) -> dict | None:
    """End or delete a session's pending state; returns the popped pending
    payload, or None if it was not pending. ``always`` leaves the tombstone
    even for a session that is not pending (delete: a turn already past its
    ownership check must not write into the deleted row). A popped payload
    without ``row_may_exist`` means there is no ``sessions`` row to act on.
    """
    if session_id in PENDING_SESSIONS:
        # Under the lock so a concurrent first turn can't insert the row
        # after the entry is dropped.
        with materialization_lock(session_id):
            return discard_pending(session_id, user_id=user_id, reason=reason)
    if stored():
        # Atomic in the table; a pending row there never has a sessions row.
        was = _store_discard(session_id, user_id, reason, only_if_pending=not always)
        return {} if was else None
    if always:
        discard_pending(session_id, user_id=user_id, reason=reason)
    return None


def rename_pending(session_id: str, topic: str) -> bool:
    """Rename a pending session's stored topic, for the row a later
    materialisation writes. True when that is all there is to rename (no
    ``sessions`` row can exist yet); False to rename the real row."""
    if session_id in PENDING_SESSIONS:
        with materialization_lock(session_id):
            pending = PENDING_SESSIONS.get(session_id)
            if pending is not None:
                pending["topic"] = topic
                # An earlier attempt may already have written the row (the
                # retry's upsert won't overwrite it): rename that too.
                return not row_may_exist(pending)
        return False  # it materialised while we waited: rename the real row
    return stored() and _store_rename(session_id, topic)


def stash_pending(session_id: str, payload: dict) -> None:
    """Record a freshly started session as pending, enforcing the bounds
    (in the table with the flag on; :func:`astash_pending` from the loop).

    Expired entries (older than ``PENDING_TTL_SECONDS``) are dropped, then the
    oldest are evicted until there is room under ``PENDING_MAX_ENTRIES``. Dicts
    keep insertion order, so "oldest" is the front of the dict. An evicted
    session answers 404 on its first turn, like any unknown id.
    """
    if stored():
        _store_stash(session_id, payload)
        return
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


def _memory_discarded_reason(session_id: str, user_id: str | None) -> str | None:
    t = _DISCARDED.get(session_id)
    if t is None or t[2] < _now() - DISCARD_TOMBSTONE_TTL_SECONDS:
        return None
    if user_id is not None and t[0] != user_id:
        return None
    return t[1]


def discarded_reason(session_id: str | None, user_id: str | None = None) -> str | None:
    """``"ended"`` / ``"deleted"`` if ``session_id`` was discarded within the
    tombstone TTL (by ``user_id``, when one is given), else None."""
    if not session_id:
        return None
    reason = _memory_discarded_reason(session_id, user_id)
    if reason is None and session_id not in PENDING_SESSIONS and stored():
        reason = _view(_store_row(session_id), user_id)[1]
    return reason


async def adiscarded_reason(session_id: str | None, user_id: str | None = None) -> str | None:
    """:func:`discarded_reason` over the async seam."""
    if not session_id:
        return None
    reason = _memory_discarded_reason(session_id, user_id)
    if reason is None and session_id not in PENDING_SESSIONS and await astored():
        reason = _view(await _astore_row(session_id), user_id)[1]
    return reason


def session_ended_error() -> HTTPException:
    """The one 409 for a turn on an ended session (code SESSION_ENDED)."""
    exc = HTTPException(status_code=409, detail=SESSION_ENDED_MESSAGE)
    exc.code = SESSION_ENDED_CODE  # main.py's handler puts it in the body
    return exc


def _raise_for(reason: str | None) -> None:
    if reason == "ended":
        raise session_ended_error()
    if reason is not None:
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)


def raise_if_discarded(session_id: str | None, user_id: str | None = None) -> None:
    """409 SESSION_ENDED for an ended discard, 404 for a deleted one."""
    _raise_for(discarded_reason(session_id, user_id))


def raise_if_discarded_here(session_id: str | None, user_id: str | None = None) -> None:
    """:func:`raise_if_discarded` for THIS process's tombstones only: no I/O,
    so a caller can run it first whichever store the flag picks (a session
    pending in memory when the flag went on is ended in memory)."""
    if session_id:
        _raise_for(_memory_discarded_reason(session_id, user_id))


async def araise_if_discarded(session_id: str | None, user_id: str | None = None) -> None:
    """:func:`raise_if_discarded` for event-loop callers (#117 wave 3)."""
    _raise_for(await adiscarded_reason(session_id, user_id))


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


async def arequire_owned_open(session_id: str, user_id: str) -> None:
    """One ``sessions`` read: 404 unless the row is ``user_id``'s, 409
    SESSION_ENDED if it has ended. For a session known not to be pending."""
    rows = await table("sessions").aselect(
        "user_id,ended_at", filters={"id": f"eq.{session_id}"}, limit=1
    )
    if not _row_owned_by(rows, user_id):
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)
    _raise_unless_open(rows)

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
    pending = get_pending(session_id)
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
    pending = await aget_pending(session_id)
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
