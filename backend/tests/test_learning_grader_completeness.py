"""A broken model verdict must not become a student's incorrect observation."""

import asyncio

import pytest
from pydantic_ai.models.function import FunctionModel

from agents import grader as g
from agents.tools.check import CheckAnswer, grade_answer
from tests import grader_fakes
from tests.test_learning_check_tool import _deps, _good, _item


HONEST = "The base case stops the recursive calls; without it the stack grows without bound."

BAD_VERDICTS = [
    [],
    ["r1:yes"],
    ["r1:no"],
    ["r1:yes", "r2:unclear"],
    ["r1:no", "r2"],
    ["r1:yes", "r1:yes", "r2:yes"],
    ["r1:yes", "r1:no", "r2:no"],
    ["r1:yes", "r2:yes", "unknown:no"],
]


def _submit(model, monkeypatch, *, answer=HONEST):
    monkeypatch.setattr(g, "record_agent_usage", lambda *a, **kw: None)
    monkeypatch.setattr(g, "model_for", lambda slot: model)
    deps = _deps()
    with g.grader_agent.override(model=model):
        outcome = asyncio.run(
            grade_answer(
                _item(), CheckAnswer(question_hash="qh-1", answer_text=answer),
                deps=deps, node_id="node-1",
            )
        )
    return outcome, deps.pending_evidence


@pytest.mark.parametrize("entries", BAD_VERDICTS)
@pytest.mark.parametrize("answer", [HONEST, "The base case is unnecessary because recursion stops itself."])
def test_incomplete_primary_verdict_never_records_either_outcome(monkeypatch, entries, answer):
    model, calls = grader_fakes.scripted_grader([{**_good(), "item_results": entries}])
    outcome, evidence = _submit(model, monkeypatch, answer=answer)
    assert outcome.unavailable and outcome.correct is None and outcome.evidence is None
    assert evidence == []
    assert calls["n"] == 1 and calls["spans"] == 0 and calls["contexts"] == 0


@pytest.mark.parametrize("entries", BAD_VERDICTS)
def test_incomplete_replacing_second_opinion_is_not_a_failure(monkeypatch, entries):
    model, calls = grader_fakes.scripted_grader(
        [_good(conf=0.1), {**_good(), "item_results": entries}]
    )
    outcome, evidence = _submit(model, monkeypatch)
    assert outcome.unavailable and outcome.correct is None and evidence == []
    assert calls["n"] == 2 and calls["spans"] == 0


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize(
    "support",
    [[], ["r1:"], ["unknown: unsupported"], ["r1: quoted", "r1: quoted"]],
)
def test_missing_or_ambiguous_support_is_not_incorrect_evidence(monkeypatch, partial, support):
    payload = {**_good(), "support": support}
    if partial:
        payload["item_results"] = ["r1:yes", "r2:no"]
    model, calls = grader_fakes.scripted_grader([payload])
    outcome, evidence = _submit(model, monkeypatch)
    assert outcome.unavailable and outcome.correct is None and evidence == []
    assert calls["n"] == 1 and calls["spans"] == 0


@pytest.mark.parametrize("stage,field", [("span", "asserted"), ("span", "item_results"), ("context", "withdrawn")])
@pytest.mark.parametrize("failure", ["missing", "duplicate", "unknown-verdict", "extra-label"])
def test_invalid_support_checks_degrade_after_one_bounded_retry(monkeypatch, stage, field, failure):
    calls = {"span": 0, "context": 0}

    def handler(messages, info):
        current = (
            "context" if grader_fakes.is_context_check(info)
            else "span" if grader_fakes.is_span_check(info)
            else "grade"
        )
        if current == "grade":
            return grader_fakes.reply(info, grader_fakes.labelled(_good(), messages))
        calls[current] += 1
        out = (
            grader_fakes.context_verdicts(messages) if current == "context"
            else grader_fakes.span_verdicts(messages)
        )
        if current == stage:
            values = out[field]
            if failure == "missing":
                out[field] = values[:-1]
            elif failure == "duplicate":
                out[field] = values + values[:1]
            elif failure == "unknown-verdict":
                out[field] = [values[0].partition(":")[0] + ":unclear", *values[1:]]
            else:
                out[field] = [*values, "unknown:no"]
        return grader_fakes.reply(info, out)

    outcome, evidence = _submit(FunctionModel(handler), monkeypatch)
    assert outcome.unavailable and outcome.correct is None and outcome.evidence is None
    assert evidence == [] and calls[stage] == 2
    assert calls["context"] == (2 if stage == "context" else 0)


@pytest.mark.parametrize("correct", [True, False])
def test_complete_verdicts_still_record_real_positive_and_negative_evidence(monkeypatch, correct):
    payload = _good() if correct else {**_good(), "item_results": ["r1:no", "r2:no"]}
    model, _ = grader_fakes.scripted_grader([payload])
    outcome, evidence = _submit(model, monkeypatch)
    assert not outcome.unavailable and outcome.correct is correct
    assert len(evidence) == 1 and evidence[0]["correct"] is correct


def test_every_actual_model_request_keeps_generation_bounds(monkeypatch):
    """Second-opinion thinking overrides must not drop response/timeout caps."""
    from learning.params import GRADER_OUTPUT_MAX_TOKENS, GRADER_REQUEST_TIMEOUT_S

    settings = []

    def handler(messages, info):
        settings.append(info.model_settings)
        return grader_fakes.check_reply(messages, info) or grader_fakes.reply(
            info, grader_fakes.labelled(_good(), messages)
        )

    outcome, evidence = _submit(FunctionModel(handler), monkeypatch)
    assert outcome.correct and len(evidence) == 1 and len(settings) == 3
    for request in settings:
        assert request["max_tokens"] == GRADER_OUTPUT_MAX_TOKENS
        assert request["timeout"] == GRADER_REQUEST_TIMEOUT_S
    assert all(request["google_thinking_config"].thinking_budget == 0 for request in settings[1:])
