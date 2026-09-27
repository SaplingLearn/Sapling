"""PKG-05: grader agent (+ grader_second) + grade_answer + flush_pending.

Hermetic: the grader agent runs on a FunctionModel; grade_answer's one seam
(the module-level `grade`) is stubbed; apply_graph_update is a spy. Nothing
here may touch table() for a graph table. Items are real, decrypted
`learning.checks.CheckItem`s (HANDOFF-04: rubric / common_wrong are models,
and the correct option's `wrong_key` is None)."""
from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

import pytest
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from agents import GRADER_LIMITS
from agents.deps import SaplingDeps
from learning.checks import CheckItem, Option, RubricItem, WrongReason
from learning.params import (
    GRADER_LIMITS as GRADER_LIMITS_SPEC,
    GRADER_LOW_CONFIDENCE,
    GRADER_SECOND_OPINION_CONFIDENCE,
    GRADER_SECOND_OPINION_SLOT,
)

REFERENCE = "The base case stops the recursion; without it the stack grows until overflow."
NODE = "node-recursion"


def _item(**over) -> CheckItem:
    """A decrypted CheckItem (A2 keys, A22 columns)."""
    base = dict(
        id="ci-1",
        course_id="c1",
        concept_key="recursion",
        format="free",
        difficulty=1,
        prompt="Why does every recursive function need a base case?",
        reference_answer=REFERENCE,
        rubric=[RubricItem(id="r1", text="names the base case"),
                RubricItem(id="r2", text="explains unbounded growth")],
        common_wrong=[WrongReason(key="w_loop", text="confuses recursion with a loop")],
        options=None,
        correct_option=None,
        answer_kind="free",
        canonical_answer=None,
        tolerance=None,
        canonical_verified=False,
        stepwise=False,
        source_chunk_ids=[],
        question_hash="qh-1",
    )
    base.update(over)
    return CheckItem(**base)


def _mc_item(**over) -> CheckItem:
    options = [Option(letter=letter, text=text, wrong_key=key) for letter, text, key in (
        ("A", "It stops the recursion", None),
        ("B", "It makes recursion faster", "w_speed"),
        ("C", "Recursion is a loop that ends on its own", "w_loop"),
    )]
    base = dict(format="mc_reason", options=options, correct_option="A",
                common_wrong=[WrongReason(key="w_loop", text="confuses recursion with a loop"),
                              WrongReason(key="w_speed", text="says the base case is only for speed")])
    base.update(over)
    return _item(**base)


def _numeric_item(**over) -> CheckItem:
    base = dict(answer_kind="numeric", canonical_answer="9.81", tolerance=0.01, canonical_verified=True)
    base.update(over)
    return _item(**base)


def _deps(**over) -> SaplingDeps:
    kw = dict(user_id="u1", course_id="c1", supabase=None, request_id="r1",
              session_id="s1", feature="tutor", learning_loop=True)
    kw.update(over)
    return SaplingDeps(**kw)


def _scripted_grader(outputs: list[dict]):
    """A FunctionModel that emits each dict in turn through the output tool."""
    calls = {"n": 0}

    def handler(messages, info):
        payload = outputs[min(calls["n"], len(outputs) - 1)]
        calls["n"] += 1
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=payload)])

    return FunctionModel(handler), calls


def _good(conf: float = 0.9) -> dict:
    return {"item_results": ["r1:yes", "r2:yes"], "confidence": conf,
            "matched_wrong_key": "", "feedback_hint": "Think about what stops the calls."}


def _partial(conf: float = 0.9) -> dict:
    return {**_good(conf), "item_results": ["r1:yes", "r2:no"], "matched_wrong_key": "w_loop"}


# ── grader agent ──────────────────────────────────────────────────────────


def test_build_grader_message_has_every_section():
    from agents.grader import build_grader_message

    text = build_grader_message(_item(), format="free", student_answer="It stops the calls.")
    assert "QUESTION:" in text and REFERENCE in text and "FORMAT: free" in text
    assert re.search(r"^RUBRIC ITEM r1:", text, re.M) and re.search(r"^RUBRIC ITEM r2:", text, re.M)
    assert re.search(r"^COMMON WRONG REASON w_loop:", text, re.M) and text.rstrip().endswith("It stops the calls.")
    assert GRADER_LIMITS.tool_calls_limit == 0


def test_grader_limits_are_the_spec_values():
    """agents.GRADER_LIMITS is built from learning.params.GRADER_LIMITS (spec §3.4;
    one value, one name) — never retyped."""
    assert GRADER_LIMITS.request_limit == GRADER_LIMITS_SPEC["request_limit"]
    assert GRADER_LIMITS.tool_calls_limit == GRADER_LIMITS_SPEC["tool_calls_limit"]
    assert GRADER_LIMITS.total_tokens_limit == GRADER_LIMITS_SPEC["total_tokens_limit"]


def test_parse_item_results_is_strict():
    from agents.grader import parse_item_results

    got = parse_item_results(["r1:yes", "r2:NO", "r9:yes", "garbage"], ["r1", "r2", "r3"])
    assert got == {"r1": True, "r2": False, "r3": False}


def test_parse_item_results_a_contradicted_id_is_no():
    """Strictness is the safer bias: an id judged both yes and no counts as no."""
    from agents.grader import parse_item_results

    assert parse_item_results(["r1:yes", "r1:no", " r2 : Yes "], ["r1", "r2"]) == {"r1": False, "r2": True}
    assert parse_item_results(["r1:no", "r1:yes"], ["r1"]) == {"r1": False}


def test_grade_returns_all_yes_and_records_usage(monkeypatch):
    import agents.grader as g

    model, calls = _scripted_grader([_good()])
    recorded = []
    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: recorded.append(kw) or r)
    with g.grader_agent.override(model=model):
        res = asyncio.run(g.grade(_item(), format="free", student_answer="x", deps=_deps()))
    assert res.unavailable is False and res.all_yes is True
    assert res.item_results == {"r1": True, "r2": True}
    assert res.low_confidence is False and res.backend == "gemini"
    assert calls["n"] == 1
    assert recorded == [{"feature": "tutor", "task": "grader", "user_id": "u1"}]


def test_grade_flags_low_confidence(monkeypatch):
    import agents.grader as g

    conf = (GRADER_SECOND_OPINION_CONFIDENCE + GRADER_LOW_CONFIDENCE) / 2
    model, _ = _scripted_grader([_partial(conf)])
    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: r)
    with g.grader_agent.override(model=model):
        res = asyncio.run(g.grade(_item(), format="free", student_answer="x", deps=_deps()))
    assert res.low_confidence is True and res.all_yes is False
    assert res.matched_wrong_key == "w_loop" and res.backend == "gemini"


def test_grade_drops_a_wrong_key_the_item_does_not_list(monkeypatch):
    """matched_wrong_key is a LISTED key or "" (spec behaviour 1): an invented key
    never reaches GradeOutcome.wrong_key (PKG-10 records only matched keys)."""
    import agents.grader as g

    model, _ = _scripted_grader([{**_partial(), "matched_wrong_key": "w_invented"}])
    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: r)
    with g.grader_agent.override(model=model):
        res = asyncio.run(g.grade(_item(), format="free", student_answer="x", deps=_deps()))
    assert res.unavailable is False and res.matched_wrong_key == ""


def test_grade_second_opinion_then_unavailable(monkeypatch):
    import agents.grader as g

    low = GRADER_SECOND_OPINION_CONFIDENCE / 2
    model, calls = _scripted_grader([_good(low), _good(low)])
    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: r)
    monkeypatch.setattr(g, "model_for", lambda slot: model)  # the second run's per-run model
    with g.grader_agent.override(model=model):
        res = asyncio.run(g.grade(_item(), format="free", student_answer="x", deps=_deps()))
    assert calls["n"] == 2
    assert res.unavailable is True


def test_grade_second_opinion_runs_on_grader_second_slot(monkeypatch):
    """A22: the second call is the SAME agent and message on another model,
    thinking off, with its own usage row; its verdict is marked gemini_second."""
    import agents.grader as g

    seen = []

    async def _run(message, **kw):
        seen.append((message, kw))
        conf = GRADER_SECOND_OPINION_CONFIDENCE / 2 if len(seen) == 1 else 0.9
        return SimpleNamespace(output=g.GraderOutput(**_good(conf)))

    tasks = []
    monkeypatch.setattr(g.grader_agent, "run", _run)
    monkeypatch.setattr(g, "model_for", lambda slot: f"model:{slot}")
    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: tasks.append(kw["task"]) or r)
    res = asyncio.run(g.grade(_item(), format="free", student_answer="x", deps=_deps()))
    (first_msg, first_kw), (second_msg, second_kw) = seen
    assert first_msg == second_msg and "model" not in first_kw
    assert second_kw["model"] == f"model:{GRADER_SECOND_OPINION_SLOT}"
    assert second_kw["model_settings"] == g._SECOND_OPINION_SETTINGS
    assert first_kw["usage_limits"] is GRADER_LIMITS and second_kw["usage_limits"] is GRADER_LIMITS
    assert tasks == ["grader", GRADER_SECOND_OPINION_SLOT]
    assert res.unavailable is False and res.backend == "gemini_second" and res.confidence == 0.9


def test_second_opinion_settings_pin_thinking_off():
    import agents.grader as g

    assert g._SECOND_OPINION_SETTINGS["google_thinking_config"].thinking_budget == 0


@pytest.mark.parametrize("exc", [
    UsageLimitExceeded("budget"),
    UnexpectedModelBehavior("garbage"),
    ModelHTTPError(status_code=503, model_name="gemini-2.5-flash-lite", body="UNAVAILABLE"),
])
def test_grade_degrades_honestly(monkeypatch, caplog, exc):
    import agents.grader as g

    async def _boom(*a, **k):
        raise exc

    monkeypatch.setattr(g.grader_agent, "run", _boom)
    with caplog.at_level("WARNING"):
        res = asyncio.run(g.grade(_item(), format="free", student_answer="x", deps=_deps()))
    assert res.unavailable is True
    assert any("grader unavailable" in r.getMessage() for r in caplog.records)


def test_grade_degrades_when_the_second_opinion_fails(monkeypatch, caplog):
    import agents.grader as g

    calls = []

    async def _run(message, **kw):
        calls.append(kw)
        if len(calls) == 1:
            return SimpleNamespace(output=g.GraderOutput(**_good(GRADER_SECOND_OPINION_CONFIDENCE / 2)))
        raise UnexpectedModelBehavior("garbage")

    monkeypatch.setattr(g.grader_agent, "run", _run)
    monkeypatch.setattr(g, "model_for", lambda slot: f"model:{slot}")
    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: r)
    with caplog.at_level("WARNING"):
        res = asyncio.run(g.grade(_item(), format="free", student_answer="x", deps=_deps()))
    assert len(calls) == 2 and res.unavailable is True
    assert any("grader unavailable" in r.getMessage() for r in caplog.records)


# ── function-mode handler ─────────────────────────────────────────────────


@pytest.fixture
def _clean_registry(monkeypatch):
    """Cold seam, env-module lane (the test_e2e_function_handlers posture)."""
    import sys

    import agents._providers as providers

    providers.clear_function_handlers()
    monkeypatch.setattr(providers, "_ENV_HANDLERS_LOADED", False)
    sys.modules.pop("agents.function_handlers_e2e", None)
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    yield
    providers.clear_function_handlers()
    sys.modules.pop("agents.function_handlers_e2e", None)


def test_e2e_grader_handler_all_yes_on_token(_clean_registry, monkeypatch):
    import agents.grader as g
    from agents._providers import model_for

    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: r)
    with g.grader_agent.override(model=model_for("grader")):
        from agents.function_handlers_e2e import E2E_GRADER_CORRECT_TOKEN, E2E_GRADER_HINT

        yes = asyncio.run(g.grade(_item(), format="free",
                                  student_answer=f"answer {E2E_GRADER_CORRECT_TOKEN}", deps=_deps()))
        no = asyncio.run(g.grade(_item(), format="free", student_answer="a loop", deps=_deps()))
    assert yes.all_yes is True and yes.item_results == {"r1": True, "r2": True}
    assert yes.feedback_hint == E2E_GRADER_HINT and yes.low_confidence is False
    assert yes.backend == "gemini" and yes.matched_wrong_key == ""
    assert no.unavailable is False and no.item_results == {"r1": False, "r2": False}


def test_e2e_grader_handler_serves_both_slots(_clean_registry, monkeypatch):
    """Invariant 6: the grader_second slot has the same fixed handler."""
    import agents.grader as g
    from agents._providers import model_for

    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: r)
    for slot in ("grader", GRADER_SECOND_OPINION_SLOT):
        with g.grader_agent.override(model=model_for(slot)):
            from agents.function_handlers_e2e import E2E_GRADER_CORRECT_TOKEN

            res = asyncio.run(g.grade(_item(), format="free",
                                      student_answer=f"x {E2E_GRADER_CORRECT_TOKEN}", deps=_deps()))
        assert res.unavailable is False and res.all_yes is True, slot


def test_e2e_grader_handler_reads_rubric_ids_off_the_message(_clean_registry, monkeypatch):
    """Any seeded item works: ids come from `RUBRIC ITEM <id>:` lines, so a
    three-item rubric gets three verdicts; the confidence never triggers the
    second opinion in E2E."""
    import agents.grader as g
    from agents._providers import model_for

    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: r)
    item = _item(rubric=[RubricItem(id=f"rubric_{i}", text=f"point {i}") for i in range(3)])
    with g.grader_agent.override(model=model_for("grader")):
        from agents.function_handlers_e2e import E2E_GRADER_CONFIDENCE, E2E_GRADER_CORRECT_TOKEN

        res = asyncio.run(g.grade(item, format="teachback",
                                  student_answer=E2E_GRADER_CORRECT_TOKEN, deps=_deps()))
    assert res.item_results == {"rubric_0": True, "rubric_1": True, "rubric_2": True}
    assert res.confidence == E2E_GRADER_CONFIDENCE >= GRADER_LOW_CONFIDENCE
