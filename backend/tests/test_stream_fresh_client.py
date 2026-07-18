# backend/tests/test_stream_fresh_client.py
"""Regression: streaming turns must run on a FRESH google.genai client.

A streaming tutor turn makes two sequential streamed model requests per run
(reply -> tool calls -> continuation). Reusing the shared module-level
provider's pooled HTTP connection across them raised
`RuntimeError: Event loop is closed` in google-genai's teardown, so EVERY
tool-calling turn died on the post-tool request (the JSON path is unaffected —
it uses a single non-streamed request per model call). The streaming routes
override the run model with a per-request fresh-provider GoogleModel; these
tests lock that in so the override can't be silently dropped.

The mocked unit/route tests can't reproduce the live crash (they never make a
real google-genai request) — hence this structural guard rather than a
behavioral one.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from agents._providers import _provider, fresh_google_model, model_name_for
from main import app
from routes.learn import _fresh_stream_model

client = TestClient(app)


class TestFreshClientHelpers:
    def test_fresh_google_model_never_shares_the_module_provider(self):
        m1 = fresh_google_model("gemini-2.5-flash-lite")
        m2 = fresh_google_model("gemini-2.5-flash-lite")
        # Each call builds its own provider == its own google.genai client and
        # HTTP connection pool. That isolation is the whole fix.
        assert m1.provider is not _provider
        assert m2.provider is not _provider
        assert m1.provider is not m2.provider
        # ...while preserving the requested model name.
        assert m1.model_name == "gemini-2.5-flash-lite"

    def test_fresh_stream_model_resolves_the_right_name(self):
        assert _fresh_stream_model("fast").model_name == "gemini-2.5-flash-lite"
        assert _fresh_stream_model("smart").model_name == "gemini-2.5-pro"
        # None (and any unknown pref) falls through to the chat_tutor default.
        assert _fresh_stream_model(None).model_name == model_name_for("chat_tutor")
        assert _fresh_stream_model("bogus").model_name == model_name_for("chat_tutor")

    def test_fresh_stream_model_is_always_fresh(self):
        assert _fresh_stream_model(None).provider is not _provider
        assert _fresh_stream_model("fast").provider is not _provider


def _capturing_stream(captured: dict):
    async def fake_stream(**kwargs):
        captured.update(kwargs)
        from services.agent_events import SaplingEvent
        yield SaplingEvent(type="status", step="start", message="Starting.")
        kwargs["on_complete"]("hi", {}, [])
        yield SaplingEvent(type="done", step="reply", message="Complete.",
                           data={"reply": "hi", "graph_update": {}, "mastery_changes": []})
    return fake_stream


class TestRoutesOverrideModelWithFreshClient:
    def test_chat_stream_passes_a_fresh_provider_model(self):
        captured: dict = {}
        with patch("routes.learn.stream_agent_turn", _capturing_stream(captured)), \
             patch("routes.learn._prepare_chat_run",
                   return_value=(MagicMock(), "msg", {}, MagicMock())), \
             patch("routes.learn._consume_pending"), \
             patch("routes.learn._get_session_offering_id", return_value="off-1"), \
             patch("routes.learn.offering_course_id", return_value="c1"), \
             patch("routes.learn._load_message_history", return_value=[]), \
             patch("routes.learn.save_message"):
            r = client.post("/api/learn/chat/stream", json={
                "session_id": "s1", "user_id": "u1", "message": "hello", "mode": "socratic",
            })
        assert r.status_code == 200
        model = captured["run_kwargs"].get("model")
        assert model is not None, "streaming route must set run_kwargs['model']"
        assert model.provider is not _provider, (
            "chat_stream must run on a fresh provider, not the shared module client"
        )

    def test_start_session_stream_passes_a_fresh_provider_model(self):
        captured: dict = {}
        with patch("routes.learn.stream_agent_turn", _capturing_stream(captured)), \
             patch("routes.learn._prepare_chat_run",
                   return_value=(MagicMock(), "msg", {}, MagicMock())), \
             patch("routes.learn.resolve_offering", return_value="off-1"), \
             patch("routes.learn.get_graph", return_value={"nodes": []}):
            r = client.post("/api/learn/start-session/stream", json={
                "user_id": "u1", "topic": "t", "course_id": "c1", "mode": "socratic",
            })
        assert r.status_code == 200
        model = captured["run_kwargs"].get("model")
        assert model is not None, "streaming route must set run_kwargs['model']"
        assert model.provider is not _provider, (
            "start_session_stream must run on a fresh provider, not the shared client"
        )
