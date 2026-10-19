"""PKG-14 review fix round: with the kill switch thrown, a rate-limited loop route
answers the spec §7 404 before any 401 (no session) or 429 (rate limited)."""

import pytest
from fastapi.testclient import TestClient

import config
from routes import learn_loop
from services import ai_budget

RATE_LIMITED_POSTS = sorted(
    r.path
    for r in learn_loop.router.routes
    if "POST" in getattr(r, "methods", set())
    and ai_budget.enforce_rate_limit in {d.call for d in r.dependant.dependencies}
)


def test_there_are_rate_limited_loop_routes():
    assert len(RATE_LIMITED_POSTS) >= 10


def test_kill_switch_dependency_runs_before_the_rate_limit():
    for r in learn_loop.router.routes:
        if not hasattr(r, "dependant"):
            continue
        calls = [d.call for d in r.dependant.dependencies]
        if ai_budget.enforce_rate_limit in calls:
            assert calls.index(learn_loop._kill_switch_first) < calls.index(
                ai_budget.enforce_rate_limit
            ), r.path


@pytest.mark.parametrize("path", RATE_LIMITED_POSTS)
def test_kill_switch_answers_404_without_a_session(monkeypatch, path):
    from main import app

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)

    def _no_rate_limit_read(_request):
        raise AssertionError("the rate limit ran under the kill switch")

    monkeypatch.setattr(ai_budget, "_rate_limit_decision", _no_rate_limit_read)
    client = TestClient(app)
    res = client.post("/api/learn/loop" + path, json={})
    assert res.status_code == 404, (path, res.status_code, res.text)


def test_gate_on_is_not_404d_by_the_kill_switch_dependency(monkeypatch):
    """Gate on: the request gets past the kill-switch dependency to the handler —
    whatever it answers, it is never the kill switch's 404 detail."""
    from main import app

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    res = TestClient(app).post(
        "/api/learn/loop/chat",
        json={"user_id": "u-1", "session_id": "s-1", "message": "hi"},
    )
    assert res.json().get("detail") != learn_loop._NOT_ENABLED, res.text
