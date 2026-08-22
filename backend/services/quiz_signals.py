"""Cheap personalization signals the quiz generator never asked for (#556, H4).

Each of these was already sitting in a table the request path touches, and
none of it reached the prompt:

  * `graph_nodes.times_studied` — in the row `generate_quiz` ALREADY reads,
    just not selected. Zero extra queries.
  * learning velocity — the 14-day computation already exists in
    `graph_service._compute_velocity`; this reuses it rather than writing a
    second one (see #557 for how two copies of one number ends).
  * an in-flight attempt on this concept — trivially available since #542
    added derived status.

NOT included: flashcard review state, which the issue also lists. There is no
concept-level flashcard data to read — `flashcards.topic` is free text and
every writer sets it to the COURSE name (`routes/flashcards.py` stores
`body.topic`; the only caller, `Study.tsx`, passes `course.course_name`). A
concept-name match against it is a permanent zero, and shipping that would
have F6 conclude the signal is worthless when it was simply never wired to
real data — which defeats the point of landing these behind a measurement.
Needs a concept↔card mapping first; see #556.

Per the issue, these land BEHIND the F6 measurement: every signal records its
own prompt dimension, so `llm_usage.prompt_tokens` can be attributed and the
question "is this worth its tokens?" is answerable with data rather than
taste. That is the point of landing them together.

Contract: never raises, and every read is owner-scoped and bounded. This runs
on the generation request path as one leg of the existing gather; a signal
nobody strictly needs must never be able to fail a quiz.
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

from db.connection import table

logger = logging.getLogger(__name__)

#: Cap on the mastery events read for the velocity computation. `_compute_velocity`
#: only looks 14 days back, so an unbounded read is pure transfer cost.
_EVENT_SCAN_LIMIT = 60


class QuizSignals(NamedTuple):
    """What else we know about this student and this concept.

    Every field is optional in the "we couldn't tell" sense: `None` means the
    read failed or was skipped, and is deliberately distinct from a zero,
    which is a fact about the student.
    """

    times_studied: int | None = None
    velocity_per_day: float | None = None
    in_flight_attempts: int | None = None

    def as_dimensions(self) -> dict[str, Any]:
        """F6: what this block contributed, for token attribution."""
        return {
            "signal_times_studied": self.times_studied,
            "signal_velocity": self.velocity_per_day,
            "signal_in_flight": self.in_flight_attempts,
        }


def gather_signals(
    user_id: str,
    concept_node_id: str,
    *,
    times_studied: Any = None,
) -> QuizSignals:
    """Collect the cheap signals for one (student, concept).

    `times_studied` is passed IN rather than re-read: `generate_quiz` already
    fetches that row to resolve the concept name and course, so selecting one
    more column costs nothing and a second read would cost a round-trip to
    learn something we were already told.
    """
    return QuizSignals(
        times_studied=_coerce_int(times_studied),
        velocity_per_day=_velocity(concept_node_id),
        in_flight_attempts=_in_flight(user_id, concept_node_id),
    )


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _velocity(concept_node_id: str) -> float | None:
    """Mastery gained per day over the last 14 days, via graph_service's own
    computation — imported, not re-derived."""
    if not concept_node_id:
        return None
    try:
        from services.graph_service import _compute_velocity

        rows = table("node_mastery_events").select(
            "delta,created_at",
            filters={"node_id": f"eq.{concept_node_id}"},
            # desc + limit so the cap keeps the NEWEST events; asc + limit
            # would keep the oldest, which is the opposite of what a 14-day
            # window wants.
            order="created_at.desc",
            limit=_EVENT_SCAN_LIMIT,
        ) or []
        # ...then REVERSED, because `_compute_velocity` derives its window
        # from `recent[0]` as the OLDEST recent event — `get_graph` feeds it
        # `created_at.asc` for exactly that reason. Handing it newest-first
        # collapses `days` to 1 and inflates the result by up to 14x, so the
        # Tree and the quiz prompt would report different velocities for the
        # same concept. That is the "two copies of one number" failure this
        # module cites #557 for, reintroduced through the argument instead of
        # the algorithm.
        return _compute_velocity(list(reversed(rows)))
    except Exception:
        logger.debug("quiz signals: velocity read failed", exc_info=True)
        return None


def _in_flight(user_id: str, concept_node_id: str) -> int | None:
    """Attempts on this concept the student started and has not finished.

    Owner-scoped, and it applies #542's TTL rather than only checking the two
    NULL stamps. `_attempt_status` treats an in-progress row past the TTL as
    abandoned EVEN BEFORE the lazy sweep stamps `abandoned_at` — and the sweep
    runs on the history/list reads, not on generation. So a NULL-only check
    would tell the model about attempts the rest of the app already calls
    abandoned: a student who generated three quizzes last week and never
    opened their history would be told they have three in flight.
    """
    if not user_id or not concept_node_id:
        return None
    try:
        from routes.quiz import _abandon_cutoff

        _rows, total = table("quiz_attempts").select_with_count(
            "id",
            filters={
                "user_id": f"eq.{user_id}",
                "concept_node_id": f"eq.{concept_node_id}",
                "completed_at": "is.null",
                "abandoned_at": "is.null",
                "created_at": f"gte.{_abandon_cutoff().isoformat()}",
            },
            limit=1,
        )
        # The exact count, not `len(rows)` under a cap: a saturated page would
        # report "20" as though it were a fact about the student.
        return total
    except Exception:
        logger.debug("quiz signals: in-flight read failed", exc_info=True)
        return None



def prompt_block(signals: QuizSignals) -> str:
    """One line per signal we actually have, or "" when we have nothing.

    Omission is deliberate: "times studied: unknown" spends tokens to say
    nothing, and a block of unknowns trains the model to ignore the block.
    """
    parts: list[str] = []
    if signals.times_studied is not None:
        parts.append(f"studied {signals.times_studied}x")
    if signals.velocity_per_day:
        # Falsy 0.0 is skipped on purpose: `_compute_velocity` returns 0.0
        # both for "no recent gain" and "not enough data", so reporting it
        # would assert stagnation we cannot distinguish from silence.
        parts.append(f"recent mastery gain ~{signals.velocity_per_day:.3f}/day")
    if signals.in_flight_attempts:
        parts.append(
            f"{signals.in_flight_attempts} unfinished attempt(s) on this concept"
        )

    if not parts:
        return ""
    return " Student signals: " + "; ".join(parts) + "."
