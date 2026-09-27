"""FSRS-6 scheduler for the learning loop (spec §3.2). Pure: no I/O, no DB, no LLM.

Stability ``S`` is in days (the time for retrievability to fall to 0.9),
difficulty ``D`` is in [1, 10], retrievability ``R`` is in (0, 1]. Every
formula below is the spec's, verbatim, over the weights ``params.FSRS_W``.
Ratings are the FSRS grades 1 Again / 2 Hard / 3 Good / 4 Easy; v1 never
emits Easy (``rating_for`` returns at most Good).
"""

from __future__ import annotations

import math

from learning.params import (
    FSRS_EXAM_WINDOW_DAYS,
    FSRS_LARGE_SET_CONCEPTS,
    FSRS_RETENTION_DEFAULT,
    FSRS_RETENTION_EXAM,
    FSRS_RETENTION_LARGE_SET,
    FSRS_W,
)

W = FSRS_W
_DECAY = W[20]
_STABILITY_R = 0.9  # R(t = S) by the definition of stability (spec §3.2)
FACTOR = _STABILITY_R ** (-1 / _DECAY) - 1


# --- curves -----------------------------------------------------------------


def _check_days(days: float) -> None:
    # `not days >= 0` also rejects NaN; +inf is allowed (R → 0, the limit).
    if not days >= 0:
        raise ValueError(f"days must be >= 0, got {days}")


def _check_stability(stability: float) -> None:
    if not (math.isfinite(stability) and stability > 0):
        raise ValueError(f"stability must be finite and > 0, got {stability}")


def retrievability(days: float, stability: float) -> float:
    """R(t, S) = (1 + factor·t/S)^(−w20). R(0, S) = 1; R(S, S) = 0.9."""
    _check_days(days)
    _check_stability(stability)
    return (1 + FACTOR * days / stability) ** (-_DECAY)


def interval(retention: float, stability: float) -> float:
    """I(r, S) = (S/factor)·(r^(−1/w20) − 1): days until R falls to ``retention``."""
    if not 0 < retention <= 1:
        raise ValueError(f"retention must be in (0, 1], got {retention}")
    _check_stability(stability)
    return (stability / FACTOR) * (retention ** (-1 / _DECAY) - 1)


def retention_target(n_scheduled: int, exam_within_days: int | None = None) -> float:
    """Desired retention: exam window wins, then large set, else default (spec §3.2)."""
    if exam_within_days is not None and exam_within_days <= FSRS_EXAM_WINDOW_DAYS:
        return FSRS_RETENTION_EXAM
    if n_scheduled > FSRS_LARGE_SET_CONCEPTS:
        return FSRS_RETENTION_LARGE_SET
    return FSRS_RETENTION_DEFAULT
