"""
Behavioral tests for the graph dedup constraints (#181, #195).

These cover the application side of the UNIQUE indexes added in
migration_dedup_unique.sql: the node insert recovers from a concurrent
unique-violation (409) instead of crashing, and edges are written via an
idempotent upsert keyed on the constraint columns.
"""
from unittest.mock import MagicMock, patch

import httpx

from services.graph_service import apply_graph_update


def _http_409() -> httpx.HTTPStatusError:
    resp = MagicMock()
    resp.status_code = 409
    return httpx.HTTPStatusError("conflict", request=MagicMock(), response=resp)


def _node(id_, name, course="c1", mastery=0.0, studied=0):
    return {"id": id_, "concept_name": name, "mastery_score": mastery,
            "times_studied": studied, "course_id": course, "mastery_events": []}


class TestNodeUniqueViolationRecovery:
    def test_concurrent_insert_409_is_recovered_not_raised(self):
        # Bulk fetch sees no node, so insert is attempted; a concurrent caller
        # already created it, so the DB returns 409. Recovery refetch returns
        # the winning row, and the same-concept update must target that row.
        winner = _node("win", "Recursion", mastery=0.4, studied=2)
        gn = MagicMock()
        select_calls = {"n": 0}

        def _select(*_a, **_k):
            select_calls["n"] += 1
            return [] if select_calls["n"] == 1 else [winner]

        gn.select.side_effect = _select
        gn.insert.side_effect = _http_409()
        gn.update.return_value = []

        def factory(name):
            if name == "graph_nodes":
                return gn
            m = MagicMock()
            m.select.return_value = (
                [{"streak_count": 0, "last_active_date": None}] if name == "users" else []
            )
            return m

        graph_update = {
            "new_nodes": [{"concept_name": "Recursion", "initial_mastery": 0.0}],
            "updated_nodes": [{"concept_name": "recursion", "mastery_delta": 0.2}],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            apply_graph_update("u1", graph_update, course_id="c1")

        gn.insert.assert_called_once()
        gn.update.assert_called_once()
        assert gn.update.call_args.kwargs["filters"] == {"id": "eq.win"}

    def test_non_409_error_still_propagates(self):
        gn = MagicMock()
        gn.select.return_value = []
        resp = MagicMock()
        resp.status_code = 500
        gn.insert.side_effect = httpx.HTTPStatusError(
            "boom", request=MagicMock(), response=resp
        )

        def factory(name):
            if name == "graph_nodes":
                return gn
            m = MagicMock()
            m.select.return_value = []
            return m

        graph_update = {
            "new_nodes": [{"concept_name": "Recursion", "initial_mastery": 0.0}],
            "updated_nodes": [],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            try:
                apply_graph_update("u1", graph_update, course_id="c1")
            except httpx.HTTPStatusError as exc:
                assert exc.response.status_code == 500
            else:
                raise AssertionError("non-409 error should not be swallowed")


class TestEdgeUpsert:
    def test_new_edge_is_upserted_on_constraint_columns(self):
        nodes = [_node("n1", "A"), _node("n2", "B")]
        gn = MagicMock()
        gn.select.return_value = nodes
        ge = MagicMock()
        ge.select.return_value = []  # no existing edge -> write path

        def factory(name):
            if name == "graph_nodes":
                return gn
            if name == "graph_edges":
                return ge
            m = MagicMock()
            m.select.return_value = (
                [{"streak_count": 0, "last_active_date": None}] if name == "users" else []
            )
            return m

        graph_update = {
            "new_nodes": [],
            "updated_nodes": [],
            "new_edges": [{"source": "A", "target": "B", "strength": 0.7}],
        }
        with patch("services.graph_service.table", side_effect=factory):
            apply_graph_update("u1", graph_update, course_id="c1")

        ge.insert.assert_not_called()
        ge.upsert.assert_called_once()
        assert ge.upsert.call_args.kwargs["on_conflict"] == (
            "user_id,source_node_id,target_node_id"
        )
