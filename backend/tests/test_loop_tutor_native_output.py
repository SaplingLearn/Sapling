"""Production loop agent + pinned Google SDK over an in-process HTTP transport.

No credentials, provider calls, learner evidence or database: assertions inspect
the actual serialized wire body, including native constraints during streaming
and validation retries. Malformed output is never repaired or counted as served.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
import json
from types import MethodType

from google.genai import _api_client
import httpx
from pydantic import TypeAdapter
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models import ModelRequestContext, ModelRequestParameters
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.output import OutputObjectDefinition
from pydantic_ai.profiles.google import GoogleModelProfile
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RunUsage
import pytest

from agents import CONTINUATION_LIMITS, LOOP_LIMITS
from agents import loop_tutor as tutor
from agents.deps import SaplingDeps
from learning.ladder import Rung
from learning.params import (
    LOOP_FLASH_THINKING_BUDGET,
    LOOP_MAX_VISIBLE_TOKENS,
    LOOP_PRO_THINKING_BUDGET,
)
from learning.turn_shape import (
    LoopTurnOut,
    TURN_FIELDS,
    render_partial,
    render_turn,
    turn_limits,
)
from services.chat_stream import stream_structured_turn

# Capture before the autouse transport guard, and restore ONLY on the one SDK
# instance using MockTransport. Every other LLM and DB egress remains blocked.
_SDK_ASYNC_METHODS = {
    name: getattr(_api_client.BaseApiClient, name)
    for name in (
        "async_request",
        "async_request_streamed",
        "_async_request",
        "_async_request_once",
    )
}
TURN = {
    "key_idea": "A base case stops recursion.",
    "body": "It provides a stopping condition for the function.",
    "question": "Which input should stop the function?",
}
BAD_SHAPE = {**TURN, "question": "Review the stopping condition. Which input should stop it?"}
MODEL_NAMES = {
    "lite": "gemini-2.5-flash-lite",
    "standard": "gemini-2.5-flash",
    "deep": "gemini-2.5-pro",
}


@asynccontextmanager
async def transport_model(handler, name="gemini-2.5-flash", **kwargs):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = GoogleProvider(api_key="synthetic-test-key", http_client=http)
        api = provider.client._api_client
        for method_name, method in _SDK_ASYNC_METHODS.items():
            setattr(api, method_name, MethodType(method, api))
        try:
            yield GoogleModel(name, provider=provider, **kwargs)
        finally:
            await provider.client.aio.aclose()
            provider.client.close()


def deps(*, released=False):
    result = SaplingDeps(
        user_id="synthetic-user",
        course_id="synthetic-course",
        supabase=None,
        request_id="synthetic",
    )
    result.loop_turn = turn_limits("feedback" if released else "teach", Rung.H3, released)
    return result


def wire_part(part, *, finish=True, name="gemini-2.5-flash"):
    result = {
        "candidates": [{"content": {"role": "model", "parts": [part]}}],
        "modelVersion": name,
    }
    if finish:
        result["candidates"][0]["finishReason"] = "STOP"
        result["usageMetadata"] = {
            "promptTokenCount": 20,
            "candidatesTokenCount": 10,
            "totalTokenCount": 30,
        }
    return result


def google_response(request, text, *, function=None, name="gemini-2.5-flash"):
    if ":streamGenerateContent" in request.url.path:
        if function:
            chunks = [wire_part({"functionCall": {"name": function, "args": {}}}, name=name)]
        else:
            # JSON strings/escapes are deliberately split across transport frames.
            pieces = [text[i : i + 9] for i in range(0, len(text), 9)]
            chunks = [
                wire_part({"text": piece}, finish=i == len(pieces) - 1, name=name)
                for i, piece in enumerate(pieces)
            ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks),
        )
    assert request.url.path.endswith(":generateContent")
    part = {"functionCall": {"name": function, "args": {}}} if function else {"text": text}
    return httpx.Response(200, json=wire_part(part, name=name))


def assert_native(body):
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    schema = config["responseJsonSchema"]
    assert schema["type"] == "object"
    assert list(schema["properties"]) == list(TURN_FIELDS)
    assert schema["required"] == list(TURN_FIELDS)
    assert schema["additionalProperties"] is False
    assert all(schema["properties"][key]["type"] == "string" for key in TURN_FIELDS)
    assert "tools" not in body and "toolConfig" not in body


@pytest.mark.parametrize("tier", MODEL_NAMES)
def test_all_tiers_send_native_schema_for_disabled_tools_without_changing_caps(tier, monkeypatch):
    bodies, paths = [], []

    def handle(request):
        paths.append(request.url.path)
        bodies.append(json.loads(request.content))
        return google_response(request, json.dumps(TURN), name=MODEL_NAMES[tier])

    async def run():
        async with transport_model(handle, MODEL_NAMES[tier]) as model:
            slots = []

            def configured(slot):
                slots.append(slot)
                return model

            monkeypatch.setattr(tutor, "model_for", configured)
            result = await tutor.loop_tutor_agent.run(
                "Synthetic feedback context.",
                deps=deps(released=True),
                usage_limits=LOOP_LIMITS,
                **tutor.tier_run_kwargs(tier, tool_choice="none"),
            )
            assert result.output == TURN and result.usage.requests == 1
            assert slots == [tutor.LOOP_TIER_SLOTS[tier]]

    asyncio.run(run())
    assert len(bodies) == 1 and MODEL_NAMES[tier] in paths[0]
    assert_native(bodies[0])
    config = bodies[0]["generationConfig"]
    thinking = LOOP_PRO_THINKING_BUDGET if tier == "deep" else LOOP_FLASH_THINKING_BUDGET
    assert config["maxOutputTokens"] == LOOP_MAX_VISIBLE_TOKENS + thinking
    if tier != "lite":
        assert config["thinkingConfig"]["thinking_budget"] == thinking
    assert tutor._LOOP_SYSTEM_PROMPT.strip() == bodies[0]["systemInstruction"]["parts"][0]["text"]


@pytest.mark.parametrize("streamed", [False, True])
def test_callable_read_round_is_preserved_then_final_and_retries_become_native(streamed):
    bodies, called, persisted = [], [], []

    def read_material() -> str:
        called.append(1)
        return "Synthetic course source."

    def handle(request):
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return google_response(request, "", function="read_material")
        return google_response(request, json.dumps(BAD_SHAPE if len(bodies) == 2 else TURN))

    async def run():
        async with transport_model(handle) as model:
            with tutor.loop_tutor_agent.override(tools=[read_material]):
                if streamed:
                    events = await collect(model, persisted, allow_tools=True)
                    assert events[-1].type == "done" and not any(e.type == "error" for e in events)
                    assert any(e.type == "retract" for e in events)
                else:
                    result = await tutor.loop_tutor_agent.run(
                        "Synthetic material lookup.",
                        model=model,
                        deps=deps(),
                        usage_limits=LOOP_LIMITS,
                    )
                    assert result.output == TURN and result.usage.requests == 3

    asyncio.run(run())
    assert len(bodies) == 3 and called == [1]
    names = {
        declaration["name"]
        for tool in bodies[0]["tools"]
        for declaration in tool["functionDeclarations"]
    }
    assert names == {"read_material"}
    assert "responseJsonSchema" not in bodies[0]["generationConfig"]
    assert "responseMimeType" not in bodies[0]["generationConfig"]
    for body in bodies[1:]:
        assert_native(body)
    assert "functionResponse" in json.dumps(bodies[1]["contents"])
    assert "question_shape:2 sentences" in json.dumps(bodies[2]["contents"])
    if streamed:
        assert persisted == [render_turn(TURN)]


async def collect(
    model,
    persisted,
    *,
    usage=None,
    completed=None,
    incomplete=None,
    fallback=None,
    allow_tools=False,
):
    d = deps()
    return [
        event
        async for event in stream_structured_turn(
            agent=tutor.loop_tutor_agent,
            user_message="Synthetic feedback context.",
            run_kwargs={
                "deps": d,
                "model": model,
                "model_settings": {} if allow_tools else {"tool_choice": "none"},
                "usage_limits": LOOP_LIMITS,
                "usage": usage if usage is not None else RunUsage(),
            },
            deps=d,
            # Use the same object for validator and producer side effects.
            on_complete=lambda reply, graph, mastery: persisted.append(reply) or {},
            on_usage=completed.append if completed is not None else None,
            on_incomplete_usage=incomplete.append if incomplete is not None else None,
            transform=lambda text: text,
            render_partial=render_partial,
            render_final=render_turn,
            nonstream_fallback=fallback if callable(fallback) else None,
        )
    ]


@pytest.mark.parametrize("bad_rounds", [0, 1, 2, 3])
def test_native_stream_retries_control_character_json_without_repair_or_extra_calls(bad_rounds):
    bodies, persisted, completed, incomplete, fallback_calls = [], [], [], [], []
    usage = RunUsage()
    # Reproduce the real parser failure using synthetic text, not an actual
    # learner reply: the JSON string contains an unescaped control character.
    malformed = json.dumps(TURN).replace("Which input", "Which\ninput")

    def handle(request):
        bodies.append(json.loads(request.content))
        return google_response(
            request, malformed if len(bodies) <= bad_rounds else json.dumps(TURN)
        )

    async def fallback(messages):
        fallback_calls.append(1)
        raise AssertionError("tokens must not cause an invisible rescue")

    async def run():
        async with transport_model(handle) as model:
            return await collect(
                model,
                persisted,
                usage=usage,
                completed=completed,
                incomplete=incomplete,
                fallback=fallback,
            )

    events = asyncio.run(run())
    types = [event.type for event in events]
    assert len(bodies) == usage.requests == min(bad_rounds + 1, 3)
    assert fallback_calls == []
    for body in bodies:
        assert_native(body)
    assert types.count("retract") == min(bad_rounds, 2)
    if bad_rounds == 3:
        assert types[-1] == "error" and types.count("error") == 1 and "done" not in types
        assert persisted == completed == [] and incomplete == [usage]
    else:
        assert types[-1] == "done" and "error" not in types
        assert persisted == [render_turn(TURN)]
        assert len(completed) == 1 and completed[0].usage == usage and incomplete == []


def test_native_mode_preserves_custom_leak_retry_and_partial_parser():
    class Guard:
        retried = False

        @staticmethod
        def leaks(text):
            return "forbidden answer" in text

        render = staticmethod(render_turn)

    bodies = []
    bad = {**TURN, "body": "The forbidden answer is stated here."}

    def handle(request):
        bodies.append(json.loads(request.content))
        return google_response(request, json.dumps(bad if len(bodies) == 1 else TURN))

    async def run():
        async with transport_model(handle) as model:
            d = deps()
            d.loop_leak = guard = Guard()
            result = await tutor.loop_tutor_agent.run(
                "Synthetic feedback context.",
                model=model,
                deps=d,
                model_settings={"tool_choice": "none"},
                usage_limits=LOOP_LIMITS,
            )
            assert result.output == TURN and guard.retried and result.usage.requests == 2

    asyncio.run(run())
    assert len(bodies) == 2
    assert tutor.LEAK_RETRY_MESSAGE in json.dumps(bodies[1]["contents"])
    for body in bodies:
        assert_native(body)
    # Native required fields must not make local streaming partials invalid.
    assert (
        TypeAdapter(LoopTurnOut).validate_json(
            '{"key_idea":"A base case stops.', experimental_allow_partial=True
        )
        == {}
    )


def test_toolless_continuation_uses_native_output_without_a_tool_choice_override():
    bodies = []

    def handle(request):
        bodies.append(json.loads(request.content))
        return google_response(request, json.dumps(TURN))

    async def run():
        async with transport_model(handle) as model:
            with tutor.loop_tutor_agent.override(tools=[], toolsets=[]):
                result = await tutor.loop_tutor_agent.run(
                    "Synthetic continuation context.",
                    model=model,
                    deps=deps(),
                    model_settings={"max_tokens": LOOP_MAX_VISIBLE_TOKENS},
                    usage_limits=CONTINUATION_LIMITS,
                )
            assert result.output == TURN and result.usage.requests == 1

    asyncio.run(run())
    assert len(bodies) == 1
    assert_native(bodies[0])
    assert bodies[0]["generationConfig"]["maxOutputTokens"] == LOOP_MAX_VISIBLE_TOKENS


def context(model, *, choice="none", tools=True, native_tools=None):
    params = ModelRequestParameters(
        output_mode="prompted",
        output_object=OutputObjectDefinition(TypeAdapter(LoopTurnOut).json_schema()),
        function_tools=[ToolDefinition(name="read_material")] if tools else [],
        native_tools=native_tools or [],
        prompted_output_template=tutor.LOOP_OUTPUT_TEMPLATE,
    )
    return ModelRequestContext(
        model=model,
        messages=[],
        model_settings={"tool_choice": choice, "max_tokens": LOOP_MAX_VISIBLE_TOKENS},
        model_request_parameters=params,
    )


def test_hook_is_request_local_and_function_model_seam_is_unchanged():
    function = FunctionModel(
        lambda messages, info: ModelResponse(parts=[TextPart(json.dumps(TURN))])
    )
    request = context(function)
    assert tutor._native_output_when_toolless(None, request) is request

    # No transport is used to inspect a model or transform request parameters.
    google = GoogleModel("gemini-2.5-flash", provider=GoogleProvider(api_key="synthetic-test-key"))
    try:
        request = context(google)
        original = deepcopy(request.model_request_parameters)
        updated = tutor._native_output_when_toolless(None, request)
        assert updated is not request
        assert request.model_request_parameters == original
        assert updated.model is google and updated.model_settings is request.model_settings
        assert updated.messages is request.messages
        assert updated.model_request_parameters.output_mode == "native"
        assert not updated.model_request_parameters.function_tools
        assert request.model_request_parameters.function_tools
        assert "required" not in request.model_request_parameters.output_object.json_schema
        # A concurrent tool-enabled request retains declarations and prompt mode.
        enabled = replace(request, model_settings={"tool_choice": "auto"})
        assert tutor._native_output_when_toolless(None, enabled) is enabled
        forced = replace(request, model_settings={"tool_choice": ["read_material"]})
        assert tutor._native_output_when_toolless(None, forced) is forced
        wrapped = replace(request, model=WrapperModel(google))
        assert (
            tutor._native_output_when_toolless(None, wrapped).model_request_parameters.output_mode
            == "native"
        )
    finally:
        google.client.close()


def test_unsupported_native_google_model_fails_before_transport():
    called = []

    def handle(request):
        called.append(1)
        raise AssertionError("unsupported native mode must fail before the wire")

    async def run():
        async with transport_model(
            handle, profile=GoogleModelProfile(supports_json_schema_output=False)
        ) as model:
            with pytest.raises(UserError, match="Native structured output is not supported"):
                await tutor.loop_tutor_agent.run(
                    "Synthetic feedback context.",
                    model=model,
                    deps=deps(),
                    model_settings={"tool_choice": "none"},
                    usage_limits=LOOP_LIMITS,
                )

    asyncio.run(run())
    assert called == []
