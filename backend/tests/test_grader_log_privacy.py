"""A grader or decision outage never writes the model's response to the log (#866 Z46).

`_GRADER_FAILURES` (and the decision seam's `_DECISION_FAILURES`, the same
tuple) include `UnexpectedModelBehavior`, whose text appends the response
body; some provider messages also embed the model's response part. The model
answers about a student's answer, so formatting the exception into a WARNING
put student text in the log store. Each site now logs
`services.log_privacy.safe_exception_text(exc)`: pydantic-ai's own message,
with the body withheld.
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.function import FunctionModel

from agents import grader as g
from services import learning_decisions as ld
from tests import grader_fakes
from tests.test_learning_check_tool import _deps, _good, _item

SECRET = "my answer: the base case is n == 0 (STUDENT-TEXT-7f3a)"
HONEST = "The base case stops the recursive calls; without it the stack grows without bound."


def _boom():
    return UnexpectedModelBehavior("Unsupported response from the model", body=SECRET)


def _logged(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records)


@pytest.fixture(autouse=True)
def _no_usage(monkeypatch):
    monkeypatch.setattr(g, "record_agent_usage", lambda *a, **kw: None)
    monkeypatch.setattr(ld, "record_agent_usage", lambda *a, **kw: None)


def _grade(model, monkeypatch):
    monkeypatch.setattr(g, "model_for", lambda slot: model)
    with g.grader_agent.override(model=model):
        return asyncio.run(g.grade(_item(), format="free", student_answer=HONEST, deps=_deps()))


def test_a_failed_grading_run_logs_no_response_body(monkeypatch, caplog):
    def handler(messages, info):
        raise _boom()

    with caplog.at_level(logging.WARNING, logger="sapling.agents.grader"):
        result = _grade(FunctionModel(handler), monkeypatch)
    assert result.unavailable
    assert "grader unavailable" in _logged(caplog)
    assert SECRET not in _logged(caplog)
    assert "response body withheld" in _logged(caplog)


@pytest.mark.parametrize("which", ["span", "context"])
def test_a_failed_span_or_context_check_logs_no_response_body(monkeypatch, caplog, which):
    def handler(messages, info):
        if (which == "span" and grader_fakes.is_span_check(info)) or (
            which == "context" and grader_fakes.is_context_check(info)
        ):
            raise _boom()
        return grader_fakes.check_reply(messages, info) or grader_fakes.reply(
            info, grader_fakes.labelled(_good(conf=0.9), messages)
        )

    with caplog.at_level(logging.WARNING, logger="sapling.agents.grader"):
        result = _grade(FunctionModel(handler), monkeypatch)
    assert result.unavailable
    assert f"the {which} check failed" in _logged(caplog)
    assert SECRET not in _logged(caplog)


def test_a_failed_decision_run_logs_no_response_body(caplog):
    def handler(messages, info):
        raise _boom()

    state = SimpleNamespace(passages=["The base case stops recursion."], question="Q?", reference="R.")
    with caplog.at_level(logging.WARNING), ld.learning_decision_agent.override(model=FunctionModel(handler)):
        assert asyncio.run(ld._run_decision("item_answerable", state, _deps())) is None
    assert "decision unavailable" in _logged(caplog)
    assert SECRET not in _logged(caplog)
