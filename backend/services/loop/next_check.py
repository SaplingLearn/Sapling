"""POST /check/next: the next check item of the plan.
"""
from __future__ import annotations

from services.loop.errors import HTTPException
from starlette.requests import Request
from learning import grade_checkpoint
from learning import prequestion as prequestion_rules
from learning import self_explain
from learning.help_ledger import record_posed
from models import LoopCheckNextBody
from services.tutor import save_message_sync as save_message
from services.tutor import _consume_pending
from services import ai_budget
from services.ai_budget import AIBudgetExceeded
from services.check_item_service import get_check_item
from services import varied_practice

from services.loop.flags import _ANSWER_CLAIM, _GUESS_IN_FLIGHT, OPEN_QUESTION_KEY
from services.loop.state import (
    _arm_for,
    _gate,
    _live,
    _load_loop_state,
    _loop_phase,
    _now_s,
    _pending_grade,
    _request_id,
    _require_no_pending_feedback,
    _require_teaching,
    _session_scope,
    _update_loop_state,
)
from services.loop.learner import _band_for
from services.loop.reveals import _ledger
from services.loop.planning import _continue_goal, _preparing
from services.loop.pose import _superseded_prequestion, _without_claim
from services.loop.practice import _activate_next_item, _pose_payload, _worked_example_owed
from services.loop.claims import _grading_open


def check_next(body: LoopCheckNextBody, request: Request) -> dict:
    """ "Check me" (spec §9, A27): the current concept's next check item and its
    pose. No model call, so no rate limit and no invariant-23 run site; the
    budget is read only for the novice pause (§3.5): a novice-band concept is
    not activated at the hard level. The activation is tried on a read copy
    first (the budget read is not a mutate's business), then applied to the
    fresh document by one compare-and-set write."""
    _gate(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)
    _, course_id = _session_scope(body.session_id, body.user_id)
    state = _load_loop_state(body.session_id)
    _require_teaching(state)
    _require_no_pending_feedback(state)
    active = state.get("current")
    entry = (state.get("steps") or {}).get(active) if active else None
    now = _now_s()
    if isinstance(entry, dict) and grade_checkpoint.KEY in entry:
        return {"phase": "check", "pending_grade": _pending_grade(state)}
    if _grading_open(entry, now):
        item = get_check_item(entry["check_item_id"]) if entry.get("check_item_id") else None
        if item is not None:  # idempotent (A122: a worked example still owed says so)
            pose = _pose_payload(item, worked_first=_worked_example_owed(body.user_id, state, active))
            return {"phase": "check", "check": pose}

    def activate(st: dict, out: dict) -> None:
        out.clear()
        _require_teaching(st)
        _require_no_pending_feedback(st)  # recheck on the fresh CAS document too
        cur = st.get("current")
        cur_entry = (st.get("steps") or {}).get(cur) if cur else None
        if isinstance(cur_entry, dict) and grade_checkpoint.KEY in cur_entry:
            out["pending_grade"] = _pending_grade(st)
            return
        if _grading_open(cur_entry, now):
            if cur_entry.get("check_item_id") and get_check_item(cur_entry["check_item_id"]):
                out["qh"] = cur  # another request activated one meanwhile
                return
        # Spec §13 A138 (review fix): a guess being saved under its claim is
        # the one open prompt until it commits — no check opens over it
        card = prequestion_rules.open_record(st, st.get("concept"))
        if card is not None and _live(card, _ANSWER_CLAIM, now):
            raise HTTPException(status_code=409, detail=_GUESS_IN_FLIGHT)
        if cur:
            # withdrawn (A23) or held (A124, A123), graded, or left under a
            # stale claim (C2): drop it; the entry stays
            st["current"] = None
        out["qh"] = _activate_next_item(body.user_id, course_id, st, now=now)
        if out["qh"] is not None:
            # Spec §13 A121: the student chose the check over the tutor's last
            # question; the card is now the one open prompt, so a later chat
            # message is no reply to that question
            st[OPEN_QUESTION_KEY] = False
            # Spec §13 A139 / A138: so is it over an open self-explanation prompt
            # (its row stays 'open': never replied) and over a prequestion card
            # on the concept the check opens (the segment started on a check)
            self_explain.close_open(st)
            node = (st.get("steps") or {}).get(out["qh"], {}).get("node_id")
            rec = prequestion_rules.open_record(st, node)
            if rec is not None:
                records = dict(prequestion_rules.records(st))
                records[node] = {**_without_claim(rec), "status": prequestion_rules.SUPERSEDED}
                st[prequestion_rules.KEY] = records
                out["pq_superseded"] = (node, rec)

    trial: dict = {}
    activate(state, trial)
    if trial.get("qh") is not None:
        band, _ = _band_for(body.user_id, state["steps"][trial["qh"]]["node_id"])
        if band == "novice":
            decision = ai_budget.check(
                body.user_id,
                "tutor",
                "novice",
                session_tutor_requests=int(state.get("tutor_requests") or 0),
                session_deep_requests=int(state.get("deep_requests") or 0),
                arm_session=bool(_arm_for(body.user_id, request)),
            )
            if decision.pause_novice:
                raise AIBudgetExceeded(decision)  # nothing activated, nothing saved
    out: dict = {}
    saved = _update_loop_state(body.session_id, lambda st: activate(st, out))
    if out.get("pending_grade"):
        return {"phase": "check", "pending_grade": out["pending_grade"]}
    qh = out.get("qh")
    if qh is None:  # the cursor may have moved
        saved = _continue_goal(body.session_id, body.user_id, course_id, saved)
        plan = saved.get("plan") if isinstance(saved.get("plan"), dict) else {}
        out = {"phase": _loop_phase(saved), "plan_done": bool(plan.get("done")) and _loop_phase(saved) != "plan", "check": None}
        if saved.get("goal") and isinstance(plan.get("goal_progress"), dict):
            out["goal_progress"] = plan["goal_progress"]
        if saved.get("goal"):
            out["practice_unavailable_node_ids"] = list(plan.get("practice_unavailable_node_ids") or [])
        out.update(_preparing(body.user_id, course_id))  # A128
        return out
    item = get_check_item(saved["steps"][qh]["check_item_id"])
    # A122: an item that opens on the worked example says so (the client asks for it)
    pose = _pose_payload(item, worked_first=_worked_example_owed(body.user_id, saved, qh))
    _ledger(record_posed, body.user_id, qh, source="loop", session_id=body.session_id)  # A93
    varied_practice.note_posed(body.user_id, body.session_id, item)  # A141
    save_message(body.session_id, "assistant", pose["prompt"])
    if out.get("pq_superseded"):  # spec §13 A138
        node, rec = out["pq_superseded"]
        _superseded_prequestion(body.user_id, body.session_id, _request_id(request), node, rec, at=now)
    return {"phase": "check", "check": pose}
