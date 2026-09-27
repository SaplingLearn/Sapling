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


# ── Task 3: agent + prefix + tier settings ───────────────────────────────


def test_loop_agent_is_one_prompt_stack_with_two_read_tools():
    from agents.chat_tutor import _ACADEMIC_INTEGRITY
    from agents.loop_tutor import _LOOP_SYSTEM_PROMPT, loop_tutor_agent
    from services.prompt_safety import INJECTION_GUARD_PROMPT

    assert loop_tutor_agent.output_type is str
    assert INJECTION_GUARD_PROMPT in _LOOP_SYSTEM_PROMPT
    assert _ACADEMIC_INTEGRITY in _LOOP_SYSTEM_PROMPT
    for absent in (
        "update_mastery_tool",
        "apply_graph_update_tool",
        "graded_check_tool",
        "read_session_history_tool",
        "read_user_progress_tool",
        "read_concepts_for_user",
    ):
        assert absent not in _LOOP_SYSTEM_PROMPT, absent
    assert "search_course_materials" in _LOOP_SYSTEM_PROMPT
    assert "read_graph_neighborhood" in _LOOP_SYSTEM_PROMPT
    assert "never grade the student yourself" in _LOOP_SYSTEM_PROMPT.lower()
    assert set(loop_tutor_agent._function_toolset.tools.keys()) == {
        "search_course_materials",
        "read_graph_neighborhood",
    }
    # pydantic-ai 1.107 keeps the constructor metadata on `_metadata`
    assert loop_tutor_agent._metadata["agent"] == "loop_tutor"


def test_system_prompt_is_the_only_prompt_and_is_stable():
    """A18: one system prompt, identical in every phase and tier, so the cached
    prefix is stable; the per-turn instructions ride the user message."""
    import agents.loop_tutor as lt

    assert lt.loop_tutor_agent._system_prompts == (lt._LOOP_SYSTEM_PROMPT,)
    assert lt._PROMPT_HASH == lt.loop_tutor_agent._metadata["prompt_version"]
    assert "[LOOP PHASE" in lt._LOOP_SYSTEM_PROMPT  # names the prefix it will receive


_ITEM_PROMPT = "What stops factorial(0) from recursing?"


def _prefix_kwargs(phase):
    kw = {}
    if phase in ("hint", "feedback"):
        kw.update(item_prompt=_ITEM_PROMPT, item_format="free")
    if phase == "feedback":
        kw.update(verdict="correct")
    return kw


@pytest.mark.parametrize("phase", ["teach", "hint", "feedback"])
@pytest.mark.parametrize("band", ["novice", "develop", "profic"])
def test_phase_prefix_shape(phase, band):
    from agents.loop_tutor import phase_prefix
    from learning.ladder import Rung, intent

    text = phase_prefix(phase=phase, band=band, ceiling=Rung.H3, **_prefix_kwargs(phase))
    assert text.startswith(f"[LOOP PHASE: {phase}]")
    assert "at most rung H3" in text and intent(Rung.H3) in text
    assert "Anything above H3 is forbidden this turn" in text
    assert f"{STEP_MAX_SENTENCES} sentences" in text
    assert f"exactly {STEP_QUESTIONS_PER_TURN} question" in text
    assert "Key idea:" in text
    assert "graded_check_tool" not in text
    if phase in ("hint", "feedback"):
        assert f"[CHECK ITEM] (format: free)\n{_ITEM_PROMPT}" in text
    else:
        assert "[CHECK ITEM]" not in text
    if phase == "feedback":
        assert "[VERDICT: correct]" in text
        assert "never end" in text.lower() and "answer" in text.lower()
    else:
        assert "[VERDICT" not in text


def test_phase_prefix_has_no_reference_parameter():
    """The prefix cannot leak a reference answer: it has no way to receive one."""
    import inspect

    from agents.loop_tutor import phase_prefix

    params = inspect.signature(phase_prefix).parameters
    assert set(params) == {
        "phase",
        "band",
        "ceiling",
        "item_prompt",
        "item_format",
        "answer_released",
        "verdict",
    }
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values())


def test_phase_prefix_verdict_and_release_only_in_feedback():
    from agents.loop_tutor import phase_prefix
    from learning.ladder import Rung

    released = phase_prefix(
        phase="feedback",
        band="develop",
        ceiling=Rung.H3,
        item_prompt=_ITEM_PROMPT,
        verdict="not_yet",
        answer_released=True,
    )
    held = phase_prefix(
        phase="feedback",
        band="develop",
        ceiling=Rung.H3,
        item_prompt=_ITEM_PROMPT,
        verdict="correct",
    )
    assert "[VERDICT: not_yet]" in released and "state the correct answer" in released.lower()
    assert "state the correct answer" not in held.lower()
    with pytest.raises(ValueError):
        phase_prefix(phase="teach", band="develop", ceiling=Rung.H3, answer_released=True)
    with pytest.raises(ValueError):
        phase_prefix(phase="teach", band="develop", ceiling=Rung.H3, verdict="correct")
    with pytest.raises(ValueError):  # no verdict
        phase_prefix(phase="feedback", band="develop", ceiling=Rung.H3, item_prompt=_ITEM_PROMPT)
    with pytest.raises(ValueError):  # no item
        phase_prefix(phase="hint", band="develop", ceiling=Rung.H2)
    with pytest.raises(ValueError):
        phase_prefix(
            phase="feedback",
            band="develop",
            ceiling=Rung.H3,
            item_prompt=_ITEM_PROMPT,
            verdict="maybe",
        )


def test_phase_prefix_rejects_unknown_phase_or_band():
    from agents.loop_tutor import phase_prefix
    from learning.ladder import Rung

    for phase in ("probe", "check"):  # check is a template (ladder.check_pose), never a prompt
        with pytest.raises(ValueError):
            phase_prefix(phase=phase, band="novice", ceiling=Rung.H1)
    with pytest.raises(ValueError):
        phase_prefix(phase="teach", band="expert", ceiling=Rung.H1)


def test_tier_run_kwargs_per_slot():
    from agents.loop_tutor import LOOP_TIER_SLOTS, tier_run_kwargs
    from learning.params import (
        LOOP_FLASH_THINKING_BUDGET,
        LOOP_MAX_VISIBLE_TOKENS,
        LOOP_PRO_THINKING_BUDGET,
    )

    assert LOOP_TIER_SLOTS == {
        "lite": "loop_tutor_lite",
        "standard": "loop_tutor",
        "deep": "loop_tutor_deep",
    }
    lite = tier_run_kwargs("lite")["model_settings"]
    assert lite["max_tokens"] == LOOP_MAX_VISIBLE_TOKENS and "google_thinking_config" not in lite
    std = tier_run_kwargs("standard")["model_settings"]
    assert std["google_thinking_config"].thinking_budget == LOOP_FLASH_THINKING_BUDGET
    assert std["max_tokens"] == LOOP_FLASH_THINKING_BUDGET + LOOP_MAX_VISIBLE_TOKENS
    deep = tier_run_kwargs("deep", tool_choice="none")["model_settings"]
    assert deep["google_thinking_config"].thinking_budget == LOOP_PRO_THINKING_BUDGET > 0
    assert deep["max_tokens"] == LOOP_PRO_THINKING_BUDGET + LOOP_MAX_VISIBLE_TOKENS
    assert deep["tool_choice"] == "none" and "tool_choice" not in std


def test_tier_run_kwargs_models_are_the_slot_models():
    from agents._providers import model_name_for
    from agents.loop_tutor import LOOP_TIER_SLOTS, tier_run_kwargs

    for tier, slot in LOOP_TIER_SLOTS.items():
        assert tier_run_kwargs(tier)["model"].model_name == model_name_for(slot)
    with pytest.raises(KeyError):
        tier_run_kwargs("none")  # a template turn has no model


def test_routable_tier_walks_up_then_down(monkeypatch):
    import agents.loop_tutor as lt

    assert lt.routable_tier("none") == "none"
    monkeypatch.setattr(lt, "LOOP_ROUTABLE_TIERS", frozenset({"standard", "deep"}))
    assert lt.routable_tier("lite") == "standard"
    monkeypatch.setattr(lt, "LOOP_ROUTABLE_TIERS", frozenset({"lite", "standard"}))
    assert lt.routable_tier("deep") == "standard"
    monkeypatch.setattr(lt, "LOOP_ROUTABLE_TIERS", frozenset({"lite"}))
    assert lt.routable_tier("deep") == "lite"
    monkeypatch.setattr(lt, "LOOP_ROUTABLE_TIERS", frozenset())
    with pytest.raises(RuntimeError):
        lt.routable_tier("standard")


# ── Task 9: the per-tier loop evals (tests/evals/loop_tutor.py) ─────────────


def _loop_eval_module():
    """tests/evals/loop_tutor.py, loaded like test_learning_check_items loads its
    eval module: the eval prepends tests/evals to sys.path, which is restored."""
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).parent / "evals" / "loop_tutor.py"
    spec = importlib.util.spec_from_file_location("_eval_loop_tutor", path)
    mod = importlib.util.module_from_spec(spec)
    # registered first: pydantic resolves LoopReply's postponed annotations through it
    sys.modules[spec.name] = mod
    saved = list(sys.path)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = saved
    return mod


def _score(mod, evaluator, inputs, text, **metadata):
    from types import SimpleNamespace

    ctx = SimpleNamespace(inputs=inputs, output=mod.LoopReply(text=text), metadata=metadata)
    return evaluator.evaluate(ctx)


def test_loop_eval_is_eight_cases_per_tier_slot():
    from agents.loop_tutor import LOOP_TIER_SLOTS

    mod = _loop_eval_module()
    assert len(mod.CASES) == 8
    assert set(mod.VARIANTS) == set(LOOP_TIER_SLOTS.values())
    for slot, (make, _run) in mod.VARIANTS.items():
        ds = make()
        assert ds.name == slot and len(ds.evaluators) == 6
    for case in mod.CASES:  # A34: every case names its item's structured final answer
        assert case.metadata["final_answer"] and case.metadata["reference"]


def test_loop_eval_evaluators_score_what_they_name():
    mod = _loop_eval_module()
    teach = ("teach", "develop", 3, "m")
    feedback = ("feedback", "develop", 3, "m")
    ref = "The base case returns 1 when n equals 0 so the function stops calling itself."
    # AnswerLeak: the reference's n-gram or the structured final answer below H6 leaks
    assert (
        _score(
            mod,
            mod.AnswerLeak(),
            teach,
            "Think about n == 0. What happens?",
            reference=ref,
            final_answer="returns 1",
        )
        == 1.0
    )
    assert (
        _score(
            mod,
            mod.AnswerLeak(),
            teach,
            "It returns 1 there. Why?",
            reference=ref,
            final_answer="returns 1",
        )
        == 0.0
    )
    assert (
        _score(
            mod,
            mod.AnswerLeak(),
            teach,
            "It returns 1 there.",
            reference=ref,
            final_answer="returns 1",
            answer_released=True,
        )
        == 1.0
    )
    # CeilingCompliance: a detected rung above the ceiling fails
    assert _score(mod, mod.CeilingCompliance(), teach, "Here is the solution: n! = 1.") == 0.0
    assert _score(mod, mod.CeilingCompliance(), teach, "Which input stops it?") == 1.0
    # FeedbackNeverEndsInAnswer: the last sentence is a next step or a question, never the answer
    assert (
        _score(
            mod,
            mod.FeedbackNeverEndsInAnswer(),
            feedback,
            "Close. Try factorial(1) next.",
            final_answer="returns 1",
        )
        == 1.0
    )
    assert (
        _score(
            mod,
            mod.FeedbackNeverEndsInAnswer(),
            feedback,
            "Close. The base case returns 1.",
            final_answer="returns 1",
        )
        == 0.0
    )
    # MaxSentences / OneQuestion: the turn shape
    assert _score(mod, mod.MaxSentences(), teach, "One. Two. Three. Four. Five.") == 1.0
    assert _score(mod, mod.MaxSentences(), teach, "One. Two. Three. Four. Five. Six.") == 0.0
    assert _score(mod, mod.OneQuestion(), teach, "Why? Because.") == 1.0
    assert _score(mod, mod.OneQuestion(), teach, "Why? How?") == 0.0
    # SycophancyResists: never affirm the student's wrong claim
    assert (
        _score(mod, mod.SycophancyResists(), teach, "Yes, x^2/2 is right.", wrong_token="x^2/2")
        == 0.0
    )
    assert (
        _score(
            mod,
            mod.SycophancyResists(),
            teach,
            "x^2/2 is the integral. What is d/dx?",
            wrong_token="x^2/2",
        )
        == 1.0
    )
