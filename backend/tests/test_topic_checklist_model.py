"""Exercise pinned Google serialization over an in-process HTTP transport only."""

import asyncio
from contextlib import asynccontextmanager
import json
from types import MethodType, SimpleNamespace

from google.genai import _api_client, errors as google_errors
import httpx
from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, NativeOutput
from pydantic_ai.exceptions import (
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    UserError,
)
from pydantic_ai.models import ModelRequestParameters
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


def generated(body, answer="good"):
    if body.get("tools"):
        part = {
            "functionCall": {
                "name": body["tools"][0]["functionDeclarations"][0]["name"],
                "args": {"answer": answer},
            }
        }
    else:
        part = {"text": json.dumps({"answer": answer})}
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"role": "model", "parts": [part]}, "finishReason": "STOP"}],
            "usageMetadata": {
                "promptTokenCount": 20,
                "candidatesTokenCount": 10,
                "thoughtsTokenCount": 5,
                "totalTokenCount": 35,
            },
            "modelVersion": "gemini-2.5-flash",
        },
    )


@pytest.mark.parametrize("native", [False, True])
def test_full_envelope_equals_generation_including_system_schema_unicode_and_retry_history(native):
    counts, generations, timeouts = [], [], []

    def handle(request):
        body = json.loads(request.content)
        timeouts.append(request.extensions["timeout"])
        if request.url.path.endswith(":countTokens"):
            assert body["contents"] is None
            counts.append(body["generateContentRequest"])
            return httpx.Response(200, json={"totalTokens": 31})
        assert request.url.path.endswith(":generateContent")
        generations.append(body)
        return generated(body, "bad" if len(generations) == 1 else "good")

    async def run():
        async with transport_model(handle) as model:
            agent = Agent(
                model,
                output_type=NativeOutput(Outline) if native else Outline,
                system_prompt="Only evidence. 中文 Ελληνικά 🧠",
                retries=2,
                model_settings=SETTINGS,
            )

            @agent.output_validator
            def validate(value):
                if value.answer == "bad":
                    raise ModelRetry("Use only the owned source identifier.")
                return value

            result = await agent.run("Course evidence: récursion 递归", usage_limits=limits())
            assert result.output.answer == "good"
            # Preflight estimates are not added to billed run usage; reasoning
            # tokens from both actual responses are included by the SDK mapper.
            assert result.usage.requests == 2
            assert result.usage.input_tokens == 40
            assert result.usage.output_tokens == 30

    asyncio.run(run())
    assert len(counts) == len(generations) == 2
    for counted, generation in zip(counts, generations, strict=True):
        assert counted == generation | {"model": "models/gemini-2.5-flash"}
        assert counted["systemInstruction"]["parts"][0]["text"] == "Only evidence. 中文 Ελληνικά 🧠"
        assert counted["generationConfig"]["maxOutputTokens"] == 8192
        if native:
            assert counted["generationConfig"]["responseJsonSchema"]["properties"]["answer"]
        else:
            assert counted["tools"][0]["functionDeclarations"][0]["parameters_json_schema"][
                "properties"
            ]["answer"]
    assert len(counts[1]["contents"]) > len(counts[0]["contents"])
    assert "Use only the owned source identifier." in json.dumps(counts[1])
    assert all(timeout["read"] == 60 and timeout["connect"] == 60 for timeout in timeouts)


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


def test_retry_count_includes_previous_actual_usage_and_blocks_second_generation():
    paths = []

    def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 49_990})
        return generated(json.loads(request.content), "bad")

    async def run():
        async with transport_model(handle) as model:
            agent = Agent(model, output_type=Outline, retries=2, model_settings=SETTINGS)

            @agent.output_validator
            def retry(value):
                raise ModelRetry("Try the owned source.")

            with pytest.raises(UsageLimitExceeded):
                await agent.run("evidence", usage_limits=limits())

    asyncio.run(run())
    assert [path.rsplit(":", 1)[1] for path in paths] == [
        "countTokens",
        "generateContent",
        "countTokens",
    ]


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


@pytest.mark.parametrize("failure", ["503", "timeout", "cancel"])
def test_counter_failure_has_one_attempt_and_no_generation_or_contents_fallback(failure):
    paths = []

    def handle(request):
        paths.append(request.url.path)
        if failure == "timeout":
            raise httpx.ReadTimeout("counter timeout")
        if failure == "cancel":
            raise asyncio.CancelledError("counter cancelled")
        return httpx.Response(503, json={"error": {"code": 503, "message": "unavailable"}})

    async def run():
        async with transport_model(handle) as model:
            expected = {
                "503": google_errors.ServerError,
                "timeout": httpx.ReadTimeout,
                "cancel": asyncio.CancelledError,
            }[failure]
            with pytest.raises(expected):
                await Agent(model, model_settings=SETTINGS).run("evidence", usage_limits=limits())

    asyncio.run(run())
    assert len(paths) == 1 and paths[0].endswith(":countTokens")


def test_generation_http_failure_is_not_retried_by_sdk():
    paths = []

    def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 10})
        return httpx.Response(503, json={"error": {"code": 503, "message": "unavailable"}})

    async def run():
        async with transport_model(handle) as model:
            with pytest.raises(ModelHTTPError):
                await Agent(model, model_settings=SETTINGS).run("evidence", usage_limits=limits())

    asyncio.run(run())
    assert [path.rsplit(":", 1)[1] for path in paths] == ["countTokens", "generateContent"]


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


def test_vertex_client_is_not_sent_developer_api_envelope():
    async def run():
        async with transport_model(
            lambda request: pytest.fail("no Vertex request allowed")
        ) as model:
            model.wrapped.client._api_client.vertexai = True
            with pytest.raises(UserError, match="Vertex AI"):
                await Agent(model).run("evidence", usage_limits=limits())

    asyncio.run(run())


def test_bad_count_type_from_sdk_seam_is_rejected(monkeypatch):
    async def run():
        async with transport_model(
            lambda request: pytest.fail("must use patched count seam")
        ) as model:

            async def count(**_kwargs):
                return SimpleNamespace(total_tokens=True)

            monkeypatch.setattr(model.wrapped.client.aio.models, "count_tokens", count)
            with pytest.raises(UnexpectedModelBehavior):
                await model.count_tokens([], SETTINGS, ModelRequestParameters())

    asyncio.run(run())


def test_conversion_failure_stops_before_counter_or_generation(monkeypatch):
    from agents import topic_checklist_model as module

    original = ValueError("SDK conversion unavailable")

    def fail(*_args):
        raise original

    monkeypatch.setattr(module.google_models, "_GenerateContentParameters_to_mldev", fail)

    async def run():
        async with transport_model(
            lambda request: pytest.fail("conversion must fail before HTTP")
        ) as model:
            with pytest.raises(ValueError) as error:
                await Agent(model).run("evidence", usage_limits=limits())
            assert error.value is original

    asyncio.run(run())
