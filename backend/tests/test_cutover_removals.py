"""PKG-14b: spec §11 removals and launch changes that inv_21's grep does not cover."""

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from tests.split_patches import patch_tutor
from tests.db_fakes import with_async_twins


def test_onboarding_ignores_learning_style():
    from models import OnboardingBody

    # main's onboarding (#886): a year choice and the accepted legal versions
    base = dict(
        user_id="u", first_name="A", last_name="B", year="junior", majors=["x"], course_ids=["c"],
        accepted_terms_version="t", accepted_privacy_version="p",
    )
    body = OnboardingBody(**base)
    assert body.learning_style is None
    # A legacy client that still sends it is accepted and the value ignored.
    assert OnboardingBody(**base, learning_style="visual").learning_style == "visual"
    from routes import onboarding

    assert "learning_style" not in inspect.getsource(onboarding.save_onboarding_profile)


@pytest.mark.kill_switch
def test_kill_switch_marker_turns_the_loop_off(loop_off_via):
    """Both ways (tests/conftest.py LOOP_OFF_VIA): the env kill switch, or the
    student's learning_loop flag off under an open switch."""
    import os

    import config
    from learning.gate import learning_loop_active

    if loop_off_via == "kill_switch":
        assert config.LEARNING_LOOP_ENABLED is False
    else:
        assert config.LEARNING_LOOP_ENABLED is True
        assert os.environ["SAPLING_FLAG_LEARNING_LOOP"] == "off"
    assert learning_loop_active("anyone") is False


def _route(path: str):
    """The route object on routes.learn's own router (never app.routes — the
    framework's included-router shape differs across fastapi versions)."""
    from routes import learn

    local = path.removeprefix("/api/learn")
    for r in learn.router.routes:
        if getattr(r, "path", None) == local and "POST" in getattr(r, "methods", set()):
            return r
    raise AssertionError(path)


@pytest.mark.parametrize(
    "path",
    [
        "/api/learn/start-session",
        "/api/learn/start-session/stream",
        "/api/learn/chat",
        "/api/learn/chat/stream",
        "/api/learn/action",
    ],
)
def test_no_delegating_route_reads_the_rate_limit_as_a_dependency(path):
    """A20 on the delegating routes (A93 review): the rate-limit read is never a
    route dependency, which FastAPI would run before the handler's require_self.
    The behaviour (no read on the loop-off path, the replay and the 409 before
    the read on the loop path) is pinned by the request tests below."""
    from services import ai_budget

    route = _route(path)
    deps = [d.call for d in route.dependant.dependencies]
    assert ai_budget.enforce_rate_limit not in deps, path


# ── legacy client (kill-switch path) ─────────────────────────────────────────


@pytest.fixture
def legacy_client():
    """TestClient over the real app with the legacy chat_tutor run site patched:
    `agent_runs` records every agent the route builds (routes.learn.agent_for_mode)."""
    from main import app

    client = TestClient(app)
    client.agent_runs = []

    def _agent_for_mode(mode):
        client.agent_runs.append(mode)
        agent = MagicMock()
        agent.run = AsyncMock(side_effect=AssertionError("agent ran past the budget check"))
        return agent

    def _table(name):
        m = MagicMock()
        m.select.return_value = [{"user_id": "user_andres", "offering_id": "off1", "mode": "socratic"}] if name == "sessions" else []
        m.update.return_value = []
        m.insert.return_value = []
        return m

    with (
        patch_tutor("agent_for_mode", side_effect=_agent_for_mode),
        patch_tutor("table", side_effect=with_async_twins(_table)),
    ):
        yield client


@pytest.fixture
def legacy_chat_body():
    return {
        "session_id": "s1",
        "user_id": "user_andres",
        "message": "What is recursion?",
        "mode": "socratic",
        "use_shared_context": True,
    }


def _hard():
    from services import ai_budget

    return ai_budget.BudgetDecision(level="hard", tier_ceiling="none", scope="daily_usd")


#: Every ai_budget entry point a request could read through, and the read
#: under them all (`_usage`: the one llm_usage read; `_tutor_calls_today`).
_AI_BUDGET_READS = (
    "check", "count_tutor_call", "enforce_rate_limit_for", "rate_limited",
    "_rate_limit_decision", "_usage", "_tutor_calls_today",
)


@pytest.fixture
def ai_budget_reads(monkeypatch):
    """Records every ai_budget read a request makes, and makes none."""
    from services import ai_budget

    reads = []
    for name in _AI_BUDGET_READS:
        monkeypatch.setattr(
            ai_budget, name, lambda *a, _name=name, **k: reads.append((_name, a)) or _hard()
        )
    return reads


@pytest.mark.kill_switch
@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/learn/chat", None),
        ("/api/learn/chat/stream", None),
        ("/api/learn/start-session", {"user_id": "user_andres", "topic": "Recursion", "mode": "socratic"}),
        ("/api/learn/start-session/stream", {"user_id": "user_andres", "topic": "Recursion", "mode": "socratic"}),
        ("/api/learn/action", {"session_id": "s1", "user_id": "user_andres", "action_type": "hint", "mode": "socratic"}),
    ],
)
def test_loop_off_tutor_routes_make_no_ai_budget_reads(
    legacy_client, legacy_chat_body, ai_budget_reads, path, body,
):
    """Owner decision 2026-11-18 ("caps only when the loop is on"): with the loop
    off (the kill switch, or the student's flag), every legacy tutor route runs as
    it did before the loop — straight to the tutor agent, under main's own limits
    — and makes no ai_budget read: no 429 at the loop's caps, no tutor-call count."""
    r = legacy_client.post(path, json=body or legacy_chat_body)
    assert r.status_code != 429, r.text
    assert legacy_client.agent_runs, "the legacy tutor agent was never reached"
    assert ai_budget_reads == []


def _must_not_hand_off(why: str):
    """A loop handler (resolved at route entry) that fails the test if called."""

    async def _handler(body, request):
        pytest.fail(why)

    return _handler


def test_loop_path_replays_a_persisted_turn_before_the_rate_limit(
    monkeypatch, legacy_client, legacy_chat_body, ai_budget_reads,
):
    """B3/B4: a JSON fallback that re-sends a turn the stream already persisted
    gets the stored reply, even at the cap: the replay precedes the rate-limit
    read and the hand-off, so the loop never runs the turn twice."""
    from routes import learn

    replay = {"reply": "saved", "graph_update": {}, "mastery_changes": [], "replayed": True}
    monkeypatch.setattr(learn, "learning_loop_for_request", lambda uid: True)
    monkeypatch.setattr(learn, "_loop_delegate", lambda name: _must_not_hand_off("the loop ran a replayed turn"))
    with patch_tutor("_persisted_turn", new=AsyncMock(return_value=replay)):
        r = legacy_client.post("/api/learn/chat", json={**legacy_chat_body, "turn_id": "turn-0001"})
        assert r.status_code == 200 and r.json() == replay
        s = legacy_client.post("/api/learn/chat/stream", json={**legacy_chat_body, "turn_id": "turn-0001"})
        assert s.status_code == 200 and '"saved"' in s.text
    assert ai_budget_reads == []


def test_loop_path_answers_the_ended_session_409_before_the_rate_limit(
    monkeypatch, legacy_chat_body, ai_budget_reads,
):
    """B3: a turn on an ended session is the SESSION_ENDED 409, never the loop's
    rate-limit 429 and never a hand-off."""
    from main import app
    from routes import learn

    def _table(name):
        m = MagicMock()
        m.select.return_value = (
            [{"user_id": "user_andres", "ended_at": "2026-11-18T00:00:00Z"}] if name == "sessions" else []
        )
        return m

    monkeypatch.setattr(learn, "learning_loop_for_request", lambda uid: True)
    monkeypatch.setattr(learn, "_loop_delegate", lambda name: _must_not_hand_off("an ended session was handed off"))
    with patch_tutor("table", side_effect=with_async_twins(_table)):
        client = TestClient(app)
        for path in ("/api/learn/chat", "/api/learn/chat/stream", "/api/learn/action"):
            body = legacy_chat_body if path != "/api/learn/action" else {
                "session_id": "s1", "user_id": "user_andres", "action_type": "hint", "mode": "socratic",
            }
            r = client.post(path, json=body)
            assert r.status_code == 409, (path, r.text)
    assert ai_budget_reads == []


def test_loop_path_delegates_after_only_the_rate_limit_read(monkeypatch, legacy_client, legacy_chat_body):
    """Loop on for this student (the suite turns the `learning_loop` flag on; it
    ships off): the legacy handler reads the rate limit, then delegates to the
    loop, whose own budget code runs. The legacy handler itself never runs
    `ai_budget.check`."""
    import config
    from routes import learn
    from services import ai_budget

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)  # the code default, pinned
    seen = []
    monkeypatch.setattr(ai_budget, "check", lambda *a, **k: seen.append(a) or _hard())

    async def _loop_chat(body, request):
        return {"delegated": True}

    monkeypatch.setattr(learn, "_loop_delegate", lambda name: _loop_chat)
    r = legacy_client.post("/api/learn/chat", json=legacy_chat_body)
    assert r.json() == {"delegated": True}
    assert seen == []
