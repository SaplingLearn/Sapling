"""The per-student `learning_loop` flag (owner decision 2026-11-11).

The loop is on for a student only when the env kill switch
(`LEARNING_LOOP_ENABLED`) is not thrown AND their `learning_loop` flag is on
(learning/gate.py). The flag ships off, so a student nobody turned on gets the
pre-loop app — exactly the kill switch's. Pinned here:

- the gate's truth table, and that a thrown kill switch reads nothing (no flag,
  no session);
- the flag is registered off-first and client-visible;
- flag off under an open kill switch answers every loop route exactly as the
  kill switch does, and the legacy tutor does not hand off to the loop;
- only the named sites resolve the uploader's gate.

The kill_switch-marked tests elsewhere run twice (tests/conftest.py
LOOP_OFF_VIA), so every legacy-path pin holds for flag-off too.
"""

from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import config
from learning import gate
from routes import learn_loop
from services import feature_flags
from services.loop.constants import _NOT_ENABLED
from test_learning_loop_invariants import db_client_calls

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _loop_off(monkeypatch, how: str) -> None:
    if how == "kill_switch":
        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
    else:
        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", "off")


# ── the gate ────────────────────────────────────────────────────────────────


def test_the_flag_is_registered_off_first_and_client_visible():
    fd = feature_flags.REGISTRY[gate.LEARNING_LOOP_FLAG]
    assert fd.key == "learning_loop"
    assert fd.variants == ("off", "on")
    assert fd.client_visible is True


@pytest.mark.parametrize(
    "env_on, flag, user, expected",
    [
        (True, "on", "u1", True),
        (True, "off", "u1", False),
        (False, "on", "u1", False),
        (False, "off", "u1", False),
        (True, "on", None, False),
        (True, "on", "", False),
    ],
)
def test_truth_table(monkeypatch, env_on, flag, user, expected):
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", env_on)
    monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", flag)
    assert gate.learning_loop_active(user) is expected
    assert gate.learning_loop_for_request(user) is expected
    assert gate.learning_loop_for_uploader(user) is expected


def test_the_flag_ships_off(monkeypatch):
    """No env override and no stored configuration: the flag resolves off, so
    the gate is off for every student while the kill switch stays open."""
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    monkeypatch.delenv("SAPLING_FLAG_LEARNING_LOOP", raising=False)
    monkeypatch.setattr(
        feature_flags,
        "_get_snapshot",
        lambda fresh=False: feature_flags.Snapshot(flags={}, targets={}),
    )
    assert feature_flags.explain("learning_loop", "u1") == feature_flags.Resolution(
        "off", "default", "no stored configuration"
    )
    assert gate.learning_loop_active("u1") is False


def test_a_thrown_kill_switch_reads_no_flag(monkeypatch):
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
    monkeypatch.delenv("SAPLING_FLAG_LEARNING_LOOP", raising=False)

    def boom(*_a, **_k):
        raise AssertionError("the kill switch read the flag")

    monkeypatch.setattr(gate, "flag_on", boom)
    before = db_client_calls()
    assert gate.learning_loop_active("u1") is False
    assert db_client_calls()[len(before):] == []


def test_the_gate_dependency_reads_no_session_under_the_kill_switch(monkeypatch):
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)

    def boom(*_a, **_k):
        raise AssertionError("the kill switch looked up the session")

    from services import auth_guard

    monkeypatch.setattr(auth_guard, "get_session_user_id", boom)
    request = SimpleNamespace(state=SimpleNamespace())
    assert learn_loop._loop_gate_for_session(request) is False
    assert request.state.learning_loop == (None, False)


def test_the_gate_dependency_resolves_once_and_carries_it(monkeypatch):
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    calls = []
    monkeypatch.setattr(gate, "learning_loop_for_request", lambda uid: calls.append(uid) or True)
    request = SimpleNamespace(state=SimpleNamespace(), query_params={}, path_params={})
    assert learn_loop._loop_gate_for_session(request) is True
    assert learn_loop._loop_gate_for_session(request) is True
    learn_loop._kill_switch_first(request)
    assert calls == ["user_andres"]  # the hermetic session user, resolved once
    assert request.state.learning_loop == ("user_andres", True)


# ── flag off == the kill switch, route by route ─────────────────────────────


def _loop_routes():
    for route in learn_loop.router.routes:
        for method in sorted(getattr(route, "methods", set()) - {"HEAD"}):
            yield method, route.path


_PARAMS = {"user_id": "u1", "session_id": "s1", "course_id": "c1"}
_BODY = {
    "user_id": "u1", "session_id": "s1", "message": "hi", "answer": "x", "reason": "r",
    "question_hash": "qh-1", "concept_ids": ["n1"], "node_id": "n1", "kind": "check",
    "item_id": "i1", "course_id": "c1", "topic": "Recursion", "action_type": "hint",
    "attempt_text": "n == 0", "rating": 5, "text": "goal", "reply": "because",
    "category": "wrong_answer", "posttest_id": "p1",
}
#: The bodies that forbid extra fields get exactly theirs, so every loop route
#: reaches its gate.
_STRICT_BODIES = {
    "/posttest/shown": {"user_id": "u1", "node_id": "n1", "question_hash": "qh-1"},
    "/probe/answer": {"user_id": "u1", "session_id": "s1", "question_hash": "qh-1", "answer": "x"},
    "/review/answer": {
        "user_id": "u1", "session_id": "s1", "kind": "check", "item_id": "i1", "answer": "x",
    },
}


def _without_request_ids(body):
    """The house error envelope stamps each response with its own request id."""
    if isinstance(body, dict):
        return {k: _without_request_ids(v) for k, v in body.items() if k != "request_id"}
    if isinstance(body, list):
        return [_without_request_ids(v) for v in body]
    return body


def _answers(monkeypatch, how: str) -> dict:
    """Every loop route's (status, body) for an authenticated student, the loop
    off `how`. No model may run and no loop table may be read."""
    from main import app

    _loop_off(monkeypatch, how)
    client = TestClient(app)
    out = {}
    before = db_client_calls()
    for method, path in _loop_routes():
        url = "/api/learn/loop" + path
        if method == "GET":
            r = client.get(url, params=_PARAMS)
        else:
            body = _STRICT_BODIES.get(path, _BODY)
            r = client.request(method, url, params={"user_id": "u1"}, json=body)
        out[(method, path)] = (r.status_code, _without_request_ids(r.json()))
    reads = [
        c for c in db_client_calls()[len(before):]
        # the request logger's error.4xx rows (events_service) are the app's,
        # flushed whenever its queue drains; every other call would be the loop's
        if not (c.args and str(c.args[0]).endswith("/rest/v1/events"))
    ]
    assert reads == [], f"{how}: a loop route reached the database"
    return out


def test_flag_off_answers_every_loop_route_exactly_as_the_kill_switch(monkeypatch):
    kill = _answers(monkeypatch, "kill_switch")
    flag_off = _answers(monkeypatch, "flag_off")
    assert flag_off == kill
    assert kill[("GET", "/review/active")] == (200, {"active": False})
    for key, answer in kill.items():
        if key != ("GET", "/review/active"):
            assert answer == (404, {"detail": _NOT_ENABLED}), (key, answer)
    assert len(kill) >= 30


@pytest.mark.parametrize("how", ["kill_switch", "flag_off"])
def test_the_legacy_tutor_does_not_hand_off_when_the_loop_is_off(monkeypatch, how):
    from routes import learn

    _loop_off(monkeypatch, how)
    request = SimpleNamespace(state=SimpleNamespace())
    for name in ("start_session", "chat", "chat_stream", "start_session_stream", "action", "end_session"):
        assert learn._loop_for("u1", name, request) is None, name
        assert request.state.learning_loop == ("u1", False)


def test_the_legacy_tutor_hands_off_with_the_flag_on(monkeypatch):
    from routes import learn

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", "on")
    request = SimpleNamespace(state=SimpleNamespace())
    assert callable(learn._loop_for("u1", "chat", request))
    assert request.state.learning_loop == ("u1", True)


@pytest.mark.parametrize("how", ["kill_switch", "flag_off"])
def test_the_quiz_learning_flags_need_the_loop(monkeypatch, how):
    from services import quiz_learning

    _loop_off(monkeypatch, how)
    keys = (quiz_learning.CONCEPT_PLAN_FLAG, quiz_learning.RESULTS_ROUTING_FLAG)
    for key in keys:
        monkeypatch.setenv(f"SAPLING_FLAG_{key.upper()}", "on")
    assert quiz_learning.quiz_flags("u1", *keys) == (False, False)
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", "on")
    for key in keys:
        monkeypatch.setenv(f"SAPLING_FLAG_{key.upper()}", "on")
    assert quiz_learning.quiz_flags("u1", *keys) == (True, True)


# ── who resolves the uploader's gate ────────────────────────────────────────

#: Upload-time work with no student request behind it decides by the
#: uploader's gate, once per upload, at exactly these places.
UPLOADER_SITES = {
    ("routes/documents.py", "upload_document_sync"),
    ("services/documents/post_roll.py", "_stream_index_steps"),
    ("services/document_jobs.py", "_post_roll"),
}


def test_only_the_upload_post_rolls_resolve_the_uploaders_gate():
    found = set()
    for top in ("routes", "services", "agents", "learning", "worker"):
        for path in sorted((BACKEND / top).rglob("*.py")):
            rel = path.relative_to(BACKEND).as_posix()
            if rel == "learning/gate.py":
                continue
            tree = ast.parse(path.read_text())
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(fn):
                    name = node.id if isinstance(node, ast.Name) else (
                        node.attr if isinstance(node, ast.Attribute) else None
                    )
                    if name == "learning_loop_for_uploader":
                        found.add((rel, fn.name))
    assert found == UPLOADER_SITES


def test_an_async_handler_reads_an_uncarried_gate_off_the_event_loop(monkeypatch):
    """`_agate`: with nothing carried for this student, the flag read (inside
    `_gate`) runs in the threadpool, never on the event loop's thread."""
    import asyncio
    import threading

    from services.loop import state

    seen = []

    def gate_read(uid):
        seen.append((uid, threading.current_thread() is threading.main_thread()))
        return True

    monkeypatch.setattr(state, "learning_loop_for_request", gate_read)
    request = SimpleNamespace(state=SimpleNamespace())
    assert asyncio.run(state._agate("u1", request)) is True
    assert seen == [("u1", False)]
    # carried for this student: no second read at all
    request.state.learning_loop = ("u1", False)
    with pytest.raises(Exception) as refused:
        asyncio.run(state._agate("u1", request))
    assert getattr(refused.value, "status_code", None) == 404
    assert seen == [("u1", False)]
