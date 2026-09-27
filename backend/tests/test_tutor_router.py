"""The observe-only tutor turn router (services/tutor_router.py, #640).

Pins the three properties that make it safe to ship before anyone trusts it:

1. **Observe-only.** Enabling it changes nothing about a turn — same agent
   call, same retrieval, same reply — even when its answers would argue for a
   different turn (no retrieval, a hard question).
2. **Zero added latency, zero added failure.** It is scheduled, not awaited;
   it never raises into the route; off (the default) does no work at all.
3. **Observable.** Every routed turn emits exactly one ``decision.made`` with
   the router's extras, including on its own timeout backstop.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from agents.decision import decision_agent
from main import app
from services import decisions, events_service, tutor_router
from tests.agent_run_fakes import run_result

client = TestClient(app)

#: Answers that WOULD change the turn if anything acted on them.
DISRUPTIVE = [
    {"key": "needs_retrieval", "value": "no", "confidence": 0.95},
    {"key": "needs_rewrite", "value": "yes", "confidence": 0.9},
    {"key": "complexity", "value": "hard", "confidence": 0.9},
    {"key": "is_graded_work_request", "value": "yes", "confidence": 0.9},
    {"key": "injection_attempt", "value": "yes", "confidence": 0.9},
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (decisions.BACKEND_ENV, decisions.SHADOW_ENV, decisions.FLOOR_ENV,
                decisions.TIMEOUT_ENV, decisions.JEV_TIMEOUT_ENV, "SAPLING_MODEL_MODE"):
        monkeypatch.delenv(var, raising=False)


def _model(answers, *, delay=0.0, calls=None):
    async def handler(messages, info):
        if calls is not None:
            calls.append(messages)
        if delay:
            await asyncio.sleep(delay)
        return ModelResponse(parts=[
            ToolCallPart(tool_name=info.output_tools[0].name, args={"answers": answers})
        ])

    return FunctionModel(handler, model_name="function:decision")


def _observe(**overrides):
    kwargs = dict(user_id="u1", session_id="s1", message="Why does my proof fail?",
                  history=[], mode="socratic", model_pref_requested=None,
                  model_tier="fast", tutor_model="gemini-2.5-flash-lite",
                  request_id="req-9")
    kwargs.update(overrides)
    return tutor_router.observe_tutor_turn(**kwargs)


def _decision_events(sink):
    events_service.flush_now()
    return [r for r in sink if r.get("event_type") == "decision.made"]


# ── Safe defaults + state ─────────────────────────────────────────────────


def test_safe_defaults_are_todays_behaviour():
    result = decisions.defaults_result(tutor_router.QUESTIONS, reason="x")
    assert {k: a.value for k, a in result.answers.items()} == {
        "needs_retrieval": True,        # retrieve, as every turn does today
        "needs_rewrite": False,
        "complexity": None,             # no opinion → the user's model_pref stands
        "is_graded_work_request": False,
        "injection_attempt": False,
    }


def test_question_set_is_the_issue_contract():
    kinds = {q.key: type(q).__name__ for q in tutor_router.QUESTIONS}
    assert kinds == {
        "needs_retrieval": "YesNo", "needs_rewrite": "YesNo", "complexity": "Score",
        "is_graded_work_request": "YesNo", "injection_attempt": "YesNo",
    }
    complexity = next(q for q in tutor_router.QUESTIONS if q.key == "complexity")
    assert [k for k, _ in complexity.levels] == ["easy", "medium", "hard"]


def test_build_state_keeps_a_short_clipped_tail():
    history = []
    for i in range(6):
        history.append(ModelRequest(parts=[UserPromptPart(content=f"q{i} " + "a" * 900)]))
        history.append(ModelResponse(parts=[TextPart(content=f"r{i}")]))
    history.append(ModelResponse(parts=[]))  # textless: skipped
    state = tutor_router.build_state("latest " + "b" * 9000, history)
    assert state["student_latest_message"].startswith("latest ")
    assert len(state["student_latest_message"]) == tutor_router.MESSAGE_CLIP_CHARS
    tail = state["recent_conversation"]
    # Last 4 messages minus the textless one, oldest first.
    assert [t["speaker"] for t in tail] == ["tutor", "student", "tutor"]
    assert tail[1]["text"].startswith("q5 ")
    assert len(tail[1]["text"]) == tutor_router.HISTORY_CLIP_CHARS


# ── Scheduling ────────────────────────────────────────────────────────────


def test_off_schedules_nothing():
    async def run():
        return _observe()

    assert asyncio.run(run()) is None


def test_scheduling_never_raises_even_without_a_loop(monkeypatch):
    monkeypatch.setenv(decisions.BACKEND_ENV, "flash_lite")
    # No running loop here: create_task can't be reached; must not raise.
    assert _observe() is None


def test_routed_turn_is_fire_and_forget_and_emits_one_event(monkeypatch, sink):
    monkeypatch.setenv(decisions.BACKEND_ENV, "flash_lite")
    answers = [dict(a, value=v) for a, v in zip(
        DISRUPTIVE, ["yes", "no", "medium", "no", "no"])]

    async def run():
        task = _observe()
        assert task is not None
        assert not task.done(), "observe_tutor_turn must return before the decision runs"
        return await task

    with decision_agent.override(model=_model(answers, delay=0.05)):
        result = asyncio.run(run())

    assert result.backend == "flash_lite"
    assert result.value("complexity") == "medium"
    (event,) = _decision_events(sink)
    p = event["payload"]
    assert p["feature"] == "tutor_router"
    assert (p["session_id"], p["mode"]) == ("s1", "socratic")
    assert (p["model_pref_requested"], p["model_tier"], p["tutor_model"]) == (
        None, "fast", "gemini-2.5-flash-lite")
    assert p["history_messages"] == 0
    assert set(p["answers"]) == {q.key for q in tutor_router.QUESTIONS}
    assert event["user_id"] == "u1" and event["request_id"] == "req-9"
    assert "proof" not in json.dumps(event), "the student's text never enters the event"


def test_backstop_timeout_emits_defaults(monkeypatch, sink):
    monkeypatch.setenv(decisions.BACKEND_ENV, "flash_lite")
    monkeypatch.setattr(decisions, "worst_case_s", lambda: -0.95)  # backstop = 50ms

    async def hang(*a, **k):
        await asyncio.sleep(5)

    monkeypatch.setattr(decisions, "decide", hang)

    async def run():
        return await _observe()

    result = asyncio.run(run())
    assert result.fallback_reason == "router_timeout"
    assert result.value("needs_retrieval") is True
    (event,) = _decision_events(sink)
    assert event["payload"]["fallback_reason"] == "router_timeout"
    assert event["payload"]["session_id"] == "s1"


def test_function_mode_routes_with_the_e2e_handler(monkeypatch, sink):
    """The E2E lane's shape: function mode, no backend env, the env-named
    handlers module — the router runs and every key is answered above floor."""
    import sys

    import agents._providers as providers
    from agents._providers import clear_function_handlers, model_for

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    monkeypatch.setattr(providers, "_ENV_HANDLERS_LOADED", False)
    clear_function_handlers()
    sys.modules.pop("agents.function_handlers_e2e", None)
    try:
        async def run():
            return await _observe()

        with decision_agent.override(model=model_for("decision")):
            result = asyncio.run(run())
    finally:
        clear_function_handlers()
        sys.modules.pop("agents.function_handlers_e2e", None)

    assert result.backend == "function"
    assert not any(a.defaulted for a in result.answers.values())
    (event,) = _decision_events(sink)
    assert event["payload"]["backend"] == "function"


# ── Route wiring: observe-only, once per PERSISTED turn ──────────────────


def _table_factory(name):
    mock = MagicMock()
    mock.select.return_value = [{"offering_id": "off1"}] if name == "sessions" else []
    mock.insert.return_value = []
    mock.update.return_value = []
    return mock


def _post_chat(**overrides):
    body = {
        "session_id": "s1", "user_id": "user_andres", "message": "What is recursion?",
        "mode": "socratic", "model_pref": "fast",
    }
    body.update(overrides)
    return client.post("/api/learn/chat", json=body)


def _post_stream(**overrides):
    body = {
        "session_id": "s1", "user_id": "user_andres", "message": "What is recursion?",
        "mode": "socratic", "model_pref": "smart",
    }
    body.update(overrides)
    return client.post("/api/learn/chat/stream", json=body)


class _RouterSpy:
    """Stands in for `observe_tutor_turn` inside the route: records each
    scheduling call without starting a task (a task started on the
    per-request TestClient loop is cancelled when the request's loop closes,
    before it could emit). :meth:`replay` then runs every recorded call
    through the REAL router, so tests count genuine ``decision.made`` events."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return None

    def replay(self, answers=DISRUPTIVE):
        async def run():
            return [await tutor_router.observe_tutor_turn(**kw) for kw in self.calls]

        with decision_agent.override(model=_model(answers)):
            return asyncio.run(run())


@pytest.fixture
def router_on(monkeypatch):
    monkeypatch.setenv(decisions.BACKEND_ENV, "flash_lite")


def test_json_chat_routes_the_turn_once_after_persisting(router_on):
    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("reply"))
    order: list[str] = []
    spy = _RouterSpy()

    def save(session_id, role, *a, **k):
        order.append(f"save:{role}")

    def observe(**kw):
        order.append("route")
        return spy(**kw)

    with (
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("routes.learn.save_message", side_effect=save),
        patch("routes.learn.observe_tutor_turn", side_effect=observe),
    ):
        r = _post_chat()
    assert r.status_code == 200
    assert order == ["save:user", "save:assistant", "route"], (
        "the router is scheduled at the persist point, after the turn is saved")
    (kw,) = spy.calls
    assert (kw["message"], kw["session_id"], kw["mode"]) == (
        "What is recursion?", "s1", "socratic")
    assert kw["history"] == []


def test_stream_failing_before_persist_then_json_retry_is_one_decision(router_on, sink):
    """The double-routing regression: the client's own JSON rung (Learn.tsx
    `shouldFallBackToJson` → POST /chat) retries a stream that failed before
    its first token. The stream persisted nothing, so it must not have routed
    anything; the /chat retry that DOES persist routes the turn — once."""
    failing = MagicMock()
    # Nothing streams → Rung 1 → the JSON fallback, whose own agent run fails
    # too → a terminal error with nothing persisted.
    failing.run = AsyncMock(side_effect=RuntimeError("model down"))
    ok = MagicMock()
    ok.run = AsyncMock(return_value=run_result("retry reply"))
    spy = _RouterSpy()
    saved: list = []

    with (
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn._consume_pending"),
        patch("routes.learn.save_message", side_effect=lambda *a, **k: saved.append(a)),
        patch("routes.learn.observe_tutor_turn", side_effect=spy),
    ):
        with patch("routes.learn.agent_for_mode", return_value=failing):
            r1 = _post_stream()
        assert r1.status_code == 200 and '"error"' in r1.text
        assert saved == [], "the failed stream persisted nothing"
        assert spy.calls == [], "…so it routed nothing"
        with patch("routes.learn.agent_for_mode", return_value=ok):
            r2 = _post_chat(model_pref="smart")
        assert r2.status_code == 200

    assert len(spy.calls) == 1
    spy.replay()
    assert len(_decision_events(sink)) == 1, "one persisted turn, one decision"


def test_successful_stream_is_one_decision_with_the_served_model(router_on, sink):
    from services.agent_events import SaplingEvent

    async def fake_stream(**kwargs):
        extra = kwargs["on_complete"]("streamed reply", {}, [])
        yield SaplingEvent(type="done", step="reply", message="Complete.", data=extra)

    spy = _RouterSpy()
    with (
        patch("routes.learn.stream_agent_turn", fake_stream),
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=MagicMock()),
        patch("routes.learn._consume_pending"),
        patch("routes.learn.observe_tutor_turn", side_effect=spy),
    ):
        r = _post_stream()
    assert r.status_code == 200
    (kw,) = spy.calls
    assert (kw["model_pref_requested"], kw["model_tier"], kw["tutor_model"]) == (
        "smart", "smart", "gemini-2.5-pro")
    spy.replay()
    (event,) = _decision_events(sink)
    assert event["payload"]["model_tier"] == "smart"
    # #672 review: the router's decision runs as a detached task, outside the
    # request contextvar; its llm_usage row must still join to the turn.
    usage = [r for r in sink if "prompt_tokens" in r and r.get("task") == "decision"]
    assert len(usage) == 1
    assert usage[0]["request_id"] == kw["request_id"] == event["request_id"]
    assert usage[0]["request_id"] is not None


def test_stream_rung1_fallback_is_one_decision_on_the_fast_tier(router_on):
    """The stream's server-side Rung-1 fallback runs the JSON pipeline, which
    persists the turn — one decision, labelled with the tier that actually
    served it (fast, D2), not the smart tier the request asked for."""
    from services.agent_events import SaplingEvent

    async def fake_stream(**kwargs):
        result = await kwargs["nonstream_fallback"]()
        yield SaplingEvent(type="done", step="reply", message="Complete.", data=result)

    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("fallback reply"))
    spy = _RouterSpy()
    with (
        patch("routes.learn.stream_agent_turn", fake_stream),
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("routes.learn._consume_pending"),
        patch("routes.learn.observe_tutor_turn", side_effect=spy),
    ):
        r = _post_stream()
    assert r.status_code == 200
    assert "fallback reply" in r.text
    (kw,) = spy.calls
    assert (kw["model_pref_requested"], kw["model_tier"], kw["tutor_model"]) == (
        "smart", "fast", "gemini-2.5-flash-lite")


def test_json_chat_without_a_pref_logs_the_default_model(router_on):
    from agents._providers import model_name_for

    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("reply"))
    spy = _RouterSpy()
    with (
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("routes.learn.observe_tutor_turn", side_effect=spy),
    ):
        r = _post_chat(model_pref=None)
    assert r.status_code == 200
    (kw,) = spy.calls
    assert (kw["model_pref_requested"], kw["model_tier"], kw["tutor_model"]) == (
        None, "default", model_name_for("chat_tutor"))


def test_failed_json_turn_routes_nothing(router_on):
    agent = MagicMock()
    agent.run = AsyncMock(side_effect=RuntimeError("model down"))
    spy = _RouterSpy()
    with (
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("routes.learn.observe_tutor_turn", side_effect=spy),
    ):
        r = _post_chat()
    assert r.status_code >= 500
    assert spy.calls == []


def test_off_schedules_nothing_at_the_persist_point():
    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("reply"))
    scheduled: list = []
    real_observe = tutor_router.observe_tutor_turn

    def spy(**kw):
        scheduled.append(real_observe(**kw))
        return scheduled[-1]

    with (
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("routes.learn.observe_tutor_turn", side_effect=spy),
    ):
        r = _post_chat()
    assert r.status_code == 200
    assert scheduled == [None], "off: the router is asked, and schedules nothing"


def test_the_seam_switch_is_read_once_per_turn(router_on, monkeypatch):
    """#672 review: learn.py re-checked decisions.enabled() before calling
    observe_tutor_turn, which checks it itself. One owner: the router."""
    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("reply"))
    reads: list = []

    def enabled():
        reads.append(1)
        return True

    async def no_route(*a, **k):
        return None

    monkeypatch.setattr(decisions, "enabled", enabled)
    monkeypatch.setattr(tutor_router, "_route", no_route)
    with (
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
    ):
        r = _post_chat()
    assert r.status_code == 200
    assert len(reads) == 1


def test_function_mode_labels_the_tier_the_turn_really_ran_on(router_on, monkeypatch):
    """#672 review: outside real mode `_resolve_model_pref` ignores the pref
    (#391), so a `fast` request runs the seam's default model — the event
    must say `default`, agreeing with `tutor_model`, not echo `fast`."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("reply"))
    spy = _RouterSpy()
    with (
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("routes.learn.observe_tutor_turn", side_effect=spy),
    ):
        r = _post_chat(model_pref="fast")
    assert r.status_code == 200
    (kw,) = spy.calls
    assert (kw["model_pref_requested"], kw["model_tier"], kw["tutor_model"]) == (
        "fast", "default", "function:chat_tutor")


def test_model_labels_come_from_config_without_building_a_model(monkeypatch):
    """#672 review: no private `_model_mode` import and no Model construction
    per turn — the labels are configuration reads."""
    import agents._providers as providers
    from routes import learn

    def boom(*a, **k):
        raise AssertionError("model_for must not be called to label an event")

    monkeypatch.setattr(providers, "model_for", boom)
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    assert learn._served_model_name("fast") == "function:chat_tutor"
    monkeypatch.delenv("SAPLING_MODEL_MODE")
    assert learn._served_model_name("smart") == "gemini-2.5-pro"
    assert learn._served_model_name(None) == providers.model_name_for("chat_tutor")
    assert learn._served_tier("turbo") == "default"


def test_router_failure_cannot_fail_the_turn():
    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("reply"))
    with (
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("services.tutor_router.decisions.enabled", side_effect=RuntimeError("boom")),
    ):
        r = _post_chat()
    assert r.status_code == 200 and r.json()["reply"] == "reply"


def test_router_failure_cannot_fail_a_persisted_stream(router_on):
    """On the streamed path the router runs INSIDE on_complete, after the rows
    are saved: an exception there would turn a persisted turn into an error
    event. It must be absorbed."""
    from services.agent_events import SaplingEvent

    async def fake_stream(**kwargs):
        extra = kwargs["on_complete"]("streamed reply", {}, [])
        yield SaplingEvent(type="done", step="reply", message="Complete.", data=extra)

    with (
        patch("routes.learn.stream_agent_turn", fake_stream),
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=MagicMock()),
        patch("routes.learn._consume_pending"),
        patch("routes.learn.observe_tutor_turn", side_effect=RuntimeError("boom")),
    ):
        r = _post_stream()
    assert r.status_code == 200
    assert '"done"' in r.text and '"error"' not in r.text


def test_enabled_router_leaves_the_turn_byte_identical(monkeypatch, sink):
    """Observe-only, end to end: with the router ON and answering that the
    turn needs no retrieval and is hard, the tutor still retrieves, still runs
    the same agent call with the same kwargs, and returns the same reply as
    with the router OFF."""

    def run_turn(backend: str | None):
        if backend is None:
            monkeypatch.delenv(decisions.BACKEND_ENV, raising=False)
        else:
            monkeypatch.setenv(decisions.BACKEND_ENV, backend)
        agent = MagicMock()
        retrieve = MagicMock(return_value=[])
        agent.run = AsyncMock(return_value=run_result("same reply"))
        spy = _RouterSpy()

        with (
            patch("routes.learn.table", side_effect=_table_factory),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.offering_course_id", return_value="c1"),
            patch("routes.learn._get_course_info", return_value={"course_code": "CS101"}),
            patch("routes.learn._get_catalog_chunk", return_value=""),
            patch("services.rag_service.retrieve_chunks", retrieve),
            patch("services.graph_context.build_graph_context_block", return_value=""),
            patch("routes.learn.observe_tutor_turn", side_effect=spy),
        ):
            r = _post_chat()
        return r, agent.run.call_args, retrieve.call_args_list, spy

    r_off, call_off, retr_off, spy_off = run_turn(None)
    r_on, call_on, retr_on, spy_on = run_turn("flash_lite")

    # The route always hands the persisted turn to the router, which owns the
    # on/off check (test_off_schedules_nothing_at_the_persist_point).
    assert len(spy_off.calls) == len(spy_on.calls) == 1
    assert r_on.status_code == r_off.status_code == 200
    assert r_on.json() == r_off.json()
    assert retr_on == retr_off and len(retr_on) == 1, "retrieval still runs"
    assert call_on.args == call_off.args
    assert call_on.kwargs.keys() == call_off.kwargs.keys()
    # The fast pref's model override is rebuilt per turn, so compare by name:
    # the router's "hard" must not have escalated the tier.
    assert call_on.kwargs["model"].model_name == call_off.kwargs["model"].model_name
    assert call_on.kwargs["model"].model_name == "gemini-2.5-flash-lite"
    assert call_on.kwargs["message_history"] == call_off.kwargs["message_history"]
    # And the router really does decide those disruptive answers for this
    # turn (so "nothing changed" is not just "nothing ran").
    spy_on.replay(DISRUPTIVE)
    (event,) = _decision_events(sink)
    assert event["payload"]["answers"]["needs_retrieval"]["value"] is False
    assert event["payload"]["answers"]["complexity"]["value"] == "hard"
