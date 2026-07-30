# backend/tests/test_learn_stream_routes.py
"""Route-level tests for the SSE chat streams."""
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

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
            # so we can assert on nonstream_fallback wiring after the request.
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

        # The Rung-1 nonstream fallback must be wired into stream_agent_turn
        # so an agent failure before any token degrades to the JSON turn
        # (_chat_turn_json) instead of erroring outright.
        assert stream_kwargs.get("nonstream_fallback") is not None, (
            "nonstream_fallback must be passed to stream_agent_turn (Rung-1 fallback)"
        )
        assert inspect.iscoroutinefunction(stream_kwargs["nonstream_fallback"])

    def test_nonstream_fallback_runs_chat_turn_json_on_fast_tier(self):
        """D2 (#151a): the stream route's Rung-1 fallback is the JSON turn
        (_chat_turn_json) forced onto the FAST tier — a different, faster
        model is a materially better second chance than re-rolling the same
        tier, and it bounds the client's 45s idle window."""
        async def fake_stream(**kwargs):
            from services.agent_events import SaplingEvent
            fallback_result = await kwargs["nonstream_fallback"]()
            yield SaplingEvent(type="done", step="reply", message="Complete.",
                               data=fallback_result)

        turn = AsyncMock(return_value={
            "reply": "fallback reply", "graph_update": {}, "mastery_changes": [],
        })
        with patch("routes.learn.stream_agent_turn", fake_stream), \
             patch("routes.learn._prepare_chat_run",
                   return_value=(MagicMock(), "msg", {}, MagicMock())), \
             patch("routes.learn._chat_turn_json", turn), \
             patch("routes.learn._consume_pending"), \
             patch("routes.learn._get_session_offering_id", return_value="off-1"), \
             patch("routes.learn.offering_course_id", return_value="c1"), \
             patch("routes.learn._load_message_history", return_value=[]):
            r = client.post("/api/learn/chat/stream", json={
                "session_id": "s1", "user_id": "u1", "message": "hello",
                "mode": "socratic", "model_pref": "smart",
            })

        assert r.status_code == 200
        assert "fallback reply" in r.text
        turn.assert_awaited_once()
        assert turn.await_args.kwargs["model_pref"] == "fast", (
            "the Rung-1 fallback must force the fast tier regardless of the "
            "body's own model_pref"
        )

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

    def test_nonstream_fallback_wired_and_stashes_exactly_once(self):
        """Finding 1 regression (reworked for #151a): start_session_stream
        used to pass no fallback, diverging from the spec's Rung 1. Mirrors
        TestChatStream's wiring assertion, then goes further: simulates
        stream_agent_turn's REAL mutual-exclusion contract (Rung 1 invokes
        ONLY nonstream_fallback, never on_complete) and proves the fallback
        stashes PENDING_SESSIONS exactly once via the shared
        _start_session_agent helper (a mocked agent run — the legacy
        pipeline is gone) — no double-stash, no double-persist. Also pins
        D2: the fallback re-runs on the FAST tier.
        """
        from types import SimpleNamespace

        stream_kwargs = {}

        async def fake_stream(**kwargs):
            stream_kwargs.update(kwargs)
            from services.agent_events import SaplingEvent
            # Rung 1: agent failed before any token. Real stream_agent_turn
            # calls ONLY nonstream_fallback here, never on_complete — that
            # exclusivity is exactly what this test is pinning.
            fallback_result = await kwargs["nonstream_fallback"]()
            yield SaplingEvent(type="token", step="reply", message="",
                                data={"delta": fallback_result["reply"]})
            yield SaplingEvent(type="done", step="reply", message="Complete.",
                                data=fallback_result)

        from routes.learn import PENDING_SESSIONS
        PENDING_SESSIONS.clear()

        fallback_agent = MagicMock()
        fallback_agent.run = AsyncMock(
            return_value=SimpleNamespace(output="Fallback greeting")
        )
        fallback_deps = SimpleNamespace(graph_updates=[], mastery_changes=[])

        with patch("routes.learn.stream_agent_turn", fake_stream), \
             patch("routes.learn._prepare_chat_run",
                   return_value=(fallback_agent, "msg", {}, fallback_deps)) as prep, \
             patch("routes.learn._get_course_id_for_topic", return_value="c1"), \
             patch("routes.learn.resolve_offering", return_value="off-1"), \
             patch("routes.learn.get_graph", return_value={"nodes": []}), \
             patch("routes.learn.table") as tbl:
            r = client.post("/api/learn/start-session/stream", json={
                "user_id": "u1", "topic": "Eigenvalues", "mode": "socratic",
            })

        assert r.status_code == 200
        assert stream_kwargs.get("nonstream_fallback") is not None, (
            "nonstream_fallback must be passed to stream_agent_turn (Rung-1 fallback)"
        )
        assert inspect.iscoroutinefunction(stream_kwargs["nonstream_fallback"])

        assert len(PENDING_SESSIONS) == 1, (
            "nonstream_fallback must stash PENDING_SESSIONS exactly once "
            "(via _start_session_agent) — never zero, never twice"
        )
        stashed = next(iter(PENDING_SESSIONS.values()))
        assert stashed["assistant_reply"] == "Fallback greeting"
        assert stashed["topic"] == "Eigenvalues"
        assert "Fallback greeting" in r.text, (
            "the fallback reply must reach the client as a token/done"
        )
        tbl.assert_not_called()

        # Two _prepare_chat_run calls: the route's own (body pref, None) and
        # the fallback's — which must force the fast tier (D2).
        prefs = [c.kwargs["model_pref"] for c in prep.call_args_list]
        assert prefs == [None, "fast"], (
            "the Rung-1 fallback must re-run _start_session_agent with "
            "model_pref='fast'"
        )


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
