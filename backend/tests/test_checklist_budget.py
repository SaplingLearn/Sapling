"""Hermetic RPC protocol and dispatch/receipt tests; SQL races need real DB tests."""
from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.usage import RequestUsage, RunUsage

import config
from agents.topic_checklist import TopicOutline, topic_checklist_agent
from agents.topic_checklist_model import wrap_topic_checklist_model
from services import checklist_budget as budget
from services import topic_checklist_service as svc
from services.checklist_budget_run import ChecklistDispatches
from services.usage_receipts import prepare_checklist_usage_receipt

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


@pytest.fixture
def reservation():
    return budget.Reservation(uuid4(), "owner", "enrollment", "a" * 64, 7)


def row(reservation, state="prepared"):
    return {"operation_id": str(reservation.operation_id), "user_id": reservation.user_id,
            "enrollment_id": reservation.enrollment_id, "input_hash": reservation.input_hash,
            "fence": reservation.fence, "state": state,
            "dispatch_at": NOW.isoformat() if state != "prepared" else None}


def response():
    return ModelResponse(parts=[TextPart("complete")], model_name=budget.MODEL, provider_name="google-gla",
                         usage=RequestUsage(input_tokens=100, output_tokens=20))


def receipt(reservation):
    return prepare_checklist_usage_receipt(operation_id=reservation.operation_id, user_id=reservation.user_id,
        approved_model=budget.MODEL, responses=(response(),), dispatched_requests=1,
        usage=RunUsage(requests=1, input_tokens=100, output_tokens=20), completed=True, dispatched_at=NOW)


def test_admission_lost_ack_replays_identical_operation_and_receipt(monkeypatch):
    calls = []

    def rpc(name, params):
        calls.append((name, dict(params)))
        if len(calls) == 1:
            raise TimeoutError("committed but acknowledgment lost")
        return {"status": "replay", "reservation": {
            "operation_id": params["p_operation_id"], "user_id": params["p_user_id"],
            "enrollment_id": params["p_enrollment_id"], "input_hash": params["p_input_hash"],
            "fence": 1, "state": "prepared"}}

    monkeypatch.setattr(budget, "rpc", rpc)
    result = budget.admit("owner", "enrollment", "a" * 64)
    assert result.user_id == "owner"
    assert calls[0] == calls[1]
    assert calls[0][1]["p_policy"] == budget.POLICY
    assert calls[0][1]["p_daily_usd"] == str(config.STUDENT_DAILY_BUDGET_USD)


@pytest.mark.parametrize("status,code", [("busy", 409), ("denied", 429), ("blocked", 429),
    ("ownership", 404), ("usage_unavailable", 503), ("conflict", 503)])
def test_admission_failures_never_authorize_dispatch(monkeypatch, status, code):
    monkeypatch.setattr(budget, "rpc", lambda *args: {"status": status})
    with pytest.raises(HTTPException) as error:
        budget.admit("owner", "enrollment", "a" * 64)
    assert error.value.status_code == code


def test_coalesced_cache_hit_is_free(monkeypatch):
    monkeypatch.setattr(budget, "rpc", lambda *args: {"status": "cached"})
    assert budget.admit("owner", "enrollment", "a" * 64) is None


@pytest.mark.parametrize("key,value", [("user_id", "other"), ("enrollment_id", "other"),
    ("input_hash", "b" * 64), ("operation_id", str(uuid4())), ("state", "started")])
def test_admission_rejects_wrong_replay(monkeypatch, key, value):
    def rpc(name, params):
        r = {"operation_id": params["p_operation_id"], "user_id": params["p_user_id"],
             "enrollment_id": params["p_enrollment_id"], "input_hash": params["p_input_hash"],
             "fence": 1, "state": "prepared"}
        r[key] = value
        return {"status": "replay", "reservation": r}
    monkeypatch.setattr(budget, "rpc", rpc)
    with pytest.raises(HTTPException):
        budget.admit("owner", "enrollment", "a" * 64)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), "invalid", None])
def test_bad_cap_never_reaches_rpc(monkeypatch, value):
    monkeypatch.setattr(config, "STUDENT_DAILY_BUDGET_USD", value)
    monkeypatch.setattr(budget, "rpc", lambda *args: pytest.fail("Malformed policy reached DB"))
    with pytest.raises(HTTPException):
        budget.admit("owner", "enrollment", "a" * 64)


def test_changed_price_fails_before_admission(monkeypatch):
    monkeypatch.setattr(budget.llm_pricing, "cost_usd", lambda *args: 0.10)
    monkeypatch.setattr(budget, "rpc", lambda *args: pytest.fail("Stale price profile reached DB"))
    with pytest.raises(HTTPException):
        budget.admit("owner", "enrollment", "a" * 64)


def test_ambiguous_start_is_never_retried(monkeypatch, reservation):
    calls = []
    def rpc(name, params):
        calls.append(name)
        raise TimeoutError("committed but ACK lost")
    monkeypatch.setattr(budget, "rpc", rpc)
    with pytest.raises(HTTPException):
        budget.start(reservation)
    assert calls == ["checklist_budget_start"]


def test_start_replay_does_not_authorize_second_dispatch(monkeypatch, reservation):
    monkeypatch.setattr(budget, "rpc", lambda *args: {"status": "not_started", "reservation": row(reservation, "started")})
    with pytest.raises(HTTPException) as error:
        budget.start(reservation)
    assert error.value.status_code == 409


def test_settlement_lost_ack_replays_same_immutable_bill(monkeypatch, reservation):
    prepared = receipt(reservation)
    calls = []
    def rpc(name, params):
        calls.append((name, dict(params)))
        if len(calls) == 1:
            raise TimeoutError("lost ACK")
        return {"status": "settled", "reservation": {**row(reservation, "settled"),
            "receipt": prepared.to_row(), "fingerprint": prepared.fingerprint}}
    monkeypatch.setattr(budget, "rpc", rpc)
    result = budget.reconcile(reservation, receipt=prepared, content="encrypted")
    assert result["state"] == "settled" and calls[0] == calls[1]
    assert calls[0][1]["p_action"] == "settle"


@pytest.mark.parametrize("changed", [False, True])
def test_settlement_readback_verifies_full_receipt(monkeypatch, reservation, changed):
    prepared = receipt(reservation)
    calls = []
    def rpc(name, params):
        calls.append(name)
        if name.endswith("reconcile"):
            raise TimeoutError("ACK unavailable")
        recovered = prepared.to_row()
        if changed:
            recovered["cost_usd"] = 1
        return {"status": "found", "reservation": {**row(reservation, "settled"),
            "receipt": recovered, "fingerprint": prepared.fingerprint}}
    monkeypatch.setattr(budget, "rpc", rpc)
    if changed:
        with pytest.raises(HTTPException):
            budget.reconcile(reservation, receipt=prepared)
    else:
        assert budget.reconcile(reservation, receipt=prepared)["state"] == "settled"
    assert calls == ["checklist_budget_reconcile", "checklist_budget_reconcile", "checklist_budget_read"]


def test_changed_receipt_conflict_keeps_failure_visible(monkeypatch, reservation):
    monkeypatch.setattr(budget, "rpc", lambda *args: {"status": "conflict"})
    with pytest.raises(HTTPException):
        budget.reconcile(reservation, receipt=receipt(reservation))


def google_model():
    # Construct a native model only; handler below supplies the response. No
    # provider/key/environment transport is used by these hermetic tests.
    return GoogleModel(budget.MODEL, provider=GoogleProvider(api_key="unit-test-placeholder"))


def test_dispatch_tracker_counts_raised_unknown_request(monkeypatch, reservation):
    started = replace(reservation, dispatch_at=NOW)
    monkeypatch.setattr(budget, "start", lambda r: started)
    tracker = ChecklistDispatches(reservation=reservation)
    async def handler(ctx):
        raise TimeoutError("remote outcome unknown")
    with pytest.raises(TimeoutError):
        asyncio.run(tracker.wrap_model_request(None, request_context=SimpleNamespace(model=google_model()), handler=handler))
    assert tracker.dispatched == 1 and tracker.responses == []
    assert tracker.reservation == started and not tracker.nonbillable_test


def test_dispatch_tracker_starts_once_records_every_response(monkeypatch, reservation):
    starts = []
    def start(r):
        starts.append(r)
        return replace(r, dispatch_at=NOW)
    monkeypatch.setattr(budget, "start", start)
    tracker = ChecklistDispatches(reservation=reservation)
    async def handler(ctx):
        return response()
    async def run():
        for _ in range(2):
            await tracker.wrap_model_request(None, request_context=SimpleNamespace(model=google_model()), handler=handler)
    asyncio.run(run())
    assert len(starts) == 1 and tracker.dispatched == len(tracker.responses) == 2


def test_lost_start_ack_does_not_enter_generation(monkeypatch, reservation):
    tracker = ChecklistDispatches(reservation=reservation)
    def start(r):
        raise HTTPException(503, "ACK lost")
    monkeypatch.setattr(budget, "start", start)
    async def handler(ctx):
        pytest.fail("Ambiguous start launched generation")
    with pytest.raises(HTTPException):
        asyncio.run(tracker.wrap_model_request(None, request_context=SimpleNamespace(model=google_model()), handler=handler))
    assert tracker.dispatched == 0


@pytest.mark.parametrize("local", [False, True])
def test_only_explicit_local_function_model_is_free(monkeypatch, reservation, local):
    monkeypatch.setattr(config, "IS_LOCAL", local)
    monkeypatch.setattr(budget, "start", lambda *args: pytest.fail("FunctionModel must not start a paid dispatch"))
    tracker = ChecklistDispatches(reservation=reservation)
    async def handler(ctx):
        return response()
    model = FunctionModel(lambda *args: response())
    if local:
        asyncio.run(tracker.wrap_model_request(None, request_context=SimpleNamespace(model=model), handler=handler))
        assert tracker.nonbillable_test and tracker.dispatched == 1
    else:
        with pytest.raises(ValueError):
            asyncio.run(tracker.wrap_model_request(None, request_context=SimpleNamespace(model=model), handler=handler))
        assert tracker.dispatched == 0 and not tracker.nonbillable_test


def test_failed_complete_outline_still_settles_bill_without_cache(monkeypatch, reservation):
    tracker = ChecklistDispatches(reservation=replace(reservation, dispatch_at=NOW), dispatched=1, responses=[response()])
    failure = ValueError("invalid outline")
    generation = svc.ChecklistGeneration(RunUsage(requests=1, input_tokens=100, output_tokens=20), tracker, error=failure)
    calls = []
    monkeypatch.setattr(budget, "reconcile", lambda *args, **kwargs: calls.append(kwargs))
    with pytest.raises(ValueError) as error:
        svc._finish_generation(generation, {})
    assert error.value is failure
    assert calls[0]["receipt"].to_row()["cost_usd"] > 0
    assert calls[0]["content"] is None and not calls[0]["no_dispatch"]


@pytest.mark.parametrize("free_first", [False, True])
def test_a_test_model_can_never_release_a_real_models_bill(monkeypatch, reservation, free_first):
    monkeypatch.setattr(config, "IS_LOCAL", True)
    starts = []

    def start(value):
        starts.append(value)
        return replace(value, dispatch_at=NOW)

    monkeypatch.setattr(budget, "start", start)
    tracker = ChecklistDispatches(reservation=reservation)
    models = [FunctionModel(lambda *args: response()), google_model()]
    if not free_first:
        models.reverse()
    handlers = []

    async def handler(ctx):
        handlers.append(ctx.model)
        return response()

    async def run():
        await tracker.wrap_model_request(None, request_context=SimpleNamespace(model=models[0]), handler=handler)
        with pytest.raises(ValueError, match="cannot mix"):
            await tracker.wrap_model_request(None, request_context=SimpleNamespace(model=models[1]), handler=handler)

    asyncio.run(run())
    assert len(handlers) == tracker.dispatched == len(tracker.responses) == 1
    assert tracker.nonbillable_test is free_first
    assert len(starts) == (0 if free_first else 1)


@pytest.mark.parametrize("kind", ["timeout", "missing_usage", "hidden_attempt", "mixed_model"])
def test_unknown_or_incomplete_run_keeps_hold_and_no_cache(monkeypatch, reservation, kind):
    r = response()
    tracker = ChecklistDispatches(reservation=replace(reservation, dispatch_at=NOW), dispatched=1, responses=[r])
    usage = RunUsage(requests=1, input_tokens=100, output_tokens=20)
    failure = None
    if kind == "timeout":
        tracker.responses.clear()
        failure = TimeoutError("unknown")
    elif kind == "missing_usage":
        r.usage = RequestUsage()
    elif kind == "hidden_attempt":
        tracker.dispatched = 2
    else:
        r.model_name = "gemini-2.5-pro"
    generation = svc.ChecklistGeneration(usage, tracker, outline=TopicOutline(topics=[]), error=failure)
    calls = []
    monkeypatch.setattr(budget, "reconcile", lambda *args, **kwargs: calls.append(kwargs))
    with pytest.raises(Exception):
        svc._finish_generation(generation, {"sources": []})
    assert calls[0] == {"receipt": None, "content": None, "no_dispatch": False}


def test_counter_only_failure_releases_proven_no_generation(monkeypatch, reservation):
    tracker = ChecklistDispatches(reservation=reservation)
    generation = svc.ChecklistGeneration(RunUsage(), tracker, error=ValueError("count preflight denied"))
    calls = []
    monkeypatch.setattr(budget, "reconcile", lambda *args, **kwargs: calls.append(kwargs))
    with pytest.raises(ValueError):
        svc._finish_generation(generation, {})
    assert calls[0] == {"receipt": None, "content": None, "no_dispatch": True}


def test_real_sdk_function_run_uses_capability_and_never_paid_receipt(monkeypatch, reservation):
    from pydantic_ai.messages import ToolCallPart
    monkeypatch.setattr(config, "IS_LOCAL", True)
    def handler(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"topics": []})])
    with topic_checklist_agent.override(model=wrap_topic_checklist_model(FunctionModel(handler))):
        result = asyncio.run(svc._generate({"sources": [], "assessments": []}, "owner", reservation))
    assert result.error is None and result.outline == TopicOutline(topics=[])
    assert result.dispatches.nonbillable_test and result.dispatches.dispatched == 1
    assert len(result.dispatches.responses) == 1


@pytest.mark.parametrize("component", ["cached", "input", "output"])
def test_component_price_mismatch_fails_even_if_aggregate_quote_unchanged(monkeypatch, component):
    real = budget.llm_pricing.cost_usd
    def price(model, prompt, completion, **kwargs):
        if component == "cached" and kwargs.get("cached_tokens"):
            return .00004
        if component == "input" and prompt == 1000 and completion == 0:
            return .0004
        if component == "output" and prompt == 0 and completion == 1000:
            return .0026
        return real(model, prompt, completion, **kwargs)
    monkeypatch.setattr(budget.llm_pricing, "cost_usd", price)
    monkeypatch.setattr(budget, "rpc", lambda *args: pytest.fail("Changed price profile reached DB"))
    with pytest.raises(HTTPException):
        budget.admit("owner", "enrollment", "a" * 64)


@pytest.mark.parametrize("cancel", [False, True])
def test_start_wait_does_not_block_run_deadline_or_dispatch_after_cancellation(monkeypatch, reservation, cancel):
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    handlers = []
    def delayed_start(r):
        entered.set()
        try:
            assert release.wait(2)
            return replace(r, dispatch_at=NOW)
        finally:
            returned.set()
    monkeypatch.setattr(budget, "start", delayed_start)
    monkeypatch.setattr(svc, "GENERATION_TIMEOUT_SECONDS", .02)
    async def handler(ctx):
        handlers.append(True)
        return response()
    async def sdk_run(message, **kwargs):
        tracker = kwargs["capabilities"][0]
        await tracker.wrap_model_request(None, request_context=SimpleNamespace(model=google_model()), handler=handler)
    monkeypatch.setattr(topic_checklist_agent, "run", sdk_run)
    async def run():
        task = asyncio.create_task(svc._generate({}, "owner", reservation))
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(.001)
            assert entered.is_set()
            if cancel:
                task.cancel()
            result = await asyncio.wait_for(task, .2)
            assert isinstance(result.error, asyncio.CancelledError if cancel else TimeoutError)
            assert result.dispatches.dispatched == 0 and result.dispatches.responses == []
            assert handlers == [] and not returned.is_set()
            calls = []
            monkeypatch.setattr(budget, "reconcile", lambda *args, **kwargs: calls.append(kwargs))
            with pytest.raises(type(result.error)):
                svc._finish_generation(result, {})
            assert calls == [{"receipt": None, "content": None, "no_dispatch": True}]
        finally:
            release.set()
        for _ in range(100):
            if returned.is_set():
                break
            await asyncio.sleep(.001)
        assert returned.is_set() and handlers == []
    asyncio.run(run())


@pytest.mark.parametrize("key,value", [("user_id", "other"), ("enrollment_id", "other"),
    ("input_hash", "b" * 64), ("fence", True), ("dispatch_at", "2026-10-19T12:00:00")])
def test_malformed_start_ack_cannot_change_reservation_identity(monkeypatch, reservation, key, value):
    r = row(reservation, "started")
    r[key] = value
    monkeypatch.setattr(budget, "rpc", lambda *args: {"status": "started", "reservation": r})
    with pytest.raises(HTTPException):
        budget.start(reservation)


def test_sql_coalesced_hit_precedes_legacy_budget_failure(monkeypatch, reservation):
    scope = {"enrollment_id": "enrollment"}
    snapshot = {"hash": "a" * 64, "payload": {"sources": [{"id": "source"}]}}
    monkeypatch.setattr(svc, "_current_checklist", lambda *args: (NOW, scope, snapshot, None))
    monkeypatch.setattr(budget, "admit", lambda *args: None)
    monkeypatch.setattr(svc.ai_budget, "check", lambda *args: pytest.fail("Free coalesced cache hit reached budget preflight"))
    monkeypatch.setattr(svc, "_cache", lambda *args: {"input_hash": "a" * 64})
    monkeypatch.setattr(svc, "present", lambda *args: "cached")
    assert svc.refresh_checklist("owner", "course") == "cached"


def test_pre_generation_denial_releases_only_prepared_hold(monkeypatch, reservation):
    scope = {"enrollment_id": "enrollment"}
    snapshot = {"hash": "a" * 64, "payload": {"sources": [{"id": "source"}]}}
    monkeypatch.setattr(svc, "_current_checklist", lambda *args: (NOW, scope, snapshot, None))
    monkeypatch.setattr(budget, "admit", lambda *args: reservation)
    calls = []
    monkeypatch.setattr(budget, "reconcile", lambda *args, **kwargs: calls.append(kwargs))
    def unavailable(*args):
        raise svc.ai_budget.AIBudgetUnavailable("unknown usage")
    monkeypatch.setattr(svc.ai_budget, "check", unavailable)
    monkeypatch.setattr(svc, "_generate", lambda *args: pytest.fail("Denial entered generation"))
    with pytest.raises(HTTPException) as error:
        svc.refresh_checklist("owner", "course")
    assert error.value.status_code == 503
    assert calls == [{"no_dispatch": True}]
