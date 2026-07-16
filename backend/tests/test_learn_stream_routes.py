# backend/tests/test_learn_stream_routes.py
"""Route-level tests for the SSE chat streams."""
import inspect
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _sse_events(text: str) -> list[str]:
    """Event names from a raw SSE body."""
    return [
        line.split("event:", 1)[1].strip()
        for line in text.splitlines()
        if line.startswith("event:")
    ]


class TestChatStream:
    def test_streams_tokens_then_done(self):
        # Distinctive sentinel (not []) so an accidental `message_history=[]`
        # in the route is caught by the assertion below, instead of silently
        # matching whatever the mock happens to default to.
        history_sentinel = [{"sentinel": "prior-turns"}]

        stream_kwargs = {}

        async def fake_stream(**kwargs):
            # Capture exactly what the route hands to stream_agent_turn,
            # so we can assert on legacy_fallback wiring after the request.
            stream_kwargs.update(kwargs)
            from services.agent_events import SaplingEvent
            yield SaplingEvent(type="status", step="start", message="Starting.")
            yield SaplingEvent(type="token", step="reply", message="", data={"delta": "Hi"})
            kwargs["on_complete"]("Hi", {}, [])
            yield SaplingEvent(type="done", step="reply", message="Complete.",
                               data={"reply": "Hi", "graph_update": {}, "mastery_changes": []})

        saved = []
        with patch("routes.learn.stream_agent_turn", fake_stream), \
             patch("routes.learn._prepare_chat_run",
                   return_value=(MagicMock(), "msg", {}, MagicMock())) as prep, \
             patch("routes.learn._consume_pending"), \
             patch("routes.learn._get_session_offering_id", return_value="off-1"), \
             patch("routes.learn.offering_course_id", return_value="c1"), \
             patch("routes.learn._load_message_history", return_value=history_sentinel), \
             patch("routes.learn.save_message", side_effect=lambda *a, **k: saved.append(a)):
            r = client.post("/api/learn/chat/stream", json={
                "session_id": "s1", "user_id": "u1", "message": "hello", "mode": "socratic",
                "model_pref": "smart",
            })

        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        assert _sse_events(r.text) == ["status", "token", "done"]
        assert [a[1] for a in saved] == ["user", "assistant"], "user row persists before assistant"

        # Wiring into _prepare_chat_run: prior turns loaded before the new
        # user row is written (message_history), correct course scoping,
        # the actual user message, and the model override — all as the
        # route actually passes them, not whatever the mock defaults to.
        prep_kwargs = prep.call_args.kwargs
        assert prep_kwargs["message_history"] is history_sentinel, (
            "message_history must be exactly what _load_message_history returned "
            "(loaded BEFORE the new user row is written), not [] or something else"
        )
        assert prep_kwargs["course_id"] == "c1"
        assert prep_kwargs["user_message"] == "hello"
        assert prep_kwargs["model_pref"] == "smart"

        # Rung-1 legacy fallback must be wired into stream_agent_turn so an
        # agent failure before any token degrades to _legacy_chat instead of
        # erroring outright.
        assert stream_kwargs.get("legacy_fallback") is not None, (
            "legacy_fallback must be passed to stream_agent_turn (Rung-1 fallback)"
        )
        assert inspect.iscoroutinefunction(stream_kwargs["legacy_fallback"])

    def test_requires_self(self):
        """The guard must run BEFORE any streaming work starts.

        Note the strict assertions: an earlier draft wrapped this in
        try/except Exception: pass, which swallowed the AssertionError and
        made the test pass even when auth was bypassed entirely.
        """
        from fastapi import HTTPException

        with patch("routes.learn.require_self",
                   side_effect=HTTPException(status_code=403, detail="forbidden")) as guard, \
             patch("routes.learn._consume_pending"), \
             patch("routes.learn._prepare_chat_run") as prep:
            r = client.post("/api/learn/chat/stream", json={
                "session_id": "s1", "user_id": "someone-else",
                "message": "hi", "mode": "socratic",
            })

        assert r.status_code == 403
        guard.assert_called_once()
        assert not prep.called, "auth must gate before any agent setup"


class TestStartSessionStream:
    def test_stashes_pending_session_and_does_not_write_db(self):
        async def fake_stream(**kwargs):
            from services.agent_events import SaplingEvent
            extra = kwargs["on_complete"]("Welcome!", {}, [])
            yield SaplingEvent(type="done", step="reply", message="Complete.",
                               data={"reply": "Welcome!", **extra})

        from routes.learn import PENDING_SESSIONS
        PENDING_SESSIONS.clear()

        with patch("routes.learn.stream_agent_turn", fake_stream), \
             patch("routes.learn._prepare_chat_run",
                   return_value=(MagicMock(), "msg", {}, MagicMock())) as prep, \
             patch("routes.learn._get_course_id_for_topic", return_value="c1"), \
             patch("routes.learn.resolve_offering", return_value="off-1"), \
             patch("routes.learn.get_graph", return_value={"nodes": []}), \
             patch("routes.learn.table") as tbl:
            r = client.post("/api/learn/start-session/stream", json={
                "user_id": "u1", "topic": "Eigenvalues", "mode": "socratic",
            })

        assert r.status_code == 200
        assert len(PENDING_SESSIONS) == 1, "session must be stashed, not written"
        stashed = next(iter(PENDING_SESSIONS.values()))
        assert stashed["assistant_reply"] == "Welcome!"
        assert stashed["topic"] == "Eigenvalues"
        tbl.assert_not_called()

        # A brand-new session genuinely has no prior turns; pin that literal
        # (not a mock artifact) so a regression that starts loading history
        # here — or drops it — is caught.
        assert prep.call_args.kwargs["message_history"] == [], (
            "a new session must start with no prior message history"
        )
