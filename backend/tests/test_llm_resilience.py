"""#119: retries, timeouts, circuit breaker and the flag-gated cross-provider
fallback around every real model (`agents/_resilience.py` +
`agents/_providers.py::_ResilientModelMixin`).

Hermetic: primaries and fallbacks are pydantic-ai `FunctionModel`s (the mixin
composed onto one) or the real `_LoopSafeAnthropicModel` with its SDK call
patched; nothing sleeps (`_resilience._sleep` is a recorder) and nothing
reaches a transport.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.function import FunctionModel

from agents import _providers, _resilience
from agents._providers import _ResilientModelMixin
from agents._resilience import CircuitBreaker, CircuitOpenError


# ── fixtures / helpers ───────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    """Fresh breakers, no real sleeping, deterministic (max) jitter, and the
    fallback flag pinned off unless a test turns it on."""
    _resilience.reset_for_tests()
    sleeps: list[float] = []

    async def _no_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(_resilience, "_sleep", _no_sleep)
    monkeypatch.setattr(_resilience, "_rng", SimpleNamespace(uniform=lambda lo, hi: hi))
    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "off")
    yield sleeps
    _resilience.reset_for_tests()


def _http(status: int, model: str = "claude-haiku-5-5") -> ModelHTTPError:
    return ModelHTTPError(status_code=status, model_name=model, body={"error": "x"})


class _ResilientFn(_ResilientModelMixin, FunctionModel):
    """A FunctionModel wearing the real mixin: the primary stand-in."""

    def __init__(self, function=None, *, stream_function=None, provider="anthropic",
                 task="classifier", fallback=True, model_name="claude-haiku-5-5"):
        super().__init__(function, stream_function=stream_function, model_name=model_name)
        self._init_resilience(provider=provider, task=task, allow_fallback=fallback)


def _scripted(*outcomes):
    """A FunctionModel function that raises/returns `outcomes` in order
    (the last one repeats), counting calls."""
    calls = {"n": 0}

    def fn(messages, info):
        i = min(calls["n"], len(outcomes) - 1)
        calls["n"] += 1
        out = outcomes[i]
        if isinstance(out, BaseException):
            raise out
        return ModelResponse(parts=[TextPart(out)])

    return fn, calls


def _scripted_stream(*outcomes):
    calls = {"n": 0}

    async def stream(messages, info):
        i = min(calls["n"], len(outcomes) - 1)
        calls["n"] += 1
        out = outcomes[i]
        if isinstance(out, BaseException):
            raise out
        for chunk in out:
            yield chunk

    return stream, calls


def _use_fallback(monkeypatch, fallback):
    monkeypatch.setattr(_providers, "_build_fallback_model", lambda task, name: fallback)


# ── classification + backoff ─────────────────────────────────────────────


@pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 504, 529])
def test_provider_trouble_is_retryable(status):
    assert _resilience.is_retryable(_http(status))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 422])
def test_request_errors_are_not_retryable(status):
    assert not _resilience.is_retryable(_http(status))


@pytest.mark.parametrize(
    ("exc", "retryable"),
    [
        (ModelAPIError("m", "connection reset"), True),  # SDK connection/timeouts
        (httpx.ConnectError("boom"), True),  # google-genai lets httpx through
        (httpx.ReadTimeout("slow"), True),
        (TimeoutError(), True),
        (CircuitOpenError("anthropic", "m"), False),
        (UnexpectedModelBehavior("bad output"), False),  # pydantic-ai's own layer
        (ValueError("bug"), False),
    ],
)
def test_other_errors(exc, retryable):
    assert _resilience.is_retryable(exc) is retryable


def test_backoff_is_full_jitter_exponential_and_capped(monkeypatch):
    seen = []
    monkeypatch.setattr(
        _resilience, "_rng", SimpleNamespace(uniform=lambda lo, hi: seen.append((lo, hi)) or hi)
    )
    assert [_resilience.backoff_delay(i) for i in range(5)] == [0.5, 1.0, 2.0, 4.0, 4.0]
    assert all(lo == 0.0 for lo, _ in seen)  # full jitter: anywhere from zero


class _SdkError(Exception):
    """Stands in for the SDK error pydantic-ai chains as `__cause__`."""

    def __init__(self, headers):
        super().__init__("sdk")
        self.response = SimpleNamespace(headers=headers)


def _with_retry_after(exc, headers):
    exc.__cause__ = _SdkError(headers)
    return exc


def test_retry_after_is_honoured_up_to_the_cap():
    exc = _with_retry_after(_http(429), {"retry-after": "3"})
    assert _resilience.retry_delay(exc, 0) == 3.0
    ms = _with_retry_after(_http(429), {"retry-after-ms": "1500"})
    assert _resilience.retry_delay(ms, 0) == 1.5
    too_long = _with_retry_after(_http(429), {"retry-after": "120"})
    assert _resilience.retry_delay(too_long, 0) is None  # give up, don't hold the request


def test_a_circuit_open_error_reads_as_an_upstream_503():
    exc = CircuitOpenError("anthropic", "claude-haiku-5-5")
    assert isinstance(exc, ModelHTTPError) and exc.status_code == 503


# ── retries through a real agent run ─────────────────────────────────────


def test_retries_then_succeeds(_fresh_state):
    fn, calls = _scripted(_http(529), _http(429), "ok")
    out = asyncio.run(Agent(_ResilientFn(fn)).run("hi")).output
    assert out == "ok"
    assert calls["n"] == 3
    assert _fresh_state == [0.5, 1.0]  # backoff before each retry


def test_a_non_retryable_error_is_raised_on_the_first_attempt(_fresh_state):
    fn, calls = _scripted(_http(400))
    with pytest.raises(ModelHTTPError) as exc:
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    assert exc.value.status_code == 400
    assert calls["n"] == 1 and _fresh_state == []


def test_attempts_are_bounded(_fresh_state):
    fn, calls = _scripted(_http(529))
    with pytest.raises(ModelHTTPError) as exc:
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    assert exc.value.status_code == 529
    assert calls["n"] == _resilience.RETRY_ATTEMPTS == 3
    assert len(_fresh_state) == 2


def test_an_over_long_retry_after_stops_retrying(_fresh_state):
    fn, calls = _scripted(_with_retry_after(_http(429), {"retry-after": "600"}))
    with pytest.raises(ModelHTTPError):
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    assert calls["n"] == 1 and _fresh_state == []


def test_each_attempt_has_a_deadline():
    attempts = {"n": 0}

    async def hang():
        attempts["n"] += 1
        await asyncio.sleep(5)

    site = _resilience.CallSite("anthropic", "m", "quiz")
    with pytest.raises(_resilience.DeadlineExceeded):
        asyncio.run(_resilience.call_with_retries(site, hang, deadline_s=0.01))
    assert attempts["n"] == 3  # a deadline is retryable like an SDK timeout


# ── circuit breaker ──────────────────────────────────────────────────────


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _breaker():
    clock = _Clock()
    return CircuitBreaker("anthropic", clock=clock), clock


def test_breaker_opens_after_consecutive_failures_and_fails_fast():
    b, _ = _breaker()
    for _ in range(_resilience.BREAKER_FAILURE_THRESHOLD - 1):
        b.record_failure()
    assert b.state == "closed" and b.allow()
    b.record_failure()
    assert b.state == "open"
    assert not b.allow()


def test_a_success_resets_the_streak():
    b, _ = _breaker()
    for _ in range(_resilience.BREAKER_FAILURE_THRESHOLD - 1):
        b.record_failure()
    b.record_success()
    b.record_failure()
    assert b.state == "closed"


def test_failures_spread_beyond_the_window_do_not_open_it():
    b, clock = _breaker()
    for _ in range(_resilience.BREAKER_FAILURE_THRESHOLD - 1):
        b.record_failure()
    clock.t += _resilience.BREAKER_WINDOW_S + 1
    b.record_failure()
    assert b.state == "closed"


def _open(b):
    for _ in range(_resilience.BREAKER_FAILURE_THRESHOLD):
        b.record_failure()
    assert b.state == "open"


def test_half_open_lets_exactly_one_probe_through_then_closes_on_success():
    b, clock = _breaker()
    _open(b)
    clock.t += _resilience.BREAKER_COOLDOWN_S - 1
    assert not b.allow()
    clock.t += 2
    assert b.allow() and b.state == "half_open"
    assert not b.allow()  # the probe is in flight
    b.record_success()
    assert b.state == "closed" and b.allow()


def test_a_failed_probe_reopens_for_another_cooldown():
    b, clock = _breaker()
    _open(b)
    clock.t += _resilience.BREAKER_COOLDOWN_S + 1
    assert b.allow()
    b.record_failure()
    assert b.state == "open" and not b.allow()
    clock.t += _resilience.BREAKER_COOLDOWN_S + 1
    assert b.allow() and b.state == "half_open"


def test_a_released_probe_frees_the_slot_and_a_stale_one_expires():
    b, clock = _breaker()
    _open(b)
    clock.t += _resilience.BREAKER_COOLDOWN_S + 1
    assert b.allow()
    b.release()  # cancelled: no verdict
    assert b.state == "half_open" and b.allow()
    assert not b.allow()
    clock.t += _resilience.BREAKER_PROBE_TTL_S + 1
    assert b.allow()  # the hung probe no longer blocks


def test_breakers_are_per_provider_and_thread_safe():
    import threading

    anthropic = _resilience.breaker_for("anthropic")
    assert _resilience.breaker_for("google") is not anthropic
    assert _resilience.breaker_for("anthropic") is anthropic

    def hammer():
        for _ in range(500):
            anthropic.record_failure()
            anthropic.allow()
            anthropic.record_success()

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert anthropic.state == "closed"


def test_an_open_breaker_fails_calls_fast_without_a_request(_fresh_state):
    _open(_resilience.breaker_for("anthropic"))
    fn, calls = _scripted("ok")
    with pytest.raises(CircuitOpenError):
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    assert calls["n"] == 0


def test_the_breaker_opens_from_real_failing_calls(_fresh_state):
    fn, calls = _scripted(_http(529))
    agent = Agent(_ResilientFn(fn))
    runs = -(-_resilience.BREAKER_FAILURE_THRESHOLD // _resilience.RETRY_ATTEMPTS)
    for _ in range(runs):
        with pytest.raises(ModelHTTPError):
            asyncio.run(agent.run("hi"))
    assert _resilience.breaker_for("anthropic").state == "open"
    before = calls["n"]
    with pytest.raises(CircuitOpenError):
        asyncio.run(agent.run("hi"))
    assert calls["n"] == before


def test_a_non_retryable_error_counts_as_the_provider_answering():
    b = _resilience.breaker_for("anthropic")
    for _ in range(_resilience.BREAKER_FAILURE_THRESHOLD - 1):
        b.record_failure()
    fn, _ = _scripted(_http(400))
    with pytest.raises(ModelHTTPError):
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    b.record_failure()
    assert b.state == "closed"


# ── fallback ─────────────────────────────────────────────────────────────


def test_fallback_is_used_only_when_the_flag_is_on(monkeypatch):
    fn, primary_calls = _scripted(_http(529))
    fb_fn, fb_calls = _scripted("from gemini")
    _use_fallback(monkeypatch, FunctionModel(fb_fn, model_name="gemini-2.5-flash-lite"))
    agent = Agent(_ResilientFn(fn))

    with pytest.raises(ModelHTTPError):
        asyncio.run(agent.run("hi"))
    assert fb_calls["n"] == 0  # flag off: today's primary-only path

    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    result = asyncio.run(agent.run("hi"))
    assert result.output == "from gemini"
    assert fb_calls["n"] == 1
    # usage is recorded against the model that actually served the run
    from agents.usage import served_model_name

    assert served_model_name(result, "classifier") == "gemini-2.5-flash-lite"


def test_no_fallback_for_a_request_error(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    fn, _ = _scripted(_http(400))
    fb_fn, fb_calls = _scripted("from gemini")
    _use_fallback(monkeypatch, FunctionModel(fb_fn))
    with pytest.raises(ModelHTTPError):
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    assert fb_calls["n"] == 0


def test_an_open_breaker_goes_straight_to_the_fallback(monkeypatch, _fresh_state):
    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    _open(_resilience.breaker_for("anthropic"))
    fn, primary_calls = _scripted("never")
    fb_fn, _ = _scripted("from gemini")
    _use_fallback(monkeypatch, FunctionModel(fb_fn))
    assert asyncio.run(Agent(_ResilientFn(fn)).run("hi")).output == "from gemini"
    assert primary_calls["n"] == 0 and _fresh_state == []


def test_a_failing_fallback_surfaces_the_primary_error(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    fn, _ = _scripted(_http(529))
    fb_fn, _ = _scripted(_http(401, "gemini-2.5-flash"))
    _use_fallback(monkeypatch, FunctionModel(fb_fn))
    with pytest.raises(ModelHTTPError) as exc:
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    assert exc.value.status_code == 529


def test_the_health_probe_never_falls_back(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    fn, _ = _scripted(_http(529))
    fb_fn, fb_calls = _scripted("x")
    _use_fallback(monkeypatch, FunctionModel(fb_fn))
    with pytest.raises(ModelHTTPError):
        asyncio.run(Agent(_ResilientFn(fn, task=None)).run("hi"))
    assert fb_calls["n"] == 0


def test_the_flag_is_read_without_io_when_cached_and_off_the_loop_when_cold(monkeypatch):
    from services import feature_flags as ff

    monkeypatch.delenv("SAPLING_FLAG_LLM_FALLBACK", raising=False)
    monkeypatch.setattr(ff, "cached_explain", lambda key, uid: None)
    threads = []

    def cold_explain(key, uid):
        import threading

        threads.append(threading.current_thread())
        assert key == "llm_fallback" and uid is None  # global evaluation
        return ff.Resolution("on", "default")

    monkeypatch.setattr(ff, "explain", cold_explain)

    async def main():
        import threading

        return await _resilience.fallback_enabled(), threading.current_thread()

    enabled, loop_thread = asyncio.run(main())
    assert enabled and threads and threads[0] is not loop_thread

    def broken(key, uid):
        raise RuntimeError("store exploded")

    monkeypatch.setattr(ff, "explain", broken)
    assert asyncio.run(_resilience.fallback_enabled()) is False


def test_the_flag_is_registered_server_only_and_off_first():
    from services.feature_flags import REGISTRY

    fd = REGISTRY["llm_fallback"]
    assert fd.variants == ("off", "on") and not fd.client_visible


class _Out(BaseModel):
    label: str


@pytest.mark.parametrize("instrument", [False, True], ids=["plain", "instrumented"])
def test_the_fallback_gets_its_own_preparation_not_claudes(monkeypatch, instrument):
    """The real Claude primary resolves native JSON output and drops the
    output tools when it prepares a request; logfire's instrumentation
    (main.py) prepares BEFORE `request` and passes those parameters down. The
    fallback must still get the unprepared parameters (so its own profile
    picks its output mode) and none of Claude's bottom-layer settings."""
    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    primary_calls = {"n": 0}

    async def overloaded(self, messages, model_settings, params):
        primary_calls["n"] += 1
        raise _http(529)

    monkeypatch.setattr(AnthropicModel, "request", overloaded)
    seen = {}

    def fb_fn(messages, info):
        seen["info"] = info
        tool = info.output_tools[0]
        from pydantic_ai.messages import ToolCallPart

        return ModelResponse(parts=[ToolCallPart(tool.name, {"label": "fallback"})])

    _use_fallback(monkeypatch, FunctionModel(fb_fn, model_name="gemini-2.5-flash-lite"))
    primary = _providers.provider_model("claude-haiku-5-5", task="classifier")
    agent = Agent(primary, output_type=_Out, instrument=instrument)
    out = asyncio.run(agent.run("hi")).output

    assert out == _Out(label="fallback")
    assert primary_calls["n"] == 3
    info = seen["info"]
    assert info.output_tools, "fallback was handed Claude's native-output preparation"
    assert info.model_request_parameters.output_mode != "native"
    settings = info.model_settings or {}
    assert "anthropic_effort" not in settings and "max_tokens" not in settings
    assert "timeout" not in settings  # Claude's httpx timeout must not reach Gemini


# ── timeouts + SDK retry budget ──────────────────────────────────────────


def test_claude_requests_carry_the_slot_timeout(monkeypatch):
    from anthropic.resources.beta.messages.messages import AsyncMessages

    sent = {}

    async def capture(self, **kwargs):
        sent.update(kwargs)
        raise ValueError("captured")  # not retryable: one attempt

    monkeypatch.setattr(AsyncMessages, "create", capture)
    agent = Agent(_providers.provider_model("claude-haiku-5-5", task="quiz"))
    with pytest.raises(ValueError):
        asyncio.run(agent.run("hi"))
    timeout = sent["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.read == _providers.timeout_for("quiz") == 240.0
    assert timeout.connect == 5.0

    sent.clear()
    with pytest.raises(ValueError):
        asyncio.run(agent.run("hi", model_settings={"timeout": 7.0}))
    assert sent["timeout"] == 7.0  # an agent/run-level timeout wins (ocr_vision)


def test_gemini_requests_get_a_numeric_timeout():
    m = _providers.provider_model("gemini-2.5-flash", task="syllabus")
    assert m._with_timeout(None) == {"timeout": 240.0}
    assert _providers.provider_model("claude-haiku-5-5")._with_timeout({})["timeout"].read == 30.0


def test_the_anthropic_sdk_does_not_retry_on_its_own():
    assert _providers._new_anthropic_provider().client.max_retries == 0


# ── fallback model selection ─────────────────────────────────────────────


def test_fallback_names(monkeypatch):
    assert _providers.fallback_model_name_for("quiz", "claude-haiku-5-5") == "gemini-2.5-flash-lite"
    assert _providers.fallback_model_name_for("chat_tutor", "claude-sonnet-5-5") == "gemini-2.5-pro"
    # a slot pointed back at Gemini falls back to its Claude default
    assert _providers.fallback_model_name_for("quiz", "gemini-2.5-flash") == "claude-haiku-5-5"
    monkeypatch.setenv("SAPLING_MODEL_FALLBACK_QUIZ", "gemini-2.5-flash")
    assert _providers.fallback_model_name_for("quiz", "claude-haiku-5-5") == "gemini-2.5-flash"
    assert set(_providers._GEMINI_FALLBACKS) == set(_providers._DEFAULTS)


def test_the_loop_key_and_alignment_checks_never_fall_back_to_the_drafters_family():
    # A119 / A124: a check must not come from the gemini-* drafter's family,
    # and an unavailable check already fails closed (the item is held).
    for task in ("check_items_verify", "check_items_solve"):
        assert _providers._GEMINI_FALLBACKS[task] is None
        assert _providers.fallback_model_name_for(task, "claude-haiku-5-5") is None
    # A pending loop slot flipped to Claude falls back to the Gemini model its
    # gates were recorded on; on its Gemini default it has no fallback at all.
    assert _providers.fallback_model_name_for("grader", "claude-haiku-5-5") == "gemini-2.5-flash-lite"
    assert _providers.fallback_model_name_for("loop_tutor_deep", "claude-sonnet-5-5") == "gemini-2.5-pro"
    assert _providers.fallback_model_name_for("grader", "gemini-2.5-flash-lite") is None


def test_a_run_that_asks_for_a_longer_timeout_gets_a_longer_deadline():
    # The loop's Flex drafting waits up to FLEX_TIMEOUT_S (900 s): a 120 s slot
    # deadline would cut every queued request and retry it as a new generation.
    from learning.params import FLEX_TIMEOUT_S

    assert _providers.deadline_for("check_items") == _providers.timeout_for("check_items")
    assert _providers.deadline_for("check_items", {"timeout": FLEX_TIMEOUT_S}) == FLEX_TIMEOUT_S
    assert _providers.deadline_for(
        "check_items", {"timeout": httpx.Timeout(FLEX_TIMEOUT_S, connect=5.0)}
    ) == FLEX_TIMEOUT_S
    # never shorter than the slot's: ocr_vision pins 60 s and keeps 120 s
    assert _providers.deadline_for("ocr_vision", {"timeout": 60.0}) == 120.0
    assert _providers.deadline_for("quiz", {"timeout": True}) == _providers.timeout_for("quiz")


def test_a_built_fallback_is_resilient_but_never_falls_back_again():
    fb = _providers._build_fallback_model("quiz", "claude-haiku-5-5")
    assert isinstance(fb, _providers._LoopSafeGoogleModel)
    assert fb.model_name == "gemini-2.5-flash-lite"
    assert fb._res_provider == "google" and fb._res_allow_fallback is False
    assert _providers._build_fallback_model(None, "claude-haiku-5-5") is None


# ── streaming ────────────────────────────────────────────────────────────


async def _stream_text(agent):
    async with agent.run_stream("hi") as run:
        return await run.get_output()


def test_a_stream_retries_while_opening(_fresh_state):
    stream, calls = _scripted_stream(_http(529), ["hel", "lo"])
    fn, _ = _scripted("unused")
    agent = Agent(_ResilientFn(fn, stream_function=stream))
    assert asyncio.run(_stream_text(agent)) == "hello"
    assert calls["n"] == 2 and _fresh_state == [0.5]


def test_a_stream_falls_back_when_the_flag_is_on(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    stream, _ = _scripted_stream(_http(529))
    fn, _ = _scripted("unused")
    fb_stream, fb_calls = _scripted_stream(["from ", "gemini"])
    _use_fallback(monkeypatch, FunctionModel(fn, stream_function=fb_stream))
    agent = Agent(_ResilientFn(fn, stream_function=stream))
    assert asyncio.run(_stream_text(agent)) == "from gemini"
    assert fb_calls["n"] == 1


def test_a_mid_stream_failure_is_not_retried():
    calls = {"n": 0}

    async def stream(messages, info):
        calls["n"] += 1
        yield "partial "
        raise _http(529)

    fn, _ = _scripted("unused")
    agent = Agent(_ResilientFn(fn, stream_function=stream))
    with pytest.raises(ModelHTTPError):
        asyncio.run(_stream_text(agent))
    assert calls["n"] == 1  # a retry would have duplicated "partial "


# ── function mode is untouched ───────────────────────────────────────────


def test_function_mode_never_meets_the_resilience_layer(monkeypatch):
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    model = _providers.model_for("classifier")
    assert isinstance(model, FunctionModel)
    assert not isinstance(model, _ResilientModelMixin)

    async def boom(*a, **k):
        raise AssertionError("resilience layer reached in function mode")

    monkeypatch.setattr(_resilience, "call_with_retries", boom)
    _providers.register_function_handler(
        "classifier", lambda messages, info: ModelResponse(parts=[TextPart("scripted")])
    )
    try:
        assert asyncio.run(Agent(model).run("hi")).output == "scripted"
    finally:
        _providers.clear_function_handlers()
