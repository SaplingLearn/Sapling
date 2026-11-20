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


def test_a_grade_whose_run_overshoots_the_bound_is_graded_in_one_run(monkeypatch):
    """End to end: a primary verdict at confidence 1.02 grades on its first run —
    no output retry, no second opinion, no outage."""
    monkeypatch.setattr(g, "record_agent_usage", lambda *a, **kw: None)
    model, calls = grader_fakes.scripted_grader([_good(conf=1.02)])
    monkeypatch.setattr(g, "model_for", lambda slot: model)
    with g.grader_agent.override(model=model):
        result = asyncio.run(g.grade(_item(), format="free", student_answer=HONEST, deps=_deps()))
    assert not result.unavailable and result.all_yes
    assert result.confidence == 1.0
    assert calls["n"] == 1  # one grading run: the overshoot cost no retry
