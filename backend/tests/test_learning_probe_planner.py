"""PKG-08: probe phase + planner (spec §3.3 probe row, §3.4, §6, §9).
Pure halves use synthetic learner states; route half patches the seams
routes/learn_loop.py exposes for this package."""

from __future__ import annotations

from dataclasses import dataclass

# PKG-05's map; probe.py takes it as an argument (invariant 2 keeps agents out).
from agents.tools.check import CHANNEL_FOR_FORMAT
from learning import params as P


# ── fixtures ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Item:
    id: str
    node_id: str
    format: str
    difficulty: int
    question_hash: str


def _items(node_id: str, n: int, *, difficulty: int = 2, fmt: str = "free") -> list[_Item]:
    return [
        _Item(f"{node_id}-i{k}", node_id, fmt, difficulty, f"h-{node_id}-{k}") for k in range(n)
    ]


def _obs(node_id, p_after, *, correct=True, idk=False, difficulty=2, k=0):
    return {
        "node_id": node_id,
        "question_hash": f"h-{node_id}-{k}",
        "difficulty": difficulty,
        "channel": "free_response",
        "correct": correct,
        "idk": idk,
        "p_after": p_after,
    }


# ── expected_success ────────────────────────────────────────────────────────


def test_expected_success_monotone_in_p():
    from learning.probe import expected_success

    grid = [i / 20 for i in range(21)]
    vals = [expected_success(p, 2, "free_response") for p in grid]
    assert all(a <= b for a, b in zip(vals, vals[1:]))
    assert 0.0 <= min(vals) and max(vals) <= 1.0


def test_easier_items_have_higher_expected_success():
    from learning.probe import expected_success

    p = 0.5
    e1, e2, e3 = (expected_success(p, d, "free_response") for d in (1, 2, 3))
    assert e1 > e2 > e3


def test_mc_is_chance_corrected_by_channel_guess():
    from learning.probe import expected_success

    # A student who knows nothing still "succeeds" at the channel's guess rate.
    assert expected_success(0.0, 2, "mc") > expected_success(0.0, 2, "free_response")


# ── next_probe_item ─────────────────────────────────────────────────────────


def test_choice_is_in_band_and_closest_to_midpoint():
    from learning.probe import expected_success, next_probe_item

    states = {"A": 0.5}
    items = (
        _items("A", 1, difficulty=1) + _items("A", 1, difficulty=2) + _items("A", 1, difficulty=3)
    )
    chosen = next_probe_item(states, items, asked_hashes=[], channel_for_format=CHANNEL_FOR_FORMAT)
    assert chosen is not None
    es = expected_success(states["A"], chosen.difficulty, CHANNEL_FOR_FORMAT[chosen.format])
    mid = (P.PROBE_TARGET_LO + P.PROBE_TARGET_HI) / 2
    in_band = [
        it
        for it in items
        if P.PROBE_TARGET_LO
        <= expected_success(states["A"], it.difficulty, CHANNEL_FOR_FORMAT[it.format])
        <= P.PROBE_TARGET_HI
    ]
    if in_band:
        assert P.PROBE_TARGET_LO <= es <= P.PROBE_TARGET_HI
    best = min(
        items,
        key=lambda it: abs(
            expected_success(states["A"], it.difficulty, CHANNEL_FOR_FORMAT[it.format]) - mid
        ),
    )
    assert chosen.question_hash == best.question_hash


def test_falls_back_to_nearest_when_nothing_is_in_band():
    from learning.probe import next_probe_item

    states = {"A": 0.0}  # every item is below the band
    items = _items("A", 1, difficulty=3) + _items("A", 1, difficulty=1)
    chosen = next_probe_item(states, items, asked_hashes=[], channel_for_format=CHANNEL_FOR_FORMAT)
    assert chosen is not None and chosen.difficulty == P.PROBE_EASIEST_DIFFICULTY


def test_asked_hashes_are_skipped():
    from learning.probe import next_probe_item

    items = _items("A", 2)
    chosen = next_probe_item(
        {"A": 0.5},
        items,
        asked_hashes=[items[0].question_hash],
        channel_for_format=CHANNEL_FOR_FORMAT,
    )
    assert chosen is not None and chosen.question_hash == items[1].question_hash


def test_per_skill_cap():
    from learning.probe import next_probe_item

    items = _items("A", P.PROBE_ITEMS_PER_SKILL_MAX + 2) + _items("B", 1)
    asked = [it.question_hash for it in items if it.node_id == "A"][: P.PROBE_ITEMS_PER_SKILL_MAX]
    chosen = next_probe_item(
        {"A": 0.5, "B": 0.5}, items, asked_hashes=asked, channel_for_format=CHANNEL_FOR_FORMAT
    )
    assert chosen is not None and chosen.node_id == "B"


def test_session_cap_returns_none():
    from learning.probe import next_probe_item

    items = _items("A", P.PROBE_SESSION_CAP + 3)
    asked = [it.question_hash for it in items][: P.PROBE_SESSION_CAP]
    chosen = next_probe_item(
        {"A": 0.5}, items, asked_hashes=asked, channel_for_format=CHANNEL_FOR_FORMAT
    )
    assert chosen is None


def test_unknown_node_and_unknown_format_are_ignored():
    from learning.probe import next_probe_item

    items = _items("Z", 1) + [_Item("x", "A", "essay", 2, "h-x")]
    chosen = next_probe_item(
        {"A": 0.5}, items, asked_hashes=[], channel_for_format=CHANNEL_FOR_FORMAT
    )
    assert chosen is None


# ── probe_done / novice_floor ───────────────────────────────────────────────


def test_probe_done_empty_is_false():
    from learning.probe import probe_done

    assert probe_done([]) is False


def test_stop_rule_needs_min_items_and_stable_posterior():
    from learning.probe import probe_done

    stable = [0.5, 0.55, 0.6, 0.6 + P.PROBE_STOP_DELTA / 2]
    hist = [_obs("A", p, k=i) for i, p in enumerate(stable)]
    assert len(hist) == P.PROBE_ITEMS_PER_SKILL_MIN
    assert probe_done(hist) is True
    moving = stable[:-1] + [stable[-2] + 2 * P.PROBE_STOP_DELTA]
    assert probe_done([_obs("A", p, k=i) for i, p in enumerate(moving)]) is False
    assert probe_done(hist[:-1]) is False  # below MIN


def test_probe_done_at_per_skill_max_even_if_moving():
    from learning.probe import probe_done

    hist = [_obs("A", 0.1 * i, k=i) for i in range(P.PROBE_ITEMS_PER_SKILL_MAX)]
    assert probe_done(hist) is True


def test_probe_done_requires_every_named_skill():
    from learning.probe import probe_done

    hist = [_obs("A", 0.6, k=i) for i in range(P.PROBE_ITEMS_PER_SKILL_MAX)]
    assert probe_done(hist, skills=["A", "B"]) is False
    assert probe_done(hist, skills=["A"]) is True


def test_probe_done_at_session_cap():
    from learning.probe import probe_done

    hist = [_obs(f"N{i}", 0.5, k=i) for i in range(P.PROBE_SESSION_CAP)]
    assert probe_done(hist) is True


def test_novice_floor_misses_at_easiest_difficulty():
    from learning.probe import novice_floor, probe_done

    hist = [
        _obs("A", 0.2, correct=False, difficulty=P.PROBE_EASIEST_DIFFICULTY, k=i)
        for i in range(P.NOVICE_FLOOR_MISSES)
    ]
    assert novice_floor(hist) is True and probe_done(hist) is True
    harder = [dict(h, difficulty=P.PROBE_EASIEST_DIFFICULTY + 1) for h in hist]
    assert novice_floor(harder) is False


def test_novice_floor_repeated_idk():
    from learning.probe import novice_floor

    hist = [
        _obs("A", 0.3, correct=False, idk=True, difficulty=3, k=i)
        for i in range(P.NOVICE_FLOOR_IDK)
    ]
    assert novice_floor(hist) is True
    assert novice_floor(hist[:-1]) is False
