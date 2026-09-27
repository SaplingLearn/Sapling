"""Bayesian Knowledge Tracing core (spec §3.1). Pure: stdlib + learning.params.

Only graded checks change what Sapling believes a student knows (spec §1).
This module is the arithmetic of that belief: van de Sande's closed-form
update with a separate guess/slip pair per evidence channel, decay toward the
prior along the FSRS-6 forgetting curve at read time, one-hop asymmetric
prerequisite propagation, and the band/tier cuts. It never touches the
database, the graph, or an agent; PKG-03's apply_graph_update calls it.
"""

from __future__ import annotations

import math
from typing import Literal

from learning.params import (
    BAND_DEVELOP_MAX,
    BAND_NOVICE_MAX,
    BKT_L0,
    BKT_MASTERED,
    BKT_MASTERED_MIN_STRONG,
    BKT_P_MAX,
    BKT_PROFICIENT,
    BKT_T,
    CHANNELS,
    FSRS_S0_GOOD,
    FSRS_W,
    PROPAGATION_CHANNEL,
    S_IDK,
    TIER_UNEXPLORED_MAX,
    WEIGHT_PROPAGATION,
)

Band = Literal["novice", "develop", "profic"]
Tier = Literal["unexplored", "struggling", "learning", "mastered"]
Propagation = tuple[str, str, bool, float]  # (node_id, channel, correct, weight)

_FULL_WEIGHT = 1.0
_P_MIN = 0.0
_P_MAX = 1.0


def _posterior(p: float, g: float, s: float, correct: bool) -> float:
    """Observation-only Bayes step (spec §3.1 `correct:` / `incorrect:` lines)."""
    if correct:
        num = p * (1.0 - s)
        den = num + (1.0 - p) * g
    else:
        num = p * s
        den = num + (1.0 - p) * (1.0 - g)
    if den == 0.0:  # only reachable at p in {0, 1} with a degenerate g/s; keep p
        return p
    return num / den


def _clamp01(x: float) -> float:
    return min(_P_MAX, max(_P_MIN, x))


def _check_p(p: float) -> None:
    """Spec §Error semantics: a belief outside [0, 1] is a programming error.
    The chained comparison is False for NaN, so NaN raises too."""
    if not _P_MIN <= p <= _P_MAX:
        raise ValueError(f"p must be in [0, 1], got {p}")


def update(
    p: float,
    channel: str,
    correct: bool,
    *,
    weight: float = _FULL_WEIGHT,
    idk: bool = False,
) -> float:
    """One BKT opportunity (spec §3.1).

    P' = P + weight·(P_post − P); learn step P'' = P' + (1 − P')·BKT_T only
    when weight == 1.0. idk=True is an incorrect observation with the item
    channel's G and S_IDK (`correct` is ignored). `channel` must be a key of
    CHANNELS; "idk" is the flag, not a channel.

    The result is capped at BKT_P_MAX (†): at p == 1.0 the incorrect posterior
    is 1, so a belief that rounded up to 1.0 could never be lowered again. Any
    p in [0, 1] is still a valid input; one above the cap comes back at it.
    """
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}; idk is the idk=True flag, not a channel")
    _check_p(p)
    if not _P_MIN <= weight <= _FULL_WEIGHT:
        raise ValueError(f"weight must be in [0, 1], got {weight}")
    row = CHANNELS[channel]
    g = float(row["G"])
    s = S_IDK if idk else float(row["S"])
    observed = False if idk else bool(correct)
    p_post = _posterior(p, g, s, observed)
    p_new = p + weight * (p_post - p)
    if weight == _FULL_WEIGHT:
        p_new = p_new + (1.0 - p_new) * BKT_T
    return min(BKT_P_MAX, _clamp01(p_new))


# Spec §3.2 retrievability, reproduced privately so PKG-01 and PKG-02 can merge
# in either order. PKG-03 may replace the body with `learning.fsrs.retrievability`
# once both are on main; keep the name so decayed_p does not change.
_W20 = FSRS_W[20]
_FSRS_FACTOR = 0.9 ** (-1.0 / _W20) - 1.0


def _retrievability(t: float, s: float) -> float:
    """R(t, S) = (1 + factor·t/S)^(−w20); R(S, S) = 0.9 by construction."""
    return (1.0 + _FSRS_FACTOR * t / s) ** (-_W20)


def decayed_p(p_stored: float, days_since: float, stability: float | None) -> float:
    """Decay-at-read (spec §3.1): P_now = L0 + (P_stored − L0)·R(Δt, S_c).

    stability None → FSRS_S0_GOOD (no FSRS state yet); otherwise it must be
    finite and > 0. Negative days_since (clock skew) reads as 0, +inf gives
    the prior, NaN raises. The prior is a fixed point; every other p moves
    toward it from its own side and never crosses. p_stored outside [0, 1]
    raises.
    """
    _check_p(p_stored)
    s_c = FSRS_S0_GOOD if stability is None else stability
    if not (s_c > 0.0 and math.isfinite(s_c)):  # `not >` also rejects NaN
        raise ValueError(f"stability must be finite and > 0, got {stability}")
    if math.isnan(days_since):
        raise ValueError(f"days_since must be a number, got {days_since}")
    t = max(0.0, days_since)
    if t == 0.0:
        return p_stored
    return _clamp01(BKT_L0 + (p_stored - BKT_L0) * _retrievability(t, s_c))


def propagate_prereq(
    evidence_correct: bool, parents: list[str], children: list[str]
) -> list[Propagation]:
    """One-hop asymmetric propagation (spec §3.1).

    correct at c   → each prerequisite parent gets a PROPAGATION_CHANNEL-strength
                     correct observation at WEIGHT_PROPAGATION; children untouched.
    incorrect at c → each dependent child gets the incorrect observation; parents
                     untouched (an error can be local).
    The caller resolves parents/children from graph_edges using
    EDGE_PREREQ_SOURCE_IS_PREREQ; this function never sees an edge.
    """
    targets = parents if evidence_correct else children
    return [
        (node_id, PROPAGATION_CHANNEL, bool(evidence_correct), WEIGHT_PROPAGATION)
        for node_id in targets
    ]


def band(p: float) -> Band:
    """Spec §3.1 / ZPD STATE block: novice < BAND_NOVICE_MAX ≤ develop < BAND_DEVELOP_MAX ≤ profic."""
    _check_p(p)
    if p < BAND_NOVICE_MAX:
        return "novice"
    if p < BAND_DEVELOP_MAX:
        return "develop"
    return "profic"


def tier_for(p: float) -> Tier:
    """Loop-path mirror into graph_nodes.mastery_tier (spec §3.1). Not the legacy
    config.get_mastery_tier, which keeps its own cuts until PKG-14."""
    _check_p(p)
    if p < TIER_UNEXPLORED_MAX:
        return "unexplored"
    if p < BAND_NOVICE_MAX:
        return "struggling"
    if p < BKT_PROFICIENT:
        return "learning"
    return "mastered"


def is_proficient(p: float) -> bool:
    _check_p(p)
    return p >= BKT_PROFICIENT


def is_mastered(p: float, n_strong_unassisted: int) -> bool:
    """Mastered needs the belief AND BKT_MASTERED_MIN_STRONG strong-channel
    unassisted observations (spec §3.1); belief alone is never enough."""
    _check_p(p)
    return p >= BKT_MASTERED and n_strong_unassisted >= BKT_MASTERED_MIN_STRONG
