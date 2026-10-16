"""The tutor's rules must reach the model on EVERY turn, not only the opener.

pydantic-ai sends an agent's `system_prompt=` only when the run starts with
an EMPTY `message_history`. The tutor routes rebuild history from `messages`
rows (`routes.learn._load_message_history`) as bare UserPromptPart/TextPart
pairs — no SystemPromptPart — so with `system_prompt=` every turn after the
opener ran without the mode rules, the academic-integrity rule, the
injection guard and the tool guidance. `instructions=` is re-sent on every
model request regardless of history.

Most tests drive the REAL tutor agents (model swapped via
`agent.override(model=FunctionModel(...))`) and assert on what the model is
actually handed: `info.instructions` plus any SystemPromptPart in the
messages. Checking both keeps the assertion about the invariant ("the rules
reach the model exactly once") rather than about which pydantic-ai field
carries them. The last two go one layer further down, through the real
`GoogleModel`, and read the Gemini request itself — the client call is
intercepted, so nothing leaves the process.
"""
from __future__ import annotations

import asyncio
from typing import get_args

import pytest
from pydantic_ai import Tool
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agents.chat_tutor import _PROMPTS, TutorMode, agent_for_mode
from agents.deps import SaplingDeps
from routes.learn import _CONTINUATION_INSTRUCTIONS, _continuation_text
from tests.agent_run_fakes import FakeRunResult

MODES = get_args(TutorMode)

RESCUED_REPLY = "Good — what comes next?"


def _deps() -> SaplingDeps:
    return SaplingDeps(
        user_id="u1", course_id="c1", supabase=None,
        request_id="r1", session_id="s1",
    )


def _history() -> list:
    """Two prior messages, shaped exactly like `_load_message_history` output."""
    return [
        ModelRequest(parts=[UserPromptPart(content="what is gradient descent?")]),
        ModelResponse(parts=[TextPart(content="It walks downhill. What do you notice?")]),
    ]


def _prompt_seen(messages, info: AgentInfo) -> str:
    """Everything the model was handed as system-level text for this request."""
    parts = [info.instructions or ""]
    for m in messages:
        if isinstance(m, ModelRequest):
            parts.extend(p.content for p in m.parts if isinstance(p, SystemPromptPart))
    return "\n".join(parts)


def _assert_rules(seen: str, mode: str) -> None:
    """The full mode prompt (mode rules + academic integrity + injection guard
    + tool guidance) reached the model, and reached it ONCE — a prompt sent
    as both instructions and a SystemPromptPart would double the tokens and
    is not what any route intends."""
    count = seen.count(_PROMPTS[mode])
    assert count == 1, f"{mode}: tutor prompt seen {count} times in one request, want 1"


class _Capture:
    __name__ = "capture"

    def __init__(self):
        self.seen: list[str] = []

    def __call__(self, messages, info: AgentInfo) -> ModelResponse:
        self.seen.append(_prompt_seen(messages, info))
        return ModelResponse(parts=[TextPart(content=RESCUED_REPLY)])

    async def stream(self, messages, info: AgentInfo):
        self.seen.append(_prompt_seen(messages, info))
        yield RESCUED_REPLY


def _model(cap: _Capture) -> FunctionModel:
    return FunctionModel(cap, stream_function=cap.stream)


@pytest.mark.parametrize("mode", MODES)
def test_opener_carries_rules(mode):
    """Control: an empty-history run always carried the prompt."""
    agent = agent_for_mode(mode)
    cap = _Capture()
    with agent.override(model=_model(cap)):
        asyncio.run(agent.run("hi", deps=_deps(), message_history=[]))
    assert cap.seen
    _assert_rules(cap.seen[0], mode)


@pytest.mark.parametrize("mode", MODES)
def test_history_turn_run_carries_rules(mode):
    """/chat and the action turn: `agent.run(..., message_history=<rows>)`."""
    agent = agent_for_mode(mode)
    cap = _Capture()
    with agent.override(model=_model(cap)):
        asyncio.run(
            agent.run("and the step size?", deps=_deps(), message_history=_history())
        )
    assert cap.seen
    for seen in cap.seen:
        _assert_rules(seen, mode)


@pytest.mark.parametrize("mode", MODES)
def test_history_turn_stream_carries_rules(mode):
    """/chat/stream: `services.chat_stream` drives `run_stream_events`."""
    agent = agent_for_mode(mode)
    cap = _Capture()

    async def _drive():
        async for _ in agent.run_stream_events(
            "and the step size?", deps=_deps(), message_history=_history()
        ):
            pass

    with agent.override(model=_model(cap)):
        asyncio.run(_drive())
    assert cap.seen
    for seen in cap.seen:
        _assert_rules(seen, mode)


class _TextlessThenRescued:
    """The real #646 shape: a tool call, its return, then a response with NO
    text — followed by the continuation, which is the only request made with
    no tools available."""

    __name__ = "textless_then_rescued"

    def __init__(self):
        self.first_run_seen: list[str] = []
        self.continuation_seen: list[str] = []

    def __call__(self, messages, info: AgentInfo) -> ModelResponse:
        seen = _prompt_seen(messages, info)
        if not info.function_tools:
            self.continuation_seen.append(seen)
            return ModelResponse(parts=[TextPart(content=RESCUED_REPLY)])
        self.first_run_seen.append(seen)
        tool_ran = any(
            isinstance(p, ToolReturnPart) for m in messages for p in m.parts
        )
        if not tool_ran:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="update_mastery_tool", args={"concept": "gd"})]
            )
        return ModelResponse(parts=[])  # tools ran; the turn ends saying nothing


def _stub_update_mastery(concept: str) -> str:
    """Stands in for the real tool, which would write to the database."""
    return "mastery recorded"


@pytest.mark.parametrize("mode", MODES)
def test_textless_continuation_carries_rules_and_no_tools_notice(mode):
    """#646: the continuation reruns on `run_result.all_messages()` of a
    history-bearing turn. It must still carry the tutor's rules, AND — since
    those rules demand a mastery call every turn while the continuation is
    handed no tools — it must say plainly that no tools exist on this pass."""
    agent = agent_for_mode(mode)
    model = _TextlessThenRescued()
    run_kwargs = {"deps": _deps(), "message_history": _history()}
    stub = Tool(_stub_update_mastery, name="update_mastery_tool")
    with agent.override(model=FunctionModel(model)):
        with agent.override(tools=[stub], toolsets=[]):
            first = asyncio.run(agent.run("and the step size?", **run_kwargs))
        text = asyncio.run(_continuation_text(agent, first, run_kwargs))

    # Premise: the first run really was textless after a real tool round trip.
    assert len(model.first_run_seen) == 2, "expected tool call, then a textless reply"
    assert not any(
        isinstance(p, TextPart) for m in first.new_messages()
        if isinstance(m, ModelResponse) for p in m.parts
    )
    for seen in model.first_run_seen:
        _assert_rules(seen, mode)
        assert _CONTINUATION_INSTRUCTIONS not in seen, (
            "the no-tools notice must be scoped to the continuation"
        )

    assert text == RESCUED_REPLY
    assert len(model.continuation_seen) == 1
    seen = model.continuation_seen[0]
    _assert_rules(seen, mode)
    assert seen.count(_CONTINUATION_INSTRUCTIONS) == 1, (
        f"{mode}: continuation must tell the model no tools are available"
    )
    assert seen.index(_CONTINUATION_INSTRUCTIONS) > seen.index(_PROMPTS[mode]), (
        "the notice must follow (and so override) the tutor's tool rules"
    )


# ── Through the real GoogleModel ──────────────────────────────────────────


class _Sent(Exception):
    """Carries the kwargs the GoogleModel handed to the genai client."""

    def __init__(self, kwargs: dict):
        super().__init__("intercepted")
        self.kwargs = kwargs


def _intercepting_google_model(monkeypatch):
    """A real `GoogleModel` whose genai client raises `_Sent(kwargs)` instead
    of sending. (The autouse hermetic LLM guard backs this up: if the
    intercept ever missed, the transport would raise, not reach Gemini.)"""
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    provider = GoogleProvider(api_key="test-key-never-sent")

    async def _capture(**kwargs):
        raise _Sent(kwargs)

    monkeypatch.setattr(provider.client.aio.models, "generate_content", _capture)
    return GoogleModel("gemini-2.5-flash-lite", provider=provider)


def _texts(content) -> str:
    """All text parts of a genai ContentDict (or list of them), joined."""
    items = content if isinstance(content, list) else [content]
    return "\n".join(
        part.get("text") or ""
        for item in items if item
        for part in item.get("parts", [])
    )


def test_history_turn_rules_land_in_gemini_system_instruction(monkeypatch):
    """The FunctionModel tests prove pydantic-ai hands the rules over; this
    proves the Google mapping puts them in `system_instruction` (once) and
    not in the conversation turns."""
    agent = agent_for_mode("socratic")
    model = _intercepting_google_model(monkeypatch)
    with agent.override(model=model), pytest.raises(_Sent) as sent:
        asyncio.run(
            agent.run("and the step size?", deps=_deps(), message_history=_history())
        )

    config = sent.value.kwargs["config"]
    system = _texts(config["system_instruction"])
    assert system.count(_PROMPTS["socratic"]) == 1
    contents = _texts(sent.value.kwargs["contents"])
    assert "what is gradient descent?" in contents, "history must be sent"
    assert _PROMPTS["socratic"] not in contents
    assert config.get("tools"), "a normal tutor turn declares its tools"


def test_continuation_gemini_request_has_notice_and_no_tools(monkeypatch):
    """The continuation's actual Gemini request: no tool declarations, and the
    no-tools notice inside `system_instruction` after the tutor's rules."""
    agent = agent_for_mode("socratic")
    model = _intercepting_google_model(monkeypatch)
    textless = FakeRunResult(
        "It walks downhill. What do you notice?",
        [
            ModelRequest(parts=[UserPromptPart(content="and the step size?")]),
            ModelResponse(parts=[
                ToolCallPart(tool_name="update_mastery_tool", args={"concept": "gd"},
                             tool_call_id="call-1"),
            ]),
            ModelRequest(parts=[
                ToolReturnPart(tool_name="update_mastery_tool",
                               content="mastery recorded", tool_call_id="call-1"),
            ]),
            ModelResponse(parts=[]),
        ],
        history=_history(),
    )
    run_kwargs = {"deps": _deps(), "message_history": _history()}
    with agent.override(model=model), pytest.raises(_Sent) as sent:
        asyncio.run(_continuation_text(agent, textless, run_kwargs))

    config = sent.value.kwargs["config"]
    assert not config.get("tools"), "the continuation must declare no tools"
    system = _texts(config["system_instruction"])
    assert system.count(_PROMPTS["socratic"]) == 1
    assert system.count(_CONTINUATION_INSTRUCTIONS) == 1
    assert system.index(_CONTINUATION_INSTRUCTIONS) > system.index(_PROMPTS["socratic"])
