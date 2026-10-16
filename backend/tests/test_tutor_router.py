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
from services import decisions, events_service, feature_flags, tutor_router
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
    for var in (decisions.FLOOR_ENV,
                decisions.TIMEOUT_ENV, decisions.JEV_TIMEOUT_ENV, "SAPLING_MODEL_MODE",
                "SAPLING_FLAG_DECISION_ROUTER"):
        monkeypatch.delenv(var, raising=False)
    # Hermetic flag store: no stored config, so `decision_router` resolves to
    # its "off" default instead of reading whatever DB .env points at.
    monkeypatch.setattr(feature_flags, "read_config",
                        lambda **k: feature_flags.Snapshot(flags={}, targets={}))


def _flash_lite(monkeypatch):
    """Route with the flash_lite backend (the decision agent, overridable
    with a FunctionModel) — what the flag would pick is tested separately."""
    monkeypatch.setattr(decisions, "router_backends",
                        lambda user_id: (decisions.FLASH_LITE, decisions.OFF))


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


def test_off_decides_nothing_and_emits_nothing(sink):
    """The flag's off default: the task reads the flag and ends — no
    decision, no event."""
    async def run():
        task = _observe()
        assert task is not None
        return await task

    assert asyncio.run(run()) is None
    assert _decision_events(sink) == []


def test_scheduling_never_raises_even_without_a_loop(monkeypatch):
    _flash_lite(monkeypatch)
    # No running loop here: create_task can't be reached; must not raise.
    assert _observe() is None


def test_the_flag_is_read_off_the_event_loop(monkeypatch):
    """#672 review: router_backends reads the flag store (a blocking httpx
    PostgREST call on a cache miss — every call on the E2E stack, TTL 0).
    It must run in a worker thread, never on the loop's thread."""
    import threading

    seen: dict = {}

    def router_backends(user_id):
        seen["thread"] = threading.get_ident()
        return decisions.OFF, decisions.OFF

    monkeypatch.setattr(decisions, "router_backends", router_backends)

    async def run():
        seen["loop"] = threading.get_ident()
        return await _observe()

    assert asyncio.run(run()) is None
    assert seen["thread"] != seen["loop"]


def test_observe_does_no_flag_io_before_returning(monkeypatch):
    """On a cold cache observe_tutor_turn only schedules: the flag read
    happens later, inside the task."""
    calls: list = []
    monkeypatch.setattr(decisions, "router_backends",
                        lambda user_id: calls.append(user_id) or (decisions.OFF, decisions.OFF))

    async def run():
        task = _observe()
        assert calls == [], "no flag read before the task runs"
        assert await task is None, "the flag read off: nothing decided"
        return calls

    assert asyncio.run(run()) == ["u1"]


def test_an_unreadable_flag_store_records_the_gap(monkeypatch, sink):
    """#672 review: a store outage is not "off" — the turn gets one
    decision.made with all defaults and fallback_reason=flag_unreadable."""

    def down(**k):
        raise RuntimeError("db down")

    monkeypatch.setattr(feature_flags, "read_config", down)

    async def run():
        return await _observe()

    result = asyncio.run(run())
    assert (result.fallback_reason, result.requested, result.backend) == (
        "flag_unreadable", "none", "none")
    (event,) = _decision_events(sink)
    assert event["payload"]["fallback_reason"] == "flag_unreadable"
    assert event["payload"]["session_id"] == "s1"


def test_a_warm_off_flag_schedules_nothing(monkeypatch):
    """With the flag cache warm and the flag off, observe_tutor_turn answers
    inline: no state, no task, no thread hop."""

    async def run():
        feature_flags.explain("decision_router", "u1")  # warms the snapshot
        with patch("services.tutor_router.build_state") as build, \
             patch("asyncio.to_thread") as hop:
            assert _observe() is None
        return build.called, hop.called

    assert asyncio.run(run()) == (False, False)


def test_routed_turn_is_fire_and_forget_and_emits_one_event(monkeypatch, sink):
    _flash_lite(monkeypatch)
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
    _flash_lite(monkeypatch)
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


def test_router_error_still_emits_one_decision(monkeypatch, sink, caplog):
    """#672 review: an unexpected failure in the router task left NO event, so
    one-decision-per-persisted-turn silently broke on the error path."""
    _flash_lite(monkeypatch)

    async def broken(*a, **k):
        raise RuntimeError("bug in the seam")

    monkeypatch.setattr(decisions, "decide", broken)

    async def run():
        return await _observe()

    with caplog.at_level("DEBUG", logger="sapling.tutor_router"):
        result = asyncio.run(run())
    assert result.fallback_reason == "router_error"
    (event,) = _decision_events(sink)
    p = event["payload"]
    assert p["fallback_reason"] == "router_error" and p["backend"] == "none"
    assert p["session_id"] == "s1" and event["request_id"] == "req-9"
    loud = [r for r in caplog.records if r.levelno >= 30]
    assert loud and all(r.exc_info is None for r in loud), "WARN, no traceback"


@pytest.mark.parametrize("failure,reason", [("hang", "router_timeout"),
                                            ("raise", "router_error")])
def test_flag_driven_failure_logs_the_backend_it_requested(monkeypatch, sink, failure, reason):
    """A defaults row from the router's own backstop/error path logs the
    backend the turn requested (jev, from the flag), not "off"."""
    monkeypatch.setattr(decisions, "worst_case_s", lambda: -0.95)  # backstop = 50ms

    async def broken(*a, **k):
        if failure == "hang":
            await asyncio.sleep(5)
        raise RuntimeError("bug in the seam")

    monkeypatch.setattr(decisions, "decide", broken)

    async def run():
        return await _observe()

    with patch("services.feature_flags.explain",
               return_value=feature_flags.Resolution("jev", "default", "")):
        result = asyncio.run(run())
    assert (result.fallback_reason, result.requested) == (reason, "jev")
    (event,) = _decision_events(sink)
    assert event["payload"]["requested"] == "jev"


def test_shutdown_drains_an_inflight_decision(monkeypatch, sink):
    """#672 review: the lifespan closes the Jev client and stops the events
    worker after the router tasks; draining first keeps a turn persisted just
    before shutdown from losing its decision.made row."""
    _flash_lite(monkeypatch)

    async def run():
        with decision_agent.override(model=_model(DISRUPTIVE, delay=0.05)):
            task = _observe()
            assert task is not None and not task.done()
            await tutor_router.drain_inflight()
            return task

    task = asyncio.run(run())
    assert task.done()
    assert len(_decision_events(sink)) == 1


def test_function_mode_routes_with_the_e2e_handler(monkeypatch, sink):
    """The E2E lane's shape: function mode, the flag switched on through its
    env override (scripts/e2e-up.sh), the env-named handlers module — the
    router runs the scripted backend and every key is answered above floor."""
    import sys

    import agents._providers as providers

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FLAG_DECISION_ROUTER", "jev")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    monkeypatch.setattr(providers, "_ENV_HANDLERS_LOADED", False)
    providers.clear_function_handlers()
    sys.modules.pop("agents.function_handlers_e2e", None)
    try:
        async def run():
            return await _observe()

        with decision_agent.override(model=providers.model_for("decision")):
            result = asyncio.run(run())
    finally:
        providers.clear_function_handlers()
        sys.modules.pop("agents.function_handlers_e2e", None)

    assert result.backend == "function"
    assert not any(a.defaulted for a in result.answers.values())
    (event,) = _decision_events(sink)
    assert event["payload"]["backend"] == "function"


# ── Route wiring: observe-only, once per PERSISTED turn ──────────────────


def _table_factory(name):
    mock = MagicMock()
    # The sessions row answers both reads: the turn's offering, and the
    # ownership check (services.tutor_sessions) that it is the caller's.
    mock.select.return_value = (
        [{"offering_id": "off1", "user_id": "user_andres"}] if name == "sessions" else []
    )
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
    _flash_lite(monkeypatch)


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


def test_streamed_turn_usage_row_carries_the_request_id(router_on):
    """#672 review: the stream's on_usage hook recorded chat_tutor usage
    without request_id; it runs inside the SSE generator, so the row could
    not be joined to the turn — or to the turn's decision.made."""
    from services.agent_events import SaplingEvent

    async def fake_stream(**kwargs):
        kwargs["on_usage"](_served_by("streamed", "gemini-2.5-pro"))
        extra = kwargs["on_complete"]("streamed", {}, [])
        yield SaplingEvent(type="done", step="reply", message="Complete.", data=extra)

    usage_calls: list = []
    spy = _RouterSpy()
    with (
        patch("routes.learn.stream_agent_turn", fake_stream),
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=MagicMock()),
        patch("routes.learn._consume_pending"),
        patch("routes.learn.observe_tutor_turn", side_effect=spy),
        patch("routes.learn.record_agent_usage",
              side_effect=lambda rr, **kw: usage_calls.append(kw) or rr),
    ):
        r = _post_stream()
    assert r.status_code == 200
    (kw,) = spy.calls
    (usage,) = [c for c in usage_calls if c.get("feature") == "chat_tutor"]
    assert usage["request_id"] is not None
    assert usage["request_id"] == kw["request_id"] == r.headers["X-Request-ID"]


@pytest.mark.parametrize("path", ["/api/learn/chat/stream", "/api/learn/start-session/stream"])
def test_streamed_continuation_usage_row_carries_the_request_id(router_on, path):
    """#672 review: the textless-turn continuation runs inside the SSE
    generator (the contextvar is gone), so its llm_usage row needs the turn's
    request_id passed explicitly — on both streamed routes."""
    from services.agent_events import SaplingEvent

    async def fake_stream(**kwargs):
        await kwargs["continuation"](_served_by("", "gemini-2.5-pro"))
        yield SaplingEvent(type="error", step="reply", message="stop.", data={})

    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("finished"))
    usage_calls: list = []
    body = ({"session_id": "s1", "user_id": "user_andres", "message": "Hi", "mode": "socratic"}
            if path.endswith("chat/stream") else
            {"user_id": "user_andres", "topic": "Recursion", "mode": "socratic"})
    with (
        patch("routes.learn.stream_agent_turn", fake_stream),
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("routes.learn._consume_pending"),
        patch("routes.learn.record_agent_usage",
              side_effect=lambda rr, **kw: usage_calls.append(kw) or rr),
    ):
        r = client.post(path, json=body)
    assert r.status_code == 200
    (usage,) = [c for c in usage_calls if c.get("feature") == "chat_tutor_continuation"]
    assert usage["request_id"] is not None
    assert usage["request_id"] == r.headers["X-Request-ID"]


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
    agent = MagicMock()
    agent.run = AsyncMock(return_value=_served_by("reply", "gemini-2.5-pro"))
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
        None, "default", "gemini-2.5-pro")


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


def test_off_decides_nothing_at_the_persist_point(sink):
    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("reply"))
    spy = _RouterSpy()
    with (
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("routes.learn.observe_tutor_turn", side_effect=spy),
    ):
        r = _post_chat()
    assert r.status_code == 200
    assert len(spy.calls) == 1, "the route always hands the persisted turn over"
    assert spy.replay() == [None], "off: the router decides nothing"
    assert _decision_events(sink) == []


def test_the_seam_switch_is_read_once_per_turn(router_on, monkeypatch):
    """#672 review: learn.py re-checked decisions.enabled() before calling
    observe_tutor_turn, which checks it itself. One owner: the router.

    The router's on/off check is `decisions.router_backends()` (which also
    resolves the decision_router flag's backends); the "one owner" property
    is what this test pins."""
    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("reply"))
    reads: list = []

    def router_backends(user_id):
        reads.append(1)
        return (decisions.JEV, decisions.OFF)

    async def no_route(*a, **k):
        return None

    monkeypatch.setattr(decisions, "router_backends", router_backends)
    monkeypatch.setattr(tutor_router, "_route", no_route)
    spy = _RouterSpy()
    with (
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("routes.learn.observe_tutor_turn", side_effect=spy),
    ):
        r = _post_chat()
    assert r.status_code == 200
    spy.replay()
    assert len(reads) == 1


def test_function_mode_labels_the_tier_the_turn_really_ran_on(router_on, monkeypatch):
    """#672 review: outside real mode `_resolve_model_pref` ignores the pref
    (#391), so a `fast` request runs the seam's default model — the event
    must say `default`, agreeing with `tutor_model`, not echo `fast`."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    agent = MagicMock()
    agent.run = AsyncMock(return_value=_served_by("reply", "function:chat_tutor"))
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


def _served_by(output: str, model_name: str):
    """A run result whose response names the model that served it."""
    from tests.agent_run_fakes import FakeRunResult

    return FakeRunResult(output, [ModelResponse(parts=[TextPart(content=output)],
                                                model_name=model_name)])


def test_json_turn_labels_the_model_the_run_reports(router_on, monkeypatch):
    """#672 review: tutor_model came from re-deriving config; it must be what
    actually ran — the run result's model (what llm_usage records), with the
    tier from the override `_prepare_chat_run` really applied."""
    import agents._providers as providers

    def boom(*a, **k):
        raise AssertionError("labelling must not build a model")

    agent = MagicMock()
    agent.run = AsyncMock(return_value=_served_by("reply", "gemini-2.5-flash-lite-preview-09"))
    spy = _RouterSpy()
    with (
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("routes.learn.observe_tutor_turn", side_effect=spy),
    ):
        r = _post_chat(model_pref="fast")
        monkeypatch.setattr(providers, "model_for", boom)
    assert r.status_code == 200
    assert "_ran_on" not in r.json(), "the internal label never reaches the wire"
    (kw,) = spy.calls
    assert (kw["model_pref_requested"], kw["model_tier"], kw["tutor_model"]) == (
        "fast", "fast", "gemini-2.5-flash-lite-preview-09")


def test_chat_via_agent_returns_the_label_out_of_band(monkeypatch):
    """#672 review: the label rode inside the wire dict under a private key
    (popped later); it is now returned beside it, so it cannot leak."""
    from routes import learn

    agent = MagicMock()
    agent.run = AsyncMock(return_value=_served_by("reply", "gemini-2.5-pro"))
    with patch("routes.learn.agent_for_mode", return_value=agent):
        response, ran_on = asyncio.run(learn._chat_via_agent(
            user_id="u1", session_id="s1", course_id="", mode="socratic",
            user_message="m", message_history=[], use_shared_context=True,
            request_id="r1", model_pref=None,
        ))
    assert set(response) == {"reply", "graph_update", "mastery_changes"}
    assert ran_on == ("default", "gemini-2.5-pro")


def test_stream_labels_the_model_its_run_reports(router_on):
    from services.agent_events import SaplingEvent

    async def fake_stream(**kwargs):
        kwargs["on_usage"](_served_by("streamed", "gemini-2.5-pro-exp"))
        extra = kwargs["on_complete"]("streamed", {}, [])
        yield SaplingEvent(type="done", step="reply", message="Complete.", data=extra)

    spy = _RouterSpy()
    with (
        patch("routes.learn.stream_agent_turn", fake_stream),
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=MagicMock()),
        patch("routes.learn._consume_pending"),
        patch("routes.learn.observe_tutor_turn", side_effect=spy),
    ):
        r = _post_stream(model_pref="smart")
    assert r.status_code == 200
    (kw,) = spy.calls
    assert (kw["model_tier"], kw["tutor_model"]) == ("smart", "gemini-2.5-pro-exp")


def test_router_failure_cannot_fail_the_turn():
    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("reply"))
    with (
        patch("routes.learn.table", side_effect=_table_factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("services.tutor_router.decisions.router_backends", side_effect=RuntimeError("boom")),
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
        monkeypatch.setattr(decisions, "router_backends",
                            lambda user_id: (backend or decisions.OFF, decisions.OFF))
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
