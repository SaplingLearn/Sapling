"""Gemini direct-call instrumentation (issue #118).

call_gemini / call_gemini_multiturn / call_gemini_json must each emit exactly
one llm_usage row from ``response.usage_metadata``, tagged with the threaded
``feature``. call_gemini_json must NOT double-count (it delegates to
call_gemini).
"""
from __future__ import annotations

import types

import pytest

from services import gemini_service, events_service


def _usage_metadata(p, c, t):
    m = types.SimpleNamespace()
    m.prompt_token_count = p
    m.candidates_token_count = c
    m.total_token_count = t
    return m


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


@pytest.fixture
def fake_single_turn(monkeypatch):
    """Stub the genai client's single-shot generate_content.

    The real genai Client exposes ``.models``/``.chats`` as read-only
    properties, so we replace the whole client object rather than a sub-attr.
    """
    resp = types.SimpleNamespace(text='{"ok": true}', usage_metadata=_usage_metadata(100, 20, 120))
    fake_client = types.SimpleNamespace(
        models=types.SimpleNamespace(generate_content=lambda **kw: resp),
    )
    monkeypatch.setattr(gemini_service, "_client", fake_client)
    return resp


def test_call_gemini_logs_usage(sink, fake_single_turn):
    gemini_service.call_gemini("hi", feature="quiz", model="gemini-2.5-flash")
    events_service.flush_now()

    assert len(sink) == 1
    name, rows = sink[0]
    assert name == "llm_usage"
    row = rows[0]
    assert row["provider"] == "gemini"
    assert row["feature"] == "quiz"
    assert row["model"] == "gemini-2.5-flash"
    assert (row["prompt_tokens"], row["completion_tokens"], row["total_tokens"]) == (100, 20, 120)


def test_call_gemini_default_feature_is_misc(sink, fake_single_turn):
    gemini_service.call_gemini("hi", model="gemini-2.5-flash")
    events_service.flush_now()
    assert sink[0][1][0]["feature"] == "misc"


def test_call_gemini_json_does_not_double_count(sink, fake_single_turn):
    gemini_service.call_gemini_json("hi", feature="document", model="gemini-2.5-flash")
    events_service.flush_now()
    # Exactly one row — call_gemini_json delegates to call_gemini, which logs.
    total = sum(len(rows) for _, rows in sink)
    assert total == 1
    assert sink[0][1][0]["feature"] == "document"


def test_call_gemini_multiturn_logs_usage(sink, monkeypatch):
    resp = types.SimpleNamespace(text="hello", usage_metadata=_usage_metadata(200, 50, 250))

    class _Chat:
        def send_message(self, msg):
            return resp

    fake_client = types.SimpleNamespace(
        chats=types.SimpleNamespace(create=lambda **kw: _Chat()),
    )
    monkeypatch.setattr(gemini_service, "_client", fake_client)

    gemini_service.call_gemini_multiturn(
        "sys", [], "hey", feature="chat_tutor", model="gemini-2.5-pro",
    )
    events_service.flush_now()
    row = sink[0][1][0]
    assert row["feature"] == "chat_tutor"
    assert row["model"] == "gemini-2.5-pro"
    assert (row["prompt_tokens"], row["completion_tokens"], row["total_tokens"]) == (200, 50, 250)
