"""The learning loop's `async def` handlers make no sync PostgREST call on the
event loop (#117 on the loop, after its #118 split into services/loop/).

The runtime half, end to end, as tests/test_async_handlers_off_loop.py does it
for the rest of the app: nothing here patches a loop module's `table`. Every
DB call runs through the REAL `SupabaseTable` onto an `httpx.MockTransport`
(the `wire` fixture), the `no_sync_db_on_loop` fixture makes `db.sync_on_loop`
raise, and the transport records whether each request left from an
event-loop thread. A sync call some handler code catches and degrades on (the
AI budget's usage read does) would hide the raise, so `blocked` also records
every attempt the guard sees, before any `except` can swallow it. The session row is a teach-phase loop session, so each
handler reads (and, where it gets that far, writes) before it answers; the
model is a stub that refuses, so no turn reaches a provider.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from tests.split_patches import patch_loop
from tests import test_async_handlers_off_loop as _off_loop

wire = _off_loop.wire  # the real-table mock transport fixture

client = TestClient(app, raise_server_exceptions=False)
USER = "user_andres"
LOOP = "/api/learn/loop"

_SESSION = {
    "id": "s1",
    "user_id": USER,
    "offering_id": "off-1",
    "mode": "socratic",
    "topic": "Recursion",
    "loop_state": {"phase": "teach", "concept": "n1"},
    "loop_state_rev": 0,
    "close_json": None,
}

#: (path, body): every async handler of routes/learn_loop.py.
ROUTES = [
    ("/chat", {"user_id": USER, "session_id": "s1", "message": "Explain recursion"}),
    ("/chat/stream", {"user_id": USER, "session_id": "s1", "message": "Explain recursion"}),
    ("/action", {"user_id": USER, "session_id": "s1", "action_type": "hint"}),
    ("/start-session", {"user_id": USER, "topic": "Recursion"}),
    ("/start-session/stream", {"user_id": USER, "topic": "Recursion"}),
    ("/check/answer", {"user_id": USER, "session_id": "s1", "question_hash": "qh", "answer": "x"}),
    ("/check/answer/stream", {"user_id": USER, "session_id": "s1", "question_hash": "qh", "answer": "x"}),
    ("/prequestion/answer", {"user_id": USER, "session_id": "s1", "question_hash": "qh", "answer": "x"}),
    ("/prequestion/answer/stream",
     {"user_id": USER, "session_id": "s1", "question_hash": "qh", "answer": "x"}),
    ("/probe/answer", {"user_id": USER, "session_id": "s1", "question_hash": "qh", "answer": "x"}),
    ("/posttest/answer", {"user_id": USER, "node_id": "n1", "question_hash": "qh", "answer": "x"}),
    ("/review/answer", {"user_id": USER, "session_id": "r1", "kind": "check", "item_id": "i1",
                        "answer": "x"}),
    ("/close", {"user_id": USER, "session_id": "s1"}),
]


@pytest.fixture
def blocked(monkeypatch):
    """Every sync PostgREST call the runtime guard sees ON a running event loop,
    recorded (and still raised, under `no_sync_db_on_loop`)."""
    import db.async_connection as adb

    seen: list[str] = []
    real = adb.note_sync_call

    def note(target):
        if not adb._IN_ASYNC_SEAM.get() and asyncio._get_running_loop() is not None:
            seen.append(target or "?")
        return real(target)

    monkeypatch.setattr(adb, "note_sync_call", note)
    return seen


def test_every_async_loop_handler_is_listed():
    import inspect

    from routes import learn_loop

    async_paths = {
        r.path for r in learn_loop.router.routes if inspect.iscoroutinefunction(r.endpoint)
    }
    assert async_paths == {path for path, _ in ROUTES}


@pytest.mark.parametrize("path, body", ROUTES, ids=[p for p, _ in ROUTES])
def test_the_loop_handler_reads_and_writes_off_the_event_loop(wire, blocked, path, body):
    wire.rows[("GET", "sessions")] = [_SESSION]
    wire.rows[("GET", "users")] = [{"id": USER, "deleted_at": None, "is_approved": True}]
    agent = MagicMock()
    agent.run = AsyncMock(side_effect=RuntimeError("no model in this test"))
    with (
        patch_loop("learning_loop_for_request", return_value=True),
        patch_loop("loop_tutor_agent", agent),
    ):
        r = client.post(LOOP + path, json=body)
        r.read()
    # the answer is whatever the handler gives a minimal session; what is
    # pinned is that it reached the database, and never from the loop (the
    # `wire` fixture asserts that on teardown)
    assert blocked == [], f"sync PostgREST call(s) on the event loop: {blocked}"
    assert r.status_code != 500, r.text
    assert wire.calls, "the handler made no PostgREST request: the test is vacuous"
