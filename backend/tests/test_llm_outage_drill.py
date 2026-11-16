"""#119: the forced-outage drill (the `llm_outage_drill` flag,
`agents/_resilience.py`) — the plan's phase-5 "done when": a forced provider
outage falls back with no user-facing errors.

Proves, hermetically: with the drill on for a provider, every attempt against
it fails with a retryable 503 BEFORE any SDK call (retries, then the breaker
opens and fails fast); with `llm_fallback` on the run is served by the other
provider's model; with it off the routes answer their mapped errors. The
production interlock is pinned on the pure resolver and on a live run.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from agents import _providers, _resilience
from agents._providers import _ResilientModelMixin
from agents._resilience import CircuitOpenError, ForcedOutageError, resolve_forced_outage

DRILL_ENV = "SAPLING_FLAG_LLM_OUTAGE_DRILL"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    _resilience.reset_for_tests()
    sleeps: list[float] = []

    async def _no_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(_resilience, "_sleep", _no_sleep)
    monkeypatch.setattr(_resilience, "_rng", SimpleNamespace(uniform=lambda lo, hi: hi))
    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "off")
    monkeypatch.setenv(DRILL_ENV, "anthropic")
    monkeypatch.setenv("APP_ENV", "staging")
    yield sleeps
    _resilience.reset_for_tests()


@pytest.fixture
def no_sdk(monkeypatch):
    """Any real provider call fails the test: the drill must stop the
    request before it is sent."""
    from anthropic.resources.beta.messages.messages import AsyncMessages
    from anthropic.resources.messages.messages import AsyncMessages as AsyncMessagesGA
    from google.genai.models import AsyncModels

    async def boom(*a, **k):
        raise AssertionError("a real provider SDK call went out during the drill")

    monkeypatch.setattr(AsyncMessages, "create", boom)
    monkeypatch.setattr(AsyncMessagesGA, "create", boom)
    monkeypatch.setattr(AsyncModels, "generate_content", boom)
    monkeypatch.setattr(AsyncModels, "generate_content_stream", boom)


class _ResilientFn(_ResilientModelMixin, FunctionModel):
    def __init__(self, function=None, *, stream_function=None, provider="anthropic",
                 task="chat_tutor", model_name="claude-sonnet-5-5"):
        super().__init__(function, stream_function=stream_function, model_name=model_name)
        self._init_resilience(provider=provider, task=task, allow_fallback=True)


def _counting(text):
    calls = {"n": 0}

    def fn(messages, info):
        calls["n"] += 1
        return ModelResponse(parts=[TextPart(text)])

    return fn, calls


def _gemini_fallback(monkeypatch, text="from gemini"):
    fn, calls = _counting(text)

    async def stream(messages, info):
        calls["n"] += 1
        for chunk in ("from ", "gemini"):
            yield chunk

    monkeypatch.setattr(_providers, "_build_fallback_model",
                        lambda task, name: FunctionModel(fn, stream_function=stream,
                                                         model_name="gemini-2.5-pro"))
    return calls


# ── the switch ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("variant", "env", "providers", "refused"),
    [
        ("off", {}, set(), False),
        ("off", {"APP_ENV": "production"}, set(), False),
        ("anthropic", {"APP_ENV": "staging"}, {"anthropic"}, False),
        ("google", {"APP_ENV": "local"}, {"google"}, False),
        ("both", {"APP_ENV": "staging"}, {"anthropic", "google"}, False),
        ("openai", {"APP_ENV": "staging"}, set(), False),  # not a variant: off
        # production — explicitly, or by APP_ENV's own fail-closed default
        ("anthropic", {"APP_ENV": "production"}, set(), True),
        ("anthropic", {}, set(), True),
        ("both", {"APP_ENV": "production",
                  "SAPLING_LLM_FORCE_OUTAGE_ALLOW_PRODUCTION": "true"}, set(), True),
        ("anthropic", {"APP_ENV": "production",
                       "SAPLING_LLM_FORCE_OUTAGE_ALLOW_PRODUCTION": "yes"}, {"anthropic"}, False),
    ],
)
def test_the_drill_variants_and_the_production_interlock(variant, env, providers, refused):
    got, why = resolve_forced_outage(variant, env)
    assert got == providers
    assert (why is not None) is refused


def test_the_drill_flag_is_registered_server_only_and_off_first():
    from services.feature_flags import REGISTRY

    fd = REGISTRY["llm_outage_drill"]
    assert fd.variants == ("off", "anthropic", "google", "both") and not fd.client_visible


def test_the_drill_is_resolved_globally_and_off_the_loop(monkeypatch):
    """Global (user_id=None) like llm_fallback, through the shared off-loop
    flag read: no I/O when cached, a worker thread when cold."""
    import threading

    from services import feature_flags as ff

    monkeypatch.delenv(DRILL_ENV)
    monkeypatch.setattr(ff, "cached_explain", lambda key, uid: None)
    seen = []

    def cold(key, uid):
        seen.append((key, uid, threading.current_thread()))
        return ff.Resolution("google", "default")

    monkeypatch.setattr(ff, "explain", cold)

    async def main():
        return await _resilience.forced_outage(), threading.current_thread()

    providers, loop_thread = asyncio.run(main())
    assert providers == frozenset({"google"})
    assert [(k, u) for k, u, _ in seen] == [("llm_outage_drill", None)]
    assert seen[0][2] is not loop_thread

    def broken(key, uid):
        raise RuntimeError("store exploded")

    monkeypatch.setattr(ff, "explain", broken)
    assert asyncio.run(_resilience.forced_outage()) == frozenset()  # unreadable: off


def test_production_refuses_an_armed_drill_without_the_interlock(monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SAPLING_LLM_FORCE_OUTAGE_ALLOW_PRODUCTION", raising=False)
    fn, primary = _counting("from claude")
    with caplog.at_level("ERROR", logger="sapling.agents.resilience"):
        assert asyncio.run(Agent(_ResilientFn(fn)).run("hi")).output == "from claude"
    assert primary["n"] == 1
    assert any("NOT armed" in r.getMessage() for r in caplog.records)
    monkeypatch.setenv("SAPLING_LLM_FORCE_OUTAGE_ALLOW_PRODUCTION", "yes")
    with pytest.raises(ModelHTTPError):
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    assert primary["n"] == 1  # the interlock released: the drill stops the request


def test_a_forced_outage_is_a_retryable_fallback_eligible_503():
    exc = ForcedOutageError("anthropic", "claude-haiku-5-5")
    assert exc.status_code == 503
    assert _resilience.is_retryable(exc) and _resilience.fallback_eligible(exc)


# ── drill on, llm_fallback on: no user-facing error ──────────────────────


def test_drill_on_fallback_on_the_run_is_served_by_the_other_provider(monkeypatch, _fresh):
    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    fb_calls = _gemini_fallback(monkeypatch)
    fn, primary = _counting("from claude")
    result = asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    assert result.output == "from gemini"
    assert primary["n"] == 0  # the drill stops the request before it is sent
    assert fb_calls["n"] == 1
    assert len(_fresh) == _resilience.RETRY_ATTEMPTS - 1  # it retried like a real outage first
    from agents.usage import served_model_name

    assert served_model_name(result, "chat_tutor") == "gemini-2.5-pro"  # what llm_usage records


def test_drill_on_the_real_claude_model_never_reaches_the_sdk(monkeypatch, no_sdk):
    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    _gemini_fallback(monkeypatch)
    agent = Agent(_providers.provider_model("claude-haiku-5-5", task="quiz"))
    assert asyncio.run(agent.run("hi")).output == "from gemini"


def test_the_breaker_opens_then_every_call_goes_straight_to_the_fallback(monkeypatch, _fresh):
    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    _gemini_fallback(monkeypatch)
    agent = Agent(_ResilientFn(_counting("x")[0]))
    runs = -(-_resilience.BREAKER_FAILURE_THRESHOLD // _resilience.RETRY_ATTEMPTS)
    for _ in range(runs):
        assert asyncio.run(agent.run("hi")).output == "from gemini"
    assert _resilience.breaker_for("anthropic").state == "open"
    _fresh.clear()
    assert asyncio.run(agent.run("hi")).output == "from gemini"
    assert _fresh == []  # open breaker: no retries, no backoff, straight to the fallback


def test_drill_on_a_streamed_turn_falls_back_too(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    _gemini_fallback(monkeypatch)

    async def stream(messages, info):
        raise AssertionError("primary stream opened during the drill")
        yield ""  # pragma: no cover

    agent = Agent(_ResilientFn(_counting("x")[0], stream_function=stream))

    async def run():
        async with agent.run_stream("hi") as r:
            return await r.get_output()

    assert asyncio.run(run()) == "from gemini"


def test_the_sse_tutor_shows_no_error_during_a_fallback_drill(monkeypatch):
    from services.chat_stream import stream_agent_turn

    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    _gemini_fallback(monkeypatch)

    async def stream(messages, info):
        raise AssertionError("primary stream opened during the drill")
        yield ""  # pragma: no cover

    agent = Agent(_ResilientFn(_counting("x")[0], stream_function=stream))
    deps = SimpleNamespace(graph_updates=[], mastery_changes=[])

    async def collect():
        return [ev async for ev in stream_agent_turn(
            agent=agent, user_message="hi", run_kwargs={}, deps=deps,
            on_complete=lambda *a: {}, request_id="rid",
        )]

    events = asyncio.run(collect())
    assert [e.type for e in events if e.type == "error"] == []
    assert events[-1].type == "done" and events[-1].data["reply"] == "from gemini"


def test_a_google_drill_leaves_claude_alone(monkeypatch):
    monkeypatch.setenv(DRILL_ENV, "google")
    fn, primary = _counting("from claude")
    assert asyncio.run(Agent(_ResilientFn(fn)).run("hi")).output == "from claude"
    assert primary["n"] == 1


# ── drill on, llm_fallback off (or both providers down): mapped errors ────


def test_drill_on_fallback_off_raises_the_provider_error(monkeypatch):
    fb_calls = _gemini_fallback(monkeypatch)
    with pytest.raises(ModelHTTPError) as exc:
        asyncio.run(Agent(_ResilientFn(_counting("x")[0])).run("hi"))
    assert exc.value.status_code == 503
    assert fb_calls["n"] == 0


def test_drill_on_fallback_off_the_tutor_route_answers_its_mapped_502(monkeypatch):
    from routes.learn import _MODEL_TROUBLE_DETAIL, _agent_turn_or_http_error

    agent = Agent(_ResilientFn(_counting("x")[0]))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(_agent_turn_or_http_error(agent.run("hi"), what="chat agent"))
    assert exc.value.status_code == 502 and exc.value.detail == _MODEL_TROUBLE_DETAIL


def test_drill_on_fallback_off_the_sse_tutor_ends_in_a_retryable_error(monkeypatch):
    from services.chat_stream import stream_agent_turn

    async def stream(messages, info):
        raise AssertionError("primary stream opened during the drill")
        yield ""  # pragma: no cover

    agent = Agent(_ResilientFn(_counting("x")[0], stream_function=stream))
    deps = SimpleNamespace(graph_updates=[], mastery_changes=[])

    async def collect():
        return [ev async for ev in stream_agent_turn(
            agent=agent, user_message="hi", run_kwargs={}, deps=deps,
            on_complete=lambda *a: {}, request_id="rid",
        )]

    last = asyncio.run(collect())[-1]
    assert last.type == "error" and last.data["retryable"] is True
    assert last.message == "The tutor is unavailable. Please retry."


def test_both_providers_down_surfaces_the_primary_error(monkeypatch, no_sdk):
    """The real fallback (a Gemini model) is drilled too: the user gets the
    route's mapped error, and neither SDK is ever called."""
    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    monkeypatch.setenv(DRILL_ENV, "both")
    agent = Agent(_providers.provider_model("claude-haiku-5-5", task="quiz"))
    with pytest.raises(ModelHTTPError) as exc:
        asyncio.run(agent.run("hi"))
    assert exc.value.status_code == 503
    assert not isinstance(exc.value, CircuitOpenError)
    assert exc.value.body["provider"] == "anthropic"  # the primary's error, not the fallback's


# ── the admin view of the drill ──────────────────────────────────────────


def test_admin_drill_endpoint_reports_the_switch_and_breakers(monkeypatch):
    from main import app

    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    _resilience.breaker_for("anthropic")
    body = TestClient(app).get("/api/admin/llm/drill").json()
    assert body["forced_outage"] == {
        "variant": "anthropic", "source": "env_override",
        "providers": ["anthropic"], "refused": None,
    }
    assert body["llm_fallback"] == "on"
    assert body["breakers"] == {"anthropic": "closed"}


def test_admin_drill_endpoint_shows_a_production_refusal(monkeypatch):
    from main import app

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SAPLING_LLM_FORCE_OUTAGE_ALLOW_PRODUCTION", raising=False)
    fo = TestClient(app).get("/api/admin/llm/drill").json()["forced_outage"]
    assert fo["variant"] == "anthropic" and fo["providers"] == []
    assert "refused in production" in fo["refused"]


def test_breaker_states_is_a_copy():
    _resilience.breaker_for("google")
    states = _resilience.breaker_states()
    assert states == {"google": "closed"}
    states["google"] = "open"
    assert _resilience.breaker_states() == {"google": "closed"}
