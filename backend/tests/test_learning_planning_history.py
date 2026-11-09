"""Cross-session readiness uses durable, final, owner-scoped evidence only."""

from copy import deepcopy
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from learning import bkt, planner, planning_history
from learning.evidence import (
    Evidence,
    PlanningObservation,
    PlanningPersistenceUnavailable,
    PlanningProvenance,
    planning_observation,
)
from test_learning_probe_planner import LOOP, PLAN_Q, client, probe as probe
import routes.learn_loop as rl


def event(key, *, node="A", owner="u1", course="c1", **changes):
    difficulty = changes.pop("difficulty", 3)
    synthetic = changes.pop("synthetic_idk", False)
    seen = changes.pop("previously_seen", False)
    ev = Evidence(
        node_id=node,
        channel="free_response",
        correct=changes.pop("correct", False),
        check_item_id=f"item-{key}",
        question_hash=key,
        planning_provenance=PlanningProvenance(
            check_item_id=f"item-{key}",
            difficulty=difficulty,
            synthetic_idk=synthetic,
            previously_seen=seen,
        ),
        **changes,
    )
    return {
        **ev.model_dump(),
        "id": key,
        "planning_observation": planning_observation(ev),
        "reason": f"evidence:{ev.channel}" + (":idk" if ev.idk else ""),
        "created_at": "2026-10-19T01:00:00+00:00",
        "evidence_seq": 0,
        "graph_nodes": {"user_id": owner, "course_id": course},
    }


class Pages:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def select_with_count(self, columns, **kwargs):
        self.calls.append((columns, kwargs))
        start, limit = kwargs["offset"], kwargs["limit"]
        return self.rows[start : start + limit], 0  # missing count must not truncate


def read(rows, *, nodes=("A", "T")):
    pages = Pages(rows)
    with patch.object(planning_history, "table", return_value=pages):
        result = planning_history.read_planning_history("u1", "c1", nodes)
    return result, pages


def test_fresh_goal_cannot_forget_failed_practice_and_only_independent_recovery_clears(probe):
    p, rows = 0.999, []
    for index, recheck in enumerate((False, True)):
        row = event(f"old-{index}", max_rung=2, same_session_recheck=recheck, confidence=0.9)
        p = bkt.update(p, row["channel"], row["correct"], weight=row["weight"])
        rows.append(row)
    assert p >= rl.BKT_PROFICIENT
    probe.states.return_value = {"A": p, "T": 0.35}
    probe.edges.return_value = [("A", "T")]
    probe.due.return_value = ["A"]
    fresh = {"phase": "plan", "goal": {"target_node_ids": ["T"]}}
    with patch.object(rl, "read_planning_history", side_effect=lambda *a: read(rows)[0]):
        before = rl._current_plan(fresh, "u1", "c1")
        assert "T" not in before.ready
        assert [c.node_id for c in before.proposal.concepts] == ["A"]
        rows.append(event("helped-correct", correct=True, max_rung=2))
        rows.append(event("easier-correct", correct=True, difficulty=1))
        assert "T" not in rl._current_plan(fresh, "u1", "c1").ready
        rows.append(event("independent-recovery", correct=True))
        after = rl._current_plan(fresh, "u1", "c1")
    assert "T" in after.ready
    assert "T" in [c.node_id for c in after.proposal.concepts]


def test_current_legacy_snapshots_neither_upgrade_unknown_nor_reblock_newer_recovery(probe):
    miss, recovery = event("miss", max_rung=2), event("recovery", correct=True)
    probe.states.return_value = {"A": 0.999, "T": 0.35}
    probe.edges.return_value = [("A", "T")]
    state = {
        "goal": {"target_node_ids": ["T"]},
        "steps": {
            "old-missing": {
                "graded_at": 1,
                "goal_observation": event("old-missing")["planning_observation"],
            },
            "recovery": {"graded_at": 2, "goal_observation": recovery["planning_observation"]},
        },
        "probe": {"history": [recovery["planning_observation"]]},
    }
    with patch.object(
        rl, "read_planning_history", side_effect=lambda *a: read([miss, recovery])[0]
    ):
        assert "T" in rl._current_plan(state, "u1", "c1").ready
    unknown = {**recovery, "planning_observation": None}
    with patch.object(rl, "read_planning_history", side_effect=lambda *a: read([miss, unknown])[0]):
        assert "T" not in rl._current_plan(state, "u1", "c1").ready


def test_global_first_hash_includes_unknown_and_other_course_but_not_other_user():
    miss = event("miss", max_rung=2)
    recovery = event("shared", correct=True)
    for early in (event("shared", course="other"), {**recovery, "planning_observation": None}):
        history, _ = read([early, miss, recovery])
        assert planner.planning_states({"A": 0.999}, history)["A"] < rl.BKT_PROFICIENT
    history, _ = read([event("shared", owner="another-user"), miss, recovery])
    assert planner.planning_states({"A": 0.999}, history)["A"] == 0.999


def test_all_owned_pages_are_read_before_course_projection_with_total_journal_order():
    rows = [event(f"other-{i}", course="other") for i in range(1105)]
    rows += [event("late-miss", max_rung=2)]
    history, pages = read(rows)
    assert planner.planning_states({"A": 0.999}, history)["A"] < rl.BKT_PROFICIENT
    assert len(pages.calls) >= 2
    for columns, kwargs in pages.calls:
        assert kwargs["order"] == "created_at.asc,evidence_seq.asc.nullslast,id.asc"
        assert kwargs["filters"]["graph_nodes.user_id"] == "eq.u1"
        assert not any("course" in key for key in kwargs["filters"])
        assert "answer" not in columns and "prompt" not in columns


@pytest.mark.parametrize(
    "change",
    [
        {"independent": "true"},
        {"correct": "false"},
        {"difficulty": True},
        {"max_rung": 1, "assisted": True, "independent": True},
        {"same_session_recheck": True, "independent": True},
        {"synthetic_idk": True},
        {"node_id": "foreign"},
        {"question_hash": "other"},
        {"feedback": "learner prose must not be accepted"},
    ],
)
def test_invalid_or_mismatched_envelope_cannot_repair_or_create_need(change):
    row = event("invalid", correct=True)
    row["planning_observation"].update(change)
    history, _ = read([event("miss", max_rung=2), row])
    assert planner.planning_states({"A": 0.999}, history)["A"] < rl.BKT_PROFICIENT
    history, _ = read([row])
    assert planner.planning_states({"A": 0.999}, history)["A"] == 0.999


def test_canonical_recheck_and_refloor_win_over_independence_claims():
    recheck = event("recheck", correct=True, same_session_recheck=True)
    assert recheck["planning_observation"]["independent"] is False
    late_floor = Evidence.model_validate(
        {
            **event("floor", correct=True),
            "max_rung": 6,
            "assisted": False,
        }
    )
    assert planning_observation(late_floor)["independent"] is False
    assert planning_observation(late_floor)["max_rung"] == 6


def test_explicit_goal_read_outage_is_503_without_state_or_mastery_changes(probe):
    probe.states.return_value = {"A": 0.999, "T": 0.35}
    probe.edges.return_value = [("A", "T")]
    probe.store["doc"] = {"phase": "plan", "goal": {"target_node_ids": ["T"]}}
    before = deepcopy(probe.store["doc"])
    with patch.object(
        rl, "read_planning_history", side_effect=PlanningPersistenceUnavailable("down")
    ):
        result = client.get(f"{LOOP}/plan", params=PLAN_Q)
    assert result.status_code == 503
    assert probe.store["doc"] == before
    probe.agu.assert_not_called()


def test_adapter_read_outage_and_missing_migration_are_never_empty_history():
    with patch.object(planning_history, "table", side_effect=RuntimeError("column unavailable")):
        with pytest.raises(PlanningPersistenceUnavailable):
            planning_history.read_planning_history("u1", "c1", ["A"])


def test_typed_envelope_refuses_unknown_extra_fields_and_coerced_flags():
    value = event("valid")["planning_observation"]
    with pytest.raises(ValidationError):
        PlanningObservation.model_validate({**value, "independent": 0})
    with pytest.raises(ValidationError):
        PlanningProvenance(
            check_item_id="x",
            difficulty=1,
            synthetic_idk=False,
            previously_seen=False,
            answer="private",
        )
