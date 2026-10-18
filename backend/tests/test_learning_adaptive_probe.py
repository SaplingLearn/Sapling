"""Adversarial pure diagnostic/planner contracts: no model, HTTP or database."""

from dataclasses import dataclass

import pytest

from learning import params as P
from learning.planner import goal_scope, plan
from learning.probe import diagnostic_summary, next_probe_item, probe_done


@dataclass(frozen=True)
class Item:
    id: str
    node_id: str
    difficulty: int
    question_hash: str
    format: str = "free"


def bank(*nodes, copies=7):
    return [
        Item(f"{n}-{d}-{i}", n, d, f"{n}-{d}-{i}")
        for n in nodes
        for d in P.PROBE_DIFFICULTY_SHIFT
        for i in range(copies)
    ]


def observation(node="A", *, difficulty=2, correct=True, independent=True, k=0, **extra):
    return {
        "node_id": node,
        "question_hash": f"observed-{node}-{k}",
        "difficulty": difficulty,
        "channel": "free_response",
        "correct": correct,
        "idk": False,
        "p_after": 0.999,
        "independent": independent,
        **extra,
    }


def choose(history, *, nodes=("A",), items=None):
    return next_probe_item(
        {n: 0.6 for n in nodes},
        bank(*nodes) if items is None else items,
        [],
        channel_for_format={"free": "free_response"},
        history=history,
    )


def summary(history, **kwargs):
    return diagnostic_summary(history, skills=["A"], **kwargs)


def bracket(node="A"):
    return [
        observation(node, difficulty=d, correct=c, k=i)
        for i, (d, c) in enumerate([(1, True), (3, False), (2, True), (3, False)])
    ]


def test_all_correct_stable_posterior_keeps_diagnosing_and_escalates():
    history = [observation(k=i) for i in range(P.PROBE_ITEMS_PER_SKILL_MIN)]
    assert not probe_done(history)
    assert summary(history)["status"] == "in_progress"
    assert summary(history)["skills"][0]["ceiling_difficulty"] is None
    assert choose(history).difficulty == 3


def test_all_correct_at_top_of_bank_is_above_range_not_bracketed():
    history = [observation(difficulty=3, k=i) for i in range(P.PROBE_ITEMS_PER_SKILL_MIN)]
    report = summary(history, available_difficulties={"A": [1, 2, 3]})
    assert report["skills"][0]["status"] == "above_range"
    assert report["status"] == "in_progress"
    assert not probe_done(history)
    history.extend(observation(difficulty=3, k=i) for i in range(4, P.PROBE_ITEMS_PER_SKILL_MAX))
    report = summary(history, available_difficulties={"A": [1, 2, 3]})
    assert report["status"] == "limited"
    assert report["stop_reason"] == "per_skill_cap"
    assert probe_done(history)


def test_no_bank_coverage_never_invents_above_or_below_range():
    for correct, difficulty in [(True, 3), (False, 2)]:
        history = [observation(correct=correct, difficulty=difficulty, k=i) for i in range(4)]
        assert summary(history)["skills"][0]["status"] == "partial"


def test_failure_descends_then_ordered_boundary_is_bisected():
    history = [observation(difficulty=3, correct=False)]
    assert choose(history).difficulty == 1
    history.append(observation(difficulty=1, correct=True, k=1))
    assert choose(history).difficulty == 2
    assert not probe_done(history)


def test_boundary_requires_minimum_independent_evidence():
    history = bracket()
    assert not probe_done(history[:3])
    assert probe_done(history)
    report = summary(history)
    assert report["status"] == "bracketed"
    assert report["stop_reason"] == "observed_boundaries"
    row = report["skills"][0]
    assert (row["floor_difficulty"], row["ceiling_difficulty"]) == (2, 3)
    assert (row["independent_correct"], row["independent_incorrect"]) == (2, 2)
    assert choose(history) is None


@pytest.mark.parametrize("floor,ceiling", [(1, 2), (2, 3)])
def test_adjacent_boundary_confirms_fresh_floor_examples_after_a_release_recheck(floor, ceiling):
    """A miss releases its answer; the next concept check is a recheck.

    Fresh items at the failed ceiling have the same failed shape and remain
    owed isomorphs, so cycling through them cannot establish unaided evidence.
    Confirming the already-solved floor lets diagnosis finish within its cap
    without treating the release/recheck as independent success.
    """
    history = [
        observation(difficulty=floor, k=0),
        observation(difficulty=ceiling, correct=False, k=1),
    ]
    assert not probe_done(history)
    for k in range(2, 5):
        item = choose(history)
        assert item is not None and item.difficulty == floor
        recheck = k == 2  # First check after the ceiling answer was released.
        history.append(
            observation(
                difficulty=item.difficulty,
                question_hash=item.question_hash,
                independent=not recheck,
                same_session_recheck=recheck,
                k=k,
            )
        )
        if recheck:
            assert summary(history)["skills"][0]["independent_observations"] == 2
            assert not probe_done(history)
    report = summary(history)
    assert len(history) < P.PROBE_ITEMS_PER_SKILL_MAX
    assert report["status"] == "bracketed"
    assert report["stop_reason"] == "observed_boundaries"
    assert report["skills"][0]["independent_correct"] == 3
    assert report["skills"][0]["independent_incorrect"] == 1
    assert probe_done(history)


def test_same_difficulty_slip_is_retested_and_not_confidently_bracketed():
    history = [observation(correct=c, k=i) for i, c in enumerate([True, False, True, True])]
    report = summary(history)
    assert report["skills"][0]["status"] == "inconsistent"
    assert report["skills"][0]["contradictory_difficulties"] == [2]
    assert not probe_done(history)
    assert choose(history).difficulty == 2


def test_reversed_boundary_is_inconsistent_even_with_low_posterior_delta():
    history = [
        observation(difficulty=d, correct=c, k=i)
        for i, (d, c) in enumerate([(3, True), (1, False), (3, True), (2, False)])
    ]
    row = summary(history)["skills"][0]
    assert row["status"] == "inconsistent"
    assert row["contradictory_difficulties"] == [1, 2, 3]
    assert not probe_done(history)
    assert choose(history).difficulty in (1, 2)


def test_assistance_and_unknown_legacy_provenance_cannot_establish_boundaries():
    for provenance in (False, None):
        history = bracket()
        for h in history:
            if provenance is None:
                h.pop("independent")
            else:
                h["independent"] = provenance
        report = summary(history)
        assert report["status"] == "not_assessed"
        assert report["skills"][0]["status"] == "untested"
        assert report["skills"][0]["independent_observations"] == 0
        assert not probe_done(history)
        # Compatibility: unknown old sessions still hit a finite cap.
        history += [dict(history[0], question_hash=f"legacy-{i}") for i in range(2)]
        assert probe_done(history)
        assert summary(history)["stop_reason"] == "per_skill_cap"


def test_assisted_answers_do_not_fill_the_minimum_unaided_evidence():
    history = bracket()[:2] + [
        observation(difficulty=2, independent=False, k=2),
        observation(difficulty=3, correct=False, independent=False, k=3),
    ]
    row = summary(history)["skills"][0]
    assert row["status"] == "partial"
    assert row["observations"] == 4
    assert row["independent_observations"] == 2
    assert not probe_done(history)


def test_legacy_history_is_not_used_to_adapt_difficulty():
    history = [observation(difficulty=1, k=0)]
    history[0].pop("independent")
    # The unsupported old observation must not force escalation to hardest.
    assert choose(history).difficulty == choose([]).difficulty


def test_all_wrong_at_easiest_is_below_range_only_with_minimum_evidence():
    history = [observation(difficulty=1, correct=False, k=i) for i in range(4)]
    report = summary(history, available_difficulties={"A": [1, 2, 3]})
    assert report["skills"][0]["status"] == "below_range"
    assert report["skills"][0]["floor_difficulty"] is None
    assert report["status"] == "limited"
    assert report["stop_reason"] == "novice_floor"


def test_novice_fatigue_stop_explicitly_reports_partial_and_untested_skills():
    history = [observation(difficulty=1, correct=False, k=i) for i in range(P.NOVICE_FLOOR_MISSES)]
    report = diagnostic_summary(history, skills=["A", "B"], available_difficulties={"A": [1, 2, 3]})
    assert probe_done(history, skills=["A", "B"])
    assert choose(history, nodes=("A", "B")) is None
    assert report["status"] == "limited"
    assert report["stop_reason"] == "novice_floor"
    assert [r["status"] for r in report["skills"]] == ["partial", "untested"]


def test_bank_exhaustion_is_an_explicit_limit_not_a_found_boundary():
    history = [observation(difficulty=2)]
    assert choose(history, items=[]) is None
    report = summary(history, stop_reason="bank_exhausted")
    assert report["status"] == "limited"
    assert report["stop_reason"] == "bank_exhausted"
    assert report["skills"][0]["status"] == "partial"


def test_fair_coverage_prevents_a_high_prior_strand_starving_another():
    history = []
    items = bank("A", "B", "C")
    states = {"A": 0.6, "B": 0.01, "C": 0.999}
    for i in range(P.PROBE_SESSION_CAP):
        chosen = next_probe_item(
            states, items, [], channel_for_format={"free": "free_response"}, history=history
        )
        assert chosen is not None
        history.append(
            observation(
                chosen.node_id,
                difficulty=chosen.difficulty,
                question_hash=chosen.question_hash,
                k=i,
            )
        )
        counts = {n: sum(h["node_id"] == n for h in history) for n in states}
        assert max(counts.values()) - min(counts.values()) <= 1
    assert list(counts.values()) == [4, 4, 4]
    assert choose(history, nodes=tuple(states)) is None
    report = diagnostic_summary(history, skills=states)
    assert report["status"] == "limited"
    assert report["stop_reason"] == "session_cap"
    assert all(r["ceiling_difficulty"] is None for r in report["skills"])


def test_finished_strand_does_not_consume_another_strands_remaining_budget():
    history = bracket("A")
    assert choose(history, nodes=("A", "B")).node_id == "B"


def test_explicit_goal_skills_exclude_old_goal_evidence_but_keep_global_fatigue():
    history = bracket("old") + bracket("A")
    report = diagnostic_summary(history, skills=["A"])
    assert [r["node_id"] for r in report["skills"]] == ["A"]
    assert report["status"] == "bracketed"
    assert probe_done(history, skills=["A"])
    old = [observation("old", k=i) for i in range(P.PROBE_SESSION_CAP)]
    report = diagnostic_summary(old, skills=["A", "B"])
    assert report["status"] == "not_assessed"
    assert report["stop_reason"] == "session_cap"
    assert probe_done(old, skills=["A", "B"])


def test_more_scoped_nodes_than_session_budget_reports_untested_not_complete():
    history = [observation("A", k=i) for i in range(P.PROBE_SESSION_CAP)]
    report = diagnostic_summary(history, skills=["A", "B", "C", "D"])
    assert report["status"] == "limited"
    assert [r["status"] for r in report["skills"]] == [
        "partial",
        "untested",
        "untested",
        "untested",
    ]


def test_goal_closure_includes_foundations_not_other_descendants_or_disconnected_nodes():
    edges = [("root", "mid"), ("mid", "goal"), ("root", "unrelated"), ("goal", "later")]
    nodes = {"root", "mid", "goal", "unrelated", "later", "isolated"}
    assert goal_scope(["goal"], edges, nodes=nodes) == frozenset({"root", "mid", "goal"})
    assert goal_scope(["isolated"], edges, nodes=nodes) == frozenset({"isolated"})


def test_goal_closure_is_cycle_safe_and_drops_invalid_endpoint_bridges():
    edges = [("A", "B"), ("B", "A"), ("P", "A"), ("ghost", "B"), ("outside", "ghost")]
    assert goal_scope(["B", "missing"], edges, nodes=["A", "B", "P", "outside"]) == frozenset(
        {"A", "B", "P"}
    )
    assert goal_scope(["missing"], edges, nodes=["A", "B"]) == frozenset()


def test_goal_filter_applies_to_interleaved_siblings_as_well_as_reviews_and_new_nodes():
    allowed = {"goal", "foundation", "in-scope-review"}
    out = plan(
        ["goal", "unrelated-new"],
        ["unrelated-review", "in-scope-review"],
        lambda _: ["unrelated-sibling", "foundation"],
        allowed.__contains__,
        proficient=frozenset({"foundation", "unrelated-sibling"}),
    )
    assert [(c.node_id, c.kind) for c in out.concepts] == [
        ("in-scope-review", "review"),
        ("goal", "new"),
        ("foundation", "sibling"),
    ]
