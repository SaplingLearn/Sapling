"""Behavioral acceptance for #153: structured-output retry + degradation.

The issue's acceptance criterion, pinned end to end: a deliberately malformed
model output retries (bounded — the #153 budget of 2), then degrades to a
TYPED error, never a raw 500. Runs on the SAPLING_MODEL_MODE=function seam so
the REAL output-tool registration, schema validation, and retry loop execute
(a mocked `agent.run` would prove nothing about retry behavior).

Also pins the observability half: a run that only succeeded after a
validation retry logs a warning via `record_agent_usage` (#153 chose a log
line over a new #117 event — the frozen taxonomy stays untouched).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from agents import WORKER_LIMITS
from agents._providers import (
    clear_function_handlers,
    model_for,
    register_function_handler,
)
from agents.deps import SaplingDeps
from agents.note_summary import note_summary_agent
from agents.quiz import quiz_agent
from agents.usage import record_agent_usage
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_function_registry():
    clear_function_handlers()
    yield
    clear_function_handlers()


def _deps() -> SaplingDeps:
    return SaplingDeps(
        user_id="retry-user",
        course_id="retry-course",
        supabase=None,
        request_id="retry-req",
    )


def _garbage(messages, info) -> ModelResponse:
    """A response that can never satisfy a structured output schema: plain
    text where the output tool call is required."""
    return ModelResponse(parts=[TextPart(content="i am not structured output")])


def test_malformed_output_retries_twice_then_raises_umb_within_worker_budget(
    monkeypatch,
):
    """1 initial + 2 validation retries, then UnexpectedModelBehavior — and
    specifically NOT UsageLimitExceeded: WORKER_LIMITS.request_limit=3 must
    admit the whole retry ladder, or routes that map the two exceptions
    differently (notes' 413-vs-500) misfile persistent garbage as an
    over-budget input."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    calls = {"n": 0}

    def handler(messages, info) -> ModelResponse:
        calls["n"] += 1
        return _garbage(messages, info)

    register_function_handler("note_summary", handler)
    with note_summary_agent.override(model=model_for("note_summary")):
        with pytest.raises(UnexpectedModelBehavior):
            note_summary_agent.run_sync(
                "Summarize this note.", deps=_deps(), usage_limits=WORKER_LIMITS
            )
    assert calls["n"] == 3, "expected 1 initial request + 2 bounded retries"


def test_recovered_validation_retry_is_logged(monkeypatch, caplog):
    """Garbage once, valid on the retry: the run succeeds and
    record_agent_usage warns with the retry count — the #153 observability
    contract for retries that would otherwise be invisible."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    calls = {"n": 0}

    def handler(messages, info) -> ModelResponse:
        calls["n"] += 1
        if calls["n"] == 1:
            return _garbage(messages, info)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args={"summary": "The note explains gradient descent."},
                )
            ]
        )

    register_function_handler("note_summary", handler)
    with note_summary_agent.override(model=model_for("note_summary")):
        with caplog.at_level(logging.WARNING, logger="sapling.agents.usage"):
            result = record_agent_usage(
                note_summary_agent.run_sync(
                    "Summarize this note.", deps=_deps(), usage_limits=WORKER_LIMITS
                ),
                feature="notes",
                task="note_summary",
            )
    assert calls["n"] == 2
    assert result.output.summary == "The note explains gradient descent."
    assert "recovered after 1 validation retry" in caplog.text
    assert "task=note_summary" in caplog.text


def test_quiz_route_degrades_to_typed_502_after_bounded_retries(monkeypatch):
    """The issue's acceptance criterion at the HTTP boundary: persistent
    malformed output exhausts the bounded retries and surfaces as the
    route's TYPED 502 (JSON detail + request-correlatable log), never a raw
    500 traceback."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    calls = {"n": 0}

    def handler(messages, info) -> ModelResponse:
        calls["n"] += 1
        return _garbage(messages, info)

    register_function_handler("quiz", handler)

    def factory(name):
        mock = MagicMock()
        if name == "graph_nodes":
            mock.select.return_value = [{
                "id": "node1",
                "user_id": "user_andres",
                "course_id": "course1",
                "concept_name": "Derivatives",
                "mastery_score": 0.4,
            }]
        else:
            mock.select.return_value = []
            mock.insert.return_value = []
        return mock

    with (
        patch("routes.quiz.table", side_effect=factory),
        patch("routes.quiz._course_material_block", return_value=""),
        quiz_agent.override(model=model_for("quiz")),
    ):
        r = client.post("/api/quiz/generate", json={
            "user_id": "user_andres",
            "concept_node_id": "node1",
            "num_questions": 3,
            "difficulty": "medium",
            "use_shared_context": False,
        })

    assert r.status_code == 502, r.text
    assert "temporarily unavailable" in r.json()["detail"]
    # Still ONE run here: 1 initial request + 2 bounded output retries.
    #
    # routes/quiz.py does retry a guardrail trip on gemini-2.5-flash — an
    # empty `finish_reason=error` response from flash-lite is not fixable by
    # re-asking the same model — but that escalation goes through
    # _resolve_model_pref, which returns None outside real model mode (#391)
    # rather than constructing a live GoogleModel. So the function-mode seam
    # deliberately gets no second attempt, and this test keeps measuring the
    # in-run budget it was written for.
    assert calls["n"] == 3, "expected 1 initial request + 2 bounded retries"


def test_quiz_route_recovers_when_a_fresh_run_succeeds(monkeypatch):
    """A guardrail trip on the FIRST run must not reach the student.

    flash-lite intermittently completes its tool calls and then never emits
    a valid output; pydantic-ai spends both output retries and raises
    UnexpectedModelBehavior. Sampled live, that hit roughly one generation
    in four — and re-running the same request succeeded, because the failure
    is in the run's own exchange, not in the request. The route re-runs once.
    """
    from agents.quiz import Quiz, QuizQuestion

    calls = {"n": 0}
    good = Quiz(questions=[
        QuizQuestion(
            question="P = [[0.7, 0.3], [0.4, 0.6]]; what is P[0][1]?",
            type="multiple_choice", difficulty="medium",
            options=["0.3", "0.7", "0.4", "0.6"], correct_answer="0.3",
            explanation="Row 0, column 1.", concept="Derivatives",
            kind="worked_problem",
        )
    ])

    async def flaky_run(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise UnexpectedModelBehavior("Exceeded maximum output retries (2)")
        return SimpleNamespace(output=good, usage=lambda: None)

    def factory(name):
        mock = MagicMock()
        if name == "graph_nodes":
            mock.select.return_value = [{
                "id": "node1", "user_id": "user_andres", "course_id": "course1",
                "concept_name": "Derivatives", "mastery_score": 0.4,
            }]
        else:
            mock.select.return_value = []
            mock.insert.return_value = []
        return mock

    with (
        patch("routes.quiz.table", side_effect=factory),
        patch("routes.quiz._course_material_block", return_value=""),
        patch("routes.quiz.quiz_agent.run", new=flaky_run),
        patch("routes.quiz.record_agent_usage", side_effect=lambda r, **k: r),
    ):
        r = client.post("/api/quiz/generate", json={
            "user_id": "user_andres",
            "concept_node_id": "node1",
            "num_questions": 1,
            "difficulty": "medium",
            "use_shared_context": False,
        })

    assert r.status_code == 200, r.text
    assert calls["n"] == 2, "expected exactly one fresh re-run, not more"
    assert len(r.json()["questions"]) == 1
