"""Probe phase (spec §3.3 probe band, §3.4 limits). Pure: no agents/db imports.

Picks the next check item whose expected success under the current belief
sits in the probe band, stops when belief stabilises, and detects the
novice floor. Items arrive through a Protocol so this module never depends
on the check-item module; the format -> channel map arrives as an argument
(PKG-05 owns CHANNEL_FOR_FORMAT in agents/tools/check.py, which this module
may not import — invariant 2 — and no second map is defined here);
observations are JSON dicts because they live in sessions.loop_state.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol, TypedDict

from learning.params import (
    CHANNELS,
    NOVICE_FLOOR_IDK,
    NOVICE_FLOOR_MISSES,
    PROBE_DIFFICULTY_SHIFT,
    PROBE_EASIEST_DIFFICULTY,
    PROBE_ITEMS_PER_SKILL_MAX,
    PROBE_ITEMS_PER_SKILL_MIN,
    PROBE_SESSION_CAP,
    PROBE_STOP_DELTA,
    PROBE_TARGET_HI,
    PROBE_TARGET_LO,
)


class ProbeItem(Protocol):
    """What the probe needs of a check item. The route binds each item to the
    student's node_id (A2: stored items key on concept_key, not node_id)."""

    id: str
    node_id: str
    format: str
    difficulty: int
    question_hash: str


class ProbeObservation(TypedDict):
    node_id: str
    question_hash: str
    difficulty: int
    channel: str  # always the item's channel (A1: no "idk" channel)
    correct: bool
    idk: bool  # explicit "I don't know" (A1)
    p_after: float


def expected_success(p_known: float, item_difficulty: int, channel: str) -> float:
    """P(correct) for one item: difficulty-shifted belief through the channel's
    BKT observation likelihood p·(1 − S) + (1 − p)·G (spec §3.1) — the same
    formula chance-corrects mc. An unknown channel raises KeyError."""
    row = CHANNELS[channel]
    g, s = float(row["G"]), float(row["S"])
    p = max(0.0, min(1.0, p_known + PROBE_DIFFICULTY_SHIFT[item_difficulty]))
    return p * (1.0 - s) + (1.0 - p) * g


def next_probe_item(
    states: dict[str, float],
    items: Sequence[ProbeItem],
    asked_hashes: Iterable[str],
    *,
    channel_for_format: Mapping[str, str],
    asked_per_node: Mapping[str, int] | None = None,
) -> ProbeItem | None:
    """The unasked item closest to the probe-band midpoint, in-band preferred;
    ties break on (difficulty, question_hash). Respects PROBE_ITEMS_PER_SKILL_MAX
    per node and PROBE_SESSION_CAP. Pass the full candidate list (asked items
    included) so per-node counts are right; the caller has already removed items
    that must never be served (post-test reserve, unavailable, unservable).
    channel_for_format is PKG-05's CHANNEL_FOR_FORMAT. `asked_per_node` is the
    caller's own count of asked items per node (its recorded observations); when
    given it replaces the count over `items`, so an asked item that has since
    left the list (withdrawn) still counts toward the per-skill cap."""
    asked = set(asked_hashes)
    if len(asked) >= PROBE_SESSION_CAP:
        return None
    per_node: Counter[str] = (
        Counter(dict(asked_per_node))
        if asked_per_node is not None
        else Counter(it.node_id for it in items if it.question_hash in asked)
    )
    mid = (PROBE_TARGET_LO + PROBE_TARGET_HI) / 2.0
    in_band: list[tuple[tuple[float, int, str], ProbeItem]] = []
    near: list[tuple[tuple[float, int, str], ProbeItem]] = []
    for it in items:
        if it.question_hash in asked or it.node_id not in states:
            continue
        if per_node[it.node_id] >= PROBE_ITEMS_PER_SKILL_MAX:
            continue
        channel = channel_for_format.get(it.format)
        if channel is None or it.difficulty not in PROBE_DIFFICULTY_SHIFT:
            continue
        es = expected_success(states[it.node_id], it.difficulty, channel)
        key = (abs(es - mid), it.difficulty, it.question_hash)
        (in_band if PROBE_TARGET_LO <= es <= PROBE_TARGET_HI else near).append((key, it))
    pool = in_band or near
    if not pool:
        return None
    return min(pool, key=lambda pair: pair[0])[1]


def novice_floor(history: Sequence[ProbeObservation]) -> bool:
    """Spec §3.3 last bullet, session-wide: NOVICE_FLOOR_MISSES not-correct
    answers (an idk counts) at the easiest difficulty, or NOVICE_FLOOR_IDK idks."""
    misses_easiest = sum(
        1 for h in history if h["difficulty"] == PROBE_EASIEST_DIFFICULTY and not h["correct"]
    )
    idks = sum(1 for h in history if h.get("idk", False))
    return misses_easiest >= NOVICE_FLOOR_MISSES or idks >= NOVICE_FLOOR_IDK


def probe_done(
    history: Sequence[ProbeObservation],
    *,
    skills: Iterable[str] | None = None,
) -> bool:
    """Session cap, novice floor, or every skill (history's nodes plus `skills`)
    capped (≥ MAX items) or stabilised (≥ MIN items and the last two posteriors
    within PROBE_STOP_DELTA). Empty history → False."""
    if not history:
        return False
    if len(history) >= PROBE_SESSION_CAP or novice_floor(history):
        return True
    by_node: dict[str, list[float]] = defaultdict(list)
    for h in history:
        by_node[h["node_id"]].append(float(h["p_after"]))
    required = set(by_node) | (set(skills) if skills is not None else set())
    for node_id in required:
        ps = by_node.get(node_id, [])
        if len(ps) >= PROBE_ITEMS_PER_SKILL_MAX:
            continue
        if len(ps) >= PROBE_ITEMS_PER_SKILL_MIN and abs(ps[-1] - ps[-2]) < PROBE_STOP_DELTA:
            continue
        return False
    return True
