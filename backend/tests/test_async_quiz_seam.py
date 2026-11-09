"""routes/quiz.py's attempt handlers on the async DB seam (#117; wave 2 of
docs/design/async-db-client.md §4.1).

GET /attempts/{id}, POST /attempts/{id}/answer and /abandon are `async def`
over the `a*` twins (the sweep hops to a worker thread). End to end over the
REAL ``SupabaseTable`` onto an ``httpx.MockTransport`` (the ``wire`` fixture
of test_async_handlers_off_loop.py: ``no_sync_db_on_loop`` on, and no sync
PostgREST request may leave from an event-loop thread), with
``async_db_client`` off and on.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

import routes.quiz as quiz_routes
from main import app
from tests.test_async_handlers_off_loop import Wire, wire  # noqa: F401 (fixture)
from tests.test_quiz_lifecycle_d import _attempt_row

client = TestClient(app)


def test_attempt_handlers_are_async_and_submit_stays_sync():
    for name in ("generate_quiz", "list_attempts", "get_attempt", "answer_question",
                 "abandon_attempt"):
        assert inspect.iscoroutinefunction(getattr(quiz_routes, name)), name
    # submit_quiz runs apply_graph_update + the scoring chain: plain def.
    assert not inspect.iscoroutinefunction(quiz_routes.submit_quiz)


def _mode(w: Wire, mode: str, native: set[tuple[str, str]]) -> None:
    if mode == "on":
        assert native <= set(w.native)
    else:
        assert w.native == []
        assert native <= {(m, n) for m, n, _ in w.calls}


@pytest.mark.parametrize("async_mode", ["off", "on"])
def test_get_attempt(wire, monkeypatch, async_mode):  # noqa: F811
    monkeypatch.setenv("SAPLING_FLAG_ASYNC_DB_CLIENT", async_mode)
    wire.rows[("GET", "quiz_attempts")] = [_attempt_row()]
    r = client.get("/api/quiz/attempts/quiz1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "in_progress" and body["resumable"] is True
    assert body["questions"] and all("correct" not in str(q) for q in body["questions"])
    _mode(wire, async_mode, {("GET", "quiz_attempts"), ("GET", "quiz_responses")})


@pytest.mark.parametrize("async_mode", ["off", "on"])
def test_answer_question(wire, monkeypatch, async_mode):  # noqa: F811
    monkeypatch.setenv("SAPLING_FLAG_ASYNC_DB_CLIENT", async_mode)
    wire.rows[("GET", "quiz_attempts")] = [_attempt_row()]
    r = client.post("/api/quiz/attempts/quiz1/answer",
                    json={"question_index": 0, "selected_index": 0})
    assert r.status_code == 200, r.text
    assert r.json()["recorded"] is True
    _mode(wire, async_mode, {("GET", "quiz_attempts"), ("GET", "quiz_responses"),
                             ("POST", "quiz_responses")})


@pytest.mark.parametrize("async_mode", ["off", "on"])
def test_abandon_attempt(wire, monkeypatch, async_mode):  # noqa: F811
    monkeypatch.setenv("SAPLING_FLAG_ASYNC_DB_CLIENT", async_mode)
    wire.rows[("GET", "quiz_attempts")] = [_attempt_row()]
    wire.rows[("PATCH", "quiz_attempts")] = [
        {"abandoned_at": "2099-01-01T00:00:00+00:00"}]
    r = client.post("/api/quiz/attempts/quiz1/abandon")
    assert r.status_code == 200, r.text
    assert r.json() == {"quiz_id": "quiz1", "status": "abandoned",
                        "abandoned_at": "2099-01-01T00:00:00+00:00"}
    _mode(wire, async_mode, {("GET", "quiz_attempts"), ("PATCH", "quiz_attempts")})


def test_a_foreign_attempt_is_still_refused(wire, monkeypatch):  # noqa: F811
    """The owner check still runs on the attempt's owner (the suite stubs the
    guard open; this one refuses anyone but the signed-in student)."""
    from fastapi import HTTPException

    def _require_self(user_id, request, **_kw):
        if user_id != "user_andres":
            raise HTTPException(status_code=403, detail="Forbidden: not your account")

    monkeypatch.setattr(quiz_routes, "require_self", _require_self)
    wire.rows[("GET", "quiz_attempts")] = [_attempt_row(user_id="someone_else")]
    for method, path, body in (
        ("get", "/api/quiz/attempts/quiz1", None),
        ("post", "/api/quiz/attempts/quiz1/answer", {"question_index": 0, "selected_index": 0}),
        ("post", "/api/quiz/attempts/quiz1/abandon", None),
    ):
        r = getattr(client, method)(path, **({"json": body} if body else {}))
        assert r.status_code == 403, (path, r.text)
    assert not any(m != "GET" for m, _n, _ in wire.calls)
