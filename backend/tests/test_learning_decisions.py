"""PKG-05b: the typed decision seam (spec §3.6, §6, §8.24–25, §13 A24). Hermetic:
FunctionModel for the decision agent; the grader stubbed at agents.grader.grade;
events captured by patching events_service.log_event. No DB, no network."""

from __future__ import annotations

import pathlib
import re
import sys

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from agents.deps import SaplingDeps

BACKEND = pathlib.Path(__file__).resolve().parents[1]
QUESTION = "Why does every recursive function need a base case?"
REFERENCE = "The base case stops the recursion; without it the stack grows until overflow."
RUBRIC = {"r1": "names the base case", "r2": "explains unbounded growth"}
WRONG = {
    "w_loop": "confuses recursion with a loop",
    "w_speed": "says the base case is only for speed",
}


def _deps(**over) -> SaplingDeps:
    kw = dict(
        user_id="u1",
        course_id="c1",
        supabase=None,
        request_id="r1",
        session_id="s1",
        feature="tutor",
        learning_loop=True,
    )
    return SaplingDeps(**{**kw, **over})


def _scripted(outputs: list[dict]):
    """FunctionModel emitting each dict in turn through the run's output tool."""
    calls = {"n": 0, "prompts": []}

    def handler(messages, info):
        calls["prompts"].append(messages[-1].parts[-1].content)
        payload = outputs[min(calls["n"], len(outputs) - 1)]
        calls["n"] += 1
        return ModelResponse(
            parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=payload)]
        )

    return FunctionModel(handler), calls


@pytest.fixture
def events(monkeypatch):
    from services import events_service

    got: list[tuple[str, dict]] = []
    monkeypatch.setattr(events_service, "log_event", lambda et, **kw: got.append((et, kw)))
    return got


def _kinds(events) -> list[str]:
    return [et for et, _ in events]


@pytest.fixture
def _function_lane(monkeypatch):
    """Cold seam, env-module lane (the test_e2e_function_handlers posture)."""
    import agents._providers as providers

    providers.clear_function_handlers()
    monkeypatch.setattr(providers, "_ENV_HANDLERS_LOADED", False)
    sys.modules.pop("agents.function_handlers_e2e", None)
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    yield
    providers.clear_function_handlers()
    sys.modules.pop("agents.function_handlers_e2e", None)


# ── Task 2: decision agent, slot, function handler ─────────────────────────


def test_decision_slot_is_flash_lite_thinking_off_one_prompt(monkeypatch):
    from agents import decision as d
    from agents._providers import _DEFAULTS, model_name_for

    monkeypatch.delenv("SAPLING_MODEL_DECISION", raising=False)
    assert _DEFAULTS["decision"] == model_name_for("decision") == "gemini-2.5-flash-lite"
    assert d.decision_agent.model_settings["google_thinking_config"].thinking_budget == 0
    src = (BACKEND / "agents" / "decision.py").read_text()
    assert src.count("_SYSTEM_PROMPT = ") == 1 and len(re.findall(r"\bAgent[\[(]", src)) == 1
    text = d.build_decision_message(
        "Which?", [("STUDENT ANSWER", "a loop")], [("w_loop", "l"), ("w_speed", "s")]
    )
    assert text.startswith("QUESTION: Which?") and "\nSTATE:\nSTUDENT ANSWER:\na loop" in text
    assert re.findall(r"^OPTION (\S+):", text, re.M) == ["w_loop", "w_speed"]


def test_e2e_decision_handler_serves_both_output_types(_function_lane):
    from agents._providers import model_for
    from agents.decision import DecisionPickOutput, build_decision_message, decision_agent
    from agents.function_handlers_e2e import E2E_DECISION_CONFIDENCE, E2E_DECISION_YES_TOKEN

    opts = [("w_loop", "loop"), ("w_speed", "speed")]
    hit = build_decision_message(f"Q {E2E_DECISION_YES_TOKEN}", [("S", "x")], opts)
    miss = build_decision_message("Q", [("S", "x")], opts)
    with decision_agent.override(model=model_for("decision")):
        picks = [
            decision_agent.run_sync(m, deps=_deps(), output_type=DecisionPickOutput).output
            for m in (hit, miss)
        ]
        yes, no = (decision_agent.run_sync(m, deps=_deps()).output for m in (hit, miss))
    assert [p.choice for p in picks] == ["w_loop", "none"] and (yes.answer, no.answer) == (
        "yes",
        "no",
    )
    assert yes.confidence == picks[1].confidence == E2E_DECISION_CONFIDENCE
