"""PKG-14b: spec §11 removals and launch changes that inv_21's grep does not cover."""

import inspect
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def test_gate_module_is_env_only():
    import re

    src = (BACKEND / "learning" / "gate.py").read_text()
    assert not re.search(r"^from db|table\(", src, re.M), "spec §7: the post-launch gate reads no table"
    assert "user_settings" not in src and "learning_loop_beta" not in src


def test_config_parse_is_the_exact_spec_7_expression():
    src = (BACKEND / "config.py").read_text()
    assert '_raw = os.getenv("LEARNING_LOOP_ENABLED", "").strip().lower()' in src
    assert 'LEARNING_LOOP_ENABLED = _raw not in {"false", "0", "off", "no"}' in src


def test_quiz_and_flashcards_do_not_consult_the_gate():
    from routes import flashcards, quiz

    for mod in (quiz, flashcards):
        assert "learning_loop_active" not in inspect.getsource(mod), mod.__name__


def test_onboarding_ignores_learning_style():
    from models import OnboardingBody

    body = OnboardingBody(user_id="u", first_name="A", last_name="B", year="1", majors=["x"], course_ids=["c"])
    assert body.learning_style is None
    # A legacy client that still sends it is accepted and the value ignored.
    assert OnboardingBody(
        user_id="u", first_name="A", last_name="B", year="1", majors=["x"], course_ids=["c"],
        learning_style="visual",
    ).learning_style == "visual"
    from routes import onboarding

    assert "learning_style" not in inspect.getsource(onboarding.save_onboarding_profile)


def test_profile_reads_no_learning_style():
    from routes import profile

    assert "learning_style" not in inspect.getsource(profile)


def test_end_session_summary_has_no_dead_lists():
    from routes import learn

    src = inspect.getsource(learn.end_session)
    for key in ("mastery_changes", "new_connections", "recommended_next"):
        assert key not in src, key


def test_frontend_session_summary_renders_no_dead_lists():
    src = (REPO / "frontend/src/components/chat/SessionSummary.tsx").read_text()
    for key in ("mastery_changes", "new_connections", "recommended_next"):
        assert key not in src, key


def test_post_launch_wording_replaces_the_build_phase_comments():
    main = (BACKEND / "main.py").read_text()
    assert "# Learning loop: 404 when LEARNING_LOOP_ENABLED=false (kill switch)." in main
    example = (BACKEND / ".env.local.example").read_text()
    assert "# LEARNING_LOOP_ENABLED — unset = ON (default); false/0/off/no = kill switch (spec §7)" in example
    assert not any(
        line.strip().startswith("LEARNING_LOOP_ENABLED=") for line in example.splitlines()
    ), "no example config sets the variable (spec §7: owner-set)"


@pytest.mark.kill_switch
def test_kill_switch_marker_turns_the_loop_off():
    import config
    from learning.gate import learning_loop_active

    assert config.LEARNING_LOOP_ENABLED is False
    assert learning_loop_active("anyone") is False


def test_kill_switch_path_is_cost_bounded_in_source():
    from routes import learn

    src = inspect.getsource(learn)
    assert "ai_budget.check(" in src and "ai_budget.enforce_rate_limit" in src
    for handler in (learn.start_session, learn.start_session_stream, learn.chat, learn.chat_stream, learn.action):
        body = inspect.getsource(handler)
        assert "_kill_switch_budget(" in body, handler.__name__


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
def test_every_legacy_model_route_reads_the_rate_limit_once_after_require_self(path):
    """A20 on the legacy routes (A93 review): ONE rate-limit read for both the loop
    and the kill-switch path, and only AFTER the caller's identity is checked — never
    a dependency, which FastAPI runs before the handler's require_self."""
    import inspect

    from services import ai_budget

    route = _route(path)
    deps = [d.call for d in route.dependant.dependencies]
    assert ai_budget.enforce_rate_limit not in deps, path
    body = inspect.getsource(route.endpoint)
    assert body.count("ai_budget.enforce_rate_limit_for(body.user_id)") == 1, path
    assert body.index("require_self(body.user_id, request)") < body.index(
        "ai_budget.enforce_rate_limit_for(body.user_id)"
    ), path


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
        m.select.return_value = [{"offering_id": "off1"}] if name == "sessions" else []
        m.update.return_value = []
        m.insert.return_value = []
        return m

    with (
        patch("routes.learn.agent_for_mode", side_effect=_agent_for_mode),
        patch("routes.learn.table", side_effect=_table),
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


@pytest.mark.kill_switch
@pytest.mark.parametrize("path", ["/api/learn/chat", "/api/learn/chat/stream"])
def test_kill_switch_path_returns_429_at_the_hard_cap(monkeypatch, legacy_client, legacy_chat_body, path):
    from services import ai_budget

    calls = []
    monkeypatch.setattr(ai_budget, "check", lambda *a, **k: calls.append((a, k)) or _hard())
    r = legacy_client.post(path, json=legacy_chat_body)
    assert r.status_code == 429 and r.json()["detail"] == "ai budget reached"
    assert legacy_client.agent_runs == []  # checked before any agent run and before the stream opens
    assert calls == [(("user_andres", "tutor", "develop"), {})]


@pytest.mark.kill_switch
@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/learn/start-session", {"user_id": "user_andres", "topic": "Recursion", "mode": "socratic"}),
        ("/api/learn/start-session/stream", {"user_id": "user_andres", "topic": "Recursion", "mode": "socratic"}),
        ("/api/learn/action", {"session_id": "s1", "user_id": "user_andres", "action_type": "hint", "mode": "socratic"}),
    ],
)
def test_every_other_legacy_model_route_returns_429_at_the_hard_cap(monkeypatch, legacy_client, path, body):
    from services import ai_budget

    monkeypatch.setattr(ai_budget, "check", lambda *a, **k: _hard())
    counted = []
    monkeypatch.setattr(ai_budget, "count_tutor_call", lambda uid: counted.append(uid) or 1)
    r = legacy_client.post(path, json=body)
    assert r.status_code == 429, r.text
    assert legacy_client.agent_runs == [] and counted == []


@pytest.mark.kill_switch
def test_kill_switch_path_counts_one_tutor_call_per_model_request(monkeypatch, legacy_client, legacy_chat_body):
    """A39: the daily tutor-call cap works even when llm_usage reads nothing —
    the kill-switch path bumps it once per model request, after the check."""
    from services import ai_budget

    ok = ai_budget.BudgetDecision(level="normal", tier_ceiling="deep")
    order = []
    monkeypatch.setattr(ai_budget, "check", lambda *a, **k: order.append("check") or ok)
    monkeypatch.setattr(ai_budget, "count_tutor_call", lambda uid: order.append(("count", uid)) or 1)
    legacy_client.post("/api/learn/chat", json=legacy_chat_body)
    assert order[:2] == ["check", ("count", "user_andres")]
    assert order.count("check") == 1 and len([o for o in order if o != "check"]) == 1


def test_default_path_delegates_before_the_legacy_budget_check(monkeypatch, legacy_client, legacy_chat_body):
    """Default ON: the legacy handler delegates to the loop, and the loop's own
    budget code runs — the legacy develop-band check is the kill-switch path's."""
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
