"""POST /probe/answer (PKG-08): `_probe_submission`, the probe's evidence
writer, and its checkpoint.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from datetime import datetime, timezone
import config
from services.loop.errors import HTTPException
from services import abuse_limits
from services.request_limits import aenforce_abuse_limit
from starlette.requests import Request
from agents.tools.check import CheckAnswer, GradeOutcome, grade_answer
from learning import grade_checkpoint, policy
from learning.claim_deadline import within_grade_deadline
from learning import probe as probe_policy
from learning.evidence import PlanningPersistenceUnavailable, stated_confidence
from learning.goals import goal_version
from learning.misconceptions import carry, recheck_after_release
from learning.loop_state_store import seen_hashes
from learning.params import CHECK_REFUSALS_AS_IDK
from models import ProbeAnswerBody
from services.tutor import _consume_pending_off_loop
from services.tutor import _agent_turn_or_http_error
from services import ai_budget, crisis_support
from services.check_item_service import get_check_item

from services.loop.constants import _ALREADY_GRADED
from services.loop.state import (
    _agate,
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
from services.loop.probe import (
    PLAN_PHASE,
    PROBE_PHASE,
    STOP_COVERAGE_LIMIT,
    STOP_OBSERVED_BOUNDARIES,
)
from services.loop.checkpoint import (
    PROBE_KIND,
    RECOVERY_UNAVAILABLE,
    grading_deps,
    grading_failure_http,
    submitted_answer,
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


#: A refusal reason that is never escalated to idk (A97).
_DISOWNED = "disowned_answer"

#: The probe's not-graded answers: a withdrawn or unavailable item, and a refusal.
_UNAVAILABLE = {"graded": False, "unavailable": True}
_REFUSED = {"graded": False, "refused": True}

_CORRECTIVE_UNAVAILABLE = "Corrective feedback unavailable; retry the same answer"


def _posed(state: dict, qh: str) -> dict:
    """The probe's posed item, when it is `qh` (else 409)."""
    posed = _probe_doc(state).get("current")
    if not isinstance(posed, dict) or posed.get("question_hash") != qh:
        raise HTTPException(status_code=409, detail=_PROBE_NOT_POSED)
    return posed


def _take_claim(qh: str, claim: str, now: float):
    """The compare-and-set that takes the grading claim on the posed item (409
    when it is not posed, or is already claimed)."""

    def take_posed(doc: dict) -> None:
        _require_phase(doc, PROBE_PHASE)
        _refuse_while_closing(doc, now)  # PKG-09: grading and closing exclude each other
        cur = _probe_doc(doc).get("current")
        if not isinstance(cur, dict) or cur.get("question_hash") != qh:
            raise HTTPException(status_code=409, detail=_PROBE_NOT_POSED)
        if cur.get("grading_claim"):
            raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
        cur["grading_claim"], cur["grading_claim_at"] = claim, now

    return take_posed


def _count_refusal(qh: str, disowned: bool):
    """A33: count a refusal of `qh` in this probe; below CHECK_REFUSALS_AS_IDK
    (or a disowned answer, A97) the claim is released — asked again."""

    def count_refusal(pr: dict, cur: dict) -> None:
        if not disowned:
            pr["refusals"][qh] = int(pr["refusals"].get(qh) or 0) + 1
        if disowned or pr["refusals"][qh] < CHECK_REFUSALS_AS_IDK:
            _release(pr, cur)  # nothing was graded: asked again

    return count_refusal


def _observation(posed: dict, outcome, *, qh, node_id, idk, floor, recheck, synthetic_idk, previously_seen) -> dict:
    """The probe history's observation of this grade."""
    evidence = outcome.evidence or {}
    return {
        "node_id": node_id, "question_hash": qh, "difficulty": int(posed["difficulty"]),
        "channel": posed["channel"], "correct": bool(outcome.correct),
        "idk": bool(evidence.get("idk", idk)),
        "independent": floor == 0 and not recheck and not synthetic_idk and not previously_seen,
        "max_rung": int(floor), "same_session_recheck": bool(recheck),
        "synthetic_idk": synthetic_idk,
    }


async def _release_unsaved_claim(session_id: str, qh: str, claim: str) -> None:
    """Give up a claim no checkpoint was saved under (never raises)."""
    try:
        await asyncio.to_thread(
            _update_loop_state, session_id, _under_probe_claim(qh, claim, _release)
        )
    except Exception:
        logger.warning("probe grading claim could not be released")


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
    # #117: every sync PostgREST read and write below hops off the event loop
    state = await asyncio.to_thread(_load_loop_state, body.session_id)
    _require_phase(state, PROBE_PHASE)
    qh = body.question_hash
    posed = _posed(state, qh)
    if grade_checkpoint.KEY in posed:
        checkpoint = _open_grade_checkpoint(posed, body, course_id, kind=PROBE_KIND)
        return await asyncio.to_thread(_finish_probe_checkpoint, checkpoint, request, loop_on=loop_on)
    if posed.get("grading_claim"):
        raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
    skills = list(_probe_doc(state).get("skills") or [])
    node_id = posed["node_id"]
    probe_items = await asyncio.to_thread(_probe_items, body.user_id, course_id, skills)  # #117
    item = next((it for it in probe_items if it.id == posed.get("check_item_id")), None)
    now = _now_s()
    claim = str(uuid.uuid4())
    await asyncio.to_thread(_update_loop_state, body.session_id, _take_claim(qh, claim, now))
    if item is None:  # A23 withdrawal: nothing is graded
        await asyncio.to_thread(
            _update_loop_state, body.session_id, _under_probe_claim(qh, claim, _not_asked)
        )
        return dict(_UNAVAILABLE)

    text = body.answer or body.reason
    idk = body.idk or _is_idk_phrase(text)
    # spec §13 A120: the probe feeds the §3.3 slip/misconception rule too —
    # the hook appends this answer to the session attempt log on a copy;
    # the change rides the checkpoint into the claimed save below
    deps = grading_deps(body, course_id, request, kind=PROBE_KIND, loop_on=loop_on, state=state)
    # PKG-10 (spec §13 A76, fix round 3): a probe item is the next graded item
    # on its concept after a release too — the same rule as the check route
    recheck = await asyncio.to_thread(
        recheck_after_release,
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
    floor = await asyncio.to_thread(_reveal_floor, body.user_id, item.item, None)
    answer = submitted_answer(body, idk=idk)
    try:
        async with within_grade_deadline(_now_s() - now):
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
                # A97: a disowned answer is never escalated to idk
                state = await asyncio.to_thread(
                    _update_loop_state, body.session_id,
                    _under_probe_claim(qh, claim, _count_refusal(qh, outcome.refused == _DISOWNED)),
                )
                if (_probe_doc(state).get("current") or {}).get("grading_claim") != claim:
                    return dict(_REFUSED)
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
                await asyncio.to_thread(
                    _update_loop_state, body.session_id, _under_probe_claim(qh, claim, _not_asked)
                )
                return dict(_UNAVAILABLE)

            floor = await asyncio.to_thread(
                _refloor, deps.pending_evidence, body.user_id, item.item, None, floor
            )
            previously_seen = bool(posed.get("previously_seen", False)) or qh in (
                await asyncio.to_thread(seen_hashes, body.user_id)
            )
            _tag_planning_evidence(deps.pending_evidence, item.item, synthetic_idk=synthetic_idk,
                                   previously_seen=previously_seen, operation_id=claim, observed_at=now)
            observation = _observation(
                posed, outcome, qh=qh, node_id=node_id, idk=idk, floor=floor, recheck=recheck,
                synthetic_idk=synthetic_idk, previously_seen=previously_seen,
            )
            checkpoint = grade_checkpoint.GradeCheckpoint(
                kind=PROBE_KIND, operation_id=claim, user_id=body.user_id,
                session_id=body.session_id, course_id=course_id or None, question_hash=qh,
                goal_version=goal_version(state), evidence=copy.deepcopy(deps.pending_evidence),
                continuation={"observation": observation, "correct": bool(outcome.correct),
                              "check_item_id": item.id,
                              # A120: the attempt log change (and a row to record), re-applied below
                              "diagnosis": getattr(outcome, "diagnosis", None),
                              "answer": answer.model_dump(mode="json")},
            )
        checkpointed = True
        await asyncio.to_thread(_save_grade_checkpoint, checkpoint)
        return await asyncio.to_thread(
            _finish_probe_checkpoint, checkpoint, request, loop_on=loop_on, deps=deps
        )
    except BaseException as exc:
        if not checkpointed:
            await _release_unsaved_claim(body.session_id, qh, claim)
        mapped = grading_failure_http(exc)
        if mapped is not None:
            raise mapped from None
        raise


def _unwritten(receipt) -> dict | None:
    """The answer for a probe grade the flush did not write (A123: its item was
    retired while it was graded; or superseded / abandoned), else None."""
    if receipt is _ITEM_RETIRED:  # A123: the item was retired while it was graded
        return {**_UNAVAILABLE, "superseded": True, "withdrawn": True}
    if receipt is False:
        return {**_UNAVAILABLE, "superseded": True}
    return None


def _saved_posterior(checkpoint, receipt) -> tuple[str, float]:
    """The graded node and its posterior in the committed receipt (503 when
    the receipt holds no valid one)."""
    try:
        node_id = checkpoint.continuation["observation"]["node_id"]
        p_after = (receipt or {}).get("posteriors", {}).get(node_id)
        if type(p_after) not in (int, float) or not 0 <= p_after <= 1:
            raise PlanningPersistenceUnavailable("Saved grade posterior unavailable")
    except PlanningPersistenceUnavailable:
        raise HTTPException(status_code=503, detail=RECOVERY_UNAVAILABLE) from None
    return node_id, p_after


def _corrective_reference(checkpoint):
    """For a wrong answer, the item and its reference answer, read while the
    checkpoint is still recoverable (503 when the read fails)."""
    if checkpoint.continuation["correct"]:
        return None, None
    # Read corrective source text while the checkpoint is still recoverable.
    try:
        item = get_check_item(checkpoint.continuation["check_item_id"])
        return item, (item.reference_answer if item is not None else None)
    except Exception:
        raise HTTPException(status_code=503, detail=_CORRECTIVE_UNAVAILABLE) from None


def _stop_reason(pr: dict) -> str:
    """Why a finished probe stops: the diagnostic's reason, widened to
    `coverage_limit` when the scope holds skills the probe did not cover."""
    reason = probe_policy.diagnostic_summary(pr["history"], skills=pr.get("skills") or [])["stop_reason"]
    if reason == STOP_OBSERVED_BOUNDARIES and set(pr.get("scope", [])) - set(pr.get("skills", [])):
        reason = STOP_COVERAGE_LIMIT
    return reason


def _record_observation(checkpoint, observation: dict, diagnosis, out: dict):
    """The compare-and-set write that records the observation under OUR claim
    (it may run more than once; what it did lands in `out`)."""

    def record(pr: dict, _cur: dict) -> None:
        pr["history"].append(observation)
        pr["current"] = None
        out["recorded"] = True
        out["done"] = probe_policy.probe_done(pr["history"], skills=pr.get("skills") or [])
        out["novice_floor"] = probe_policy.novice_floor(pr["history"])
        if out["done"]:
            pr["stop_reason"] = _stop_reason(pr)

    def record_posed(doc: dict) -> None:
        out.clear()
        _require_phase(doc, PROBE_PHASE)
        _refuse_while_closing(doc, _now_s())
        _check_goal_version(doc, checkpoint.goal_version)
        _under_probe_claim(checkpoint.question_hash, checkpoint.operation_id, record)(doc)
        if out.get("recorded"):
            # spec §13 A120: this answer joins the session attempt log the §3.3
            # rule reads, on the FRESH document, in the write that records it
            carry(doc, diagnosis)
        if out.get("done"):
            doc["phase"] = PLAN_PHASE

    return record_posed


def _write_probe_misconception(checkpoint, diagnosis, item) -> None:
    """A120 (A75 (a)'s order): the row the rule marked, written only after the
    one flush and the save that recorded the answer under OUR claim."""
    if not ((diagnosis or {}).get("record") and item is not None):
        return
    try:
        _write_misconception(
            checkpoint.user_id, GradeOutcome(diagnosis=diagnosis), _item_like(item),
            CheckAnswer.model_validate(checkpoint.continuation["answer"]),
        )
    except Exception:
        logger.warning("probe misconception not recorded after saved grade")


def _probe_dwell_ms(checkpoint) -> int:
    """W2.5: high-confidence wrong → Next holds while the reference is on screen."""
    answer = checkpoint.continuation.get("answer") or {}
    obs = checkpoint.continuation.get("observation") or {}
    idk = bool(obs.get("idk"))
    return policy.hypercorrection_feedback_dwell_ms(
        correct=bool(checkpoint.continuation["correct"]),
        student_confidence=stated_confidence(
            answer.get("confidence") if isinstance(answer, dict) else None, idk=idk
        ),
        idk=idk,
        time_scale=config.LEARNING_GATE_TIME_SCALE,
    )


def _finish_probe_checkpoint(checkpoint, request, *, loop_on, deps=None):
    receipt = _flush_grade_checkpoint(checkpoint, request, loop_on=loop_on, deps=deps)
    unwritten = _unwritten(receipt)
    if unwritten is not None:
        return unwritten
    node_id, p_after = _saved_posterior(checkpoint, receipt)
    committed = _committed_grade_observation(checkpoint, receipt, node_id)
    observation = {**checkpoint.continuation["observation"], **committed, "p_after": p_after,
                   "grade_operation_id": checkpoint.operation_id}
    diagnosis = checkpoint.continuation.get("diagnosis")  # A120; None before A120
    item, reference = _corrective_reference(checkpoint)
    out: dict = {}
    saved = _update_loop_state(
        checkpoint.session_id, _record_observation(checkpoint, observation, diagnosis, out),
        require_open=True, require_existing=True,
    )
    if not out.get("recorded"):
        raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
    _write_probe_misconception(checkpoint, diagnosis, item)
    # spec §13 A127 (same order): a correct, unassisted probe answer on an
    # isomorph closes what its item tests; the response below is unchanged
    _resolve_misconceptions(checkpoint, diagnosis, committed, surface="probe", request=request)
    if out.get("done"):
        _emit_probe_done(saved, checkpoint.user_id, _request_id(request))
    response = {
        "graded": True, "correct": checkpoint.continuation["correct"], "p_known": p_after,
        "probe_done": bool(out.get("done")), "novice_floor": bool(out.get("novice_floor")),
        **_learning_scope_payload(saved, checkpoint.session_id),
    }
    if reference is not None:
        response["reference_answer"] = reference
    dwell = _probe_dwell_ms(checkpoint)
    if dwell > 0:
        response["feedback_dwell_ms"] = dwell
    return response


async def probe_answer(body: ProbeAnswerBody, request: Request) -> dict:
    """Behaviour 11: grade_answer only (A16) — no tutor turn, no tutor budget
    (A20); the rate limit is the one model-cost guard here (spec §9), checked
    inline AFTER the gate (PKG-12's pattern) so a gate-off student gets the
    404, never a 429."""
    loop_on = await _agate(body.user_id, request)
    # crisis support: before the rate limit; the probe item stays posed, ungraded
    if crisis := await crisis_support.screen_async(
        request, body.user_id, "loop_probe_answer", body.answer, body.reason
    ):
        return crisis_support.json_body(crisis, graded=False)
    # audit Z02: one tutor turn, as every graded loop answer is charged
    await aenforce_abuse_limit(abuse_limits.TUTOR_TURN, body.user_id)
    await asyncio.to_thread(ai_budget.enforce_rate_limit_for, body.user_id)  # #117
    await _consume_pending_off_loop(body.session_id, body.user_id)
    return await _agent_turn_or_http_error(
        _probe_submission(body, request, loop_on=loop_on), what="probe grader"
    )
