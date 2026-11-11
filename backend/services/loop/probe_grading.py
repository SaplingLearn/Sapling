"""POST /probe/answer (PKG-08): `_probe_submission`, the probe's evidence
writer, and its checkpoint.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from datetime import datetime, timezone
from services.loop.errors import HTTPException
from starlette.requests import Request
from agents.deps import SaplingDeps
from agents.tools.check import CheckAnswer, GradeOutcome, grade_answer
from learning import grade_checkpoint
from learning import probe as probe_policy
from learning.evidence import PlanningPersistenceUnavailable
from learning.goals import goal_version
from learning.misconceptions import carry, recheck_after_release
from learning.loop_state_store import seen_hashes
from learning.params import CHECK_REFUSALS_AS_IDK
from models import ProbeAnswerBody
from services.tutor import _consume_pending_off_loop
from services.tutor import _agent_turn_or_http_error
from services import ai_budget, crisis_support
from services.auth_guard import guard_off_loop
from services.check_item_service import get_check_item

from services.loop.constants import _ALREADY_GRADED
from services.loop.state import (
    _gate,
    _item_like,
    _load_loop_state,
    _now_s,
    _refuse_while_closing,
    _request_id,
    _session_scope,
    _update_loop_state,
)
from services.loop.reveals import _refloor, _reveal_floor, _tag_planning_evidence
from services.loop.planning import (
    _check_goal_version,
    _emit_probe_done,
    _learning_scope_payload,
    _probe_doc,
    _probe_items,
    _PROBE_NOT_POSED,
    _require_phase,
)
from services.loop.claims import (
    _is_idk_phrase,
    _not_asked,
    _resolve_misconceptions,
    _under_probe_claim,
    _write_misconception,
)
from services.loop.checkpoint import (
    _committed_grade_observation,
    _flush_grade_checkpoint,
    _ITEM_RETIRED,
    _open_grade_checkpoint,
    _save_grade_checkpoint,
)

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


def _release(_pr: dict, cur: dict) -> None:
    cur.pop("grading_claim", None)
    cur.pop("grading_claim_at", None)
    cur.pop(grade_checkpoint.KEY, None)


async def _probe_submission(body: ProbeAnswerBody, request: Request, *, loop_on: bool) -> dict:
    """Grade ONE explicit probe answer (A16) and persist its evidence with ONE
    flush_pending — invariant 26's probe writer. Grading is a CLAIM on the posed
    item (PKG-07's C2 discipline, A52): taken by compare-and-set before
    grade_answer, so a double submit, a resubmission or a concurrent refusal can
    never grade or write the item twice (409). A33: a refusal (read BEFORE
    `unavailable`, which it also sets) keeps the item posed, counts on
    `probe.refusals[qh]` and releases the claim; the CHECK_REFUSALS_AS_IDK-th
    refusal of the item in this probe is graded as idk. `unavailable` (an
    outage, a missing second opinion, the grader cap) and a withdrawn item count
    as not asked: no evidence for either outcome. After the flush the claim is
    released only by the write that records the observation, so a lost record
    never admits a second write (the item is moved past once the claim is
    stale)."""
    _, course_id = await asyncio.to_thread(_session_scope, body.session_id, body.user_id)  # #117
    state = _load_loop_state(body.session_id)
    _require_phase(state, "probe")
    qh = body.question_hash
    posed = _probe_doc(state).get("current")
    if not isinstance(posed, dict) or posed.get("question_hash") != qh:
        raise HTTPException(status_code=409, detail=_PROBE_NOT_POSED)
    if grade_checkpoint.KEY in posed:
        checkpoint = _open_grade_checkpoint(posed, body, course_id, kind="probe")
        return _finish_probe_checkpoint(checkpoint, request, loop_on=loop_on)
    if posed.get("grading_claim"):
        raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
    skills = list(_probe_doc(state).get("skills") or [])
    node_id = posed["node_id"]
    probe_items = await asyncio.to_thread(_probe_items, body.user_id, course_id, skills)  # #117
    item = next(
        (
            it
            for it in probe_items
            if it.id == posed.get("check_item_id")
        ),
        None,
    )
    now = _now_s()
    claim = str(uuid.uuid4())

    def take(pr: dict, cur: dict) -> None:
        if cur.get("grading_claim"):
            raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
        cur["grading_claim"], cur["grading_claim_at"] = claim, now

    def take_posed(doc: dict) -> None:
        _require_phase(doc, "probe")
        _refuse_while_closing(doc, now)  # PKG-09: grading and closing exclude each other
        cur = _probe_doc(doc).get("current")
        if not isinstance(cur, dict) or cur.get("question_hash") != qh:
            raise HTTPException(status_code=409, detail=_PROBE_NOT_POSED)
        take(doc["probe"], cur)

    _update_loop_state(body.session_id, take_posed)
    if item is None:  # A23 withdrawal: nothing is graded
        _update_loop_state(body.session_id, _under_probe_claim(qh, claim, _not_asked))
        return {"graded": False, "unavailable": True}

    text = body.answer or body.reason
    idk = body.idk or _is_idk_phrase(text)
    deps = SaplingDeps(
        user_id=body.user_id,
        course_id=course_id or None,
        supabase=None,
        request_id=_request_id(request),
        session_id=body.session_id,
        feature="loop_probe",
        learning_loop=loop_on,
        # spec §13 A120: the probe feeds the §3.3 slip/misconception rule too —
        # the hook appends this answer to the session attempt log on a copy;
        # the change rides the checkpoint into the claimed save below
        loop_state=copy.deepcopy(state),
    )
    # PKG-10 (spec §13 A76, fix round 3): a probe item is the next graded item
    # on its concept after a release too — the same rule as the check route
    recheck = recheck_after_release(
        body.user_id,
        node_id,
        state,
        now=datetime.fromtimestamp(now, tz=timezone.utc),
        item=item.item,
    )
    checkpointed = False
    synthetic_idk = False
    # A93: a probe item graded with help anywhere (another session's hints, a
    # reveal) carries no unassisted credit — the same help floor as every grade
    floor = _reveal_floor(body.user_id, item.item, None)
    answer = CheckAnswer(
        question_hash=qh,
        answer_text=body.answer,
        selected_option=body.option,
        reason=body.reason,
        idk=idk,
        # spec §13 A127: the stated confidence; an idk (a box or a phrase) states none
        confidence=None if idk else body.confidence,
    )
    try:
        outcome = await grade_answer(
            item.item,
            answer,
            deps=deps,
            node_id=node_id,
            max_rung=floor,
            same_session_recheck=recheck,
            confront=False,  # A120: the probe is a diagnostic — it never sets a marker
        )
        if outcome.refused:  # A33, read BEFORE `unavailable`: never a skip

            disowned = outcome.refused == "disowned_answer"  # A97: never escalated to idk

            def count_refusal(pr: dict, cur: dict) -> None:
                if not disowned:
                    pr["refusals"][qh] = int(pr["refusals"].get(qh) or 0) + 1
                if disowned or pr["refusals"][qh] < CHECK_REFUSALS_AS_IDK:
                    _release(pr, cur)  # nothing was graded: asked again

            state = _update_loop_state(
                body.session_id, _under_probe_claim(qh, claim, count_refusal)
            )
            if (_probe_doc(state).get("current") or {}).get("grading_claim") != claim:
                return {"graded": False, "refused": True}
            synthetic_idk = True
            idk = True  # the CHECK_REFUSALS_AS_IDK-th refusal is an idk observation (A1)
            answer = CheckAnswer(question_hash=qh, idk=True)
            outcome = await grade_answer(
                item.item,
                answer,
                deps=deps,
                node_id=node_id,
                max_rung=floor,
                same_session_recheck=recheck,
                confront=False,
            )
        if outcome.unavailable:  # invariant 28: nothing for either outcome
            _update_loop_state(body.session_id, _under_probe_claim(qh, claim, _not_asked))
            return {"graded": False, "unavailable": True}

        floor = _refloor(deps.pending_evidence, body.user_id, item.item, None, floor)
        previously_seen = bool(posed.get("previously_seen", False)) or qh in seen_hashes(body.user_id)
        _tag_planning_evidence(deps.pending_evidence, item.item, synthetic_idk=synthetic_idk,
                               previously_seen=previously_seen, operation_id=claim, observed_at=now)
        correct = bool(outcome.correct)
        evidence = outcome.evidence or {}
        observation = {
            "node_id": node_id, "question_hash": qh, "difficulty": int(posed["difficulty"]),
            "channel": posed["channel"], "correct": correct,
            "idk": bool(evidence.get("idk", idk)),
            "independent": floor == 0 and not recheck and not synthetic_idk and not previously_seen,
            "max_rung": int(floor), "same_session_recheck": bool(recheck),
            "synthetic_idk": synthetic_idk,
        }
        checkpoint = grade_checkpoint.GradeCheckpoint(
            kind="probe", operation_id=claim, user_id=body.user_id,
            session_id=body.session_id, course_id=course_id or None, question_hash=qh,
            goal_version=goal_version(state), evidence=copy.deepcopy(deps.pending_evidence),
            continuation={"observation": observation, "correct": correct,
                          "check_item_id": item.id,
                          # A120: the attempt log change (and a row to record), re-applied below
                          "diagnosis": getattr(outcome, "diagnosis", None),
                          "answer": answer.model_dump(mode="json")},
        )
        checkpointed = True
        _save_grade_checkpoint(checkpoint)
        return _finish_probe_checkpoint(checkpoint, request, loop_on=loop_on, deps=deps)
    except BaseException as exc:
        if not checkpointed:
            try:
                _update_loop_state(body.session_id, _under_probe_claim(qh, claim, _release))
            except Exception:
                logger.warning("probe grading claim could not be released")
        if isinstance(exc, PlanningPersistenceUnavailable):
            raise HTTPException(status_code=503, detail="Learning evidence unavailable; retry the same answer") from None
        raise


def _finish_probe_checkpoint(checkpoint, request, *, loop_on, deps=None):
    receipt = _flush_grade_checkpoint(checkpoint, request, loop_on=loop_on, deps=deps)
    if receipt is _ITEM_RETIRED:  # A123: the item was retired while it was graded
        return {"graded": False, "unavailable": True, "superseded": True, "withdrawn": True}
    if receipt is False:
        return {"graded": False, "unavailable": True, "superseded": True}
    try:
        node_id = checkpoint.continuation["observation"]["node_id"]
        p_after = (receipt or {}).get("posteriors", {}).get(node_id)
        if type(p_after) not in (int, float) or not 0 <= p_after <= 1:
            raise PlanningPersistenceUnavailable("Saved grade posterior unavailable")
    except PlanningPersistenceUnavailable:
        raise HTTPException(status_code=503, detail="Saved grade recovery unavailable; retry the same answer") from None
    committed = _committed_grade_observation(checkpoint, receipt, node_id)
    observation = {**checkpoint.continuation["observation"], **committed, "p_after": p_after,
                   "grade_operation_id": checkpoint.operation_id}
    diagnosis = checkpoint.continuation.get("diagnosis")  # A120; None before A120
    reference = item = None
    if not checkpoint.continuation["correct"]:
        # Read corrective source text while the checkpoint is still recoverable.
        try:
            item = get_check_item(checkpoint.continuation["check_item_id"])
            reference = item.reference_answer if item is not None else None
        except Exception:
            raise HTTPException(status_code=503, detail="Corrective feedback unavailable; retry the same answer") from None
    out: dict = {}

    def record(pr: dict, _cur: dict) -> None:
        pr["history"].append(observation)
        pr["current"] = None
        out["recorded"] = True
        out["done"] = probe_policy.probe_done(pr["history"], skills=pr.get("skills") or [])
        out["novice_floor"] = probe_policy.novice_floor(pr["history"])
        if out["done"]:
            reason = probe_policy.diagnostic_summary(pr["history"], skills=pr.get("skills") or [])["stop_reason"]
            if reason == "observed_boundaries" and set(pr.get("scope", [])) - set(pr.get("skills", [])):
                reason = "coverage_limit"
            pr["stop_reason"] = reason

    def record_posed(doc: dict) -> None:
        out.clear()
        _require_phase(doc, "probe")
        _refuse_while_closing(doc, _now_s())
        _check_goal_version(doc, checkpoint.goal_version)
        _under_probe_claim(checkpoint.question_hash, checkpoint.operation_id, record)(doc)
        if out.get("recorded"):
            # spec §13 A120: this answer joins the session attempt log the §3.3
            # rule reads, on the FRESH document, in the write that records it
            carry(doc, diagnosis)
        if out.get("done"):
            doc["phase"] = "plan"

    saved = _update_loop_state(checkpoint.session_id, record_posed, require_open=True, require_existing=True)
    if not out.get("recorded"):
        raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
    if (diagnosis or {}).get("record") and item is not None:
        # A120 (A75 (a)'s order): the row the rule marked, written only after the
        # one flush and the save that recorded the answer under OUR claim
        try:
            _write_misconception(
                checkpoint.user_id, GradeOutcome(diagnosis=diagnosis), _item_like(item),
                CheckAnswer.model_validate(checkpoint.continuation["answer"]),
            )
        except Exception:
            logger.warning("probe misconception not recorded after saved grade")
    # spec §13 A127 (same order): a correct, unassisted probe answer on an
    # isomorph closes what its item tests; the response below is unchanged
    _resolve_misconceptions(checkpoint, diagnosis, committed, surface="probe", request=request)
    if out.get("done"):
        _emit_probe_done(saved, checkpoint.user_id, _request_id(request))
    response = {
        "graded": True, "correct": checkpoint.continuation["correct"], "p_known": p_after,
        "probe_done": bool(out.get("done")), "novice_floor": bool(out.get("novice_floor")),
        **_learning_scope_payload(saved),
    }
    if reference is not None:
        response["reference_answer"] = reference
    return response


async def probe_answer(body: ProbeAnswerBody, request: Request) -> dict:
    """Behaviour 11: grade_answer only (A16) — no tutor turn, no tutor budget
    (A20); the rate limit is the one model-cost guard here (spec §9), checked
    inline AFTER the gate (PKG-12's pattern) so a gate-off student gets the
    404, never a 429."""
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    # crisis support: before the rate limit; the probe item stays posed, ungraded
    if crisis := await crisis_support.screen_async(
        body.user_id, "loop_probe_answer", body.answer, body.reason
    ):
        return crisis_support.json_body(crisis, graded=False)
    ai_budget.enforce_rate_limit_for(body.user_id)
    await _consume_pending_off_loop(body.session_id, body.user_id)
    return await _agent_turn_or_http_error(
        _probe_submission(body, request, loop_on=loop_on), what="probe grader"
    )
