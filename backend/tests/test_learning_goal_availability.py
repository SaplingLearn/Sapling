"""Real goal/plan/CAS handlers preflight the same bank as check activation."""

import copy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import routes.learn_loop as rl
from learning.checks import posttest_reserve_hash
from test_learning_goal_integrity import approve, proposal
from test_learning_goals import _open_write_harness as _open_write_harness, set_goal
from test_learning_probe_planner import LOOP, NEXT, PLAN_Q, _node_items, client, probe as probe

_REAL_PREFLIGHT = rl._goal_practice_unavailable


@pytest.fixture
def bank(probe):
    probe.practice.side_effect = _REAL_PREFLIGHT
    probe.ai_budget.check.return_value = SimpleNamespace(pause_novice=False)
    assets = {node: _node_items(node, 3) for node in ("A", "B", "T", "K")}
    with (
        patch.object(rl, "_concept_key_for_node", side_effect=lambda _u, node: node),
        patch.object(rl, "list_items", side_effect=lambda _c, key: assets.get(key, [])) as listed,
        patch.object(rl, "get_check_item", side_effect=lambda item_id: next(
            (item for items in assets.values() for item in items if item.id == item_id), None,
        )),
        patch.object(rl, "_band_for", return_value=("novice", 0.2)),
        patch.object(rl, "_ledger"),
        patch.object(rl, "save_message"),
    ):
        yield SimpleNamespace(assets=assets, listed=listed)


def foundation(probe):
    probe.states.return_value = {"A": 0.2, "T": 0.3}
    probe.edges.return_value = [("A", "T")]


def exhaust(probe, bank, node="A"):
    reserve = posttest_reserve_hash(bank.assets[node])
    used = {item.question_hash for item in bank.assets[node] if item.question_hash != reserve}
    probe.seen.return_value = used
    probe.revealed.return_value = used


def test_exhausted_prerequisite_is_explicit_before_approval_not_skipped_or_assessed(probe, bank):
    foundation(probe)
    bank.assets["A"] = _node_items("A", 17)
    exhaust(probe, bank)
    body = proposal(probe)
    assert body["concepts"] == [] and body["empty"] and body["phase"] == "teach"
    assert body["practice_unavailable_node_ids"] == ["A"]
    assert body["goal_progress"]["status"] == "needs_more_practice"
    assert body["goal_progress"]["unresolved_prerequisite_ids"] == ["A"]
    assert body["goal_progress"]["remaining_target_node_ids"] == ["T"]
    assert body["goal_progress"]["attempted_node_ids"] == []
    doc = probe.store["doc"]
    assert doc["plan"]["approved"] == [] and "concept" not in doc
    assert not doc["plan"].get("checked_nodes") and not doc.get("steps")
    resumed = client.get(f"{LOOP}/status", params=PLAN_Q).json()
    assert resumed["practice_unavailable_node_ids"] == ["A"]
    assert not probe.agu.called and not probe.grade.called


@pytest.mark.parametrize("inventory", ["empty", "posttest_only", "unservable", "session_used"])
def test_only_reserved_or_unusable_items_do_not_make_a_goal_checkable(probe, bank, inventory):
    foundation(probe)
    if inventory == "empty":
        bank.assets["A"] = []
    elif inventory == "posttest_only":
        bank.assets["A"] = bank.assets["A"][:1]
    elif inventory == "unservable":
        for item in bank.assets["A"][1:]:
            item.item.final_answer = None
    else:
        assert set_goal(("T",)).status_code == 200
        probe.store["doc"]["steps"] = {item.question_hash: {"rung": 0, "first_shown_at": rl._now_s()}
                                      for item in bank.assets["A"][1:]}
        probe.store["doc"]["phase"] = "plan"
        body = client.get(f"{LOOP}/plan", params=PLAN_Q).json()
        assert body["practice_unavailable_node_ids"] == ["A"] and body["concepts"] == []
        return
    body = proposal(probe)
    assert body["practice_unavailable_node_ids"] == ["A"] and body["concepts"] == []


def test_one_fresh_probe_practice_reserve_can_be_approved_and_actually_posed(probe, bank):
    foundation(probe)
    bank.assets["A"] = bank.assets["A"][:2]
    fresh = bank.assets["A"][1]
    assert set_goal(("T",)).status_code == 200
    probe.store["doc"].update({"phase": "plan", "probe": {"practice_reserves": {"A": fresh.question_hash}}})
    body = client.get(f"{LOOP}/plan", params=PLAN_Q).json()
    assert [concept["node_id"] for concept in body["concepts"]] == ["A"]
    assert body["practice_unavailable_node_ids"] == []
    assert approve(body, ["A"]).status_code == 200
    response = client.post(f"{LOOP}/check/next", json=NEXT)
    assert response.status_code == 200 and response.json()["check"]["question_hash"] == fresh.question_hash
    assert fresh.question_hash != posttest_reserve_hash(bank.assets["A"])
    assert not probe.agu.called and not probe.grade.called


def test_unavailable_foundation_does_not_hide_an_independent_available_goal(probe, bank):
    probe.states.return_value = {"A": 0.2, "T": 0.3, "B": 0.4}
    probe.edges.return_value = [("A", "T")]
    exhaust(probe, bank)
    body = proposal(probe, ("T", "B"))
    assert [concept["node_id"] for concept in body["concepts"]] == ["B"]
    assert body["practice_unavailable_node_ids"] == ["A"]
    assert approve(body, ["B"]).status_code == 200
    assert probe.store["doc"]["plan"]["approved"] == ["B"]


@pytest.mark.parametrize("during_cas", [False, True])
def test_depletion_between_proposal_and_approval_preserves_plan_and_rejects_stale_approval(probe, bank, during_cas):
    foundation(probe)
    body = proposal(probe)
    before = copy.deepcopy(probe.store["doc"])
    if during_cas:
        probe.store["conflicts"] = 1
        probe.store["racer"] = lambda _doc: exhaust(probe, bank)
    else:
        exhaust(probe, bank)
    response = approve(body, ["A"])
    assert response.status_code == 409
    assert response.json()["detail"] == "Fresh practice is unavailable; review the current plan"
    assert probe.store["doc"] == before
    refreshed = client.get(f"{LOOP}/plan", params=PLAN_Q).json()
    assert refreshed["concepts"] == [] and refreshed["practice_unavailable_node_ids"] == ["A"]
    assert not probe.agu.called and not probe.grade.called


def test_preflight_source_review_can_discover_genuinely_new_questions_without_resetting_history(probe, bank):
    foundation(probe)
    exhaust(probe, bank)
    body = proposal(probe)
    version = body["goal_version"]
    history = copy.deepcopy(probe.store["doc"].get("probe"))
    new_item = _node_items("A", 18)[-1]
    bank.assets["A"].append(new_item)
    response = client.post(f"{LOOP}/check/next", json=NEXT).json()
    assert response["phase"] == "plan" and response["check"] is None
    assert response["practice_unavailable_node_ids"] == []
    assert probe.store["doc"]["plan"]["approved"] == []  # not autoapproved
    refreshed = client.get(f"{LOOP}/plan", params=PLAN_Q).json()
    assert refreshed["goal_version"] == version
    assert [concept["node_id"] for concept in refreshed["concepts"]] == ["A"]
    assert probe.store["doc"].get("probe") == history
    assert refreshed["goal_progress"]["attempted_node_ids"] == []
    assert approve(refreshed, ["A"]).status_code == 200
    assert client.post(f"{LOOP}/check/next", json=NEXT).json()["check"]["question_hash"] == new_item.question_hash


def test_depletion_after_approval_is_an_honest_bounded_attempt_not_a_reset_on_replenishment(probe, bank):
    foundation(probe)
    body = proposal(probe)
    assert approve(body, ["A"]).status_code == 200
    exhaust(probe, bank)
    response = client.post(f"{LOOP}/check/next", json=NEXT).json()
    assert response["check"] is None and response["plan_done"]
    assert response["practice_unavailable_node_ids"] == ["A"]
    assert response["goal_progress"]["attempted_node_ids"] == ["A"]
    assert not probe.store["doc"]["plan"].get("checked_nodes")
    bank.assets["A"].append(_node_items("A", 18)[-1])
    repeated = client.post(f"{LOOP}/check/next", json=NEXT).json()
    assert repeated["phase"] == "teach" and repeated["check"] is None
    assert repeated["goal_progress"]["status"] == "needs_more_practice"
    assert repeated["goal_progress"]["attempted_node_ids"] == ["A"]
    assert not probe.agu.called and not probe.grade.called


@pytest.mark.parametrize("endpoint", ["proposal", "approval", "activation"])
def test_availability_read_failure_is_retryable_not_an_empty_bank_or_state_change(probe, bank, endpoint):
    foundation(probe)
    body = proposal(probe)
    if endpoint == "activation":
        assert approve(body, ["A"]).status_code == 200
    before = copy.deepcopy(probe.store["doc"])
    bank.listed.side_effect = RuntimeError("storage outage")
    response = (client.get(f"{LOOP}/plan", params=PLAN_Q) if endpoint == "proposal"
                else approve(body, ["A"]) if endpoint == "approval"
                else client.post(f"{LOOP}/check/next", json=NEXT))
    assert response.status_code == 503
    assert response.json()["detail"] == "Practice availability unavailable; retry"
    assert probe.store["doc"] == before
    assert not probe.agu.called and not probe.grade.called


def test_coursewide_plan_keeps_existing_teaching_only_behavior_without_new_preflight(probe, bank):
    probe.store["doc"]["phase"] = "plan"
    probe.practice.side_effect = AssertionError("whole-course planning must not add a bank preflight")
    body = client.get(f"{LOOP}/plan", params=PLAN_Q).json()
    assert body["concepts"] and "practice_unavailable_node_ids" not in body


def test_status_metadata_does_not_read_capacity_after_a_recorded_grade(probe, bank):
    foundation(probe)
    body = proposal(probe)
    assert approve(body, ["A"]).status_code == 200
    probe.store["doc"]["plan"]["practice_unavailable_node_ids"] = ["A"]
    bank.listed.side_effect = AssertionError("presentation must not perform a new capacity read")
    response = client.get(f"{LOOP}/status", params=PLAN_Q)
    assert response.status_code == 200 and response.json()["practice_unavailable_node_ids"] == ["A"]
