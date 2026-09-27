"""grade_answer — the single grading ROUTE helper (PKG-05; spec §13 A16, A22).

Turns one explicit student submission into one learning.evidence Evidence dict
on `deps.pending_evidence` and a code-side GradeOutcome. It is not a tutor
tool (A16): the check route (PKG-07), the probe (PKG-08), review (PKG-12) and
the post-test (PKG-14) call it. It NEVER persists: the calling route runs
learning.evidence.flush_pending once (spec §5, §8.1; inv_14). No Supabase
import here by design.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

from agents.deps import SaplingDeps
from agents.grader import grade
from learning.evidence import Evidence, GraderBackend
from learning.params import LADDER_MAX_RUNG

if TYPE_CHECKING:
    from learning.checks import CheckItem

#: The item's format → its evidence channel (spec §3.1 channel table).
CHANNEL_FOR_FORMAT: dict[str, str] = {
    "free": "free_response",
    "teachback": "teachback_llm",
    "mc_reason": "mc_reasoned",
}
_MC_REASON = "mc_reason"
_NUMERIC = "numeric"
# Float noise at the tolerance edge: an answer exactly `tolerance` away in
# decimal lands a hair either side in binary (|0.4 − 0.3| = 0.10000000000000003).
# The gate fires only on a CLEAR mismatch, so a gap within this relative slack
# of the operands' magnitude still counts as on the edge. Not a policy value:
# it sits orders of magnitude above double-precision error (~1e-16) and below
# any tolerance a key would carry.
_EDGE_SLACK = 1e-12


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
    outcome (A22, invariant 28). Never carries the reference answer."""

    correct: bool | None = None
    confidence: float | None = None
    feedback_hint: str = ""  # optional downstream: the A16 feedback turn writes student text
    matched_wrong_key: str | None = None  # the grader's reason match, as returned
    wrong_key: str | None = None  # what PKG-10 may record (A22 rule in _wrong_key)
    unavailable: bool = False
    grader_backend: GraderBackend | None = None
    evidence: dict | None = None  # the Evidence dict appended to deps.pending_evidence


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
    slack = _EDGE_SLACK * max(1.0, abs(got), abs(want))
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


def _record(deps: SaplingDeps, outcome: GradeOutcome, ev: Evidence) -> GradeOutcome:
    """Append the Evidence dict. Its weight is PKG-03's evidence_weight(ev),
    derived by the model at validation from the flags: assisted (a correct
    answer at H1–H3), the same-session re-check, the grader's confidence for
    BOTH outcomes, and 0.0 for a correct answer after H4–H6."""
    row = ev.model_dump()
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

    if answer.idk:  # A1: an incorrect observation on the item's channel; no grader call
        return _record(deps, GradeOutcome(correct=False), Evidence(idk=True, correct=False, **base))

    student_answer = answer.answer_text
    if item.format == _MC_REASON:  # the reason check runs for BOTH option outcomes (A22)
        student_answer = (
            f"Selected option: {answer.selected_option or ''}\nReason: {answer.reason or ''}"
        )
    result = await grade(item, format=item.format, student_answer=student_answer, deps=deps)
    if result.unavailable:  # A22 / invariant 28: nothing for EITHER outcome
        return GradeOutcome(unavailable=True)

    correct = result.all_yes
    if item.format == _MC_REASON:
        correct = correct and _option_matches(answer.selected_option, item.correct_option)
    matched = result.matched_wrong_key or None
    backend: GraderBackend | None = result.backend
    confidence: float | None = result.confidence
    if item.format != _MC_REASON and _numeric_mismatch(item, answer):
        # A22 numeric gate, AFTER the grader returned (it ran for both outcomes, so an
        # outage or the grade cap above recorded nothing for either — invariant 28).
        # It can only ever say "incorrect"; the grader's matched key still stands.
        correct, backend, confidence = False, "deterministic", None
    outcome = GradeOutcome(
        correct=correct,
        confidence=confidence,
        feedback_hint=result.feedback_hint,
        matched_wrong_key=matched,
        wrong_key=_wrong_key(item, answer, correct=correct, matched=matched),
        grader_backend=backend,
    )
    ev = Evidence(correct=correct, confidence=confidence, grader_backend=backend, **base)
    return _record(deps, outcome, ev)
