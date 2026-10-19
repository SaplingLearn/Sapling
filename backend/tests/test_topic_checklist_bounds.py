"""Real agent/FunctionModel bounds, without network, real providers or database."""

import asyncio
import json

import httpx
import pytest
from pydantic_ai import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from agents.topic_checklist import (
    CHECKLIST_LIMITS,
    CHECKLIST_MAX_OUTPUT_TOKENS,
    CHECKLIST_OUTPUT_RETRIES,
    CHECKLIST_REQUEST_TIMEOUT_SECONDS,
    topic_checklist_agent,
)
from agents.topic_checklist_model import wrap_topic_checklist_model
from services import topic_checklist_service as svc

PAYLOAD = {"sources": [{"id": "course-description", "text": "Functions."}], "assessments": []}


def output(*, source="course-description", count=1):
    return {"topics": [{
        "name": f"Concept {index}", "description": "Inputs, outputs and function composition.",
        "source_ids": [source], "importance": 0.5,
    } for index in range(count)]}


def response(info, value):
    return ModelResponse(
        parts=[ToolCallPart(info.output_tools[0].name, value)],
        usage=RequestUsage(input_tokens=41, output_tokens=13),
    )


@pytest.fixture
def recorded(monkeypatch):
    rows = []

    def record(result, **metadata):
        usage = result.usage()
        rows.append({"requests": usage.requests, "input_tokens": usage.input_tokens,
                     "output_tokens": usage.output_tokens, "metadata": metadata})
        return result

    monkeypatch.setattr(svc, "record_agent_usage", record)
    return rows


def test_native_settings_reach_actual_function_model_and_all_sixty_concise_topics_remain_valid(recorded):
    observed = []

    async def handler(_messages, info):
        observed.append(info.model_settings)
        return response(info, output(count=60))

    with topic_checklist_agent.override(model=wrap_topic_checklist_model(FunctionModel(handler))):
        result = asyncio.run(svc._generate(PAYLOAD, "owner"))
    assert len(result.topics) == 60
    assert observed == [{"max_tokens": CHECKLIST_MAX_OUTPUT_TOKENS, "timeout": CHECKLIST_REQUEST_TIMEOUT_SECONDS}]
    assert CHECKLIST_MAX_OUTPUT_TOKENS == 8192 and CHECKLIST_REQUEST_TIMEOUT_SECONDS == 60
    assert svc.GENERATION_TIMEOUT_SECONDS == 60  # shared whole-run deadline, not 60s per retry
    # Structural compatibility, not a claim that Google's tokenizer fits every
    # maximal schema instance in this completion budget (FunctionModel is local).
    assert len(json.dumps(result.model_dump())) < CHECKLIST_MAX_OUTPUT_TOKENS * 3
    assert len(recorded) == 1 and recorded[0]["requests"] == 1
    assert recorded[0]["metadata"] == {"feature": "topic_checklist", "task": "topic_checklist", "user_id": "owner"}


def test_invalid_references_exhaust_three_actual_attempts_and_record_known_usage_once(recorded, caplog):
    calls = []

    async def handler(_messages, info):
        calls.append(info.model_settings)
        return response(info, output(source="not-owned-evidence"))

    with topic_checklist_agent.override(model=wrap_topic_checklist_model(FunctionModel(handler))):
        with pytest.raises(UnexpectedModelBehavior):
            asyncio.run(svc._generate(PAYLOAD, "owner"))
    assert len(calls) == 1 + CHECKLIST_OUTPUT_RETRIES == CHECKLIST_LIMITS.request_limit == 3
    assert CHECKLIST_LIMITS.tool_calls_limit == 0
    assert CHECKLIST_LIMITS.total_tokens_limit == 50_000
    assert CHECKLIST_LIMITS.input_tokens_limit == 50_000
    assert CHECKLIST_LIMITS.count_tokens_before_request is True
    assert CHECKLIST_LIMITS.output_tokens_limit == 3 * CHECKLIST_MAX_OUTPUT_TOKENS
    assert len(recorded) == 1
    assert recorded[0]["requests"] == 3
    assert recorded[0]["input_tokens"] == 123 and recorded[0]["output_tokens"] == 39
    assert "In-flight provider usage may be incomplete" in caplog.text


def test_success_after_validation_retry_is_one_aggregate_bill(recorded):
    calls = []

    async def handler(_messages, info):
        calls.append(info.model_settings)
        return response(info, output(source="invalid" if len(calls) == 1 else "course-description"))

    with topic_checklist_agent.override(model=wrap_topic_checklist_model(FunctionModel(handler))):
        assert asyncio.run(svc._generate(PAYLOAD, "owner")).topics
    assert len(calls) == 2 and len(recorded) == 1
    assert recorded[0]["requests"] == 2 and recorded[0]["output_tokens"] == 26


def test_reported_token_backstop_still_rejects_overshoot_without_retry_or_losing_known_usage(recorded):
    calls = []

    async def handler(_messages, info):
        calls.append(info)
        result = response(info, output())
        result.usage.output_tokens = CHECKLIST_LIMITS.output_tokens_limit + 1
        return result

    with topic_checklist_agent.override(model=wrap_topic_checklist_model(FunctionModel(handler))):
        with pytest.raises(UsageLimitExceeded):
            asyncio.run(svc._generate(PAYLOAD, "owner"))
    assert len(calls) == len(recorded) == 1
    assert recorded[0]["output_tokens"] == CHECKLIST_LIMITS.output_tokens_limit + 1


@pytest.mark.parametrize("after_response", [False, True])
def test_outer_timeout_cancels_cooperative_request_and_keeps_only_reported_usage(monkeypatch, recorded, after_response):
    calls, cancellations = [], []
    monkeypatch.setattr(svc, "GENERATION_TIMEOUT_SECONDS", 0.02)

    async def handler(_messages, info):
        calls.append(info)
        if after_response and len(calls) == 1:
            return response(info, output(source="invalid"))
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellations.append(True)
            raise

    with topic_checklist_agent.override(model=wrap_topic_checklist_model(FunctionModel(handler))):
        with pytest.raises(TimeoutError):
            asyncio.run(svc._generate(PAYLOAD, "owner"))
    assert len(calls) == 1 + int(after_response) and cancellations == [True]
    # RunUsage includes answered requests, not the cancelled in-flight call.
    # Never fabricate that call's unknown token or billed-request usage.
    assert len(recorded) == 1 and recorded[0]["requests"] == int(after_response)
    assert recorded[0]["input_tokens"] == (41 if after_response else 0)
    assert recorded[0]["output_tokens"] == (13 if after_response else 0)


@pytest.mark.parametrize("after_response", [False, True])
@pytest.mark.parametrize("broken_hook", [False, True])
def test_cancellation_preserves_identity_and_never_retries_or_double_records(monkeypatch, recorded, after_response, broken_hook):
    original = asyncio.CancelledError("caller cancelled")
    calls = []
    if broken_hook:
        def failed_record(result, **_metadata):
            recorded.append({"requests": result.usage().requests})
            raise RuntimeError("instrumentation failed")
        monkeypatch.setattr(svc, "record_agent_usage", failed_record)

    async def handler(_messages, info):
        calls.append(info)
        if after_response and len(calls) == 1:
            return response(info, output(source="invalid"))
        raise original

    with topic_checklist_agent.override(model=wrap_topic_checklist_model(FunctionModel(handler))):
        with pytest.raises(asyncio.CancelledError) as error:
            asyncio.run(svc._generate(PAYLOAD, "owner"))
    assert error.value is original
    assert len(calls) == 1 + int(after_response)
    assert len(recorded) == 1 and recorded[0]["requests"] == int(after_response)


def test_native_request_timeout_is_not_a_validation_retry_or_synthetic_usage(recorded):
    original = httpx.ReadTimeout("request timed out")
    calls = []

    async def handler(_messages, info):
        calls.append(info)
        raise original

    with topic_checklist_agent.override(model=wrap_topic_checklist_model(FunctionModel(handler))):
        with pytest.raises(httpx.ReadTimeout) as error:
            asyncio.run(svc._generate(PAYLOAD, "owner"))
    assert error.value is original and len(calls) == 1 and len(recorded) == 1
    assert recorded[0]["input_tokens"] == recorded[0]["output_tokens"] == 0


def test_successful_output_is_not_lost_or_billed_twice_when_recording_hook_fails(monkeypatch):
    calls, records = [], []

    async def handler(_messages, info):
        calls.append(info)
        return response(info, output())

    def failed_record(result, **_metadata):
        records.append(result.usage().requests)
        raise RuntimeError("instrumentation failed")

    monkeypatch.setattr(svc, "record_agent_usage", failed_record)
    with topic_checklist_agent.override(model=wrap_topic_checklist_model(FunctionModel(handler))):
        assert asyncio.run(svc._generate(PAYLOAD, "owner")).topics
    assert len(calls) == 1 and records == [1]
