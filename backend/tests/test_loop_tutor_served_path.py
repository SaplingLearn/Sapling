"""PKG-07 Task 9: the loop tutor's SERVED path as shared, importable production
code — what tests/evals/loop_tutor.py replays through — and the tool-round cost
fix (flash-lite answers empty while tools stay declared after a tool call).
"""

from __future__ import annotations

import asyncio
import json

from pydantic_ai import capture_run_messages
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel

from agents import CONTINUATION_LIMITS, LOOP_LIMITS
from learning.ladder import Rung
from learning.leak import WITHHELD

_TURN = {
    "key_idea": "A base case stops recursion.",
    "body": "It is the input the function answers without calling itself.",
    "question": "Which input does factorial answer directly?",
}
_ITEM = {
    "reference": "The base case returns 1 when n equals 0 so the function stops calling itself.",
    "final_answer": "returns 1",
    "canonical_answer": None,
    "correct_option": None,
}


# ── the served text ─────────────────────────────────────────────────────────


def test_loop_leak_rung_is_the_routes_clamp():
    from routes.learn_loop import loop_leak_rung

    # hint turns are served at the hint rung, others at the ceiling
    assert (
        loop_leak_rung(phase="hint", rung=Rung.H2, ceiling=Rung.H5, answer_released=False)
        == Rung.H2
    )
    assert (
        loop_leak_rung(phase="teach", rung=Rung.H0, ceiling=Rung.H3, answer_released=False)
        == Rung.H3
    )
    # model text never writes H6 unreleased; a released answer is served at H6
    assert (
        loop_leak_rung(phase="teach", rung=Rung.H0, ceiling=Rung.H6, answer_released=False)
        == Rung.H5
    )
    assert (
        loop_leak_rung(phase="feedback", rung=Rung.H0, ceiling=Rung.H1, answer_released=True)
        == Rung.H6
    )


def test_served_model_text_serves_the_ladder_line_for_a_leak_and_passes_clean_text():
    """Fix round 2 (N1): a leak is never masked in place — the rung's ladder
    line is served instead; a copy of the text the model was given is none."""
    from routes.learn_loop import LADDER_FALLBACK_LINES, served_model_text

    clean = "Key idea: A base case stops recursion.\n\nWhich input ends it?"
    text, verdict = served_model_text(clean, leak_rung=Rung.H3, **_ITEM)
    assert text == clean and not verdict.leaked

    leaky = "Key idea: At n == 0 it returns 1.\n\nWhy does that stop it?"
    text, verdict = served_model_text(leaky, leak_rung=Rung.H3, **_ITEM)
    assert verdict.leaked and text == LADDER_FALLBACK_LINES[3] and WITHHELD not in text

    given = "Student: my code has a base case that at n == 0 it returns 1, why?"
    text, verdict = served_model_text(leaky, leak_rung=Rung.H3, given=given, **_ITEM)
    assert text == leaky and not verdict.leaked, "the student's own words are no leak"

    # released (served at H6): nothing is checked
    text, verdict = served_model_text(leaky, leak_rung=Rung.H6, **_ITEM)
    assert text == leaky and not verdict.leaked


def test_served_model_text_takes_the_correct_option():
    from routes.learn_loop import LADDER_FALLBACK_LINES, served_model_text

    reply = "Key idea: Look again at option B.\n\nWhat does option B claim?"
    item = {**_ITEM, "correct_option": "B"}
    text, verdict = served_model_text(reply, leak_rung=Rung.H3, **item)
    assert verdict.leaked and text == LADDER_FALLBACK_LINES[3]


# ── the tool-less continuation's plan (route + eval share it) ────────────────


def test_continuation_plan_continues_from_the_last_tool_results():
    from routes.learn_loop import _CONTINUATION_NUDGE, continuation_plan

    tool_round = [
        ModelRequest(parts=[UserPromptPart("hi")]),
        ModelResponse(parts=[ToolCallPart("read_graph_neighborhood", {}, tool_call_id="t1")]),
        ModelRequest(parts=[ToolReturnPart("read_graph_neighborhood", "{}", tool_call_id="t1")]),
    ]
    run_kwargs = {
        "deps": "D",
        "model": "M",
        "model_settings": {"tool_choice": "auto", "max_tokens": 400},
        "message_history": ["H"],
        "usage_limits": LOOP_LIMITS,
    }
    plan = continuation_plan(
        assembled="PREFIX\n\nhi",
        run_kwargs=run_kwargs,
        messages=[*tool_round, ModelResponse(parts=[])],
    )
    assert plan.prompt == _CONTINUATION_NUDGE and plan.feature == "loop_tutor_continuation"
    assert plan.run_kwargs["message_history"] == tool_round
    assert plan.run_kwargs["usage_limits"] is CONTINUATION_LIMITS
    assert plan.run_kwargs["model_settings"] == {"max_tokens": 400}
    assert plan.run_kwargs["deps"] == "D" and plan.run_kwargs["model"] == "M"

    plan = continuation_plan(assembled="PREFIX\n\nhi", run_kwargs=run_kwargs, messages=[])
    assert plan.prompt == "PREFIX\n\nhi" and plan.feature == "loop_tutor"
    assert plan.run_kwargs["message_history"] == ["H"]
    assert plan.run_kwargs["usage_limits"] is LOOP_LIMITS


# ── the cost fix: tools are offered only until the first tool round ─────────


def _deps():
    from unittest.mock import AsyncMock, MagicMock

    from agents.deps import SaplingDeps
    from agents.tools.graph_read import GraphNeighborhood

    retrieval = MagicMock()
    retrieval.graph_neighborhood = AsyncMock(return_value=GraphNeighborhood(concepts=[], edges=[]))
    return SaplingDeps(
        user_id="u1",
        course_id="c1",
        supabase=None,
        request_id="r",
        session_id="s",
        retrieval=retrieval,
        learning_loop=True,
        feature="loop_tutor",
    )


def test_the_request_after_a_tool_round_declares_no_tools():
    """Flash-lite answers EMPTY while tools stay declared after a tool call
    (#646's live finding), and pydantic-ai re-sends that request once per output
    retry: 3 wasted requests per tool turn before the rescue. The agent offers
    its tools only until the run's first tool round, so the follow-up request is
    tool-less — the shape Gemini answers — and a tool turn is 2 requests."""
    from agents.loop_tutor import loop_tutor_agent

    seen = []

    def model(messages, info):
        seen.append(sorted(t.name for t in info.function_tools))
        if len(seen) == 1:
            return ModelResponse(
                parts=[ToolCallPart("read_graph_neighborhood", {"concepts": ["recursion"]})]
            )
        if info.function_tools:
            return ModelResponse(parts=[])  # the lite behaviour with tools declared
        return ModelResponse(parts=[TextPart(json.dumps(_TURN))])

    async def go():
        with capture_run_messages() as messages:
            result = await loop_tutor_agent.run(
                "hi", deps=_deps(), model=FunctionModel(model), usage_limits=LOOP_LIMITS
            )
        return result, messages

    result, messages = asyncio.run(go())
    assert result.output == _TURN
    assert seen == [["read_graph_neighborhood", "search_course_materials"], []]
    assert sum(isinstance(m, ModelResponse) for m in messages) == 2


def test_tools_stay_declared_on_a_retry_before_any_tool_round():
    """A shape retry of a turn that called no tool keeps the declarations (the
    cached prefix is unchanged; only a tool round switches them off)."""
    from agents.loop_tutor import loop_tutor_agent

    seen = []
    bad = {**_TURN, "question": "Which input? And why?"}

    def model(messages, info):
        seen.append(len(info.function_tools))
        return ModelResponse(parts=[TextPart(json.dumps(bad if len(seen) == 1 else _TURN))])

    result = asyncio.run(
        loop_tutor_agent.run(
            "hi", deps=_deps(), model=FunctionModel(model), usage_limits=LOOP_LIMITS
        )
    )
    assert result.output == _TURN and seen == [2, 2]


def test_history_tool_rounds_do_not_switch_tools_off():
    """Only a tool round of THIS run counts: an earlier turn's tool results in
    message_history leave the new turn's first request with its tools."""
    from agents.loop_tutor import loop_tutor_agent

    seen = []

    def model(messages, info):
        seen.append(len(info.function_tools))
        return ModelResponse(parts=[TextPart(json.dumps(_TURN))])

    history = [
        ModelRequest(parts=[UserPromptPart("earlier")]),
        ModelResponse(parts=[ToolCallPart("read_graph_neighborhood", {}, tool_call_id="t0")]),
        ModelRequest(parts=[ToolReturnPart("read_graph_neighborhood", "{}", tool_call_id="t0")]),
        ModelResponse(parts=[TextPart(json.dumps(_TURN))]),
    ]
    asyncio.run(
        loop_tutor_agent.run(
            "hi",
            deps=_deps(),
            model=FunctionModel(model),
            usage_limits=LOOP_LIMITS,
            message_history=history,
        )
    )
    assert seen == [2]
