"""Spec §13 A116: learning evidence names the provider that graded.

A grader verdict is learning evidence, and analyses group it by its provenance
(`node_mastery_events.grader_backend`, `zpd.step`'s `grader_backend`). The grader
used to label every verdict `gemini` / `gemini_second` whatever model its slot ran,
so with SAPLING_MODEL_GRADER=claude-* every evidence row named Gemini while
llm_usage named Claude.

Here the REAL grade() runs: one scripted FunctionModel (tests/grader_fakes.py)
answers for both slots, and the provider comes from each slot's configuration,
exactly as in production. The label is read where it lands: GradeResult, the
decision seam's verdict and `decision.made`, the Evidence row grade_answer
appends, and the zpd.step payload."""

from __future__ import annotations

import asyncio

import pytest

import tests.test_learning_check_tool as t
from learning.params import GRADER_SECOND_OPINION_CONFIDENCE
from tests import grader_fakes

CLAUDE, CLAUDE_2 = "claude-haiku-5-5", "claude-sonnet-5-5"
GEMINI, GEMINI_2 = "gemini-2.5-flash-lite", "gemini-2.5-flash"
GOOD = t._good()  # all yes, confident: the first slot's verdict stands
LOW = t._good(GRADER_SECOND_OPINION_CONFIDENCE / 2)  # below the floor: the second opinion decides
# an all-yes whose own run says it contradicts the reference: the second opinion confirms (A33)
CONFLICTED = {**GOOD, "contradicts_reference": True}
NODE = "node-recursion"


def _slots(monkeypatch, grader: str | None, second: str | None) -> None:
    """Point the grader slots at these models (None: the slot's default)."""
    for env, model in (("SAPLING_MODEL_GRADER", grader), ("SAPLING_MODEL_GRADER_SECOND", second)):
        if model is None:
            monkeypatch.delenv(env, raising=False)
        else:
            monkeypatch.setenv(env, model)


@pytest.fixture
def events(monkeypatch):
    from services import events_service

    got: list[tuple[str, dict]] = []
    monkeypatch.setattr(events_service, "log_event", lambda et, **kw: got.append((et, kw)))
    return got


@pytest.fixture
def scripted(monkeypatch, events):
    """The real grade() over a scripted FunctionModel: the agent override serves the
    first slot, the patched `model_for` the grader_second runs (second opinion, span
    and context checks). The seam serves its default selection; no usage rows."""
    import agents.grader as g
    from services import learning_decisions as decisions

    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    for name in decisions.DECISION_NAMES:
        monkeypatch.delenv(f"DECISION_BACKEND_{name.upper()}", raising=False)
    monkeypatch.setattr(decisions, "JEV_ENABLED", False)
    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: r)

    def run(outputs, coro_fn):
        model, calls = grader_fakes.scripted_grader(outputs)
        monkeypatch.setattr(g, "model_for", lambda slot: model)
        with g.grader_agent.override(model=model):
            return asyncio.run(coro_fn()), calls

    return run


def _grade(scripted, outputs, *, item=None, answer="It stops the calls."):
    import agents.grader as g

    return scripted(
        outputs,
        lambda: g.grade(item or t._item(), format="free", student_answer=answer, deps=t._deps()),
    )


def _grade_answer(scripted, outputs, *, item=None, answer=None):
    from agents.tools.check import grade_answer

    deps = t._deps()
    out, calls = scripted(
        outputs,
        lambda: grade_answer(item or t._item(), answer or t._answer(), deps=deps, node_id=NODE),
    )
    return out, deps, calls


def _made(events) -> list[tuple[str, str]]:
    return [
        (kw["payload"]["decision"], kw["payload"]["backend"])
        for et, kw in events
        if et == "decision.made"
    ]


# ── the label: which slot's run, which provider ───────────────────────────────


@pytest.mark.parametrize(
    "grader,second,labels",
    [
        (None, None, ("gemini", "gemini_second")),  # the defaults, pending the Claude eval (A111)
        (GEMINI, GEMINI_2, ("gemini", "gemini_second")),
        (CLAUDE, CLAUDE_2, ("claude", "claude_second")),
        (CLAUDE, GEMINI_2, ("claude", "gemini_second")),
        (GEMINI, CLAUDE, ("gemini", "claude_second")),
        (f"anthropic:{CLAUDE}", f"google-gla:{GEMINI_2}", ("claude", "gemini_second")),
    ],
)
def test_run_backend_reads_each_slots_provider(monkeypatch, grader, second, labels):
    from agents.grader import run_backend

    _slots(monkeypatch, grader, second)
    assert (run_backend(), run_backend(second_opinion=True)) == labels


def test_every_provider_has_a_label():
    """A provider `slot_provider` can name and no label covers would be a KeyError at
    grade time: adding one means adding its labels here, to learning.evidence's
    GraderBackend and to the CHECK (a migration), in one change."""
    from typing import get_args

    from agents._providers import ProviderName
    from agents.grader import _RUN_BACKENDS
    from services.learning_decisions import _PROVIDER_BACKEND

    providers = set(get_args(ProviderName))
    assert set(_RUN_BACKENDS) == {(p, second) for p in providers for second in (False, True)}
    assert set(_PROVIDER_BACKEND) == providers


@pytest.mark.parametrize(
    "grader,second,first_label,second_label",
    [
        (CLAUDE, CLAUDE_2, "claude", "claude_second"),
        (GEMINI, GEMINI_2, "gemini", "gemini_second"),
        (None, None, "gemini", "gemini_second"),
        # each verdict names the slot ITS run used, never the other one
        (CLAUDE, GEMINI_2, "claude", "gemini_second"),
        (GEMINI, CLAUDE_2, "gemini", "claude_second"),
    ],
)
def test_grade_names_the_provider_of_the_slot_whose_run_it_used(
    monkeypatch, scripted, grader, second, first_label, second_label
):
    _slots(monkeypatch, grader, second)
    res, calls = _grade(scripted, [GOOD])  # the first slot's confident verdict stands
    assert (res.unavailable, res.all_yes, calls["n"]) == (False, True, 1)
    assert res.backend == first_label
    res, calls = _grade(scripted, [LOW, GOOD])  # the second opinion replaces an unsure first run
    assert (res.unavailable, res.all_yes, calls["n"]) == (False, True, 2)
    assert res.backend == second_label
    res, calls = _grade(scripted, [CONFLICTED, GOOD])  # ...and confirms a conflicted all-yes
    assert (res.unavailable, res.all_yes, calls["n"]) == (False, True, 2)
    assert res.backend == second_label


def test_the_provider_is_read_at_grade_time(monkeypatch, scripted):
    """An env flip is honoured without a re-import: nothing caches the label."""
    _slots(monkeypatch, GEMINI, GEMINI_2)
    assert _grade(scripted, [GOOD])[0].backend == "gemini"
    _slots(monkeypatch, CLAUDE, CLAUDE_2)
    assert _grade(scripted, [GOOD])[0].backend == "claude"
    assert _grade(scripted, [LOW, GOOD])[0].backend == "claude_second"


def test_an_unavailable_grade_names_no_run(monkeypatch, scripted):
    _slots(monkeypatch, CLAUDE, CLAUDE_2)
    res, calls = _grade(scripted, [LOW, LOW])  # below the floor twice: no verdict
    assert (res.unavailable, res.backend, calls["n"]) == (True, None, 2)


# ── where it lands: Evidence, GradeOutcome, decision.made, zpd.step ───────────


@pytest.mark.parametrize(
    "grader,second,outputs,label",
    [
        (CLAUDE, CLAUDE_2, [GOOD], "claude"),
        (CLAUDE, CLAUDE_2, [LOW, GOOD], "claude_second"),
        (GEMINI, GEMINI_2, [GOOD], "gemini"),
        (GEMINI, GEMINI_2, [LOW, GOOD], "gemini_second"),
    ],
)
def test_grade_answer_evidence_names_the_provider_that_graded(
    monkeypatch, scripted, events, grader, second, outputs, label
):
    from learning.evidence import Evidence

    _slots(monkeypatch, grader, second)
    out, deps, _ = _grade_answer(scripted, outputs)
    [ev] = deps.pending_evidence
    assert (out.correct, out.unavailable) == (True, False)
    assert ev["grader_backend"] == out.grader_backend == label
    assert Evidence.model_validate(ev).grader_backend == label
    # the decision seam's own record agrees: the grade, then PKG-10's key from that prior
    provider = label.removesuffix("_second")
    assert _made(events) == [("grade_rubric_items", provider), ("match_wrong_reason", provider)]


def test_an_mc_reason_grade_names_the_provider_too(monkeypatch, scripted, events):
    _slots(monkeypatch, CLAUDE, CLAUDE_2)
    out, deps, _ = _grade_answer(
        scripted,
        [{**GOOD, "item_results": ["r1:yes", "r2:yes"]}],
        item=t._mc_item(),
        answer=t._answer(selected_option="A", reason="It stops the recursion at the base case."),
    )
    [ev] = deps.pending_evidence
    assert ev["channel"] == "mc_reasoned" and ev["grader_backend"] == "claude"
    assert _made(events) == [("reason_is_correct", "claude"), ("match_wrong_reason", "claude")]


def test_the_numeric_gate_stays_deterministic_under_a_claude_grader(monkeypatch, scripted, events):
    """A22: the verified-key clear mismatch overrides the grader's yes, and its
    evidence names code, whichever provider the grader that ran first is on."""
    _slots(monkeypatch, CLAUDE, CLAUDE_2)
    out, deps, calls = _grade_answer(
        scripted, [GOOD], item=t._numeric_item(), answer=t._answer(answer_text="12.5")
    )
    [ev] = deps.pending_evidence
    assert calls["n"] == 1, "the grader still ran for both numeric outcomes (inv 28)"
    assert ev["correct"] is False and ev["grader_backend"] == out.grader_backend == "deterministic"
    assert ("numeric_gate", "deterministic") in _made(events)


@pytest.mark.parametrize("grader,label", [(None, "gemini"), (CLAUDE, "claude")])
def test_function_mode_records_the_slot_it_stands_in_for(monkeypatch, scripted, events, grader, label):
    """The E2E lanes (SAPLING_MODEL_MODE=function): a FunctionModel answers, so the
    seam's verdict says `function`; the evidence names the provider of the slot the
    FunctionModel stands in for — `gemini` under today's defaults, as before."""
    _slots(monkeypatch, grader, None)
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    out, deps, _ = _grade_answer(scripted, [GOOD])
    [ev] = deps.pending_evidence
    assert ev["grader_backend"] == out.grader_backend == label
    assert _made(events) == [("grade_rubric_items", "function"), ("match_wrong_reason", label)]


@pytest.mark.parametrize("model,label", [(None, "gemini"), (GEMINI, "gemini"), (CLAUDE, "claude")])
def test_the_decision_agents_verdicts_name_its_slots_provider(monkeypatch, scripted, events, model, label):
    """The same rule for the seam's other model answers (spec §13 A116): a
    learning_decision run names the provider its slot serves on, while the
    selection keeps the model backend's name (`gemini`)."""
    import tests.test_learning_decisions as d
    from agents.learning_decision import learning_decision_agent
    from services import learning_decisions as seam

    if model is None:
        monkeypatch.delenv("SAPLING_MODEL_LEARNING_DECISION", raising=False)
    else:
        monkeypatch.setenv("SAPLING_MODEL_LEARNING_DECISION", model)
    monkeypatch.setattr(seam, "record_agent_usage", lambda r, **kw: r)
    yes, _ = d._scripted([{"answer": "yes", "confidence": 0.8}])
    pick, _ = d._scripted([{"choice": "w_speed", "confidence": 0.8}])
    leak = seam.LeakState(reference=d.REFERENCE, emitted="Once it stops, the calls end.", rung=1)
    wrong = seam.WrongReasonState(question=d.QUESTION, answer="only for speed", wrong=d.WRONG)
    with learning_decision_agent.override(model=yes):
        judged = asyncio.run(seam.judge_leak(leak, deps=t._deps()))
    with learning_decision_agent.override(model=pick):
        matched = asyncio.run(seam.match_wrong_reason(wrong, deps=t._deps()))
    assert (judged.backend, matched.backend, matched.value) == (label, label, "w_speed")
    assert seam.select_backend("judge_leak").served == "gemini"
    assert _made(events) == [("judge_leak", label), ("match_wrong_reason", label)]


def test_the_zpd_step_payload_carries_the_label(monkeypatch, scripted):
    """zpd.step's grader_backend is what the route read off the grade (its loop_state
    entry): here the real grade_answer's, emitted through the real payload builder."""
    from learning import params, zpd_events
    from learning.ladder import Rung
    from learning.policy import CeilingReason

    _slots(monkeypatch, CLAUDE, CLAUDE_2)
    out, _, _ = _grade_answer(scripted, [LOW, GOOD])
    emitted: list[tuple[str, dict]] = []  # zpd_events binds log_event at import
    monkeypatch.setattr(zpd_events, "log_event", lambda et, **kw: emitted.append((et, kw)))
    zpd_events.emit_zpd_step(
        user_id="u1",
        request_id="r1",
        concept_id=NODE,
        question_hash="q" * 64,
        phase="check",
        channel="free_response",
        band="develop",
        ceiling=Rung.H3,
        ceiling_reason=CeilingReason.DEVELOP,
        first_attempt_correct=True,
        n_attempts=1,
        max_rung_used=Rung.H0,
        rungs=[],
        time_to_first_attempt_ms=1000,
        time_to_correct_ms=1000,
        independent_time_ms=1000,
        assisted=False,
        confidence=out.confidence,
        fsrs_rating=params.FSRS_RATING_GOOD,
        p_known_before=0.4,
        p_known_after=0.6,
        r_before=None,
        item_difficulty=1,
        tier="standard",
        grader_backend=out.grader_backend,
    )
    [(event_type, kw)] = emitted
    assert event_type == "zpd.step" and kw["payload"]["grader_backend"] == "claude_second"
