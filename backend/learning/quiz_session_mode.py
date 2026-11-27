"""Practice vs Exam Twin session modes (Alvar plan W7.8).

Pure: no I/O, no model. Listed in
`tests/test_learning_loop_invariants.py::PURE_MODULES`.

Two quiz session modes share one generate/submit path. They differ in what
counts as mastery evidence and which tools are allowed — not in how
questions are written.

| Mode | Mastery evidence | Misconceptions (A146) | Tools (Ask / help) | Farm claim (A100) |
|------|------------------|----------------------|--------------------|-------------------|
| `practice` | Yes — A132 lint + A145 gate → farm → help → `apply_graph_update` | Yes when flagged | Allowed | Claims the rolling window |
| `exam_twin` | No — score only (dress-rehearsal / post-test-*like* UX) | No | Refused | Does **not** claim (so Practice later can still count) |

**Why Exam Twin writes no mastery.** Plan W7.8: Practice *is* the learning
evidence path; Exam Twin is timed and tool-light and **must not** double-count
daily evidence. Skipping the evidence write (and the farm claim) is the
strong form of that rule. The delayed Learn post-test remains the learning-
gain measure; Exam Twin is a quiz UX mode, not a second evidence channel.

Default / missing / unknown → `practice` (pre-W7.8 attempts, omitted body).
"""

from __future__ import annotations

from typing import Literal

QuizSessionMode = Literal["practice", "exam_twin"]

PRACTICE: QuizSessionMode = "practice"
EXAM_TWIN: QuizSessionMode = "exam_twin"
MODES: tuple[QuizSessionMode, ...] = (PRACTICE, EXAM_TWIN)

#: Student-facing labels (UI + results). Kept here so server events and the
#: frontend twin stay aligned; the frontend re-states the same strings.
LABELS: dict[QuizSessionMode, str] = {
    PRACTICE: "Practice",
    EXAM_TWIN: "Exam Twin",
}


def parse(value: object) -> QuizSessionMode:
    """Wire / stored value → mode. Anything unknown is Practice (fail open to
    the learning-evidence path, never to score-only)."""
    if isinstance(value, str) and value in MODES:
        return value  # type: ignore[return-value]
    return PRACTICE


def writes_mastery(mode: QuizSessionMode) -> bool:
    """True when submit may build `mc` evidence for this attempt."""
    return mode == PRACTICE


def allows_tools(mode: QuizSessionMode) -> bool:
    """True when Ask-about-this / help ledger rows are allowed for the attempt."""
    return mode == PRACTICE


def allows_misconceptions(mode: QuizSessionMode) -> bool:
    """True when A146 may record/resolve misconceptions after submit."""
    return mode == PRACTICE


def claims_farm_window(mode: QuizSessionMode) -> bool:
    """True when submit may take an A100 `quiz_evidence_claims` row.

    Exam Twin must not burn the window: a dress rehearsal that claimed would
    make a later Practice round `already_counted` without ever writing
    mastery — a silent double-block, not double-count, but still wrong.
    """
    return mode == PRACTICE


__all__ = [
    "EXAM_TWIN",
    "LABELS",
    "MODES",
    "PRACTICE",
    "QuizSessionMode",
    "allows_misconceptions",
    "allows_tools",
    "claims_farm_window",
    "parse",
    "writes_mastery",
]
