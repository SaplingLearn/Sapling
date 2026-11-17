"""The grade checkpoint (crash recovery of a graded answer): save, flush and
finish, and the band verdict it emits (A122).
"""
from __future__ import annotations

import copy
import logging
from typing import NamedTuple
from services.loop.errors import HTTPException
from agents.deps import SaplingDeps
from agents.tools.check import CheckAnswer, GradeOutcome
from learning import policy, zpd_events
from learning import grade_checkpoint
from learning.evidence import PlanningObservation, PlanningPersistenceUnavailable, flush_pending
from learning.evidence_transaction import (
    EvidenceItemRetired,
    EvidenceObservationSuperseded,
    read_receipt as read_evidence_receipt,
)
from learning.learner_state import LearnerState, read_states
from learning.misconceptions import carry
from learning.loop_state_store import opportunity_window
from learning.help_ledger import mark_graded
from learning.params import ZPD_RATING_EVERY_N_CHECKS
from learning.policy import StepState
from services.check_item_service import get_check_item

from services.loop.constants import _ALREADY_GRADED
from services.loop.state import (
    _item_like,
    _now_s,
    _refuse_while_closing,
    _request_id,
    _require_teaching,
    _steps,
    _update_loop_state,
)
from services.loop.learner import _band_of, _learner_view, _prerequisites
from services.loop.reveals import _ledger
from services.loop.planning import _check_goal_version, _probe_doc, _require_phase
from services.loop.practice import _BAND_CONTROL
from services.loop.claims import (
    _not_asked,
    _record_attempt,
    _resolve_misconceptions,
    _Submission,
    _under_claim,
    _under_probe_claim,
    _write_misconception,
)

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


def _open_grade_checkpoint(entry, body, course_id, *, kind):
    try:
        return grade_checkpoint.open_checkpoint(
            entry.get(grade_checkpoint.KEY), kind=kind, operation_id=entry.get("grading_claim"),
            user_id=body.user_id, session_id=body.session_id, course_id=course_id or None,
            question_hash=body.question_hash,
        )
    except PlanningPersistenceUnavailable:
        raise HTTPException(status_code=503, detail="Saved grade recovery unavailable; retry later") from None


def _save_grade_checkpoint(checkpoint):
    encrypted = grade_checkpoint.seal(checkpoint)  # constant across CAS retries

    def save(doc):
        _refuse_while_closing(doc, _now_s())
        _check_goal_version(doc, checkpoint.goal_version)
        entry = (_steps(doc).get(checkpoint.question_hash) if checkpoint.kind == "check"
                 else _probe_doc(doc).get("current"))
        if (not isinstance(entry, dict) or entry.get("grading_claim") != checkpoint.operation_id
                or (checkpoint.kind == "probe" and entry.get("question_hash") != checkpoint.question_hash)):
            raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
        entry[grade_checkpoint.KEY] = encrypted
        entry["grading_claim_at"] = _now_s()

    _update_loop_state(checkpoint.session_id, save, require_open=True, require_existing=True)


#: spec §13 A123: _flush_grade_checkpoint's answer when the commit refused the
#: grade because staff retired its item meanwhile (EvidenceItemRetired)
_ITEM_RETIRED = object()


_RETIRED_DETAIL = "This question was withdrawn. Select another check to continue."


def _flush_grade_checkpoint(checkpoint, request, *, loop_on, deps=None):
    def guard(doc):
        _refuse_while_closing(doc, _now_s())
        _check_goal_version(doc, checkpoint.goal_version)
        if checkpoint.kind == "probe":
            _require_phase(doc, "probe")
            entry = _probe_doc(doc).get("current")
        else:
            _require_teaching(doc)
            entry = _steps(doc).get(checkpoint.question_hash)
            if doc.get("current") != checkpoint.question_hash:
                raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
        if (not isinstance(entry, dict) or entry.get("grading_claim") != checkpoint.operation_id
                or grade_checkpoint.KEY not in entry):
            raise HTTPException(status_code=409, detail=_ALREADY_GRADED)

    # The durable claim excludes goal changes and close. A conditional write
    # also checks ended_at/close_json before any replay can write evidence.
    _update_loop_state(checkpoint.session_id, guard, require_open=True, require_existing=True)
    deps = deps or SaplingDeps(
        user_id=checkpoint.user_id, course_id=checkpoint.course_id, supabase=None,
        request_id=_request_id(request), session_id=checkpoint.session_id,
        feature="loop_check" if checkpoint.kind == "check" else "loop_probe", learning_loop=loop_on,
    )
    deps.pending_evidence = copy.deepcopy(checkpoint.evidence)
    try:
        flush_pending(deps, checkpoint.course_id)
    except EvidenceObservationSuperseded as exc:
        # The original answer has no committed receipt, and a newer observation
        # is already authoritative — or (A123, EvidenceItemRetired) staff retired
        # the item while it was graded, so the grade is void by definition and
        # nothing was written. Never apply the old answer out of order or
        # invent a diagnosis; retire its pose and ask for fresh evidence.
        def supersede(doc):
            if checkpoint.kind == "check":
                def retire(entry):
                    entry["grading_superseded"] = True
                    entry["discarded_grade_operation_id"] = checkpoint.operation_id
                _under_claim(checkpoint.question_hash, checkpoint.operation_id, retire, release=True)(doc)
                if doc.get("current") == checkpoint.question_hash:
                    doc["current"] = None
            else:
                _under_probe_claim(checkpoint.question_hash, checkpoint.operation_id, _not_asked)(doc)

        _update_loop_state(checkpoint.session_id, supersede, require_open=True, require_existing=True)
        return _ITEM_RETIRED if isinstance(exc, EvidenceItemRetired) else False
    except PlanningPersistenceUnavailable:
        raise HTTPException(status_code=503, detail="Learning evidence unavailable; retry the same answer") from None
    try:
        receipt = read_evidence_receipt(checkpoint.user_id, checkpoint.operation_id)
        if receipt is None or receipt.get("course_id") != checkpoint.course_id:
            raise PlanningPersistenceUnavailable("Saved grade receipt unavailable")
    except PlanningPersistenceUnavailable:
        raise HTTPException(status_code=503, detail="Saved grade recovery unavailable; retry the same answer") from None
    _ledger(mark_graded, checkpoint.user_id, checkpoint.question_hash)
    return receipt


def _committed_grade_observation(checkpoint, receipt, node_id):
    """Use the final serialized writer's exposure provenance, never a stale guess.

    Another session may have answered this question after the grader began.
    The original grade stays frozen, but only the committed receipt can attest
    that this particular exposure was fresh and independently useful.
    """
    try:
        matches = [PlanningObservation.model_validate(row) for row in receipt["observations"]
                   if row.get("node_id") == node_id and row.get("question_hash") == checkpoint.question_hash]
        original = next(row for row in checkpoint.evidence if row["node_id"] == node_id)
        if len(matches) != 1:
            raise ValueError("Saved grade observation unavailable")
        final = matches[0].model_dump(mode="json")
        for key in ("check_item_id", "channel", "correct", "idk", "max_rung"):
            if final[key] != original[key]:
                raise ValueError("Saved grade observation disagrees")
        for key in ("difficulty", "synthetic_idk"):
            if final[key] != original["planning_provenance"][key]:
                raise ValueError("Saved grade immutable provenance disagrees")
        if original.get("same_session_recheck") and not final["same_session_recheck"]:
            raise ValueError("Saved grade recheck provenance weakened")
        if original["planning_provenance"]["previously_seen"] and not final["previously_seen"]:
            raise ValueError("Saved grade exposure provenance weakened")
        return final
    except Exception:
        raise HTTPException(status_code=503, detail="Saved grade recovery unavailable; retry the same answer") from None


class _BandOutcome(NamedTuple):
    """One graded check's band-control verdict (spec §13 A122). `stored` is
    what the graded step keeps for its feedback turn to apply (ids, the enum,
    an int) — None for HOLD, which adjusts nothing; the rest feeds the events."""

    stored: dict | None
    verdict: policy.BandVerdict
    p_known: float
    opps: int
    difficulty: int | None
    prerequisite_ids: list[str]


def _graded_difficulty(difficulty: int | None, checkpoint) -> int | None:
    """The graded item's difficulty: the grading request's (it holds the item),
    else — a saved grade recovered by a later request — the item's, read once
    by its id in the checkpoint's evidence; None when it cannot be read."""
    if type(difficulty) is int:
        return difficulty
    ids = [
        row.get("check_item_id")
        for row in checkpoint.evidence
        if row.get("question_hash") == checkpoint.question_hash and row.get("check_item_id")
    ]
    try:
        item = get_check_item(ids[0]) if ids else None
    except Exception:
        logger.warning("graded item unreadable; band control takes no difficulty step")
        return None
    return item.difficulty if item is not None else None


def _band_verdict(user_id: str, node_id: str, difficulty: int | None) -> _BandOutcome | None:
    """Spec §3.3 band control after ONE graded check (§13 A122), read after its
    evidence is flushed so the window holds it: the concept's opportunity window
    (loop_state_store.opportunity_window: unassisted first-attempt outcomes,
    newest last, across sessions), its decayed learner_state (p_known, opps, the
    A3 max streak) and — for a verdict that checks prerequisites
    (EASIER_CHECK_PREREQS, WHEELSPIN) — its prerequisite parents, from which
    policy.repair_target picks the weakest unproficient one. Typed state in
    (policy.band_verdict, invariant 4); never the student's text. None when a
    read failed: the grade stands, no verdict is applied — never an invented
    one — and the next graded check decides again from the durable journal."""
    window = opportunity_window(user_id, node_id)
    if window is None:
        return None
    try:
        state = read_states(user_id, [node_id]).get(node_id) or LearnerState(
            user_id=user_id, node_id=node_id
        )
        verdict = policy.band_verdict(
            window,
            p_known=state.p_known,
            opps=state.opps,
            max_streak_unassisted=state.max_streak_unassisted,
        )
        band, _ = _band_of(state)
        adjusts = verdict.action is not policy.BandAction.HOLD
        # prerequisites: the repair target (EASIER_CHECK_PREREQS, WHEELSPIN), and
        # the novice rows of the effective ceiling (prerequisite known or not)
        checks_prereqs = verdict.action in (
            policy.BandAction.EASIER_CHECK_PREREQS,
            policy.BandAction.WHEELSPIN,
        ) or (adjusts and band == "novice")
        prerequisites = _prerequisites(user_id, node_id) if checks_prereqs else []
    except Exception as exc:
        logger.warning("band control skipped for this grade: %s", type(exc).__name__)
        return None
    target = policy.repair_target(prerequisites)
    delta = policy.ceiling_delta(verdict.action)
    stored = None
    if adjusts:
        proficient = policy.prerequisite_status(prerequisites) is policy.PrerequisiteStatus.PROFICIENT
        view = _learner_view(state, band=band, prereq_proficient=proficient)
        stored = {
            "action": verdict.action.value,
            "difficulty": (
                policy.next_difficulty(verdict.action, difficulty)
                if difficulty is not None
                else None
            ),
            "repair": target.node_id if target is not None else None,
            # §3.3's ceiling clause and the ceiling it leaves a fresh item on the
            # concept (0 failed attempts, outside exam mode): the band's row moved
            # by the delta, clamped — gates still apply turn by turn
            "ceiling_delta": delta,
            "ceiling": int(
                policy.ceiling(view, StepState(question_hash=""), band_delta=delta)
            ),
        }
    return _BandOutcome(
        stored=stored,
        verdict=verdict,
        p_known=state.p_known,
        opps=state.opps,
        difficulty=difficulty,
        prerequisite_ids=sorted(p.node_id for p in prerequisites),
    )


def _emit_band_verdict(user_id: str, request_id: str, node_id: str, band: _BandOutcome) -> None:
    """Spec §6 (§13 A122): zpd.band_adjust for every verdict that adjusts
    something (HOLD adjusts nothing), with direction, trigger and window_stats
    (numbers and bools only); and on WHEELSPIN zpd.wheelspin (category error) —
    the spec's "flag instructor": Sapling has no instructor role, so this error
    event IS the flag. The emitters never raise into the request."""
    verdict = band.verdict
    trigger = policy.BAND_TRIGGERS.get(verdict.action)
    if trigger is None:
        return
    stored = band.stored or {}
    zpd_events.emit_zpd_band_adjust(
        user_id=user_id,
        request_id=request_id,
        direction=verdict.action,
        trigger=trigger,
        window_stats={
            "rate": verdict.rate,
            "n": verdict.n,
            "full_windows": verdict.full_windows,
            "stable": verdict.stable,
            "p_known": band.p_known,
            "opps": band.opps,
            "difficulty": band.difficulty,
            "next_difficulty": stored.get("difficulty"),
            "repair": stored.get("repair") is not None,
        },
        ceiling_delta=policy.ceiling_delta(verdict.action),  # spec §13 A122
    )
    if verdict.action is policy.BandAction.WHEELSPIN:
        zpd_events.emit_zpd_wheelspin(
            user_id=user_id,
            request_id=request_id,
            concept_id=node_id,
            opps=band.opps,
            unassisted_next=verdict.rate,
            htc_k=verdict.htc_k,
            prerequisite_ids=list(band.prerequisite_ids),
        )


def _finish_check_checkpoint(checkpoint, scope, request, *, loop_on, deps=None, difficulty=None):
    receipt = _flush_grade_checkpoint(checkpoint, request, loop_on=loop_on, deps=deps)
    if receipt is _ITEM_RETIRED:
        raise HTTPException(status_code=409, detail=_RETIRED_DETAIL)
    if receipt is False:
        raise HTTPException(status_code=409, detail="Newer learning activity was recorded. Select another check to continue.")
    qh, claim = checkpoint.question_hash, checkpoint.operation_id
    c = checkpoint.continuation
    graded, correct, genuine = copy.deepcopy(c["graded"]), c["correct"], c["genuine"]
    committed = _committed_grade_observation(checkpoint, receipt, graded["node_id"])
    if graded.get("goal_observation") is not None:
        graded["goal_observation"].update(committed)
    now = graded["graded_at"]
    # spec §13 A122: the band controller's verdict on the concept, read now that
    # the journal holds this grade; stored on the step under the claim below and
    # applied when its feedback turn is served
    band = _band_verdict(
        checkpoint.user_id, graded["node_id"], _graded_difficulty(difficulty, checkpoint)
    )
    def record_grade(e: dict) -> None:
        if genuine:
            _record_attempt(e, now, failed=not correct)
        if e.get("graded_at") is None:
            e["first_attempt_correct"] = correct
        e["graded"] = int(e.get("graded") or 0) + 1
        e["wrong"] = int(e.get("wrong") or 0) + (0 if correct else 1)
        e.update(graded)

    under = _under_claim(qh, claim, record_grade, release=True)
    diagnosis = c["diagnosis"]

    held = {"last": False}

    def record_grade_and_diagnosis(doc: dict) -> None:
        _refuse_while_closing(doc, _now_s())
        _check_goal_version(doc, checkpoint.goal_version)
        entry = _steps(doc).get(qh)
        held["last"] = isinstance(entry, dict) and entry.get("grading_claim") == claim
        under(doc)
        if held["last"]:
            _steps(doc)[qh]["graded_operation_id"] = claim
            if band is not None and band.stored is not None:
                _steps(doc)[qh][_BAND_CONTROL] = dict(band.stored)
        if held["last"]:  # PKG-10: the attempt log + marker change, on the FRESH document
            carry(doc, diagnosis)
            # PKG-14 (spec §3.4): one more flushed check toward the zpd.rating prompt,
            # in this same write — only an evidence flush counts (A16, invariant 26)
            doc["checks_since_rating"] = int(doc.get("checks_since_rating") or 0) + 1
            held["checks"] = doc["checks_since_rating"]

    # saved NOW: a failed feedback turn is recovered by _phase_for. An exhausted
    # conflict retains the encrypted checkpoint; retry replays the same atomic
    # operation and then materializes this session continuation exactly once.
    state = _update_loop_state(checkpoint.session_id, record_grade_and_diagnosis, require_open=True, require_existing=True)
    if not held["last"]:
        raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
    if band is not None:  # after the save that recorded it under OUR claim: once per grade
        _emit_band_verdict(checkpoint.user_id, _request_id(request), graded["node_id"], band)
    if held["last"]:
        # PKG-10 (spec §13 A75): the row grade_answer marked, written only now —
        # after the ONE flush and the save that recorded the grade under OUR
        # claim (a claim lost to another request writes nothing; never raises)
        if (diagnosis or {}).get("record"):
            try:
                item = get_check_item((_steps(state).get(qh) or {}).get("check_item_id"))
                if item is not None:
                    _write_misconception(checkpoint.user_id, GradeOutcome(diagnosis=diagnosis),
                                         _item_like(item), CheckAnswer.model_validate(c["answer"]))
            except Exception:
                logger.warning("optional misconception rollup unavailable after saved grade")
        # spec §13 A127: a correct, unassisted answer on an isomorph closes the
        # misconceptions its item tests — after the flush and the claimed save
        _resolve_misconceptions(checkpoint, diagnosis, committed, surface="check", request=request)
    ask = held.get("checks", 0) >= ZPD_RATING_EVERY_N_CHECKS
    return _Submission("feedback", state, c["rendered"], scope, c["verdict"], refused=c["refused"], ask_rating=ask)
