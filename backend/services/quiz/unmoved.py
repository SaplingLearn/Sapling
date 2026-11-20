"""Why a graded quiz could not move the concept's mastery (#866 K40).

A submit writes mastery evidence for each question through three gates, in
order (services/quiz/submission.py): `_lint_gate` drops a question its checks
flagged or did not verify (spec §13 A132, A145), `_farm_guard` drops one this
student already earned evidence for in the rolling window (A94, A100), and
`_help_floor` keeps the rest but takes the upward credit off a right answer the
student had help on (A99). The results screen says why the mastery stayed
where it was from THIS record, never from the percent it shows: a percent can
stand still with evidence written (a mastery at 99.5 % reads 100 %; right and
wrong answers that net out), and then no reason is true.
"""

from __future__ import annotations

from typing import Literal

from learning.params import RUNG_NO_CREDIT_MIN

#: The reasons, each true of at least one question when it is listed.
Reason = Literal["not_verified", "already_counted", "helped", "write_failed"]


def _can_move(ev: dict) -> bool:
    """A written evidence that can move p_known: a wrong answer always does
    (a standard incorrect observation at any rung), a right one unless it was
    floored at no credit (`learning.evidence.evidence_weight` == 0)."""
    return not (ev.get("correct") and int(ev.get("max_rung") or 0) >= RUNG_NO_CREDIT_MIN)


def mastery_unmoved(
    *, graded: int, checked: int, counted: int, written: list[dict], stored: bool,
) -> list[Reason] | None:
    """The reasons NO question of this submit could move the mastery, or None
    when one could (or there was no question at all).

    `graded` questions were graded, `checked` survived `_lint_gate`, `counted`
    survived `_farm_guard`, and `written` is what `_help_floor` handed the
    graph writer. `stored` is False when the evidence did not reach the graph:
    the farm guard's claim failed (it fails closed) or the write raised
    (#760) — then the one reason is `write_failed`."""
    if not stored:
        return ["write_failed"]
    if any(_can_move(ev) for ev in written):
        return None
    reasons: list[Reason] = []
    if checked < graded:
        reasons.append("not_verified")
    if counted < checked:
        reasons.append("already_counted")
    if written:
        reasons.append("helped")
    return reasons or None
