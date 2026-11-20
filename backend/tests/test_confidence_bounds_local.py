"""A confidence outside [0, 1] is clamped locally, never an output retry (#866 Z44, Z55).

The grader (`GraderOutput`) and the loop's decision agent
(`DecisionYesNoOutput`, `DecisionPickOutput`) bound `confidence` with
ge=0/le=1. Gemini enforced that at decode time; Claude's strict JSON mode
cannot (pydantic-ai moves minimum/maximum into the field description), and
every one of these slots now defaults to Claude. One stray value (1.02, or 95
read as a percent) failed validation for the WHOLE output and spent the run's
only retry under GRADER_LIMITS (request_limit 2): a second miss was
UsageLimitExceeded, so the answer earned no evidence while two requests were
billed. The bound stays in the schema the model sees; a finite value past it
is clamped before validation (agents/_bounded.py::clamp_unit), as the list
and prose caps are clipped. A non-finite value is still rejected.
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest
from pydantic import ValidationError

from agents import grader as g
from agents.learning_decision import DecisionPickOutput, DecisionYesNoOutput
from tests import grader_fakes
from tests.test_learning_check_tool import _deps, _good, _item

HONEST = "The base case stops the recursive calls; without it the stack grows without bound."


def _grader_out(confidence) -> dict:
    return {
        "addresses_grader": False,
        "contradicts_reference": False,
        "item_results": ["r1:yes"],
        "support": [],
        "confidence": confidence,
        "matched_wrong_key": "",
        "feedback_hint": "",
    }


OUTPUTS = [
    (g.GraderOutput, _grader_out),
    (DecisionYesNoOutput, lambda c: {"answer": "yes", "confidence": c}),
    (DecisionPickOutput, lambda c: {"choice": "none", "confidence": c}),
]


@pytest.mark.parametrize("model, payload", OUTPUTS, ids=[m.__name__ for m, _ in OUTPUTS])
@pytest.mark.parametrize("raw, want", [(1.02, 1.0), (95, 1.0), (-0.2, 0.0), (0.4, 0.4), (1, 1.0), (0, 0.0)])
def test_a_finite_confidence_past_its_bound_is_clamped(model, payload, raw, want):
    assert model.model_validate(payload(raw)).confidence == want


@pytest.mark.parametrize("model, payload", OUTPUTS, ids=[m.__name__ for m, _ in OUTPUTS])
@pytest.mark.parametrize("raw", [math.nan, math.inf, -math.inf])
def test_a_non_finite_confidence_still_fails_validation(model, payload, raw):
    with pytest.raises(ValidationError):
        model.model_validate(payload(raw))


@pytest.mark.parametrize("model", [m for m, _ in OUTPUTS], ids=[m.__name__ for m, _ in OUTPUTS])
def test_the_schema_the_model_sees_keeps_the_bound(model):
    """No prompt change: the JSON schema still says 0..1 (a decode-time bound on
    Gemini, a description hint on Claude)."""
    prop = model.model_json_schema()["properties"]["confidence"]
    assert prop["minimum"] == 0.0 and prop["maximum"] == 1.0


def _grade(monkeypatch, outputs):
    monkeypatch.setattr(g, "record_agent_usage", lambda *a, **kw: None)
    model, calls = grader_fakes.scripted_grader(outputs)
    monkeypatch.setattr(g, "model_for", lambda slot: model)
    with g.grader_agent.override(model=model):
        result = asyncio.run(g.grade(_item(), format="free", student_answer=HONEST, deps=_deps()))
    return result, calls


@pytest.mark.parametrize("raw", [1.02, 40])
def test_a_first_run_whose_confidence_overshoots_asks_the_second_opinion(monkeypatch, raw):
    """End to end (#866 review): a primary verdict at confidence 1.02, or 40 meant
    as 40%, validates (no output retry, no outage), but a number past 1 is no
    0..1 confidence, so it is trusted as none: the ONE second opinion runs and
    the verdict stands on that run's own confidence — never on the 1.0 the clamp
    made, which would have skipped the second opinion on an evidence path."""
    result, calls = _grade(monkeypatch, [_good(conf=raw), _good(conf=0.85)])
    assert calls["n"] == 2
    assert not result.unavailable and result.all_yes
    assert result.confidence == 0.85


def test_a_second_opinion_whose_confidence_overshoots_is_no_verdict(monkeypatch):
    """Both runs past 1: neither carries a usable confidence, so the grade is
    unavailable (the below-the-floor-twice path), never credited at 1.0."""
    result, calls = _grade(monkeypatch, [_good(conf=40), _good(conf=95)])
    assert calls["n"] == 2
    assert result.unavailable and not result.all_yes


def test_a_confidence_of_exactly_one_is_trusted(monkeypatch):
    """The bound itself is a confidence: 1.0 grades on the first run."""
    result, calls = _grade(monkeypatch, [_good(conf=1.0)])
    assert calls["n"] == 1
    assert not result.unavailable and result.confidence == 1.0


@pytest.mark.parametrize("raw, want", [(1.02, 0.0), (40, 0.0), (1, 1.0), (0.7, 0.7), (-0.2, 0.0)])
def test_trusted_confidence_reads_a_value_past_one_as_none(raw, want):
    out = g.GraderOutput.model_validate_json(json.dumps(_grader_out(raw)))
    assert g.trusted_confidence(out) == want
    assert out.confidence == min(max(raw, 0.0), 1.0)  # the field itself is only clamped
