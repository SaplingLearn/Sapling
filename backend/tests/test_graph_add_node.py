"""Tests for the manual add-concept path (#330): graph_service.add_node and
POST /api/graph/{user_id}/nodes.

add_node is a thin wrapper over apply_graph_update — the dedup/merge and
analytics-refresh machinery stays in one place (routes never write
graph_nodes/graph_edges directly), so these tests pin the ORCHESTRATION:
the pre-check that reports merge-vs-create, the anchor-id → name resolution
that feeds the edge (apply_graph_update resolves edges by name), and the
canonical read-back. Supabase is mocked per tests/test_graph_service.py's
idiom; apply_graph_update itself is patched (its behavior has its own suite).
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
import routes.graph as graph_routes
import services.graph_service as gs

client = TestClient(app)

ANCHOR = {"id": "n-root", "concept_name": "Math 210", "course_id": "c1"}
CREATED = {
    "id": "n-new", "concept_name": "Recursion", "course_id": "c1",
    "mastery_score": 0.0, "mastery_tier": "unexplored",
}


def _graph_nodes_mock(select_side_effect):
    """One cached graph_nodes mock whose .select returns follow the given
    sequence; other tables return empty lists."""
    nodes = MagicMock()
    nodes.select.side_effect = select_side_effect

    def factory(name):
        if name == "graph_nodes":
            return nodes
        other = MagicMock()
        other.select.return_value = []
        return other
    return factory, nodes


class TestAddNodeService:
    def test_creates_via_apply_graph_update_with_anchor_edge(self):
        # selects: pre-check (no match) → anchor lookup → canonical read-back
        factory, _ = _graph_nodes_mock([[], [ANCHOR], [CREATED]])
        with patch.object(gs, "table", side_effect=factory), \
             patch.object(gs, "apply_graph_update", return_value=[]) as agu:
            out = gs.add_node("u1", "  Recursion ", "c1", anchor_node_id="n-root")

        assert out["already_existed"] is False
        assert out["node"]["id"] == "n-new"
        agu.assert_called_once()
        update = agu.call_args.args[1]
        assert update["new_nodes"] == [
            {"concept_name": "Recursion", "course_id": "c1", "initial_mastery": 0.0},
        ]
        # The edge feeds apply_graph_update by NAME (its _lookup is name-keyed).
        assert update["new_edges"][0]["source"] == "Math 210"
        assert update["new_edges"][0]["target"] == "Recursion"
        assert agu.call_args.kwargs.get("course_id") == "c1"

    def test_merge_reports_already_existed(self):
        existing = {**CREATED, "id": "n-1", "mastery_score": 0.4, "mastery_tier": "learning"}
        # pre-check finds the (case-insensitively) matching row; no anchor;
        # read-back returns the surviving row.
        factory, _ = _graph_nodes_mock([[existing], [existing]])
        with patch.object(gs, "table", side_effect=factory), \
             patch.object(gs, "apply_graph_update", return_value=[]):
            out = gs.add_node("u1", "recursion", "c1")

        assert out["already_existed"] is True
        assert out["node"]["id"] == "n-1"

    def test_missing_anchor_creates_node_without_edge(self):
        # anchor id resolves to nothing (deleted mid-flight) — node still lands.
        factory, _ = _graph_nodes_mock([[], [], [CREATED]])
        with patch.object(gs, "table", side_effect=factory), \
             patch.object(gs, "apply_graph_update", return_value=[]) as agu:
            out = gs.add_node("u1", "Recursion", "c1", anchor_node_id="n-gone")

        assert out["already_existed"] is False
        assert "new_edges" not in agu.call_args.args[1]

    def test_blank_name_raises(self):
        with pytest.raises(ValueError):
            gs.add_node("u1", "   ", "c1")


class TestAddNodeRoute:
    def test_post_returns_node_and_flag(self, monkeypatch):
        monkeypatch.setattr(
            graph_routes, "add_node",
            lambda user_id, concept_name, course_id, anchor_node_id=None: {
                "node": CREATED, "already_existed": False,
            },
        )
        r = client.post("/api/graph/u1/nodes", json={"concept_name": "Recursion", "course_id": "c1"})
        assert r.status_code == 200
        body = r.json()
        assert body["node"]["id"] == "n-new"
        assert body["already_existed"] is False

    def test_post_whitespace_name_is_422(self):
        r = client.post("/api/graph/u1/nodes", json={"concept_name": "   ", "course_id": "c1"})
        assert r.status_code == 422

    def test_post_missing_course_is_422(self):
        r = client.post("/api/graph/u1/nodes", json={"concept_name": "Recursion"})
        assert r.status_code == 422

    def test_post_requires_self(self, monkeypatch):
        from fastapi import HTTPException

        def _deny(user_id, request):
            raise HTTPException(status_code=403, detail="Forbidden")

        monkeypatch.setattr(graph_routes, "require_self", _deny)
        r = client.post("/api/graph/u1/nodes", json={"concept_name": "Recursion", "course_id": "c1"})
        assert r.status_code == 403
