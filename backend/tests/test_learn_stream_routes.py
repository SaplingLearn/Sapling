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

    def test_legacy_fallback_wired_and_stashes_exactly_once(self):
        """Finding 1 regression: start_session_stream used to pass
        legacy_fallback=None, diverging from the spec's Rung 1 ("falls back
        to the existing start_session body"). Mirrors TestChatStream's
        wiring assertion, then goes further: simulates stream_agent_turn's
        REAL mutual-exclusion contract (Rung 1 invokes ONLY
        legacy_fallback, never on_complete) and proves the fallback stashes
        PENDING_SESSIONS exactly once via the shared _start_session_legacy
        helper — no double-stash, no double-persist.
        """
        stream_kwargs = {}

        async def fake_stream(**kwargs):
            stream_kwargs.update(kwargs)
            from services.agent_events import SaplingEvent
            # Rung 1: agent failed before any token. Real stream_agent_turn
            # calls ONLY legacy_fallback here, never on_complete — that
            # exclusivity is exactly what this test is pinning.
            legacy_result = await kwargs["legacy_fallback"]()
            yield SaplingEvent(type="token", step="reply", message="",
                                data={"delta": legacy_result["reply"]})
            yield SaplingEvent(type="done", step="reply", message="Complete.",
                                data=legacy_result)

        from routes.learn import PENDING_SESSIONS
        PENDING_SESSIONS.clear()

        with patch("routes.learn.stream_agent_turn", fake_stream), \
             patch("routes.learn._prepare_chat_run",
                   return_value=(MagicMock(), "msg", {}, MagicMock())), \
             patch("routes.learn._get_course_id_for_topic", return_value="c1"), \
             patch("routes.learn.resolve_offering", return_value="off-1"), \
             patch("routes.learn.get_graph", return_value={"nodes": []}), \
             patch("routes.learn.get_user_name", return_value="Student"), \
             patch("routes.learn._get_course_documents", return_value=[]), \
             patch("routes.learn.build_system_prompt", return_value="prompt"), \
             patch("routes.learn.call_gemini_multiturn", return_value="raw"), \
             patch("routes.learn.extract_graph_update",
                   return_value=("Legacy greeting", {"new_nodes": []})), \
             patch("routes.learn.apply_graph_update", return_value=[]):
            r = client.post("/api/learn/start-session/stream", json={
                "user_id": "u1", "topic": "Eigenvalues", "mode": "socratic",
            })

        assert r.status_code == 200
        assert stream_kwargs.get("legacy_fallback") is not None, (
            "legacy_fallback must be passed to stream_agent_turn (Rung-1 fallback)"
        )
        assert inspect.iscoroutinefunction(stream_kwargs["legacy_fallback"])

        assert len(PENDING_SESSIONS) == 1, (
            "legacy_fallback must stash PENDING_SESSIONS exactly once "
            "(via _start_session_legacy) — never zero, never twice"
        )
        stashed = next(iter(PENDING_SESSIONS.values()))
        assert stashed["assistant_reply"] == "Legacy greeting"
        assert stashed["topic"] == "Eigenvalues"
        assert "Legacy greeting" in r.text, "the legacy reply must reach the client as a token/done"


class TestSseCompressionOptOut:
    """SSE responses must carry `Cache-Control: no-transform` (#356 journeys).

    The e2e stack (and any self-hosted `next start`) proxies /api/* through
    Next's production server, which wraps responses in the `compression`
    middleware unless config.compress is false. gzip BUFFERS small SSE
    frames: a paced token stream produced nothing client-side for its whole
    duration and arrived as one burst at `done` — progressive rendering
    silently broken behind that proxy. `no-transform` is the standard
    opt-out the middleware honors; sse_starlette only `setdefault`s its
    own Cache-Control, so the route's value must win.
    """

    def test_chat_stream_sets_no_transform(self):
        async def fake_stream(**kwargs):
            from services.agent_events import SaplingEvent
            yield SaplingEvent(type="done", step="reply", message="Complete.",
                               data={"reply": "Hi", "graph_update": {}, "mastery_changes": []})

        with patch("routes.learn.stream_agent_turn", fake_stream), \
             patch("routes.learn._prepare_chat_run",
                   return_value=(MagicMock(), "msg", {}, MagicMock())), \
             patch("routes.learn._consume_pending"), \
             patch("routes.learn._get_session_offering_id", return_value="off-1"), \
             patch("routes.learn.offering_course_id", return_value="c1"), \
             patch("routes.learn._load_message_history", return_value=[]):
            r = client.post("/api/learn/chat/stream", json={
                "session_id": "s1", "user_id": "u1", "message": "hello", "mode": "socratic",
            })
        assert r.status_code == 200
        assert "no-transform" in r.headers.get("cache-control", "")

    def test_start_session_stream_sets_no_transform(self):
        async def fake_stream(**kwargs):
            from services.agent_events import SaplingEvent
            yield SaplingEvent(type="done", step="reply", message="Complete.",
                               data={"reply": "Hello", "session_id": "s-new"})

        with patch("routes.learn.stream_agent_turn", fake_stream), \
             patch("routes.learn._prepare_chat_run",
                   return_value=(MagicMock(), "msg", {}, MagicMock())), \
             patch("routes.learn._get_course_id_for_topic", return_value=""), \
             patch("routes.learn.resolve_offering", return_value=""):
            r = client.post("/api/learn/start-session/stream", json={
                "user_id": "u1", "topic": "Recursion", "mode": "socratic",
            })
        assert r.status_code == 200
        assert "no-transform" in r.headers.get("cache-control", "")
