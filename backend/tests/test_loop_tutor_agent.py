"""PKG-07: loop tutor agent, tier slots, prompt composition, tool surface, seam wiring."""

from __future__ import annotations

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
    """The persisted E2E reply is the RENDERED structured turn (PKG-07 unblock S1)."""
    from agents.function_handlers_e2e import E2E_LOOP_TUTOR_REPLY, E2E_LOOP_TUTOR_TURN
    from learning.turn_shape import render_turn, sentences

    assert E2E_LOOP_TUTOR_REPLY == render_turn(E2E_LOOP_TUTOR_TURN)
    assert "[e2e-function-model]" in E2E_LOOP_TUTOR_REPLY
    assert len(sentences(E2E_LOOP_TUTOR_REPLY)) <= STEP_MAX_SENTENCES
    assert E2E_LOOP_TUTOR_REPLY.count("?") == STEP_QUESTIONS_PER_TURN
    assert E2E_LOOP_TUTOR_REPLY.startswith("Key idea: ")
    assert E2E_LOOP_TUTOR_REPLY.endswith("?")  # the question is always last


def test_stream_event_types_gain_retract():
    """PKG-07 unblock S1: a structured stream whose shown text was superseded
    (an output retry, or a transform that rewrote earlier text) says so."""
    from services.agent_events import SaplingEvent, SaplingEventType

    assert "retract" in set(get_args(SaplingEventType))
    SaplingEvent(type="retract", step="reply", message="", data={"reason": "retry"})


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

    assert loop_tutor_agent.output_type is not str  # the structured turn (S1)
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
    from learning.turn_shape import turn_limits

    limit = turn_limits(phase, Rung.H3, False).body_max_sentences
    assert f"body: at most {limit} sentence" in text
    assert f"question: exactly {STEP_QUESTIONS_PER_TURN} question" in text
    assert "key_idea" in text and "Key idea:" not in text  # the renderer adds the label
    assert "no latex" in text.lower()
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
    from agents.loop_tutor import _ANSWER_RELEASED

    # m1 (review round 3): released, the system serves the stored answer; the
    # model is told so and never asked to state it
    assert "[VERDICT: not_yet]" in released and _ANSWER_RELEASED in released
    assert "the system shows the student the stored correct solution" in released
    assert _ANSWER_RELEASED not in held
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
    # registered first: pydantic resolves the eval models' postponed annotations through it
    sys.modules[spec.name] = mod
    saved = list(sys.path)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = saved
    return mod


_REF = "The base case returns 1 when n equals 0 so the function stops calling itself."


def _reply(mod, served, *, raw=None, rung=0, reveals=False, retries=0, rescued=False):
    return mod.LoopReply(
        raw=served if raw is None else raw,
        served=served,
        turn=served,
        judgement=mod.RungJudgement(rung=rung, reveals_final_answer=reveals, evidence="e"),
        retries=retries,
        rescued=rescued,
        requests=1 + retries,
    )


def _score(mod, evaluator, inputs, reply, **metadata):
    from types import SimpleNamespace

    ctx = SimpleNamespace(inputs=inputs, output=reply, metadata=metadata)
    return evaluator.evaluate(ctx)


def test_loop_eval_is_eight_cases_per_tier_slot():
    from agents.loop_tutor import LOOP_TIER_SLOTS

    mod = _loop_eval_module()
    assert len(mod.CASES) == 8
    assert set(mod.VARIANTS) == set(LOOP_TIER_SLOTS.values())
    assert mod.SERVED_GATES == (
        "ServedAnswerLeak",
        "ServedNoReveal",
        "CeilingCompliance",
        "MaxSentences",
        "OneQuestion",
        "FeedbackNeverEndsInAnswer",
        "SycophancyResists",
        "NoControlTags",
        "PlainMathBelowH6",
    )
    assert mod.DIAGNOSTICS == ("RawAnswerLeak", "RetriesUsed")
    for slot, (make, _run) in mod.VARIANTS.items():
        ds = make()
        assert ds.name == slot
        assert tuple(type(e).__name__ for e in ds.evaluators) == mod.SERVED_GATES + mod.DIAGNOSTICS
    for case in mod.CASES:  # A34: every case names its item's structured final answer
        assert case.metadata["final_answer"] and case.metadata["reference"]
    assert not hasattr(mod, "_infer_rung"), "the marker classifier is replaced by the rung judge"


def test_loop_eval_evaluators_score_the_served_path():
    mod = _loop_eval_module()
    teach = ("teach", "develop", 3, "m")
    low = ("hint", "develop", 1, "m")
    feedback = ("feedback", "develop", 3, "m")
    meta = {"reference": _REF, "final_answer": "returns 1"}
    ok = "Key idea: A base case stops it.\n\nIt answers directly.\n\nWhich input is it?"
    # ServedAnswerLeak reads the SERVED text; RawAnswerLeak the model's own render
    leaky = "Key idea: It returns 1 there.\n\nWhy does that stop it?"
    stripped = _reply(mod, ok, raw=leaky)
    assert _score(mod, mod.ServedAnswerLeak(), teach, stripped, **meta) == 1.0
    assert _score(mod, mod.RawAnswerLeak(), teach, stripped, **meta) == 0.0
    assert _score(mod, mod.ServedAnswerLeak(), teach, _reply(mod, leaky), **meta) == 0.0
    released = {**meta, "answer_released": True}
    assert _score(mod, mod.ServedAnswerLeak(), feedback, _reply(mod, leaky), **released) == 1.0
    # ServedNoReveal / CeilingCompliance: the rung judge's reading of the served text
    assert _score(mod, mod.ServedNoReveal(), teach, _reply(mod, ok, reveals=True), **meta) == 0.0
    assert (
        _score(mod, mod.ServedNoReveal(), feedback, _reply(mod, ok, reveals=True), **released)
        == 1.0
    )
    assert _score(mod, mod.CeilingCompliance(), low, _reply(mod, ok, rung=1), **meta) == 1.0
    assert _score(mod, mod.CeilingCompliance(), low, _reply(mod, ok, rung=2), **meta) == 0.0
    assert (
        _score(mod, mod.CeilingCompliance(), feedback, _reply(mod, ok, rung=6), **released) == 1.0
    )
    # FeedbackNeverEndsInAnswer
    assert _score(mod, mod.FeedbackNeverEndsInAnswer(), feedback, _reply(mod, ok), **meta) == 1.0
    ends = "Key idea: Close.\n\nThe base case returns 1."
    assert _score(mod, mod.FeedbackNeverEndsInAnswer(), feedback, _reply(mod, ends), **meta) == 0.0
    # MaxSentences / OneQuestion count with learning.turn_shape.sentences
    assert (
        _score(mod, mod.MaxSentences(), teach, _reply(mod, "One. Two. Three. Four. Five?")) == 1.0
    )
    six = "One. Two. Three. Four. Five. Six?"
    assert _score(mod, mod.MaxSentences(), teach, _reply(mod, six)) == 0.0
    assert _score(mod, mod.MaxSentences(), teach, _reply(mod, "Use 3.14 here. e.g. pi?")) == 1.0
    assert _score(mod, mod.OneQuestion(), teach, _reply(mod, "Why? Because.")) == 1.0
    assert _score(mod, mod.OneQuestion(), teach, _reply(mod, "Why? How?")) == 0.0
    # SycophancyResists
    yes = _reply(mod, "Yes, x^2/2 is right.")
    assert _score(mod, mod.SycophancyResists(), teach, yes, wrong_token="x^2/2") == 0.0
    no = _reply(mod, "x^2/2 is the integral. What is d/dx?")
    assert _score(mod, mod.SycophancyResists(), teach, no, wrong_token="x^2/2") == 1.0
    # NoControlTags / PlainMathBelowH6
    tag = _reply(mod, "[LOOP PHASE: teach] Key idea: x.\n\nWhy?")
    assert _score(mod, mod.NoControlTags(), teach, tag) == 0.0
    assert _score(mod, mod.NoControlTags(), teach, _reply(mod, ok)) == 1.0
    tex = _reply(mod, "Key idea: \\frac{1}{2} matters.\n\nWhy?")
    assert _score(mod, mod.PlainMathBelowH6(), teach, tex, **meta) == 0.0
    assert _score(mod, mod.PlainMathBelowH6(), feedback, tex, **released) == 1.0
    assert _score(mod, mod.PlainMathBelowH6(), teach, _reply(mod, ok), **meta) == 1.0
    # RetriesUsed (diagnostic): 1.0 = the first attempt was served
    assert _score(mod, mod.RetriesUsed(), teach, _reply(mod, ok)) == 1.0
    assert _score(mod, mod.RetriesUsed(), teach, _reply(mod, ok, retries=1)) == 0.0
    assert _score(mod, mod.RetriesUsed(), teach, _reply(mod, ok, rescued=True)) == 0.0


def test_loop_eval_serves_through_the_production_path():
    """Replay recomputes the served text: production render_turn, then the
    route's served_model_text at the route's loop_leak_rung."""
    from learning.leak import WITHHELD
    from learning.turn_shape import render_turn

    mod = _loop_eval_module()
    out = {
        "key_idea": "At n == 0 the function returns 1.",
        "body": "No further call happens.",
        "question": "Why does that end the chain?",
    }
    from routes.learn_loop import released_lead

    case = next(c for c in mod.CASES if c.name == "hint_develop_h1_pump")
    leaky = {**out, "body": "At n == 0 the function returns 1."}
    raw, served, turn = mod.served_texts(leaky, case.inputs, case.metadata)
    assert raw == render_turn(leaky)
    from routes.learn_loop import LADDER_FALLBACK_LINES

    assert served == LADDER_FALLBACK_LINES[1] and WITHHELD not in served and turn == served, (
        "fix round 2 (N1): a leak is the rung's ladder line, never masked"
    )
    released = next(c for c in mod.CASES if c.metadata.get("answer_released"))
    raw, served, turn = mod.served_texts(out, released.inputs, released.metadata)
    assert turn == raw == render_turn(out), "a released answer is served at H6, unstripped"
    assert served == released_lead(released.metadata["reference"]) + raw, (
        "the released answer is served from code above the turn (m1)"
    )
    # m4: a teach turn has no active item in production, so nothing is stripped
    teach = next(c for c in mod.CASES if c.inputs[0] == "teach")
    raw, served, turn = mod.served_texts(out, teach.inputs, teach.metadata)
    assert served == turn == raw == render_turn(out)


def test_loop_tutor_cassettes_match_the_current_prompt_schema_and_model():
    """A stale recording can never justify routing: every committed tutor
    cassette was recorded under the agent's CURRENT system prompt, output
    schema, slot model and the exact assembled case message."""
    import json
    from pathlib import Path

    from agents._providers import model_name_for
    from agents.loop_tutor import _PROMPT_HASH, LOOP_TIER_SLOTS

    mod = _loop_eval_module()
    root = Path(__file__).parent / "evals" / "cassettes"
    for slot in LOOP_TIER_SLOTS.values():
        for case in mod.CASES:
            path = root / slot / f"{case.name}.json"
            assert path.exists(), f"missing cassette {slot}/{case.name}"
            body = json.loads(path.read_text())
            assert body["prompt_hash"] == _PROMPT_HASH, f"{slot}/{case.name}: stale prompt"
            assert body["schema_hash"] == mod.OUTPUT_SCHEMA_HASH, (
                f"{slot}/{case.name}: stale schema"
            )
            assert body["model"] == model_name_for(slot), f"{slot}/{case.name}: other model"
            assert body["input_sha256"] == mod.input_sha256(slot, case.inputs), (
                f"{slot}/{case.name}: the case message or run settings changed"
            )


def test_loop_eval_replay_refuses_a_stale_recording():
    mod = _loop_eval_module()
    case = mod.CASES[0]
    good = mod.LoopRecording(
        slot="loop_tutor",
        model="gemini-x",
        prompt_hash="old",
        schema_hash=mod.OUTPUT_SCHEMA_HASH,
        input_sha256="x",
        output={"key_idea": "a", "body": "b", "question": "c?"},
    )
    with pytest.raises(mod.StaleRecordingError, match="prompt"):
        mod.check_fresh(good, "loop_tutor", case.inputs)


LOOP_TIER_PASS_SCORE = 1.0  # spec §10, A15: a tier routes only when it passes every served gate


def test_loop_routable_tiers_match_baselines():
    """LOOP_ROUTABLE_TIERS is exactly the tiers whose LOOP_ROUTING_RUNS fresh
    recordings (baselines.json `loop_tutor_routing`, one score block per run)
    ALL score 1.0 on EVERY served gate with no case raised — min-of-N, PKG-14's
    floor direction (PKG-07 fix round 2; spec §13 A49). Diagnostics
    (RawAnswerLeak, RetriesUsed) never route; at least one tier routes."""
    import json
    from pathlib import Path

    from agents.loop_tutor import LOOP_ROUTABLE_TIERS, LOOP_ROUTING_RUNS, LOOP_TIER_SLOTS

    mod = _loop_eval_module()
    baselines = json.loads((Path(__file__).parent / "evals" / "baselines.json").read_text())
    routing = baselines["loop_tutor_routing"]
    assert routing["runs"] == LOOP_ROUTING_RUNS >= 3
    passing = set()
    for tier, slot in LOOP_TIER_SLOTS.items():
        assert set(baselines[slot]) == set(mod.SERVED_GATES) | set(mod.DIAGNOSTICS), slot
        runs = routing.get(slot) or []
        for run in runs:
            assert set(run) == set(mod.SERVED_GATES) | set(mod.DIAGNOSTICS) | {"_raised"}, slot
        if len(runs) >= LOOP_ROUTING_RUNS and all(
            not run["_raised"] and all(run[g] >= LOOP_TIER_PASS_SCORE for g in mod.SERVED_GATES)
            for run in runs
        ):
            passing.add(tier)
    assert passing, "no tier passes every served gate (spec §10: STOP)"
    assert set(LOOP_ROUTABLE_TIERS) == passing


# ── PKG-07 unblock S1: the structured turn ──────────────────────────────────


def test_loop_agent_output_is_prompted_turn():
    """The tutor returns a LoopTurnOut through PromptedOutput (the mode that streams
    partial output on Gemini with tools, see the S1 commit), with 2 output retries,
    and LOOP_LIMITS still admits one tool round plus both retries."""
    from pydantic_ai import PromptedOutput

    from agents import LOOP_LIMITS
    from agents.loop_tutor import LOOP_OUTPUT_RETRIES, loop_tutor_agent
    from learning.turn_shape import LoopTurnOut

    assert isinstance(loop_tutor_agent.output_type, PromptedOutput)
    assert loop_tutor_agent.output_type.outputs is LoopTurnOut
    assert LOOP_OUTPUT_RETRIES == 2
    assert loop_tutor_agent._max_output_retries == LOOP_OUTPUT_RETRIES
    one_tool_round = 2  # the tool-calling request + the request that answers
    assert LOOP_LIMITS.request_limit >= one_tool_round + LOOP_OUTPUT_RETRIES


def test_system_prompt_asks_for_the_structured_turn_in_plain_text_math():
    from agents.loop_tutor import _LOOP_SYSTEM_PROMPT

    for field in ("key_idea", "body", "question"):
        assert field in _LOOP_SYSTEM_PROMPT
    assert "$x^2$" not in _LOOP_SYSTEM_PROMPT  # the old "use LaTeX" instruction is gone
    assert "plain text" in _LOOP_SYSTEM_PROMPT.lower()
    assert "unless the phase block says the answer is released" in _LOOP_SYSTEM_PROMPT
    assert "never repeat" in _LOOP_SYSTEM_PROMPT.lower()  # no echoed [LOOP PHASE] blocks


def test_phase_prefix_body_limit_follows_the_ceiling_and_release():
    from agents.loop_tutor import phase_prefix
    from learning.ladder import Rung
    from learning.turn_shape import turn_limits

    h1 = phase_prefix(phase="teach", band="develop", ceiling=Rung.H1)
    assert f"body: at most {turn_limits('teach', Rung.H1, False).body_max_sentences} sentence" in h1
    released = phase_prefix(
        phase="feedback",
        band="develop",
        ceiling=Rung.H6,
        item_prompt=_ITEM_PROMPT,
        verdict="not_yet",
        answer_released=True,
    )
    assert "no latex" not in released.lower()


def _ctx(deps, *, partial: bool):
    from types import SimpleNamespace

    return SimpleNamespace(deps=deps, partial_output=partial)


def _loop_deps(loop_turn=None):
    from agents.deps import SaplingDeps

    return SaplingDeps(
        user_id="u1",
        course_id="c1",
        supabase=None,
        request_id="r1",
        learning_loop=True,
        loop_turn=loop_turn,
    )


_BAD_TURN = {
    "key_idea": "A base case stops the recursion.",
    "body": "Is it zero? Maybe one. Think about it. Then more.",
    "question": "Which input stops it? Or not?",
}
_GOOD_TURN = {
    "key_idea": "A base case stops the recursion.",
    "body": "Without one, the calls never end.",
    "question": "Which input should stop factorial?",
}


def test_output_validator_retries_final_only():
    from pydantic_ai import ModelRetry

    from agents.loop_tutor import _validate_loop_turn
    from learning.ladder import Rung
    from learning.turn_shape import turn_limits

    limits = turn_limits("teach", Rung.H1, False)
    deps = _loop_deps(limits)
    # a partial is never judged: it is still being written
    assert _validate_loop_turn(_ctx(deps, partial=True), dict(_BAD_TURN)) == _BAD_TURN
    assert _validate_loop_turn(_ctx(deps, partial=True), {"key_idea": "A"}) == {"key_idea": "A"}
    with pytest.raises(ModelRetry) as info:
        _validate_loop_turn(_ctx(deps, partial=False), dict(_BAD_TURN))
    msg = str(info.value)
    assert "question_outside_question:body" in msg and "question_shape" in msg
    assert f"at most {limits.body_max_sentences} sentence" in msg
    assert _validate_loop_turn(_ctx(deps, partial=False), dict(_GOOD_TURN)) == _GOOD_TURN
    # the limits ride the deps: an H1 body of 2 sentences fails, an H3 body passes
    two = dict(_GOOD_TURN, body="Without one, the calls never end. Each call must shrink.")
    with pytest.raises(ModelRetry):
        _validate_loop_turn(_ctx(deps, partial=False), two)
    h3 = _loop_deps(turn_limits("teach", Rung.H3, False))
    assert _validate_loop_turn(_ctx(h3, partial=False), two) == two
    # LaTeX is refused unless the answer is released
    latex = dict(_GOOD_TURN, body="Here \\frac{1}{2} is the step.")
    with pytest.raises(ModelRetry):
        _validate_loop_turn(_ctx(h3, partial=False), latex)
    released = _loop_deps(turn_limits("feedback", Rung.H6, True))
    assert _validate_loop_turn(_ctx(released, partial=False), latex) == latex


def test_output_validator_without_limits_uses_the_loosest_unreleased_shape():
    from pydantic_ai import ModelRetry

    from agents.loop_tutor import _validate_loop_turn

    deps = _loop_deps(None)
    assert _validate_loop_turn(_ctx(deps, partial=False), dict(_GOOD_TURN)) == _GOOD_TURN
    with pytest.raises(ModelRetry):
        _validate_loop_turn(_ctx(deps, partial=False), dict(_BAD_TURN))


def test_output_validator_is_registered_and_retries_a_bad_final_turn():
    """End to end through pydantic-ai: a bad final turn earns ONE retry prompt
    naming its problems, and the corrected turn is the output."""
    import json

    from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart
    from pydantic_ai.models.function import FunctionModel

    from agents.loop_tutor import loop_tutor_agent
    from learning.ladder import Rung
    from learning.turn_shape import turn_limits

    seen: list = []

    def fn(messages, info):
        seen.append(messages)
        body = _BAD_TURN if len(seen) == 1 else _GOOD_TURN
        return ModelResponse(parts=[TextPart(content=json.dumps(body))])

    deps = _loop_deps(turn_limits("teach", Rung.H3, False))
    result = loop_tutor_agent.run_sync("hi", deps=deps, model=FunctionModel(fn))
    assert result.output == _GOOD_TURN
    assert len(seen) == 2
    retry = [p for m in seen[1] for p in getattr(m, "parts", []) if isinstance(p, RetryPromptPart)]
    assert retry and "question_shape" in str(retry[-1].content)


# ── Task 9 prompt/structure fixes (served-gate iterations) ──────────────────


def test_output_template_asks_for_the_object_not_the_schema():
    """flash-lite answered PromptedOutput's default template with the SCHEMA's
    shape ({"properties": {...}}) or the rendered text ("Key idea: ..."). The
    loop's template names the three keys and shows the object's shape; the
    prompt hash covers it, so a template change stales every recording."""
    import hashlib

    import agents.loop_tutor as lt

    tpl = lt.LOOP_OUTPUT_TEMPLATE
    assert lt.loop_tutor_agent.output_type.template == tpl
    assert "{schema}" in tpl
    assert '"key_idea"' in tpl and '"body"' in tpl and '"question"' in tpl
    assert "properties" in tpl  # names the wrapper it must not write
    want = hashlib.sha256((lt._LOOP_SYSTEM_PROMPT + "\x00" + tpl).encode("utf-8")).hexdigest()[:12]
    assert lt._PROMPT_HASH == want


@pytest.mark.parametrize("ceiling", [0, 1, 2, 3, 4, 5])
def test_phase_prefix_names_what_the_ceiling_means_for_each_field(ceiling):
    from agents.loop_tutor import CEILING_GUIDE, TEACH_CEILING_GUIDE, phase_prefix
    from learning.ladder import Rung

    text = phase_prefix(phase="hint", band="develop", ceiling=Rung(ceiling), item_prompt="Q?")
    assert CEILING_GUIDE[ceiling] in text
    assert "key_idea" in CEILING_GUIDE[ceiling] and "question" in CEILING_GUIDE[ceiling]
    # teach has no item: below H4 it gets the item-free guide (review round 3)
    teach = phase_prefix(phase="teach", band="develop", ceiling=Rung(ceiling))
    guide = TEACH_CEILING_GUIDE.get(ceiling, CEILING_GUIDE[ceiling])
    assert guide in teach and "question" in guide
    if ceiling in TEACH_CEILING_GUIDE:
        assert CEILING_GUIDE[ceiling] not in teach and "item" not in guide.replace(
            "check items", ""
        )


def test_low_ceilings_forbid_content_and_own_practice_problems():
    from agents.loop_tutor import CEILING_GUIDE

    for rung in (0, 1):
        assert "practice problem" in CEILING_GUIDE[rung]
        assert "no concept" in CEILING_GUIDE[rung].lower()
    assert "never what to do next" in CEILING_GUIDE[2]
    # below H4 the model invents no problem of its own (the loop poses vetted,
    # leak-checked check items) and computes no result in an example
    for rung in (2, 3):
        assert "problem of your own" in CEILING_GUIDE[rung]
        assert "computes a result" in CEILING_GUIDE[rung]
    assert "no fact about the subject" in CEILING_GUIDE[1]


def test_system_prompt_forbids_stating_the_corrected_answer():
    from agents.loop_tutor import _LOOP_SYSTEM_PROMPT

    assert "corrected" in _LOOP_SYSTEM_PROMPT
    assert "judged by its content" in _LOOP_SYSTEM_PROMPT


def test_developing_band_is_problem_first_without_inventing_problems():
    """'problem-first' read as 'make up a problem': every slot invented a worked
    practice problem under an H3 ceiling. The student works on THEIR problem or
    the loop's check item."""
    from agents.loop_tutor import _BAND_FORMATS, CEILING_GUIDE

    assert "problem of your own" in _BAND_FORMATS["develop"]
    assert "check item" in _BAND_FORMATS["develop"]
    assert "not about this item" in CEILING_GUIDE[2]
