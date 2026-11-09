"""Route tests for the concept-description endpoint (routes/graph.py).

Backs the knowledge-map rail's on-demand concept blurb. Covers:
  - happy path returns the agent's description
  - oversized concept / course_label are truncated before the agent sees them
  - model / transport / validation failures translate to HTTP 502
  - an UnregisteredHandlerError (function-mode seam with no registered
    handler, #446) degrades the same way rather than a bare 500
  - empty concept is rejected with 400
  - unexpected exceptions — including a bare KeyError/IndexError, the
    LookupError builtin's other subclasses (#446 PR review) — still fall
    through to the generic 500 handler rather than being caught by the
    route's over-broad-if-it-were-`except LookupError` clause
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fastapi.testclient import TestClient
from pydantic_ai.exceptions import UnexpectedModelBehavior

from agents._providers import UnregisteredHandlerError
from main import app
from routes.graph import _MAX_CONCEPT_LEN, _MAX_COURSE_LABEL_LEN

# #117: a sync PostgREST call reached on the event loop raises here.
pytestmark = pytest.mark.usefixtures("no_sync_db_on_loop")

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


def test_unregistered_handler_error_translates_to_502():
    # #446: SAPLING_MODEL_MODE=function with no handler registered for
    # 'concept_describe' raises UnregisteredHandlerError out of the dispatch
    # seam (agents/_providers.py::_dispatch). A misconfigured seam is an
    # upstream problem, not a route bug — it must degrade the same way
    # AgentRunError does, not 500.
    with _agent_run_stub(), \
         patch(
             "routes.graph.run_agent_sync",
             side_effect=UnregisteredHandlerError(
                 "SAPLING_MODEL_MODE=function but no handler is registered "
                 "for task 'concept_describe'"
             ),
         ):
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


def test_unrelated_key_error_falls_through_to_500():
    # #446 PR review (empirical repro): LookupError is the builtin base class
    # of KeyError/IndexError. A prior version of the route caught bare
    # `LookupError`, which silently converted an unrelated KeyError bug deep
    # in the agent-run path (e.g. pydantic-ai response handling) into this
    # endpoint's 502 "concept-description agent failed" instead of letting it
    # surface as the generic 500 like any other unexpected bug. The route now
    # catches the specific `UnregisteredHandlerError` subclass only, so a bare
    # KeyError must still fall through here.
    safe_client = TestClient(app, raise_server_exceptions=False)
    with _agent_run_stub(), \
         patch("routes.graph.run_agent_sync", side_effect=KeyError("some_unrelated_bug")):
        resp = safe_client.post(URL, json={"concept": "Recursion"})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Internal server error."



# ── Budget refusal (#119; release doc wave 2 §11) ─────────────────────────────


def _refusal():
    from datetime import datetime, timedelta, timezone

    from services.llm_budget import LLMBudgetExceeded

    return LLMBudgetExceeded(
        limit=10, used=12, reset_at=datetime.now(timezone.utc) + timedelta(hours=2))


def _assert_friendly_429(resp):
    from services.llm_budget import ERROR_CODE

    assert resp.status_code == 429, resp.text
    body = resp.json()
    # main.py's LLMBudgetExceeded handler: the same 429 the tutor and uploads
    # answer with, never "concept-description agent failed".
    assert body["error"]["code"] == ERROR_CODE
    assert body["error"]["reset_at"]
    assert "limit for AI features" in body["detail"]
    assert int(resp.headers["Retry-After"]) > 0


def test_budget_refusal_from_the_agent_run_is_the_friendly_429():
    """The REAL run_agent_sync drives the run; the refusal raised inside it
    (where _providers' budget gate raises) reaches the client as the 429."""
    async def _refused_run(*_a, **_k):
        raise _refusal()

    with patch("routes.graph.concept_describe_agent.run", side_effect=_refused_run):
        resp = client.post(URL, json={"concept": "Recursion"})
    _assert_friendly_429(resp)


def test_budget_refusal_wrapped_in_an_agent_error_is_still_the_429():
    """A refusal that surfaces wrapped in an error the route maps to 502
    (AgentRunError, a transport error) is unwrapped, not mislabelled."""
    from pydantic_ai.exceptions import AgentRunError

    wrapped = AgentRunError("run failed")
    wrapped.__cause__ = _refusal()
    with _agent_run_stub(), patch("routes.graph.run_agent_sync", side_effect=wrapped):
        resp = client.post(URL, json={"concept": "Recursion"})
    _assert_friendly_429(resp)


def test_a_refused_description_is_not_cached():
    fake = _FakeCache()
    with _agent_run_stub(), patch("routes.graph.cache", fake), \
         patch("routes.graph.run_agent_sync", side_effect=_refusal()):
        resp = client.post(URL, json={"concept": "Recursion"})
    assert resp.status_code == 429
    assert fake.store == {}


# ── Cross-student description cache (#97's Redis cache) ───────────────────────


class _FakeCache:
    """Dict-backed stand-in for services.cache with Redis configured."""

    def __init__(self, on: bool = True):
        self.on = on
        self.store: dict[str, str] = {}

    def enabled(self) -> bool:
        return self.on

    def get_str(self, key: str):
        return self.store.get(key)

    def set_str(self, key: str, value: str, ttl_seconds=None):
        self.store[key] = value


def test_description_is_cached_across_calls_and_students():
    fake = _FakeCache()
    with _agent_run_stub(), patch("routes.graph.cache", fake), \
         patch("routes.graph.run_agent_sync", return_value=_result("Recursion is self-reference.")) as run:
        first = client.post(URL, json={"concept": "Recursion", "course_label": "CS 101"})
        # Case and the asking student don't matter: the sentence is about the concept.
        second = client.post(
            "/api/graph/user_andres/concept-description",
            json={"concept": "recursion", "course_label": "cs 101"},
        )
    assert first.json() == second.json() == {"description": "Recursion is self-reference."}
    assert run.call_count == 1


def test_a_different_course_label_is_a_different_description():
    fake = _FakeCache()
    with _agent_run_stub(), patch("routes.graph.cache", fake), \
         patch("routes.graph.run_agent_sync", return_value=_result("ok")) as run:
        client.post(URL, json={"concept": "Kernel", "course_label": "Linear Algebra"})
        client.post(URL, json={"concept": "Kernel", "course_label": "Operating Systems"})
    assert run.call_count == 2


def test_no_cache_configured_calls_the_agent_every_time():
    fake = _FakeCache(on=False)
    with _agent_run_stub(), patch("routes.graph.cache", fake), \
         patch("routes.graph.run_agent_sync", return_value=_result("ok")) as run:
        client.post(URL, json={"concept": "Recursion"})
        client.post(URL, json={"concept": "Recursion"})
    assert run.call_count == 2
    assert fake.store == {}


def test_a_blank_description_is_not_cached():
    fake = _FakeCache()
    with _agent_run_stub(), patch("routes.graph.cache", fake), \
         patch("routes.graph.run_agent_sync", return_value=_result("   ")):
        client.post(URL, json={"concept": "Recursion"})
    assert fake.store == {}


def test_cache_key_names_the_model_mode_and_prompt_version():
    """Function-mode stand-ins must never land under a real model's key, and a
    prompt edit must not keep serving the old prompt's text (#737 review)."""
    from agents.concept_describe import PROMPT_VERSION
    from routes.graph import _description_cache_key

    with patch("routes.graph.model_mode", return_value="real"):
        real = _description_cache_key("Recursion", "CS101")
    with patch("routes.graph.model_mode", return_value="function"):
        stand_in = _description_cache_key("Recursion", "CS101")
    assert real != stand_in
    assert PROMPT_VERSION in real
