"""PKG-15: agents/_jev.py, the Jev backend over typesafe-sdk==0.7.2 (spec §3.6, §13 A24, A98).

Hermetic: every call goes through an httpx2.MockTransport installed on
`_jev._transport_override` (the conftest guard installs a blocking one by default).
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx2
import pytest

from agents import _jev
from services import decisions

_BACKEND = __import__("pathlib").Path(__file__).resolve().parents[1]

STATE = {"question": "What does a base case do?", "student_answer": "It stops the recursion."}
QUESTIONS = {
    "q1": _jev.Question(
        instructions="Does the answer say the base case stops the recursion?",
        options={"yes": "It does.", "no": "It does not.", "unclear": "The state does not settle it."},
    )
}


def _answer(choice="yes", confidence=0.91, probs=None, *, model="jev-1.13.0", name="q1"):
    probs = probs or {"yes": 0.93, "no": 0.05, "unclear": 0.02}
    return {
        "model": model,
        "answers": {
            name: {"type": "choice", "choice": choice, "confidence": confidence, "probabilities": probs}
        },
        "usage": {"input_tokens": 120, "output_tokens": 4},
    }


class _Wire:
    """A scripted MockTransport: each call pops the next (status, body) or raises."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        nxt = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(nxt, BaseException):
            raise nxt
        status, body = nxt
        return httpx2.Response(status, json=body)

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


@pytest.fixture
def jev(monkeypatch):
    """Real mode, Jev enabled, a key set, a fresh breaker and client cache."""
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    monkeypatch.setattr(decisions, "JEV_ENABLED", True)
    monkeypatch.setenv(_jev.API_KEY_ENV, "ts-test-key")
    monkeypatch.setenv("APP_ENV", "test")
    _jev.reset_for_tests()
    yield _jev
    _jev.reset_for_tests()


def _install(monkeypatch, wire: _Wire):
    monkeypatch.setattr(_jev, "_transport_override", httpx2.MockTransport(wire))
    _jev.reset_for_tests()
    return wire


def _ask(state=STATE, questions=QUESTIONS):
    return asyncio.run(_jev.ask(state, questions))


# ── the build guard (invariant 24) ───────────────────────────────────────────


@pytest.mark.parametrize(
    "mode,enabled", [("function", True), ("test", True), ("real", False), (None, False)]
)
def test_client_is_built_only_in_real_mode_with_jev_enabled(jev, monkeypatch, mode, enabled):
    built = []
    monkeypatch.setattr(_jev, "_client_class_override", lambda **kw: built.append(kw))
    if mode is None:
        monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    else:
        monkeypatch.setenv("SAPLING_MODEL_MODE", mode)
    monkeypatch.setattr(decisions, "JEV_ENABLED", enabled)
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "jev_absent" and built == []
    assert _jev.enabled() is False


def test_no_key_is_jev_absent_without_a_client(jev, monkeypatch):
    built = []
    monkeypatch.setattr(_jev, "_client_class_override", lambda **kw: built.append(kw))
    monkeypatch.delenv(_jev.API_KEY_ENV, raising=False)
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "jev_absent" and built == []


def test_client_is_pinned_and_bounded(jev, monkeypatch):
    built = []

    class _Spy:
        def __init__(self, **kw):
            built.append(kw)

        async def system_one(self, state, questions, *, model=None, **kw):
            raise AssertionError("not called")

    monkeypatch.setattr(_jev, "_client_class_override", _Spy)

    async def _build():
        return _jev._client()

    asyncio.run(_build())
    [kw] = built
    assert kw["model"] == decisions.JEV_MODEL == "jev-1.13.0"
    assert kw["timeout"] == decisions.JEV_TIMEOUT_MS / 1000
    retry = kw["retry"]
    assert retry.max_retries == decisions.JEV_MAX_RETRIES == 1
    assert (retry.backoff_initial, retry.respect_retry_after, retry.api_timeout_error) == (
        0.0,
        False,
        False,
    )
    assert 429 not in retry.http_statuses and 529 not in retry.http_statuses


# ── the call ────────────────────────────────────────────────────────────────


def test_ask_sends_choice_questions_on_the_pinned_model_and_parses(jev, monkeypatch):
    wire = _install(monkeypatch, _Wire((200, _answer())))
    out = _ask()
    [body] = wire.bodies()
    assert body["model"] == "jev-1.13.0"
    assert body["state"] == STATE
    assert body["questions"]["q1"]["type"] == "choice"  # A24: a Choice, never a Noul
    assert set(body["questions"]["q1"]["criteria"]) == {"yes", "no", "unclear"}
    assert set(body) == {"state", "model", "questions"}  # no extra_body, no identifiers
    a = out.answers["q1"]
    assert (a.choice, a.confidence, a.probabilities["yes"]) == ("yes", 0.91, 0.93)
    assert (out.model, out.input_tokens, out.output_tokens) == ("jev-1.13.0", 120, 4)
    assert isinstance(out.latency_ms, int)
    headers = {k.lower() for k in wire.requests[0].headers}
    assert not headers & {"x-user-id", "x-request-id", "x-session-id"}


@pytest.mark.parametrize(
    "status,code", [(401, "http_401"), (403, "http_403"), (422, "http_422"), (429, "http_429"), (529, "http_529")]
)
def test_http_errors_map_to_enum_codes_and_never_retry(jev, monkeypatch, status, code):
    wire = _install(monkeypatch, _Wire((status, {"error": "the state was: It stops the recursion."})))
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == code and len(wire.requests) == 1
    assert "recursion" not in str(exc.value) and exc.value.__suppress_context__


def test_a_5xx_is_retried_once(jev, monkeypatch):
    wire = _install(monkeypatch, _Wire((503, {}), (200, _answer())))
    assert _ask().answers["q1"].choice == "yes" and len(wire.requests) == 2
    wire = _install(monkeypatch, _Wire((503, {})))
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "http_503" and len(wire.requests) == 2  # 1 + JEV_MAX_RETRIES


def test_a_timeout_is_not_retried(jev, monkeypatch):
    wire = _install(monkeypatch, _Wire(httpx2.ReadTimeout("slow")))
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "timeout" and len(wire.requests) == 1


def test_the_wall_clock_deadline_holds(jev, monkeypatch):
    monkeypatch.setattr(decisions, "JEV_TIMEOUT_MS", 20)

    class _Slow:
        def __init__(self, **kw):
            pass

        async def system_one(self, *a, **kw):
            await asyncio.sleep(5)

    monkeypatch.setattr(_jev, "_client_class_override", _Slow)
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "timeout"


def test_a_connection_error_is_transport(jev, monkeypatch):
    _install(monkeypatch, _Wire(httpx2.ConnectError("refused")))
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "transport"


@pytest.mark.parametrize(
    "body",
    [
        _answer(choice="maybe"),  # not a listed option
        _answer(name="other"),  # the question went unanswered
        {"model": "jev-1.13.0", "usage": {"input_tokens": 1, "output_tokens": 0}, "answers": {"q1": {"type": "noul", "noul": 0.9}}},
    ],
)
def test_an_unusable_answer_is_bad_answer_and_keeps_the_billed_tokens(jev, monkeypatch, body):
    _install(monkeypatch, _Wire((200, body)))
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "bad_answer"
    assert exc.value.model == "jev-1.13.0" and exc.value.input_tokens >= 1


def test_a_malformed_body_is_bad_answer(jev, monkeypatch):
    _install(monkeypatch, _Wire((200, {"answers": "nope"})))
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "bad_answer"


# ── the token budget: oversize goes elsewhere, never truncated ───────────────


def test_an_oversize_state_is_refused_before_any_call_and_never_truncated(jev, monkeypatch):
    wire = _install(monkeypatch, _Wire((200, _answer())))
    limit = decisions.JEV_STATE_MAX_TOKENS
    big = {"passage": "x" * (limit * _jev.CHARS_PER_TOKEN)}
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask(state=big)
    assert exc.value.code == "oversize" and wire.requests == []
    assert big["passage"] == "x" * (limit * _jev.CHARS_PER_TOKEN)  # untouched
    for _ in range(decisions.JEV_CIRCUIT_FAILS):  # oversize never trips the breaker
        with pytest.raises(_jev.JevUnavailable):
            _ask(state=big)
    assert _ask().answers["q1"].choice == "yes"


def test_the_estimate_is_pessimistic_over_state_plus_longest_question():
    state = {"a": "y" * 300}
    est = _jev.estimate_tokens(state, {"q": {"instructions": "z" * 30}})
    assert est >= (len(json.dumps(state)) + 30) // 3


# ── the circuit breaker ─────────────────────────────────────────────────────


def test_consecutive_failures_open_the_circuit_for_the_cooldown(jev, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(_jev, "_clock", lambda: now[0])
    wire = _install(monkeypatch, _Wire((529, {})))
    for _ in range(decisions.JEV_CIRCUIT_FAILS):
        with pytest.raises(_jev.JevUnavailable) as exc:
            _ask()
        assert exc.value.code == "http_529"
    sent = len(wire.requests)
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "circuit_open" and len(wire.requests) == sent
    now[0] += decisions.JEV_CIRCUIT_COOLDOWN_S - 1
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "circuit_open"
    # after the cooldown ONE probe goes out; it fails → open again
    now[0] += 2
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "http_529" and len(wire.requests) == sent + 1
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "circuit_open"
    # a successful probe closes it
    now[0] += decisions.JEV_CIRCUIT_COOLDOWN_S + 1
    wire.responses = [(200, _answer())]
    assert _ask().answers["q1"].choice == "yes"
    assert _ask().answers["q1"].choice == "yes"
    assert _jev.circuit_open() is False


def test_a_success_resets_the_failure_count(jev, monkeypatch):
    wire = _install(monkeypatch, _Wire((529, {})))
    for _ in range(decisions.JEV_CIRCUIT_FAILS - 1):
        with pytest.raises(_jev.JevUnavailable):
            _ask()
    wire.responses = [(200, _answer())]
    _ask()
    wire.responses = [(529, {})]
    for _ in range(decisions.JEV_CIRCUIT_FAILS - 1):
        with pytest.raises(_jev.JevUnavailable) as exc:
            _ask()
        assert exc.value.code == "http_529"


# ── no student text in logs ─────────────────────────────────────────────────


def test_the_sdk_logger_never_logs_bodies(jev, monkeypatch, caplog):
    """typesafe_sdk logs request/response BODIES at DEBUG; _jev floors it at WARNING
    even when the root logger (or TYPESAFE_LOG_LEVEL) asks for DEBUG."""
    assert logging.getLogger("typesafe_sdk").getEffectiveLevel() >= logging.WARNING
    _install(monkeypatch, _Wire((200, _answer())))
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("typesafe_sdk").setLevel(logging.DEBUG)  # what TYPESAFE_LOG_LEVEL=debug does
        _jev._floor_sdk_logging()
        _ask()
    assert not any("recursion" in r.getMessage() for r in caplog.records)


def test_the_conftest_guard_refuses_unstubbed_egress(monkeypatch):
    """Without a test's own MockTransport, a Jev call never leaves the process."""
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    monkeypatch.setattr(decisions, "JEV_ENABLED", True)
    monkeypatch.setenv(_jev.API_KEY_ENV, "ts-test-key")
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "transport"


def test_jev_is_priced_input_only_on_the_pinned_id():
    from services import llm_pricing

    assert llm_pricing.MODEL_PRICING[decisions.JEV_MODEL] == (0.000042, 0.0)
    assert llm_pricing.cost_usd(decisions.JEV_MODEL, 1_000_000, 50) == pytest.approx(0.042)


# ── review fix round (PKG-15 R1) ─────────────────────────────────────────────


def test_a_cancelled_half_open_probe_releases_the_circuit(jev, monkeypatch):
    """M1 (the reviewer's probe_cancel.py): a probe cancelled mid-call (a client
    disconnect cancels the route) must not leave the breaker probing forever."""
    now = [1000.0]
    monkeypatch.setattr(_jev, "_clock", lambda: now[0])
    _install(monkeypatch, _Wire((500, {})))
    for _ in range(decisions.JEV_CIRCUIT_FAILS):
        with pytest.raises(_jev.JevUnavailable):
            _ask()
    assert _jev.circuit_open()
    now[0] += decisions.JEV_CIRCUIT_COOLDOWN_S + 1

    async def slow(request):
        await asyncio.sleep(10)

    monkeypatch.setattr(_jev, "_transport_override", httpx2.MockTransport(slow))
    _jev._clients.clear()

    async def cancel_probe():
        t = asyncio.create_task(_jev.ask(STATE, QUESTIONS))
        await asyncio.sleep(0.02)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):  # still propagates
            await t

    asyncio.run(cancel_probe())
    assert _jev._breaker.probing is False  # released; the cancel counted as a failure
    now[0] += decisions.JEV_CIRCUIT_COOLDOWN_S + 1
    _install(monkeypatch, _Wire((200, _answer())))
    assert _ask().answers["q1"].choice == "yes"
    assert not _jev.circuit_open()


def test_a_non_sdk_exception_during_the_call_releases_the_probe(jev, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(_jev, "_clock", lambda: now[0])
    _jev._breaker.opened_at, _jev._breaker.fails = now[0], decisions.JEV_CIRCUIT_FAILS
    now[0] += decisions.JEV_CIRCUIT_COOLDOWN_S + 1

    class _Boom:
        def __init__(self, **kw):
            pass

        async def system_one(self, *a, **kw):
            raise RuntimeError("an SDK bug")

    monkeypatch.setattr(_jev, "_client_class_override", _Boom)
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "bad_answer" and _jev._breaker.probing is False


def test_a_transport_failure_records_its_real_latency(jev, monkeypatch):
    import time as _time

    def slow_refuse(request):
        _time.sleep(0.03)
        raise httpx2.ConnectError("refused")

    monkeypatch.setattr(_jev, "_transport_override", httpx2.MockTransport(slow_refuse))
    _jev.reset_for_tests()
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "transport" and exc.value.latency_ms >= 30


def test_the_deadline_is_jev_timeout_ms_in_total(jev, monkeypatch):
    """Minor 6: JEV_TIMEOUT_MS bounds the whole call, retries included."""
    import time as _time

    monkeypatch.setattr(decisions, "JEV_TIMEOUT_MS", 60)
    calls = []

    async def slow_503(request):
        calls.append(1)
        await asyncio.sleep(0.04)
        return httpx2.Response(503, json={})

    monkeypatch.setattr(_jev, "_transport_override", httpx2.MockTransport(slow_503))
    _jev.reset_for_tests()
    t0 = _time.monotonic()
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert (_time.monotonic() - t0) < 0.2 and exc.value.code == "timeout" and len(calls) == 2


@pytest.mark.parametrize(
    "app_env,recorded,allowed",
    [
        ("production", None, False),
        ("staging", None, False),
        ("production", "false", False),
        ("production", "true", True),
        ("staging", " TRUE ", True),
        ("local", None, True),
        ("test", None, True),
    ],
)
def test_the_privacy_gate_interlock(jev, monkeypatch, app_env, recorded, allowed):
    """Minor 3 (spec §13 A24): in production or staging no Jev call goes out — serve or
    shadow — until the owner records the gate with JEV_PRIVACY_GATE_RECORDED=true."""
    wire = _install(monkeypatch, _Wire((200, _answer())))
    monkeypatch.setenv("APP_ENV", app_env)
    if recorded is None:
        monkeypatch.delenv("JEV_PRIVACY_GATE_RECORDED", raising=False)
    else:
        monkeypatch.setenv("JEV_PRIVACY_GATE_RECORDED", recorded)
    if allowed:
        assert _ask().answers["q1"].choice == "yes"
    else:
        with pytest.raises(_jev.JevUnavailable) as exc:
            _ask()
        assert exc.value.code == "privacy_gate" and wire.requests == []


def test_an_unset_app_env_is_production_for_the_gate(jev, monkeypatch):
    _install(monkeypatch, _Wire((200, _answer())))
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("JEV_PRIVACY_GATE_RECORDED", raising=False)
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "privacy_gate"  # config.py: unset APP_ENV means production


def test_importing_jev_does_not_import_the_sdk():
    """Minor 2: app start with JEV_ENABLED=false never depends on the SDK importing."""
    import subprocess
    import sys

    code = (
        "import sys; import agents._jev, services.decisions; "
        "print('typesafe_sdk' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(_BACKEND), check=True
    )
    assert out.stdout.strip() == "False"


def test_a_missing_sdk_is_jev_absent(jev, monkeypatch):
    import builtins

    real = builtins.__import__

    def no_sdk(name, *a, **k):
        if name.startswith("typesafe_sdk"):
            raise ImportError("not installed")
        return real(name, *a, **k)

    monkeypatch.setattr(_jev, "_SDK", None)
    monkeypatch.setattr(builtins, "__import__", no_sdk)
    with pytest.raises(_jev.JevUnavailable) as exc:
        _ask()
    assert exc.value.code == "jev_absent"


def test_the_sdk_log_floor_is_unconditional(jev, monkeypatch):
    """Minor 4: WARNING whatever the root level or TYPESAFE_LOG_LEVEL, and a filter that
    drops anything below it even if someone lowers the level later."""
    sdk = logging.getLogger("typesafe_sdk")
    sdk.setLevel(logging.DEBUG)
    logging.getLogger().setLevel(logging.ERROR)  # a high root must not "inherit" a low floor
    try:
        _jev._floor_sdk_logging()
        assert sdk.level == logging.WARNING
        sdk.setLevel(logging.DEBUG)  # lowered after the floor
        seen = []

        class _H(logging.Handler):
            def emit(self, record):
                seen.append(record)

        h = _H(level=logging.DEBUG)
        sdk.addHandler(h)
        sdk.debug("body=%s", "It stops the recursion.")
        sdk.removeHandler(h)
        assert seen == []
    finally:
        logging.getLogger().setLevel(logging.WARNING)
        sdk.setLevel(logging.WARNING)
