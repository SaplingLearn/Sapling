"""Tests for the concept_scan agent migration (/scan-concepts)."""
import pytest
from unittest.mock import patch

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior
from pydantic_ai.models.google import GoogleModel
from fastapi.testclient import TestClient

from agents._providers import model_for
from agents.concept_scan import NewConcepts, concept_scan_agent
import routes.documents as documents
from main import app


def test_model_for_concept_scan_defaults_to_flash_lite():
    m = model_for("concept_scan")
    assert isinstance(m, GoogleModel)
    assert m.model_name == "gemini-2.5-flash-lite"


def test_new_concepts_allows_empty_list():
    assert NewConcepts(concepts=[]).concepts == []


def test_new_concepts_rejects_more_than_15():
    with pytest.raises(ValidationError):
        NewConcepts(concepts=[f"Concept {i}" for i in range(16)])


def test_concept_scan_agent_is_configured():
    assert isinstance(concept_scan_agent, Agent)
    assert concept_scan_agent.output_type is NewConcepts


class _Result:
    def __init__(self, concepts):
        self.output = NewConcepts(concepts=concepts)


class _FakeAgent:
    """Stand-in for concept_scan_agent with an async run()."""

    def __init__(self, *, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.calls = []

    async def run(self, message, **kwargs):
        self.calls.append((message, kwargs))
        if self._exc is not None:
            raise self._exc
        return self._result


def test_scan_user_message_includes_existing_and_doc_context():
    msg = documents._scan_user_message(
        course_label="CS101",
        existing_concepts=["Recursion"],
        doc_filename="lecture1.pdf",
        doc_summary="Intro to sorting algorithms.",
        doc_concept_notes=[{"name": "Merge Sort", "description": "divide and conquer"}],
    )
    assert "CS101" in msg
    assert "Recursion" in msg
    assert "lecture1.pdf" in msg
    assert "Merge Sort" in msg


def test_extend_concepts_returns_agent_output(monkeypatch):
    fake = _FakeAgent(result=_Result(["Binary Search", "Hashing"]))
    monkeypatch.setattr(documents, "concept_scan_agent", fake)
    out = documents._extend_concepts(
        "u1", "c1", course_label="CS101", existing_concepts=["Recursion"],
    )
    assert out == ["Binary Search", "Hashing"]
    assert fake.calls  # agent was actually invoked


def test_extend_concepts_handles_empty(monkeypatch):
    fake = _FakeAgent(result=_Result([]))
    monkeypatch.setattr(documents, "concept_scan_agent", fake)
    out = documents._extend_concepts(
        "u1", "c1", course_label="CS101", existing_concepts=[],
    )
    assert out == []


@pytest.mark.parametrize(
    "exc",
    [UsageLimitExceeded("limit"), UnexpectedModelBehavior("weird"), RuntimeError("boom")],
)
def test_extend_concepts_degrades_to_empty_on_agent_failure(monkeypatch, caplog, exc):
    """#151b (D4): /scan-concepts is best-effort graph enrichment — any agent
    failure degrades to 'no new concepts' with a warning log. The legacy
    call_gemini_json fallback is gone (ADR 0024)."""
    monkeypatch.setattr(documents, "concept_scan_agent", _FakeAgent(exc=exc))
    with caplog.at_level("WARNING", logger="routes.documents"):
        out = documents._extend_concepts(
            "u1", "c1", course_label="CS101", existing_concepts=["Recursion"],
        )
    assert out == []
    assert any("concept_scan" in rec.message for rec in caplog.records)


client = TestClient(app)


def test_course_scan_endpoint_uses_agent_and_keeps_response_shape():
    fake = _FakeAgent(result=_Result(["Binary Search", "Hashing"]))
    with patch("routes.documents._validate_user", return_value=None), \
         patch("routes.documents._course_label", return_value="CS101"), \
         patch("routes.documents.apply_graph_update", return_value=None), \
         patch("routes.documents.concept_scan_agent", fake), \
         patch("routes.documents.table") as t:
        t.return_value.select.return_value = [
            {"id": "n1", "concept_name": "Recursion"},
        ]
        r = client.post(
            "/api/documents/course/c1/scan-concepts",
            json={"user_id": "u1"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["concepts"] == ["Binary Search", "Hashing"]
    assert "added" in body and "existing" in body
    assert fake.calls  # the agent path served the request


def test_course_scan_endpoint_degrades_to_empty_shape_on_agent_failure():
    """Route-level #151b contract: an agent failure yields HTTP 200 with the
    same shape an actually-empty scan produces — {"concepts": [], "added": 0,
    "existing": N} — and writes nothing to the graph."""
    fake = _FakeAgent(exc=RuntimeError("boom"))
    with patch("routes.documents._validate_user", return_value=None), \
         patch("routes.documents._course_label", return_value="CS101"), \
         patch("routes.documents.apply_graph_update") as apply_update, \
         patch("routes.documents.concept_scan_agent", fake), \
         patch("routes.documents.table") as t:
        t.return_value.select.return_value = [
            {"id": "n1", "concept_name": "Recursion"},
        ]
        r = client.post(
            "/api/documents/course/c1/scan-concepts",
            json={"user_id": "u1"},
        )
    assert r.status_code == 200
    assert r.json() == {"concepts": [], "added": 0, "existing": 1}
    apply_update.assert_not_called()
