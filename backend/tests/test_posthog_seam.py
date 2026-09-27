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

from services import ai_observability, analytics_consent, events_service, posthog_client
from services.ai_observability import AllowlistSpanProcessor, bind_ai_context
from services.analytics_consent import Consent

# The shape production actually issues (routes/auth.py: f"user_{google_id}").
# users.id is TEXT, not a UUID — a UUID-only rule would drop every real user.
USER_ID = "user_109876543210987654321"
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


_REAL_LOOKUP = analytics_consent._lookup


@pytest.fixture(autouse=True)
def consent_db(monkeypatch):
    """Stand-in for the users/user_settings read behind analytics_consent:
    user id -> Consent. Anything not listed is DENIED, exactly as a missing
    users row is. Records every lookup so tests can count round trips."""
    answers: dict[str, Consent] = {USER_ID: Consent.ALLOWED}
    calls: list[str] = []

    def fake_lookup(uid):
        calls.append(uid)
        answer = answers.get(uid, Consent.DENIED)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(analytics_consent, "_lookup", fake_lookup)
    analytics_consent.clear_analytics_consent_cache()
    # Other suites call auth_guard.get_session_user_id directly on the test
    # thread, which notes a session user in THAT context; start each test here
    # from the request-free defaults, as the sweeper or a fresh request does.
    from services.request_context import _PRIVACY_SIGNAL_CTX, _SESSION_USER_CTX

    user_token = _SESSION_USER_CTX.set(None)
    signal_token = _PRIVACY_SIGNAL_CTX.set(False)
    try:
        yield SimpleNamespace(answers=answers, calls=calls)
    finally:
        _PRIVACY_SIGNAL_CTX.reset(signal_token)
        _SESSION_USER_CTX.reset(user_token)
        analytics_consent.clear_analytics_consent_cache()


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
            "note_id": "n1", "has_body": True, "event_category": "usage",
            "request_id": "req-123",
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


@pytest.fixture
def run_boundary():
    """The Agent.iter wrapper that binds attribution per run (installed in
    production by posthog_ai_span_processors when PostHog is on)."""
    ai_observability.install_agent_run_boundary()
    try:
        yield
    finally:
        ai_observability.uninstall_agent_run_boundary()


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
        messages = json.dumps([{"role": "user", "parts": [{"content": SECRET}]}])
        with bind_ai_context(session_id="sess-1", distinct_id=USER_ID, request_id="req-1"), \
             tracer.start_as_current_span("chat gemini-2.5-flash") as span:
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
        with bind_ai_context(session_id="sess-1", distinct_id=USER_ID, request_id="req-1"), \
             tracer.start_as_current_span("running tool") as span:
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
        # Even a gen_ai-looking span from a non-Pydantic-AI tracer stays out.
        with tracer.start_as_current_span("chat x") as span:
            span.set_attribute("gen_ai.request.model", "m")
        assert exporter.get_finished_spans() == ()

    def test_the_live_span_is_not_mutated_for_logfire(self):
        """Attribution is added to the COPY; Logfire's span keeps its own set."""
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        raw = InMemorySpanExporter()
        provider.add_span_processor(AllowlistSpanProcessor(SimpleSpanProcessor(exporter)))
        provider.add_span_processor(SimpleSpanProcessor(raw))
        with bind_ai_context(session_id=None, distinct_id=USER_ID, request_id="r"), \
             provider.get_tracer("pydantic-ai").start_as_current_span("chat m") as span:
            span.set_attribute("gen_ai.request.model", "m")
        assert "posthog.distinct_id" not in raw.get_finished_spans()[0].attributes
        assert exporter.get_finished_spans()[0].attributes["posthog.distinct_id"] == USER_ID

    def test_a_broken_delegate_never_raises_into_tracing(self):
        delegate = MagicMock()
        delegate.on_end.side_effect = RuntimeError("exporter down")
        provider = TracerProvider()
        provider.add_span_processor(AllowlistSpanProcessor(delegate))
        with provider.get_tracer("pydantic-ai").start_as_current_span("chat m") as span:
            span.set_attribute("gen_ai.request.model", "m")

    @pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
    def test_real_pydantic_ai_run_reaches_posthog_without_content(self, version, run_boundary):
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

        deps = SimpleNamespace(user_id=USER_ID, session_id=None, request_id="req-9")
        result = asyncio.run(agent.run(f"hello {SECRET}", deps=deps))
        assert SECRET in result.output  # the run really carried the content
        # Bound for the run only: nothing is left behind in this context.
        assert ai_observability._AI_ATTRIBUTION.get() is None

        spans = exporter.get_finished_spans()
        assert spans, "no AI spans reached the PostHog delegate"
        for s in spans:
            assert SECRET not in _dump(s), f"content leaked on span {s.name!r}"
            assert s.attributes.get("posthog.distinct_id") == USER_ID
            assert s.attributes.get("$ai_session_id") == "req-9"
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


# ── 6. Review fixes (PR #677) ───────────────────────────────────────────────
#
# One class per /code-review finding, so each regression is findable.


class TestConsentLookup:
    """analytics_consent: the one read behind every "may this user be named"
    decision — shape, placeholders, deletion, opt-out, failure, caching."""

    def _real(self, monkeypatch, rows=None, exc=None):
        monkeypatch.setattr(analytics_consent, "_lookup", _REAL_LOOKUP)
        t = MagicMock()
        if exc is not None:
            t.return_value.select.side_effect = exc
        else:
            t.return_value.select.return_value = rows
        monkeypatch.setattr("db.connection.table", t)
        return t

    @pytest.mark.parametrize("rows, expect", [
        ([{"id": USER_ID, "deleted_at": None, "user_settings": {"analytics_opt_out": False}}],
         Consent.ALLOWED),
        ([{"id": USER_ID, "deleted_at": None, "user_settings": [{"analytics_opt_out": False}]}],
         Consent.ALLOWED),
        # No settings row yet = the column default (not opted out).
        ([{"id": USER_ID, "deleted_at": None, "user_settings": None}], Consent.ALLOWED),
        ([{"id": USER_ID, "deleted_at": None, "user_settings": {"analytics_opt_out": True}}],
         Consent.DENIED),
        # Soft-deleted: a new event would re-create the deleted person.
        ([{"id": USER_ID, "deleted_at": "2026-09-26T00:00:00Z",
           "user_settings": {"analytics_opt_out": False}}], Consent.DENIED),
        # Unknown id.
        ([], Consent.DENIED),
        # A row that does not answer the question fails closed.
        ([{"id": USER_ID, "deleted_at": None, "user_settings": {}}], Consent.DENIED),
    ])
    def test_row_shapes(self, monkeypatch, rows, expect):
        t = self._real(monkeypatch, rows=rows)
        assert analytics_consent.consent_for(USER_ID) is expect
        t.assert_called_once_with("users")
        cols = t.return_value.select.call_args.args[0]
        assert "deleted_at" in cols and "user_settings(analytics_opt_out)" in cols

    def test_lookup_failure_fails_closed(self, monkeypatch, caplog):
        self._real(monkeypatch, exc=RuntimeError("postgrest down"))
        with caplog.at_level(logging.WARNING, "sapling.analytics_consent"):
            assert analytics_consent.consent_for(USER_ID) is Consent.DENIED
        assert "not sending" in caplog.text

    @pytest.mark.parametrize("uid", [
        None, "", "  ", "anonymous", "Anonymous", "backfill", "system", "unknown",
        "has space", "semi;colon", "x" * 200, 42,
    ])
    def test_placeholders_are_no_user_without_a_lookup(self, uid, consent_db):
        assert analytics_consent.consent_for(uid) is Consent.NO_USER
        assert consent_db.calls == []

    @pytest.mark.parametrize("uid", [
        # Real id shapes in this codebase: production google ids, the seeded
        # e2e/staging users, and a UUID. None of these may be dropped by shape.
        "user_109876543210987654321", "seed-user-demo", "rich-student-1",
        "9b2f6a3e-1c1d-4c55-9a8e-2f1f0e6b7a10",
    ])
    def test_real_id_shapes_are_looked_up(self, uid, consent_db):
        consent_db.answers[uid] = Consent.ALLOWED
        assert analytics_consent.consent_for(uid) is Consent.ALLOWED
        assert consent_db.calls == [uid]

    def test_cached_per_process_and_cleared_by_the_hook(self, consent_db):
        for _ in range(5):
            assert analytics_consent.consent_for(USER_ID) is Consent.ALLOWED
        assert consent_db.calls == [USER_ID]  # one round trip, not five
        consent_db.answers[USER_ID] = Consent.DENIED
        assert analytics_consent.consent_for(USER_ID) is Consent.ALLOWED  # still cached
        analytics_consent.clear_analytics_consent_cache(USER_ID)
        assert analytics_consent.consent_for(USER_ID) is Consent.DENIED
        assert consent_db.calls == [USER_ID, USER_ID]

    def test_entries_expire(self, consent_db, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(analytics_consent.time, "monotonic", lambda: now[0])
        analytics_consent.consent_for(USER_ID)
        now[0] += analytics_consent._TTL_S + 1
        analytics_consent.consent_for(USER_ID)
        assert consent_db.calls == [USER_ID, USER_ID]


class TestOptOut:
    """Finding 1: the mirror, exceptions and AI spans honour the stored
    opt-out and the DNT / GPC request headers."""

    def test_opted_out_user_is_not_mirrored_but_our_row_is_kept(
        self, fake_client, consent_db, sink,
    ):
        consent_db.answers[USER_ID] = Consent.DENIED
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        fake_client.capture.assert_not_called()
        events_service.flush_now()
        assert [r["event_type"] for r in sink] == ["note.created"]

    def test_unreadable_consent_sends_nothing(self, fake_client, consent_db, sink):
        consent_db.answers[USER_ID] = RuntimeError("db down")
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        fake_client.capture.assert_not_called()

    def test_per_event_reads_are_cached(self, fake_client, consent_db, sink):
        for _ in range(20):
            events_service.log_event("note.created", category="usage", user_id=USER_ID)
        assert fake_client.capture.call_count == 20
        assert consent_db.calls == [USER_ID]

    def test_session_user_opt_out_covers_events_without_a_user(
        self, fake_client, consent_db, sink,
    ):
        from services.request_context import _SESSION_USER_CTX

        consent_db.answers[USER_ID] = Consent.DENIED
        token = _SESSION_USER_CTX.set(USER_ID)
        try:
            events_service.log_event("rag.index_failed", category="error", payload={})
        finally:
            _SESSION_USER_CTX.reset(token)
        fake_client.capture.assert_not_called()

    def test_opted_out_exception_is_not_captured(self, fake_client, consent_db):
        consent_db.answers[USER_ID] = Consent.DENIED
        posthog_client.capture_exception(ValueError("x"), user_id=USER_ID, request_id="r")
        fake_client.capture_exception.assert_not_called()

    @pytest.mark.parametrize("headers, signal", [
        ({"Sec-GPC": "1"}, True),
        ({"DNT": "1"}, True),
        ({"DNT": "0"}, False),
        ({"Sec-GPC": "0"}, False),
        ({}, False),
    ])
    def test_privacy_headers_through_the_middleware(
        self, headers, signal, fake_client, sink,
    ):
        """End to end through RequestIDMiddleware: an event logged inside the
        handler, and the middleware's own error.5xx, are both skipped for a
        DNT/GPC request."""
        from fastapi import FastAPI

        from services.request_context import RequestIDMiddleware

        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/api/thing/{thing_id}")
        async def thing(thing_id: str):
            events_service.log_event("note.created", category="usage", user_id=USER_ID)
            raise RuntimeError("boom")

        r = TestClient(app, raise_server_exceptions=False).get("/api/thing/abc", headers=headers)
        assert r.status_code == 500
        sent = [c.args[0] for c in fake_client.capture.call_args_list]
        assert sent == ([] if signal else ["note.created", "error.5xx"])
        events_service.flush_now()
        # Our own table is unaffected by the browser signal.
        assert {"note.created", "error.5xx"} <= {r["event_type"] for r in sink}

    def test_opted_out_user_ai_spans_are_not_exported(self, consent_db, run_boundary):
        consent_db.answers[USER_ID] = Consent.DENIED
        spans = _run_tiny_agent(SimpleNamespace(user_id=USER_ID, session_id="s", request_id="r"))
        assert spans == ()

    def test_privacy_header_suppresses_ai_spans(self, run_boundary):
        from services.request_context import _PRIVACY_SIGNAL_CTX

        token = _PRIVACY_SIGNAL_CTX.set(True)
        try:
            spans = _run_tiny_agent(
                SimpleNamespace(user_id=USER_ID, session_id=None, request_id="r"),
            )
        finally:
            _PRIVACY_SIGNAL_CTX.reset(token)
        assert spans == ()

    def test_unreadable_consent_suppresses_ai_spans(self, consent_db, run_boundary):
        consent_db.answers[USER_ID] = RuntimeError("db down")
        spans = _run_tiny_agent(SimpleNamespace(user_id=USER_ID, session_id=None, request_id="r"))
        assert spans == ()


class TestSettingsContract:
    """The shared contract with the frontend (PR #675): PATCH accepts
    analytics_opt_out, GET returns it, and the PATCH invalidates the cache."""

    def _tables(self, row):
        captured: dict = {}

        def table_side_effect(name):
            m = MagicMock()
            if name == "user_settings":
                m.select.return_value = [row]
                m.update.side_effect = (
                    lambda data, filters: captured.update({"data": data}) or [{}]
                )
            else:
                m.select.return_value = []
            return m

        return table_side_effect, captured

    def test_patch_accepts_and_invalidates(self, consent_db):
        from main import app

        analytics_consent.consent_for(USER_ID)  # warm the cache: ALLOWED
        consent_db.answers[USER_ID] = Consent.DENIED  # the DB after the write
        table_side_effect, captured = self._tables({"user_id": USER_ID})
        with patch("routes.profile.require_self"), \
             patch("routes.profile.table", side_effect=table_side_effect):
            r = TestClient(app).patch(
                f"/api/profile/{USER_ID}/settings", json={"analytics_opt_out": True},
            )
        assert r.status_code == 200
        assert captured["data"]["analytics_opt_out"] is True
        # The very next read in this process sees the opt-out.
        assert analytics_consent.consent_for(USER_ID) is Consent.DENIED

    def test_other_fields_do_not_invalidate(self, consent_db):
        from main import app

        table_side_effect, _ = self._tables({"user_id": USER_ID})
        with patch("routes.profile.require_self"), \
             patch("routes.profile.table", side_effect=table_side_effect), \
             patch("routes.profile.clear_analytics_consent_cache") as clear:
            TestClient(app).patch(f"/api/profile/{USER_ID}/settings", json={"theme": "dark"})
        clear.assert_not_called()

    def test_get_selects_and_returns_the_column(self):
        from main import app
        from routes.profile import _SETTINGS_COLS

        assert "analytics_opt_out" in _SETTINGS_COLS.split(",")
        table_side_effect, _ = self._tables({"user_id": USER_ID, "analytics_opt_out": True})
        with patch("routes.profile.require_self"), \
             patch("routes.profile.table", side_effect=table_side_effect):
            r = TestClient(app).get(f"/api/profile/{USER_ID}/settings")
        assert r.status_code == 200 and r.json()["analytics_opt_out"] is True

    def test_non_boolean_is_rejected(self):
        from main import app

        table_side_effect, captured = self._tables({"user_id": USER_ID})
        with patch("routes.profile.require_self"), \
             patch("routes.profile.table", side_effect=table_side_effect):
            r = TestClient(app).patch(
                f"/api/profile/{USER_ID}/settings", json={"analytics_opt_out": "maybe"},
            )
        assert r.status_code == 422 and "data" not in captured

    def test_migration_adds_the_column(self):
        from pathlib import Path

        migrations = Path(__file__).resolve().parents[1] / "db" / "migrations"
        hits = [
            p for p in migrations.glob("2*.sql")
            if "analytics_opt_out" in p.read_text()
        ]
        assert len(hits) == 1
        sql = " ".join(
            line for line in hits[0].read_text().splitlines()
            if not line.lstrip().startswith("--")
        )
        sql = " ".join(sql.split()).lower()
        assert (
            "alter table user_settings add column if not exists analytics_opt_out "
            "boolean not null default false"
        ) in sql


class TestCategoryKey:
    """Finding 2: the #117 category no longer clobbers a payload's own."""

    def test_payload_category_survives(self, fake_client, sink):
        events_service.log_event(
            "document.processed", category="usage", user_id=USER_ID,
            payload={"category": "syllabus", "doc_id": "d1"},
        )
        props = fake_client.capture.call_args.kwargs["properties"]
        assert props["category"] == "syllabus"
        assert props["event_category"] == "usage"


class TestDeletedUsers:
    """Finding 3: no event re-creates a deleted person; queues drain first."""

    def test_deleted_user_is_skipped(self, fake_client, consent_db, sink):
        consent_db.answers[USER_ID] = Consent.DENIED  # deleted_at is set
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        fake_client.capture.assert_not_called()

    def test_account_delete_invalidates_the_cached_yes(self, consent_db):
        from main import app

        analytics_consent.consent_for(USER_ID)  # cached ALLOWED
        consent_db.answers[USER_ID] = Consent.DENIED  # the row after the soft delete
        with patch("routes.profile.require_self"), \
             patch("routes.profile.table"), \
             patch("routes.profile.delete_posthog_person"):
            r = TestClient(app).request(
                "DELETE", f"/api/profile/{USER_ID}/account", json={"confirmation": "DELETE"},
            )
        assert r.status_code == 200
        assert analytics_consent.consent_for(USER_ID) is Consent.DENIED

    def test_person_delete_flushes_both_queues_before_the_request(
        self, monkeypatch, fake_client,
    ):
        monkeypatch.setattr(posthog_client, "disabled_reason", lambda: None)
        monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_key")
        monkeypatch.setenv("POSTHOG_PROJECT_ID", "4242")
        monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")
        monkeypatch.delenv("POSTHOG_API_HOST", raising=False)
        order: list[str] = []
        fake_client.flush.side_effect = lambda **k: order.append("events")
        processor = MagicMock()
        processor.force_flush.side_effect = lambda t: order.append("spans")
        monkeypatch.setattr(ai_observability, "_processor", processor)
        with patch("httpx.post", side_effect=lambda *a, **k: order.append("delete")
                   or MagicMock(status_code=202)):
            posthog_client.delete_person(USER_ID)
        assert order == ["events", "spans", "delete"]
        assert fake_client.flush.call_args.kwargs["timeout_seconds"] > 0


class TestSentinelIds:
    """Finding 4: only a real users.id becomes a distinct_id."""

    @pytest.mark.parametrize("uid", ["anonymous", "backfill", None])
    def test_placeholder_mirrors_personless(self, uid, fake_client, consent_db, sink):
        events_service.log_event("note.created", category="usage", user_id=uid)
        assert fake_client.capture.call_args.kwargs["distinct_id"] is None
        assert consent_db.calls == []

    def test_unknown_id_is_skipped(self, fake_client, consent_db, sink):
        events_service.log_event("note.created", category="usage", user_id="quizfix-user-0001")
        fake_client.capture.assert_not_called()

    def test_real_non_uuid_id_is_attributed(self, fake_client, sink):
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        assert fake_client.capture.call_args.kwargs["distinct_id"] == USER_ID

    @pytest.mark.parametrize("uid", ["backfill", "anonymous"])
    def test_placeholder_ai_run_is_unattributed(self, uid, run_boundary):
        spans = _run_tiny_agent(SimpleNamespace(user_id=uid, session_id=None, request_id="r"))
        assert spans
        assert all("posthog.distinct_id" not in s.attributes for s in spans)


class TestErrorEvents:
    """Finding 5: error.4xx stays home; error.5xx carries the route template."""

    def test_4xx_is_not_mirrored(self, fake_client, sink):
        events_service.log_event(
            "error.4xx", category="error", user_id=USER_ID,
            payload={"path": f"/api/profile/{USER_ID}", "status_code": 404},
        )
        fake_client.capture.assert_not_called()
        events_service.flush_now()
        assert [r["event_type"] for r in sink] == ["error.4xx"]

    @pytest.mark.parametrize("payload, expect", [
        ({"path": f"/api/profile/{USER_ID}", "route": "/api/profile/{user_id}"},
         "/api/profile/{user_id}"),
        ({"path": "/wp-login.php"}, "<unmatched>"),
    ])
    def test_5xx_path_is_the_template(self, payload, expect, fake_client, sink):
        events_service.log_event("error.5xx", category="error", user_id=USER_ID, payload=payload)
        props = fake_client.capture.call_args.kwargs["properties"]
        assert props["path"] == expect
        assert f"/api/profile/{USER_ID}" not in json.dumps(props)
        events_service.flush_now()
        assert sink[0]["payload"]["path"] == payload["path"]  # our row keeps it


class TestRunBoundary:
    """Finding 6: attribution is bound for one run and reset — nothing leaks
    from a SaplingDeps constructor into later runs or BackgroundTasks."""

    def test_constructing_deps_binds_nothing(self):
        from agents.deps import SaplingDeps

        SaplingDeps(user_id=USER_ID, course_id=None, supabase=None, request_id="r")
        assert ai_observability._AI_ATTRIBUTION.get() is None

    def test_a_later_deps_less_run_does_not_inherit(self, run_boundary):
        async def two_runs():
            spans_a = await _run_tiny_agent_async(
                SimpleNamespace(user_id=USER_ID, session_id="s1", request_id="r1"),
            )
            spans_b = await _run_tiny_agent_async(None)
            return spans_a, spans_b

        spans_a, spans_b = asyncio.run(two_runs())
        assert spans_a and all(
            s.attributes.get("posthog.distinct_id") == USER_ID for s in spans_a
        )
        assert spans_b and all("posthog.distinct_id" not in s.attributes for s in spans_b)

    def test_bind_resets_on_exit_and_on_error(self):
        with bind_ai_context(session_id="s", distinct_id=USER_ID, request_id="r"):
            assert ai_observability._AI_ATTRIBUTION.get().distinct_id == USER_ID
        assert ai_observability._AI_ATTRIBUTION.get() is None
        with pytest.raises(ValueError):
            with bind_ai_context(session_id="s", distinct_id=USER_ID, request_id="r"):
                raise ValueError
        assert ai_observability._AI_ATTRIBUTION.get() is None

    def test_install_is_idempotent_and_reversible(self):
        from pydantic_ai import Agent

        original = Agent.iter
        ai_observability.install_agent_run_boundary()
        try:
            wrapped = Agent.iter
            ai_observability.install_agent_run_boundary()
            assert Agent.iter is wrapped and wrapped is not original
        finally:
            ai_observability.uninstall_agent_run_boundary()
        assert Agent.iter is original

    def test_processor_factory_installs_the_boundary(self, monkeypatch):
        from pydantic_ai import Agent

        monkeypatch.setattr(posthog_client, "disabled_reason", lambda: None)
        monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
        original = Agent.iter
        try:
            with patch("posthog.ai.otel.PostHogSpanProcessor"):
                procs = list(ai_observability.posthog_ai_span_processors())
            assert len(procs) == 1 and ai_observability._processor is procs[0]
            assert Agent.iter is not original
        finally:
            ai_observability.uninstall_agent_run_boundary()
            monkeypatch.setattr(ai_observability, "_processor", None)
        assert Agent.iter is original

    def test_session_user_attributes_a_deps_less_run(self, run_boundary):
        from services.request_context import _SESSION_USER_CTX

        token = _SESSION_USER_CTX.set(USER_ID)
        try:
            spans = _run_tiny_agent(None)
        finally:
            _SESSION_USER_CTX.reset(token)
        assert spans and all(s.attributes.get("posthog.distinct_id") == USER_ID for s in spans)


class TestApiHost:
    """Finding 7: the personal key only ever goes to a PostHog app host."""

    @pytest.mark.parametrize("ingest, expect", [
        ("https://us.i.posthog.com", "https://us.posthog.com"),
        ("https://eu.i.posthog.com/", "https://eu.posthog.com"),
        ("https://US.I.POSTHOG.COM", "https://us.posthog.com"),
        ("https://ph.example.com", None),
        ("https://evil.i.posthog.com.attacker.net", None),
        ("http://us.i.posthog.com", None),
    ])
    def test_derivation(self, ingest, expect, monkeypatch):
        import config

        monkeypatch.setenv("POSTHOG_HOST", ingest)
        monkeypatch.delenv("POSTHOG_API_HOST", raising=False)
        assert config.posthog_api_host() == expect

    def test_explicit_host_wins(self, monkeypatch):
        import config

        monkeypatch.setenv("POSTHOG_HOST", "https://ph.example.com")
        monkeypatch.setenv("POSTHOG_API_HOST", "https://ph-app.example.com/")
        assert config.posthog_api_host() == "https://ph-app.example.com"

    def test_unknown_host_skips_the_delete_with_a_warning(self, monkeypatch, caplog):
        monkeypatch.setattr(posthog_client, "disabled_reason", lambda: None)
        monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_key")
        monkeypatch.setenv("POSTHOG_PROJECT_ID", "4242")
        monkeypatch.setenv("POSTHOG_HOST", "https://ph.example.com")
        monkeypatch.delenv("POSTHOG_API_HOST", raising=False)
        with patch("httpx.post") as post, caplog.at_level(logging.WARNING, "sapling.posthog"):
            posthog_client.delete_person(USER_ID)
        post.assert_not_called()
        assert "POSTHOG_API_HOST" in caplog.text and "skipped" in caplog.text


class TestSpanProcessorCost:
    """Finding 8: is_ai_span resolved once; non-AI-scope spans do no work."""

    def test_is_ai_span_resolved_at_construction(self):
        from posthog.ai.otel import is_ai_span

        proc = AllowlistSpanProcessor(MagicMock())
        assert proc._is_ai_span is is_ai_span

    def test_non_ai_scope_spans_skip_lock_and_bookkeeping(self):
        delegate = MagicMock()
        proc = AllowlistSpanProcessor(delegate)
        proc._lock = MagicMock()  # any acquisition would be recorded
        proc._is_ai_span = MagicMock(return_value=True)
        provider = TracerProvider()
        provider.add_span_processor(proc)
        tracer = provider.get_tracer("opentelemetry.instrumentation.httpx")
        with bind_ai_context(session_id="s", distinct_id=USER_ID, request_id="r"):
            for _ in range(10):
                with tracer.start_as_current_span("GET"):
                    pass
        proc._lock.__enter__.assert_not_called()
        proc._is_ai_span.assert_not_called()
        delegate.on_end.assert_not_called()
        assert proc._pending == {}


class TestRequestIdOnce:
    """Finding 10: log_event resolves the ambient request id once."""

    def test_single_resolution_shared_by_row_and_mirror(self, fake_client, sink, monkeypatch):
        calls: list[int] = []

        def rid():
            calls.append(1)
            return f"rid-{len(calls)}"

        monkeypatch.setattr(events_service, "current_request_id", rid)
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        assert len(calls) == 1
        events_service.flush_now()
        assert sink[0]["request_id"] == "rid-1"
        assert fake_client.capture.call_args.kwargs["properties"]["request_id"] == "rid-1"


class TestSpanLevelDistinctId:
    """Finding 9: PostHog's OTLP capture resolves distinct_id per SPAN, span
    attributes first (rust/capture/src/otel/identity.rs,
    extract_distinct_id_for_span). So the id must be on each exported span —
    and it is, on the sanitized copy, for every AI span of the run."""

    def test_every_exported_span_carries_it_at_span_level(self, run_boundary):
        spans = _run_tiny_agent(SimpleNamespace(user_id=USER_ID, session_id=None, request_id="r"))
        assert spans
        for s in spans:
            assert s.attributes["posthog.distinct_id"] == USER_ID
            # Never on the resource: that is per process, not per user.
            assert "posthog.distinct_id" not in s.resource.attributes


# ── helpers for section 6 ───────────────────────────────────────────────────


async def _run_tiny_agent_async(deps):
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.models.instrumented import InstrumentationSettings

    provider, exporter = _pipeline()
    agent = Agent(
        FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart("ok")])),
        instrument=InstrumentationSettings(tracer_provider=provider),
    )
    await agent.run("hi", deps=deps)
    assert ai_observability._AI_ATTRIBUTION.get() is None  # reset at run end
    return exporter.get_finished_spans()


def _run_tiny_agent(deps):
    return asyncio.run(_run_tiny_agent_async(deps))
