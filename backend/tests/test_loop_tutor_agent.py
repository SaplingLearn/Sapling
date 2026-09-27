"""PKG-07: loop tutor agent, tier slots, prompt composition, tool surface, seam wiring."""

from __future__ import annotations

import re
from typing import get_args

import pytest

from learning.params import STEP_MAX_SENTENCES, STEP_QUESTIONS_PER_TURN

LOOP_TUTOR_SLOTS = ("loop_tutor_lite", "loop_tutor", "loop_tutor_deep")


def test_stream_event_types_gain_the_five_loop_events():
    from services.agent_events import SaplingEvent, SaplingEventType

    types = set(get_args(SaplingEventType))
    assert {"phase", "check", "hint_offer", "learner_state", "budget"} <= types
    # Legacy vocabulary untouched.
    assert {"status", "progress", "result", "error", "token", "graph_update", "done"} <= types
    SaplingEvent(
        type="budget",
        step="loop",
        message="",
        data={"level": "hard", "reset_at": "2026-09-27T00:00:00+00:00"},
    )


def test_loop_limits_shape():
    from agents import CONTINUATION_LIMITS, LOOP_LIMITS

    assert LOOP_LIMITS.request_limit == 4
    assert LOOP_LIMITS.tool_calls_limit == 3
    assert LOOP_LIMITS.total_tokens_limit == 40_000
    # The #646 continuation stays tool-less and budget-capped for the loop too.
    assert CONTINUATION_LIMITS.tool_calls_limit == 0


def test_tier_thinking_constants_appended_to_params():
    from learning.params import (
        LOOP_FLASH_THINKING_BUDGET,
        LOOP_MAX_VISIBLE_TOKENS,
        LOOP_PRO_THINKING_BUDGET,
    )

    assert LOOP_PRO_THINKING_BUDGET == 1024  # 2.5 Pro cannot go below 128; never 0
    assert LOOP_FLASH_THINKING_BUDGET == 0
    assert LOOP_MAX_VISIBLE_TOKENS == 400


def test_loop_tutor_tier_slots_and_defaults():
    from agents._providers import _DEFAULTS, AgentTask, model_name_for

    assert set(LOOP_TUTOR_SLOTS) <= set(get_args(AgentTask))
    assert _DEFAULTS["loop_tutor_lite"] == "gemini-2.5-flash-lite"
    assert _DEFAULTS["loop_tutor"] == "gemini-2.5-flash"
    assert _DEFAULTS["loop_tutor_deep"] == "gemini-2.5-pro"
    assert model_name_for("loop_tutor") == "gemini-2.5-flash"


def _tool_names(tools) -> set:
    return {getattr(t, "name", None) or getattr(t, "__name__", None) for t in tools}


def test_build_tools_default_is_the_legacy_seven():
    from agents.chat_tutor import _build_tools

    assert _tool_names(_build_tools()) == {
        "search_course_materials",
        "read_session_history_tool",
        "read_user_progress_tool",
        "apply_graph_update_tool",
        "update_mastery_tool",
        "read_graph_neighborhood",
        "read_concepts_for_user",
    }


def test_build_tools_learning_loop_is_the_two_read_tools():
    from agents.chat_tutor import _build_tools

    assert _tool_names(_build_tools(learning_loop=True)) == {
        "search_course_materials",
        "read_graph_neighborhood",
    }


def test_e2e_loop_reply_is_a_valid_loop_turn():
    from agents.function_handlers_e2e import E2E_LOOP_TUTOR_REPLY

    assert E2E_LOOP_TUTOR_REPLY.startswith("[e2e-function-model]")
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", E2E_LOOP_TUTOR_REPLY.strip()) if s]
    assert len(sentences) <= STEP_MAX_SENTENCES
    assert E2E_LOOP_TUTOR_REPLY.count("?") == STEP_QUESTIONS_PER_TURN
    assert "Key idea:" in E2E_LOOP_TUTOR_REPLY  # the loop's turn shape (phase_prefix)


@pytest.mark.parametrize("slot", LOOP_TUTOR_SLOTS)
def test_e2e_loop_handler_is_registered_for_every_slot(slot):
    import sys

    import agents._providers as providers

    providers.clear_function_handlers()
    sys.modules.pop("agents.function_handlers_e2e", None)
    try:
        import agents.function_handlers_e2e as handlers

        assert providers._FUNCTION_HANDLERS[slot] is handlers._loop_tutor_handler
    finally:
        providers.clear_function_handlers()
        sys.modules.pop("agents.function_handlers_e2e", None)
