"""Opening a tutor turn's session (#118, moved verbatim from routes/learn.py):
materialise a lazily started session on its first turn (`_consume_pending`)
and the entry checks every turn route runs (`_open_turn_session`).

The pending store itself lives in services/tutor_sessions.py.
"""
from __future__ import annotations

from starlette.concurrency import run_in_threadpool

from db.connection import table
from services import events_service
from services.profiles import get_display_name
from services.tutor.errors import HTTPException
from services.tutor.messages import save_message_sync
from services.tutor_sessions import (
    PENDING_SESSIONS,
    SESSION_NOT_FOUND as _SESSION_NOT_FOUND,
    amaterialize_stored,
    aopen_stored,
    aowned_live_row,
    araise_if_discarded,
    arequire_session_open,
    arequire_session_owner,
    astored,
    materialization_lock,
    materialize_stored,
    raise_if_discarded,
    raise_if_discarded_here,
    stored,
)


# Lazy sessions: start-session does not write to DB until the user sends their
# first chat message. PENDING_SESSIONS (session_id -> pending payload) lives in
# services/tutor_sessions.py so other routes can share the ownership rule.


def get_user_name(user_id: str) -> str:
    # Display name lives on user_profiles (0024); resolve + decrypt via helper.
    return get_display_name(user_id) or "Student"


def _consume_pending(session_id: str, user_id: str) -> bool:
    """If session was started lazily, persist session row + first assistant message before user/chat.

    Callers run require_session_owner first; the user check here is a
    second line of defence and runs before anything is written, so a
    mismatched caller can never destroy or claim the owner's pending session.

    Concurrency (CodeRabbit on #709): every turn route runs this in FastAPI's
    threadpool (`_consume_pending_off_loop`), so two of the owner's requests
    can arrive while the session is still pending. Materialisation is serialised per session id by
    ``materialization_lock``; the pending entry is removed only AFTER the
    session row and the initial assistant message are written. So:

    - a request that finds no pending entry can rely on the row existing
      UNLESS the entry was discarded (end-session / delete) rather than
      materialised. A discard leaves a tombstone (``discard_pending``), and
      both the lock-free fast path and the post-wait re-check consult it, so
      a turn that passed its ownership check just before the discard answers
      409 (ended) / 404 (deleted) instead of writing messages for a session
      row that will never exist (#761). The fast path takes no lock for a
      ready session;
    - a request that loses the race waits on the lock, then finds the entry
      gone and returns, and only then writes its own messages (no FK
      failure on ``messages.session_id``);
    - ownership checks keep seeing the pending entry throughout, so a
      concurrent request is never 404'd in a gap between "no longer
      pending" and "row inserted";
    - if materialisation fails, the entry stays pending (never wrongly
      ready) and the lock is released for the next request to retry.

    The row write is an upsert that ignores a duplicate id, so a retry is
    safe even when an earlier attempt committed the row but its response was
    lost (timeout, dropped connection). Two markers on the pending payload:

    - ``_row_may_exist`` is set BEFORE the first write attempt. From then on
      end-session / rename / delete must treat the session as possibly
      having a ``sessions`` row and act on the DB too, not just on memory.
    - ``_row_written`` is set once a write has returned. It guards the
      ``session.started`` event against double-logging when a later step
      (the greeting write) fails and the request is retried.

    Sync code: the async routes call it through ``_consume_pending_off_loop``
    so the lock wait and the network writes never block the event loop.

    Returns True only when THIS call materialised the session (so the row
    was just written with ``ended_at`` NULL and the caller can skip the
    ended-session read).

    With ``stateless_tutor_sessions`` on (#117), a session not pending in THIS
    process may be pending in the table (started on another replica — the
    learning loop's routes reach every session through here):
    ``materialize_tutor_session`` writes its row (with the loop document) and
    greeting in one transaction, or answers its tombstone (409 / 404), or
    'none' for a live session. This process's own tombstones are checked
    first, with no I/O.
    """
    if session_id not in PENDING_SESSIONS:
        raise_if_discarded_here(session_id, user_id)
        if stored():
            return materialize_stored(session_id, user_id)
        raise_if_discarded(session_id, user_id)
        return False
    with materialization_lock(session_id):
        pending = PENDING_SESSIONS.get(session_id)
        if pending is None:
            # Another request materialised it (row exists) or discarded it
            # (tombstone) while we waited.
            raise_if_discarded(session_id, user_id)
            return False
        if pending["user_id"] != user_id:
            raise HTTPException(status_code=404, detail=_SESSION_NOT_FOUND)

        if not pending.get("_row_written"):
            # Sessions key on the offering (0025). The pending payload carries
            # the offering id (resolved at start-session) alongside the
            # abstract course id.
            session_data = {
                "id": session_id,
                "user_id": user_id,
                "mode": pending["mode"],
                "topic": pending["topic"],
            }
            if pending.get("offering_id"):
                session_data["offering_id"] = pending["offering_id"]
            if pending.get("loop_state"):
                # Quiz-ask loop sessions materialize in teach phase.
                session_data["loop_state"] = pending["loop_state"]

            pending["_row_may_exist"] = True
            table("sessions").upsert(session_data, on_conflict="id", ignore_duplicates=True)
            pending["_row_written"] = True
            # #117: session.started once the lazy session row actually
            # materializes. The topic is free text -> content= (fingerprint
            # only), never payload.
            events_service.log_event(
                "session.started",
                category="usage",
                user_id=user_id,
                payload={
                    "session_id": session_id,
                    "mode": pending["mode"],
                    "offering_id": pending.get("offering_id"),
                },
                content=pending["topic"],
            )
        save_message_sync(session_id, "assistant", pending["assistant_reply"], pending["graph_update"])
        PENDING_SESSIONS.pop(session_id, None)
        return True


async def _consume_pending_off_loop(session_id: str, user_id: str) -> bool:
    """`_consume_pending` for the async routes (/chat, /chat/stream, /action).

    The slow path takes a blocking threading lock (possibly held by a
    threadpool request mid-insert) and makes sync network writes, so it runs
    in the threadpool; doing it inline would freeze every request on this
    worker's event loop for as long as the insert takes. A session that is
    not pending takes the inline fast path and never leaves the loop.
    """
    if session_id not in PENDING_SESSIONS:
        raise_if_discarded_here(session_id, user_id)
        if await astored():
            # #117: pending on another replica, or live: one atomic call
            return await amaterialize_stored(session_id, user_id)
        await araise_if_discarded(session_id, user_id)
        return False
    return await run_in_threadpool(_consume_pending, session_id, user_id)


async def _open_turn_session(session_id: str, user_id: str) -> None:
    """The entry checks every turn route (/chat, /chat/stream, /action,
    /mode-switch) runs before touching a session (#761): not discarded,
    owned by the caller, materialised if still pending, and — once
    materialised — not ended (409).

    The tombstone check comes first so a session ended while still pending
    answers 409 SESSION_ENDED rather than the bare 404 the ownership check
    would give a session that has no row and no pending entry. A ready
    session never reaches `_consume_pending` (pinned in
    test_learn_session_ownership.py).

    With `stateless_tutor_sessions` on (#117) a session not pending in THIS
    process goes to `aopen_stored` (one `sessions` read when live). This
    process's own tombstones are checked first on both paths (no I/O).
    """
    raise_if_discarded_here(session_id, user_id)
    if session_id not in PENDING_SESSIONS and await astored():
        return await aopen_stored(session_id, user_id)
    await araise_if_discarded(session_id, user_id)
    await arequire_session_owner(session_id, user_id)
    if await _consume_pending_off_loop(session_id, user_id):
        return  # materialised just now, with ended_at NULL
    await arequire_session_open(session_id)


async def _require_turn_session(session_id: str, user_id: str) -> None:
    """The first half of `_open_turn_session` for the turn routes that hand a
    learning-loop session to the loop (/chat, /chat/stream, /action; spec
    §7): not discarded, owned by the caller — before the rate-limit read and
    the loop hand-off (A93 review). `_materialize_turn_session` opens the
    legacy session after. This process's own tombstones first (no I/O); the
    ownership check reads a table-held pending session too
    (`stateless_tutor_sessions`, #117)."""
    raise_if_discarded_here(session_id, user_id)
    if session_id not in PENDING_SESSIONS and await astored() and await aowned_live_row(
        session_id, user_id
    ):
        # #117: a live session answers from its sessions row, with no store read
        # (`_materialize_turn_session` then opens it through `aopen_stored`)
        return
    await araise_if_discarded(session_id, user_id)
    await arequire_session_owner(session_id, user_id)


async def _materialize_turn_session(session_id: str, user_id: str) -> None:
    """The second half of `_open_turn_session`: materialise if pending, then
    refuse an ended session (409). The turn routes run the entry checks
    first (`_require_turn_session`), hand a learning-loop session to the
    loop (spec §7), and only then open the legacy session here. With
    `stateless_tutor_sessions` on, a session not pending in this process
    opens through `aopen_stored` (#117)."""
    if session_id not in PENDING_SESSIONS and await astored():
        return await aopen_stored(session_id, user_id)
    if await _consume_pending_off_loop(session_id, user_id):
        return  # materialised just now, with ended_at NULL
    await arequire_session_open(session_id)
