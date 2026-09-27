"""FSRS-6 scheduler for the learning loop (spec §3.2). Pure: no I/O, no DB, no LLM.

Stability ``S`` is in days (the time for retrievability to fall to 0.9),
difficulty ``D`` is in [1, 10], retrievability ``R`` is in (0, 1]. Every
formula below is the spec's, verbatim, over the weights ``params.FSRS_W``.
Ratings are the FSRS grades 1 Again / 2 Hard / 3 Good / 4 Easy; v1 never
emits Easy (``rating_for`` returns at most Good).
"""

from __future__ import annotations

import math
from enum import IntEnum

from learning.params import (
    FSRS_EXAM_WINDOW_DAYS,
    FSRS_LARGE_SET_CONCEPTS,
    FSRS_RETENTION_DEFAULT,
    FSRS_RETENTION_EXAM,
    FSRS_RETENTION_LARGE_SET,
    FSRS_W,
    MC_STABILITY_GAIN_CAP,
)

W = FSRS_W
_DECAY = W[20]
_STABILITY_R = 0.9  # R(t = S) by the definition of stability (spec §3.2)
FACTOR = _STABILITY_R ** (-1 / _DECAY) - 1
_D_MIN, _D_MAX = 1.0, 10.0


class Rating(IntEnum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


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


# --- state transition -------------------------------------------------------


def _clamp_d(d: float) -> float:
    return min(_D_MAX, max(_D_MIN, d))


def _check_rating(rating: int) -> int:
    try:
        g = int(rating)
    except (TypeError, ValueError):
        raise ValueError(f"rating must be 1..4, got {rating!r}") from None
    if g != rating or g not in (Rating.AGAIN, Rating.HARD, Rating.GOOD, Rating.EASY):
        raise ValueError(f"rating must be 1..4, got {rating!r}")
    return g


def _check_difficulty(d: float) -> None:
    # `not a <= d <= b` also rejects NaN.
    if not _D_MIN <= d <= _D_MAX:
        raise ValueError(f"difficulty must be in [{_D_MIN}, {_D_MAX}], got {d}")


def initial_stability(rating: int) -> float:
    """S0(G) = w[G−1]."""
    return W[_check_rating(rating) - 1]


def initial_difficulty(rating: int) -> float:
    """D0(G) = clamp(w4 − e^(w5·(G−1)) + 1, 1, 10)."""
    g = _check_rating(rating)
    return _clamp_d(W[4] - math.exp(W[5] * (g - 1)) + 1)


def _next_difficulty(d: float, g: int) -> float:
    """ΔD = −w6·(G−3); D' = D + ΔD·(10−D)/9; D'' = w7·D0(4) + (1−w7)·D'."""
    delta = -W[6] * (g - Rating.GOOD)
    d_prime = d + delta * (_D_MAX - d) / (_D_MAX - _D_MIN)
    d_pp = W[7] * initial_difficulty(Rating.EASY) + (1 - W[7]) * d_prime
    return _clamp_d(d_pp)


def _stability_recall(d: float, s: float, r: float, g: int) -> float:
    hard = W[15] if g == Rating.HARD else 1.0
    easy = W[16] if g == Rating.EASY else 1.0
    growth = (
        math.exp(W[8])
        * (_D_MAX + 1 - d)
        * s ** (-W[9])
        * (math.exp(W[10] * (1 - r)) - 1)
        * hard
        * easy
    )
    return s * (growth + 1)


def _stability_lapse(d: float, s: float, r: float) -> float:
    return W[11] * d ** (-W[12]) * ((s + 1) ** W[13] - 1) * math.exp(W[14] * (1 - r))


def _stability_same_day(s: float, g: int) -> float:
    return s * math.exp(W[17] * (g - Rating.GOOD + W[18])) * s ** (-W[19])


def next_state(
    d: float | None,
    s: float | None,
    rating: int,
    days_since: float,
    *,
    same_day: bool = False,
    mc_unassisted: bool = False,
) -> tuple[float, float]:
    """(D', S') after one rating. ``d``/``s`` None → first rating (D0, S0).

    ``same_day`` selects S_same_day; otherwise Again selects S_lapse and
    Hard/Good/Easy select S_recall, all at R = retrievability(days_since, s).
    ``mc_unassisted`` caps S' at S·MC_STABILITY_GAIN_CAP (spec §3.2 rating map).
    The difficulty update runs for every non-first rating. Nothing is scheduled
    here: the caller turns S' into a due date with ``interval``.
    """
    g = _check_rating(rating)
    if d is None or s is None:
        return initial_difficulty(g), initial_stability(g)
    _check_difficulty(d)
    r = retrievability(days_since, s)  # validates days_since and s
    new_d = _next_difficulty(d, g)
    if same_day:
        new_s = _stability_same_day(s, g)
    elif g == Rating.AGAIN:
        new_s = _stability_lapse(d, s, r)
    else:
        new_s = _stability_recall(d, s, r, g)
    if mc_unassisted:
        new_s = min(new_s, s * MC_STABILITY_GAIN_CAP)
    return new_d, new_s
