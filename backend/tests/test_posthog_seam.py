"""The PostHog seam (ADR 0028): gating, the one event mirror, the AI-span
allowlist, exception-capture safety, and best-effort account deletion.

Everything here runs hermetically: under pytest the real gate says "off", so
tests that need an "on" seam install a fake client or patch the gate
explicitly, and the no-network tests assert that no socket is ever opened.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode

from services import ai_observability, events_service, posthog_client
from services.ai_observability import AllowlistSpanProcessor, bind_ai_context

USER_ID = "9b2f6a3e-1c1d-4c55-9a8e-2f1f0e6b7a10"
# Stands in for decrypted student text (a note body, a chat message, a name).
SECRET = "SECRET-student-note-Ada-Lovelace-4471"


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_client():
    """Install a fake PostHog client for the duration of one test."""
    client = MagicMock(name="PosthogClient")
    posthog_client.set_client_for_tests(client)
    try:
        yield client
    finally:
        posthog_client.set_client_for_tests(None)


@pytest.fixture
def no_network(monkeypatch):
    """Record (and refuse) every outbound socket connect."""
    attempts: list = []

    def _refuse(self, address, *a, **k):
        attempts.append(address)
        raise OSError("network disabled by test")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    return attempts


_ON_ENV = {
    "POSTHOG_PROJECT_TOKEN": "phc_test",
    "SAPLING_MODEL_MODE": "real",
    "APP_ENV": "local",
}


# ── 1. Gating ───────────────────────────────────────────────────────────────


class TestGate:
    def test_token_set_real_mode_local_is_on(self):
        assert posthog_client._disabled_reason_for(_ON_ENV, under_pytest=False) is None

    def test_production_with_token_is_on(self):
        env = {**_ON_ENV, "APP_ENV": "production"}
        assert posthog_client._disabled_reason_for(env, under_pytest=False) is None

    @pytest.mark.parametrize(
        "override, expect",
        [
            ({"POSTHOG_PROJECT_TOKEN": ""}, "POSTHOG_PROJECT_TOKEN"),
            ({"POSTHOG_PROJECT_TOKEN": "   "}, "POSTHOG_PROJECT_TOKEN"),
            ({"SAPLING_MODEL_MODE": "function"}, "SAPLING_MODEL_MODE"),
            ({"SAPLING_MODEL_MODE": " Function "}, "SAPLING_MODEL_MODE"),
            ({"APP_ENV": "test"}, "APP_ENV=test"),
            ({"POSTHOG_DISABLED": "1"}, "POSTHOG_DISABLED"),
            ({"POSTHOG_DISABLED": "true"}, "POSTHOG_DISABLED"),
        ],
    )
    def test_each_forced_off_rule(self, override, expect):
        env = {**_ON_ENV, **override}
        reason = posthog_client._disabled_reason_for(env, under_pytest=False)
        assert reason is not None and expect in reason

    def test_pytest_forces_off_even_when_everything_else_says_on(self):
        reason = posthog_client._disabled_reason_for(_ON_ENV, under_pytest=True)
        assert reason == "running under pytest"

    def test_real_gate_is_off_in_this_process(self, monkeypatch):
        # The live gate, with a token deliberately present: pytest wins.
        monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
        monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
        assert posthog_client.is_enabled() is False

    def test_kill_switch_zero_is_not_truthy(self):
        env = {**_ON_ENV, "POSTHOG_DISABLED": "0"}
        assert posthog_client._disabled_reason_for(env, under_pytest=False) is None


@pytest.mark.parametrize(
    "override",
    [
        {"POSTHOG_PROJECT_TOKEN": ""},
        {"SAPLING_MODEL_MODE": "function"},
        {"APP_ENV": "test"},
        {"POSTHOG_DISABLED": "1"},
    ],
)
def test_disabled_means_no_client_no_processor_no_network(override, monkeypatch, no_network):
    """Every forced-off rule, evaluated as if NOT under pytest: no Posthog()
    constructed, no AI span processor, and no socket opened by any seam use."""
    env = {**_ON_ENV, **override}
    monkeypatch.setattr(
        posthog_client, "disabled_reason",
        lambda: posthog_client._disabled_reason_for(env, under_pytest=False),
    )
    with patch("posthog.Posthog") as ctor:
        assert posthog_client.initialize_posthog() is None
        ctor.assert_not_called()
    assert posthog_client.get_posthog_client() is None
    assert list(ai_observability.posthog_ai_span_processors()) == []

    events_service.log_event("note.created", category="usage", user_id=USER_ID, payload={})
    posthog_client.capture_exception(ValueError("x"), user_id=USER_ID, request_id=None)
    with patch("httpx.post") as post:
        posthog_client.delete_person(USER_ID)
    if "POSTHOG_PROJECT_TOKEN" not in override:
        post.assert_not_called()
    assert no_network == []


def test_enabled_client_is_constructed_with_privacy_settings(monkeypatch):
    monkeypatch.setattr(posthog_client, "disabled_reason", lambda: None)
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
    monkeypatch.delenv("POSTHOG_HOST", raising=False)
    with patch("posthog.Posthog") as ctor:
        try:
            client = posthog_client.initialize_posthog()
            assert client is ctor.return_value
            kwargs = ctor.call_args.kwargs
            assert kwargs["project_api_key"] == "phc_test"
            assert kwargs["host"] == "https://us.i.posthog.com"  # US cloud default
            assert kwargs["capture_exception_code_variables"] is False
            assert kwargs["enable_exception_autocapture"] is False
            assert kwargs["before_send"] is posthog_client._scrub_event
            # A personal key must never reach the capture client (it would
            # start feature-flag polling = background network).
            assert "personal_api_key" not in kwargs and "secret_key" not in kwargs
            # Idempotent.
            assert posthog_client.initialize_posthog() is client
            assert ctor.call_count == 1
        finally:
            posthog_client.shutdown_posthog()
    assert posthog_client.get_posthog_client() is None


def test_lifespan_under_pytest_builds_no_client():
    """The app's own lifespan runs initialize_posthog; under pytest it must
    leave the client None even with a token in the environment."""
    with patch.dict("os.environ", {"POSTHOG_PROJECT_TOKEN": "phc_test"}), \
         patch("posthog.Posthog") as ctor:
        assert posthog_client.initialize_posthog() is None
        ctor.assert_not_called()


# ── 2. The chokepoint mirror ────────────────────────────────────────────────


class TestMirror:
    def test_log_event_mirrors_same_name_payload_and_uuid(self, fake_client, sink):
        events_service.log_event(
            "note.created",
            category="usage",
            user_id=USER_ID,
            request_id="req-123",
            payload={"note_id": "n1", "has_body": True},
            content=SECRET,
        )
        fake_client.capture.assert_called_once()
        call = fake_client.capture.call_args
        assert call.args == ("note.created",)
        assert call.kwargs["distinct_id"] == USER_ID
        assert call.kwargs["properties"] == {
            "note_id": "n1", "has_body": True, "category": "usage", "request_id": "req-123",
        }
        # Neither the content nor its fingerprint is forwarded.
        assert SECRET not in json.dumps(call.kwargs, default=str)
        assert "content_fp" not in call.kwargs["properties"]
        # And our own table still got its row.
        events_service.flush_now()
        assert [r["event_type"] for r in sink] == ["note.created"]

    def test_kill_switch_stops_the_mirror_too(self, fake_client, monkeypatch, sink):
        monkeypatch.setenv("EVENTS_LOGGING_ENABLED", "false")
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        fake_client.capture.assert_not_called()

    def test_no_user_is_a_personless_event(self, fake_client, sink):
        events_service.log_event("rag.index_failed", category="error", payload={"doc_id": "d"})
        assert fake_client.capture.call_args.kwargs["distinct_id"] is None

    def test_a_failing_client_never_raises_or_costs_the_db_row(self, fake_client, sink):
        fake_client.capture.side_effect = RuntimeError("posthog down")
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        events_service.flush_now()
        assert [r["event_type"] for r in sink] == ["note.created"]

    def test_no_client_is_a_no_op(self, sink):
        assert posthog_client.get_posthog_client() is None
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        events_service.flush_now()
        assert len(sink) == 1

    def test_real_client_capture_is_non_blocking(self, monkeypatch, no_network):
        """posthog-python's capture is an enqueue for a background consumer:
        with every socket refused, capture still returns immediately."""
        from posthog import Posthog

        client = Posthog(
            "phc_test", host="https://us.i.posthog.com", flush_interval=60, max_retries=0,
        )
        try:
            posthog_client.set_client_for_tests(client)
            started = time.monotonic()
            events_service.log_event("note.created", category="usage", user_id=USER_ID)
            elapsed = time.monotonic() - started
            # Queued for the consumer thread, not sent on this one.
            assert client._analytics_lane.queue.qsize() == 1
            assert elapsed < 0.5
        finally:
            posthog_client.set_client_for_tests(None)
            # The consumer's one upload attempt hits the refused socket and
            # gives up (max_retries=0); shutdown then returns promptly.
            client.shutdown()


class TestFlashcardEvents:
    """The two events added to the taxonomy for ADR 0028 are emitted through
    events_service (so both pipelines see them)."""

    def test_generate_emits_flashcard_generated(self, sink):
        from main import app

        with patch("routes.flashcards._get_course_documents", return_value=[{"x": 1}]), \
             patch("routes.flashcards._get_weak_concepts", return_value=["a", "b"]), \
             patch("routes.flashcards._generate", return_value=[{"front": SECRET, "back": "b"}]), \
             patch("routes.flashcards.table") as t, \
             patch("services.achievement_service.check_achievements"):
            t.return_value.select.return_value = []
            r = TestClient(app).post("/api/flashcards/generate", json={
                "user_id": USER_ID, "topic": "CS", "count": 1,
            })
        assert r.status_code == 200
        events_service.flush_now()
        rows = [x for x in sink if x["event_type"] == "flashcard.generated"]
        assert len(rows) == 1
        assert rows[0]["user_id"] == USER_ID
        assert rows[0]["payload"] == {
            "card_count": 1, "documents_used": 1, "weak_concepts_used": 2,
        }
        assert SECRET not in json.dumps(rows[0])

    def test_rate_emits_flashcard_reviewed(self, sink):
        from main import app

        with patch("routes.flashcards.table") as t, \
             patch("routes.flashcards.check_achievements"):
            t.return_value.select.return_value = [{"id": "c1", "times_reviewed": 2}]
            r = TestClient(app).post("/api/flashcards/rate", json={
                "user_id": USER_ID, "card_id": "c1", "rating": 3,
            })
        assert r.status_code == 200
        events_service.flush_now()
        rows = [x for x in sink if x["event_type"] == "flashcard.reviewed"]
        assert [x["payload"] for x in rows] == [{"card_id": "c1", "rating": 3}]


# ── 3. AI-span allowlist ────────────────────────────────────────────────────


def _pipeline():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(AllowlistSpanProcessor(SimpleSpanProcessor(exporter)))
    return provider, exporter


def _dump(span) -> str:
    return span.to_json()


class TestAiSpanAllowlist:
    def test_content_is_stripped_and_metrics_survive(self):
        provider, exporter = _pipeline()
        tracer = provider.get_tracer("pydantic-ai")
        bind_ai_context(session_id="sess-1", distinct_id=USER_ID, request_id="req-1")

        messages = json.dumps([{"role": "user", "parts": [{"content": SECRET}]}])
        with tracer.start_as_current_span("chat gemini-2.5-flash") as span:
            span.set_attributes({
                "gen_ai.operation.name": "chat",
                "gen_ai.system": "google-gla",
                "gen_ai.request.model": "gemini-2.5-flash",
                "gen_ai.response.model": "gemini-2.5-flash",
                "gen_ai.usage.input_tokens": 120,
                "gen_ai.usage.output_tokens": 45,
                "operation.cost": 0.0012,
                "gen_ai.response.finish_reasons": ["stop"],
                "gen_ai.input.messages": messages,
                "gen_ai.output.messages": messages,
                "gen_ai.system_instructions": SECRET,
                "model_request_parameters": json.dumps({"x": SECRET}),
                "logfire.msg": f"chat about {SECRET}",
                "gen_ai.request.model_extra": SECRET,  # unknown key: dropped
                "gen_ai.usage.details.bogus": SECRET,  # string under numeric prefix
            })
            span.add_event("gen_ai.user.message", {"content": SECRET})
        with tracer.start_as_current_span("running tool") as span:
            span.set_attributes({
                "gen_ai.tool.name": "read_notes",
                "gen_ai.tool.call.id": "call_1",
                "gen_ai.tool.call.arguments": json.dumps({"q": SECRET}),
                "gen_ai.tool.call.result": SECRET,
                "tool_arguments": json.dumps({"q": SECRET}),
                "tool_response": SECRET,
            })
            try:
                raise ValueError(SECRET)
            except ValueError as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, SECRET))

        spans = exporter.get_finished_spans()
        assert len(spans) == 2
        for s in spans:
            assert SECRET not in _dump(s)
            assert not s.events and not s.links
            assert s.status.description is None

        chat = next(s for s in spans if s.name.startswith("chat"))
        assert dict(chat.attributes) == {
            "gen_ai.operation.name": "chat",
            "gen_ai.system": "google-gla",
            "gen_ai.request.model": "gemini-2.5-flash",
            "gen_ai.response.model": "gemini-2.5-flash",
            "gen_ai.usage.input_tokens": 120,
            "gen_ai.usage.output_tokens": 45,
            "operation.cost": 0.0012,
            "gen_ai.response.finish_reasons": ("stop",),
            "posthog.distinct_id": USER_ID,
            "$ai_session_id": "sess-1",
        }
        tool = next(s for s in spans if s.name == "running tool")
        assert tool.attributes["gen_ai.tool.name"] == "read_notes"
        assert tool.attributes["error.type"] == "ValueError"
        assert tool.status.status_code == StatusCode.ERROR
        assert "gen_ai.tool.call.arguments" not in tool.attributes
        assert "tool_arguments" not in tool.attributes

    def test_non_ai_spans_are_not_forwarded(self):
        provider, exporter = _pipeline()
        tracer = provider.get_tracer("fastapi")
        with tracer.start_as_current_span("GET /api/notes") as span:
            span.set_attribute("http.route", "/api/notes")
        assert exporter.get_finished_spans() == ()

    def test_the_live_span_is_not_mutated_for_logfire(self):
        """Attribution is added to the COPY; Logfire's span keeps its own set."""
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        raw = InMemorySpanExporter()
        provider.add_span_processor(AllowlistSpanProcessor(SimpleSpanProcessor(exporter)))
        provider.add_span_processor(SimpleSpanProcessor(raw))
        bind_ai_context(session_id=None, distinct_id=USER_ID, request_id="r")
        with provider.get_tracer("t").start_as_current_span("chat m") as span:
            span.set_attribute("gen_ai.request.model", "m")
        assert "posthog.distinct_id" not in raw.get_finished_spans()[0].attributes
        assert exporter.get_finished_spans()[0].attributes["posthog.distinct_id"] == USER_ID

    def test_a_broken_delegate_never_raises_into_tracing(self):
        delegate = MagicMock()
        delegate.on_end.side_effect = RuntimeError("exporter down")
        provider = TracerProvider()
        provider.add_span_processor(AllowlistSpanProcessor(delegate))
        with provider.get_tracer("t").start_as_current_span("chat m") as span:
            span.set_attribute("gen_ai.request.model", "m")

    @pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
    def test_real_pydantic_ai_run_reaches_posthog_without_content(self, version):
        """End to end against the INSTALLED pydantic-ai's own instrumentation,
        every data-format version: a prompt, tool args, tool result and output
        all carrying SECRET, and none of it survives — but model and token
        usage do."""
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.models.instrumented import InstrumentationSettings

        def handler(messages, info):
            if len(messages) == 1:
                return ModelResponse(parts=[ToolCallPart("lookup", {"q": SECRET})])
            return ModelResponse(parts=[TextPart(f"answer {SECRET}")])

        provider, exporter = _pipeline()
        agent = Agent(
            FunctionModel(handler),
            name="sapling_tutor",
            system_prompt=f"You tutor {SECRET}.",
            instrument=InstrumentationSettings(tracer_provider=provider, version=version),
        )

        @agent.tool_plain
        def lookup(q: str) -> str:
            return f"notes for {SECRET}"

        bind_ai_context(session_id=None, distinct_id=USER_ID, request_id="req-9")
        result = asyncio.run(agent.run(f"hello {SECRET}"))
        assert SECRET in result.output  # the run really carried the content

        spans = exporter.get_finished_spans()
        assert spans, "no AI spans reached the PostHog delegate"
        for s in spans:
            assert SECRET not in _dump(s), f"content leaked on span {s.name!r}"
            assert s.attributes.get("posthog.distinct_id") == USER_ID
        chats = [s for s in spans if s.attributes.get("gen_ai.operation.name") == "chat"]
        assert chats
        for s in chats:
            assert s.attributes.get("gen_ai.request.model") or s.attributes.get("gen_ai.response.model")
            assert s.attributes.get("gen_ai.usage.input_tokens", 0) > 0
            assert s.attributes.get("gen_ai.usage.output_tokens", 0) > 0
        tool_spans = [s for s in spans if s.attributes.get("gen_ai.tool.name") == "lookup"]
        assert tool_spans


# ── 4. Exception capture ────────────────────────────────────────────────────


class TestExceptionCapture:
    def test_real_sdk_event_has_no_locals_and_no_message(self, monkeypatch):
        """Through the real posthog SDK (send=False): the queued $exception
        event carries type + frames, but not the message or any local."""
        import posthog as posthog_pkg

        captured: list[dict] = []
        real_scrub = posthog_client._scrub_event

        def spy(msg):
            out = real_scrub(msg)
            captured.append(out)
            return out

        monkeypatch.setattr(posthog_client, "_scrub_event", spy)
        monkeypatch.setattr(posthog_client, "disabled_reason", lambda: None)
        monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
        real_ctor = posthog_pkg.Posthog
        monkeypatch.setattr(
            posthog_pkg, "Posthog", lambda **kw: real_ctor(**kw, send=False),
        )
        try:
            posthog_client.initialize_posthog()

            def handler_with_decrypted_locals():
                note_body = SECRET  # noqa: F841 - the local that must not ship
                raise ValueError(f"bad input: {SECRET}")

            try:
                handler_with_decrypted_locals()
            except ValueError as exc:
                posthog_client.capture_exception(exc, user_id=USER_ID, request_id="req-5")
        finally:
            posthog_client.shutdown_posthog()

        assert len(captured) == 1
        event = captured[0]
        assert event["event"] == "$exception"
        assert event["distinct_id"] == USER_ID
        assert event["properties"]["request_id"] == "req-5"
        assert SECRET not in json.dumps(event, default=str)
        exc_list = event["properties"]["$exception_list"]
        assert exc_list[0]["type"] == "ValueError"
        assert exc_list[0]["value"] == "[redacted]"
        frames = exc_list[0]["stacktrace"]["frames"]
        assert frames and all("vars" not in f for f in frames)

    def test_scrub_strips_vars_even_if_present(self):
        msg = {"properties": {"$exception_list": [{
            "type": "KeyError", "value": SECRET,
            "stacktrace": {"frames": [{"function": "f", "vars": {"x": SECRET}}]},
        }]}}
        out = posthog_client._scrub_event(msg)
        assert SECRET not in json.dumps(out)

    def test_500_handler_captures_with_the_session_user(self, fake_client):
        from main import unhandled_exception_handler

        request = SimpleNamespace(
            state=SimpleNamespace(user_id=USER_ID, request_id="rid-1"),
            url=SimpleNamespace(path="/api/notes"),
        )
        exc = RuntimeError("boom")
        resp = asyncio.run(unhandled_exception_handler(request, exc))
        assert resp.status_code == 500
        fake_client.capture_exception.assert_called_once_with(
            exc, distinct_id=USER_ID, properties={"request_id": "rid-1"},
        )

    def test_500_handler_is_inert_when_disabled(self):
        from main import unhandled_exception_handler

        request = SimpleNamespace(
            state=SimpleNamespace(request_id="rid-2"), url=SimpleNamespace(path="/x"),
        )
        resp = asyncio.run(unhandled_exception_handler(request, RuntimeError("x")))
        assert resp.status_code == 500

    def test_a_failing_capture_never_raises(self, fake_client):
        fake_client.capture_exception.side_effect = RuntimeError("down")
        posthog_client.capture_exception(ValueError("x"), user_id=None, request_id=None)


# ── 5. Account deletion ─────────────────────────────────────────────────────


class TestDeletePerson:
    @pytest.fixture
    def on(self, monkeypatch):
        monkeypatch.setattr(posthog_client, "disabled_reason", lambda: None)
        monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_key")
        monkeypatch.setenv("POSTHOG_PROJECT_ID", "4242")
        monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")
        monkeypatch.delenv("POSTHOG_API_HOST", raising=False)

    def test_posts_bulk_delete_to_the_app_host(self, on):
        with patch("httpx.post", return_value=MagicMock(status_code=202)) as post:
            posthog_client.delete_person(USER_ID)
        post.assert_called_once()
        assert post.call_args.args[0] == (
            "https://us.posthog.com/api/projects/4242/persons/bulk_delete/"
        )
        assert post.call_args.kwargs["json"] == {
            "distinct_ids": [USER_ID], "delete_events": True,
        }
        assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer phx_key"}
        assert post.call_args.kwargs["timeout"] > 0

    def test_runs_even_with_no_project_token(self, monkeypatch, on):
        monkeypatch.setattr(
            posthog_client, "disabled_reason", lambda: posthog_client._NO_TOKEN,
        )
        with patch("httpx.post", return_value=MagicMock(status_code=202)) as post:
            posthog_client.delete_person(USER_ID)
        post.assert_called_once()

    @pytest.mark.parametrize("unset", ["POSTHOG_PERSONAL_API_KEY", "POSTHOG_PROJECT_ID"])
    def test_unconfigured_warns_and_skips(self, on, monkeypatch, caplog, unset):
        monkeypatch.delenv(unset)
        with patch("httpx.post") as post, caplog.at_level(logging.WARNING, "sapling.posthog"):
            posthog_client.delete_person(USER_ID)
        post.assert_not_called()
        assert "skipped" in caplog.text

    def test_under_pytest_the_real_gate_skips_the_request(self, monkeypatch, caplog):
        monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_key")
        monkeypatch.setenv("POSTHOG_PROJECT_ID", "4242")
        with patch("httpx.post") as post, caplog.at_level(logging.WARNING, "sapling.posthog"):
            posthog_client.delete_person(USER_ID)
        post.assert_not_called()
        assert "pytest" in caplog.text

    @pytest.mark.parametrize(
        "outcome",
        [RuntimeError("dns"), MagicMock(status_code=500), MagicMock(status_code=400)],
    )
    def test_failures_never_raise(self, on, outcome, caplog):
        kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
        with patch("httpx.post", **kwargs), caplog.at_level(logging.WARNING, "sapling.posthog"):
            posthog_client.delete_person(USER_ID)
        assert "PostHog person delete" in caplog.text

    def test_account_route_schedules_the_delete_after_the_soft_delete(self):
        from main import app

        order: list[str] = []

        def table_side_effect(name):
            m = MagicMock()
            m.update.side_effect = lambda *a, **k: order.append(f"update:{name}") or [{}]
            return m

        with patch("routes.profile.require_self"), \
             patch("routes.profile.table", side_effect=table_side_effect), \
             patch("routes.profile.delete_posthog_person",
                   side_effect=lambda uid: order.append(f"posthog:{uid}")):
            r = TestClient(app).request(
                "DELETE", f"/api/profile/{USER_ID}/account", json={"confirmation": "DELETE"},
            )
        assert r.status_code == 200 and r.json() == {"deleted": True}
        assert order == ["update:users", f"posthog:{USER_ID}"]

    def test_wrong_confirmation_never_touches_posthog(self):
        from main import app

        with patch("routes.profile.require_self"), \
             patch("routes.profile.table"), \
             patch("routes.profile.delete_posthog_person") as delete:
            r = TestClient(app).request(
                "DELETE", f"/api/profile/{USER_ID}/account", json={"confirmation": "nope"},
            )
        assert r.status_code == 400
        delete.assert_not_called()
