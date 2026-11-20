"""PKG-14b: spec §11 removals and launch changes that inv_21's grep does not cover."""

import inspect
import pathlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from tests.split_patches import patch_tutor
from tests.db_fakes import with_async_twins

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
    assert (
        "# Learning loop: 404 unless the loop is on for the student (the "
        "LEARNING_LOOP_ENABLED kill switch, then their learning_loop flag)." in main
    )
    example = (BACKEND / ".env.local.example").read_text()
    assert (
        "# LEARNING_LOOP_ENABLED — the kill switch: false/0/off/no = loop off for everyone; "
        "unset = the per-student learning_loop flag decides (spec §7)" in example
    )
    assert not any(
        line.strip().startswith("LEARNING_LOOP_ENABLED=") for line in example.splitlines()
    ), "no example config sets the variable (spec §7: owner-set)"


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


#: The five legacy tutor handler bodies (#118: the same-named functions in
#: services/tutor/; routes/learn.py wraps them).
LEGACY_TUTOR_BODIES = ("start_session", "start_session_stream", "chat", "chat_stream", "action")


def _loop_branch(body: str) -> tuple[int, int]:
    """(start, end) of a handler body's `if loop_handler is not None:` block,
    ending at the hand-off's `return await loop_handler(...)`."""
    start = body.index("if loop_handler is not None:")
    return start, body.index("return await loop_handler(body, request)", start)


def test_only_the_loop_path_reads_the_ai_budget_in_source():
    """Owner decision 2026-11-18 ("caps only when the loop is on"; was A20's
    kill-switch cost bound, PKG-14b). The legacy tutor a loop-off student gets
    reads no AI budget: every `ai_budget` read in a handler body sits inside
    its loop branch, and none of them calls the retired `_kill_switch_budget`."""
    import routes.learn as learn_route
    import services.tutor as tutor
    import services.tutor.run as tutor_run

    for module in (tutor_run, learn_route):  # deleted, not just uncalled (#866 B2)
        assert not hasattr(module, "_kill_switch_budget"), module.__name__
        assert not hasattr(module, "KILL_SWITCH_BUDGET_BAND"), module.__name__
    assert not hasattr(tutor_run, "ai_budget")
    for name in LEGACY_TUTOR_BODIES:
        body = inspect.getsource(getattr(tutor, name))
        start, end = _loop_branch(body)
        assert "_kill_switch_budget" not in body, name
        reads = [i for i in range(len(body)) if body.startswith("ai_budget.", i)]
        reads += [i for i in range(len(body)) if body.startswith("_loop_turn_entry(", i)]
        assert reads, name
        assert all(start < i < end for i in reads), name


def test_the_loop_turn_entry_replays_and_refuses_before_the_rate_limit():
    """#761 order on the loop path (B3): ownership, the replay of a persisted
    turn, the ended-session 409, and only then the rate-limit read."""
    from services.tutor import turns

    body = inspect.getsource(turns._loop_turn_entry)
    order = [
        body.index("await _require_turn_session(session_id, user_id)"),
        body.index("await _persisted_turn(session_id, turn_id)"),
        body.index("await _refuse_ended_session(session_id)"),
        body.index("asyncio.to_thread(ai_budget.enforce_rate_limit_for, user_id)"),
    ]
    assert order == sorted(order)


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
def test_every_delegating_route_reads_the_rate_limit_once_after_require_self(path):
    """A20 on the delegating routes (A93 review): ONE rate-limit read on the loop
    path (none on the legacy one, owner decision 2026-11-18), and only AFTER the
    caller's identity is checked — never a dependency, which FastAPI runs before
    the handler's require_self."""
    import inspect

    from services import ai_budget

    import services.tutor as tutor
    from services.tutor import turns

    route = _route(path)
    deps = [d.call for d in route.dependant.dependencies]
    assert ai_budget.enforce_rate_limit not in deps, path
    # #118 (spec §13 A149): the route is a thin wrapper; its body is the
    # same-named function in services/tutor/, where the read hops off the loop
    body = inspect.getsource(getattr(tutor, route.endpoint.__name__))
    read = "asyncio.to_thread(ai_budget.enforce_rate_limit_for, body.user_id)"
    if "_loop_turn_entry(" in body:  # the turn routes: the read is the entry's last step
        assert read not in body, path
        read = "_loop_turn_entry("
        entry = inspect.getsource(turns._loop_turn_entry)
        assert entry.count("asyncio.to_thread(ai_budget.enforce_rate_limit_for, user_id)") == 1
    assert body.count(read) == 1, path
    # #756: the guard runs off the event loop (`guard_off_loop(require_self, ...)`)
    assert body.index("guard_off_loop(require_self, body.user_id, request)") < body.index(read), path


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
