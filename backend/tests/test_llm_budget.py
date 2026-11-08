"""#119: the per-user daily LLM token budget (`services/llm_budget.py`, flag
`llm_budget`) at the model chokepoint, and how every surface maps its refusal.

Hermetic: the primary is a pydantic-ai `FunctionModel` wearing the real
`_ResilientModelMixin` (as in test_llm_resilience.py); the status read
(`read_status`, one `llm_budget_status` RPC) is replaced by a recorder; the
session user is set the way RequestIDMiddleware sets it. The SQL itself is
pinned in tests/integration/test_llm_budgets_db.py.
"""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from agents import _resilience
from agents._providers import _ResilientModelMixin
from services import llm_budget, request_context
from services.llm_budget import BudgetStatus, LLMBudgetExceeded

USER = "user_budget"
RESET = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


# ── fixtures / helpers ───────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    _resilience.reset_for_tests()
    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "off")
    monkeypatch.setenv("SAPLING_FLAG_LLM_BUDGET", "on")
    llm_budget.clear_llm_budget_cache()
    yield
    llm_budget.clear_llm_budget_cache()
    _resilience.reset_for_tests()


@pytest.fixture
def status(monkeypatch):
    """Script `read_status`: set `.value` (a BudgetStatus, or an exception to
    raise); `.calls` counts reads."""
    box = SimpleNamespace(value=BudgetStatus(limit=1000, used=0, source="default", reset_at=RESET),
                          calls=[])

    def fake(user_id):
        box.calls.append(user_id)
        if isinstance(box.value, BaseException):
            raise box.value
        return box.value

    monkeypatch.setattr(llm_budget, "read_status", fake)
    return box


def _over(limit=1000):
    return BudgetStatus(limit=limit, used=limit, source="default", reset_at=RESET)


@contextlib.contextmanager
def session_user(user_id: str | None = USER):
    """What RequestIDMiddleware + auth_guard leave behind for a request."""
    view = request_context.RequestView({"state": {"user_id": user_id} if user_id else {}})
    token = request_context._REQUEST_CTX.set(view)
    try:
        yield
    finally:
        request_context._REQUEST_CTX.reset(token)


class _ResilientFn(_ResilientModelMixin, FunctionModel):
    def __init__(self, function=None, *, stream_function=None, task="chat_tutor",
                 fallback=True, model_name="claude-sonnet-5-5"):
        super().__init__(function, stream_function=stream_function, model_name=model_name)
        self._init_resilience(provider="anthropic", task=task, allow_fallback=fallback)


def _counting(text="ok"):
    calls = {"n": 0}

    def fn(messages, info):
        calls["n"] += 1
        return ModelResponse(parts=[TextPart(text)])

    return fn, calls


# ── the run-start heuristic ──────────────────────────────────────────────


def test_only_the_first_request_of_a_run_is_a_run_start():
    first = [ModelRequest(parts=[UserPromptPart("hi")])]
    assert llm_budget.starts_run(first)
    assert llm_budget.starts_run([])
    tool_loop = first + [
        ModelResponse(parts=[ToolCallPart("t", {}, tool_call_id="c1")]),
        ModelRequest(parts=[ToolReturnPart("t", "x", tool_call_id="c1")]),
    ]
    assert not llm_budget.starts_run(tool_loop)
    retry = first + [ModelResponse(parts=[TextPart("bad")]),
                     ModelRequest(parts=[RetryPromptPart("fix it")])]
    assert not llm_budget.starts_run(retry)
    # a new turn on top of a history is a new run
    next_turn = tool_loop + [ModelResponse(parts=[TextPart("done")]),
                             ModelRequest(parts=[UserPromptPart("again")])]
    assert llm_budget.starts_run(next_turn)


# ── the gate at the chokepoint ───────────────────────────────────────────


def test_over_budget_refuses_before_the_model_is_called(status):
    status.value = _over()
    fn, calls = _counting()
    with session_user(), pytest.raises(LLMBudgetExceeded) as exc:
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    assert calls["n"] == 0
    err = exc.value
    assert isinstance(err, HTTPException) and err.status_code == 429
    assert "today's limit" in err.detail and "midnight UTC" in err.detail
    assert 0 < int(err.headers["Retry-After"]) <= 86400
    assert err.code == "LLM_BUDGET_EXCEEDED" and err.reset_at == RESET


def test_under_budget_and_unlimited_runs_go_through(status):
    fn, calls = _counting()
    with session_user():
        assert asyncio.run(Agent(_ResilientFn(fn)).run("hi")).output == "ok"
        status.value = BudgetStatus(limit=None, used=10**9, source="role:admin", reset_at=RESET)
        llm_budget.clear_llm_budget_cache()
        assert asyncio.run(Agent(_ResilientFn(fn)).run("hi")).output == "ok"
    assert calls["n"] == 2


def test_no_session_user_is_never_budgeted(status):
    """The sweeper, the job worker, scripts and evals run with no user."""
    status.value = _over()
    fn, calls = _counting()
    with session_user(None):
        assert asyncio.run(Agent(_ResilientFn(fn)).run("hi")).output == "ok"
    assert asyncio.run(Agent(_ResilientFn(fn)).run("hi")).output == "ok"  # no request at all
    assert status.calls == []


def test_flag_off_reads_nothing(status, monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_LLM_BUDGET", "off")
    status.value = _over()
    fn, _ = _counting()
    with session_user():
        assert asyncio.run(Agent(_ResilientFn(fn)).run("hi")).output == "ok"
    assert status.calls == []


def test_the_flag_resolves_per_user(status, monkeypatch):
    from services import feature_flags as ff

    monkeypatch.delenv("SAPLING_FLAG_LLM_BUDGET")
    seen = []
    monkeypatch.setattr(ff, "cached_explain", lambda key, uid: seen.append((key, uid)) or
                        ff.Resolution("on", "user"))
    status.value = _over()
    with session_user(), pytest.raises(LLMBudgetExceeded):
        asyncio.run(Agent(_ResilientFn(_counting()[0])).run("hi"))
    assert seen == [("llm_budget", USER)]


def test_a_run_that_started_under_budget_is_never_cut_off(status):
    """Only the run's first request is checked: the tool loop finishes even
    if the budget runs out mid-run (its tools may already have written)."""
    calls = {"n": 0}

    def fn(messages, info):
        calls["n"] += 1
        if calls["n"] == 1:
            status.value = _over()  # spent while the first request ran
            llm_budget.clear_llm_budget_cache()
            return ModelResponse(parts=[ToolCallPart("lookup", {}, tool_call_id="c1")])
        return ModelResponse(parts=[TextPart("answer")])

    agent = Agent(_ResilientFn(fn))

    @agent.tool_plain
    def lookup() -> str:
        return "fact"

    with session_user():
        assert asyncio.run(agent.run("hi")).output == "answer"
        assert calls["n"] == 2
        with pytest.raises(LLMBudgetExceeded):  # ...but the NEXT run is refused
            asyncio.run(agent.run("again"))


def test_fallback_models_and_the_health_probe_are_not_budgeted(status):
    status.value = _over()
    fn, calls = _counting()
    with session_user():
        asyncio.run(Agent(_ResilientFn(fn, fallback=False)).run("hi"))
        asyncio.run(Agent(_ResilientFn(fn, task=None)).run("hi"))
    assert calls["n"] == 2 and status.calls == []


def test_function_mode_never_meets_the_budget(status, monkeypatch):
    from agents import _providers

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    status.value = _over()
    _providers.register_function_handler(
        "classifier", lambda messages, info: ModelResponse(parts=[TextPart("scripted")])
    )
    try:
        with session_user():
            assert asyncio.run(Agent(_providers.model_for("classifier")).run("hi")).output == "scripted"
    finally:
        _providers.clear_function_handlers()
    assert status.calls == []


# ── fail open + caching ──────────────────────────────────────────────────


def test_an_unreadable_status_fails_open_and_is_remembered_briefly(status):
    status.value = RuntimeError("db down")
    fn, calls = _counting()
    with session_user():
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    assert calls["n"] == 2
    assert len(status.calls) == 1  # the failure is cached (FAILURE_TTL_S), not retried per run


def test_a_slow_status_read_fails_open(status, monkeypatch):
    import time

    monkeypatch.setattr(llm_budget, "STATUS_TIMEOUT_S", 0.05)

    def slow(user_id):
        time.sleep(0.3)
        return _over()

    monkeypatch.setattr(llm_budget, "read_status", slow)
    fn, calls = _counting()
    with session_user():
        assert asyncio.run(Agent(_ResilientFn(fn)).run("hi")).output == "ok"


def test_status_is_cached_per_user_until_cleared(status):
    fn, _ = _counting()
    with session_user():
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
        assert len(status.calls) == 1
        status.value = _over()
        llm_budget.clear_llm_budget_cache(USER)  # what the admin write does
        with pytest.raises(LLMBudgetExceeded):
            asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    assert len(status.calls) == 2


def test_a_cached_status_never_outlives_the_reset(monkeypatch):
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    llm_budget._remember(USER, BudgetStatus(limit=1, used=1, source="default", reset_at=past))
    assert llm_budget._cached(USER) == (False, None)


def test_parse_status_reads_the_rpc_payload():
    s = llm_budget.parse_status({"limit": 500, "used": 600, "source": "user",
                                 "reset_at": "2026-11-09T00:00:00+00:00"})
    assert s.exceeded and s.limit == 500 and s.reset_at.tzinfo is not None
    assert llm_budget.parse_status([{"limit": None, "used": 0, "source": "none",
                                     "reset_at": "2026-11-09T00:00:00Z"}]).exceeded is False


def test_read_status_calls_the_rpc_as_service(monkeypatch):
    from db import connection, scope

    seen = {}

    def fake_rpc(name, params):
        seen.update(name=name, params=params, service=scope.in_service_scope())
        return {"limit": 1, "used": 0, "source": "default", "reset_at": RESET.isoformat()}

    monkeypatch.setattr(connection, "rpc", fake_rpc)
    assert llm_budget.read_status(USER).limit == 1
    assert seen == {"name": "llm_budget_status", "params": {"p_user_id": USER}, "service": True}


def test_the_flag_is_registered_server_only_and_off_first():
    from services.feature_flags import REGISTRY

    fd = REGISTRY["llm_budget"]
    assert fd.variants == ("off", "on") and not fd.client_visible


def test_user_message_wording():
    now = datetime(2026, 11, 8, 18, 30, tzinfo=timezone.utc)
    reset = datetime(2026, 11, 9, tzinfo=timezone.utc)
    assert "in about 6 hours" in llm_budget.user_message(reset, now=now)
    assert "in under an hour" in llm_budget.user_message(reset, now=reset - timedelta(minutes=5))


# ── how each surface answers ─────────────────────────────────────────────


def _exc() -> LLMBudgetExceeded:
    return LLMBudgetExceeded(limit=1000, used=1200, reset_at=RESET)


def test_the_tutor_json_route_passes_the_429_through():
    from routes.learn import _agent_turn_or_http_error

    async def turn():
        raise _exc()

    with pytest.raises(LLMBudgetExceeded):
        asyncio.run(_agent_turn_or_http_error(turn(), what="chat agent"))


def test_the_429_body_carries_code_message_and_reset():
    from starlette.requests import Request

    from main import llm_budget_exceeded_handler

    request = Request({"type": "http", "method": "POST", "path": "/api/learn/chat",
                       "headers": [], "query_string": b"", "state": {"request_id": "rid-1"}})
    resp = asyncio.run(llm_budget_exceeded_handler(request, _exc()))
    import json

    body = json.loads(resp.body)
    assert resp.status_code == 429 and "retry-after" in resp.headers
    assert body["detail"].startswith("You've reached today's limit")
    assert body["error"]["code"] == "LLM_BUDGET_EXCEEDED"
    assert body["error"]["reset_at"] == RESET.isoformat()


def test_a_streamed_tutor_turn_ends_in_a_terminal_budget_error(status):
    """Refused before the first token: a terminal, non-retryable `error`
    carrying the budget's message — never the Rung-1 JSON fallback (it would
    hit the same budget) and never persistence."""
    from services.chat_stream import stream_agent_turn

    status.value = _over()
    fn, calls = _counting()

    async def stream(messages, info):
        calls["n"] += 1
        yield "never"

    agent = Agent(_ResilientFn(fn, stream_function=stream))
    deps = SimpleNamespace(graph_updates=[], mastery_changes=[])
    fallback_called = []

    async def nonstream_fallback():
        fallback_called.append(1)
        return {"reply": "x"}

    def on_complete(*a):
        raise AssertionError("nothing may persist")

    async def collect():
        return [ev async for ev in stream_agent_turn(
            agent=agent, user_message="hi", run_kwargs={}, deps=deps,
            on_complete=on_complete, nonstream_fallback=nonstream_fallback, request_id="rid",
        )]

    with session_user():
        events = asyncio.run(collect())
    last = events[-1]
    assert last.type == "error"
    assert last.data["code"] == "LLM_BUDGET_EXCEEDED"
    assert last.data["retryable"] is False
    assert last.data["reset_at"] == RESET.isoformat()
    assert "today's limit" in last.message
    assert calls["n"] == 0 and fallback_called == []


def test_quiz_generation_answers_its_daily_limit_code_and_refunds_the_slot(monkeypatch):
    import routes.quiz as quiz
    from services.quiz_errors import QuizAPIError, QuizErrorCode

    async def refused(**_kw):
        raise _exc()

    refunds = []
    monkeypatch.setattr(quiz, "_quiz_via_agent", refused)
    monkeypatch.setattr(quiz, "_refund_generate_slot", lambda uid, slot: refunds.append((uid, slot)))
    body = SimpleNamespace(user_id=USER, concept_node_id="n1", difficulty="medium",
                           use_shared_context=True, model_pref=None,
                           question_format="multiple_choice", num_questions=5)
    with pytest.raises(QuizAPIError) as exc:
        asyncio.run(quiz._generate_or_502(
            body, request_id="rid", course_id="c1", concept_name="limits",
            times_studied=None, count=5, slot=1.5,
        ))
    assert exc.value.status_code == 429
    assert exc.value.code is QuizErrorCode.QUIZ_DAILY_LIMIT_REACHED
    assert "today's limit" in exc.value.detail
    assert refunds == [(USER, 1.5)]


def test_document_upload_sync_answers_429_not_502():
    from tests.test_documents_routes import _doc_text, _make_upload, _mock_validate_user

    with (
        _mock_validate_user(),
        patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
        patch("routes.documents.process_document", side_effect=_exc()),
        patch("routes.documents.table") as t,
    ):
        t.return_value.select.return_value = []
        r = _make_upload()
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "LLM_BUDGET_EXCEEDED"
    t.return_value.insert.assert_not_called()


# ── admin API ────────────────────────────────────────────────────────────


class _FakeBudgets:
    def __init__(self, store):
        self.store = store

    def select(self, columns="*", filters=None, order=None, **_):
        rows = self.store.setdefault(self.name, [])
        out = []
        for r in rows:
            if all(str(r.get(k)) == v.removeprefix("eq.") for k, v in (filters or {}).items()):
                out.append(dict(r))
        return out

    def upsert(self, data, on_conflict="id", **_):
        rows = self.store.setdefault(self.name, [])
        keys = on_conflict.split(",")
        rows[:] = [r for r in rows if any(r.get(k) != data.get(k) for k in keys)]
        rows.append(dict(data))
        return [data]

    def delete(self, filters):
        rows = self.store.setdefault(self.name, [])
        hit = [r for r in rows if all(str(r.get(k)) == v.removeprefix("eq.") for k, v in filters.items())]
        rows[:] = [r for r in rows if r not in hit]
        return hit


@pytest.fixture
def admin(monkeypatch):
    import routes.admin_llm as admin_llm

    store = {
        "llm_budgets": [{"scope": "default", "subject": "", "daily_token_limit": 2_000_000}],
        "roles": [{"id": "r1", "slug": "vip"}],
        "users": [{"id": USER}],
    }

    def table(name):
        t = _FakeBudgets(store)
        t.name = name
        return t

    audits = []
    monkeypatch.setattr(admin_llm, "table", table)
    monkeypatch.setattr(admin_llm, "log_admin_action", lambda **kw: audits.append(kw))
    from main import app

    return SimpleNamespace(client=TestClient(app), store=store, audits=audits)


def test_admin_reads_and_sets_budgets_and_the_cache_is_cleared(admin):
    llm_budget._remember(USER, _over())
    r = admin.client.put("/api/admin/llm/budgets",
                         json={"scope": "user", "subject": USER, "daily_token_limit": 50_000})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["default"]["daily_token_limit"] == 2_000_000
    assert body["users"][0]["daily_token_limit"] == 50_000
    assert admin.audits[-1]["action"] == "llm_budget.update"
    assert llm_budget._cached(USER) == (False, None)

    r = admin.client.put("/api/admin/llm/budgets", json={"scope": "role", "subject": "vip",
                                                        "daily_token_limit": None})
    assert r.status_code == 200 and r.json()["roles"][0]["daily_token_limit"] is None
    r = admin.client.put("/api/admin/llm/budgets", json={"scope": "default", "daily_token_limit": 0})
    assert r.status_code == 200 and r.json()["default"]["daily_token_limit"] == 0


def test_admin_budget_validation(admin):
    put = admin.client.put
    assert put("/api/admin/llm/budgets", json={"scope": "role", "subject": "nope",
                                               "daily_token_limit": 1}).status_code == 404
    assert put("/api/admin/llm/budgets", json={"scope": "default", "subject": "x",
                                               "daily_token_limit": 1}).status_code == 422
    assert put("/api/admin/llm/budgets", json={"scope": "user",
                                               "daily_token_limit": 1}).status_code == 422
    assert put("/api/admin/llm/budgets", json={"scope": "user", "subject": USER,
                                               "daily_token_limit": -5}).status_code == 422


def test_admin_deletes_an_override_but_never_the_default(admin):
    admin.client.put("/api/admin/llm/budgets",
                     json={"scope": "user", "subject": USER, "daily_token_limit": 5})
    assert admin.client.delete(f"/api/admin/llm/budgets/user/{USER}").status_code == 200
    assert admin.client.delete(f"/api/admin/llm/budgets/user/{USER}").status_code == 404
    assert admin.client.delete("/api/admin/llm/budgets/default/x").status_code == 422


def test_admin_status_for_a_user(admin, status):
    status.value = _over(300)
    r = admin.client.get(f"/api/admin/llm/budgets/status/{USER}")
    assert r.status_code == 200
    body = r.json()
    assert body["exceeded"] is True and body["limit"] == 300 and body["flag"] == "on"
    status.value = RuntimeError("down")
    assert admin.client.get(f"/api/admin/llm/budgets/status/{USER}").status_code == 503


def test_admin_llm_routes_are_admin_only(monkeypatch):
    import routes.admin_llm as admin_llm
    from main import app

    def deny(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    monkeypatch.setattr(admin_llm, "require_admin", deny)
    c = TestClient(app)
    assert c.get("/api/admin/llm/budgets").status_code == 403
    assert c.get("/api/admin/llm/drill").status_code == 403
    assert c.put("/api/admin/llm/budgets", json={"scope": "default",
                                                 "daily_token_limit": 1}).status_code == 403
