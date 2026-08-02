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
