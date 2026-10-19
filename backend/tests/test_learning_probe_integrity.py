"""Diagnostic claims need distinct, valid, unaided observations, not row counts."""

from dataclasses import dataclass

import pytest

from learning import params as P
from learning import probe


def obs(qh, *, node="A", difficulty=1, correct=True, **changes):
    return {
        "node_id": node,
        "question_hash": qh,
        "difficulty": difficulty,
        "channel": "free_response",
        "correct": correct,
        "idk": False,
        "p_after": 0.99,
        "independent": True,
        **changes,
    }


def report(history, **kwargs):
    return probe.diagnostic_summary(history, skills=["A"], **kwargs)


def test_repeated_same_question_cannot_supply_minimum_independent_evidence():
    floor = obs("floor")
    ceiling = obs("ceiling", difficulty=3, correct=False)
    history = [floor, ceiling, dict(floor), dict(ceiling)]
    row = report(history)["skills"][0]
    assert row["observations"] == 4
    assert row["independent_observations"] == 2
    assert row["status"] == "partial"
    assert not probe.probe_done(history)
    # Repeats still exhaust the finite fatigue budget; no extra questions gained.
    history += [dict(floor), dict(ceiling)]
    assert probe.probe_done(history)
    assert report(history)["stop_reason"] == "per_skill_cap"


def test_first_exposure_with_help_cannot_become_independent_on_a_repeat():
    history = [obs("repeat", independent=False, max_rung=3), obs("repeat")]
    row = report(history)["skills"][0]
    assert row["independent_observations"] == 0
    assert row["floor_difficulty"] is None


def test_repeated_prompt_across_goal_strands_is_not_new_independent_evidence():
    history = [obs("repeat", node="old-goal"), obs("repeat")]
    row = report(history)["skills"][0]
    assert row["independent_observations"] == 0
    assert row["status"] == "untested"


@pytest.mark.parametrize(
    "changes",
    [
        {"correct": "False"},
        {"correct": None},
        {"correct": 0},
        {"correct": 1},
        {"idk": "false"},
        {"idk": None},
        {"idk": 1},
        {"difficulty": True},
        {"difficulty": 1.0},
        {"difficulty": "1"},
        {"question_hash": ""},
        {"question_hash": None},
        {"channel": "idk"},
        {"channel": "unknown"},
    ],
)
def test_malformed_verdict_or_identity_cannot_establish_a_boundary(changes):
    history = [obs(f"bad-{i}", **changes) for i in range(4)]
    row = report(history, available_difficulties={"A": [1]})["skills"][0]
    assert row["independent_observations"] == 0
    assert row["status"] == "untested"
    assert row["floor_difficulty"] is None
    assert row["ceiling_difficulty"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"max_rung": 1},
        {"max_rung": "0"},
        {"max_rung": None},
        {"same_session_recheck": True},
        {"synthetic_idk": True},
        {"previously_seen": True},
        {"unavailable": True},
        {"graded": False},
        {"refused": "not_an_attempt"},
        {"refused": 0},
    ],
)
def test_explicit_disqualifying_provenance_overrules_stale_independent_flag(changes):
    history = [obs(f"not-independent-{i}", **changes) for i in range(4)]
    assert report(history)["skills"][0]["independent_observations"] == 0


def test_unavailable_grades_do_not_invent_a_ceiling_or_novice_floor():
    history = [
        obs(f"unavailable-{i}", correct=False, unavailable=True)
        for i in range(P.NOVICE_FLOOR_MISSES)
    ]
    assert not probe.novice_floor(history)
    assert report(history)["skills"][0]["ceiling_difficulty"] is None
    # No successful assessment has happened; a failure is still bounded globally.
    history *= P.PROBE_ITEMS_PER_SKILL_MAX
    assert probe.probe_done(history)
    assert report(history)["status"] == "not_assessed"


def test_unavailable_history_cannot_make_adaptive_selection_descend():
    @dataclass(frozen=True)
    class Item:
        id: str
        node_id: str
        format: str
        difficulty: int
        question_hash: str

    items = [Item(str(d), "A", "free", d, f"item-{d}") for d in (1, 2, 3)]
    arguments = dict(
        states={"A": 0.6},
        items=items,
        asked_hashes=[],
        channel_for_format={"free": "free_response"},
    )
    baseline = probe.next_probe_item(**arguments)
    invalid = [obs("outage", difficulty=3, correct=False, unavailable=True)]
    selected = probe.next_probe_item(**arguments, history=invalid)
    assert selected.difficulty == baseline.difficulty


def test_valid_explicit_unknown_is_a_ceiling_and_valid_distinct_evidence_brackets():
    history = [obs("f1"), obs("c1", difficulty=3, correct=False, idk=True), obs("f2"), obs("f3")]
    row = report(history)["skills"][0]
    assert row["status"] == "bracketed"
    assert row["independent_observations"] == 4
    assert (row["floor_difficulty"], row["ceiling_difficulty"]) == (1, 3)


def test_distinct_questions_and_posterior_values_do_not_change_evidence_validity():
    history = [
        obs("f1", p_after=0),
        obs("c1", difficulty=2, correct=False, p_after=1),
        obs("f2", p_after=float("nan")),
        obs("f3", p_after=-100),
    ]
    row = report(history)["skills"][0]
    assert row["status"] == "bracketed"
    assert row["independent_observations"] == 4


@dataclass(frozen=True)
class Item:
    id: str
    node_id: str
    format: str
    difficulty: int
    question_hash: str


def choose(history, items):
    return probe.next_probe_item(
        {"A": 0.6}, items, [], channel_for_format={"free": "free_response"}, history=history
    )


def test_repeated_rows_do_not_stop_fresh_boundary_questions():
    floor, ceiling = obs("floor"), obs("ceiling", difficulty=3, correct=False)
    history = [floor, ceiling, dict(floor), dict(ceiling)]
    item = Item("fresh", "A", "free", 2, "fresh-interior")
    assert choose(history, [item]) is item


def test_repeated_prompt_from_old_goal_does_not_force_adaptive_escalation():
    items = [Item(str(d), "A", "free", d, f"fresh-{d}") for d in (1, 2, 3)]
    baseline = choose([], items)
    repeated = [obs("repeated", node="old-goal"), obs("repeated", difficulty=3)]
    assert choose(repeated, items).difficulty == baseline.difficulty


def test_duplicate_bank_bindings_do_not_exhaust_a_skill_fatigue_budget():
    asked = Item("asked", "A", "free", 1, "asked")
    fresh = Item("fresh", "A", "free", 2, "fresh")
    assert choose([obs("asked")], [asked] * P.PROBE_ITEMS_PER_SKILL_MAX + [fresh]) is fresh


@pytest.mark.parametrize("coverage", [[True], [1.0], ["1"]])
def test_malformed_bank_levels_do_not_establish_range_coverage(coverage):
    history = [obs(f"floor-{i}") for i in range(P.PROBE_ITEMS_PER_SKILL_MIN)]
    row = report(history, available_difficulties={"A": coverage})["skills"][0]
    assert row["available_difficulties"] == []
    assert row["status"] == "partial"


def test_boolean_bank_difficulty_is_not_an_integer_difficulty_level():
    item = Item("bad", "A", "free", True, "bad-difficulty")
    assert choose([], [item]) is None


def test_public_independent_selection_is_global_ordered_and_does_not_mutate_history():
    old = obs("repeat", node="old-goal", independent=False)
    repeated = obs("repeat")
    valid = obs("valid")
    unavailable = obs("unavailable", unavailable=True)
    history = [old, repeated, valid, unavailable]
    before = [dict(h) for h in history]
    assert probe.independent_observations(history) == [valid]
    assert history == before


def test_non_observation_json_records_never_become_evidence_but_remain_bounded():
    history = [None, {}, {"node_id": "A", "correct": None}]
    assert report(history)["skills"][0]["independent_observations"] == 0
    assert not probe.probe_done(history)
    assert probe.probe_done(history * P.PROBE_SESSION_CAP)


def test_unhashable_bank_metadata_is_ignored_without_inventing_a_range():
    history = [obs(f"floor-{i}") for i in range(P.PROBE_ITEMS_PER_SKILL_MIN)]
    row = report(history, available_difficulties={"A": [[], {}]})["skills"][0]
    assert row["status"] == "partial"
    assert row["available_difficulties"] == []
