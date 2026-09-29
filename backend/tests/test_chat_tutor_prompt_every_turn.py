"""The tutor's rules must reach the model on EVERY turn, not only the opener.

pydantic-ai sends an agent's `system_prompt=` only when the run starts with
an EMPTY `message_history`. The tutor routes rebuild history from `messages`
rows (`routes.learn._load_message_history`) as bare UserPromptPart/TextPart
pairs — no SystemPromptPart — so with `system_prompt=` every turn after the
opener ran without the mode rules, the academic-integrity rule, the
injection guard and the tool guidance. `instructions=` is re-sent on every
model request regardless of history.

These tests drive the REAL tutor agents (model swapped via
`agent.override(model=FunctionModel(...))`) and assert on what the model is
actually handed: `info.instructions` plus any SystemPromptPart in the
messages. Checking both keeps the assertion about the invariant ("the rules
reach the model") rather than about which pydantic-ai field carries them.
"""
from __future__ import annotations

import asyncio

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agents.chat_tutor import _ACADEMIC_INTEGRITY, _PROMPTS, agent_for_mode
from agents.deps import SaplingDeps
from services.prompt_safety import INJECTION_GUARD_PROMPT

MODES = ("socratic", "expository", "teachback")

#: The mode-specific tail of each prompt (the "MODE: ..." paragraph).
_MODE_MARKER = {
    "socratic": "MODE: Socratic.",
    "expository": "MODE: Expository.",
    "teachback": "MODE: TeachBack.",
}


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
    assert _MODE_MARKER[mode] in seen, f"{mode}: mode rules missing"
    assert "ACADEMIC INTEGRITY (non-negotiable)" in seen, f"{mode}: integrity rule missing"
    assert _ACADEMIC_INTEGRITY in seen
    assert INJECTION_GUARD_PROMPT in seen, f"{mode}: injection guard missing"
    assert _PROMPTS[mode] in seen


class _Capture:
    __name__ = "capture"

    def __init__(self):
        self.seen: list[str] = []

    def __call__(self, messages, info: AgentInfo) -> ModelResponse:
        self.seen.append(_prompt_seen(messages, info))
        return ModelResponse(parts=[TextPart(content="Good — what comes next?")])

    async def stream(self, messages, info: AgentInfo):
        self.seen.append(_prompt_seen(messages, info))
        yield "Good — what comes next?"


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


@pytest.mark.parametrize("mode", MODES)
def test_textless_continuation_carries_rules(mode):
    """#646: the continuation reruns on `run_result.all_messages()` of a
    history-bearing turn — it must still carry the tutor's rules."""
    from routes.learn import _continuation_text

    agent = agent_for_mode(mode)
    cap = _Capture()
    deps = _deps()
    run_kwargs = {"deps": deps, "message_history": _history()}
    with agent.override(model=_model(cap)):
        first = asyncio.run(agent.run("and the step size?", **run_kwargs))
        cap.seen.clear()
        text = asyncio.run(_continuation_text(agent, first, run_kwargs))
    assert text
    assert cap.seen
    for seen in cap.seen:
        _assert_rules(seen, mode)
