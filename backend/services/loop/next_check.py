"""POST /check/next: the next check item of the plan.
"""
from __future__ import annotations

from services.loop.errors import HTTPException
from services import abuse_limits
from services.request_limits import enforce_abuse_limit
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

from services.loop.flags import _ANSWER_CLAIM, _GRADING_CLAIM, _GUESS_IN_FLIGHT, OPEN_QUESTION_KEY
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
from services.loop.planning import _continue_goal, _moved_plan_view, _plan_position, _preparing
from services.loop.pose import _superseded_prequestion, _without_claim
from services.loop.practice import _activate_next_item, _pose_payload, _worked_example_owed
from services.loop.claims import ABANDON_MOVED_PAST, _abandon_claimed, _grading_open


def check_next(body: LoopCheckNextBody, request: Request) -> dict:
    """ "Check me" (spec §9, A27): the current concept's next check item and its
    pose. No model call, so no rate limit and no invariant-23 run site; the
    budget is read only for the novice pause (§3.5): a novice-band concept is
    not activated at the hard level. The activation is tried on a read copy
    first (the budget read is not a mutate's business), then applied to the
    fresh document by one compare-and-set write. The loop-action budget
    (audit Z02) bounds it: it serves and writes with no model."""
    _gate(body.user_id, request)
    enforce_abuse_limit(abuse_limits.LOOP_ACTION, body.user_id)
    _consume_pending(body.session_id, body.user_id)
    _, course_id = _session_scope(body.session_id, body.user_id)
    state = _load_loop_state(body.session_id)
    _require_teaching(state)
    _require_no_pending_feedback(state)
    position = _plan_position(state)  # #866 K08: before the trial below moves it
    now = _now_s()
    already = _already_open(body.user_id, state, now)
    if already is not None:
        return already

    def activate(st: dict, out: dict) -> None:
        _activate_check(st, out, body.user_id, course_id, body.session_id, now)

    trial: dict = {}
    activate(state, trial)
    if trial.get("qh") is not None:
        _novice_pause(body.user_id, request, state, trial["qh"])
    out: dict = {}
    saved = _update_loop_state(body.session_id, lambda st: activate(st, out))
    if out.get("pending_grade"):
        return {"phase": "check", "pending_grade": out["pending_grade"]}
    qh = out.get("qh")
    if qh is None:  # the cursor may have moved
        saved = _continue_goal(body.session_id, body.user_id, course_id, saved)
        return _no_check_view(body.user_id, course_id, position, saved)
    return _pose_activated(body, request, saved, qh, out, position, now)


def _already_open(user_id: str, state: dict, now: float) -> dict | None:
    """The answer when the current concept already has an open check: a grade
    still being written (its pending checkpoint), or an item still open for
    grading (idempotent; A122: a worked example still owed says so). None when
    there is nothing open, so a new item is activated."""
    active = state.get("current")
    entry = (state.get("steps") or {}).get(active) if active else None
    if isinstance(entry, dict) and grade_checkpoint.KEY in entry:
        return {"phase": "check", "pending_grade": _pending_grade(state)}
    if _grading_open(entry, now):
        item = get_check_item(entry["check_item_id"]) if entry.get("check_item_id") else None
        if item is not None:
            pose = _pose_payload(item, worked_first=_worked_example_owed(user_id, state, active))
            return {"phase": "check", "check": pose}
    return None


def _activate_check(
    st: dict, out: dict, user_id: str, course_id: str, session_id: str, now: float
) -> None:
    """The activation, run on the read copy (the trial) and again on the fresh
    CAS document: it fills ``out`` with ``pending_grade``, or ``qh`` (the
    activated item, None when the cursor had none) and ``pq_superseded``."""
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
        _drop_current(st, cur_entry)
    out["qh"] = _activate_next_item(user_id, course_id, st, now=now, session_id=session_id)
    if out["qh"] is not None:
        _close_other_prompts(st, out)


def _drop_current(st: dict, cur_entry) -> None:
    """Withdrawn (A23) or held (A124, A123), graded, or left under a stale
    claim (C2): drop it; the entry stays. A claim still on it (stale, or live
    on a withdrawn item) is given up in this same write, so the grade it
    guards can never be saved on an item that is no longer current (it would
    wedge the session)."""
    if (isinstance(cur_entry, dict) and cur_entry.get(_GRADING_CLAIM)
            and cur_entry.get("graded_at") is None):
        _abandon_claimed(cur_entry, ABANDON_MOVED_PAST)
    st["current"] = None


def _close_other_prompts(st: dict, out: dict) -> None:
    """The activated card is now the one open prompt. Spec §13 A121: the
    student chose the check over the tutor's last question, so a later chat
    message is no reply to that question. A139 / A138: so is it over an open
    self-explanation prompt (its row stays 'open': never replied) and over a
    prequestion card on the concept the check opens (the segment started on a
    check)."""
    st[OPEN_QUESTION_KEY] = False
    self_explain.close_open(st)
    node = (st.get("steps") or {}).get(out["qh"], {}).get("node_id")
    rec = prequestion_rules.open_record(st, node)
    if rec is not None:
        records = dict(prequestion_rules.records(st))
        records[node] = {**_without_claim(rec), "status": prequestion_rules.SUPERSEDED}
        st[prequestion_rules.KEY] = records
        out["pq_superseded"] = (node, rec)


def _novice_pause(user_id: str, request: Request, state: dict, qh: str) -> None:
    """Spec §3.5: a novice-band concept is not activated when the budget says
    pause; raises AIBudgetExceeded before anything is activated or saved."""
    band, _ = _band_for(user_id, state["steps"][qh]["node_id"])
    if band != "novice":
        return
    decision = ai_budget.check(
        user_id,
        "tutor",
        "novice",
        session_tutor_requests=int(state.get("tutor_requests") or 0),
        session_deep_requests=int(state.get("deep_requests") or 0),
        arm_session=bool(_arm_for(user_id, request)),
    )
    if decision.pause_novice:
        raise AIBudgetExceeded(decision)  # nothing activated, nothing saved


def _no_check_view(user_id: str, course_id: str, position, saved: dict) -> dict:
    """The answer when no item was activated: where the loop stands now."""
    plan = saved.get("plan") if isinstance(saved.get("plan"), dict) else {}
    out = {"phase": _loop_phase(saved), "plan_done": bool(plan.get("done")) and _loop_phase(saved) != "plan", "check": None}
    if saved.get("goal") and isinstance(plan.get("goal_progress"), dict):
        out["goal_progress"] = plan["goal_progress"]
    if saved.get("goal"):
        out["practice_unavailable_node_ids"] = list(plan.get("practice_unavailable_node_ids") or [])
    out["checks_unavailable_node_ids"] = _checks_unavailable(saved)
    out.update(_preparing(user_id, course_id))  # A128
    out.update(_moved_plan_view(user_id, position, saved))  # K08
    return out


def _pose_activated(
    body: LoopCheckNextBody, request: Request, saved: dict, qh: str, out: dict, position, now: float
) -> dict:
    """Pose the activated item: ledger it (A93), note it for varied practice
    (A141), save the prompt as the tutor's message, and record a superseded
    prequestion (A138)."""
    item = get_check_item(saved["steps"][qh]["check_item_id"])
    # A122: an item that opens on the worked example says so (the client asks for it)
    pose = _pose_payload(item, worked_first=_worked_example_owed(body.user_id, saved, qh))
    _ledger(record_posed, body.user_id, qh, source="loop", session_id=body.session_id)  # A93
    varied_practice.note_posed(body.user_id, body.session_id, item)  # A141
    save_message(body.session_id, "assistant", pose["prompt"])
    if out.get("pq_superseded"):  # spec §13 A138
        node, rec = out["pq_superseded"]
        _superseded_prequestion(body.user_id, body.session_id, _request_id(request), node, rec, at=now)
    # K08: an activation that moved past a concept with no check says where to
    return {"phase": "check", "check": pose, **_moved_plan_view(body.user_id, position, saved)}


def _checks_unavailable(state: dict) -> list[str]:
    """The plan concepts the cursor has passed with no graded check in this
    session, in plan order: activation moves past a concept only when it has
    no servable check item left (every other cursor move follows a graded
    check on it), so these are the concepts "Check me" could not check. []
    when every passed concept had one — the plan really finished with graded
    checks. Read off loop state; no I/O."""
    raw = state.get("plan")
    plan: dict = raw if isinstance(raw, dict) else {}
    approved = [n for n in plan.get("approved") or [] if isinstance(n, str) and n]
    try:
        cursor = max(0, int(plan.get("cursor") or 0))
    except (TypeError, ValueError):
        cursor = 0
    graded = {
        e.get("node_id")
        for e in (state.get("steps") or {}).values()
        if isinstance(e, dict) and e.get("graded_at") is not None
    }
    return list(dict.fromkeys(n for n in approved[:cursor] if n not in graded))
