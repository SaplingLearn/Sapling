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
  * flashcards for this concept — whether the student has drilled it another
    way, and how recently.

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
    flashcards: int | None = None

    def as_dimensions(self) -> dict[str, Any]:
        """F6: what this block contributed, for token attribution."""
        return {
            "signal_times_studied": self.times_studied,
            "signal_velocity": self.velocity_per_day,
            "signal_in_flight": self.in_flight_attempts,
            "signal_flashcards": self.flashcards,
        }


def gather_signals(
    user_id: str,
    concept_node_id: str,
    *,
    concept_name: str = "",
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
        flashcards=_flashcards(user_id, concept_name),
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
            order="created_at.desc",
            limit=_EVENT_SCAN_LIMIT,
        ) or []
        return _compute_velocity(rows)
    except Exception:
        logger.debug("quiz signals: velocity read failed", exc_info=True)
        return None


def _in_flight(user_id: str, concept_node_id: str) -> int | None:
    """Attempts on this concept the student started and never finished.

    Owner-scoped, and `completed_at IS NULL` is the same derived-status rule
    #542 established rather than a second definition of "unfinished".
    """
    if not user_id or not concept_node_id:
        return None
    try:
        rows = table("quiz_attempts").select(
            "id",
            filters={
                "user_id": f"eq.{user_id}",
                "concept_node_id": f"eq.{concept_node_id}",
                "completed_at": "is.null",
                "abandoned_at": "is.null",
            },
            limit=20,
        ) or []
        return len(rows)
    except Exception:
        logger.debug("quiz signals: in-flight read failed", exc_info=True)
        return None


def _flashcards(user_id: str, concept_name: str) -> int | None:
    """How many cards the student has for this concept.

    Matched on `topic`, which is where the concept name lands for cards
    generated from the graph. Front/back are encrypted (#518) and are neither
    read nor needed — this is a COUNT, not content.
    """
    if not user_id or not concept_name:
        return None
    try:
        rows = table("flashcards").select(
            "id",
            filters={
                "user_id": f"eq.{user_id}",
                "topic": f"eq.{concept_name}",
            },
            limit=100,
        ) or []
        return len(rows)
    except Exception:
        logger.debug("quiz signals: flashcard read failed", exc_info=True)
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
    if signals.flashcards:
        parts.append(f"{signals.flashcards} flashcard(s) on this concept")

    if not parts:
        return ""
    return " Student signals: " + "; ".join(parts) + "."
