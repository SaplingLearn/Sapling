"""GET /status and GET /sessions: a session's status and the student's open
loop sessions (PKG-13).
"""
from __future__ import annotations

import copy
from services.loop.errors import HTTPException
from starlette.requests import Request
from db.connection import table
from services.tutor_sessions import get_pending
from services.academics import course_offering_ids, offering_course_id
from services.check_item_service import get_check_item
from services.session_modes import NOT_REVIEW

from services.loop.state import (
    _gate,
    _load_loop_state,
    _loop_phase,
    _pending_grade,
    _phase_for,
    _session_scope,
    _step_state,
)
from services.loop.learner import (
    _band_ceiling_delta,
    _band_of,
    _ceiling_for,
    _learner_state,
    _learner_view,
    _node_for_item,
    _prereq_proficient,
)
from services.loop.planning import _learning_scope_payload
from services.loop.pose import _open_teach_prompts
from services.loop.practice import _pose_payload, _worked_example_owed


# ── Endpoints ──────────────────────────────────────────────────────────────


def status(request: Request, user_id: str, session_id: str) -> dict:
    _gate(user_id, request)
    pending = get_pending(session_id)
    if pending is not None:
        if pending.get("user_id") != user_id:
            raise HTTPException(status_code=404, detail="Session not found")
        state: dict = copy.deepcopy(pending.get("loop_state") or {})
    else:
        try:
            _session_scope(session_id, user_id)
            state = _load_loop_state(session_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            state = {}  # no session yet: a fresh loop (never the gate's 404)
    active = state.get("current")
    entry = (state.get("steps") or {}).get(active) if active else None
    pending_grade = _pending_grade(state)
    item = (
        get_check_item(entry["check_item_id"])
        if isinstance(entry, dict) and entry.get("check_item_id") and not pending_grade
        else None
    )
    node_id = (_node_for_item(user_id, item) if item is not None else None) or state.get("concept")
    learner = _learner_state(user_id, node_id)
    band, p_known = _band_of(learner)
    step = _step_state(state, active if item is not None else None)
    prereq = _prereq_proficient(user_id, node_id) if node_id else True
    ceiling, _ = _ceiling_for(
        step=step,
        learner=_learner_view(learner, band=band, prereq_proficient=prereq),
        message="",
        independent_s=0.0,
        band_delta=_band_ceiling_delta(state, node_id),  # spec §13 A122
    )
    pending_withdrawn_feedback = item is None and _phase_for(state) == "feedback"
    phase = ("check" if pending_grade and pending_grade["kind"] == "check"
             else "feedback" if pending_withdrawn_feedback
             else _phase_for(dict(state, current=active if item is not None else None)))
    # spec §13 A138 / A139: an open card is restored READ-ONLY on resume — each
    # key present only when there is one (never null), behind its flag
    teach_prompts = _open_teach_prompts(user_id, state) if not pending_grade else {}
    return {
        **teach_prompts,
        "active": True,
        "session_id": session_id,
        "loop_phase": _loop_phase(state),  # PKG-08: probe | plan | teach (resume point)
        **_learning_scope_payload(state),
        "phase": phase,
        "pending_grade": pending_grade,
        # PKG-13 reopen: the open item's pose, so a resuming client restores the
        # check READ-ONLY (POST /check/next may activate — write — another item).
        # Only while the item takes answers; never the reference (A17/A22). A122:
        # it still says so when its worked example is owed (the client asks for it).
        "check": (
            _pose_payload(item, worked_first=_worked_example_owed(user_id, state, active))
            if item is not None and phase == "check"
            else None
        ),
        "band": band,
        "ceiling": int(ceiling),
        "active_question_hash": active if item is not None else None,
        "items": len(state.get("steps") or {}),
        "rung": int(step.rung) if item is not None else None,
        "attempts": step.genuine_attempts if item is not None else 0,
    }


# ── Open loop sessions (PKG-13; spec §9, §11.3, §13 A26) ────────────────────
# What LoopLearn resumes instead of starting a new probe: the student's loop
# sessions for the course that have loop_state, no close record and no end.
# Read-only — no write, no model, no event — and never rate-limited (A20: a
# failure here must not push a student off the loop UI). The offerings are the
# COURSE's (`course_offering_ids`): a loop session is stamped with
# `resolve_offering(course, create=True)` — the current term — which is not the
# enrollment's offering once a term rolls over (#553/#529); ownership is the
# `user_id` filter. Offerings the store cannot vouch for are a 503 (the
# client's retry state), never an empty list — that would start a new probe.
# `loop_state=neq.{}` keeps legacy tutor sessions (the column default '{}') out
# BEFORE the limit; mode='review' rows are PKG-12's daily review sessions
# (NOT_REVIEW). A lazy session (spec §9) has no row until its first loop write,
# so it is not listed. `phase` is the phase GET /status reports for the same
# document: `_loop_phase` (probe | plan | teach), refined in teach by
# `_phase_for` (teach | check | feedback); a document whose close is being
# stored (`phase: close`) is not open. (`close_phase` is written together with
# `close_json`, so an open row never has one.)
LOOP_OPEN_SESSIONS_LIMIT = 10  # † picker length; mirrors the legacy getSessions(limit=10)


_OFFERINGS_UNKNOWN = "course offerings unavailable, retry"


def _open_loop_filters(user_id: str) -> dict:
    """An open loop session of this student: no close record, no end, loop state,
    not a review session."""
    return {
        "user_id": f"eq.{user_id}",
        "close_json": "is.null",  # never an equality on the ciphertext (invariant 9)
        "ended_at": "is.null",
        "loop_state": "neq.{}",
        **NOT_REVIEW,
    }


def _open_session_entry(row: dict) -> dict | None:
    """The listed shape of one open row, or None when it is not resumable."""
    state = row.get("loop_state")
    if not isinstance(state, dict) or not state:
        return None
    loop_phase = _loop_phase(state)
    if loop_phase == "close":
        return None
    return {
        "session_id": row["id"],
        "topic": row.get("topic") or "",
        "started_at": row.get("started_at"),
        "phase": _phase_for(state) if loop_phase == "teach" else loop_phase,
    }


def _resume_entry(user_id: str, session_id: str) -> dict | None:
    """`?resume=<id>` outside the list (another course, or past the limit): ONE
    read of that row under the same open-loop filters, its course from the
    offering. None when it is not this student's open loop session — the client
    then shows it read-only (a legacy chat) — or its course cannot be told."""
    rows = (
        table("sessions").select(
            "id,topic,started_at,loop_state,offering_id",
            filters={"id": f"eq.{session_id}", **_open_loop_filters(user_id)},
            limit=1,
        )
        or []
    )
    entry = _open_session_entry(rows[0]) if rows else None
    course = offering_course_id(rows[0].get("offering_id") or "") if entry else None
    return {**entry, "course_id": course} if entry and course else None


def list_open_sessions(
    request: Request,
    user_id: str,
    course_id: str,
    resume: str | None = None,
) -> dict:
    """PKG-13 fix round: `resume` (the `/learn?resume=<id>` deep link) adds
    `"resume": {…, course_id} | null` — the named session when it is the
    student's open loop session in ANY course, even past the list limit."""
    _gate(user_id, request)  # require_self, then the spec §7 404
    offering_ids = course_offering_ids(course_id)
    if offering_ids is None:
        raise HTTPException(status_code=503, detail=_OFFERINGS_UNKNOWN)
    rows = (
        table("sessions").select(
            "id,topic,started_at,loop_state",
            filters={
                **_open_loop_filters(user_id),
                "offering_id": f"in.({','.join(offering_ids)})",
            },
            order="started_at.desc",
            limit=LOOP_OPEN_SESSIONS_LIMIT,
        )
        if offering_ids
        else []
    ) or []
    sessions = [e for e in map(_open_session_entry, rows) if e is not None]
    if resume is None:
        return {"sessions": sessions}
    listed = next((s for s in sessions if s["session_id"] == resume), None)
    found = {**listed, "course_id": course_id} if listed else _resume_entry(user_id, resume)
    return {"sessions": sessions, "resume": found}
