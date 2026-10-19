"""Adaptive, unaided floor/ceiling diagnosis. Pure: no agents/db imports.

Beliefs choose an initial challenge, but never establish a diagnostic boundary.
Only explicitly independent observations can do that. Assisted and legacy
observations still consume the finite fatigue budget. Items arrive through a
Protocol and their format/channel map is supplied by the caller.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import NotRequired, Protocol, TypedDict

from learning.params import (
    CHANNELS,
    NOVICE_FLOOR_IDK,
    NOVICE_FLOOR_MISSES,
    PROBE_DIFFICULTY_SHIFT,
    PROBE_EASIEST_DIFFICULTY,
    PROBE_ITEMS_PER_SKILL_MAX,
    PROBE_ITEMS_PER_SKILL_MIN,
    PROBE_SESSION_CAP,
    PROBE_TARGET_HI,
    PROBE_TARGET_LO,
)


class ProbeItem(Protocol):
    """The caller binds a stored check item to the student's node_id."""

    id: str
    node_id: str
    format: str
    difficulty: int
    question_hash: str


class ProbeObservation(TypedDict):
    node_id: str
    question_hash: str
    difficulty: int
    channel: str
    correct: bool
    idk: bool
    p_after: float
    # Missing in old saved sessions: unknown help provenance is not unaided.
    independent: NotRequired[bool]


def expected_success(p_known: float, item_difficulty: int, channel: str) -> float:
    """Difficulty-shifted BKT likelihood; only a starting-item heuristic."""
    row = CHANNELS[channel]
    g, s = float(row["G"]), float(row["S"])
    p = max(0.0, min(1.0, p_known + PROBE_DIFFICULTY_SHIFT[item_difficulty]))
    return p * (1.0 - s) + (1.0 - p) * g


def _valid_difficulty(value: object) -> bool:
    # bool and float compare equal to integer levels; neither is a stored level.
    return type(value) is int and value in PROBE_DIFFICULTY_SHIFT


def _graded_outcome(observation: Mapping) -> bool | None:
    """Missing/ambiguous grading is not an incorrect student answer."""
    refused = observation.get("refused", False)
    if (
        observation.get("unavailable", False) is not False
        or observation.get("graded", True) is not True
        or (refused is not False and refused is not None and refused != "")
    ):
        return None
    correct, idk = observation.get("correct"), observation.get("idk", False)
    if type(correct) is not bool or type(idk) is not bool:
        return None
    # Explicit unknown overrides a stray correct=True in an old record.
    return False if idk else correct


def independent_observations(history: Sequence[ProbeObservation]) -> list[ProbeObservation]:
    """Distinct first exposures with valid unaided outcomes, across all strands.

    Saved history is plain JSON, not a validated evidence model. An explicit
    independent flag cannot overrule contradictory help/recheck/outage metadata.
    A later repeat is not fresh evidence, even if the first exposure was assisted
    or belonged to a previous goal. Raw rows still count toward fatigue limits.
    """
    seen: set[str] = set()
    independent = []
    for observation in history:
        if not isinstance(observation, Mapping):
            continue
        question_hash = observation.get("question_hash")
        if not isinstance(question_hash, str) or not question_hash.strip() or question_hash in seen:
            continue
        seen.add(question_hash)
        node_id, channel = observation.get("node_id"), observation.get("channel")
        if (
            observation.get("independent") is not True
            or not isinstance(node_id, str)
            or not node_id.strip()
            or not isinstance(channel, str)
            or channel not in CHANNELS
            or not _valid_difficulty(observation.get("difficulty"))
            or _graded_outcome(observation) is None
        ):
            continue
        if "max_rung" in observation and (
            type(observation["max_rung"]) is not int or observation["max_rung"] != 0
        ):
            continue
        if any(
            observation.get(flag, False) is not False
            for flag in (
                "same_session_recheck",
                "synthetic_idk",
                "previously_seen",
            )
        ):
            continue
        independent.append(observation)
    return independent


def _by_node(history: Sequence[ProbeObservation]) -> dict[str, list[ProbeObservation]]:
    grouped: dict[str, list[ProbeObservation]] = defaultdict(list)
    for observation in history:
        if isinstance(observation, Mapping) and isinstance(observation.get("node_id"), str):
            grouped[observation["node_id"]].append(observation)
    return grouped


def _evidence(history: Sequence[ProbeObservation]) -> tuple[list[int], list[int]]:
    correct, incorrect = [], []
    for observation in independent_observations(history):
        (correct if _graded_outcome(observation) else incorrect).append(observation["difficulty"])
    return correct, incorrect


def _bracketed(history: Sequence[ProbeObservation]) -> bool:
    correct, incorrect = _evidence(history)
    return bool(
        len(correct) + len(incorrect) >= PROBE_ITEMS_PER_SKILL_MIN
        and correct
        and incorrect
        and max(correct) < min(incorrect)
    )


def _difficulty_key(
    difficulty: int,
    available: set[int],
    correct: list[int],
    incorrect: list[int],
    released: set[int],
) -> tuple[float, ...]:
    """Challenge the missing side, bisect a boundary, or retest a contradiction.

    Conflicting observations are not averaged away as a supposed slip. Further
    items expose uncertainty, but cannot make conflicting evidence a confident
    boundary.
    """
    counts = Counter(correct + incorrect)
    if correct and incorrect:
        floor, ceiling = max(correct), min(incorrect)
        if floor >= ceiling:
            disputed = {d for d in correct + incorrect if ceiling <= d <= floor}
            return (
                0 if difficulty in disputed else 1,
                counts[difficulty],
                min(abs(difficulty - d) for d in disputed),
            )
        # A released shape cannot supply fresh unaided evidence, even when the
        # miss itself was assisted and therefore does not narrow the boundary.
        interior = {d for d in available if floor < d < ceiling and d not in released}
        if interior:
            return (0 if difficulty in interior else 1, abs(difficulty - (floor + ceiling) / 2))
        # A wrong answer releases its reference and makes the next concept
        # check a recheck. Repeating the failed ceiling's shape can remain an
        # owed isomorph, adding no independent evidence. Once there is no
        # fresh interior level to bisect, confirm with novel floor-level
        # examples until MIN is met; the observed ceiling is established.
        fresh_floors = {d for d in available if d <= floor and d not in released}
        target = max(fresh_floors) if fresh_floors else floor
        return (
            0 if difficulty in fresh_floors else 1,
            abs(difficulty - target),
            counts[difficulty],
        )
    if correct:
        harder = {d for d in available if d > max(correct)}
        target = max(harder) if harder else max(available)
        return (abs(difficulty - target), counts[difficulty])
    if incorrect:
        easier = {d for d in available if d < min(incorrect)}
        target = min(easier) if easier else min(available)
        return (abs(difficulty - target), counts[difficulty])
    return ()


def next_probe_item(
    states: dict[str, float],
    items: Sequence[ProbeItem],
    asked_hashes: Iterable[str],
    *,
    channel_for_format: Mapping[str, str],
    asked_per_node: Mapping[str, int] | None = None,
    history: Sequence[ProbeObservation] | None = None,
) -> ProbeItem | None:
    """Pick a novel item fairly across eligible, unfinished skill strands.

    Least-observed strands go first so one attractive band cannot exhaust the
    session before another skill is tested. Unaided evidence then drives harder,
    easier or bisecting challenges. The belief band is an initial heuristic.

    Pass all eligible items, including asked ones. Explicit observation counts
    include withdrawn items; history/counts can only increase fatigue counts.
    Old callers without history retain the starting-item heuristic and caps.
    """
    history = history or []
    asked = set(asked_hashes) | {
        h["question_hash"]
        for h in history
        if isinstance(h, Mapping) and isinstance(h.get("question_hash"), str)
    }
    by_node = _by_node(history)
    independent_by_node = _by_node(independent_observations(history))
    # Duplicate bank bindings for one prompt are not extra presentations.
    asked_by_node: dict[str, set[str]] = defaultdict(set)
    for it in items:
        if it.question_hash in asked:
            asked_by_node[it.node_id].add(it.question_hash)
    per_node = Counter({node: len(hashes) for node, hashes in asked_by_node.items()})
    for node_id, count in (asked_per_node or {}).items():
        per_node[node_id] = max(per_node[node_id], count)
    for node_id, observations in by_node.items():
        per_node[node_id] = max(per_node[node_id], len(observations))
    if max(len(asked), len(history), sum(per_node.values())) >= PROBE_SESSION_CAP or novice_floor(
        history
    ):
        return None

    candidates: dict[str, list[ProbeItem]] = defaultdict(list)
    for it in items:
        if (
            it.question_hash not in asked
            and it.node_id in states
            and per_node[it.node_id] < PROBE_ITEMS_PER_SKILL_MAX
            and not _bracketed(independent_by_node[it.node_id])
            and channel_for_format.get(it.format) in CHANNELS
            and _valid_difficulty(it.difficulty)
        ):
            candidates[it.node_id].append(it)
    if not candidates:
        return None

    # Choose the strand before comparing different kinds of adaptive keys.
    node_id = min(candidates, key=lambda n: (per_node[n], n))
    correct, incorrect = _evidence(independent_by_node[node_id])
    # Selection may avoid contaminated shapes using assisted misses too;
    # _evidence above still excludes them from all diagnostic claims.
    released = {
        h["difficulty"]
        for h in by_node[node_id]
        if _valid_difficulty(h.get("difficulty")) and _graded_outcome(h) is False
    }
    available = {it.difficulty for it in candidates[node_id]}
    mid = (PROBE_TARGET_LO + PROBE_TARGET_HI) / 2

    def rank(it: ProbeItem) -> tuple:
        es = expected_success(states[node_id], it.difficulty, channel_for_format[it.format])
        return (
            _difficulty_key(it.difficulty, available, correct, incorrect, released),
            0 if PROBE_TARGET_LO <= es <= PROBE_TARGET_HI else 1,
            abs(es - mid),
            it.difficulty,
            it.question_hash,
        )

    return min(candidates[node_id], key=rank)


def novice_floor(history: Sequence[ProbeObservation]) -> bool:
    """A session-wide fatigue stop, not proof of a skill's diagnostic floor.

    Legacy/assisted answers count toward exhaustion but never toward a boundary.
    """
    misses_easiest = sum(
        1
        for h in history
        if isinstance(h, Mapping)
        and _valid_difficulty(h.get("difficulty"))
        and h["difficulty"] == PROBE_EASIEST_DIFFICULTY
        and _graded_outcome(h) is False
    )
    idks = sum(
        1
        for h in history
        if isinstance(h, Mapping) and h.get("idk") is True and _graded_outcome(h) is not None
    )
    return misses_easiest >= NOVICE_FLOOR_MISSES or idks >= NOVICE_FLOOR_IDK


def diagnostic_summary(
    history: Sequence[ProbeObservation],
    *,
    skills: Iterable[str],
    stop_reason: str | None = None,
    available_difficulties: Mapping[str, Iterable[int]] | None = None,
) -> dict:
    """Describe evidence separately from a finite reason to stop.

    `skills` selects the current goal's strands; old goal observations still
    consume global fatigue but do not leak into this summary. Range labels need
    explicit item-bank coverage and MIN unaided observations. Without coverage,
    a missing side remains partial rather than an invented bound.
    """
    by_node = _by_node(history)
    independent_by_node = _by_node(independent_observations(history))
    rows = []
    for node_id in sorted(set(skills)):
        observations = by_node[node_id]
        independent_history = independent_by_node[node_id]
        correct, incorrect = _evidence(independent_history)
        floor = max(correct) if correct else None
        ceiling = min(incorrect) if incorrect else None
        coverage = sorted(
            {d for d in (available_difficulties or {}).get(node_id, []) if _valid_difficulty(d)}
        )
        independent = len(correct) + len(incorrect)
        contradictory = sorted(
            {d for d in correct + incorrect if ceiling <= d <= floor}
            if floor is not None and ceiling is not None and floor >= ceiling
            else set()
        )
        if not independent:
            status = "untested"
        elif contradictory:
            status = "inconsistent"
        elif _bracketed(independent_history):
            status = "bracketed"
        elif (
            independent >= PROBE_ITEMS_PER_SKILL_MIN
            and coverage
            and not incorrect
            and floor >= max(coverage)
        ):
            status = "above_range"
        elif (
            independent >= PROBE_ITEMS_PER_SKILL_MIN
            and coverage
            and not correct
            and ceiling <= min(coverage)
        ):
            status = "below_range"
        else:
            status = "partial"
        rows.append(
            {
                "node_id": node_id,
                "status": status,
                "floor_difficulty": floor,
                "ceiling_difficulty": ceiling,
                "independent_correct": len(correct),
                "independent_incorrect": len(incorrect),
                "independent_observations": independent,
                "observations": len(observations),
                "tested_difficulties": sorted(set(correct + incorrect)),
                "available_difficulties": coverage,
                "contradictory_difficulties": contradictory,
            }
        )

    all_bracketed = bool(rows) and all(r["status"] == "bracketed" for r in rows)
    if stop_reason is None:
        if len(history) >= PROBE_SESSION_CAP:
            stop_reason = "session_cap"
        elif novice_floor(history):
            stop_reason = "novice_floor"
        elif all_bracketed:
            stop_reason = "observed_boundaries"
        elif rows and all(
            r["status"] == "bracketed" or r["observations"] >= PROBE_ITEMS_PER_SKILL_MAX
            for r in rows
        ):
            stop_reason = "per_skill_cap"
    if all_bracketed:
        status = "bracketed"
    elif not any(r["independent_observations"] for r in rows):
        status = "not_assessed"
    elif stop_reason is not None:
        status = "limited"
    else:
        status = "in_progress"
    return {"status": status, "stop_reason": stop_reason, "skills": rows}


def probe_done(
    history: Sequence[ProbeObservation],
    *,
    skills: Iterable[str] | None = None,
    available_difficulties: Mapping[str, Iterable[int]] | None = None,
) -> bool:
    """Stop for observed boundaries after MIN evidence, or finite fatigue caps.

    Posterior stability and all-correct runs never prove a ceiling. Old sessions
    remain bounded even though they cannot establish unaided evidence.
    """
    if not history:
        return False
    required = set(skills) if skills is not None else set(_by_node(history))
    summary = diagnostic_summary(
        history, skills=required, available_difficulties=available_difficulties
    )
    return summary["stop_reason"] is not None
