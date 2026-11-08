"""BKT calibration against unassisted outcomes (docs/research/learning-loop/
2026-11-07-direction-audit.md, rec. 2/4: validate the learner model against delayed,
tool-free performance instead of trusting it). Pure: stdlib + learning.params.

Every evidence row journals the belief BEFORE its update (`p_before`, the
decayed read) next to the observed outcome. For an unassisted, full-weight,
rung-0 observation on a strong channel, BKT's own emission model says the
answer is correct with probability

    P(correct) = p·(1 − S) + (1 − p)·G

for the channel's guess G and slip S. Comparing that prediction with what
happened is the calibration check: a well-calibrated model's 0.8 predictions
come true about 80% of the time. Assisted, rechecked (weight < 1), propagated
or helped (rung > 0) rows are not independent observations and are left out —
the same exclusions the mastery gate applies (bkt.is_mastered counts only
strong unassisted evidence).

The post-test subset (no session, strong channel) is the cleanest signal: a
fresh reserve item, at a fixed window (POSTTEST_WINDOWS_DAYS) after the
concept's first graded evidence (spec §13 A112), graded with no tutor, RAG or
brief. Its calibration is the rung-3 validity check of `p_known` itself.

Nothing here writes, gates or changes belief. It is a report for the admin KPI.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from learning.params import CALIBRATION_BINS, CHANNELS, STRONG_CHANNELS

_FULL_WEIGHT = 1.0


def predicted_correct(p_known: float, channel: str) -> float:
    """BKT's emission probability of a correct answer on `channel` given the
    belief `p_known`: p·(1 − S) + (1 − p)·G."""
    ch = CHANNELS[channel]
    g, s = float(ch["G"]), float(ch["S"])
    return p_known * (1.0 - s) + (1.0 - p_known) * g


def _rung(value: Any) -> int | None:
    """A journaled rung (int 0..6, or "H0".."H6") as an int; None otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value[:1] in ("H", "h") and value[1:].isdigit():
        return int(value[1:])
    return None


def _p(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    p = float(value)
    return p if 0.0 <= p <= 1.0 else None


def eligible(row: Mapping[str, Any]) -> tuple[float, bool] | None:
    """(predicted P(correct), observed correct) for an independent observation,
    else None. Independent = strong channel, unassisted, rung 0, full weight,
    a readable p_before and a boolean outcome."""
    channel = row.get("channel")
    if channel not in STRONG_CHANNELS:
        return None
    correct = row.get("correct")
    if not isinstance(correct, bool):
        return None
    if row.get("assisted") or _rung(row.get("max_rung")) != 0:
        return None
    weight = row.get("weight")
    if weight is not None and (isinstance(weight, bool) or not isinstance(weight, (int, float))
                               or float(weight) < _FULL_WEIGHT):
        return None
    p = _p(row.get("p_before"))
    if p is None:
        return None
    return predicted_correct(p, channel), correct


def is_posttest(row: Mapping[str, Any]) -> bool:
    """A post-test evidence row: no session (posttest grades carry none) on a
    strong channel. Quiz evidence also has no session but is always `mc`, never
    strong, so it cannot match."""
    return not row.get("session_id") and row.get("channel") in STRONG_CHANNELS


def summarize(pairs: Iterable[tuple[float, bool]], bins: int = CALIBRATION_BINS) -> dict:
    """Brier score, mean prediction vs observed rate, expected calibration error
    (bin-weighted |observed − predicted|) and the reliability bins. Every rate is
    None when there is nothing to judge — never a zero that reads as a result."""
    pairs = list(pairs)
    n = len(pairs)
    edges = [i / bins for i in range(bins + 1)]
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for pred, obs in pairs:
        idx = min(int(pred * bins), bins - 1)
        buckets[idx].append((pred, obs))
    out_bins = []
    ece = 0.0
    for i, bucket in enumerate(buckets):
        k = len(bucket)
        mean_pred = sum(p for p, _ in bucket) / k if k else None
        observed = sum(o for _, o in bucket) / k if k else None
        if k:
            ece += (k / n) * abs(observed - mean_pred)
        out_bins.append(
            {"lo": edges[i], "hi": edges[i + 1], "n": k,
             "mean_predicted": mean_pred, "observed": observed}
        )
    return {
        "n": n,
        "brier": sum((p - float(o)) ** 2 for p, o in pairs) / n if n else None,
        "mean_predicted": sum(p for p, _ in pairs) / n if n else None,
        "observed_rate": sum(o for _, o in pairs) / n if n else None,
        "ece": ece if n else None,
        "bins": out_bins,
    }


def calibration(rows: Iterable[Mapping[str, Any]]) -> dict:
    """`all`: every independent observation; `posttest`: the post-test subset."""
    everything: list[tuple[float, bool]] = []
    posttest: list[tuple[float, bool]] = []
    for row in rows:
        pair = eligible(row)
        if pair is None:
            continue
        everything.append(pair)
        if is_posttest(row):
            posttest.append(pair)
    return {"all": summarize(everything), "posttest": summarize(posttest)}
