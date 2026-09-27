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
    LADDER_MAX_RUNG,
    RUNG_ASSISTED_MAX,
    RUNG_NO_CREDIT_MIN,
    WEIGHT_ASSISTED,
    WEIGHT_LOW_CONFIDENCE,
    WEIGHT_SAME_SESSION_RECHECK,
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


# ── grade_answer (the route helper, A16) ──────────────────────────────────


def _result(**over):
    from agents.grader import GradeResult

    base = dict(item_results={"r1": True, "r2": True}, all_yes=True, confidence=0.9,
                feedback_hint="Think about what stops the calls.", backend="gemini")
    base.update(over)
    return GradeResult(**base)


def _answer(**over):
    from agents.tools.check import CheckAnswer

    kw = dict(question_hash="qh-1", answer_text="It stops the calls.")
    kw.update(over)
    return CheckAnswer(**kw)


@pytest.fixture
def check(monkeypatch):
    """grade_answer with its one seam stubbed: the grader."""
    import agents.tools.check as c

    state = {"item": _item(), "result": _result(), "grade_calls": []}

    async def _grade(item, *, format, student_answer, deps):
        state["grade_calls"].append((format, student_answer))
        return state["result"]

    monkeypatch.setattr(c, "grade", _grade)
    return c, state


def _run(check, deps, answer, **kw):
    c, state = check
    return asyncio.run(c.grade_answer(state["item"], answer, deps=deps, node_id=NODE, **kw))


def test_grade_answer_is_inert_when_learning_loop_false(check):
    _, state = check
    deps = _deps(learning_loop=False)
    for answer in (_answer(), _answer(idk=True, answer_text="")):
        out = _run(check, deps, answer)
        assert out.unavailable is True and out.evidence is None and out.correct is None
    assert deps.pending_evidence == [] and state["grade_calls"] == []


def test_idk_is_incorrect_on_the_items_channel_without_grader(check):
    _, state = check
    deps = _deps()
    out = _run(check, deps, _answer(idk=True, answer_text=""), max_rung=1)
    assert state["grade_calls"] == []
    [ev] = deps.pending_evidence
    assert ev == out.evidence and out.correct is False and out.unavailable is False
    assert ev["channel"] == "free_response" and ev["idk"] is True and ev["correct"] is False
    assert ev["weight"] == 1.0 and ev["grader_backend"] is None and ev["max_rung"] == 1
    assert ev["node_id"] == NODE and ev["check_item_id"] == "ci-1"
    assert ev["question_hash"] == "qh-1" and ev["session_id"] == "s1"
    assert out.grader_backend is None and out.confidence is None and out.wrong_key is None


@pytest.mark.parametrize("fmt,channel", [("free", "free_response"), ("teachback", "teachback_llm"), ("mc_reason", "mc_reasoned")])
def test_channel_mapping(check, fmt, channel):
    _, state = check
    state["item"] = _mc_item() if fmt == "mc_reason" else _item(format=fmt)
    deps = _deps()
    _run(check, deps, _answer(selected_option="a", reason="because it stops"))
    [ev] = deps.pending_evidence
    assert ev["channel"] == channel and ev["correct"] is True


def test_every_check_item_format_has_a_channel():
    from typing import get_args

    from agents.tools.check import CHANNEL_FOR_FORMAT
    from learning.evidence import Channel
    from learning.params import CHECK_ITEM_FORMATS

    assert set(CHANNEL_FOR_FORMAT) == set(CHECK_ITEM_FORMATS)
    assert set(CHANNEL_FOR_FORMAT.values()) <= set(get_args(Channel))


def test_mc_reason_reason_check_runs_for_both_outcomes(check):
    _, state = check
    state["item"] = _mc_item()
    for option in ("A", "C"):
        _run(check, _deps(), _answer(selected_option=option, reason="because it stops"))
    assert state["grade_calls"] == [
        ("mc_reason", "Selected option: A\nReason: because it stops"),
        ("mc_reason", "Selected option: C\nReason: because it stops"),
    ]


def test_mc_reason_wrong_option_is_incorrect_even_with_yes_rubric(check):
    _, state = check
    state["item"] = _mc_item()
    deps = _deps()
    out = _run(check, deps, _answer(selected_option="C", reason="because"))
    [ev] = deps.pending_evidence
    assert out.correct is False and ev["correct"] is False and ev["channel"] == "mc_reasoned"


def test_mc_reason_right_option_with_failed_reason_is_incorrect(check):
    _, state = check
    state["item"] = _mc_item()
    state["result"] = _result(item_results={"r1": True, "r2": False}, all_yes=False)
    deps = _deps()
    out = _run(check, deps, _answer(selected_option="A", reason="it just is"))
    [ev] = deps.pending_evidence
    assert out.correct is False and ev["correct"] is False


def test_mc_reason_option_is_compared_case_and_whitespace_insensitively(check):
    _, state = check
    state["item"] = _mc_item()
    assert _run(check, _deps(), _answer(selected_option="  a ", reason="because it stops")).correct is True


def test_mc_reason_without_an_option_is_incorrect_but_still_graded(check):
    _, state = check
    state["item"] = _mc_item()
    deps = _deps()
    out = _run(check, deps, _answer(selected_option=None, reason="because it stops"))
    assert state["grade_calls"] == [("mc_reason", "Selected option: \nReason: because it stops")]
    assert out.correct is False and deps.pending_evidence[0]["correct"] is False


def test_wrong_key_only_when_the_reason_matches_the_chosen_option(check):
    _, state = check
    state["item"] = _mc_item()
    state["result"] = _result(item_results={"r1": False, "r2": False}, all_yes=False, matched_wrong_key="w_loop")
    matched = _run(check, _deps(), _answer(selected_option="C", reason="it loops until done"))    # C → w_loop
    unmatched = _run(check, _deps(), _answer(selected_option="B", reason="it loops until done"))  # B → w_speed
    right_option = _run(check, _deps(), _answer(selected_option="A", reason="it loops until done"))
    assert matched.wrong_key == "w_loop" and matched.matched_wrong_key == "w_loop"
    assert unmatched.wrong_key is None and unmatched.matched_wrong_key == "w_loop"
    assert right_option.correct is False and right_option.wrong_key == "w_loop"  # the reason matched (§3.3)


def test_no_wrong_key_when_correct_or_nothing_matched(check):
    _, state = check
    state["result"] = _result(matched_wrong_key="w_loop")  # a correct answer never carries a key
    assert _run(check, _deps(), _answer()).wrong_key is None
    state["result"] = _result(item_results={"r1": True, "r2": False}, all_yes=False)
    out = _run(check, _deps(), _answer())
    assert out.correct is False and out.wrong_key is None and out.matched_wrong_key is None


@pytest.mark.parametrize("fmt,option", [("mc_reason", "A"), ("mc_reason", "C"), ("free", None)])
def test_symmetric_missingness_when_grader_unavailable(check, fmt, option):
    from agents.grader import GradeResult

    _, state = check
    state["item"] = _mc_item() if fmt == "mc_reason" else _item()
    state["result"] = GradeResult(unavailable=True)
    deps = _deps()
    out = _run(check, deps, _answer(selected_option=option, reason="because"))
    assert out.unavailable is True and out.correct is None and out.evidence is None
    assert deps.pending_evidence == [] and len(state["grade_calls"]) == 1


def test_numeric_clear_mismatch_is_deterministic_incorrect(check):
    _, state = check
    state["item"] = _numeric_item()
    state["result"] = _result()  # the grader said yes; the verified key overrides it
    deps = _deps()
    out = _run(check, deps, _answer(answer_text="12.5"))
    assert len(state["grade_calls"]) == 1, "the grader runs for both numeric outcomes (inv 28)"
    [ev] = deps.pending_evidence
    assert ev["correct"] is False and ev["grader_backend"] == "deterministic"
    assert out.correct is False and out.grader_backend == "deterministic" and out.confidence is None
    assert ev["confidence"] is None and ev["weight"] == 1.0


def test_numeric_mismatch_keeps_the_graders_matched_key(check):
    _, state = check
    state["item"] = _numeric_item()
    state["result"] = _result(item_results={"r1": True, "r2": False}, all_yes=False, matched_wrong_key="w_loop")
    out = _run(check, _deps(), _answer(answer_text="12.5"))
    assert out.grader_backend == "deterministic" and out.wrong_key == "w_loop"


@pytest.mark.parametrize("answer_text", ["12.5", "9.81"])  # a clear mismatch, then a match
def test_numeric_item_under_grader_outage_records_neither_outcome(check, answer_text):
    """Invariant 28: the numeric gate never records one outcome while the other is dropped."""
    _, state = check
    state["item"] = _numeric_item()
    state["result"] = _result(unavailable=True)
    deps = _deps()
    out = _run(check, deps, _answer(answer_text=answer_text))
    assert out.unavailable is True and out.evidence is None and deps.pending_evidence == []


@pytest.mark.parametrize("answer_text,over", [
    ("9.815", {}),                              # within tolerance → the rubric grader decides
    ("9.81", {"tolerance": None}),              # exact match, no tolerance → the rubric grader
    ("about nine point eight", {}),             # parse failure → the rubric grader
    ("inf", {}),                                # not finite → the rubric grader
    ("12.5", {"canonical_verified": False}),    # unverified key → the rubric grader
    ("12.5", {"canonical_answer": "g"}),        # unparseable key → the rubric grader
    ("12.5", {"answer_kind": "free"}),          # not a numeric item → the rubric grader
])
def test_numeric_gate_never_issues_correct(check, answer_text, over):
    _, state = check
    state["item"] = _numeric_item(**over)
    state["result"] = _result(item_results={"r1": False, "r2": False}, all_yes=False)
    deps = _deps()
    out = _run(check, deps, _answer(answer_text=answer_text))
    assert len(state["grade_calls"]) == 1 and out.grader_backend == "gemini"
    assert out.correct is False  # the grader said no; code never turned a match into "correct"


def test_numeric_match_keeps_a_yes_verdict(check):
    _, state = check
    state["item"] = _numeric_item()
    out = _run(check, _deps(), _answer(answer_text=" 9.81 "))
    assert out.correct is True and out.grader_backend == "gemini" and out.confidence == 0.9


def test_grader_backend_values(check):
    _, state = check
    deps = _deps()
    _run(check, deps, _answer())
    state["result"] = _result(backend="gemini_second")
    _run(check, deps, _answer())
    _run(check, deps, _answer(idk=True))
    assert [ev["grader_backend"] for ev in deps.pending_evidence] == ["gemini", "gemini_second", None]


def test_unassisted_correct_is_full_weight(check):
    deps = _deps()
    _run(check, deps, _answer())
    [ev] = deps.pending_evidence
    assert ev["correct"] is True and ev["assisted"] is False and ev["weight"] == 1.0 and ev["max_rung"] == 0
    assert ev["confidence"] == 0.9


def test_assisted_rungs_halve_weight(check):
    deps = _deps()
    _run(check, deps, _answer(), max_rung=RUNG_ASSISTED_MAX)
    [ev] = deps.pending_evidence
    assert ev["assisted"] is True and ev["weight"] == WEIGHT_ASSISTED


def test_recheck_and_low_confidence_multiply(check):
    _, state = check
    state["result"] = _result(confidence=GRADER_LOW_CONFIDENCE / 2, low_confidence=True)
    deps = _deps()
    _run(check, deps, _answer(), max_rung=RUNG_ASSISTED_MAX, same_session_recheck=True)
    [ev] = deps.pending_evidence
    assert ev["weight"] == pytest.approx(WEIGHT_ASSISTED * WEIGHT_SAME_SESSION_RECHECK * WEIGHT_LOW_CONFIDENCE)
    assert ev["same_session_recheck"] is True


def test_low_confidence_weighs_both_outcomes(check):
    """A22: the reason check's confidence sets the weight of a correct AND a wrong answer."""
    _, state = check
    state["item"] = _mc_item()
    state["result"] = _result(confidence=GRADER_LOW_CONFIDENCE / 2, low_confidence=True)
    deps = _deps()
    _run(check, deps, _answer(selected_option="A", reason="because it stops"))
    _run(check, deps, _answer(selected_option="C", reason="because it stops"))
    right, wrong = deps.pending_evidence
    assert (right["correct"], wrong["correct"]) == (True, False)
    assert right["weight"] == wrong["weight"] == WEIGHT_LOW_CONFIDENCE
    assert right["confidence"] == wrong["confidence"] == GRADER_LOW_CONFIDENCE / 2


def test_correct_after_h4_plus_has_zero_weight_but_is_appended(check):
    deps = _deps()
    _run(check, deps, _answer(), max_rung=RUNG_NO_CREDIT_MIN)
    [ev] = deps.pending_evidence
    assert ev["correct"] is True and ev["weight"] == 0.0 and ev["max_rung"] == RUNG_NO_CREDIT_MIN


def test_wrong_after_h4_plus_keeps_standard_weight(check):
    _, state = check
    state["result"] = _result(item_results={"r1": True, "r2": False}, all_yes=False, matched_wrong_key="w_loop")
    deps = _deps()
    out = _run(check, deps, _answer(), max_rung=RUNG_NO_CREDIT_MIN + 1)
    [ev] = deps.pending_evidence
    assert ev["correct"] is False and ev["weight"] == 1.0 and out.wrong_key == "w_loop"


@pytest.mark.parametrize("max_rung", [-1, LADDER_MAX_RUNG + 1])
def test_max_rung_off_the_ladder_raises_before_any_grader_call(check, max_rung):
    _, state = check
    deps = _deps()
    with pytest.raises(ValueError, match="max_rung"):
        _run(check, deps, _answer(), max_rung=max_rung)
    assert state["grade_calls"] == [] and deps.pending_evidence == []


def test_pending_evidence_accumulates_across_calls(check):
    deps = _deps()
    _run(check, deps, _answer())
    _run(check, deps, _answer(), same_session_recheck=True)
    assert len(deps.pending_evidence) == 2
    assert deps.pending_evidence[1]["weight"] == WEIGHT_SAME_SESSION_RECHECK


def test_appended_rows_are_pkg03_evidence(check):
    """What grade_answer appends is exactly what apply_graph_update validates."""
    from learning.evidence import Evidence

    deps = _deps()
    _run(check, deps, _answer(), max_rung=RUNG_ASSISTED_MAX)
    _run(check, deps, _answer(idk=True))
    for row in deps.pending_evidence:
        assert Evidence.model_validate(row).model_dump() == row


def test_outcome_never_carries_the_reference(check):
    import dataclasses

    for answer in (_answer(), _answer(idk=True)):
        out = _run(check, _deps(), answer)
        assert REFERENCE not in repr(dataclasses.asdict(out))


def test_grade_answer_never_touches_db_tables(check, monkeypatch):
    """Spy on db.connection.table: grade_answer must not resolve ANY table."""
    import db.connection as dbconn

    names = []
    monkeypatch.setattr(dbconn, "table", lambda name, *a, **k: names.append(name) or SimpleNamespace())
    _run(check, _deps(), _answer())
    _run(check, _deps(), _answer(idk=True))
    assert names == []


# ── flush_pending (route persistence contract) ────────────────────────────


def test_flush_pending_calls_apply_graph_update_once_and_clears(monkeypatch):
    import services.graph_service as gs
    from learning import evidence as ev

    calls = []
    monkeypatch.setattr(gs, "apply_graph_update", lambda uid, gu, cid=None: calls.append((uid, gu, cid)) or [{"concept": "x"}])
    deps = _deps()
    deps.pending_evidence.extend([{"node_id": "n1", "channel": "free_response", "correct": True},
                                  {"node_id": "n1", "channel": "free_response", "idk": True, "correct": False}])
    out = ev.flush_pending(deps, "c1")
    assert out == [{"concept": "x"}]
    assert len(calls) == 1
    uid, gu, cid = calls[0]
    assert uid == "u1" and cid == "c1" and set(gu) == {"evidence"} and len(gu["evidence"]) == 2
    assert deps.pending_evidence == []


def test_flush_pending_empty_is_a_noop(monkeypatch):
    import services.graph_service as gs
    from learning import evidence as ev

    monkeypatch.setattr(gs, "apply_graph_update", lambda *a, **k: pytest.fail("must not be called"))
    assert ev.flush_pending(_deps(), "c1") == []


def test_flush_pending_keeps_the_list_when_the_write_fails(monkeypatch):
    """Errors propagate; the list is cleared only after a successful write."""
    import services.graph_service as gs
    from learning import evidence as ev

    def _boom(*a, **k):
        raise RuntimeError("postgrest down")

    monkeypatch.setattr(gs, "apply_graph_update", _boom)
    deps = _deps()
    deps.pending_evidence.append({"node_id": "n1", "channel": "mc", "correct": True})
    with pytest.raises(RuntimeError, match="postgrest down"):
        ev.flush_pending(deps, "c1")
    assert len(deps.pending_evidence) == 1


def test_flush_pending_sends_a_snapshot_not_the_live_list(monkeypatch):
    import services.graph_service as gs
    from learning import evidence as ev

    sent = []
    monkeypatch.setattr(gs, "apply_graph_update", lambda uid, gu, cid=None: sent.append(gu["evidence"]) or [])
    deps = _deps()
    deps.pending_evidence.append({"node_id": "n1", "channel": "mc", "correct": True})
    ev.flush_pending(deps, "c1")
    assert sent[0] is not deps.pending_evidence and len(sent[0]) == 1


def test_grade_answer_then_flush_pending_reaches_the_single_writer(check, monkeypatch):
    """The A16 route sequence: grade_answer appends, flush_pending persists the
    batch once through apply_graph_update as PKG-03 Evidence rows."""
    import services.graph_service as gs
    from learning import evidence as ev

    payloads = []
    monkeypatch.setattr(gs, "apply_graph_update", lambda uid, gu, cid=None: payloads.append(gu) or [])
    deps = _deps()
    _run(check, deps, _answer())
    _run(check, deps, _answer(idk=True))
    assert ev.flush_pending(deps, "c1") == []
    [payload] = payloads
    rows = [ev.Evidence.model_validate(row) for row in payload["evidence"]]
    assert [(r.correct, r.idk, r.grader_backend) for r in rows] == [(True, False, "gemini"), (False, True, None)]
    assert deps.pending_evidence == []
