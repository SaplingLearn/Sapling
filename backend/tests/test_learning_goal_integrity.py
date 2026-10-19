"""Goal graph drift and bounded progression through real plan/CAS handlers."""

from unittest.mock import patch

import pytest

from learning import planner
from test_learning_goals import _open_write_harness as _open_write_harness, set_goal
from test_learning_probe_planner import LOOP, NEXT, PLAN_Q, client, probe as probe
import routes.learn_loop as rl


def proposal(probe, targets=("T",)):
    assert set_goal(targets).status_code == 200
    probe.store["doc"]["phase"] = "plan"
    response = client.get(f"{LOOP}/plan", params=PLAN_Q)
    assert response.status_code == 200
    return response.json()


def approve(body, ids):
    with patch.object(rl, "store_brief"):
        return client.post(
            f"{LOOP}/plan/approve",
            json={**NEXT, "concept_ids": ids, "goal_version": body["goal_version"]},
        )


@pytest.mark.parametrize(
    "change", ["weak_prerequisite", "new_edge", "deleted_target", "deleted_foundation"]
)
def test_approval_revalidates_current_goal_graph_and_readiness(probe, change):
    probe.states.return_value = {"A": 0.99, "T": 0.3}
    probe.edges.return_value = [("A", "T")]
    if change == "deleted_foundation":
        probe.states.return_value["A"] = 0.3
    body = proposal(probe)
    chosen = body["concepts"][0]["node_id"]
    if change == "weak_prerequisite":
        probe.states.return_value["A"] = 0.2
    elif change == "new_edge":
        probe.states.return_value["P"] = 0.2
        probe.edges.return_value.append(("P", "T"))
    elif change == "deleted_target":
        probe.states.return_value.pop("T")
    else:
        probe.states.return_value.pop("A")
    before = repr(probe.store["doc"])
    result = approve(body, [chosen])
    assert result.status_code in {409, 422}
    assert repr(probe.store["doc"]) == before
    assert not probe.agu.called


def test_goal_approval_atomically_requires_an_open_session(probe):
    probe.states.return_value = {"T": 0.3}
    probe.edges.return_value = []
    body = proposal(probe)
    assert approve(body, ["T"]).status_code == 200
    assert probe.save.call_args.kwargs["require_open"] is True


def obs(node, *, correct=True, difficulty=2, key=None, **extra):
    return {
        "node_id": node,
        "question_hash": key or f"new-{node}",
        "difficulty": difficulty,
        "channel": "free_response",
        "correct": correct,
        "idk": False,
        "independent": True,
        "max_rung": 0,
        "same_session_recheck": False,
        "previously_seen": False,
        **extra,
    }


def finish_frontier(probe, node, *, observation):
    doc = probe.store["doc"]
    doc["concept_checks"] = rl.LOOP_CHECKS_PER_CONCEPT
    if node == "A" and (doc.get("probe") or {}).get("history"):
        doc.setdefault("steps", {})[f"recheck-{node}"] = {
            "graded_at": rl._now_s() - 1,
            "first_shown_at": rl._now_s() - 60,
            "node_id": node,
            "goal_observation": obs(
                node, key=f"recheck-{node}", independent=False, same_session_recheck=True
            ),
        }
    doc.setdefault("steps", {})[observation["question_hash"]] = {
        "graded_at": rl._now_s(),
        "first_shown_at": rl._now_s() - 60,
        "node_id": node,
        "goal_observation": observation,
    }
    rl._advance_cursor(doc)


def test_goal_frontiers_replan_A_then_B_then_target_without_autoapproval_or_mastery(probe):
    probe.states.return_value = {"A": 0.99, "B": 0.3, "T": 0.3, "unrelated": 0.2}
    probe.edges.return_value = [("A", "B"), ("B", "T")]
    body = proposal(probe)
    probe.store["doc"].setdefault("probe", {})["history"] = [
        obs("A", correct=False, key="diagnostic-A")
    ]
    body = client.get(f"{LOOP}/plan", params=PLAN_Q).json()
    assert [c["node_id"] for c in body["concepts"]] == ["A"]
    for node, following in (("A", "B"), ("B", "T")):
        assert approve(body, [node]).status_code == 200
        probe.states.return_value[node] = (
            0.99  # represents the actual graph writer's new evidence posterior
        )
        finish_frontier(probe, node, observation=obs(node, channel="teachback_llm"))
        result = client.post(f"{LOOP}/check/next", json=NEXT)
        assert result.status_code == 200
        assert result.json()["phase"] == "plan"
        assert result.json()["check"] is None
        assert result.json()["goal_progress"]["status"] == "continue_available"
        resumed = client.get(f"{LOOP}/status", params=PLAN_Q).json()
        assert resumed["loop_phase"] == "plan"
        assert resumed["goal"]["target_node_ids"] == ["T"]
        assert resumed["goal_progress"] == result.json()["goal_progress"]
        assert probe.store["doc"]["plan"]["done"]  # old wave is not silently approved again
        body = client.get(f"{LOOP}/plan", params=PLAN_Q).json()
        assert [c["node_id"] for c in body["concepts"]] == [following]
        assert probe.store["doc"]["phase"] == "plan"
    assert approve(body, ["T"]).status_code == 200
    probe.states.return_value["T"] = 0.99
    finish_frontier(probe, "T", observation=obs("T"))
    result = client.post(f"{LOOP}/check/next", json=NEXT).json()
    assert result["plan_done"] and result["phase"] == "teach"
    assert result["goal_progress"]["status"] == "session_plan_finished"
    assert result["goal_progress"]["attempted_node_ids"] == ["A", "B", "T"]
    assert not probe.agu.called  # planning itself never invents evidence


@pytest.mark.parametrize(
    "extra",
    [
        {"max_rung": 1},
        {"same_session_recheck": True},
        {"previously_seen": True},
        {"independent": False},
    ],
)
def test_help_or_recheck_cannot_clear_a_failed_foundation_or_repeat_it_forever(probe, extra):
    probe.states.return_value = {"A": 0.99, "T": 0.99}
    probe.edges.return_value = [("A", "T")]
    body = proposal(probe)
    probe.store["doc"].setdefault("probe", {})["history"] = [
        obs("A", correct=False, key="diagnostic-A")
    ]
    body = client.get(f"{LOOP}/plan", params=PLAN_Q).json()
    assert approve(body, ["A"]).status_code == 200
    finish_frontier(probe, "A", observation=obs("A", **extra))
    response = client.post(f"{LOOP}/check/next", json=NEXT).json()
    assert response["phase"] == "teach" and response["plan_done"] is True
    assert response["goal_progress"]["status"] == "needs_more_practice"
    assert response["goal_progress"]["remaining_target_node_ids"] == ["T"]
    assert response["goal_progress"]["unresolved_prerequisite_ids"] == ["A"]
    assert probe.store["doc"]["plan"]["approved"] == ["A"]


def test_easier_correct_answer_does_not_erase_a_harder_independent_failure():
    history = [obs("A", correct=False, difficulty=3, key="miss"), obs("A", difficulty=1)]
    assert planner.planning_states({"A": 0.99}, history)["A"] < rl.BKT_PROFICIENT
    history.append(obs("A", difficulty=3, key="resolved"))
    assert planner.planning_states({"A": 0.99}, history)["A"] == 0.99


def test_missing_practice_bank_does_not_claim_target_practice_finished_or_loop(probe):
    probe.states.return_value = {"T": 0.99}
    probe.edges.return_value = []
    body = proposal(probe)
    assert approve(body, ["T"]).status_code == 200
    with (
        patch.object(rl, "_concept_key_for_node", return_value="concept-t"),
        patch.object(rl, "list_items", return_value=[]),
    ):
        response = client.post(f"{LOOP}/check/next", json=NEXT).json()
    assert response["phase"] == "teach" and response["plan_done"]
    assert response["goal_progress"]["status"] == "needs_more_practice"
    assert response["goal_progress"]["remaining_target_node_ids"] == ["T"]
    assert response["goal_progress"]["attempted_node_ids"] == ["T"]
    # A repeat is an honest bounded stop, never another approval of the same target.
    assert (
        client.post(f"{LOOP}/check/next", json=NEXT).json()["goal_progress"]
        == response["goal_progress"]
    )


def test_multiple_requested_targets_are_not_lost_after_a_chosen_subset(probe):
    probe.states.return_value = {"A": 0.99, "B": 0.99, "unrelated": 0.99}
    probe.edges.return_value = []
    probe.due.return_value = ["unrelated"]
    body = proposal(probe, ("A", "B"))
    assert {c["node_id"] for c in body["concepts"]} == {"A", "B"}
    assert approve(body, ["A"]).status_code == 200
    finish_frontier(probe, "A", observation=obs("A"))
    result = client.post(f"{LOOP}/check/next", json=NEXT).json()
    assert result["phase"] == "plan"
    assert result["goal_progress"]["remaining_target_node_ids"] == ["B"]
    fresh = client.get(f"{LOOP}/plan", params=PLAN_Q).json()
    assert [c["node_id"] for c in fresh["concepts"]] == ["B"]
    assert fresh["goal"]["target_node_ids"] == ["A", "B"]


def test_legacy_malformed_plan_metadata_cannot_claim_attempted_or_checked_goals():
    from learning.goals import attempted_nodes, planning_observations, progress

    state = {
        "goal": {"target_node_ids": ["T"]},
        "plan": "legacy",
        "steps": "legacy",
        "probe": "legacy",
    }
    assert attempted_nodes(state) == []
    assert planning_observations(state) == []
    assert progress(state, {"T": 0.99}, {"T"}, continue_available=False)[
        "remaining_target_node_ids"
    ] == ["T"]
    state["plan"] = {"attempted": "T", "checked_nodes": "T"}
    assert attempted_nodes(state) == []
    assert (
        progress(state, {"T": 0.99}, {"T"}, continue_available=False)["status"]
        == "needs_more_practice"
    )
