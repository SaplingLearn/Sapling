"""The topic checklist's bill for whichever reserved model served the run (B1).

Pure receipt preparation over measured pydantic-ai responses: no model, no
database. The SQL settlement side is tests/integration/test_checklist_budget_db.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.usage import RequestUsage, RunUsage

from services import checklist_budget, llm_pricing
from services.checklist_receipt import prepare_checklist_receipt
from services.usage_receipts import UsageReceiptUnavailable

NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
MODELS = ("anthropic:claude-haiku-5-5", "gemini:gemini-2.5-flash")


def reservation(models=MODELS):
    return checklist_budget.Reservation(uuid4(), "owner", "enrollment", "a" * 64, 3, NOW, models)


def claude_usage(prompt=1200, output=300, *, read=0, write=0, **details):
    uncached = prompt - read - write
    return RequestUsage(
        input_tokens=prompt, output_tokens=output, cache_read_tokens=read, cache_write_tokens=write,
        details={"input_tokens": uncached, "output_tokens": output,
                 "cache_creation_input_tokens": write, "cache_read_input_tokens": read, **details},
    )


def claude_response(usage=None, model="claude-haiku-5-5"):
    return ModelResponse(parts=[TextPart('{"topics": []}')], model_name=model,
                         provider_name="anthropic", usage=usage or claude_usage())


def run_usage(*responses):
    usage = RunUsage()
    for r in responses:
        usage.incr(r.usage)
        usage.requests += 1
    return usage


def prepare(r, responses, **kwargs):
    return prepare_checklist_receipt(
        reservation=r, responses=tuple(responses), dispatched_requests=kwargs.pop("dispatched", len(responses)),
        usage=kwargs.pop("usage", run_usage(*responses)), completed=kwargs.pop("completed", True), **kwargs,
    )


def test_a_claude_run_is_billed_under_the_reserved_claude_model_at_llm_pricing():
    r = reservation()
    first = claude_response(claude_usage(1200, 300))
    retry = claude_response(claude_usage(1500, 400, read=1000))
    receipt = prepare(r, [first, retry], request_id="req-1")
    row = receipt.to_row()
    assert (row["model"], row["provider"], row["feature"], row["task"]) == (
        "claude-haiku-5-5", "anthropic", "topic_checklist", "topic_checklist")
    assert (row["prompt_tokens"], row["completion_tokens"], row["total_tokens"]) == (2700, 700, 3400)
    assert row["cached_tokens"] == 1000 and row["thinking_tokens"] is None
    assert Decimal(str(row["cost_usd"])) == Decimal(str(llm_pricing.cost_usd(
        "claude-haiku-5-5", 2700, 700, cached_tokens=1000, cache_read_tokens=1000, requests=2)))
    assert row["user_id"] == "owner" and row["request_id"] == "req-1" and row["session_id"] is None
    assert receipt.receipt_id == row["id"] == str(
        uuid5(NAMESPACE_URL, f"sapling:checklist-receipt:{r.operation_id}"))
    assert row["created_at"] == NOW.isoformat()
    assert prepare(r, [first, retry], request_id="req-1").fingerprint == receipt.fingerprint


def test_a_dated_claude_snapshot_bills_as_the_reserved_model():
    row = prepare(reservation(), [claude_response(model="claude-haiku-5-5-20261001")]).to_row()
    assert row["model"] == "claude-haiku-5-5"


def test_a_gemini_fallback_run_is_billed_under_the_reserved_gemini_model():
    usage = RequestUsage(input_tokens=100, output_tokens=20)
    gemini = ModelResponse(parts=[TextPart("{}")], model_name="gemini-2.5-flash",
                           provider_name="google-gla", usage=usage)
    row = prepare(reservation(), [gemini]).to_row()
    assert (row["model"], row["provider"]) == ("gemini-2.5-flash", "gemini")
    assert Decimal(str(row["cost_usd"])) == Decimal(str(llm_pricing.cost_usd("gemini-2.5-flash", 100, 20)))


@pytest.mark.parametrize(
    "responses,models",
    [
        # a model the hold was not priced for
        ([claude_response(model="claude-sonnet-5-5")], MODELS),
        ([claude_response(model="claude-haiku-5-5-preview")], MODELS),
        ([claude_response()], ("gemini:gemini-2.5-flash",)),
        # one bill per model: a run served by both keeps its whole hold
        ([claude_response(), ModelResponse(parts=[TextPart("{}")], model_name="gemini-2.5-flash",
                                           provider_name="google-gla",
                                           usage=RequestUsage(input_tokens=10, output_tokens=5))], MODELS),
    ],
)
def test_a_run_outside_its_reservation_is_never_billed(responses, models):
    with pytest.raises(UsageReceiptUnavailable):
        prepare(reservation(models), responses)


@pytest.mark.parametrize(
    "usage",
    [
        claude_usage(0, 300),
        claude_usage(1200, 0),
        claude_usage(compaction_input_tokens=50),  # an unpriced billable pass
        RequestUsage(input_tokens=1200, output_tokens=300, details={}),  # no native counters
        RequestUsage(input_tokens=1200, output_tokens=300,  # natives disagree
                     details={"input_tokens": 1000, "output_tokens": 300}),
        RequestUsage(input_tokens=1200, output_tokens=300, input_audio_tokens=5,
                     details={"input_tokens": 1200, "output_tokens": 300}),
    ],
)
def test_incomplete_or_unpriced_claude_usage_keeps_the_hold(usage):
    with pytest.raises(UsageReceiptUnavailable):
        prepare(reservation(), [claude_response(usage)])


def test_an_unmeasured_attempt_keeps_the_hold():
    r = reservation()
    measured = claude_response()
    with pytest.raises(UsageReceiptUnavailable):
        prepare(r, [measured], dispatched=2)
    with pytest.raises(UsageReceiptUnavailable):
        prepare(r, [], usage=RunUsage())
    with pytest.raises(UsageReceiptUnavailable):
        prepare(r, [measured], completed=False)
    hidden = run_usage(measured)
    hidden.input_tokens += 1
    with pytest.raises(UsageReceiptUnavailable):
        prepare(r, [measured], usage=hidden)
