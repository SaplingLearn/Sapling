"""Bayesian Knowledge Tracing core (spec §3.1). Pure: stdlib + learning.params.

Only graded checks change what Sapling believes a student knows (spec §1).
This module is the arithmetic of that belief: van de Sande's closed-form
update with a separate guess/slip pair per evidence channel, decay toward the
prior along the FSRS-6 forgetting curve at read time, one-hop asymmetric
prerequisite propagation, and the band/tier cuts. It never touches the
database, the graph, or an agent; PKG-03's apply_graph_update calls it.
"""

from __future__ import annotations

from learning.params import BKT_T, CHANNELS, S_IDK

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
    """
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}; idk is the idk=True flag, not a channel")
    if not _P_MIN <= p <= _P_MAX:
        raise ValueError(f"p must be in [0, 1], got {p}")
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
    return _clamp01(p_new)
