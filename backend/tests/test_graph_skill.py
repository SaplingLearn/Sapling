"""The learner model's skill on the graph's concepts (Tutor redesign phase 2:
one measure, `frontend/src/lib/levels.ts`). The route resolves the learning
loop's gate and then the student's `skill_ladder` flag once; with both on,
each concept carries `skill` / `skill_mastered`; else the response is the
graph as it was and the learner model is never read."""
from __future__ import annotations

from unittest.mock import patch

import pytest

import services.graph_service as gs
from learning.learner_state import LearnerState


def _state(node_id: str, p: float, opps: int, strong: int = 0) -> LearnerState:
    return LearnerState(user_id="u1", node_id=node_id, p_known=p, opps=opps, n_strong_unassisted=strong)


class TestAttachSkill:
    def test_a_measured_concept_carries_its_decayed_belief_rounded_for_the_wire(self):
        nodes = [{"id": "n1"}]
        gs._attach_skill(nodes, {"n1": _state("n1", 0.4567891, opps=2)})
        assert nodes == [{"id": "n1", "skill": 0.4568, "skill_mastered": False}]

    def test_no_row_or_a_propagated_prior_is_not_started_never_the_prior(self):
        nodes = [{"id": "n1"}, {"id": "n2"}]
        gs._attach_skill(nodes, {"n2": _state("n2", 0.62, opps=0)})
        assert [(n["skill"], n["skill_mastered"]) for n in nodes] == [(None, False), (None, False)]

    @pytest.mark.parametrize("p, strong, mastered", [
        (0.985, 3, True),    # the backend's rule: ≥ 98% and three strong unassisted answers
        (0.985, 2, False),   # belief alone is never enough
        (0.97, 5, False),
    ])
    def test_mastered_is_the_backend_rule_on_the_decayed_belief(self, p, strong, mastered):
        nodes = [{"id": "n1"}]
        gs._attach_skill(nodes, {"n1": _state("n1", p, opps=6, strong=strong)})
        assert nodes[0]["skill_mastered"] is mastered

    def test_subject_roots_carry_neither(self):
        nodes = [{"id": "subject_root__c1", "is_subject_root": True}]
        gs._attach_skill(nodes, {})
        assert nodes == [{"id": "subject_root__c1", "is_subject_root": True}]


def _client_get(captured: dict, path: str = "/api/graph/user_a"):
    from fastapi.testclient import TestClient
    import routes.graph as graph_route
    from main import app

    async def fake_get_graph(user_id, semester=None, *, skill=False):
        captured["skill"] = skill
        return {"nodes": [], "edges": [], "stats": {}}

    with patch.object(graph_route, "aget_graph", side_effect=fake_get_graph):
        return TestClient(app).get(path)


def test_the_route_asks_for_skill_with_the_loop_and_skill_ladder_on(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_SKILL_LADDER", "on")
    captured: dict = {}
    resp = _client_get(captured)
    assert resp.status_code == 200
    assert captured == {"skill": True}


def test_skill_ladder_off_is_the_graph_as_it_was_even_with_the_loop_on():
    captured: dict = {}  # skill_ladder's default is off
    resp = _client_get(captured)
    assert resp.status_code == 200
    assert captured == {"skill": False}


@pytest.mark.kill_switch
def test_the_route_asks_for_none_with_the_loop_off(loop_off_via, monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_SKILL_LADDER", "on")  # the loop's gate comes first
    captured: dict = {}
    resp = _client_get(captured)
    assert resp.status_code == 200
    assert captured == {"skill": False}


@pytest.mark.parametrize("asynchronous", [False, True])
def test_skill_off_never_reads_the_learner_model_and_adds_no_field(asynchronous):
    import asyncio
    import copy

    from tests.db_fakes import with_async_twins
    from tests.test_graph_service import _PARITY_GRAPHS, _cached_mock_table

    factory, _ = _cached_mock_table(copy.deepcopy(_PARITY_GRAPHS["full"]))
    with patch("services.graph_service.read_states") as read, \
         patch("services.graph_service.table", side_effect=with_async_twins(factory)):
        graph = asyncio.run(gs.aget_graph("u1")) if asynchronous else gs.get_graph("u1")
    read.assert_not_called()
    assert graph["nodes"]
    assert all("skill" not in n and "skill_mastered" not in n for n in graph["nodes"])
