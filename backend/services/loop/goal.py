"""POST /goal (A143): the session's learning goal.
"""
from __future__ import annotations

from services.loop.errors import HTTPException
from starlette.requests import Request
from learning.goals import encode_goal, goal_version
from models import LoopGoalBody
from services.tutor import _consume_pending
from services.tutor_sessions import get_pending
from services import crisis_support

from services.loop.state import (
    _gate,
    _loop_phase,
    _now_s,
    _refuse_while_closing,
    _session_scope,
    _update_loop_state,
)
from services.loop.planning import (
    _learning_scope_payload,
    _plan_states,
    _probe_doc,
    _probe_plan_read_limit,
    _validate_goal,
)


def set_goal(body: LoopGoalBody, request: Request) -> dict:
    """Change confirmed scope before teaching, preserving evidence and fatigue caps."""
    _gate(body.user_id, request)
    # crisis support: the goal text later rides every tutor prompt; it is not stored
    if crisis := crisis_support.screen(
        body.user_id, "loop_goal", body.goal.text if body.goal is not None else None
    ):
        return crisis_support.json_body(crisis)
    _probe_plan_read_limit(body.user_id)
    pending = get_pending(body.session_id)
    if pending is not None:
        if pending.get("user_id") != body.user_id:
            raise HTTPException(status_code=404, detail="Session not found")
        if _loop_phase(pending.get("loop_state") or {}) not in ("probe", "plan"):
            raise HTTPException(status_code=409, detail="Start a new session to change a teaching goal")
        course_id = pending.get("course_id") or ""
    else:
        _, course_id = _session_scope(body.session_id, body.user_id)
    states = _plan_states(body.user_id, course_id)
    _validate_goal(body.goal, states)
    _consume_pending(body.session_id, body.user_id)
    encoded = encode_goal(body.goal)
    now = _now_s()

    def change(doc: dict) -> None:
        _refuse_while_closing(doc, now)
        if _loop_phase(doc) not in ("probe", "plan"):
            raise HTTPException(status_code=409, detail="Start a new session to change a teaching goal")
        pr = _probe_doc(doc)
        current = pr.get("current") or {}
        if current.get("grading_claim"):
            raise HTTPException(status_code=409, detail="Wait for the current answer to finish grading")
        if current.get("question_hash") and current["question_hash"] not in pr["unavailable"]:
            pr["unavailable"].append(current["question_hash"])
        for key in ("skills", "scope", "available_difficulties", "stop_reason", "novice_floor"):
            pr.pop(key, None)
        pr["current"] = None
        doc["goal"], doc["goal_version"] = encoded, goal_version(doc) + 1
        doc.pop("plan", None)
        doc["phase"] = "probe"

    saved = _update_loop_state(body.session_id, change, require_open=True)
    return {"phase": "probe", **_learning_scope_payload(saved)}
