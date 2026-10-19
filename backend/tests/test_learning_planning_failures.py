"""Failed practice blocks goal readiness without certifying a diagnosis."""

import pytest

from learning import bkt, goals, planner
from learning.evidence import Evidence
from learning.params import BKT_PROFICIENT
from learning.probe import independent_observations


def observation(key, *, correct=False, difficulty=3, **extra):
    return {
        "node_id": "A",
        "question_hash": key,
        "difficulty": difficulty,
        "channel": "free_response",
        "correct": correct,
        "idk": False,
        "independent": False,
        "max_rung": 2,
        "same_session_recheck": False,
        "previously_seen": False,
        "synthetic_idk": False,
        **extra,
    }


@pytest.mark.parametrize(
    "prior,channel,confidence", [(0.999, "free_response", 0.9), (0.99, "teachback_llm", 0.5)]
)
def test_actual_weighted_wrong_checks_cannot_unlock_dependent_from_old_high_prior(
    prior, channel, confidence
):
    p = prior
    history = []
    for index, recheck in enumerate((False, True)):
        evidence = Evidence(
            node_id="A",
            channel=channel,
            correct=False,
            max_rung=2,
            same_session_recheck=recheck,
            confidence=confidence,
        )
        p = bkt.update(p, evidence.channel, evidence.correct, weight=evidence.weight)
        history.append(observation(f"check-{index}", channel=channel, same_session_recheck=recheck))
    assert p >= BKT_PROFICIENT  # the concrete pre-fix readiness leak
    assert independent_observations(history) == []  # never a diagnostic ceiling
    states = planner.planning_states({"A": p, "T": 0.35}, history)
    assert states["A"] < BKT_PROFICIENT
    assert "T" not in planner.prerequisite_ready(states, [("A", "T")], transitive=True)
    state = {
        "goal": {"target_node_ids": ["A"]},
        "plan": {"attempted": ["A"], "checked_nodes": ["A"]},
    }
    assert (
        goals.progress(state, states, {"A"}, continue_available=False)["status"]
        == "needs_more_practice"
    )


@pytest.mark.parametrize("difficulty", [2, 3])
def test_fresh_independent_same_or_higher_success_clears_assisted_failure(difficulty):
    history = [
        observation("helped-miss", difficulty=2, same_session_recheck=True),
        observation(
            "new-success", correct=True, difficulty=difficulty, independent=True, max_rung=0
        ),
    ]
    assert planner.planning_states({"A": 0.999}, history)["A"] == 0.999


@pytest.mark.parametrize(
    "extra",
    [
        {"independent": False},
        {"max_rung": 1},
        {"same_session_recheck": True},
        {"previously_seen": True},
        {"assisted": True},
        {"difficulty": 1},
    ],
)
def test_helped_rechecked_seen_or_easier_success_cannot_clear_need(extra):
    success = observation("success", correct=True, difficulty=2, independent=True, max_rung=0)
    history = [
        observation("helped-miss", difficulty=2),
        {**success, **extra},
    ]
    assert planner.planning_states({"A": 0.999}, history)["A"] < BKT_PROFICIENT


def test_replayed_old_wrong_cannot_reblock_after_distinct_independent_recovery():
    miss = observation("old-wrong")
    recovery = observation("fresh-success", correct=True, independent=True, max_rung=0)
    assert planner.planning_states({"A": 0.999}, [miss, recovery, dict(miss)])["A"] == 0.999
    assert (
        planner.planning_states({"A": 0.999}, [miss, {**recovery, "question_hash": "old-wrong"}])[
            "A"
        ]
        < BKT_PROFICIENT
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"correct": "false"},
        {"idk": "false"},
        {"difficulty": True},
        {"difficulty": 2.0},
        {"difficulty": 99},
        {"channel": "unknown"},
        {"channel": []},
        {"independent": "false"},
        {"max_rung": True},
        {"max_rung": -1},
        {"max_rung": 7},
        {"same_session_recheck": "false"},
        {"assisted": "false"},
        {"unavailable": True},
        {"unavailable": None},
        {"graded": False},
        {"refused": "disowned_answer"},
        {"refused": 0},
        {"synthetic_idk": True},
        {"previously_seen": True},
        {"question_hash": ""},
        {"node_id": []},
    ],
)
def test_invalid_or_unavailable_failure_cannot_create_or_recreate_need(extra):
    invalid = observation("invalid", **extra)
    assert planner.planning_states({"A": 0.999}, [invalid])["A"] == 0.999
    history = [
        observation("valid-miss"),
        observation("valid-recovery", correct=True, independent=True, max_rung=0),
        invalid,
    ]
    assert planner.planning_states({"A": 0.999}, history)["A"] == 0.999


@pytest.mark.parametrize("correct", [False, True])
def test_synthetic_unknown_does_not_block_but_genuine_graded_unknown_does(correct):
    # Match diagnostic history's backwards-compatible explicit-IDK precedence.
    unknown = observation("unknown", correct=correct, idk=True, same_session_recheck=True)
    assert planner.planning_states({"A": 0.999}, [unknown])["A"] < BKT_PROFICIENT
    assert planner.planning_states({"A": 0.999}, [{**unknown, "synthetic_idk": True}])["A"] == 0.999


def test_invalid_first_exposure_cannot_be_replayed_as_a_new_failed_check():
    first = observation("same", unavailable=True)
    assert planner.planning_states({"A": 0.999}, [first, observation("same")])["A"] == 0.999
