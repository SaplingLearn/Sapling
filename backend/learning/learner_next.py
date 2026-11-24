"""Shared learner-next buckets (W8.6 / A143 inputs).

One pure function returns the three proposal sets Hub, the Quiz launcher and
the Dashboard all need — FSRS-due reviews, concepts with an open misconception,
then the ready fringe — in the same order `learning.quiz_plan.rank_concepts`
used before its per-course cap. Quiz plan caps those buckets; Study Focus and
Dashboard consume them uncapped (or with their own budget).

Pure: imports only learning.bkt, learning.fsrs, learning.planner (all pure), so
it is listed in tests/test_learning_loop_invariants.py::PURE_MODULES. The IO
read that assembles `ConceptState` rows lives in services/learner_next.py.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from learning import bkt, fsrs, planner

#: Why a concept appears in a learner-next bucket, in proposal order.
DUE = "due"
MISCONCEPTION = "misconception"
READY = "ready"
REASONS = (DUE, MISCONCEPTION, READY)


@dataclass(frozen=True)
class ConceptState:
    """One concept of the student's, as the plan / learner-next reads it."""

    node_id: str
    p_known: float  # decayed at read
    fsrs_s: float | None = None
    fsrs_last_review_at: datetime | None = None
    fsrs_due_at: datetime | None = None
    open_misconceptions: int = 0
    course_id: str | None = None  # the quiz plan's cap bucket (None: one shared)


@dataclass(frozen=True)
class NextConcept:
    """One concept in a learner-next bucket (or the quiz plan after capping)."""

    node_id: str
    reason: str
    p_known: float
    band: str
    due_at: datetime | None
    open_misconceptions: int


@dataclass(frozen=True)
class LearnerNext:
    """The three buckets, each already ordered for proposal."""

    due: tuple[NextConcept, ...]
    misconceptions: tuple[NextConcept, ...]
    ready: tuple[NextConcept, ...]

    @property
    def ordered(self) -> tuple[NextConcept, ...]:
        """Flat proposal order: due → misconceptions → ready."""
        return self.due + self.misconceptions + self.ready


def is_due(state: ConceptState, now: datetime) -> bool:
    """True when the concept's FSRS due date has passed (inclusive)."""
    return state.fsrs_due_at is not None and state.fsrs_due_at <= now


def _as_next(state: ConceptState, reason: str) -> NextConcept:
    return NextConcept(
        node_id=state.node_id,
        reason=reason,
        p_known=state.p_known,
        band=bkt.band(state.p_known),
        due_at=state.fsrs_due_at,
        open_misconceptions=state.open_misconceptions,
    )


def learner_next(
    states: Sequence[ConceptState],
    prereq_edges: Iterable[tuple[str, str]],
    now: datetime,
) -> LearnerNext:
    """Due reviews (DASH `fsrs.order_due`), then open-misconception concepts,
    then `planner.outer_fringe` — no per-course cap. A concept appears in at
    most one bucket (due wins over misconception over ready)."""
    by_id = {s.node_id: s for s in states}
    due_rows = [
        {
            "node_id": s.node_id,
            "fsrs_s": s.fsrs_s,
            "fsrs_last_review_at": s.fsrs_last_review_at,
        }
        for s in sorted(states, key=lambda s: s.node_id)
        if is_due(s, now)
    ]
    due = tuple(_as_next(by_id[row["node_id"]], DUE) for row in fsrs.order_due(due_rows, now))
    listed = {c.node_id for c in due}
    misconceptions = tuple(
        _as_next(s, MISCONCEPTION)
        for s in sorted(
            (s for s in states if s.open_misconceptions > 0 and s.node_id not in listed),
            key=lambda s: (-s.open_misconceptions, s.p_known, s.node_id),
        )
    )
    listed.update(c.node_id for c in misconceptions)
    fringe = planner.outer_fringe({s.node_id: s.p_known for s in states}, prereq_edges)
    ready = tuple(_as_next(by_id[node], READY) for node in fringe if node not in listed)
    return LearnerNext(due=due, misconceptions=misconceptions, ready=ready)
