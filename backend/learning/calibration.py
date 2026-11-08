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

Spec §13 A127 adds the student's side, metacognitive calibration: does the
confidence a student STATES ("Guessing" / "Fairly sure" / "Sure", journaled as
`student_confidence` on the evidence it was stated on) predict whether the
answer was right? `confidence_calibration` reports it per channel. It reads
only rows with a stated confidence; the grader's `confidence` is another
column and never enters it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from learning.params import (
    CALIBRATION_BINS,
    CHANNELS,
    STRONG_CHANNELS,
    STUDENT_CONFIDENCE_LEVELS,
)

_FULL_WEIGHT = 1.0
#: two stated values this close are one level (the journal stores the float)
_LEVEL_TOLERANCE = 1e-9


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


# ── metacognitive calibration (spec §13 A127) ──────────────────────────────


def stated_pair(row: Mapping[str, Any]) -> tuple[float, bool] | None:
    """(stated confidence, observed correct) for an evidence row that carries a
    stated confidence and a boolean outcome, else None. Any graded answer
    counts — helped or not: the student judged the answer they submitted."""
    correct = row.get("correct")
    if not isinstance(correct, bool):
        return None
    stated = _p(row.get("student_confidence"))
    return None if stated is None else (stated, correct)


def confidence_level(stated: float) -> str | None:
    """The STUDENT_CONFIDENCE_LEVELS label a stated value is, or None for a value
    the current mapping does not name (a row stated under an earlier mapping)."""
    return next(
        (
            label
            for label, value in STUDENT_CONFIDENCE_LEVELS.items()
            if abs(value - stated) <= _LEVEL_TOLERANCE
        ),
        None,
    )


def _confidence_summary(pairs: list[tuple[float, bool]]) -> dict:
    """n; the mean stated confidence against the observed correct rate and
    their gap (`overconfidence` = mean stated − observed: above 0, students
    are surer than they are right); the Brier score of the stated value; and
    one row per level — every current level in scale order (n 0 included, its
    rate None), then any value the mapping no longer names (level None). Every
    rate is None when there is nothing to judge — never a zero."""
    n = len(pairs)
    mean_stated = sum(s for s, _ in pairs) / n if n else None
    observed = sum(o for _, o in pairs) / n if n else None
    by_value: dict[float, list[bool]] = {}
    for stated, obs in pairs:
        label = confidence_level(stated)
        key = STUDENT_CONFIDENCE_LEVELS[label] if label is not None else stated
        by_value.setdefault(key, []).append(obs)
    named = list(STUDENT_CONFIDENCE_LEVELS.items())
    unnamed = sorted(v for v in by_value if confidence_level(v) is None)
    levels = []
    for label, value in [*named, *((None, v) for v in unnamed)]:
        outcomes = by_value.get(value, [])
        k = len(outcomes)
        levels.append(
            {
                "level": label,
                "stated": value,
                "n": k,
                "correct": sum(outcomes),
                "observed": sum(outcomes) / k if k else None,
            }
        )
    return {
        "n": n,
        "mean_stated": mean_stated,
        "observed_rate": observed,
        "overconfidence": mean_stated - observed if n else None,
        "brier": sum((s - float(o)) ** 2 for s, o in pairs) / n if n else None,
        "levels": levels,
    }


def confidence_calibration(rows: Iterable[Mapping[str, Any]]) -> dict:
    """Spec §13 A127: the student's stated confidence against correctness —
    `all`, and `channels`: one summary per evidence channel that has a stated
    confidence in range, in params.CHANNELS order (a channel with none is not
    listed). Pure."""
    everything: list[tuple[float, bool]] = []
    per_channel: dict[str, list[tuple[float, bool]]] = {}
    for row in rows:
        pair = stated_pair(row)
        if pair is None:
            continue
        everything.append(pair)
        per_channel.setdefault(str(row.get("channel")), []).append(pair)
    channels = [
        {"channel": ch, **_confidence_summary(per_channel[ch])}
        for ch in CHANNELS
        if per_channel.get(ch)
    ]
    return {"all": _confidence_summary(everything), "channels": channels}
