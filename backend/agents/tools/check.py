"""grade_answer — the single grading ROUTE helper (PKG-05; spec §13 A16, A22).

Turns one explicit student submission into one learning.evidence Evidence dict
on `deps.pending_evidence` and a code-side GradeOutcome. It is not a tutor
tool (A16): the check route (PKG-07), the probe (PKG-08), review (PKG-12) and
the post-test (PKG-14) call it. It NEVER persists: the calling route runs
learning.evidence.flush_pending once (spec §5, §8.1; inv_14). No Supabase
import here by design.

PKG-05b: it grades through the typed decision seam (services/decisions.py,
spec §13 A24): the rubric grade via `grade_rubric_items`, the mc_reason reason
check via `reason_is_correct` — each one agents.grader.grade() call with the
same format and answer as before, so grader prompts and llm_usage rows are
byte-identical — and the numeric clear-mismatch via
`deterministic_yes_no("numeric_gate", False)`. `grader_backend` comes from the
verdict's provenance (`decisions.evidence_backend`).

Spec §13 A33 (CodeRabbit PR #673): an answer that addresses the grader (grading
directives, role or format markers — before any model call, or on the grader's
own report after it) or is longer than GRADER_ANSWER_MAX_CHARS
is refused by agents.grader.grade(), and the seam hands it back as a `Refused`
verdict. grade_answer then returns GradeOutcome(unavailable=True,
refused=<reason>) and appends nothing: this attempt counts neither for nor
against the student, and the route asks for the answer again in the student's
own words instead of reporting an outage. A refusal is never a skip: the
route's own rule records the CHECK_REFUSALS_AS_IDK-th refusal of an item as
`idk` where its plan says so (PKG-07, PKG-08).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

from agents.deps import SaplingDeps
from agents.grader import GradeResult
from learning.answer_guard import Refusal
from learning.evidence import Evidence, GraderBackend
from learning.misconceptions import (
    Attempt,
    Verdict,
    attempts_for_node,
    attempts_of,
    confront_of,
    is_key,
    set_confront,
    slip_or_misconception,
)
from learning.params import LADDER_MAX_RUNG, NUMERIC_GATE_EDGE_SLACK
from services import decisions  # a module import: tests patch its functions
from services.decisions import GradeState, ReasonState

if TYPE_CHECKING:
    from learning.checks import CheckItem

logger = logging.getLogger("sapling.agents.tools.check")

#: The item's format → its evidence channel (spec §3.1 channel table).
CHANNEL_FOR_FORMAT: dict[str, str] = {
    "free": "free_response",
    "teachback": "teachback_llm",
    "mc_reason": "mc_reasoned",
}
_MC_REASON = "mc_reason"
_NUMERIC = "numeric"


class CheckAnswer(BaseModel):
    """One explicit submission (the A16 body fields). Flat by design."""

    question_hash: str
    answer_text: str = ""
    selected_option: str | None = None  # mc_reason: the letter chosen
    reason: str | None = None  # mc_reason: the one-sentence reason
    idk: bool = False  # explicit "I don't know" (A1)


@dataclass
class GradeOutcome:
    """Code-side verdict. `unavailable=True` → nothing was appended, for either
    outcome (A22, invariant 28). Never carries the reference answer.

    `refused` (A33) names why the answer was not graded: it addressed the grader,
    or it was longer than GRADER_ANSWER_MAX_CHARS (`too_long`).
    A refused outcome is also `unavailable` (fail closed for any caller that reads
    only that flag). The route shows "please answer in your own words" instead
    of the outage message, and never counts it as a genuine attempt for hint
    unlocking (PKG-06/07 `gates.genuine_attempt`)."""

    correct: bool | None = None
    confidence: float | None = None
    feedback_hint: str = ""  # optional downstream: the A16 feedback turn writes student text
    matched_wrong_key: str | None = None  # the grader's reason match, as returned
    wrong_key: str | None = None  # what PKG-10 may record (A22 rule in _wrong_key)
    unavailable: bool = False
    refused: Refusal | None = None
    grader_backend: GraderBackend | None = None
    evidence: dict | None = None  # the Evidence dict appended to deps.pending_evidence
    # PKG-10: the slip/misconception rule's verdict (None when the rule did not
    # run) and the change it made to deps.loop_state ({"attempt", "confront"}),
    # which the route re-applies to the FRESH document of its compare-and-set
    # save (learning.misconceptions.carry). Code-side; never reaches a model.
    verdict: Verdict | None = None
    diagnosis: dict | None = None


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def _option_matches(selected: str | None, correct_option: str | None) -> bool:
    return bool(_norm(selected)) and _norm(selected) == _norm(correct_option)


def _parse_number(text: str | None) -> float | None:
    try:
        value = float((text or "").strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _numeric_mismatch(item, answer: CheckAnswer) -> bool:
    """A22 numeric gate: True only for a clear mismatch against a VERIFIED key.
    A match, a parse failure or an unverified key → False (the rubric grader
    decides). It can only ever say "incorrect", never "correct"."""
    if item.answer_kind != _NUMERIC or not item.canonical_verified:
        return False
    got, want = _parse_number(answer.answer_text), _parse_number(item.canonical_answer)
    if got is None or want is None:
        return False
    # The gate fires only on a CLEAR mismatch: float noise at the edge is no gap.
    slack = NUMERIC_GATE_EDGE_SLACK * max(1.0, abs(got), abs(want))
    return abs(got - want) > (item.tolerance or 0.0) + slack


def _wrong_key(item, answer: CheckAnswer, *, correct: bool, matched: str | None) -> str | None:
    """A22: a key enters PKG-10's rule only when the student's reason matched it.
    An mc_reason wrong option carries its own key only when the grader matched
    that same key; the option → key map alone is a prior, never a record."""
    if correct or not matched:
        return None
    if item.format != _MC_REASON or _option_matches(answer.selected_option, item.correct_option):
        return matched
    chosen = next(
        (o for o in item.options or [] if _norm(o.letter) == _norm(answer.selected_option)), None
    )
    return matched if chosen is not None and chosen.wrong_key == matched else None


def _maps(item) -> dict:
    """The decrypted item fields a grading State carries, in item order (so the
    grader message rebuilt from the State is byte-identical; rubric ids and wrong
    keys are unique per item, PKG-04)."""
    return dict(
        question=item.prompt,
        reference=item.reference_answer,
        rubric={r.id: r.text for r in item.rubric},
        wrong={w.key: w.text for w in item.common_wrong},
        # grade()'s hint leak check only (spec §13 A38); never in the message
        final_answer=getattr(item, "final_answer", None),
        canonical_answer=getattr(item, "canonical_answer", None),
    )


def _via_seam(verdict) -> tuple[GradeResult, GraderBackend | None]:
    """PKG-05b: verdict → (GradeResult, grader_backend). None = honest degrade: unavailable, no
    evidence for either outcome (inv 28). GradeResult.backend marks a grader_second verdict.
    A `decisions.Refused` verdict carries its GradeResult with `refused` set (A33)."""
    if verdict is None:
        return GradeResult(unavailable=True), None
    second = verdict.result.backend == "gemini_second"
    return verdict.result, decisions.evidence_backend(verdict, second_opinion=second)


async def _rubric_grade(item, *, format: str, student_answer: str, deps: SaplingDeps):
    state = GradeState(**_maps(item), answer=student_answer, format=format)
    return _via_seam(await decisions.grade_rubric_items(state, deps=deps, item_id=item.id))


async def _reason_grade(item, *, selected_option: str, reason: str, deps: SaplingDeps):
    state = ReasonState(
        **_maps(item),
        selected_option=selected_option,
        correct_option=item.correct_option or "",
        reason=reason,
        # course vocabulary for grade()'s answer screen (A33); never in the message
        options={o.letter: o.text for o in item.options or []},
    )
    return _via_seam(await decisions.reason_is_correct(state, deps=deps, item_id=item.id))


def grader_answer_text(item, answer: CheckAnswer) -> str:
    """The text the grader sees for `answer` (mc_reason: PKG-05's byte-identical
    "Selected option: …\nReason: …", decisions.mc_reason_answer). PKG-10: the
    wrong-reason match reads it, and the check route stores it (encrypted) as a
    misconception's evidence_text."""
    if item.format == _MC_REASON:
        return decisions.mc_reason_answer(answer.selected_option or "", answer.reason or "")
    return answer.answer_text


async def match_wrong_key(item, *, prior, answer_text: str | None, deps: SaplingDeps) -> str | None:
    """PKG-10 (spec §13 A22/A24): the ONLY source of a wrong_key. The student's
    reason is matched against the item's listed wrong reasons through the
    decision seam. `prior` is the grader's result for this same answer, so
    every backend reuses its matched_wrong_key with NO model call — without it
    nothing is called (that would be an extra `decision` run against the grade
    cap). "none", a key the item does not list or that is not identifier-shaped,
    no listed keys, or a seam failure → None (WARNING on a failure): a lost key
    loses a diagnosis, never evidence, and never for only one outcome."""
    wrong = {w.key: w.text for w in item.common_wrong or [] if w.key}
    if not wrong or prior is None:
        return None
    state = decisions.WrongReasonState(question=item.prompt, answer=answer_text or "", wrong=wrong)
    try:
        pick = await decisions.match_wrong_reason(state, deps=deps, prior=prior)
    except Exception as exc:  # the seam has its own fallbacks; this is the last guard
        logger.warning("match_wrong_reason failed for item %s: %s", item.id, type(exc).__name__)
        return None
    if pick is None:  # unavailable (PKG-05b); never after a returned grade
        return None
    key = pick.value
    return key if key in wrong and is_key(key) else None  # NO_MATCH ("none") is never listed


async def apply_misconception_rule(
    deps: SaplingDeps,
    *,
    item,
    grade: GradeOutcome,
    evidence: Evidence,
) -> Verdict | None:
    """PKG-10 (spec §3.3; A16: the hook lives in grade_answer). Append this
    attempt to the session attempt log on `deps.loop_state`, run the rule over
    this concept's attempts, and on a keyed `misconception` set the
    confrontation marker and mark the store row to write
    (`grade.diagnosis["record"]`). grade_answer never persists (spec §13 A75):
    the check route writes the row with learning.misconceptions.record AFTER
    its one flush_pending, under the grading claim, so a failed flush never
    leaves a row behind for a resubmission to count twice. The key is grade.wrong_key — the seam-matched key
    after PKG-05's A22 option filter; the option → key map alone never reaches
    here. Student-stated confidence only: CheckAnswer has none yet, and
    grade.confidence is the grader's, deliberately not read. The change is
    also left on `grade.diagnosis` for the route's compare-and-set save.
    None (inert, nothing read or written) unless the loop is on and the caller
    loaded a loop state (only the check route does: the probe and the review
    pass none)."""
    if not deps.learning_loop or deps.loop_state is None:
        return None
    log = attempts_of(deps.loop_state)
    node_id = evidence.node_id  # the student's graph node; items are course assets (A2)
    earlier = [
        a
        for a in log
        if isinstance(a, dict)
        and a.get("node_id") == node_id
        and a.get("question_hash") != item.question_hash
    ]
    attempt = Attempt(
        question_hash=item.question_hash,
        node_id=node_id,
        correct=bool(evidence.correct),
        wrong_key=grade.wrong_key,
        confidence=None,
        difficulty=int(item.difficulty),
        idk=bool(evidence.idk),
        isomorph_of=earlier[-1].get("question_hash") if earlier else None,
    ).model_dump()
    log.append(attempt)
    verdict = slip_or_misconception(attempts_for_node(log, node_id))
    marker = cleared = to_record = None
    if verdict == "misconception" and grade.wrong_key:
        marker = {"node_id": node_id, "wrong_key": grade.wrong_key, "check_item_id": item.id}
        to_record = dict(marker)  # the store row the route writes after the flush
        set_confront(deps.loop_state, marker)
    elif evidence.correct:
        # a marker still waiting for a model turn (its feedback turn was a template)
        # never confronts a student who has since answered this concept right
        pending = confront_of(deps.loop_state)
        if pending is not None and pending["node_id"] == node_id:
            cleared = pending
            set_confront(deps.loop_state, None)
    grade.diagnosis = {
        "attempt": dict(attempt),
        "confront": marker,
        "cleared": cleared,
        "record": to_record,
    }
    return verdict


async def _record(
    deps: SaplingDeps,
    outcome: GradeOutcome,
    ev: Evidence,
    *,
    item,
) -> GradeOutcome:
    """Append the Evidence dict. Its weight is PKG-03's evidence_weight(ev),
    derived by the model at validation from the flags: assisted (a correct
    answer at H1–H3), the same-session re-check, the grader's confidence for
    BOTH outcomes, and 0.0 for a correct answer after H4–H6. PKG-10: the
    slip/misconception rule runs first; its verdict and the matched key ride
    the Evidence dict (spec §5) — nothing journals them (no column), the
    misconceptions row is the durable record."""
    outcome.verdict = await apply_misconception_rule(deps, item=item, grade=outcome, evidence=ev)
    row = ev.model_copy(update={"verdict": outcome.verdict, "wrong_key": outcome.wrong_key})
    row = Evidence.model_validate(row.model_dump()).model_dump()
    deps.pending_evidence.append(row)
    outcome.evidence = row
    return outcome


async def grade_answer(
    item: CheckItem,
    answer: CheckAnswer,
    *,
    deps: SaplingDeps,
    node_id: str,
    max_rung: int = 0,
    same_session_recheck: bool = False,
) -> GradeOutcome:
    """Grade one explicit submission and append its Evidence to deps.pending_evidence.

    `item` is a decrypted CheckItem the caller loaded by `answer.question_hash`;
    `node_id` is the student's graph_nodes id for `item.concept_key` (the
    caller resolves it: items are course assets keyed per concept, A2).
    `max_rung` is the highest hint rung used before the answer (0..LADDER_MAX_RUNG);
    Evidence derives `assisted` from it (PKG-03). Raises ValueError for a rung off
    the ladder and KeyError for an unknown format, before any grader call; a
    grader failure never raises (GradeOutcome(unavailable=True)).
    """
    if not deps.learning_loop:
        return GradeOutcome(unavailable=True)
    if not 0 <= max_rung <= LADDER_MAX_RUNG:
        raise ValueError(f"max_rung {max_rung} is off the ladder (0..{LADDER_MAX_RUNG})")
    base = dict(
        node_id=node_id,
        channel=CHANNEL_FOR_FORMAT[item.format],
        max_rung=max_rung,
        session_id=deps.session_id,
        check_item_id=item.id,
        question_hash=item.question_hash,
        same_session_recheck=same_session_recheck,
    )

    answer_text = grader_answer_text(item, answer)  # PKG-10: the wrong-reason match

    if answer.idk:  # A1: an incorrect observation on the item's channel; no grader call
        return await _record(
            deps,
            GradeOutcome(correct=False),
            Evidence(idk=True, correct=False, **base),
            item=item,
        )

    if item.format == _MC_REASON:  # the reason check runs for BOTH option outcomes (A22)
        result, backend = await _reason_grade(
            item,
            selected_option=answer.selected_option or "",
            reason=answer.reason or "",
            deps=deps,
        )
    else:
        result, backend = await _rubric_grade(
            item, format=item.format, student_answer=answer.answer_text, deps=deps
        )
    if result.refused:  # A33: addressed to the grader; nothing for EITHER outcome
        return GradeOutcome(unavailable=True, refused=result.refused)
    if result.unavailable:  # A22 / invariant 28: nothing for EITHER outcome
        return GradeOutcome(unavailable=True)

    correct = result.all_yes
    if item.format == _MC_REASON:
        correct = correct and _option_matches(answer.selected_option, item.correct_option)
    # A22/A24 (PKG-10): the key comes only from the decision seam, handed the
    # grader's own result as `prior` (no model call); PKG-05's option filter below.
    matched = await match_wrong_key(item, prior=result, answer_text=answer_text, deps=deps)
    confidence: float | None = result.confidence
    if item.format != _MC_REASON and _numeric_mismatch(item, answer):
        # A22 numeric gate, AFTER the grader returned (it ran for both outcomes, so an
        # outage or the grade cap above recorded nothing for either — invariant 28).
        # It can only ever say "incorrect"; the grader's matched key still stands.
        det = decisions.evidence_backend(
            decisions.deterministic_yes_no("numeric_gate", False, deps=deps)
        )
        correct, backend, confidence = False, det, None
    outcome = GradeOutcome(
        correct=correct,
        confidence=confidence,
        feedback_hint=result.feedback_hint,
        matched_wrong_key=matched,
        wrong_key=_wrong_key(item, answer, correct=correct, matched=matched),
        grader_backend=backend,
    )
    ev = Evidence(correct=correct, confidence=confidence, grader_backend=backend, **base)
    return await _record(deps, outcome, ev, item=item)
