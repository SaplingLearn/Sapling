"""Audit Z02: the direct /api/learn/loop/* routes charge the same atomic abuse
budgets as the legacy tutor routes that delegate to them (TUTOR_SESSION_START,
TUTOR_TURN), and the loop's no-model writers a LOOP_ACTION budget. The A20
limiter counts llm_usage rows, so on its own it never trips on a request that
runs no model (a probe-phase opener, a hint, a rating...)."""
import inspect
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import config
from learning import gate as loop_gate
from main import app
from routes import learn_loop
from services import abuse_limits, ai_budget, crisis_support, request_limits

client = TestClient(app)

#: The conftest's session stub for a body-only request.
SESSION_USER = "user_andres"

#: Routes whose budget is a route dependency (they carry the kill switch).
EXPECTED = {
    ("POST", "/start-session"): abuse_limits.TUTOR_SESSION_START,
    ("POST", "/start-session/stream"): abuse_limits.TUTOR_SESSION_START,
    **{("POST", p): abuse_limits.TUTOR_TURN for p in (
        "/chat", "/chat/stream", "/action", "/check/answer", "/check/answer/stream",
        "/prequestion/answer", "/prequestion/answer/stream", "/step/attempt",
        "/self-explain", "/posttest/answer",
    )},
    **{("POST", p): abuse_limits.LOOP_ACTION for p in ("/rating", "/report", "/posttest/start")},
}

#: Routes without a dependency: the handler charges its budget inline, after
#: its gate (a gate-off student gets the 404) and after any inline crisis
#: screen (a crisis turn consumes no unit). (key, budget name, what precedes it)
INLINE = {
    ("POST", "/probe/answer"): ("TUTOR_TURN", "crisis_support.screen_async"),
    ("POST", "/review/answer"): ("LOOP_ACTION", "crisis_support.screen_async"),
    ("POST", "/hint"): ("LOOP_ACTION", "_gate("),
    ("POST", "/check/next"): ("LOOP_ACTION", "_gate("),
    ("POST", "/plan/approve"): ("LOOP_ACTION", "_gate("),
    ("POST", "/close"): ("LOOP_ACTION", "_agate("),
    ("GET", "/review/next"): ("LOOP_ACTION", "_gate("),
    ("GET", "/review/summary"): ("LOOP_ACTION", "_gate("),
}

#: Reads, and the routes that carry their own per-user limiter
#: (`_probe_plan_read_limit`, `_posttest_light_limit`).
UNCHARGED = {
    ("GET", "/status"), ("GET", "/sessions"), ("GET", "/plan"), ("GET", "/posttest/due"),
    ("GET", "/review/active"), ("POST", "/goal"), ("POST", "/probe/next"),
    ("POST", "/posttest/shown"),
}


def _routes():
    for r in learn_loop.router.routes:
        for method in getattr(r, "methods", ()):
            if method in ("GET", "POST"):
                yield (method, r.path), r


def _charge_of(route):
    calls = [d.call for d in route.dependant.dependencies]
    charges = [c for c in calls if hasattr(c, "abuse_limit")]
    return calls, charges


def test_every_loop_route_is_charged_or_named_exempt():
    assert {key for key, _ in _routes()} == set(EXPECTED) | set(INLINE) | UNCHARGED


@pytest.mark.parametrize("key", sorted(EXPECTED), ids=lambda k: f"{k[0]} {k[1]}")
def test_the_route_charges_its_budget_after_the_gate_and_screen(key):
    route = dict(_routes())[key]
    calls, charges = _charge_of(route)
    assert len(charges) == 1, key
    assert charges[0].abuse_limit is EXPECTED[key], key
    at = calls.index(charges[0])
    assert calls.index(learn_loop._kill_switch_first) < at, key
    screens = [i for i, c in enumerate(calls) if crisis_support.is_screen(c) or c.__name__ == "crisis_screen"]
    assert all(i < at for i in screens), key
    if ai_budget.enforce_rate_limit in calls:
        assert at < calls.index(ai_budget.enforce_rate_limit), key


@pytest.mark.parametrize("key", sorted(INLINE), ids=lambda k: f"{k[0]} {k[1]}")
def test_the_handler_charges_its_budget_inline_after_its_gate(key):
    import services.loop as loop

    route = dict(_routes())[key]
    assert _charge_of(route)[1] == [], key
    budget, after = INLINE[key]
    source = inspect.getsource(getattr(loop, route.endpoint.__name__))
    charge = f"enforce_abuse_limit(abuse_limits.{budget}, "
    assert source.count(charge) == 1, key
    assert source.index(after) < source.index(charge), key
    if "enforce_rate_limit_for" in source:
        assert source.index(charge) < source.index("enforce_rate_limit_for"), key


@pytest.mark.parametrize("key", sorted(UNCHARGED), ids=lambda k: f"{k[0]} {k[1]}")
def test_an_exempt_route_carries_no_charge(key):
    import services.loop as loop

    route = dict(_routes())[key]
    assert _charge_of(route)[1] == []
    assert "enforce_abuse_limit(" not in inspect.getsource(getattr(loop, route.endpoint.__name__))


def _exhaust(limit, subject):
    for _ in range(limit.limit):
        assert request_limits.check_rate_limit(
            f"{limit.name}:{subject}", limit=limit.limit, window_sec=limit.window_sec,
        ) is None


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    monkeypatch.setattr(loop_gate, "learning_loop_for_request", lambda uid: True)


SPENT = [
    (abuse_limits.TUTOR_SESSION_START, "post", "/start-session", {"user_id": SESSION_USER, "topic": "Recursion"}),
    (abuse_limits.TUTOR_TURN, "post", "/check/answer",
     {"user_id": SESSION_USER, "session_id": "s1", "item_id": "i1", "answer": "B"}),
    (abuse_limits.TUTOR_TURN, "post", "/chat", {"user_id": SESSION_USER, "session_id": "s1", "message": "hi"}),
    (abuse_limits.LOOP_ACTION, "post", "/hint", {"user_id": SESSION_USER, "session_id": "s1", "question_hash": "q1"}),
    (abuse_limits.LOOP_ACTION, "get", f"/review/next?user_id={SESSION_USER}", None),
]


@pytest.mark.parametrize("limit,method,path,body", SPENT, ids=[p for _, _, p, _ in SPENT])
def test_a_spent_budget_is_a_429_before_the_handler(gate_on, limit, method, path, body):
    _exhaust(limit, SESSION_USER)

    def _no_a20(_request):
        raise AssertionError("the A20 limiter ran past a spent abuse budget")

    with patch.object(ai_budget, "_rate_limit_decision", _no_a20), patch("db.connection._client") as db:
        kwargs = {"json": body} if body is not None else {}
        r = getattr(client, method)("/api/learn/loop" + path, **kwargs)
    assert r.status_code == 429, r.text
    assert r.json()["detail"].startswith(limit.detail)
    assert 1 <= int(r.headers["Retry-After"]) <= limit.window_sec
    touched = [c.args[0] for verb in (db.get, db.post, db.patch, db.delete) for c in verb.call_args_list if c.args]
    assert all("feature_flag" in p for p in touched), touched


def test_budgets_are_per_student(gate_on):
    _exhaust(abuse_limits.LOOP_ACTION, "someone-else")
    with patch("services.loop.review_next", return_value={"item": None}) as handler:
        r = client.get(f"/api/learn/loop/review/next?user_id={SESSION_USER}")
    assert r.status_code == 200, r.text
    handler.assert_called_once()
