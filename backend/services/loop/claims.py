"""The explicit submission's bookkeeping (A16, C2): the submission record, the
item's grading claim, attempts and the misconceptions a grade records.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from collections.abc import Callable
from services.loop.errors import HTTPException
from starlette.requests import Request
from agents.tools.check import CheckAnswer, grader_answer_text
from learning import gates
from learning import grade_checkpoint
from learning.misconceptions import record, resolve_after_grade
from learning.params import LOOP_GRADING_CLAIM_STALE_S
from models import LoopCheckAnswerBody

from services.loop.constants import _ALREADY_GRADED, _IDK_RENDERED
from services.loop.state import _refuse_while_closing, _request_id, _steps, _update_loop_state
from services.loop.planning import _probe_doc

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


# ── The explicit-submission route (A16) ───────────────────────────────────


@dataclass
class _Submission:
    kind: str  # "feedback" | "hint_request" | "unavailable" | "refused"
    state: dict
    rendered: str  # the user row persisted for this submission
    scope: tuple[str, str]
    verdict: str | None = None
    refused: bool = False  # A33: refused, or the idk its CHECK_REFUSALS_AS_IDK-th refusal became
    ask_rating: bool = False  # PKG-14: this graded check brought the counter to the rating cadence


def _is_idk_phrase(text: str) -> bool:
    """A16's idk split, as HANDOFF-06 defines it: the submission routes to idk
    when gates.non_attempt_phrases (the A16 routing rule, which fails toward
    grading) returns a gates.IDK_PATTERNS phrase (A40 06(b): "idk", "i don't
    know", "no idea", "dunno") — so a hedged answer ("idk maybe 7") is graded,
    never turned into idk evidence."""
    return any(p in gates.IDK_PATTERNS for p in gates.non_attempt_phrases(text or ""))


def _render_submission(body: LoopCheckAnswerBody, *, idk: bool) -> str:
    if body.answer:
        return body.answer
    if body.option:
        return f"({body.option}) {body.reason}".strip()
    if idk:
        return _IDK_RENDERED
    return body.reason


def _record_attempt(entry: dict, now: float, *, failed: bool) -> None:
    """A genuine attempt: its time counts toward hint unlocking
    (`attempted_at`), and one that did not close the step correct is a failed
    genuine attempt (PKG-06's `attempts`, the ceiling's input)."""
    entry["attempted_at"] = [*(entry.get("attempted_at") or []), now]
    if failed:
        entry["attempts"] = int(entry.get("attempts") or 0) + 1


def _on_step(qh: str, change: Callable[[dict], None]) -> Callable[[dict], None]:
    """A compare-and-set mutate that applies `change` to the item's per-step
    entry in the FRESH document (nothing when the entry is gone)."""

    def mutate(state: dict) -> None:
        entry = _steps(state).get(qh)
        if isinstance(entry, dict):
            change(entry)

    return mutate


def _grading_open(entry: dict | None, now: float) -> bool:
    """The item still takes answers: never graded, and not left under a claim
    older than LOOP_GRADING_CLAIM_STALE_S (a crash mid-grade or a conflict
    after the flush — /check/next moves past it; it is never graded again)."""
    if not isinstance(entry, dict) or entry.get("graded_at") is not None or entry.get("grading_superseded"):
        return False
    if grade_checkpoint.KEY in entry:
        return True  # a saved result must be recovered, never abandoned as stale
    claimed_at = entry.get("grading_claim_at")
    return not (
        entry.get("grading_claim") and now - float(claimed_at or 0) > LOOP_GRADING_CLAIM_STALE_S
    )


def _claim_grading(session_id: str, qh: str, claim: str, now: float) -> None:
    """C2 (review round 3): grading is a CLAIM. One compare-and-set write sets
    `steps[qh].grading_claim` only when the item is ungraded and unclaimed;
    otherwise nothing is written and the submission is a 409. The claim is
    never re-taken: the grade, the ONE flush and its record all run under it,
    so a resubmission after the release, a double submit or a concurrent
    refusal can never grade (or flush) the item twice."""

    def take(state: dict) -> None:
        _refuse_while_closing(state, now)  # PKG-09: grading and closing exclude each other
        entry = _steps(state).get(qh)
        if not isinstance(entry, dict):
            raise HTTPException(status_code=404, detail="No such check item in this session")
        if entry.get("graded_at") is not None or entry.get("grading_claim"):
            raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
        entry["grading_claim"], entry["grading_claim_at"] = claim, now

    _update_loop_state(session_id, take)


def _under_claim(qh: str, claim: str, change: Callable[[dict], None], *, release: bool):
    """A mutate that applies `change` to the item's entry only while `claim`
    holds it, and — `release` — gives the claim up in the same write."""

    def mutate(state: dict) -> None:
        entry = _steps(state).get(qh)
        if not isinstance(entry, dict) or entry.get("grading_claim") != claim:
            return
        change(entry)
        if release:
            entry.pop("grading_claim", None)
            entry.pop("grading_claim_at", None)
            entry.pop(grade_checkpoint.KEY, None)

    return mutate


def _write_misconception(user_id: str, outcome, item, answer: CheckAnswer) -> None:
    """PKG-10: write the misconceptions row the grade marked
    (`outcome.diagnosis["record"]`), its evidence_text the text the grader saw
    (encrypted by learning.misconceptions.record). Nothing marked, nothing
    written; the store never raises."""
    mark = (getattr(outcome, "diagnosis", None) or {}).get("record")
    if not mark:
        return
    record(
        user_id,
        mark["node_id"],
        mark["check_item_id"],
        mark["wrong_key"],
        grader_answer_text(item, answer),
        question_hash=getattr(item, "question_hash", None),  # A123: the supporting attempt's item
    )


def _resolve_misconceptions(
    checkpoint, diagnosis: dict | None, committed: dict, *, surface: str, request: Request
) -> list[str]:
    """Spec §13 A127: close what a correct, unassisted answer on an isomorph
    closes — the keys the hook listed for this answer (`diagnosis["resolve"]`:
    the item's keys but one the student's reason matched), judged on the
    grade's FINAL observation (`committed`: the single writer's, with the help
    floor's rung and any re-check it forced). Called by the check route and
    the probe after their one flush and the claimed save that recorded the
    grade (A75 (a)'s order), so a failed flush closes nothing. It never changes
    the response, the phase or the next item (the probe stays a diagnostic,
    A120 (e)). A checkpoint saved before A127 lists no keys: nothing to close.
    Never raises."""
    keys = (diagnosis or {}).get("resolve") or []
    if not keys:
        return []
    try:
        return resolve_after_grade(
            checkpoint.user_id,
            committed["node_id"],
            keys=keys,
            item_id=committed.get("check_item_id"),
            attempt=committed,
            surface=surface,
            session_id=checkpoint.session_id,
            request_id=_request_id(request),
        )
    except Exception:
        logger.warning("misconception resolution unavailable after saved grade")
        return []


def _on_posed(qh: str, change: Callable[[dict, dict], None]) -> Callable[[dict], None]:
    """A compare-and-set mutate over the probe's posed item `qh`: `change(pr,
    current)` runs only while `qh` is still the posed item."""

    def mutate(doc: dict) -> None:
        pr = _probe_doc(doc)
        cur = pr.get("current")
        if isinstance(cur, dict) and cur.get("question_hash") == qh:
            change(pr, cur)

    return mutate


def _under_probe_claim(
    qh: str, claim: str, change: Callable[[dict, dict], None]
) -> Callable[[dict], None]:
    """`_on_posed`, applied only while `claim` holds the item (PKG-07's
    `_under_claim` for the probe's posed item)."""

    def guarded(pr: dict, cur: dict) -> None:
        if cur.get("grading_claim") == claim:
            change(pr, cur)

    return _on_posed(qh, guarded)


def _not_asked(pr: dict, cur: dict) -> None:
    """Invariant 28 / Behaviour 11: the item counts as not asked — excluded from
    selection, never counted toward a cap; the next /probe/next serves another."""
    if cur["question_hash"] not in pr["unavailable"]:
        pr["unavailable"].append(cur["question_hash"])
    pr["current"] = None
