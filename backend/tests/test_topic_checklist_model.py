"""Exercise pinned Google serialization over an in-process HTTP transport only."""

import asyncio
from contextlib import asynccontextmanager
import json
from types import MethodType

from google.genai import _api_client
import httpx
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import (
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    UserError,
)
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.test import TestModel as LocalTestModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.usage import UsageLimits
import pytest

from agents.topic_checklist_model import wrap_topic_checklist_model

# Capture before autouse egress guards. Restore ONLY these methods on the one
# SDK instance whose httpx client has MockTransport; all other egress stays shut.
_SDK_ASYNC_METHODS = {
    name: getattr(_api_client.BaseApiClient, name)
    for name in ("async_request", "_async_request", "_async_request_once")
}
SETTINGS = {"max_tokens": 8192, "timeout": 60.0}


class Outline(BaseModel):
    answer: str


def limits(**changes):
    return UsageLimits(
        **(
            {
                "request_limit": 3,
                "tool_calls_limit": 0,
                "input_tokens_limit": 50_000,
                "total_tokens_limit": 50_000,
                "count_tokens_before_request": True,
            }
            | changes
        )
    )


@asynccontextmanager
async def transport_model(handler):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = GoogleProvider(api_key="test-key-never-sent", http_client=http)
        api = provider.client._api_client
        for name, method in _SDK_ASYNC_METHODS.items():
            setattr(api, name, MethodType(method, api))
        try:
            yield wrap_topic_checklist_model(GoogleModel("gemini-2.5-flash", provider=provider))
        finally:
            await provider.client.aio.aclose()
            provider.client.close()


def test_oversized_full_count_blocks_before_paid_generation():
    seen = []

    def handle(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"totalTokens": 50_001})

    async def run():
        async with transport_model(handle) as model:
            agent = Agent(model, output_type=Outline, model_settings=SETTINGS)
            with pytest.raises(UsageLimitExceeded, match="input_tokens_limit"):
                await agent.run("evidence", usage_limits=limits())

    asyncio.run(run())
    assert len(seen) == 1 and seen[0].endswith(":countTokens")


@pytest.mark.parametrize(
    "count", ["missing", None, 0, -1, 1.5, float("nan"), float("inf"), "not-a-count"]
)
def test_invalid_native_count_never_generates(count):
    paths = []

    def handle(request):
        paths.append(request.url.path)
        # Emit raw JSON here so NaN/infinity reach the SDK parser rather than
        # failing in httpx's test-response encoder before the counter reads it.
        body = {} if count == "missing" else {"totalTokens": count}
        return httpx.Response(
            200, content=json.dumps(body), headers={"content-type": "application/json"}
        )

    async def run():
        async with transport_model(handle) as model:
            with pytest.raises((UnexpectedModelBehavior, ValueError)):
                await Agent(model, model_settings=SETTINGS).run("evidence", usage_limits=limits())

    asyncio.run(run())
    assert len(paths) == 1 and paths[0].endswith(":countTokens")


def test_function_mode_is_explicit_nonbillable_zero_precount_but_keeps_real_returned_usage():
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.usage import RequestUsage

    model = wrap_topic_checklist_model(
        FunctionModel(
            lambda _messages, _info: ModelResponse(
                parts=[TextPart("local")],
                usage=RequestUsage(input_tokens=4, output_tokens=2),
            )
        )
    )
    assert wrap_topic_checklist_model(model) is model
    result = asyncio.run(Agent(model).run("fixture", usage_limits=limits()))
    assert result.output == "local"
    assert result.usage.requests == 1 and result.usage.total_tokens == 6


def test_unknown_real_provider_fails_closed_instead_of_zero_or_content_only_count():
    model = wrap_topic_checklist_model(LocalTestModel())
    with pytest.raises(UserError, match="Gemini Developer API"):
        asyncio.run(Agent(model).run("evidence", usage_limits=limits()))


# ── The checklist agent's own model: whichever provider the slot resolves to (B1) ──


class _Generated(Exception):
    """Raised by the stubbed messages.create: the count let generation start."""


@pytest.mark.parametrize("returned", [1500, 0, True, None])
def test_claude_counts_the_whole_request_natively_and_refuses_a_non_count(monkeypatch, returned):
    from anthropic.resources.beta.messages.messages import AsyncMessages
    from anthropic.types.beta import BetaMessageTokensCount

    from agents._providers import provider_model
    from agents.topic_checklist import checklist_model

    sent = []

    async def count_tokens(self, **kwargs):
        sent.append(kwargs)
        return BetaMessageTokensCount.model_construct(input_tokens=returned)

    async def create(self, **kwargs):
        raise _Generated()

    monkeypatch.setattr(AsyncMessages, "count_tokens", count_tokens)
    monkeypatch.setattr(AsyncMessages, "create", create)
    # the slot's real model: the Claude 5.x profile, the resilience, the key guard
    model = checklist_model(provider_model("claude-haiku-5-5", task="topic_checklist"))
    assert checklist_model(model) is model

    async def run():
        return await Agent(model, output_type=Outline, system_prompt="rules").run(
            "evidence", usage_limits=limits(request_limit=1)
        )

    if returned == 1500:
        with pytest.raises(_Generated):
            asyncio.run(run())
    else:
        with pytest.raises(UnexpectedModelBehavior, match="no valid token count"):
            asyncio.run(run())
    # the system prompt and the output schema are part of what Claude counted
    assert len(sent) == 1 and sent[0]["system"]
    assert sent[0]["output_config"]["format"]["type"] == "json_schema"


def test_a_google_slot_keeps_the_full_envelope_counter_and_unknown_models_fail_closed():
    from agents.topic_checklist import checklist_model

    with pytest.raises(UserError, match="Gemini Developer API"):
        asyncio.run(Agent(checklist_model(LocalTestModel())).run("evidence", usage_limits=limits()))


def test_the_billable_models_are_the_slots_model_and_its_fallback(monkeypatch):
    from agents import topic_checklist

    assert topic_checklist.checklist_model_names() == ("claude-haiku-5-5", "gemini-2.5-flash")
    monkeypatch.setenv("SAPLING_MODEL_FALLBACK_TOPIC_CHECKLIST", "google-gla:gemini-2.5-pro")
    assert topic_checklist.checklist_model_names() == ("claude-haiku-5-5", "gemini-2.5-pro")
    # the function-mode seam never bills: it is held as the slot's real models
    monkeypatch.delenv("SAPLING_MODEL_FALLBACK_TOPIC_CHECKLIST")
    monkeypatch.setenv("SAPLING_MODEL_TOPIC_CHECKLIST", "gemini-2.5-flash")
    seam = topic_checklist.checklist_model(FunctionModel(lambda *_args: None))
    assert topic_checklist.checklist_model_names(seam) == ("gemini-2.5-flash", "claude-haiku-5-5")
