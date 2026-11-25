"""The grade checkpoint (crash recovery of a graded answer): save, flush and
finish, and the band verdict it emits (A122).
"""
from __future__ import annotations

import copy
import logging
from typing import NamedTuple
import config
from services.loop.errors import HTTPException
from agents.deps import SaplingDeps
from agents.tools.check import CheckAnswer, GradeOutcome
from learning import policy, zpd_events
from learning import grade_checkpoint
from learning.claim_deadline import GradeDeadlineExceeded
from learning.evidence import (
    Evidence,
    PlanningObservation,
    PlanningPersistenceUnavailable,
    flush_pending,
    stated_confidence,
    weight_factors,
)
from learning.evidence_transaction import (
    EvidenceItemRetired,
    EvidenceObservationSuperseded,
    EvidenceTransactionConflict,
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
    ABANDON_EVIDENCE_REFUSED,
    ABANDON_MOVED_PAST,
    ABANDON_RECEIPT_MISMATCH,
    _abandon_claimed,
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

#: A saved grade's checkpoint kinds: a /check/answer grade and a probe grade.
CHECK_KIND = "check"
PROBE_KIND = "probe"

#: The loop phase a probe grade is flushed in.
_PROBE_PHASE = "probe"

#: The usage feature a recovered grade's deps bill under, by checkpoint kind.
_FEATURE_FOR_KIND = {CHECK_KIND: "loop_check", PROBE_KIND: "loop_probe"}

#: The 503 details of a grade that can be retried with the same answer.
EVIDENCE_UNAVAILABLE = "Learning evidence unavailable; retry the same answer"
RECOVERY_UNAVAILABLE = "Saved grade recovery unavailable; retry the same answer"
_RECOVERY_RETRY_LATER = "Saved grade recovery unavailable; retry later"

#: The 503 detail when grading outlived its claim deadline (#866 A1): nothing saved.
GRADE_TIMED_OUT = "Checking your answer took too long, so nothing was recorded. Please submit it again."

#: The 409 for a check grade a newer observation superseded before it was written.
_SUPERSEDED_DETAIL = "Newer learning activity was recorded. Select another check to continue."


def grading_failure_http(exc: BaseException) -> HTTPException | None:
    """The 503 a grading failure maps to before any checkpoint was saved (its
    claim already released), or None for one that propagates unchanged."""
    if isinstance(exc, GradeDeadlineExceeded):  # #866 A1: nothing saved, claim released
        return HTTPException(status_code=503, detail=GRADE_TIMED_OUT)
    if isinstance(exc, PlanningPersistenceUnavailable):
        return HTTPException(status_code=503, detail=EVIDENCE_UNAVAILABLE)
    return None


def grading_deps(body, course_id, request, *, kind: str, loop_on: bool, state: dict) -> SaplingDeps:
    """The deps one graded answer runs grade_answer under: billed to its kind's
    feature, with a copy of the loop state for the grade hook's attempt log
    (its change rides the checkpoint into the claimed save)."""
    return SaplingDeps(
        user_id=body.user_id,
        course_id=course_id or None,
        supabase=None,
        request_id=_request_id(request),
        session_id=body.session_id,
        feature=_FEATURE_FOR_KIND[kind],
        learning_loop=loop_on,
        loop_state=copy.deepcopy(state),
    )


def submitted_answer(body, *, idk: bool) -> CheckAnswer:
    """The student's explicit answer as the grader takes it."""
    return CheckAnswer(
        question_hash=body.question_hash,
        answer_text=body.answer,
        selected_option=body.option,
        reason=body.reason,
        idk=idk,
        # spec §13 A127: the stated confidence; an idk (a box or a phrase) states none
        confidence=None if idk else body.confidence,
    )


def _open_grade_checkpoint(entry, body, course_id, *, kind):
    try:
        return grade_checkpoint.open_checkpoint(
            entry.get(grade_checkpoint.KEY), kind=kind, operation_id=entry.get("grading_claim"),
            user_id=body.user_id, session_id=body.session_id, course_id=course_id or None,
            question_hash=body.question_hash,
        )
    except PlanningPersistenceUnavailable:
        raise HTTPException(status_code=503, detail=_RECOVERY_RETRY_LATER) from None


#: The 409 for an answer whose check was closed while it was graded: a later
#: request moved past the item (its claim had gone stale, or the item was
#: withdrawn), so the grade is discarded and nothing is written.
_MOVED_ON = "This check was closed while your answer was graded. Select another check to continue."


#: The 409 for a saved grade the evidence store refused for good (#866 review A2): the
#: answer is discarded with nothing written, and the session goes on.
_ABANDONED_DETAIL = "This answer could not be recorded. Select another check to continue."


def _save_grade_checkpoint(checkpoint):
    """Save the graded answer under its claim, on the item that is still
    current. A check item a later request moved past meanwhile (/check/next
    past a stale claim, a withdrawal) takes no checkpoint: a grade saved on a
    step that is no longer current could never be flushed (the flush needs it
    current) and would hold the session's close and chat for good. If the
    claim is still on such a step it is given up in the same write (409)."""
    encrypted = grade_checkpoint.seal(checkpoint)  # constant across CAS retries
    moved: dict = {}

    def save(doc):
        moved.clear()
        _refuse_while_closing(doc, _now_s())
        _check_goal_version(doc, checkpoint.goal_version)
        entry = (_steps(doc).get(checkpoint.question_hash) if checkpoint.kind == CHECK_KIND
                 else _probe_doc(doc).get("current"))
        if (isinstance(entry, dict) and checkpoint.kind == CHECK_KIND
                and entry.get("grading_abandoned") == ABANDON_MOVED_PAST
                and entry.get("discarded_grade_operation_id") == checkpoint.operation_id):
            raise HTTPException(status_code=409, detail=_MOVED_ON)  # /check/next closed it meanwhile
        if (not isinstance(entry, dict) or entry.get("grading_claim") != checkpoint.operation_id
                or (checkpoint.kind == PROBE_KIND and entry.get("question_hash") != checkpoint.question_hash)):
            raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
        if checkpoint.kind == CHECK_KIND and doc.get("current") != checkpoint.question_hash:
            _abandon_claimed(entry, ABANDON_MOVED_PAST)
            moved["past"] = True
            return
        entry[grade_checkpoint.KEY] = encrypted
        entry["grading_claim_at"] = _now_s()

    _update_loop_state(checkpoint.session_id, save, require_open=True, require_existing=True)
    if moved.get("past"):
        logger.warning("loop: a late grade found its check closed; discarded (%s)", ABANDON_MOVED_PAST)
        raise HTTPException(status_code=409, detail=_MOVED_ON)


def _abandon_grade_checkpoint(checkpoint, reason: str) -> None:
    """#866 review A2's terminal path for a saved grade the evidence store refuses
    for good (`reason`: its node is gone or outside the course, the
    operation's input or owner changed, or its committed receipt disagrees
    with the grade). Retrying the same answer can never succeed, so the claim
    is released and the checkpoint cleared in one write, under the claim, with
    no evidence written: a check step is closed for good with the reason kept
    on it (`_abandon_claimed`) and stops being current; a probe item counts as
    not asked (invariant 28) and the reason is kept on the probe. The session
    then continues (/check/next, /probe/next, chat) or closes. Logs the reason
    and the operation id only."""
    qh, claim = checkpoint.question_hash, checkpoint.operation_id

    def abandon(doc: dict) -> None:
        if checkpoint.kind == CHECK_KIND:
            entry = _steps(doc).get(qh)
            if isinstance(entry, dict) and entry.get("grading_claim") == claim:
                _abandon_claimed(entry, reason)
                if doc.get("current") == qh:
                    doc["current"] = None
            return

        def not_asked(pr: dict, cur: dict) -> None:
            pr.setdefault("abandoned", {})[qh] = reason
            _not_asked(pr, cur)

        _under_probe_claim(qh, claim, not_asked)(doc)

    _update_loop_state(checkpoint.session_id, abandon, require_open=True, require_existing=True)
    logger.warning(
        "loop: saved %s grade abandoned with no evidence (%s) operation=%s",
        checkpoint.kind, reason, claim,
    )


#: spec §13 A123: _flush_grade_checkpoint's answer when the commit refused the
#: grade because staff retired its item meanwhile (EvidenceItemRetired)
_ITEM_RETIRED = object()

#: #866 review A2: _flush_grade_checkpoint's answer for a check grade abandoned because the
#: store refused it for good (`_abandon_grade_checkpoint`); a probe's is False,
#: the answer its caller already gives as "not asked".
_GRADE_ABANDONED = object()


_RETIRED_DETAIL = "This question was withdrawn. Select another check to continue."


def _flush_guard(checkpoint):
    """The compare-and-set check before a flush: the grade's claim and its
    checkpoint are still on the entry, and a check step is still current."""
    orphan: dict = {}

    def guard(doc):
        orphan.clear()
        _refuse_while_closing(doc, _now_s())
        _check_goal_version(doc, checkpoint.goal_version)
        if checkpoint.kind == PROBE_KIND:
            _require_phase(doc, _PROBE_PHASE)
            entry = _probe_doc(doc).get("current")
        else:
            _require_teaching(doc)
            entry = _steps(doc).get(checkpoint.question_hash)
        if (not isinstance(entry, dict) or entry.get("grading_claim") != checkpoint.operation_id
                or grade_checkpoint.KEY not in entry):
            raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
        if checkpoint.kind == CHECK_KIND and doc.get("current") != checkpoint.question_hash:
            # A grade saved on a step that is no longer current (left by a
            # build before _save_grade_checkpoint refused that) can never be
            # flushed: closed here for good, in this write, so it stops
            # holding the session (#866 review A1)
            _abandon_claimed(entry, ABANDON_MOVED_PAST)
            orphan["moved"] = True

    return guard, orphan


def _supersede(checkpoint):
    """The write that retires a grade a newer observation (or a retirement)
    superseded: its pose is closed and fresh evidence is asked for."""

    def supersede(doc):
        if checkpoint.kind == CHECK_KIND:
            def retire(entry):
                entry["grading_superseded"] = True
                entry["discarded_grade_operation_id"] = checkpoint.operation_id
            _under_claim(checkpoint.question_hash, checkpoint.operation_id, retire, release=True)(doc)
            if doc.get("current") == checkpoint.question_hash:
                doc["current"] = None
        else:
            _under_probe_claim(checkpoint.question_hash, checkpoint.operation_id, _not_asked)(doc)

    return supersede


def _abandoned(checkpoint, reason: str):
    """Abandon the saved grade for good; a check's answer is _GRADE_ABANDONED,
    a probe's False (its caller's "not asked")."""
    _abandon_grade_checkpoint(checkpoint, reason)
    return _GRADE_ABANDONED if checkpoint.kind == CHECK_KIND else False


def _refused_flush(checkpoint, exc: Exception):
    """`_flush_grade_checkpoint`'s answer when its flush_pending refused the
    grade (`exc`, one of the three it catches, in its except order)."""
    if isinstance(exc, EvidenceObservationSuperseded):
        # The original answer has no committed receipt, and a newer observation
        # is already authoritative — or (A123, EvidenceItemRetired) staff retired
        # the item while it was graded, so the grade is void by definition and
        # nothing was written. Never apply the old answer out of order or
        # invent a diagnosis; retire its pose and ask for fresh evidence.
        _update_loop_state(checkpoint.session_id, _supersede(checkpoint), require_open=True, require_existing=True)
        return _ITEM_RETIRED if isinstance(exc, EvidenceItemRetired) else False
    if isinstance(exc, EvidenceTransactionConflict):
        # #866 review A2: a permanent refusal (the node is gone or outside the course, the
        # operation's input or owner changed): the same answer can never be
        # written, so it is abandoned instead of a 503 "retry" forever
        return _abandoned(checkpoint, ABANDON_EVIDENCE_REFUSED)
    raise HTTPException(status_code=503, detail=EVIDENCE_UNAVAILABLE) from None


def _committed_receipt(checkpoint):
    """The flushed grade's committed receipt, checked to attest it; a receipt
    that never will is abandoned (`_abandoned`'s answer)."""
    try:
        receipt = read_evidence_receipt(checkpoint.user_id, checkpoint.operation_id)
    except EvidenceTransactionConflict:  # the operation is another owner's: never ours to finish
        return _abandoned(checkpoint, ABANDON_RECEIPT_MISMATCH)
    except PlanningPersistenceUnavailable:
        raise HTTPException(status_code=503, detail=RECOVERY_UNAVAILABLE) from None
    if receipt is None:  # just flushed, so missing is a read that has not caught up: retry
        raise HTTPException(status_code=503, detail=RECOVERY_UNAVAILABLE)
    if receipt.get("course_id") != checkpoint.course_id:
        return _abandoned(checkpoint, ABANDON_RECEIPT_MISMATCH)
    _ledger(mark_graded, checkpoint.user_id, checkpoint.question_hash)
    try:
        _attested_observation(checkpoint, receipt, _graded_node(checkpoint))
    except _UNATTESTED:
        # #866 review A2: the committed receipt does not attest this grade, and it reads
        # the same on every retry: abandon the session record (the journal
        # keeps what it committed) instead of a 503 "retry" forever
        return _abandoned(checkpoint, ABANDON_RECEIPT_MISMATCH)
    return receipt


def _flush_grade_checkpoint(checkpoint, request, *, loop_on, deps=None):
    guard, orphan = _flush_guard(checkpoint)
    # The durable claim excludes goal changes and close. A conditional write
    # also checks ended_at/close_json before any replay can write evidence.
    _update_loop_state(checkpoint.session_id, guard, require_open=True, require_existing=True)
    if orphan.get("moved"):
        raise HTTPException(status_code=409, detail=_MOVED_ON)
    deps = deps or SaplingDeps(
        user_id=checkpoint.user_id, course_id=checkpoint.course_id, supabase=None,
        request_id=_request_id(request), session_id=checkpoint.session_id,
        feature=_FEATURE_FOR_KIND[CHECK_KIND if checkpoint.kind == CHECK_KIND else PROBE_KIND],
        learning_loop=loop_on,
    )
    deps.pending_evidence = copy.deepcopy(checkpoint.evidence)
    try:
        flush_pending(deps, checkpoint.course_id)
    except (EvidenceObservationSuperseded, EvidenceTransactionConflict, PlanningPersistenceUnavailable) as exc:
        return _refused_flush(checkpoint, exc)
    return _committed_receipt(checkpoint)


def _graded_node(checkpoint) -> str:
    """The node the saved grade observes (its continuation's)."""
    c = checkpoint.continuation
    return c["graded"]["node_id"] if checkpoint.kind == CHECK_KIND else c["observation"]["node_id"]


def _committed_grade_observation(checkpoint, receipt, node_id):
    """Use the final serialized writer's exposure provenance, never a stale guess.

    Another session may have answered this question after the grader began.
    The original grade stays frozen, but only the committed receipt can attest
    that this particular exposure was fresh and independently useful.

    A receipt that does not attest the grade (no single observation for it, or
    one that disagrees with or weakens it) is the committed record and reads
    the same on every retry, so it is permanent (#866 review A2): `_flush_grade_checkpoint`
    has already abandoned such a grade before this runs; should one reach here
    it is abandoned the same way (no session record) and the answer is a 409
    that lets the session go on — never a 503 "retry" forever.
    """
    try:
        return _attested_observation(checkpoint, receipt, node_id)
    except _UNATTESTED:
        _abandon_grade_checkpoint(checkpoint, ABANDON_RECEIPT_MISMATCH)
        raise HTTPException(status_code=409, detail=_ABANDONED_DETAIL) from None


#: What `_attested_observation` raises when the receipt does not attest the
#: grade (a validation error is a ValueError; `next` over no row stops).
_UNATTESTED = (ValueError, KeyError, TypeError, StopIteration)


def _attested_observation(checkpoint, receipt, node_id) -> dict:
    """The receipt's one observation of this grade, checked against the saved
    grade (raises ValueError, KeyError or a validation error when it does not
    attest it)."""
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


def _credited(checkpoint, node_id: str, committed: dict) -> dict:
    """#866 K07: what this grade was credited at — the weight the one writer
    journaled for it (evidence_weight over the sealed evidence row, with the
    writer's final same-session re-check flag from the committed receipt) and
    the factors that reduced it (learning.evidence.weight_factors). Stored on
    the graded step, so the feedback turn says what the journal holds, never a
    second rule rebuilt from the rung."""
    original = next(row for row in checkpoint.evidence if row["node_id"] == node_id)
    recheck = bool(original.get("same_session_recheck") or committed.get("same_session_recheck"))
    ev = Evidence.model_validate({**original, "same_session_recheck": recheck})
    return {"credit_weight": ev.weight, "credit_factors": weight_factors(ev)}


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


def _check_receipt(receipt):
    """The 409 for a check grade the flush did not write (`_flush_grade_checkpoint`'s
    sentinels); a receipt passes through."""
    if receipt is _ITEM_RETIRED:
        raise HTTPException(status_code=409, detail=_RETIRED_DETAIL)
    if receipt is _GRADE_ABANDONED:
        raise HTTPException(status_code=409, detail=_ABANDONED_DETAIL)
    if receipt is False:
        raise HTTPException(status_code=409, detail=_SUPERSEDED_DETAIL)
    return receipt


def _record_check_grade(checkpoint, graded: dict, band: _BandOutcome | None, held: dict):
    """The compare-and-set write that records a flushed check grade under its
    claim: the step's grade, the band verdict for its feedback turn, the
    attempt log and the zpd.rating count. `held["last"]` says whether the
    claim was still ours on the last run."""
    qh, claim = checkpoint.question_hash, checkpoint.operation_id
    c = checkpoint.continuation
    correct, genuine, diagnosis = c["correct"], c["genuine"], c["diagnosis"]
    now = graded["graded_at"]

    def record_grade(e: dict) -> None:
        if genuine:
            _record_attempt(e, now, failed=not correct)
        if e.get("graded_at") is None:
            e["first_attempt_correct"] = correct
        e["graded"] = int(e.get("graded") or 0) + 1
        e["wrong"] = int(e.get("wrong") or 0) + (0 if correct else 1)
        e.update(graded)

    under = _under_claim(qh, claim, record_grade, release=True)

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

    return record_grade_and_diagnosis


def _write_check_misconception(checkpoint, state: dict, diagnosis) -> None:
    """PKG-10 (spec §13 A75): the row grade_answer marked, written only now —
    after the ONE flush and the save that recorded the grade under OUR claim
    (a claim lost to another request writes nothing; never raises)."""
    if not (diagnosis or {}).get("record"):
        return
    try:
        item = get_check_item((_steps(state).get(checkpoint.question_hash) or {}).get("check_item_id"))
        if item is not None:
            _write_misconception(checkpoint.user_id, GradeOutcome(diagnosis=diagnosis),
                                 _item_like(item), CheckAnswer.model_validate(checkpoint.continuation["answer"]))
    except Exception:
        logger.warning("optional misconception rollup unavailable after saved grade")


def _check_dwell_ms(c) -> int:
    """W2.5: high stated confidence + wrong → Continue holds for corrective feedback."""
    verdict = c["verdict"]
    answer = c.get("answer") if isinstance(c.get("answer"), dict) else {}
    return policy.hypercorrection_feedback_dwell_ms(
        correct=verdict == "correct",
        student_confidence=stated_confidence(
            answer.get("confidence"), idk=verdict == "idk"
        ),
        idk=verdict == "idk",
        time_scale=config.LEARNING_GATE_TIME_SCALE,
    )


def _finish_check_checkpoint(checkpoint, scope, request, *, loop_on, deps=None, difficulty=None):
    receipt = _check_receipt(_flush_grade_checkpoint(checkpoint, request, loop_on=loop_on, deps=deps))
    c = checkpoint.continuation
    graded = copy.deepcopy(c["graded"])
    committed = _committed_grade_observation(checkpoint, receipt, graded["node_id"])
    graded.update(_credited(checkpoint, graded["node_id"], committed))
    if graded.get("goal_observation") is not None:
        graded["goal_observation"].update(committed)
    # spec §13 A122: the band controller's verdict on the concept, read now that
    # the journal holds this grade; stored on the step under the claim below and
    # applied when its feedback turn is served
    band = _band_verdict(
        checkpoint.user_id, graded["node_id"], _graded_difficulty(difficulty, checkpoint)
    )
    held = {"last": False}
    # saved NOW: a failed feedback turn is recovered by _phase_for. An exhausted
    # conflict retains the encrypted checkpoint; retry replays the same atomic
    # operation and then materializes this session continuation exactly once.
    state = _update_loop_state(
        checkpoint.session_id, _record_check_grade(checkpoint, graded, band, held),
        require_open=True, require_existing=True,
    )
    if not held["last"]:
        raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
    if band is not None:  # after the save that recorded it under OUR claim: once per grade
        _emit_band_verdict(checkpoint.user_id, _request_id(request), graded["node_id"], band)
    diagnosis = c["diagnosis"]
    _write_check_misconception(checkpoint, state, diagnosis)
    # spec §13 A127: a correct, unassisted answer on an isomorph closes the
    # misconceptions its item tests — after the flush and the claimed save
    _resolve_misconceptions(checkpoint, diagnosis, committed, surface="check", request=request)
    return _Submission(
        "feedback",
        state,
        c["rendered"],
        scope,
        c["verdict"],
        refused=c["refused"],
        ask_rating=held.get("checks", 0) >= ZPD_RATING_EVERY_N_CHECKS,
        feedback_dwell_ms=_check_dwell_ms(c),
    )
