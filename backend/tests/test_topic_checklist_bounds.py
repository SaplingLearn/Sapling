"""Real SDK/FunctionModel limits and independent dispatch evidence, offline."""
import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from pydantic_ai import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from agents.topic_checklist import (
    CHECKLIST_LIMITS, CHECKLIST_MAX_OUTPUT_TOKENS, CHECKLIST_OUTPUT_RETRIES,
    CHECKLIST_REQUEST_TIMEOUT_SECONDS, topic_checklist_agent,
)
from agents.topic_checklist_model import wrap_topic_checklist_model
from services import checklist_budget
from services import topic_checklist_service as svc

PAYLOAD = {"sources": [{"id": "course-description", "text": "Functions."}], "assessments": []}


def output(*, source="course-description", count=1):
    return {"topics": [{
        "name": f"Concept {index}", "description": "Inputs, outputs and function composition.",
        "source_ids": [source], "importance": 0.5,
    } for index in range(count)]}


def response(info, value):
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, value)],
                         usage=RequestUsage(input_tokens=41, output_tokens=13))


@pytest.fixture
def reservation():
    return checklist_budget.Reservation(uuid4(), "owner", "enrollment", "a" * 64, 1)


def run(handler, reservation):
    with topic_checklist_agent.override(model=wrap_topic_checklist_model(FunctionModel(handler))):
        return asyncio.run(svc._generate(PAYLOAD, "owner", reservation))


def test_native_settings_reach_actual_function_model_and_all_sixty_concise_topics_remain_valid(reservation):
    observed = []
    async def handler(_messages, info):
        observed.append(info.model_settings)
        return response(info, output(count=60))
    result = run(handler, reservation)
    assert result.error is None and len(result.outline.topics) == 60
    assert observed == [{"max_tokens": CHECKLIST_MAX_OUTPUT_TOKENS, "timeout": CHECKLIST_REQUEST_TIMEOUT_SECONDS}]
    assert CHECKLIST_MAX_OUTPUT_TOKENS == 8192 and CHECKLIST_REQUEST_TIMEOUT_SECONDS == 60
    assert svc.GENERATION_TIMEOUT_SECONDS == 60
    # Structural compatibility, not a Google tokenizer/invoice guarantee.
    assert len(json.dumps(result.outline.model_dump())) < CHECKLIST_MAX_OUTPUT_TOKENS * 3
    assert result.usage.requests == result.dispatches.dispatched == len(result.dispatches.responses) == 1
    assert result.dispatches.nonbillable_test


def test_invalid_references_exhaust_three_actual_attempts_and_preserve_usage(reservation):
    calls = []
    async def handler(_messages, info):
        calls.append(info.model_settings)
        return response(info, output(source="not-owned-evidence"))
    result = run(handler, reservation)
    assert isinstance(result.error, UnexpectedModelBehavior)
    assert len(calls) == 1 + CHECKLIST_OUTPUT_RETRIES == CHECKLIST_LIMITS.request_limit == 3
    assert CHECKLIST_LIMITS.tool_calls_limit == 0
    assert CHECKLIST_LIMITS.total_tokens_limit == CHECKLIST_LIMITS.input_tokens_limit == 50_000
    assert CHECKLIST_LIMITS.count_tokens_before_request is True
    assert CHECKLIST_LIMITS.output_tokens_limit == 3 * CHECKLIST_MAX_OUTPUT_TOKENS
    assert result.usage.requests == result.dispatches.dispatched == len(result.dispatches.responses) == 3
    assert result.usage.input_tokens == 123 and result.usage.output_tokens == 39


def test_success_after_validation_retry_has_one_aggregate_usage_and_all_responses(reservation):
    calls = []
    async def handler(_messages, info):
        calls.append(info.model_settings)
        return response(info, output(source="invalid" if len(calls) == 1 else "course-description"))
    result = run(handler, reservation)
    assert result.error is None and result.outline.topics
    assert len(calls) == result.usage.requests == result.dispatches.dispatched == len(result.dispatches.responses) == 2
    assert result.usage.output_tokens == 26


def test_reported_token_backstop_rejects_overshoot_without_losing_known_usage(reservation):
    calls = []
    async def handler(_messages, info):
        calls.append(info)
        result = response(info, output())
        result.usage.output_tokens = CHECKLIST_LIMITS.output_tokens_limit + 1
        return result
    result = run(handler, reservation)
    assert isinstance(result.error, UsageLimitExceeded)
    assert len(calls) == result.dispatches.dispatched == len(result.dispatches.responses) == 1
    assert result.usage.output_tokens == CHECKLIST_LIMITS.output_tokens_limit + 1


@pytest.mark.parametrize("after_response", [False, True])
def test_outer_timeout_tracks_unanswered_dispatch_independently(monkeypatch, reservation, after_response):
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
    result = run(handler, reservation)
    assert isinstance(result.error, TimeoutError)
    assert len(calls) == result.dispatches.dispatched == 1 + int(after_response)
    assert cancellations == [True]
    assert result.usage.requests == len(result.dispatches.responses) == int(after_response)
    assert result.usage.input_tokens == (41 if after_response else 0)
    assert result.usage.output_tokens == (13 if after_response else 0)


@pytest.mark.parametrize("after_response", [False, True])
def test_cancellation_preserves_identity_and_never_retries(reservation, after_response):
    original = asyncio.CancelledError("caller cancelled")
    calls = []
    async def handler(_messages, info):
        calls.append(info)
        if after_response and len(calls) == 1:
            return response(info, output(source="invalid"))
        raise original
    result = run(handler, reservation)
    assert result.error is original
    assert len(calls) == result.dispatches.dispatched == 1 + int(after_response)
    assert result.usage.requests == len(result.dispatches.responses) == int(after_response)


def test_native_request_timeout_is_not_validation_retry_or_synthetic_usage(reservation):
    original = httpx.ReadTimeout("request timed out")
    calls = []
    async def handler(_messages, info):
        calls.append(info)
        raise original
    result = run(handler, reservation)
    assert result.error is original and len(calls) == result.dispatches.dispatched == 1
    assert result.usage.requests == len(result.dispatches.responses) == 0
    assert result.usage.input_tokens == result.usage.output_tokens == 0


def test_accounting_failure_cannot_replace_original_cancellation(monkeypatch, reservation):
    original = asyncio.CancelledError("caller cancelled")
    async def handler(_messages, info):
        raise original
    result = run(handler, reservation)
    def unavailable(*args, **kwargs):
        raise RuntimeError("settlement unavailable")
    monkeypatch.setattr(checklist_budget, "reconcile", unavailable)
    with pytest.raises(asyncio.CancelledError) as error:
        svc._finish_generation(result, PAYLOAD)
    assert error.value is original and result.dispatches.dispatched == 1
