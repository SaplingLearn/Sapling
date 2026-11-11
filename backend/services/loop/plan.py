"""GET /plan and POST /plan/approve (PKG-08): the plan the probe built.
"""
from __future__ import annotations

import logging
from services.loop.errors import HTTPException
from starlette.requests import Request
from learning.goals import goal_version, attempted_nodes, progress as goal_progress
from learning.learner_brief import store_brief
from learning.params import BKT_L0, PLAN_ORDER
from models import PlanApproveBody
from services import events_service

from services.loop.flags import _prequestion_on
from services.loop.state import (
    _gate,
    _load_loop_state,
    _now_s,
    _refuse_while_closing,
    _request_id,
    _session_scope,
    _update_loop_state,
)
from services.loop.planning import (
    _check_goal_version,
    _current_plan,
    _goal_practice_unavailable,
    _learning_scope_payload,
    _plan_node_names,
    _probe_plan_read_limit,
    _require_phase,
    _update_if_changed,
)
from services.loop.pose import _NO_POSE, _pose_prequestion, _posed_prequestion

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


def plan_get(request: Request, user_id: str, session_id: str) -> dict:
    """Current goal-scoped frontier; every new frontier requires explicit approval."""
    _gate(user_id, request)
    _probe_plan_read_limit(user_id)
    _, course_id = _session_scope(session_id, user_id)
    state = _load_loop_state(session_id)
    _require_phase(state, "plan")
    version = goal_version(state)
    view = _current_plan(state, user_id, course_id)
    proposal, targets = view.proposal, view.targets
    ids = [c.node_id for c in proposal.concepts]
    kinds = {c.node_id: c.kind for c in proposal.concepts}

    def store(doc: dict) -> None:
        _require_phase(doc, "plan")
        _check_goal_version(doc, version)
        _refuse_while_closing(doc, _now_s())
        plan_doc = doc.get("plan") if isinstance(doc.get("plan"), dict) else {}
        plan_doc["proposed"], plan_doc["proposed_kinds"] = list(ids), dict(kinds)
        plan_doc["goal_version"] = version
        if view.scope is not None:
            plan_doc["scope_signature"] = view.signature
            plan_doc["practice_unavailable_node_ids"] = sorted(view.practice_unavailable)
            plan_doc["goal_progress"] = goal_progress(doc, view.planning_states, view.scope,
                                                       continue_available=bool(ids))
        doc["plan"] = plan_doc
        if not ids:
            plan_doc["approved"], plan_doc["cursor"] = [], 0
            if view.scope is not None:
                plan_doc["done"] = True
            doc["phase"] = "teach"

    saved = _update_if_changed(session_id, state, store, require_open=bool(state.get("goal")))
    if not ids:
        return {"concepts": [], "order": list(PLAN_ORDER), "empty": True, "phase": "teach", **_learning_scope_payload(saved)}
    names = _plan_node_names(user_id, ids)
    return {
        "concepts": [
            {
                "node_id": n,
                "concept_name": names.get(n, ""),
                "kind": kinds[n],
                "p_known": view.states.get(n, BKT_L0),
                "reason": "goal" if n in targets else "prerequisite" if view.scope is not None and n in view.scope else "review" if kinds[n] == "review" else "related",
                "target_node_ids": sorted(targets),
            }
            for n in ids
        ],
        "order": list(PLAN_ORDER),
        **_learning_scope_payload(saved),
    }


def plan_approve(body: PlanApproveBody, request: Request) -> dict:
    """Behaviour 14 / A27: store the approved concepts (a non-empty, duplicate-
    free subset of the proposal, in the student's order), point PKG-07's
    activation at the first one (`plan.cursor` 0, `concept`, counters 0), and
    move to `teach`. Activates nothing. PKG-09 post-hoc (spec §13 A19): after
    the plan is saved the learner brief is built and stored once for the
    session; a brief failure never changes the response."""
    _gate(body.user_id, request)
    _, course_id = _session_scope(body.session_id, body.user_id)
    snapshot = _load_loop_state(body.session_id)
    view = _current_plan(snapshot, body.user_id, course_id) if snapshot.get("goal") else None
    chosen = list(body.concept_ids)
    out: dict = {}
    # spec §13 A138: the first concept's segment starts here — its prequestion
    # is posed (or skipped) in the approval's own write; flag read once
    pq_on = _prequestion_on(body.user_id)

    def approve(doc: dict) -> None:
        _require_phase(doc, "plan")
        _refuse_while_closing(doc, _now_s())
        plan_doc = doc.get("plan") if isinstance(doc.get("plan"), dict) else {}
        version = goal_version(doc)
        if version and (body.goal_version != version or plan_doc.get("goal_version") != version):
            raise HTTPException(status_code=409, detail="Goal changed; review the current plan")
        if view is not None:
            if plan_doc.get("scope_signature") != view.signature:
                raise HTTPException(status_code=409, detail="Goal prerequisites changed; review the current plan")
            allowed = view.scope & view.ready - set(attempted_nodes(doc))
            if not set(chosen) <= allowed:
                raise HTTPException(status_code=409, detail="Goal prerequisites changed; review the current plan")
            if _goal_practice_unavailable(body.user_id, course_id, doc, chosen):
                raise HTTPException(status_code=409, detail="Fresh practice is unavailable; review the current plan")
        proposed = plan_doc.get("proposed") or []
        if len(set(chosen)) != len(chosen) or not set(chosen) <= set(proposed):
            raise HTTPException(
                status_code=422, detail="concept_ids must be distinct ids from the proposed plan"
            )
        kinds = plan_doc.get("proposed_kinds") or {}
        lead = 0
        while lead < len(chosen) and kinds.get(chosen[lead]) == "review":
            lead += 1
        out["n_reviews_first"] = lead
        plan_doc["approved"], plan_doc["cursor"] = list(chosen), 0
        plan_doc.pop("done", None)
        plan_doc.pop("goal_progress", None)
        doc["plan"] = plan_doc
        doc["concept"] = chosen[0]
        doc["teach_turns"] = 0
        doc["concept_checks"] = 0
        doc["phase"] = "teach"
        out["pose"] = _pose_prequestion(body.user_id, course_id, doc, now=_now_s()) if pq_on else _NO_POSE

    _update_loop_state(body.session_id, approve, require_open=bool(snapshot.get("goal")))
    prequestion = _posed_prequestion(body.user_id, body.session_id, _request_id(request), out["pose"])
    # PKG-09 post-hoc (spec §13 A19): the learner brief is built once per session, here.
    try:
        store_brief(body.session_id, body.user_id, course_id or None, chosen)
    except Exception as exc:
        logger.warning(
            "learner brief not stored at plan approval (%s); the first loop turn builds it",
            type(exc).__name__,
        )
    events_service.log_event(
        "learn.plan_approved",
        category="usage",
        user_id=body.user_id,
        request_id=_request_id(request),
        payload={"concept_ids": chosen, "n_reviews_first": out["n_reviews_first"]},
    )
    # spec §13 A138: present only when a prequestion was posed (never null)
    return {"phase": "teach", "concept_ids": chosen, **({"prequestion": prequestion} if prequestion else {})}
