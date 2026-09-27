"""Unit tests for agents/usage.py::record_agent_usage (issue #118).

The helper is the single, one-line-per-call-site seam that reads a Pydantic AI
run result's usage + model and forwards it to events_service.log_llm_usage. It
must never raise (instrumentation can't break the agent run) and must return
the result so it can be used inline.
"""
from __future__ import annotations

import pytest

from agents.usage import record_agent_usage
from agents._providers import model_for
from services import events_service


class _FakeUsage:
    input_tokens = 320
    output_tokens = 80
    total_tokens = 400


class _FakeResponse:
    model_name = "gemini-2.5-pro"


class _FakeResult:
    output = "hello"

    def usage(self):
        return _FakeUsage()

    @property
    def response(self):
        return _FakeResponse()


@pytest.fixture
def sink(monkeypatch):
    rows: list = []

    class _FakeTable:
        def __init__(self, name):
            self.name = name

        def insert(self, r):
            rows.append((self.name, r))
            return r

    monkeypatch.setattr(events_service, "table", lambda name: _FakeTable(name))
    return rows


def test_records_usage_from_result(sink):
    result = record_agent_usage(_FakeResult(), feature="chat_tutor", task="chat_tutor")
    events_service.flush_now()

    assert result.output == "hello", "must return the original result for inline use"
    name, rows = sink[0]
    assert name == "llm_usage"
    row = rows[0]
    assert row["feature"] == "chat_tutor"
    assert row["task"] == "chat_tutor"
    assert row["model"] == "gemini-2.5-pro"
    assert row["prompt_tokens"] == 320
    assert row["completion_tokens"] == 80
    assert row["total_tokens"] == 400


def test_falls_back_to_task_model_when_result_has_no_model(sink):
    class _NoModelResult:
        output = "x"

        def usage(self):
            return _FakeUsage()

        @property
        def response(self):
            raise AttributeError("no response")

        def all_messages(self):
            return []

    record_agent_usage(_NoModelResult(), feature="quiz", task="quiz")
    events_service.flush_now()
    row = sink[0][1][0]
    assert row["model"] == model_for("quiz").model_name


def test_never_raises_on_broken_result(sink):
    class _Broken:
        def usage(self):
            raise RuntimeError("usage exploded")

    # Must swallow: instrumentation cannot break the agent run.
    out = record_agent_usage(_Broken(), feature="notes", task="note_chat")
    events_service.flush_now()
    assert out is not None
    assert sink == []  # nothing logged, but no exception either


# ── #689: tokens must survive the REAL Gemini → pydantic-ai extraction ──────
#
# Every test above feeds record_agent_usage a hand-built usage object, which
# is exactly why #689 went unseen: the zero tokens were produced one layer
# down, inside pydantic-ai's own `_metadata_as_usage` → `RequestUsage.extract`
# (genai-prices). With genai-prices >= 0.1.0 that extraction returns modality
# split fields (`input_text_tokens`) pydantic-ai 1.x's RequestUsage does not
# accept; the TypeError is swallowed inside pydantic-ai and the run reports
# 0/0 tokens. The deployed image (Dockerfile → unlocked requirements.txt)
# resolved genai-prices 0.1.x, so prod/staging recorded zeros while every
# local backend (older genai-prices) recorded real counts.
#
# This drives the production model object (`model_for`, a _LoopSafeGoogleModel)
# over a canned GenerateContentResponse shaped like Gemini's real reply —
# including `promptTokensDetails`, the field that trips the extraction — and
# asserts the ledger row carries the tokens. Patched at `AsyncModels.
# generate_content`, above the hermetic transport guard.


def _gemini_reply():
    from google.genai import types

    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text="A blurb.")]),
                finish_reason=types.FinishReason.STOP,
            )
        ],
        model_version="gemini-2.5-flash-lite",
        response_id="resp-689",
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=199,
            candidates_token_count=38,
            total_token_count=237,
            prompt_tokens_details=[
                types.ModalityTokenCount(modality=types.MediaModality.TEXT, token_count=199)
            ],
            traffic_type=types.TrafficType.ON_DEMAND,
        ),
    )


def test_real_gemini_response_records_nonzero_tokens(sink, monkeypatch):
    import asyncio

    from google.genai import models as genai_models
    from pydantic_ai import Agent

    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    monkeypatch.delenv("SAPLING_MODEL_CONCEPT_DESCRIBE", raising=False)

    async def _fake_generate_content(self, *args, **kwargs):
        return _gemini_reply()

    monkeypatch.setattr(genai_models.AsyncModels, "generate_content", _fake_generate_content)

    agent = Agent(model_for("concept_describe"))
    result = asyncio.run(agent.run("Describe photosynthesis."))
    record_agent_usage(result, feature="graph", task="concept_describe")
    events_service.flush_now()

    row = sink[0][1][0]
    assert row["model"] == "gemini-2.5-flash-lite"
    assert (row["prompt_tokens"], row["completion_tokens"], row["total_tokens"]) == (
        199,
        38,
        237,
    ), "Gemini reported 199/38 tokens; the llm_usage row must carry them (#689)"
    assert row["cost_usd"] and row["cost_usd"] > 0
