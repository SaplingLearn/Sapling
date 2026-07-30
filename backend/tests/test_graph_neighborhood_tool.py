"""Unit tests for read_graph_neighborhood (#149, agents/tools/graph_read.py).

Covers the acceptance points from the scoping brief:
  - seed matching via graph_service._normalize_concept (case/whitespace);
  - depth-1 edge expansion (neighbors of seeds come back, by name);
  - node ids NEVER leak across the tool boundary;
  - limit + truncated flag;
  - course scoping (other-course edge endpoints dropped);
  - other-user exclusion (filters carry user_id on every read);
  - empty graph and DB-raise both degrade to an empty neighborhood;
  - read-only invariant: deps.graph_updates / deps.mastery_changes stay
    untouched when the tool wrapper runs.

Mocks `db.connection.table` via the imported reference inside
`agents.tools.graph_read`, mirroring tests/test_graph_read_tools.py.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from agents.deps import SaplingDeps
from agents.tools.graph_read import (
    GraphNeighborhood,
    read_graph_neighborhood,
    read_graph_neighborhood_tool,
)


def _run(coro):
    return asyncio.run(coro)


# Course-scoped nodes the mocked graph_nodes read returns.
NODES = [
    {"id": "n1", "concept_name": "Linear Regression", "mastery_score": 0.4,
     "mastery_tier": "struggling", "last_studied_at": "2026-07-01T00:00:00Z"},
    {"id": "n2", "concept_name": "Gradient Descent", "mastery_score": 0.6,
     "mastery_tier": "learning", "last_studied_at": None},
    {"id": "n3", "concept_name": "Loss Functions", "mastery_score": 0.2,
     "mastery_tier": "struggling", "last_studied_at": None},
    {"id": "n4", "concept_name": "Overfitting", "mastery_score": 0.8,
     "mastery_tier": "mastered", "last_studied_at": None},
]

# Depth-1 edges: n1—n2, n2—n3; n4 is disconnected. Edge to n99 points at a
# node OUTSIDE the course-scoped read (another course) and must be dropped.
EDGES = [
    {"source_node_id": "n1", "target_node_id": "n2",
     "relationship_type": "builds_on", "strength": 0.7},
    {"source_node_id": "n2", "target_node_id": "n3",
     "relationship_type": "related", "strength": 0.5},
    {"source_node_id": "n1", "target_node_id": "n99",
     "relationship_type": "related", "strength": 0.9},
]


class _FakeTable:
    """Dispatches on table name; records every select's filters."""

    def __init__(self, calls: list, nodes=None, edges=None, raise_on=None):
        self._calls = calls
        self._nodes = NODES if nodes is None else nodes
        self._edges = EDGES if edges is None else edges
        self._raise_on = raise_on or set()
        self._name = None

    def __call__(self, name):
        self._name = name
        return self

    def select(self, columns, filters=None, **kwargs):
        self._calls.append({"table": self._name, "filters": dict(filters or {})})
        if self._name in self._raise_on:
            raise RuntimeError("boom")
        if self._name == "graph_nodes":
            return list(self._nodes)
        if self._name == "graph_edges":
            f = filters or {}
            in_clause = f.get("source_node_id") or f.get("target_node_id") or ""
            ids = set(in_clause[len("in.("):-1].split(",")) if in_clause else set()
            key = "source_node_id" if "source_node_id" in f else "target_node_id"
            return [e for e in self._edges if e[key] in ids]
        return []


def test_seed_match_is_case_and_whitespace_insensitive():
    calls: list = []
    with patch("agents.tools.graph_read.table", _FakeTable(calls)):
        out = _run(
            read_graph_neighborhood("u1", "c1", ["  linear   REGRESSION "])
        )
    names = [c.concept_name for c in out.concepts]
    assert "Linear Regression" in names


def test_depth_one_expansion_returns_neighbors_but_not_two_hops():
    calls: list = []
    with patch("agents.tools.graph_read.table", _FakeTable(calls)):
        out = _run(read_graph_neighborhood("u1", "c1", ["Linear Regression"]))
    names = {c.concept_name for c in out.concepts}
    # n2 is one hop from the seed; n3 is two hops (edge n2→n3 doesn't touch
    # the seed, so the depth-1 edge reads never return it); n4 disconnected.
    assert names == {"Linear Regression", "Gradient Descent"}
    assert {(e.source, e.target) for e in out.edges} == {
        ("Linear Regression", "Gradient Descent")
    }
    assert out.edges[0].relationship_type == "builds_on"
    assert out.edges[0].strength == 0.7


def test_node_ids_never_leak():
    calls: list = []
    with patch("agents.tools.graph_read.table", _FakeTable(calls)):
        out = _run(read_graph_neighborhood("u1", "c1", ["Linear Regression"]))
    dumped = json.dumps(out.model_dump())
    for node_id in ("n1", "n2", "n3", "n4", "n99"):
        assert f'"{node_id}"' not in dumped, f"row id {node_id} leaked: {dumped}"


def test_limit_caps_concepts_and_sets_truncated():
    calls: list = []
    with patch("agents.tools.graph_read.table", _FakeTable(calls)):
        out = _run(
            read_graph_neighborhood("u1", "c1", ["Linear Regression"], limit=1)
        )
    assert len(out.concepts) == 1
    assert out.concepts[0].concept_name == "Linear Regression"  # seeds first
    assert out.truncated is True
    # Edges to dropped concepts must not dangle.
    assert out.edges == []


def test_no_truncation_flag_when_under_limit():
    calls: list = []
    with patch("agents.tools.graph_read.table", _FakeTable(calls)):
        out = _run(read_graph_neighborhood("u1", "c1", ["Linear Regression"]))
    assert out.truncated is False


def test_course_scoping_drops_other_course_edge_endpoints():
    """The n1→n99 edge points outside the course-scoped node read; neither
    the edge nor the foreign concept may appear."""
    calls: list = []
    with patch("agents.tools.graph_read.table", _FakeTable(calls)):
        out = _run(read_graph_neighborhood("u1", "c1", ["Linear Regression"]))
    assert all("n99" not in (e.source, e.target) for e in out.edges)
    node_calls = [c for c in calls if c["table"] == "graph_nodes"]
    assert node_calls[0]["filters"]["course_id"] == "eq.c1"


def test_every_read_is_user_scoped():
    calls: list = []
    with patch("agents.tools.graph_read.table", _FakeTable(calls)):
        _run(read_graph_neighborhood("u1", "c1", ["Linear Regression"]))
    assert calls, "expected at least one table read"
    for c in calls:
        assert c["filters"].get("user_id") == "eq.u1", (
            f"unscoped read against {c['table']}: {c['filters']}"
        )


def test_unknown_seeds_return_empty_without_edge_reads():
    calls: list = []
    with patch("agents.tools.graph_read.table", _FakeTable(calls)):
        out = _run(read_graph_neighborhood("u1", "c1", ["Quantum Chromodynamics"]))
    assert out == GraphNeighborhood(concepts=[], edges=[], truncated=False)
    assert [c["table"] for c in calls] == ["graph_nodes"], (
        "no seed matched — the edge reads must be skipped"
    )


def test_empty_graph_returns_empty():
    calls: list = []
    with patch("agents.tools.graph_read.table", _FakeTable(calls, nodes=[], edges=[])):
        out = _run(read_graph_neighborhood("u1", "c1", ["Linear Regression"]))
    assert out == GraphNeighborhood(concepts=[], edges=[], truncated=False)


def test_db_raise_degrades_to_empty_never_raises():
    calls: list = []
    fake = _FakeTable(calls, raise_on={"graph_nodes"})
    with patch("agents.tools.graph_read.table", fake):
        out = _run(read_graph_neighborhood("u1", "c1", ["Linear Regression"]))
    assert out == GraphNeighborhood(concepts=[], edges=[], truncated=False)

    calls2: list = []
    fake2 = _FakeTable(calls2, raise_on={"graph_edges"})
    with patch("agents.tools.graph_read.table", fake2):
        out2 = _run(read_graph_neighborhood("u1", "c1", ["Linear Regression"]))
    assert out2 == GraphNeighborhood(concepts=[], edges=[], truncated=False)


# ── tool wrapper ──────────────────────────────────────────────────────────


class _Ctx:
    def __init__(self, deps):
        self.deps = deps


def _deps() -> SaplingDeps:
    return SaplingDeps(
        user_id="u1", course_id="c1", supabase=None, request_id="r1",
        session_id="s1",
    )


def test_tool_wrapper_injects_deps_ids_and_is_read_only():
    """The wrapper takes ids from deps (LLM supplies only concepts/limit),
    and a read never touches the write accumulators."""
    calls: list = []
    deps = _deps()
    with patch("agents.tools.graph_read.table", _FakeTable(calls)):
        out = _run(
            read_graph_neighborhood_tool(_Ctx(deps), ["Linear Regression"], limit=5)
        )
    assert {c.concept_name for c in out.concepts} == {
        "Linear Regression", "Gradient Descent"
    }
    for c in calls:
        assert c["filters"].get("user_id") == "eq.u1"
    # Read-only invariant (#149): graph read tools must never write.
    assert deps.graph_updates == []
    assert deps.mastery_changes == []


def test_tool_wrapper_honors_injected_retrieval():
    """A deps-injected TutorRetrieval (the eval seam) is used instead of
    Supabase — no table() call at all."""

    class _FakeRetrieval:
        def __init__(self):
            self.calls = []

        async def graph_neighborhood(self, user_id, course_id, concepts, *, limit=20):
            self.calls.append((user_id, course_id, tuple(concepts), limit))
            return GraphNeighborhood(concepts=[], edges=[], truncated=False)

    fake = _FakeRetrieval()
    deps = SaplingDeps(
        user_id="u1", course_id="c1", supabase=None, request_id="r1",
        retrieval=fake,
    )
    with patch("agents.tools.graph_read.table") as t:
        out = _run(read_graph_neighborhood_tool(_Ctx(deps), ["X"], limit=3))
    t.assert_not_called()
    assert fake.calls == [("u1", "c1", ("X",), 3)]
    assert out.concepts == []
