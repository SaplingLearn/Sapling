"""Adversarial pure diagnostic/planner contracts: no model, HTTP or database."""

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from learning import params as P
from learning.planner import goal_scope, outer_fringe, plan, prerequisite_ready
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


def test_released_interior_shape_does_not_trap_a_wide_bracket_in_rechecks(monkeypatch):
    """Use the actual release/recheck policy, with only its journal read supplied.

    Ability 1 gives an independent floor=1/ceiling=3. The first interior miss
    is assisted by the prior release, so it cannot lower the ceiling. Avoiding
    that now-released interior class leaves enough fresh floor confirmations
    for four independent observations within the six-item cap.
    """
    from learning import misconceptions

    journal = []
    history = []
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(misconceptions, "recent_evidence", lambda *_args, **_kwargs: list(journal))

    def grade(item, *, correct):
        recheck = misconceptions.recheck_after_release("u1", "A", {}, now=now, item=item)
        history.append(
            observation(
                difficulty=item.difficulty,
                question_hash=item.question_hash,
                correct=correct,
                independent=not recheck,
                same_session_recheck=recheck,
                k=len(history),
            )
        )
        journal.append(
            {
                "question_hash": item.question_hash,
                "released": not correct,
                "shape": (item.format, item.difficulty),
            }
        )
        return recheck

    assert grade(Item("floor", "A", 1, "initial-floor"), correct=True) is False
    assert grade(Item("ceiling", "A", 3, "initial-ceiling"), correct=False) is False
    sequence = []
    while len(history) < P.PROBE_ITEMS_PER_SKILL_MAX and not probe_done(history):
        item = choose(history)
        assert item is not None
        sequence.append(item.difficulty)
        grade(item, correct=item.difficulty == 1)
    assert sequence == [2, 1, 1, 1]
    assert [h["independent"] for h in history] == [True, True, False, False, True, True]
    report = summary(history)
    row = report["skills"][0]
    assert len(history) == P.PROBE_ITEMS_PER_SKILL_MAX
    assert report["status"] == "bracketed" and probe_done(history)
    assert (row["floor_difficulty"], row["ceiling_difficulty"]) == (1, 3)
    assert (row["independent_correct"], row["independent_incorrect"]) == (3, 1)
    # Confirmation does not erase either released class's copy-risk guard.
    for difficulty in (2, 3):
        assert (
            misconceptions.recheck_after_release(
                "u1",
                "A",
                {},
                now=now,
                item=Item("owed", "A", difficulty, f"new-owed-{difficulty}"),
            )
            is True
        )


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


def test_proficient_goal_review_waits_for_its_missing_prerequisite():
    states = {"foundation": 0.2, "target": 0.99, "unrelated": 0.99}
    edges = [("foundation", "target")]
    scope = goal_scope(["target"], edges, nodes=states)
    ready = prerequisite_ready(states, edges)
    assert ready == frozenset({"foundation", "unrelated"})
    # Explicit-goal routes filter due/advanced reviews before reviews-first plan.
    reviews = [n for n in ["target", "unrelated"] if n in ready]
    proposal = plan(outer_fringe(states, edges), reviews, lambda _: [], scope.__contains__)
    assert [(c.node_id, c.kind) for c in proposal.concepts] == [("foundation", "new")]
    states["foundation"] = P.BKT_PROFICIENT
    assert "target" in prerequisite_ready(states, edges)
    proposal = plan([], ["target"], lambda _: [], scope.__contains__)
    assert [(c.node_id, c.kind) for c in proposal.concepts] == [("target", "review")]


def test_readiness_is_cycle_safe_and_ignores_foreign_or_self_endpoints():
    states = {"P": 0.2, "A": 0.3, "B": 0.99, "isolated": 0.4}
    edges = [("P", "A"), ("A", "B"), ("B", "A"), ("ghost", "isolated"), ("P", "P")]
    assert prerequisite_ready(states, iter(edges)) == frozenset({"P", "isolated"})
    assert outer_fringe(states, iter(edges)) == ["isolated", "P"]
    states["P"] = P.BKT_PROFICIENT
    assert prerequisite_ready(states, iter(edges)) == frozenset(states)
    assert outer_fringe(states, iter(edges)) == ["isolated", "A"]


def test_transitive_goal_readiness_defers_high_posterior_intermediates_and_target():
    states = {"foundation": 0.2, "bridge": 0.99, "target": 0.99, "unrelated": 0.3}
    edges = [("foundation", "bridge"), ("bridge", "target")]
    # Preserve existing direct readiness for course-wide planning.
    assert prerequisite_ready(states, edges) == frozenset({"foundation", "target", "unrelated"})
    ready = prerequisite_ready(states, iter(edges), transitive=True)
    assert ready == frozenset({"foundation", "unrelated"})
    scope = goal_scope(["target"], edges, nodes=states)
    allowed = scope & ready
    proposal = plan(
        outer_fringe(states, edges),
        ["bridge", "target"],
        lambda _: ["target"],
        allowed.__contains__,
        proficient=frozenset({"bridge", "target"}),
    )
    assert [(c.node_id, c.kind) for c in proposal.concepts] == [("foundation", "new")]
    states["foundation"] = P.BKT_PROFICIENT
    assert prerequisite_ready(states, edges, transitive=True) == frozenset(states)


def test_transitive_readiness_ignores_own_cycle_but_blocks_external_descendants():
    states = {"A": 0.2, "B": 0.99, "target": 0.99, "unrelated": 0.4}
    edges = [("A", "B"), ("B", "A"), ("B", "target"), ("ghost", "A"), ("A", "A")]
    assert prerequisite_ready(states, edges, transitive=True) == frozenset({"A", "B", "unrelated"})
    states["outside"] = 0.3
    edges.append(("outside", "A"))
    assert prerequisite_ready(states, edges, transitive=True) == frozenset({"outside", "unrelated"})
