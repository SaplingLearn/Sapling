"""Route tests for the concept-description endpoint (routes/graph.py).

Backs the knowledge-map rail's on-demand concept blurb. Covers:
  - happy path returns the agent's description
  - oversized concept / course_label are truncated before the agent sees them
  - model / transport / validation failures translate to HTTP 502
  - empty concept is rejected with 400
  - unexpected exceptions still fall through to the generic 500 handler
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from pydantic_ai.exceptions import UnexpectedModelBehavior

from main import app
from routes.graph import _MAX_CONCEPT_LEN, _MAX_COURSE_LABEL_LEN

client = TestClient(app)

URL = "/api/graph/user_andres/concept-description"


def _result(description: str):
    r = MagicMock()
    r.output.description = description
    return r


# Stub the agent's async `run` so the handler never builds a real coroutine
# (the patched run_agent_sync ignores it). Keeps `run_agent_sync` as the single
# seam where we inject the success value or failure.
def _agent_run_stub():
    return patch("routes.graph.concept_describe_agent.run", MagicMock())


def test_happy_path_returns_description():
    with _agent_run_stub(), \
         patch("routes.graph.run_agent_sync", return_value=_result("Recursion is a function calling itself.")):
        resp = client.post(URL, json={"concept": "Recursion", "course_label": "CS 101"})
    assert resp.status_code == 200
    assert resp.json() == {"description": "Recursion is a function calling itself."}


def test_oversized_inputs_truncated_before_agent():
    seen = {}

    def spy_build(concept, course_label):
        seen["concept"] = concept
        seen["course_label"] = course_label
        return "msg"

    with _agent_run_stub(), \
         patch("routes.graph.build_message", side_effect=spy_build), \
         patch("routes.graph.run_agent_sync", return_value=_result("ok")):
        resp = client.post(URL, json={"concept": "x" * 500, "course_label": "y" * 300})

    assert resp.status_code == 200
    assert len(seen["concept"]) == _MAX_CONCEPT_LEN
    assert len(seen["course_label"]) == _MAX_COURSE_LABEL_LEN


def test_agent_failure_translates_to_502():
    with _agent_run_stub(), \
         patch("routes.graph.run_agent_sync", side_effect=UnexpectedModelBehavior("model exploded")):
        resp = client.post(URL, json={"concept": "Recursion"})
    assert resp.status_code == 502
    assert "concept-description agent failed" in resp.json()["detail"]


def test_empty_concept_rejected_with_400():
    resp = client.post(URL, json={"concept": "   "})
    assert resp.status_code == 400


def test_unexpected_exception_falls_through_to_500():
    # A non-LLM bug must NOT be masked as 502 — it goes to the generic handler.
    safe_client = TestClient(app, raise_server_exceptions=False)
    with _agent_run_stub(), \
         patch("routes.graph.run_agent_sync", side_effect=ValueError("bug")):
        resp = safe_client.post(URL, json={"concept": "Recursion"})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Internal server error."
