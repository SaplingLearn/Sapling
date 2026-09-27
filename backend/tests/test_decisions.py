"""The typed decision seam (services/decisions.py, #640/#642, ADR 0027).

Hermetic: the flash_lite backend runs the REAL decision agent (prompt, output
schema, validation) on a pydantic-ai FunctionModel, and the Jev backend runs
the REAL client against an ``httpx.MockTransport`` serving payloads recorded
from the shapes in docs.typesafe.ai/api (no Jev key exists yet, so nothing
here was captured from a live call — see the ADR).

What is pinned, in the order the seam's contract states it:
1. never raises — every failure path ends in the question's safe default;
2. below the confidence floor the default wins, but the raw answer is kept;
3. every call emits exactly one ``decision.made`` event (none when off) and
   bills its tokens to ``llm_usage`` under the real provider.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from agents.decision import decision_agent
from services import decisions, events_service, llm_pricing, typesafe_client
from services.decisions import Choice, Score, YesNo

QUESTIONS = (
    YesNo(key="urgent", instructions="Is this urgent?", default=False,
          when_yes="Explicitly time-sensitive", when_no="No urgency expressed"),
    Choice(key="team", instructions="Which team handles this?",
           options=(("billing", "Payments"), ("technical", "Bugs"), ("sales", None)),
           default=None),
    Score(key="mood", instructions="How frustrated is the customer?",
          levels=(("calm", "Calm"), ("frustrated", "Frustrated"), ("angry", "Very angry")),
          default=None),
)

SECRET_TEXT = "my payouts have failed for three days SECRET-STATE-TEXT"
STATE = {"message": SECRET_TEXT}

# A recorded-shape Jev response (docs.typesafe.ai/api "Answer types").
JEV_OK = {
    "model": "jev-1.13.0",
    "answers": {
        "urgent": {"type": "noul", "noul": 0.95},
        "team": {
            "type": "choice", "choice": "technical",
            "probabilities": {"billing": 0.08, "technical": 0.85, "sales": 0.07},
            "confidence": 0.82,
        },
        "mood": {
            "type": "score", "score": 1.05,
            "legend": {"0": "Calm", "1": "Frustrated", "2": "Very angry"},
            "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05},
            "confidence": 0.92,
        },
    },
    "usage": {"input_tokens": 312, "output_tokens": 48},
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        decisions.BACKEND_ENV, decisions.SHADOW_ENV, decisions.FLOOR_ENV,
        decisions.TIMEOUT_ENV, decisions.JEV_TIMEOUT_ENV, "SAPLING_MODEL_MODE",
        typesafe_client.API_KEY_ENV, typesafe_client.BASE_URL_ENV, typesafe_client.MODEL_ENV,
    ):
        monkeypatch.delenv(var, raising=False)
    decisions._warned.clear()
    yield
    monkeypatch.setattr(typesafe_client, "_transport_override", None)


def _agent_model(answers=None, *, raises: Exception | None = None, delay: float = 0.0,
                 calls: list | None = None):
    """A FunctionModel standing in for flash-lite: emits `answers` through the
    decision agent's output tool, so the real DecisionOutput schema validates."""

    async def handler(messages, info):
        if calls is not None:
            calls.append(messages)
        if delay:
            await asyncio.sleep(delay)
        if raises is not None:
            raise raises
        return ModelResponse(parts=[
            ToolCallPart(tool_name=info.output_tools[0].name, args={"answers": answers or []})
        ])

    return FunctionModel(handler, model_name="function:decision")


GOOD_AGENT_ANSWERS = [
    {"key": "urgent", "value": "yes", "confidence": 0.8},
    {"key": "team", "value": "billing", "confidence": 0.7},
    {"key": "mood", "value": "angry", "confidence": 0.9},
]


def _jev_transport(handler_or_body, *, seen: list | None = None, status: int = 200):
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if callable(handler_or_body):
            return handler_or_body(request)
        if isinstance(handler_or_body, (bytes, str)):
            return httpx.Response(status, content=handler_or_body)
        return httpx.Response(status, json=handler_or_body)

    return httpx.MockTransport(handle)


def _use_jev(monkeypatch, transport, *, key="tsk_test"):
    monkeypatch.setenv(decisions.BACKEND_ENV, "jev")
    if key:
        monkeypatch.setenv(typesafe_client.API_KEY_ENV, key)
    monkeypatch.setattr(typesafe_client, "_transport_override", transport)


def _decide(**kw):
    return asyncio.run(decisions.decide(STATE, QUESTIONS, feature="test", user_id="u1",
                                        request_id="req-1", **kw))


def _decision_events(sink):
    events_service.flush_now()
    return [r for r in sink if r.get("event_type") == "decision.made"]


def _usage_rows(sink):
    events_service.flush_now()
    return [r for r in sink if "prompt_tokens" in r]


# ── Configuration ──────────────────────────────────────────────────────────


class TestConfiguration:
    def test_default_is_off(self):
        assert decisions.configured_backend() == "off"
        assert decisions.enabled() is False

    def test_off_decides_nothing_and_emits_nothing(self, sink):
        calls: list = []
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS, calls=calls)):
            result = _decide()
        assert calls == [], "the default (off) must not run any backend"
        assert result.backend == "none"
        assert {k: a.value for k, a in result.answers.items()} == {
            "urgent": False, "team": None, "mood": None,
        }
        assert all(a.defaulted for a in result.answers.values())
        assert _decision_events(sink) == []

    def test_function_mode_turns_the_seam_on_automatically(self, monkeypatch):
        monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
        assert decisions.configured_backend() == "function"
        # Any configured backend becomes the function backend: Jev is never
        # dialled from the deterministic lane.
        monkeypatch.setenv(decisions.BACKEND_ENV, "jev")
        assert decisions.configured_backend() == "function"

    def test_explicit_off_wins_in_function_mode(self, monkeypatch):
        monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
        monkeypatch.setenv(decisions.BACKEND_ENV, "off")
        assert decisions.configured_backend() == "off"

    def test_function_is_a_configurable_backend_in_function_mode(self, monkeypatch):
        """#672 review: the documented name must work — it used to fall
        through _read_backend's allow-list to 'off' and DISABLE the seam."""
        monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
        monkeypatch.setenv(decisions.BACKEND_ENV, "function")
        assert decisions.configured_backend() == "function"
        assert decisions.enabled() is True

    def test_a_typo_does_not_switch_function_mode_off(self, monkeypatch):
        """#672 review: in function mode only an explicit `off` disables the
        seam; a typo warned and returned `off`, silently killing the router
        in the one lane that checks it."""
        monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
        for value in ("flsh_lite", "Function ", "jevv"):
            monkeypatch.setenv(decisions.BACKEND_ENV, value)
            assert decisions.configured_backend() == "function", value
        for value in ("off", "OFF", "disabled", "false", "0", "none"):
            monkeypatch.setenv(decisions.BACKEND_ENV, value)
            assert decisions.configured_backend() == "off", value

    def test_function_outside_function_mode_is_off_never_a_live_model(self, monkeypatch):
        monkeypatch.setenv(decisions.BACKEND_ENV, "function")
        assert decisions.configured_backend() == "off"
        assert decisions.enabled() is False
        monkeypatch.setenv(decisions.BACKEND_ENV, "jev")
        monkeypatch.setenv(decisions.SHADOW_ENV, "function")
        assert decisions.shadow_backend() == "off"

    def test_unknown_backend_is_off(self, monkeypatch):
        monkeypatch.setenv(decisions.BACKEND_ENV, "gpt-9")
        assert decisions.configured_backend() == "off"

    def test_shadow_rules(self, monkeypatch):
        monkeypatch.setenv(decisions.SHADOW_ENV, "flash_lite")
        assert decisions.shadow_backend() == "off", "no shadow without a primary"
        monkeypatch.setenv(decisions.BACKEND_ENV, "flash_lite")
        assert decisions.shadow_backend() == "off", "shadow == primary is a no-op"
        monkeypatch.setenv(decisions.BACKEND_ENV, "jev")
        assert decisions.shadow_backend() == "flash_lite"
        monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
        assert decisions.shadow_backend() == "off", "never shadow in function mode"


# ── flash_lite backend ────────────────────────────────────────────────────


class TestFlashLiteBackend:
    @pytest.fixture(autouse=True)
    def _flash(self, monkeypatch):
        monkeypatch.setenv(decisions.BACKEND_ENV, "flash_lite")

    def test_answers_are_typed_and_applied(self, sink):
        calls: list = []
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS, calls=calls)):
            result = _decide()
        assert result.backend == "flash_lite" and result.requested == "flash_lite"
        assert result.fallback_reason is None
        assert result.value("urgent") is True
        assert result.value("team") == "billing"
        assert result.value("mood") == "angry"
        assert not any(a.defaulted for a in result.answers.values())
        # YesNo confidence is mapped onto P(yes) with |2p - 1| == confidence,
        # the same statistic Jev's answers are normalised to.
        urgent = result.answers["urgent"]
        assert urgent.probability == pytest.approx(0.9)
        assert abs(2 * urgent.probability - 1) == pytest.approx(urgent.confidence)
        # The prompt carried the state and every question spec.
        prompt = json.loads(calls[0][0].parts[-1].content)
        assert prompt["state"] == STATE
        assert [q["key"] for q in prompt["questions"]] == ["urgent", "team", "mood"]
        assert prompt["questions"][2]["levels"] == {
            "calm": "Calm", "frustrated": "Frustrated", "angry": "Very angry",
        }

    def test_below_floor_defaults_but_keeps_the_raw_answer(self, sink):
        answers = [
            {"key": "urgent", "value": "yes", "confidence": 0.3},
            {"key": "team", "value": "billing", "confidence": 0.49},
            {"key": "mood", "value": "angry", "confidence": 0.5},
        ]
        with decision_agent.override(model=_agent_model(answers)):
            result = _decide()
        urgent, team, mood = (result.answers[k] for k in ("urgent", "team", "mood"))
        assert (urgent.value, urgent.raw, urgent.defaulted) == (False, True, True)
        assert urgent.default_reason == "below_floor"
        assert (team.value, team.raw, team.default_reason) == (None, "billing", "below_floor")
        assert (mood.value, mood.defaulted) == ("angry", False), "the floor is inclusive"

    def test_floor_is_configurable(self, monkeypatch):
        monkeypatch.setenv(decisions.FLOOR_ENV, "0.95")
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS)):
            result = _decide()
        assert all(a.default_reason == "below_floor" for a in result.answers.values())

    def test_missing_invalid_and_unknown_keys_default_per_key(self, sink):
        answers = [
            {"key": "urgent", "value": "maybe", "confidence": 0.9},   # not yes/no
            {"key": "mood", "value": "furious", "confidence": 0.9},   # not a level
            {"key": "bogus", "value": "yes", "confidence": 0.9},      # not asked
            {"key": "team", "value": "sales", "confidence": 0.9},
            {"key": "team", "value": "billing", "confidence": 0.9},   # dup: first wins
        ]
        with decision_agent.override(model=_agent_model(answers)):
            result = _decide()
        assert result.answers["urgent"].default_reason == "invalid"
        assert result.answers["mood"].default_reason == "invalid"
        assert result.value("team") == "sales"
        assert "bogus" not in result.answers
        with decision_agent.override(model=_agent_model(answers[:1])):
            result = _decide()
        assert result.answers["team"].default_reason == "missing"

    def test_choice_and_score_match_case_and_whitespace_insensitively(self):
        answers = [
            {"key": "urgent", "value": " YES ", "confidence": 0.8},
            {"key": "team", "value": " Billing", "confidence": 0.9},
            {"key": "mood", "value": "Angry ", "confidence": 0.9},
        ]
        with decision_agent.override(model=_agent_model(answers)):
            result = _decide()
        assert not any(a.defaulted for a in result.answers.values()), result.answers
        # The CANONICAL declared key comes back, not the model's spelling.
        assert (result.value("urgent"), result.value("team"), result.value("mood")) == (
            True, "billing", "angry")
        assert result.answers["team"].raw == "billing"

    def test_usage_is_billed_under_the_decision_task(self, sink):
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS)):
            _decide()
        usage = _usage_rows(sink)
        assert len(usage) == 1
        assert usage[0]["task"] == "decision"
        assert usage[0]["feature"] == "test"
        assert usage[0]["provider"] == "gemini"

    def test_one_out_of_range_confidence_does_not_sink_the_output(self):
        """#672 review: ge/le on the schema made a single 1.02 fail validation
        for the WHOLE output. Now each key is clamped on its own."""
        from tests.test_tutor_router import DISRUPTIVE
        from services import tutor_router

        answers = [dict(a) for a in DISRUPTIVE]
        answers[2]["confidence"] = 1.02
        with decision_agent.override(model=_agent_model(answers)):
            result = asyncio.run(decisions.decide(
                {"m": "x"}, tutor_router.QUESTIONS, feature="test"))
        assert result.backend == "flash_lite", result.fallback_reason
        assert not any(a.defaulted for a in result.answers.values())
        assert result.answers["complexity"].confidence == 1.0
        assert len([a for a in result.answers.values() if a.confidence < 1.0]) == 4

    def test_usage_row_carries_the_callers_request_id(self, sink):
        """#672 review: outside a request (the router's detached task — no
        request contextvar) the row must still join to its turn."""
        from services.request_context import current_request_id

        assert current_request_id() is None, "precondition: no request scope here"
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS)):
            _decide()
        (row,) = _usage_rows(sink)
        assert row["request_id"] == "req-1"

    def test_an_off_list_answer_keeps_what_the_backend_said(self, sink):
        answers = [
            {"key": "urgent", "value": "maybe", "confidence": 0.9},
            {"key": "team", "value": "legal", "confidence": 0.8},
        ]
        with decision_agent.override(model=_agent_model(answers)):
            result = _decide()
        urgent, team = result.answers["urgent"], result.answers["team"]
        assert (urgent.value, urgent.raw, urgent.confidence) == (False, "maybe", 0.9)
        assert urgent.default_reason == "invalid"
        assert (team.value, team.raw, team.confidence) == (None, "legal", 0.8)
        # The event keeps the enum-only contract: an off-list value is free
        # model text, so it is masked there (the Answer keeps it).
        (event,) = _decision_events(sink)
        ev = event["payload"]["answers"]["urgent"]
        assert ev == {"value": False, "raw": decisions.INVALID_RAW, "confidence": 0.9,
                      "defaulted": "invalid"}
        assert "legal" not in json.dumps(event)

    def test_agent_error_degrades_to_defaults(self, sink):
        with decision_agent.override(model=_agent_model(raises=RuntimeError("boom"))):
            result = _decide()
        assert result.backend == "none"
        assert result.fallback_reason == "agent_RuntimeError"
        assert all(a.default_reason == "no_backend" for a in result.answers.values())
        assert result.value("urgent") is False
        assert len(_decision_events(sink)) == 1

    def test_agent_timeout_degrades_to_defaults(self, monkeypatch):
        monkeypatch.setenv(decisions.TIMEOUT_ENV, "50")
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS, delay=2.0)):
            result = _decide()
        assert result.fallback_reason == "agent_timeout"
        assert result.latency_ms < 1500

    def test_unregistered_function_handler_degrades(self, monkeypatch):
        """Function mode with no `decision` handler (every hermetic tutor test
        that flips the mode): a handled default, never an error in the turn."""
        from agents._providers import clear_function_handlers, model_for

        monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
        clear_function_handlers()
        with decision_agent.override(model=model_for("decision")):
            result = _decide()
        assert result.backend == "none"
        assert result.fallback_reason == "agent_UnregisteredHandlerError"

    def test_real_mode_without_a_stub_trips_the_guard_and_degrades(self):
        """Default real mode in the hermetic lane: the unstubbed Gemini call
        hits the #379 transport guard — which the seam absorbs."""
        from agents._providers import model_for

        with decision_agent.override(model=model_for("decision")):
            result = _decide()
        assert result.backend == "none"
        assert result.fallback_reason.startswith("agent_")

    def test_a_bug_inside_the_seam_still_does_not_raise(self, monkeypatch, sink):
        def broken(*a, **k):
            raise ZeroDivisionError("bug")

        monkeypatch.setattr(decisions, "_resolve", broken)
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS)):
            result = _decide()
        assert result.fallback_reason == "seam_ZeroDivisionError"
        assert result.value("urgent") is False


# ── Jev backend ────────────────────────────────────────────────────────────


class TestJevBackend:
    def test_request_shape_and_parsed_answers(self, monkeypatch, sink):
        seen: list[httpx.Request] = []
        _use_jev(monkeypatch, _jev_transport(JEV_OK, seen=seen))
        result = _decide()

        req = seen[0]
        assert req.method == "POST"
        assert str(req.url) == "https://api.typesafe.ai/v1/systemone"
        assert req.headers["authorization"] == "Bearer tsk_test"
        body = json.loads(req.content)
        assert body["model"] == "jev-1.13.0"
        assert body["state"] == STATE
        assert body["questions"] == {
            "urgent": {"type": "noul", "instructions": "Is this urgent?",
                       "criteria": {"true": "Explicitly time-sensitive",
                                    "false": "No urgency expressed"}},
            "team": {"type": "choice", "instructions": "Which team handles this?",
                     # A None description goes out as the option's own key:
                     # never a null criterion on the wire.
                     "criteria": {"billing": "Payments", "technical": "Bugs", "sales": "sales"}},
            "mood": {"type": "score", "instructions": "How frustrated is the customer?",
                     "criteria": ["Calm", "Frustrated", "Very angry"]},
        }

        assert result.backend == "jev" and result.fallback_reason is None
        assert result.model == "jev-1.13.0"
        urgent = result.answers["urgent"]
        assert urgent.value is True and urgent.probability == 0.95
        # noul carries no confidence on the wire; derived as |2p - 1|.
        assert urgent.confidence == pytest.approx(0.9)
        assert result.value("team") == "technical"
        assert result.answers["team"].confidence == 0.82
        # Score level = the distribution's mode, mapped back to OUR level keys.
        assert result.value("mood") == "frustrated"
        assert result.answers["mood"].probabilities == {
            "calm": 0.0, "frustrated": 0.95, "angry": 0.05,
        }

    def test_usage_is_billed_to_typesafe_at_jev_prices(self, monkeypatch, sink):
        _use_jev(monkeypatch, _jev_transport(JEV_OK))
        _decide()
        usage = _usage_rows(sink)
        assert len(usage) == 1
        row = usage[0]
        assert row["provider"] == "typesafe"
        assert row["model"] == "jev-1.13.0"
        assert row["task"] == "decision"
        assert (row["prompt_tokens"], row["completion_tokens"]) == (312, 48)
        # $0.042 / 1M input tokens, output free — exactly, at the column's
        # 10dp (the old 6dp stored 0.000013).
        assert row["cost_usd"] == 0.000013104

    def test_base_url_and_model_are_configurable(self, monkeypatch):
        seen: list[httpx.Request] = []
        _use_jev(monkeypatch, _jev_transport(JEV_OK, seen=seen))
        monkeypatch.setenv(typesafe_client.BASE_URL_ENV, "https://proxy.example/typesafe/")
        monkeypatch.setenv(typesafe_client.MODEL_ENV, "jev-latest")
        _decide()
        assert str(seen[0].url) == "https://proxy.example/typesafe/v1/systemone"
        assert json.loads(seen[0].content)["model"] == "jev-latest"

    def test_missing_key_falls_back_to_flash_lite_without_a_call(self, monkeypatch, sink):
        seen: list = []
        _use_jev(monkeypatch, _jev_transport(JEV_OK, seen=seen), key=None)
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS)):
            result = _decide()
        assert seen == [], "no key → no HTTP call"
        assert result.requested == "jev" and result.backend == "flash_lite"
        assert result.fallback_reason == "jev_no_key"
        assert result.value("team") == "billing"
        (event,) = _decision_events(sink)
        assert event["payload"]["fallback_reason"] == "jev_no_key"

    @pytest.mark.parametrize("failure, reason", [
        (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)), "jev_timeout"),
        (lambda r: (_ for _ in ()).throw(httpx.ConnectError("down", request=r)), "jev_transport"),
        (lambda r: httpx.Response(429, json={"error": "rate"}), "jev_http_429"),
        (lambda r: httpx.Response(529, json={"error": "overloaded"}), "jev_http_529"),
        (lambda r: httpx.Response(401, json={"error": "bad key"}), "jev_http_401"),
        (lambda r: httpx.Response(200, content=b"<html>not json</html>"), "jev_bad_payload"),
        (lambda r: httpx.Response(200, json={"model": "jev-1.13.0"}), "jev_bad_payload"),
        (lambda r: httpx.Response(200, json=["answers"]), "jev_bad_payload"),
    ])
    def test_failures_fall_back_to_flash_lite(self, monkeypatch, failure, reason):
        _use_jev(monkeypatch, _jev_transport(failure))
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS)):
            result = _decide()
        assert result.backend == "flash_lite"
        assert result.fallback_reason == reason
        assert result.value("mood") == "angry"

    def test_real_timeout_is_enforced(self, monkeypatch):
        async def slow_transport(request):
            await asyncio.sleep(2)
            return httpx.Response(200, json=JEV_OK)

        class SlowTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                return await slow_transport(request)

        _use_jev(monkeypatch, SlowTransport())
        monkeypatch.setenv(decisions.JEV_TIMEOUT_ENV, "50")
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS)):
            result = _decide()
        assert result.fallback_reason == "jev_timeout"
        assert result.latency_ms < 1500

    def test_jev_and_fallback_both_failing_ends_in_defaults(self, monkeypatch, sink):
        _use_jev(monkeypatch, _jev_transport({"error": "x"}, status=500))
        with decision_agent.override(model=_agent_model(raises=RuntimeError("down"))):
            result = _decide()
        assert result.backend == "none"
        assert result.fallback_reason == "jev_http_500+agent_RuntimeError"
        assert {k: a.value for k, a in result.answers.items()} == {
            "urgent": False, "team": None, "mood": None,
        }

    def test_malformed_single_answer_defaults_only_that_key(self, monkeypatch):
        body = json.loads(json.dumps(JEV_OK))
        body["answers"]["team"] = {"type": "choice", "choice": 7}
        del body["answers"]["mood"]
        _use_jev(monkeypatch, _jev_transport(body))
        result = _decide()
        assert result.backend == "jev"
        assert result.value("urgent") is True
        assert result.answers["team"].default_reason == "missing"
        assert result.answers["mood"].default_reason == "missing"

    def test_choice_null_criteria_are_never_serialized(self, monkeypatch):
        seen: list[httpx.Request] = []
        _use_jev(monkeypatch, _jev_transport(JEV_OK, seen=seen))
        _decide()
        raw = seen[0].content.decode()
        assert "null" not in raw, raw
        criteria = json.loads(raw)["questions"]["team"]["criteria"]
        assert list(criteria) == ["billing", "technical", "sales"], "option order kept"
        assert all(isinstance(v, str) and v for v in criteria.values())

    def test_jev_choice_is_matched_case_insensitively(self, monkeypatch):
        body = json.loads(json.dumps(JEV_OK))
        body["answers"]["team"]["choice"] = "Technical "
        _use_jev(monkeypatch, _jev_transport(body))
        result = _decide()
        assert result.value("team") == "technical"
        assert result.answers["team"].defaulted is False

    def test_a_200_with_no_readable_answer_degrades_to_flash_lite(self, monkeypatch, sink):
        """Jev answered, but in a shape we can't read for ANY key: that is a
        backend failure, not jev saying 'the defaults'."""
        body = {
            "model": "jev-1.13.0",
            "answers": {
                "urgent": {"type": "noul", "probability": 0.9},     # renamed field
                "team": {"type": "choice", "label": "billing"},
                "mood": "frustrated",
            },
            "usage": {"input_tokens": 300, "output_tokens": 10},
        }
        _use_jev(monkeypatch, _jev_transport(body))
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS)):
            result = _decide()
        assert result.requested == "jev" and result.backend == "flash_lite"
        assert result.fallback_reason == "jev_bad_answers"
        assert result.value("team") == "billing", "the fallback's answers, not defaults"
        (event,) = _decision_events(sink)
        assert event["payload"]["backend"] == "flash_lite"
        assert event["payload"]["fallback_reason"] == "jev_bad_answers"

    def test_an_unexpected_error_in_the_jev_path_degrades_to_flash_lite(
        self, monkeypatch, caplog,
    ):
        _use_jev(monkeypatch, _jev_transport(JEV_OK))

        def broken(q, ans):
            raise KeyError("surprise")

        monkeypatch.setattr(decisions, "_parse_jev_answer", broken)
        with (
            caplog.at_level("DEBUG", logger="sapling.decisions"),
            decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS)),
        ):
            result = _decide()
        assert result.backend == "flash_lite"
        assert result.fallback_reason == "jev_unexpected_KeyError"
        assert result.value("mood") == "angry"
        loud = [r for r in caplog.records if r.levelno >= 30]
        assert loud and all(r.exc_info is None for r in loud), (
            "WARN without a traceback — the e2e logscan oracle flags tracebacks")

    @pytest.mark.parametrize("probabilities, score, expected", [
        # An out-of-range key must not beat the real levels.
        ({"0": 0.1, "1": 0.2, "7": 0.7}, 1.05, "frustrated"),
        # Negative / non-numeric keys only: fall back to a valid `score`.
        ({"-1": 0.9, "high": 0.5}, 1.9, "angry"),
        # Nothing usable in the distribution, score still valid.
        ({"9": 1.0}, 0.2, "calm"),
    ])
    def test_score_ignores_bad_probability_keys(self, monkeypatch, probabilities, score, expected):
        body = json.loads(json.dumps(JEV_OK))
        body["answers"]["mood"] = {"type": "score", "score": score,
                                   "probabilities": probabilities, "confidence": 0.9}
        _use_jev(monkeypatch, _jev_transport(body))
        result = _decide()
        assert result.value("mood") == expected
        assert result.answers["mood"].defaulted is False

    def test_non_json_values_in_the_state_are_sent_as_strings(self, monkeypatch):
        """#672 review: httpx's json= has no default=str, so a datetime or
        UUID in a caller's state raised TypeError before the call left."""
        import datetime
        import uuid

        seen: list[httpx.Request] = []
        _use_jev(monkeypatch, _jev_transport(JEV_OK, seen=seen))
        when = datetime.datetime(2026, 9, 27, 5, 0, tzinfo=datetime.timezone.utc)
        ident = uuid.UUID("12345678-1234-5678-1234-567812345678")
        result = asyncio.run(decisions.decide(
            {"message": "m", "at": when, "id": ident}, QUESTIONS, feature="test"))
        assert result.backend == "jev" and result.fallback_reason is None
        assert seen[0].headers["content-type"] == "application/json"
        sent = json.loads(seen[0].content)["state"]
        assert sent == {"message": "m", "at": str(when), "id": str(ident)}

    def test_client_cache_releases_closed_loops_and_closes_on_shutdown(self, monkeypatch):
        """#672 review: a WeakKeyDictionary keyed on the loop can't expire an
        entry whose client points back at its loop. Closed loops are pruned
        on access; aclose_clients() closes the live loop's client."""
        import gc
        import weakref

        monkeypatch.setattr(typesafe_client, "_transport_override", None)
        monkeypatch.setattr(typesafe_client, "_clients", {})

        async def get():
            return typesafe_client._client()

        old = asyncio.new_event_loop()
        old_client = old.run_until_complete(get())
        old.close()
        old_ref = weakref.ref(old)
        new = asyncio.new_event_loop()
        try:
            new_client = new.run_until_complete(get())
            assert new_client is not old_client
            assert new.run_until_complete(get()) is new_client, "reused per loop"
            live_loops = [ref() for ref, _ in typesafe_client._clients.values()]
            assert live_loops == [new], "the closed loop's entry was pruned"
            del old, old_client
            gc.collect()
            assert old_ref() is None, "nothing pins the closed loop"
            new.run_until_complete(typesafe_client.aclose_clients())
            assert new_client.is_closed
            assert typesafe_client._clients == {}
        finally:
            new.close()

    def test_uncertain_noul_falls_under_the_floor(self, monkeypatch):
        body = json.loads(json.dumps(JEV_OK))
        body["answers"]["urgent"] = {"type": "noul", "noul": 0.6}  # |2p-1| = 0.2
        _use_jev(monkeypatch, _jev_transport(body))
        result = _decide()
        urgent = result.answers["urgent"]
        assert (urgent.value, urgent.raw, urgent.default_reason) == (False, True, "below_floor")

    def test_oversized_state_trims_truncatable_history_oldest_first(self, monkeypatch):
        seen: list[httpx.Request] = []
        _use_jev(monkeypatch, _jev_transport(JEV_OK, seen=seen))
        # ~40k tokens of history under the pessimistic 3-chars/token estimate.
        history = [f"turn-{i} " + "x" * 3000 for i in range(40)]
        state = {"message": "latest", "history": history}
        result = asyncio.run(decisions.decide(
            state, QUESTIONS, feature="test", truncatable=("history",),
        ))
        assert result.backend == "jev"
        sent = json.loads(seen[0].content)["state"]
        assert sent["message"] == "latest"
        assert 0 < len(sent["history"]) < 40
        assert sent["history"][-1].startswith("turn-39"), "newest turns are kept"
        assert state["history"] == history, "the caller's state is not mutated"
        assert typesafe_client.estimate_tokens(json.dumps(sent)) <= typesafe_client.STATE_TOKEN_BUDGET

    def test_fit_state_matches_the_reference_and_serializes_each_item_once(self, monkeypatch):
        """#672 review: the trim loop re-serialized the whole state per
        dropped item (O(n^2) on a long tail). The linear version must pick
        exactly what the old loop picked, dumping the full state at most once."""
        def reference(state, truncatable, qtok):
            budget = (typesafe_client.STATE_TOKEN_BUDGET - qtok
                      - decisions._JEV_BUDGET_MARGIN)

            def size(x):
                return typesafe_client.estimate_tokens(
                    json.dumps(x, ensure_ascii=False, default=str))

            if size(state) <= budget:
                return state
            trimmed = {k: (list(v) if k in truncatable and isinstance(v, list) else v)
                       for k, v in state.items()}
            while size(trimmed) > budget:
                for key in truncatable:
                    if isinstance(trimmed.get(key), list) and trimmed[key]:
                        trimmed[key].pop(0)
                        break
                else:
                    return "over"
            return trimmed

        cases = [
            {"message": "latest", "history": [f"t{i} " + "x" * 3000 for i in range(40)]},
            {"message": "ü" * 20, "a": [{"s": "é" * 2500, "n": i} for i in range(30)],
             "b": ["y" * 4000 for _ in range(20)], "tail": 1},
            {"message": "fits", "history": ["short"] * 3},
            {"message": "z" * 100_000, "history": ["h"] * 5},
        ]
        for case in cases:
            for qtok in (0, 700):
                want = reference(case, ("a", "b", "history"), qtok)
                try:
                    got = decisions._fit_state(case, ("a", "b", "history"), qtok)
                except decisions._BackendFailed:
                    got = "over"
                assert got == want

        calls = []
        real_dumps = json.dumps

        def counting(obj, *a, **k):
            if isinstance(obj, dict) and "history" in obj:
                calls.append(1)
            return real_dumps(obj, *a, **k)

        monkeypatch.setattr(decisions.json, "dumps", counting)
        big = {"message": "m", "history": ["x" * 400 for _ in range(2000)]}
        decisions._fit_state(big, ("history",), 0)
        assert len(calls) <= 1, f"state re-serialized {len(calls)} times"

    def test_oversized_untruncatable_state_goes_straight_to_defaults(self, monkeypatch):
        """#672 review: a state too big for Jev is too big for the decision
        agent's WORKER_LIMITS too — falling back would only bill a
        UsageLimitExceeded. Neither backend is called."""
        seen: list = []
        calls: list = []
        _use_jev(monkeypatch, _jev_transport(JEV_OK, seen=seen))
        state = {"message": "y" * 150_000}
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS, calls=calls)):
            result = asyncio.run(decisions.decide(state, QUESTIONS, feature="test"))
        assert seen == [] and calls == []
        assert result.backend == "none"
        assert result.fallback_reason == "jev_state_over_budget"
        assert all(a.default_reason == "no_backend" for a in result.answers.values())

    def test_over_jev_budget_still_falls_back_when_the_agent_can_fit_it(self, monkeypatch):
        _use_jev(monkeypatch, _jev_transport(JEV_OK))
        monkeypatch.setattr(decisions, "_agent_budget_fits", lambda state, qs: True)
        state = {"message": "y" * 150_000}
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS)):
            result = asyncio.run(decisions.decide(state, QUESTIONS, feature="test"))
        assert result.backend == "flash_lite"
        assert result.fallback_reason == "jev_state_over_budget"

    def test_agent_budget_threshold(self):
        from agents import WORKER_LIMITS

        per_request = WORKER_LIMITS.total_tokens_limit // WORKER_LIMITS.request_limit
        small = {"message": "hi"}
        # ~3 chars/token: a prompt of this many chars is past one request's share.
        big = {"message": "y" * (per_request * 3)}
        assert decisions._agent_budget_fits(small, QUESTIONS) is True
        assert decisions._agent_budget_fits(big, QUESTIONS) is False

    def test_fit_state_estimates_from_lengths_without_building_strings(self, monkeypatch):
        """#672 review: fits() built a throwaway "x" * chars string per check."""
        def no_strings(text):
            raise AssertionError("_fit_state must use tokens_for_chars, not estimate_tokens")

        monkeypatch.setattr(typesafe_client, "estimate_tokens", no_strings)
        state = {"message": "m", "history": ["x" * 3000 for _ in range(40)]}
        trimmed = decisions._fit_state(state, ("history",), 0)
        assert 0 < len(trimmed["history"]) < 40
        assert typesafe_client.tokens_for_chars(len("abcdefg")) == 7 // 3 + 1


# ── Shadow mode + the event ───────────────────────────────────────────────


class TestShadowAndEvent:
    def test_shadow_runs_both_and_logs_agreement(self, monkeypatch, sink):
        _use_jev(monkeypatch, _jev_transport(JEV_OK))
        monkeypatch.setenv(decisions.SHADOW_ENV, "flash_lite")
        shadow_answers = [
            {"key": "urgent", "value": "yes", "confidence": 0.9},     # agrees
            {"key": "team", "value": "billing", "confidence": 0.9},   # disagrees
            # mood missing → agreement unknown, not "disagree"
        ]
        with decision_agent.override(model=_agent_model(shadow_answers)):
            result = _decide()
        assert result.backend == "jev", "the primary's answer is what the caller gets"
        assert result.value("team") == "technical"
        (event,) = _decision_events(sink)
        shadow = event["payload"]["shadow"]
        assert shadow["backend"] == "flash_lite"
        assert shadow["agree"] == {"urgent": True, "team": False, "mood": None}
        # Both backends' tokens are billed — the shadow costs real money.
        assert {r["provider"] for r in _usage_rows(sink)} == {"typesafe", "gemini"}

    def test_primary_degraded_onto_the_shadow_backend_is_not_compared(
        self, monkeypatch, sink,
    ):
        """Jev primary fails and would fall back to flash_lite — the shadow's
        own backend. Comparing flash_lite with itself would inflate agreement
        and bill Gemini twice: the shadow's answer serves instead, once."""
        _use_jev(monkeypatch, _jev_transport({"e": 1}, status=503))
        monkeypatch.setenv(decisions.SHADOW_ENV, "flash_lite")
        calls: list = []
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS, calls=calls)):
            result = _decide()
        assert len(calls) == 1, "flash_lite ran once, not as fallback AND shadow"
        assert result.requested == "jev" and result.backend == "flash_lite"
        assert result.fallback_reason == "jev_http_503"
        assert result.value("team") == "billing"
        (event,) = _decision_events(sink)
        shadow = event["payload"]["shadow"]
        assert shadow["fallback_reason"] == "shadow_same_as_served"
        assert shadow["agree"] is None
        assert [r["provider"] for r in _usage_rows(sink)] == ["gemini"]

    def test_an_off_list_shadow_answer_disagrees(self, monkeypatch, sink):
        _use_jev(monkeypatch, _jev_transport(JEV_OK))
        monkeypatch.setenv(decisions.SHADOW_ENV, "flash_lite")
        shadow_answers = [
            {"key": "urgent", "value": "perhaps", "confidence": 0.9},   # off-list
            {"key": "team", "value": "technical", "confidence": 0.9},   # agrees
        ]
        with decision_agent.override(model=_agent_model(shadow_answers)):
            _decide()
        (event,) = _decision_events(sink)
        assert event["payload"]["shadow"]["agree"] == {
            "urgent": False, "team": True, "mood": None,
        }

    def test_degraded_primary_with_a_failing_shadow_ends_in_defaults(self, monkeypatch):
        _use_jev(monkeypatch, _jev_transport({"e": 1}, status=503))
        monkeypatch.setenv(decisions.SHADOW_ENV, "flash_lite")
        with decision_agent.override(model=_agent_model(raises=RuntimeError("down"))):
            result = _decide()
        assert result.backend == "none"
        assert result.fallback_reason == "jev_http_503+agent_RuntimeError"
        assert result.value("urgent") is False

    def test_a_doomed_flash_lite_shadow_is_skipped(self, monkeypatch, sink):
        """#672 review: with the primary over Jev's budget, the flash_lite
        shadow can't fit WORKER_LIMITS either — running it only bills a
        UsageLimitExceeded. Skipped, recorded, no agreement."""
        seen: list = []
        calls: list = []
        _use_jev(monkeypatch, _jev_transport(JEV_OK, seen=seen))
        monkeypatch.setenv(decisions.SHADOW_ENV, "flash_lite")
        state = {"message": "y" * 150_000}
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS, calls=calls)):
            result = asyncio.run(decisions.decide(state, QUESTIONS, feature="test"))
        assert seen == [] and calls == [], "neither Jev nor the agent was called"
        assert result.fallback_reason == "jev_state_over_budget"
        (event,) = _decision_events(sink)
        shadow = event["payload"]["shadow"]
        assert shadow["fallback_reason"] == "shadow_over_budget"
        assert shadow["agree"] is None
        assert _usage_rows(sink) == []

    def test_shadow_never_falls_back(self, monkeypatch, sink):
        """A failing Jev SHADOW must not quietly run flash_lite a second time."""
        monkeypatch.setenv(decisions.BACKEND_ENV, "flash_lite")
        monkeypatch.setenv(decisions.SHADOW_ENV, "jev")
        monkeypatch.setenv(typesafe_client.API_KEY_ENV, "tsk_test")
        monkeypatch.setattr(typesafe_client, "_transport_override",
                            _jev_transport({"e": 1}, status=503))
        calls: list = []
        with decision_agent.override(model=_agent_model(GOOD_AGENT_ANSWERS, calls=calls)):
            _decide()
        assert len(calls) == 1
        (event,) = _decision_events(sink)
        assert event["payload"]["shadow"]["backend"] == "none"
        assert event["payload"]["shadow"]["fallback_reason"] == "jev_http_503"

    def test_caller_extras_cannot_override_core_fields(self, monkeypatch, sink, caplog):
        """#672 review: extras were applied AFTER the core fields, so a caller
        extra could rewrite who answered and what."""
        _use_jev(monkeypatch, _jev_transport(JEV_OK))
        forged = {"backend": "forged", "model": "forged", "answers": {},
                  "fallback_reason": "forged", "requested": "forged",
                  "session_id": "s1"}
        with caplog.at_level("WARNING", logger="sapling.decisions"):
            asyncio.run(decisions.decide(STATE, QUESTIONS, feature="test",
                                         event_extra=forged))
        (event,) = _decision_events(sink)
        p = event["payload"]
        assert (p["backend"], p["model"], p["requested"]) == ("jev", "jev-1.13.0", "jev")
        assert p["fallback_reason"] is None
        assert set(p["answers"]) == {"urgent", "team", "mood"}
        assert p["session_id"] == "s1", "non-colliding extras still ride along"
        assert any("collides with a core field" in r.getMessage() for r in caplog.records)

    def test_event_payload_is_enum_only_and_never_carries_state(self, monkeypatch, sink):
        _use_jev(monkeypatch, _jev_transport(JEV_OK))
        asyncio.run(decisions.decide(
            STATE, QUESTIONS, feature="test", user_id="u1", request_id="req-1",
            event_extra={"session_id": "s1"},
        ))
        (event,) = _decision_events(sink)
        assert event["category"] == "usage"
        assert event["event_type"] in events_service.EVENT_TAXONOMY
        assert event["user_id"] == "u1" and event["request_id"] == "req-1"
        p = event["payload"]
        assert p["feature"] == "test" and p["session_id"] == "s1"
        assert p["backend"] == "jev" and p["model"] == "jev-1.13.0"
        assert isinstance(p["latency_ms"], int)
        assert p["answers"]["team"] == {"value": "technical", "raw": "technical",
                                        "confidence": 0.82}
        assert "SECRET-STATE-TEXT" not in json.dumps(event)
        assert event["content_fp"] is None


def test_jev_is_priced_input_only():
    assert llm_pricing.cost_usd("jev-1.13.0", 1_000_000, 1_000_000) == pytest.approx(0.042)
    assert llm_pricing.cost_usd("jev-latest", 1_000_000, 0) == pytest.approx(0.042)
