"""W8.6: shared learner-next buckets (pure + IO helper).

Pure ranking lives in learning.learner_next; the quiz plan caps it
(learning.quiz_plan.rank_concepts). services.learner_next assembles the
student's states once for Hub / Quiz launcher / Dashboard.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from learning import params, quiz_plan
from learning.learner_next import (
    ConceptState,
    DUE,
    MISCONCEPTION,
    READY,
    learner_next,
)
from services import learner_next as ln_svc
from services import quiz_learning as ql

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def _state(node, p, *, due=None, s=None, last=None, mis=0, course_id=None):
    return ConceptState(
        node,
        p,
        fsrs_s=s,
        fsrs_last_review_at=last,
        fsrs_due_at=due,
        open_misconceptions=mis,
        course_id=course_id,
    )


def test_learner_next_buckets_match_quiz_plan_order_before_cap():
    """Due → misconceptions → ready; same members and order as rank_concepts
    when under the per-course cap (the shared source of truth)."""
    states = [
        _state("ready_low", 0.40),
        _state("ready_high", 0.70),
        _state("due_far", 0.96, due=NOW - timedelta(days=9), s=2.0, last=NOW - timedelta(days=10)),
        _state("due_near", 0.97, due=NOW - timedelta(hours=1), s=5.0, last=NOW - timedelta(days=5)),
        _state("held", 0.50, mis=2),
        _state("blocked", 0.20),
        _state("proficient", 0.97),
        _state("due_later", 0.60, due=NOW + timedelta(days=2), s=4.0, last=NOW - timedelta(days=1)),
    ]
    edges = [("ready_low", "blocked")]
    nxt = learner_next(states, edges, NOW)
    assert [c.node_id for c in nxt.due] == ["due_far", "due_near"]
    assert all(c.reason == DUE for c in nxt.due)
    assert [c.node_id for c in nxt.misconceptions] == ["held"]
    assert nxt.misconceptions[0].reason == MISCONCEPTION
    assert [c.node_id for c in nxt.ready] == ["ready_high", "due_later", "ready_low"]
    assert all(c.reason == READY for c in nxt.ready)
    assert "blocked" not in {c.node_id for c in nxt.ordered}
    assert "proficient" not in {c.node_id for c in nxt.ordered}
    # Quiz plan is the same flat order when nothing hits the cap.
    plan = quiz_plan.rank_concepts(states, edges, NOW)
    assert [(c.node_id, c.reason) for c in plan] == [(c.node_id, c.reason) for c in nxt.ordered]


def test_rank_concepts_caps_learner_next_per_course():
    """The quiz home still applies QUIZ_PLAN_MAX_CONCEPTS per course on top
    of the shared buckets."""
    cap = params.QUIZ_PLAN_MAX_CONCEPTS
    states = [_state(f"n{i:03d}", 0.4) for i in range(cap + 5)]
    nxt = learner_next(states, [], NOW)
    assert len(nxt.ordered) == cap + 5
    assert len(quiz_plan.rank_concepts(states, [], NOW)) == cap


def test_due_wins_over_misconception_and_ready():
    """A due concept with an open misconception is only in the due bucket."""
    states = [
        _state(
            "both",
            0.90,
            due=NOW - timedelta(hours=1),
            s=3.0,
            last=NOW - timedelta(days=4),
            mis=1,
        ),
        _state("ready", 0.40),
    ]
    nxt = learner_next(states, [], NOW)
    assert [c.node_id for c in nxt.due] == ["both"]
    assert nxt.misconceptions == ()
    assert [c.node_id for c in nxt.ready] == ["ready"]


def test_service_learner_next_wires_the_three_buckets():
    """IO helper returns named wire dicts in the same bucket shape Hub needs."""
    nodes = [
        ql._Node("a", "Alpha", "c1"),
        ql._Node("b", "Beta", "c1"),
        ql._Node("c", "Gamma", "c1"),
    ]
    states = {
        "a": type(
            "S",
            (),
            {
                "p_known": 0.96,
                "fsrs_s": 2.0,
                "fsrs_last_review_at": NOW - timedelta(days=10),
                "fsrs_due_at": NOW - timedelta(days=1),
            },
        )(),
        "b": type(
            "S",
            (),
            {
                "p_known": 0.40,
                "fsrs_s": None,
                "fsrs_last_review_at": None,
                "fsrs_due_at": None,
            },
        )(),
    }
    with (
        patch.object(ql, "_nodes", return_value=nodes),
        patch.object(ql, "read_states", return_value=states),
        patch.object(
            ql,
            "_open_misconceptions",
            return_value=[{"node_id": "c", "wrong_key": "k_a", "count": 1}],
        ),
        patch.object(ql, "_prereq_edges", return_value=[("b", "c")]),
    ):
        out = ln_svc.learner_next("u", "c1", now=NOW)
    assert [c["node_id"] for c in out["due"]] == ["a"]
    assert out["due"][0]["concept_name"] == "Alpha" and out["due"][0]["reason"] == DUE
    assert [c["node_id"] for c in out["misconceptions"]] == ["c"]
    assert out["misconceptions"][0]["concept_name"] == "Gamma"
    assert [c["node_id"] for c in out["ready"]] == ["b"]
    assert out["ready"][0]["p_known"] == 0.4
    assert out["misconceptions"][0]["p_known"] == params.BKT_L0  # c missing from read_states
    # Flat quiz plan over the same inputs is the concatenation (under the cap).
    with (
        patch.object(ql, "_nodes", return_value=nodes),
        patch.object(ql, "read_states", return_value=states),
        patch.object(
            ql,
            "_open_misconceptions",
            return_value=[{"node_id": "c", "wrong_key": "k_a", "count": 1}],
        ),
        patch.object(ql, "_prereq_edges", return_value=[("b", "c")]),
    ):
        plan = ql.concept_plan("u", "c1", now=NOW)
    flat = out["due"] + out["misconceptions"] + out["ready"]
    assert [(c["node_id"], c["reason"]) for c in plan] == [
        (c["node_id"], c["reason"]) for c in flat
    ]


def test_service_learner_next_empty_when_no_nodes():
    with patch.object(ql, "_nodes", return_value=[]):
        assert ln_svc.learner_next("u", "c1", now=NOW) == {
            "due": [],
            "misconceptions": [],
            "ready": [],
        }
