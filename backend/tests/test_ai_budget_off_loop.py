"""The AI budget's llm_usage read never blocks the event loop (#866 Z16).

`services.ai_budget.check` is sync: on a cache miss it pages every llm_usage
row the student wrote this month. The grader (`grade()` and each `_run_once`:
the primary run, the second opinion, the span and context checks), the loop's
decision seam (`_run_decision`, `_serve_jev`) and the session close are
`async def`s awaited on the FastAPI event loop, and the per-request summary
lives only `_REQUEST_CACHE_TTL_S` (5 s), so a later run in a slow request
repeated the whole paged read ON the loop, stalling every request and SSE
stream on the replica. Each of those budget checks now hops to a worker
thread, as the loop tutor's own checks do (services/loop/runner.py).

`_load_rows` (the one paged read) is replaced by a probe that records whether
it ran on a thread with a running event loop. With no request key there is no
per-request cache, so every check reads: what a check past the 5 s window does.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from agents import grader as g
from agents.session_close import run_session_close
from learning.session_close import build_close
from services import ai_budget
from services import learning_decisions as ld
from tests import grader_fakes
from tests.test_learning_check_tool import _deps, _good, _item

HONEST = "The base case stops the recursive calls; without it the stack grows without bound."


@pytest.fixture
def usage_reads(monkeypatch):
    """One entry per llm_usage read the budget made: True when it ran on an
    event-loop thread (the defect), False on a worker thread."""
    seen: list[bool] = []

    def load(user_id, since):
        seen.append(asyncio._get_running_loop() is not None)
        return []

    monkeypatch.setattr(ai_budget, "_load_rows", load)
    return seen


def test_every_grader_budget_check_reads_off_the_event_loop(monkeypatch, usage_reads):
    """grade()'s own check and each run's (the primary, the span check, the
    context check) — none of them blocks the loop."""
    monkeypatch.setattr(g, "record_agent_usage", lambda *a, **kw: None)
    model, calls = grader_fakes.scripted_grader([_good(conf=0.9)])
    monkeypatch.setattr(g, "model_for", lambda slot: model)
    with g.grader_agent.override(model=model):
        result = asyncio.run(g.grade(_item(), format="free", student_answer=HONEST, deps=_deps()))
    assert result.all_yes and not result.unavailable  # it graded, through every run
    assert calls["n"] == 1 and calls["spans"] == 1 and calls["contexts"] == 1
    assert len(usage_reads) == 4, usage_reads  # grade() + three runs
    assert usage_reads == [False] * 4, "a grader budget check read llm_usage on the event loop"


def test_the_decision_runs_read_the_budget_off_the_event_loop(monkeypatch, usage_reads):
    """`_run_decision` (the learning_decision agent) and `_serve_jev` (the Jev
    backend) check the budget first; neither read runs on the loop."""
    monkeypatch.setattr(ld, "record_agent_usage", lambda *a, **kw: None)

    def handler(messages, info):
        return ModelResponse(parts=[TextPart('{"answer": "yes", "confidence": 0.9}')])

    state = SimpleNamespace(passages=["The base case stops recursion."], question="Q?", reference="R.")
    with ld.learning_decision_agent.override(model=FunctionModel(handler)):
        out = asyncio.run(ld._run_decision("item_answerable", state, _deps()))
    assert out is not None and out.answer == "yes"
    monkeypatch.setattr(ld, "_call_jev", AsyncMock(return_value=ld._JevOut(None, error_code="unavailable")))
    served, reason = asyncio.run(ld._serve_jev("item_answerable", state, _deps()))
    assert served is None and reason == "unavailable"
    assert usage_reads == [False, False], usage_reads


def _inline_budget_checks(source: str) -> list[int]:
    """Lines where an `async def`'s own body calls `ai_budget.check(...)` inline
    (a nested def or lambda is its own scope: it may run in a thread)."""
    scopes = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
    lines = []
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        stack = [n for n in fn.body if not isinstance(n, scopes)]
        while stack:
            node = stack.pop()
            func = getattr(node, "func", None) if isinstance(node, ast.Call) else None
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "check"
                and isinstance(func.value, (ast.Name, ast.Attribute))
                and (func.value.id if isinstance(func.value, ast.Name) else func.value.attr)
                == "ai_budget"
            ):
                lines.append(node.lineno)
            stack.extend(c for c in ast.iter_child_nodes(node) if not isinstance(c, scopes))
    return lines


def test_no_async_def_calls_the_budget_check_inline():
    """The static half: every `async def` in the served app hops the check
    (`await asyncio.to_thread(ai_budget.check, ...)`); the scanner itself is pinned."""
    assert _inline_budget_checks("async def f(u):\n    ai_budget.check(u, 'grader')\n") == [2]
    hop = "async def f(u):\n    await asyncio.to_thread(ai_budget.check, u, 'grader')\n"
    assert _inline_budget_checks(hop) == []
    assert _inline_budget_checks("def f(u):\n    ai_budget.check(u, 'grader')\n") == []
    backend = Path(__file__).resolve().parents[1]
    offenders = [
        f"{py.relative_to(backend)}:{line}"
        for root in ("agents", "learning", "routes", "services", "worker")
        for py in (backend / root).rglob("*.py")
        for line in _inline_budget_checks(py.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"ai_budget.check on the event loop: {offenders}"


def test_the_session_close_reads_the_budget_off_the_event_loop(monkeypatch, usage_reads):
    from agents import session_close as sc

    monkeypatch.setattr(sc.session_close_agent, "run", AsyncMock(side_effect=RuntimeError("no model")))
    draft = build_close([], [], [], measured_before=())
    assert asyncio.run(run_session_close(draft, user_id="u1", request_id="r1")) is None
    assert usage_reads == [False], usage_reads
