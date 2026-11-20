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
from tests.manual_clock import ManualClockLoop

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
#: The topic_checklist slot's models: its Claude default and its llm_fallback.
MODEL_NAMES = ("claude-haiku-5-5", "gemini-2.5-flash")
GEMINI = "gemini-2.5-flash"
MODELS = ("anthropic:claude-haiku-5-5", "gemini:gemini-2.5-flash")


@pytest.fixture
def reservation():
    return budget.Reservation(uuid4(), "owner", "enrollment", "a" * 64, 7, models=MODELS)


def row(reservation, state="prepared"):
    return {"operation_id": str(reservation.operation_id), "user_id": reservation.user_id,
            "enrollment_id": reservation.enrollment_id, "input_hash": reservation.input_hash,
            "fence": reservation.fence, "state": state, "models": list(reservation.models),
            "dispatch_at": NOW.isoformat() if state != "prepared" else None}


def admitted_row(params, **changes):
    """The reservation the admit RPC records for `params`."""
    return {"operation_id": params["p_operation_id"], "user_id": params["p_user_id"],
            "enrollment_id": params["p_enrollment_id"], "input_hash": params["p_input_hash"],
            "fence": 1, "state": "prepared", "models": params["p_models"],
            "held_usd": float(params["p_held_usd"]), "held_tokens": params["p_held_tokens"], **changes}


def response():
    return ModelResponse(parts=[TextPart("complete")], model_name=GEMINI, provider_name="google-gla",
                         usage=RequestUsage(input_tokens=100, output_tokens=20))


def receipt(reservation):
    return prepare_checklist_usage_receipt(operation_id=reservation.operation_id, user_id=reservation.user_id,
        approved_model=GEMINI, responses=(response(),), dispatched_requests=1,
        usage=RunUsage(requests=1, input_tokens=100, output_tokens=20), completed=True, dispatched_at=NOW)


def test_admission_lost_ack_replays_identical_operation_and_receipt(monkeypatch):
    calls = []

    def rpc(name, params):
        calls.append((name, dict(params)))
        if len(calls) == 1:
            raise TimeoutError("committed but acknowledgment lost")
        return {"status": "replay", "reservation": admitted_row(params)}

    monkeypatch.setattr(budget, "rpc", rpc)
    result = budget.admit("owner", "enrollment", "a" * 64, MODEL_NAMES)
    assert result.user_id == "owner" and result.models == MODELS
    assert calls[0] == calls[1]
    assert calls[0][1]["p_policy"] == budget.POLICY
    assert calls[0][1]["p_daily_usd"] == str(config.STUDENT_DAILY_BUDGET_USD)


def test_admission_holds_the_worst_case_price_of_every_model_that_can_serve():
    """B1: the hold is llm_pricing's price of one policy run, each component at
    its worst over the slot's model and its fallback, so a run served by either
    (or by both, one attempt each) is covered."""
    from decimal import Decimal

    from services import llm_pricing

    def price(*args, **kwargs):
        return Decimal(str(llm_pricing.cost_usd(*args, **kwargs)))

    output = budget.REQUESTS * budget.OUTPUT_TOKENS_PER_REQUEST
    expected = {}
    for names in (MODEL_NAMES, ("claude-haiku-5-5",), (GEMINI,)):
        input_usd = max(max(price(n, budget.INPUT_TOKENS, 0),
                            price(n, budget.INPUT_TOKENS, 0, cache_write_tokens=budget.INPUT_TOKENS)) for n in names)
        expected[names] = input_usd + max(price(n, 0, output) for n in names)
    for names, usd in expected.items():
        hold = budget.price_hold(names)
        assert hold.usd == usd and hold.tokens == 74_576
        assert hold.models == tuple(budget.billing_label(n) for n in names)
    # Claude alone holds its own (cache-write) worst case, far below flash's.
    assert budget.price_hold(("claude-haiku-5-5",)).usd < budget.price_hold(MODEL_NAMES).usd


def test_admission_sends_the_hold_and_its_models(monkeypatch):
    sent = []

    def rpc(name, params):
        sent.append(params)
        return {"status": "admitted", "reservation": admitted_row(params)}

    monkeypatch.setattr(budget, "rpc", rpc)
    hold = budget.price_hold(MODEL_NAMES)
    result = budget.admit("owner", "enrollment", "a" * 64, MODEL_NAMES)
    assert sent[0]["p_held_usd"] == str(hold.usd) and sent[0]["p_held_tokens"] == hold.tokens
    assert sent[0]["p_models"] == list(MODELS) and result.models == MODELS


@pytest.mark.parametrize("key,value", [("models", ["gemini:gemini-2.5-flash"]), ("held_usd", 0.01),
                                       ("held_tokens", 1)])
def test_admission_rejects_a_reservation_holding_something_else(monkeypatch, key, value):
    monkeypatch.setattr(budget, "rpc", lambda name, params: {
        "status": "admitted", "reservation": admitted_row(params, **{key: value})})
    with pytest.raises(HTTPException) as error:
        budget.admit("owner", "enrollment", "a" * 64, MODEL_NAMES)
    assert error.value.status_code == 503


@pytest.mark.parametrize("names", [(), ("claude-unpriced-9",), ("gemini-unpriced-9",), ("jev-1.13.0",)])
def test_an_unpriced_or_unbillable_model_never_reaches_admission(monkeypatch, names):
    monkeypatch.setattr(budget, "rpc", lambda *args: pytest.fail("An unpriced hold reached the DB"))
    with pytest.raises(HTTPException) as error:
        budget.admit("owner", "enrollment", "a" * 64, names)
    assert error.value.status_code == 503


@pytest.mark.parametrize("price", [0, -0.1, None, float("nan"), float("inf")])
def test_an_invalid_price_never_reaches_admission(monkeypatch, price):
    monkeypatch.setattr(budget.llm_pricing, "cost_usd", lambda *args, **kwargs: price)
    monkeypatch.setattr(budget, "rpc", lambda *args: pytest.fail("An invalid hold reached the DB"))
    with pytest.raises(HTTPException) as error:
        budget.admit("owner", "enrollment", "a" * 64, MODEL_NAMES)
    assert error.value.status_code == 503


def test_changed_run_bounds_fail_before_admission(monkeypatch):
    from pydantic_ai.usage import UsageLimits

    import agents.topic_checklist as agent_module

    monkeypatch.setattr(agent_module, "CHECKLIST_LIMITS", UsageLimits(
        request_limit=4, input_tokens_limit=50_000, count_tokens_before_request=True))
    monkeypatch.setattr(budget, "rpc", lambda *args: pytest.fail("A stale run bound reached the DB"))
    with pytest.raises(HTTPException) as error:
        budget.admit("owner", "enrollment", "a" * 64, MODEL_NAMES)
    assert error.value.status_code == 503


@pytest.mark.parametrize("status,code", [("busy", 409), ("denied", 429), ("blocked", 429),
    ("ownership", 404), ("usage_unavailable", 503), ("conflict", 503)])
def test_admission_failures_never_authorize_dispatch(monkeypatch, status, code):
    monkeypatch.setattr(budget, "rpc", lambda *args: {"status": status})
    with pytest.raises(HTTPException) as error:
        budget.admit("owner", "enrollment", "a" * 64, MODEL_NAMES)
    assert error.value.status_code == code


def test_coalesced_cache_hit_is_free(monkeypatch):
    monkeypatch.setattr(budget, "rpc", lambda *args: {"status": "cached"})
    assert budget.admit("owner", "enrollment", "a" * 64, MODEL_NAMES) is None


@pytest.mark.parametrize("key,value", [("user_id", "other"), ("enrollment_id", "other"),
    ("input_hash", "b" * 64), ("operation_id", str(uuid4())), ("state", "started")])
def test_admission_rejects_wrong_replay(monkeypatch, key, value):
    def rpc(name, params):
        return {"status": "replay", "reservation": admitted_row(params, **{key: value})}
    monkeypatch.setattr(budget, "rpc", rpc)
    with pytest.raises(HTTPException):
        budget.admit("owner", "enrollment", "a" * 64, MODEL_NAMES)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), "invalid", None])
def test_bad_cap_never_reaches_rpc(monkeypatch, value):
    monkeypatch.setattr(config, "STUDENT_DAILY_BUDGET_USD", value)
    monkeypatch.setattr(budget, "rpc", lambda *args: pytest.fail("Malformed policy reached DB"))
    with pytest.raises(HTTPException):
        budget.admit("owner", "enrollment", "a" * 64, MODEL_NAMES)


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


def google_model(name=GEMINI):
    # Construct a native model only; handler below supplies the response. No
    # provider/key/environment transport is used by these hermetic tests.
    return GoogleModel(name, provider=GoogleProvider(api_key="unit-test-placeholder"))


def claude_model(name="claude-haiku-5-5"):
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    return AnthropicModel(name, provider=AnthropicProvider(api_key="unit-test-placeholder"))


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


def test_dispatch_tracker_starts_a_reserved_claude_model(monkeypatch, reservation):
    """B1: the slot's Claude default dispatches under the reservation's hold."""
    starts = []
    monkeypatch.setattr(budget, "start", lambda r: starts.append(r) or replace(r, dispatch_at=NOW))
    tracker = ChecklistDispatches(reservation=reservation)

    async def handler(ctx):
        return response()

    asyncio.run(tracker.wrap_model_request(None, request_context=SimpleNamespace(model=claude_model()), handler=handler))
    assert len(starts) == 1 and tracker.dispatched == 1 and not tracker.nonbillable_test


@pytest.mark.parametrize("model", [lambda: claude_model("claude-sonnet-5-5"), lambda: google_model("gemini-2.5-pro")])
def test_an_unreserved_model_never_dispatches(monkeypatch, reservation, model):
    monkeypatch.setattr(budget, "start", lambda *args: pytest.fail("An unreserved model started a paid dispatch"))
    tracker = ChecklistDispatches(reservation=reservation)

    async def handler(ctx):
        pytest.fail("An unreserved model was called")

    with pytest.raises(ValueError, match="outside the reserved price policy"):
        asyncio.run(tracker.wrap_model_request(None, request_context=SimpleNamespace(model=model()), handler=handler))
    assert tracker.dispatched == 0


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


@pytest.mark.parametrize("cancel", [False, True])
def test_start_wait_does_not_block_run_deadline_or_dispatch_after_cancellation(monkeypatch, reservation, cancel):
    # What this proves: the first dispatch waits for `checklist_budget.start`
    # (the DB ACK) in a worker thread, so a slow ACK never blocks the event
    # loop. While it waits, the run's outer deadline [False] or the caller's
    # cancellation [True] still ends the run, with no dispatch counted and the
    # usage reconciled as never dispatched. When the ACK finally returns, the
    # model is still never called.
    #
    # The deadline is the production value on a clock the test controls, and
    # each wait is on an event, not a poll: the deadline passes only once the
    # ACK is provably blocked in its thread [False], and it can never pass
    # before the cancellation [True], however slow the machine is.
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    handlers = []
    def delayed_start(r):
        entered.set()
        try:
            assert release.wait(30)  # a hang guard, never reached when the test passes
            return replace(r, dispatch_at=NOW)
        finally:
            returned.set()
    monkeypatch.setattr(budget, "start", delayed_start)
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
            assert await asyncio.to_thread(entered.wait, 30)
            if cancel:
                task.cancel()
            else:
                asyncio.get_running_loop().advance(svc.GENERATION_TIMEOUT_SECONDS)
            result = await task
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
        assert await asyncio.to_thread(returned.wait, 30)
        assert handlers == []
    asyncio.run(run(), loop_factory=ManualClockLoop)


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
    assert svc.refresh_checklist("owner", "course", learning_loop=True) == "cached"


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
        svc.refresh_checklist("owner", "course", learning_loop=True)
    assert error.value.status_code == 503
    assert calls == [{"no_dispatch": True}]


def test_the_default_slot_hold_fits_the_daily_cap():
    """#866 review (b1-budget, defect 1): the SQL admit denies a hold above the
    daily cap even at zero spend. The default topic_checklist slot (and its
    llm_fallback model) must fit, or no loop-on student could ever refresh."""
    from decimal import Decimal

    import config
    from agents.topic_checklist import checklist_model_names

    # what admit prices: the primary only (the budgeted run is single-attempt,
    # so no fallback can serve it)
    hold = budget.price_hold(checklist_model_names(with_fallback=False))
    assert hold.usd <= Decimal(str(config.STUDENT_DAILY_BUDGET_USD))


def test_the_budgeted_run_is_single_attempt_and_its_hold_names_only_the_primary(monkeypatch):
    """#866 (b1-budget review): retries and the cross-provider fallback inside
    one dispatch were unheld. The budgeted run sends SINGLE_ATTEMPT_SETTING, so
    its hold prices the slot's own model alone."""
    import asyncio

    from agents import topic_checklist as tc
    from agents._resilience import SINGLE_ATTEMPT_SETTING
    from services import topic_checklist_service as svc

    monkeypatch.setenv("SAPLING_FLAG_LLM_FALLBACK", "on")
    assert len(tc.checklist_model_names()) == 2  # primary + its fallback, by default
    assert tc.checklist_model_names(with_fallback=False) == tc.checklist_model_names()[:1]

    seen = {}

    async def run(*a, **k):
        seen.update(k)
        raise RuntimeError("stop after the call")

    monkeypatch.setattr(svc.topic_checklist_agent, "run", run)
    generation = asyncio.run(svc._generate({"sources": []}, "u1", reservation=None))
    assert generation.error is not None
    assert seen["model_settings"] == {SINGLE_ATTEMPT_SETTING: True}


def test_a_hold_above_the_daily_cap_is_a_policy_error_before_any_rpc(monkeypatch, caplog):
    """A slot priced past the daily cap (e.g. SAPLING_MODEL_TOPIC_CHECKLIST on
    Sonnet) is a configuration error: an ERROR naming the cause and the policy
    503, never the misleading "no allowance left", and no database call."""
    import logging

    from fastapi import HTTPException

    calls = []
    monkeypatch.setattr(budget, "_call", lambda *a, **k: calls.append(a))
    with caplog.at_level(logging.ERROR, logger=budget.__name__):
        with pytest.raises(HTTPException) as exc:
            budget.admit("u1", "e1", "h", ("claude-sonnet-5-5", "gemini-2.5-flash"))
    assert exc.value.status_code == 503 and "price policy" in exc.value.detail
    assert calls == []
    assert any("exceeds the daily cap" in r.getMessage() for r in caplog.records)
