"""routes/graph.py's read handlers on the async DB seam (#117; wave 1 of
docs/design/async-db-client.md §4.1).

End to end over the REAL ``SupabaseTable`` onto an ``httpx.MockTransport``
(the ``wire`` fixture from test_async_handlers_off_loop.py, which turns on
``no_sync_db_on_loop`` and fails if any sync PostgREST request left from an
event-loop thread), with ``async_db_client`` off and on: the same answers,
and with the flag on the handler reads go out on the native client.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

import routes.graph as graph_routes
from main import app
from tests.test_async_handlers_off_loop import Wire, wire  # noqa: F401 (fixture)

client = TestClient(app)

_NODES = [
    {"id": "n1", "concept_name": "Loops", "mastery_tier": "learning",
     "mastery_score": 0.5, "course_id": "c1", "times_studied": 2, "user_id": "user_andres"},
]
_ENROLLMENTS = [{
    "id": "e1", "offering_id": "off-1", "color": "#123456", "nickname": None,
    "enrolled_at": "2026-01-01",
    "course_offerings": {"course_id": "c1",
                         "courses": {"course_code": "CS101", "course_name": "Intro CS",
                                     "department": "CS"},
                         "terms": {"label": "Spring 2026"}},
}]


def test_read_handlers_are_async_and_writes_stay_sync():
    for name in ("get_user_graph", "get_user_recommendations", "list_courses"):
        assert inspect.iscoroutinefunction(getattr(graph_routes, name)), name
    # Writes (graph_service write paths) and the LLM call (run_agent_sync)
    # have no async form yet: plain defs, run in the threadpool by FastAPI.
    for name in ("create_course", "set_course_color", "remove_course", "create_node",
                 "remove_node", "set_node_color", "describe_concept"):
        assert not inspect.iscoroutinefunction(getattr(graph_routes, name)), name


def _seed(w: Wire) -> None:
    w.rows[("GET", "users")] = [{"id": "user_andres", "streak_count": 0,
                                 "last_active_date": None}]
    w.rows[("GET", "enrollments")] = _ENROLLMENTS
    w.rows[("GET", "graph_nodes")] = _NODES
    w.rows[("GET", "graph_edges")] = []
    w.rows[("GET", "node_mastery_events")] = []


def _assert_mode(w: Wire, mode: str, reads: set[tuple[str, str]]) -> None:
    if mode == "on":
        assert reads <= set(w.native)
        assert not reads & {(m, n) for m, n, _ in w.calls}
    else:
        assert w.native == []
        assert reads <= {(m, n) for m, n, _ in w.calls}


@pytest.mark.parametrize("async_mode", ["off", "on"])
def test_get_graph(wire, monkeypatch, async_mode):  # noqa: F811
    monkeypatch.setenv("SAPLING_FLAG_ASYNC_DB_CLIENT", async_mode)
    _seed(wire)
    r = client.get("/api/graph/user_andres")
    assert r.status_code == 200, r.text
    body = r.json()
    assert {n["id"] for n in body["nodes"]} == {"n1", "subject_root__c1"}
    assert body["stats"]["total_nodes"] == 1
    _assert_mode(wire, async_mode, {
        ("GET", "users"), ("GET", "enrollments"), ("GET", "graph_nodes"),
        ("GET", "graph_edges"), ("GET", "node_mastery_events"),
    })


@pytest.mark.parametrize("async_mode", ["off", "on"])
def test_get_graph_semester_lookup_runs_off_the_loop(wire, monkeypatch, async_mode):  # noqa: F811
    monkeypatch.setenv("SAPLING_FLAG_ASYNC_DB_CLIENT", async_mode)
    _seed(wire)
    wire.rows[("GET", "terms")] = [{"id": "t-spring"}]
    wire.rows[("GET", "course_offerings")] = [{"id": "off-1", "course_id": "c1"}]
    wire.rows[("GET", "enrollments")] = _ENROLLMENTS
    r = client.get("/api/graph/user_andres", params={"semester": "Spring 2026"})
    assert r.status_code == 200, r.text
    # services/academics.py is sync: it went through the sync client, off the loop.
    assert wire.to("GET", "terms") and not any(wire.to("GET", "terms"))


@pytest.mark.parametrize("async_mode", ["off", "on"])
def test_recommendations(wire, monkeypatch, async_mode):  # noqa: F811
    monkeypatch.setenv("SAPLING_FLAG_ASYNC_DB_CLIENT", async_mode)
    _seed(wire)
    r = client.get("/api/graph/user_andres/recommendations")
    assert r.status_code == 200, r.text
    assert [x["concept_name"] for x in r.json()["recommendations"]] == ["Loops"]
    _assert_mode(wire, async_mode, {("GET", "graph_nodes")})


@pytest.mark.parametrize("async_mode", ["off", "on"])
def test_list_courses(wire, monkeypatch, async_mode):  # noqa: F811
    monkeypatch.setenv("SAPLING_FLAG_ASYNC_DB_CLIENT", async_mode)
    _seed(wire)
    r = client.get("/api/graph/user_andres/courses")
    assert r.status_code == 200, r.text
    (course,) = r.json()["courses"]
    assert course["course_id"] == "c1" and course["node_count"] == 1
    assert course["term"] == "Spring 2026" and course["color"] == "#123456"
    _assert_mode(wire, async_mode, {("GET", "enrollments"), ("GET", "graph_nodes")})
