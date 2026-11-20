"""Tutor session lifecycle (#118, moved verbatim from routes/learn.py): end,
list, rename, delete, resume and mode-switch, plus the end-of-session summary.
The handler bodies keep their names; routes/learn.py wraps them.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from db.connection import like_literal, pg_quote_value, rpc, table
from db.scope import runs_as_service
from models import EndSessionBody, ModeSwitchBody, RenameSessionBody
from services import events_service
from services.academics import offering_course_id
from services.auth_guard import get_session_user_id, guard_off_loop, require_self
from services import abuse_limits
from services.request_limits import aenforce_abuse_limit
from services.graph_service import _normalize_concept
from services.encryption import bind, decrypt_if_present, decrypt_json_column, encrypt_json
from services.session_modes import NOT_REVIEW, REVIEW_MODE
from services.streak_service import touch_streak_safe
from services.tutor.errors import HTTPException
from services.tutor.messages import save_message
from services.tutor.pending import _open_turn_session, get_user_name
from services.tutor_sessions import (
    SESSION_NOT_FOUND as _SESSION_NOT_FOUND,
    aget_pending,
    arequire_session_owner,
    discard_if_pending,
    discarded_reason,
    elapsed_minutes as _elapsed_minutes,
    get_pending,
    rename_pending,
    require_session_owner,
    row_may_exist as _session_row_may_exist,
)
from services.xp_service import award_xp_safe

# Log records keep the name they had in routes/learn.py before the #118 split:
# the move must not change what an operator (or a caplog test) filters on.
logger = logging.getLogger("routes.learn")


MODE_DISPLAY_NAMES = {
    "socratic": "Socratic (question-based)",
    "expository": "Expository (direct explanation)",
    "teachback": "Teach-back (you explain to me)",
}


#: The `sessions` columns `_session_summary` reads its own concept from.
_SESSION_CONCEPT_COLUMNS = "user_id,topic,offering_id"

#: How many candidate nodes the session-concept lookup reads: the name filter
#: leaves only spellings of one name, so this only bounds the read.
_CONCEPT_CANDIDATES = 50


def _session_concept(session: dict | None) -> str | None:
    """#866 K47: the concept a session was opened on — its topic, when that is
    the name of one of the student's graph nodes (in the session's course when
    it has one), as the picker and the map send it; the stored name. A topic
    matches a node up to case and spacing (`graph_service._normalize_concept`,
    the fold the graph dedups on and the quiz's tutor recency matches with), so
    both readers agree on which sessions were on a concept. None for a free
    topic, a course or a note's title, or a failed read (best effort: the
    summary never fails an end)."""
    row = session or {}
    topic = (row.get("topic") or "").strip()
    user_id = row.get("user_id")
    key = _normalize_concept(topic)
    if not key or not user_id:
        return None
    # Server-side narrowing to spellings of this one name (each word verbatim,
    # anything between words); the exact fold is decided below, in Python.
    pattern = "%".join(like_literal(word) for word in key.split(" "))
    filters = {"user_id": f"eq.{user_id}", "or": f"(concept_name.ilike.{pg_quote_value(pattern)})"}
    try:
        course_id = offering_course_id(row.get("offering_id"))
        if course_id:
            filters["course_id"] = f"eq.{course_id}"
        rows = table("graph_nodes").select("concept_name", filters=filters, limit=_CONCEPT_CANDIDATES) or []
    except Exception:  # noqa: BLE001 — best effort: an unread concept never fails the end
        logger.warning("session summary: the session's concept could not be read", exc_info=True)
        return None
    names = [r.get("concept_name") or "" for r in rows if isinstance(r, dict)]
    matches = [name for name in names if _normalize_concept(name) == key]
    return (topic if topic in matches else matches[0]) if matches else None


def _session_summary(
    session_id: str, started_at: str, ended_at: str | None = None, *, session: dict | None = None,
) -> dict:
    """The end-of-session summary: the concepts it covered and minutes from
    start to ``ended_at`` (now if None). Reads only — safe to recompute for a
    repeat end.

    Covered: the concept the session was opened on (`session`, its row), once
    the student wrote in it, then every concept the transcript's
    graph_update_json names. PKG-14b (spec §11.2) took away the tutor's mastery
    tool, whose `updated_nodes` were most of that list; without the session's
    own concept a loop-off student's summary was usually empty (#866 K47).
    Rows written before PKG-14b still carry `updated_nodes`."""
    msgs = table("messages").select(
        "role,graph_update_json",
        filters={"session_id": f"eq.{session_id}"},
    )

    covered: dict[str, None] = {}  # insertion-ordered, deduped
    if any(msg.get("role") == "user" for msg in msgs):
        if concept := _session_concept(session):
            covered[concept] = None
    for msg in msgs:
        if msg["graph_update_json"]:
            try:
                gu = msg["graph_update_json"]
                if isinstance(gu, str):
                    gu = json.loads(gu)
                for upd in gu.get("updated_nodes", []):
                    covered.setdefault(upd["concept_name"])
                for nn in gu.get("new_nodes", []):
                    covered.setdefault(nn["concept_name"])
            except Exception:
                pass

    # PKG-14b (spec §11.2): the three always-empty lists are gone.
    return {
        "concepts_covered": list(covered),
        "time_spent_minutes": _elapsed_minutes(started_at, until=ended_at),
    }


def _stored_session_summary(session_id: str) -> dict:
    """What a repeat /end-session returns (#761): the summary the closing
    call stored, or — if that call hasn't written it yet — the same summary
    recomputed up to the stored ended_at. Never writes."""
    rows = table("sessions").select(
        f"started_at,ended_at,summary_json,{_SESSION_CONCEPT_COLUMNS}",
        filters={"id": f"eq.{session_id}"},
        limit=1,
    )
    row = rows[0] if rows else {}
    stored = row.get("summary_json")
    if stored:
        try:
            summary = decrypt_json_column(
                stored, bind=bind("sessions", "summary_json", session_id),
            )
            if isinstance(summary, dict):
                return summary
        except Exception:
            logger.warning("stored session summary unreadable; recomputing", exc_info=True)
    return _session_summary(session_id, row.get("started_at") or "", row.get("ended_at"), session=row)


def end_session(body: EndSessionBody, request: Request, loop_handler=None):
    if body.user_id:
        require_self(body.user_id, request)
    else:
        body.user_id = get_session_user_id(request)
    # A session already ended while still pending has no row and no pending
    # entry left; its tombstone is what proves the caller ended it (#761).
    ended_while_pending = discarded_reason(body.session_id, body.user_id) == "ended"
    if not ended_while_pending:
        require_session_owner(body.session_id, body.user_id)
        # Learning loop (spec §7): `loop_handler` is the loop's handler when the
        # route-entry gate is on for this student (routes/learn.py evaluates it,
        # owner decision 00; the `learning_loop` flag defaults off); below is
        # the legacy path (spec §11.6). No model runs here, so no budget check.
        if loop_handler is not None:
            request.state.learning_loop = True  # A38 00: the loop handler reads no second gate
            loop = loop_handler(body, request)
            if loop is not None:
                return loop
    empty = {
        "concepts_covered": [],
        "time_spent_minutes": 0,
    }
    # Discard under the materialisation lock so a concurrent first turn can't
    # insert the row after we drop the entry. A pending session whose row was
    # never attempted has nothing in the DB to end. One whose materialisation
    # attempted the row (and then failed, say on the greeting) may have a
    # row, so it is ended in the DB too, as is one that materialised while
    # we waited. The discard leaves an "ended" tombstone, so a turn racing
    # this end answers 409 instead of writing into a session with no row.
    popped = discard_if_pending(body.session_id, user_id=body.user_id, reason="ended")
    if popped is not None and not _session_row_may_exist(popped):
        return {"summary": empty}

    session_rows = table("sessions").select(
        f"started_at,{_SESSION_CONCEPT_COLUMNS}",
        # a daily review session is never ended here: no XP, streak or summary (A73)
        filters={"id": f"eq.{body.session_id}", **NOT_REVIEW},
    )
    if not session_rows:
        if popped is not None or ended_while_pending:
            return {"summary": empty}  # the attempted row write never landed
        raise HTTPException(status_code=404, detail=_SESSION_NOT_FOUND)
    session = session_rows[0]

    # #761: the end is CONDITIONAL on the session still being open, and the
    # returned rows say whether THIS call closed it. Only that call awards,
    # emits session.ended and runs the session_* achievements — which are
    # computed from ended_at, so an unconditional re-end let a student move
    # ended_at to a chosen hour and farm Early Bird / Night Owl / Deep Focus.
    # A repeat end returns the stored summary and changes nothing.
    ended_at = datetime.now(timezone.utc).isoformat()
    closed = table("sessions").update(
        {"ended_at": ended_at},
        filters={"id": f"eq.{body.session_id}", "ended_at": "is.null"},
    )
    if not closed:
        return {"summary": _stored_session_summary(body.session_id), "achievements_earned": []}

    # The row above is the commit point for "session completed" — award
    # immediately after it, keyed on the session id. Only the call that
    # closed the session gets here; the xp_events idempotency key is a
    # second line of defence.
    award_xp_safe(
        body.user_id, "session_completed",
        source_type="session", source_id=body.session_id,
    )

    # touch_streak_safe shares this exact commit point: it's the same
    # post-"session completed" moment as the XP award above, past the
    # pending-session early return, and touch_streak's own same-day check
    # makes a double end-session call a no-op just like the xp_events key
    # does for the award above. Run it before the login_streak achievement
    # check below so that check sees today's advanced streak_count.
    touch_streak_safe(body.user_id)

    summary = _session_summary(body.session_id, session["started_at"], ended_at, session=session)
    elapsed_minutes = summary["time_spent_minutes"]
    concepts_covered = summary["concepts_covered"]

    # #117: session.ended for real (materialized) sessions only — the pending
    # early-return above emits nothing. concepts_covered is a COUNT; the
    # concept names never enter the payload. No timestamps in payload either
    # (created_at is a DB default).
    events_service.log_event(
        "session.ended",
        category="usage",
        user_id=body.user_id,
        payload={
            "session_id": body.session_id,
            "time_spent_minutes": elapsed_minutes,
            "concepts_covered": len(concepts_covered),
        },
    )

    table("sessions").update(
        {"summary_json": encrypt_json(
            summary, bind=bind("sessions", "summary_json", body.session_id),
        )},
        filters={"id": f"eq.{body.session_id}"},
    )

    # Check for achievements after session end
    newly_earned = []
    try:
        from services.achievement_service import check_achievements
        newly_earned = check_achievements(body.user_id, "login_streak", {})
        newly_earned += check_achievements(body.user_id, "session_count", {})
        # A finished session is the only thing that advances these. Without
        # them `deep-focus` (session_minutes), `early-bird`
        # (session_before_hour), `night-owl` (session_after_midnight) and
        # `perfect-week` (goal_streak) are live badges nothing can award.
        # Fired here, after the sessions row has its ended_at, because every
        # one of these stats is computed from ended_at.
        newly_earned += check_achievements(body.user_id, "session_minutes", {})
        newly_earned += check_achievements(body.user_id, "session_before_hour", {})
        newly_earned += check_achievements(body.user_id, "session_after_midnight", {})
        # goal_streak counts days that met daily_goal_xp; the session_completed
        # award above may well be what tipped today over the line.
        newly_earned += check_achievements(body.user_id, "goal_streak", {})
    except Exception:
        logger.warning("session-end achievement checks failed", exc_info=True)

    return {"summary": summary, "achievements_earned": newly_earned}


#: list_sessions returns at most this many rows (the client asks for 10; a
#: limit <= 0 used to mean "all") and counts messages 8 reads at a time.
SESSION_LIST_MAX, _SESSION_COUNT_CONCURRENCY = 100, 8


async def list_sessions(user_id: str, request: Request, limit: int = 10):
    await guard_off_loop(require_self, user_id, request)
    limit = SESSION_LIST_MAX if limit <= 0 else min(limit, SESSION_LIST_MAX)
    sessions = await table("sessions").aselect(
        # close_json is read only for IS NULL (a ciphertext is never compared);
        # the loop phase alone says the row is a learning-loop session.
        "id,user_id,topic,mode,offering_id,started_at,ended_at,close_json,loop_phase:loop_state->>phase",
        filters={"user_id": f"eq.{user_id}", **NOT_REVIEW},  # review queue rows are not tutor sessions
        order="started_at.desc",
        limit=limit,
    )
    gate = asyncio.Semaphore(_SESSION_COUNT_CONCURRENCY)

    async def message_count(sid: str) -> int:  # count=exact over a one-row body
        async with gate:
            return (await table("messages").aselect_with_count(
                "id", filters={"session_id": f"eq.{sid}"}, limit=1))[1]

    counts = await asyncio.gather(*(message_count(s["id"]) for s in sessions))
    # Sessions key on the offering; the frontend speaks abstract course ids.
    # Map each offering → its abstract course once.
    offering_to_course: dict[str, str | None] = {}
    result = []
    for s, n_messages in zip(sessions, counts):
        off_id = s.get("offering_id")
        if off_id and off_id not in offering_to_course:
            offering_to_course[off_id] = await run_in_threadpool(offering_course_id, off_id)
        result.append({
            "id": s["id"],
            "topic": s["topic"],
            "mode": s["mode"],
            "course_id": offering_to_course.get(off_id),
            "started_at": s["started_at"],
            "ended_at": s.get("ended_at"),
            "message_count": n_messages,
            "is_active": s.get("ended_at") is None,
            # A learning-loop session the student can still resume: the Tutor's
            # recents mark it "in progress" (a loop close writes close_json,
            # never ended_at, so is_active alone reads a wrapped-up one as open).
            "loop_open": bool(s.get("loop_phase")) and s.get("ended_at") is None and s.get("close_json") is None,
        })
    return {"sessions": result}


def rename_session(session_id: str, body: RenameSessionBody, request: Request):
    require_self(body.user_id, request)
    topic = body.topic.strip()
    if not topic or len(topic) > 120:
        raise HTTPException(status_code=400, detail="Topic must be 1-120 characters")

    require_session_owner(session_id, body.user_id)
    # A pending session: rename the copy a later materialisation will write
    # (and the row too if an earlier attempt may already have written it).
    if rename_pending(session_id, topic):
        return {"updated": True, "session": {"id": session_id, "topic": topic}}

    table("sessions").update(
        {"topic": topic},
        filters={"id": f"eq.{session_id}"},
    )
    return {"updated": True, "session": {"id": session_id, "topic": topic}}


#: 20261118195124_learning_session_node_erase.sql: clears one session's typed
#: text in the loop's append-only teach-prompt records (service_role may not
#: write them directly).
_SESSION_TEXT_ERASE = "learning_session_text_erase"


@runs_as_service  # the teach-prompt records and their erase function are service-only (A148)
def _erase_session_text(user_id: str, session_id: str) -> None:
    """PR #866 C8: the student's own words in a deleted session — a
    prequestion guess, a self-explanation reply — are cleared. The rows stay
    (an answered prequestion is a release A76's re-check reads across
    sessions; a reply's length feeds the admin report), with no text. Raises
    on a failed call."""
    rpc(_SESSION_TEXT_ERASE, {"p_user_id": user_id, "p_session_id": session_id})


def delete_session(session_id: str, request: Request, user_id: str | None = None):
    if user_id:
        require_self(user_id, request)
    else:
        user_id = get_session_user_id(request)
    # Idempotent and unrevealing (#709 review): a missing OR foreign session is a
    # no-op 200 — nothing is deleted, and the answer never says whether the id
    # exists. A second delete (another tab, a double click) still succeeds.
    # A known OWNED daily-review row is explicitly refused. Missing and
    # foreign ids still share #709's idempotent success below. Never delete
    # the daily queue through the tutor endpoint (that would reset its budget).
    # One read decides both: the owned row (if any) and its mode. A pending
    # session (memory or table) has no row yet and is judged by its payload.
    pending = get_pending(session_id)
    if pending is not None:
        owned = pending.get("user_id") == user_id and pending.get("mode") != REVIEW_MODE
    else:
        owner_rows = table("sessions").select(
            "user_id,mode",
            filters={"id": f"eq.{session_id}", "user_id": f"eq.{user_id}"},
            limit=1,
        )
        owned = bool(owner_rows) and owner_rows[0].get("user_id") == user_id
        if owned and owner_rows[0].get("mode") == REVIEW_MODE:
            raise HTTPException(status_code=404, detail=_SESSION_NOT_FOUND)
    if not owned:
        return {"deleted": True}
    # Every delete leaves a "deleted" tombstone (#761): a turn already past
    # its ownership check answers 404 at its next write instead of an FK
    # failure (or, for a pending session, instead of materialising a row the
    # student just deleted).
    popped = discard_if_pending(session_id, user_id=user_id, reason="deleted", always=True)
    if popped is not None and not _session_row_may_exist(popped):
        return {"deleted": True}
    # A row may exist (an attempted materialisation, one that finished while
    # we waited, or a live session): delete it. Both deletes are no-ops if not.
    # The loop's teach-prompt text goes FIRST (C8): a failure answers 500 with
    # the row still there, so the retry still owns the session and erases it.
    _erase_session_text(user_id, session_id)
    table("messages").delete({"session_id": f"eq.{session_id}"})
    table("sessions").delete({"id": f"eq.{session_id}"})
    return {"deleted": True}


async def resume_session(session_id: str, request: Request):
    user_id = await guard_off_loop(get_session_user_id, request)
    await arequire_session_owner(session_id, user_id)
    # .get(), not `in` + [...]: a concurrent first turn or delete can drop the
    # entry in between. Gone means it materialised (or was discarded): read
    # the DB below.
    p = await aget_pending(session_id)
    if p is not None:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "session": {
                "id": session_id,
                "user_id": p["user_id"],
                "topic": p["topic"],
                "mode": p["mode"],
                "course_id": p.get("course_id"),
                "started_at": now,
                "ended_at": None,
            },
            "messages": [
                {
                    "id": "pending_assistant",
                    "role": "assistant",
                    "content": p["assistant_reply"],
                    "created_at": now,
                },
            ],
        }

    session_rows = await table("sessions").aselect(
        "id,user_id,topic,mode,started_at,ended_at,offering_id",
        filters={"id": f"eq.{session_id}", **NOT_REVIEW},  # a review session is never resumed
    )
    if not session_rows:
        raise HTTPException(status_code=404, detail=_SESSION_NOT_FOUND)

    # Expose the abstract course id (derived from the offering) for the
    # frontend, alongside the stored offering id.
    session = dict(session_rows[0])
    session["course_id"] = await run_in_threadpool(offering_course_id, session.get("offering_id"))

    msgs = await table("messages").aselect(
        "id,role,content,created_at",
        filters={"session_id": f"eq.{session_id}"},
        order="created_at.asc",
    )
    return {
        "session": session,
        "messages": [
            {**m, "content": decrypt_if_present(
                m["content"], bind=bind("messages", "content", session_id),
            )} for m in msgs
        ],
    }


async def mode_switch(body: ModeSwitchBody, request: Request):
    await guard_off_loop(require_self, body.user_id, request)
    await aenforce_abuse_limit(abuse_limits.TUTOR_TURN, body.user_id)
    # `new_mode` is a TutorMode Literal, so the body validation has already
    # refused anything sessions.mode's CHECK constraint would (422).
    await _open_turn_session(body.session_id, body.user_id)
    # #761: the switch is a session state change, not just a message — the
    # stored mode is what the session list and resume report.
    await table("sessions").aupdate(
        {"mode": body.new_mode},
        filters={"id": f"eq.{body.session_id}", "ended_at": "is.null"},
    )
    student_name = (await run_in_threadpool(get_user_name, body.user_id)).split()[0]
    session_rows = await table("sessions").aselect(
        "topic,mode", filters={"id": f"eq.{body.session_id}"}, limit=1
    )
    if session_rows and session_rows[0].get("mode") == REVIEW_MODE:  # never a tutor session (A73)
        raise HTTPException(status_code=404, detail="Session not found")
    topic = session_rows[0]["topic"] if session_rows else "this topic"
    
    mode_label = MODE_DISPLAY_NAMES.get(body.new_mode, body.new_mode)

    reply = (
        f"Got it, {student_name}! Switching to {mode_label} mode. "
        f"We'll continue with {topic}, let's keep going!"
    )
    await save_message(body.session_id, "assistant", reply)
    return {"reply": reply}
