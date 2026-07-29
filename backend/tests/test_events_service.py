"""Unit tests for services/events_service.py — the fire-and-forget write
path for `events` + `llm_usage` (issue #116).

The worker thread is never started in these tests; `flush_now()` drains the
queue synchronously on the calling thread, which makes assertions
deterministic (no races with a background drainer).
"""
from __future__ import annotations

import pytest

from services import events_service


# ── Test doubles for the db seam ────────────────────────────────────────────


class _FakeTable:
    def __init__(self, name: str, sink: list):
        self.name = name
        self.sink = sink

    def insert(self, rows):
        # PostgREST accepts a list for a batch insert; record what was sent.
        self.sink.append((self.name, rows))
        return rows if isinstance(rows, list) else [rows]


def _fake_table_factory(sink: list):
    def factory(name: str):
        return _FakeTable(name, sink)

    return factory


def _raising_table_factory():
    def factory(name: str):
        class _T:
            def insert(self, rows):
                raise RuntimeError("simulated PostgREST failure")

        return _T()

    return factory


@pytest.fixture
def sink(monkeypatch):
    rows: list = []
    monkeypatch.setattr(events_service, "table", _fake_table_factory(rows))
    return rows


# ── log_llm_usage ───────────────────────────────────────────────────────────


def test_log_llm_usage_enqueues_normalized_row_with_cost(sink, monkeypatch):
    monkeypatch.setenv("EVENTS_LOGGING_ENABLED", "true")

    class FakeUsage:
        input_tokens = 1000
        output_tokens = 1000
        total_tokens = 2000

    events_service.log_llm_usage(
        feature="quiz", task="quiz", model="gemini-2.5-flash", usage=FakeUsage(),
        user_id="user_andres", request_id="req-1",
    )
    events_service.flush_now()

    assert len(sink) == 1
    name, rows = sink[0]
    assert name == "llm_usage"
    row = rows[0]
    assert row["feature"] == "quiz"
    assert row["task"] == "quiz"
    assert row["model"] == "gemini-2.5-flash"
    assert row["provider"] == "gemini"
    assert row["prompt_tokens"] == 1000
    assert row["completion_tokens"] == 1000
    assert row["total_tokens"] == 2000
    assert row["user_id"] == "user_andres"
    assert row["request_id"] == "req-1"
    assert row["cost_usd"] == pytest.approx(0.0028)


def test_log_llm_usage_unknown_model_persists_null_cost(sink):
    class FakeUsage:
        input_tokens = 5
        output_tokens = 5
        total_tokens = 10

    events_service.log_llm_usage(
        feature="notes", task="note_chat", model="mystery-model-9000", usage=FakeUsage(),
    )
    events_service.flush_now()

    row = sink[0][1][0]
    assert row["cost_usd"] is None


def test_log_llm_usage_gemini_metadata_shape(sink):
    class FakeMeta:
        prompt_token_count = 30
        candidates_token_count = 12
        total_token_count = 42

    events_service.log_llm_usage(
        feature="document", task=None, model="gemini-2.5-flash-lite",
        usage=FakeMeta(), provider="gemini",
    )
    events_service.flush_now()
    row = sink[0][1][0]
    assert (row["prompt_tokens"], row["completion_tokens"], row["total_tokens"]) == (30, 12, 42)
    assert row["task"] is None


# ── log_event + content fingerprinting ──────────────────────────────────────


def test_log_event_hashes_content_and_never_stores_raw(sink):
    secret = "student's private essay body that must never be persisted"
    events_service.log_event(
        "document.upload", category="usage", user_id="u1", content=secret,
    )
    events_service.flush_now()

    name, rows = sink[0]
    assert name == "events"
    row = rows[0]
    assert row["event_type"] == "document.upload"
    assert row["category"] == "usage"
    # content_fp is a 16-hex fingerprint; raw content is absent everywhere.
    assert row["content_fp"] is not None
    assert len(row["content_fp"]) == 16
    assert "content" not in row
    assert secret not in str(row)


def test_log_event_defaults_request_id_from_contextvar(sink):
    from services import request_context

    token = request_context._REQUEST_ID_CTX.set("ctx-req-42")
    try:
        events_service.log_event("auth.login", category="audit")
        events_service.flush_now()
    finally:
        request_context._REQUEST_ID_CTX.reset(token)

    assert sink[0][1][0]["request_id"] == "ctx-req-42"


# ── Non-blocking + failure isolation ────────────────────────────────────────


def test_calling_thread_never_hits_db(monkeypatch):
    """log_* must enqueue only — no DB call happens on the caller's thread,
    so even a table() that raises on insert can't affect the caller."""
    monkeypatch.setattr(events_service, "table", _raising_table_factory())

    class FakeUsage:
        input_tokens = 1
        output_tokens = 1
        total_tokens = 2

    # Neither call raises, because the (raising) insert only runs at flush time.
    events_service.log_llm_usage(feature="quiz", task="quiz", model="gemini-2.5-flash", usage=FakeUsage())
    events_service.log_event("quiz.completed", category="usage")


def test_worker_insert_error_is_swallowed(monkeypatch, caplog):
    monkeypatch.setattr(events_service, "table", _raising_table_factory())
    events_service.log_event("error.5xx", category="error")
    # flush_now performs the insert; the error must be caught and logged,
    # never propagated.
    with caplog.at_level("WARNING"):
        events_service.flush_now()  # must not raise
    assert any("simulated PostgREST failure" in r.getMessage() or "flush" in r.getMessage().lower()
               for r in caplog.records)


def test_queue_overflow_drops_and_increments_counter(monkeypatch, sink):
    events_service.reset_for_tests(maxsize=1)
    monkeypatch.setattr(events_service, "table", _fake_table_factory(sink))

    # First enqueues; the rest overflow a size-1 queue (nothing drains yet).
    for i in range(4):
        events_service.log_event(f"usage.tick.{i}", category="usage")

    assert events_service.dropped_count() == 3
    events_service.flush_now()
    # Only the single row that fit is inserted.
    assert sum(len(rows) for _, rows in sink) == 1


def test_kill_switch_makes_helpers_noops(monkeypatch, sink):
    monkeypatch.setenv("EVENTS_LOGGING_ENABLED", "false")

    class FakeUsage:
        input_tokens = 1
        output_tokens = 1
        total_tokens = 2

    events_service.log_event("usage.tick", category="usage")
    events_service.log_llm_usage(feature="quiz", task="quiz", model="gemini-2.5-flash", usage=FakeUsage())
    events_service.flush_now()

    assert sink == []


def test_flush_now_drains_queue(sink):
    events_service.log_event("a.b", category="usage")
    events_service.log_event("c.d", category="audit")
    events_service.flush_now()
    total = sum(len(rows) for _, rows in sink)
    assert total == 2
    # Queue is empty afterwards — a second flush inserts nothing more.
    sink.clear()
    events_service.flush_now()
    assert sink == []
