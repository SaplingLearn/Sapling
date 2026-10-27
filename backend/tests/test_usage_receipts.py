"""Strict preparation cannot finalize incomplete bills or write a receipt."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import hashlib
from uuid import UUID

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.usage import RequestUsage, RunUsage

from services import events_service, llm_pricing
from services.usage_receipts import UsageReceiptUnavailable, prepare_checklist_usage_receipt

MODEL = "gemini-2.5-flash"
OP = UUID("8c93ea7d-77cb-43d0-aa4b-0c52c490a8a3")
DISPATCHED = datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc)


def response(*, model=MODEL, provider="google-gla", state="complete", usage=None):
    return ModelResponse(
        parts=[TextPart("A structured checklist response.")],
        model_name=model,
        provider_name=provider,
        state=state,
        usage=usage if usage is not None else RequestUsage(input_tokens=1000, output_tokens=500),
    )


def aggregate(responses):
    usage = RunUsage(requests=len(responses))
    for item in responses:
        usage.incr(item.usage)
    return usage


def prepare(**overrides):
    args = dict(
        operation_id=OP, user_id="student", approved_model=MODEL,
        responses=(response(),), dispatched_requests=1,
        usage=RunUsage(requests=1, input_tokens=1000, output_tokens=500),
        completed=True, dispatched_at=DISPATCHED, request_id="request",
    )
    args.update(overrides)
    return prepare_checklist_usage_receipt(**args)


def prepare_responses(responses, **overrides):
    args = dict(responses=responses, usage=aggregate(responses), dispatched_requests=len(responses))
    args.update(overrides)
    return prepare(**args)


def test_canonical_queue_and_receipt_share_pricing_without_duplicate_write(monkeypatch):
    queued = []
    monkeypatch.setattr(events_service, "_logging_enabled", lambda: True)
    monkeypatch.setattr(events_service, "_enqueue", lambda table, row: queued.append((table, row)))
    responses = (response(usage=RequestUsage(
        input_tokens=1000, output_tokens=500, cache_read_tokens=200,
        details={"thoughts_tokens": 100, "cached_content_tokens": 200},
    )),)
    usage = aggregate(responses)
    receipt = prepare_responses(responses)
    assert queued == []
    events_service.log_llm_usage(
        feature="topic_checklist", task="topic_checklist", model=MODEL, usage=usage,
        user_id="student", request_id="request", cached_tokens=200, thinking_tokens=100,
    )
    row = receipt.to_row()
    assert len(queued) == 1 and queued[0][0] == "llm_usage"
    assert {k: v for k, v in row.items() if k not in {"id", "created_at"}} == queued[0][1]
    assert row["cost_usd"] == llm_pricing.cost_usd(MODEL, 1000, 500, cached_tokens=200)


def test_preparation_does_not_consult_analytics_gate_context_queue_or_database(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Receipt preparation must not consult analytics state or persist anything")

    monkeypatch.setattr(events_service, "_logging_enabled", forbidden)
    monkeypatch.setattr(events_service, "current_request_id", forbidden)
    monkeypatch.setattr(events_service, "_enqueue", forbidden)
    monkeypatch.setattr(events_service, "table", forbidden)
    assert prepare().to_row()["request_id"] == "request"
    assert prepare(request_id=None).to_row()["request_id"] is None


def test_queue_keeps_context_fallback_while_builder_is_explicit(monkeypatch):
    queued = []
    monkeypatch.setattr(events_service, "_logging_enabled", lambda: True)
    monkeypatch.setattr(events_service, "current_request_id", lambda: "context")
    monkeypatch.setattr(events_service, "_enqueue", lambda table, row: queued.append(row))
    usage = RunUsage(requests=1, input_tokens=1)
    row = events_service.build_llm_usage_row(feature="x", task=None, model=MODEL, usage=usage)
    assert row["request_id"] is None
    events_service.log_llm_usage(feature="x", task=None, model=MODEL, usage=usage)
    events_service.log_llm_usage(feature="x", task=None, model=MODEL, usage=usage, request_id="")
    assert [item["request_id"] for item in queued] == ["context", ""]


def test_stable_identity_and_payload_survive_caller_mutation():
    responses = (response(),)
    usage = aggregate(responses)
    first = prepare(responses=responses, usage=usage)
    second = prepare(responses=responses, usage=usage)
    assert first == second
    assert UUID(first.receipt_id).version == 5
    assert first.fingerprint == hashlib.sha256(first.row_json.encode()).hexdigest()
    copied = first.to_row()
    copied["cost_usd"] = 0
    responses[0].usage.input_tokens = 9999
    usage.input_tokens = 9999
    assert first.to_row()["prompt_tokens"] == 1000
    assert first.to_row()["cost_usd"] > 0
    with pytest.raises(FrozenInstanceError):
        first.fingerprint = "changed"
    changed = prepare_responses((response(usage=RequestUsage(input_tokens=2000, output_tokens=500)),))
    assert changed.receipt_id == first.receipt_id and changed.fingerprint != first.fingerprint
    assert prepare(user_id="another-student").receipt_id == first.receipt_id
    assert prepare(user_id="another-student").fingerprint != first.fingerprint


def test_equivalent_dispatch_instants_have_identical_receipts_across_month_boundary():
    local = datetime(2026, 11, 1, 0, 59, tzinfo=timezone(timedelta(hours=1)))
    assert prepare(dispatched_at=local) == prepare(dispatched_at=DISPATCHED)
    assert prepare(dispatched_at=local).to_row()["created_at"] == "2026-10-31T23:59:00+00:00"


@pytest.mark.parametrize("changes", [
    {"completed": False}, {"completed": 1}, {"usage": None},
    {"usage": RunUsage(requests=0, input_tokens=10, output_tokens=5)},
    {"usage": RunUsage(requests=1)},
    {"usage": RunUsage(requests=1, input_tokens=1000, output_tokens=500, tool_calls=1)},
    {"responses": ()}, {"responses": (response(), response())},
    {"responses": [response()]}, {"responses": ({"model_name": MODEL},)},
    {"user_id": " "}, {"operation_id": str(OP)},
    {"dispatched_at": datetime(2026, 10, 31)}, {"request_id": ""},
    {"approved_model": "gemini-unpriced-2099", "responses": (response(model="gemini-unpriced-2099"),)},
])
def test_invalid_incomplete_or_unpriced_runs_cannot_prepare_final_bills(changes):
    with pytest.raises(UsageReceiptUnavailable):
        prepare(**changes)


@pytest.mark.parametrize("dispatched", [0, 2, -1, True, "1", 1.0])
def test_every_dispatch_must_have_a_completed_measured_response(dispatched):
    with pytest.raises(UsageReceiptUnavailable):
        prepare(dispatched_requests=dispatched)


def test_started_request_without_response_cannot_hide_behind_known_usage():
    responses = (response(),)
    with pytest.raises(UsageReceiptUnavailable, match="Every dispatched request"):
        prepare_responses(responses, dispatched_requests=2)
    usage = aggregate(responses)
    usage.requests = 2
    with pytest.raises(UsageReceiptUnavailable, match="Every dispatched request"):
        prepare(responses=responses, usage=usage, dispatched_requests=2)


@pytest.mark.parametrize("state", ["incomplete", "interrupted"])
def test_partial_response_state_cannot_be_certified_by_completed_flag(state):
    with pytest.raises(UsageReceiptUnavailable, match="complete same-model responses"):
        prepare_responses((response(state=state),))


def test_zero_usage_response_is_not_hidden_by_a_measured_retry():
    responses = (response(usage=RequestUsage()), response())
    usage = aggregate(responses)
    assert usage.requests == 2 and usage.total_tokens > 0
    with pytest.raises(UsageReceiptUnavailable, match="Per-response text usage is incomplete"):
        prepare_responses(responses)


@pytest.mark.parametrize("scope", ["response", "aggregate"])
@pytest.mark.parametrize("field,value", [
    ("input_tokens", -1), ("input_tokens", 0.5), ("input_tokens", True),
    ("output_tokens", float("nan")), ("output_tokens", 2_147_483_648),
    ("cache_read_tokens", 1001),
])
def test_malformed_native_usage_is_not_coerced(scope, field, value):
    responses = (response(),)
    usage = aggregate(responses)
    target = responses[0].usage if scope == "response" else usage
    setattr(target, field, value)
    with pytest.raises(UsageReceiptUnavailable):
        prepare(responses=responses, usage=usage)


@pytest.mark.parametrize("requests", [True, "1", -1, 1.0])
def test_malformed_sdk_request_counts_are_rejected(requests):
    usage = RunUsage(requests=1, input_tokens=1000, output_tokens=500)
    usage.requests = requests
    with pytest.raises(UsageReceiptUnavailable):
        prepare(usage=usage)


@pytest.mark.parametrize("scope", ["response", "aggregate"])
@pytest.mark.parametrize("field", [
    "cache_write_tokens", "input_audio_tokens", "cache_audio_read_tokens", "output_audio_tokens",
])
def test_unpriced_native_billable_components_are_rejected(scope, field):
    responses = (response(),)
    usage = aggregate(responses)
    setattr(responses[0].usage if scope == "response" else usage, field, 1)
    with pytest.raises(UsageReceiptUnavailable, match="Unsupported billable usage component"):
        prepare(responses=responses, usage=usage)


@pytest.mark.parametrize("scope", ["response", "aggregate"])
@pytest.mark.parametrize("key", ["audio_prompt_tokens", "image_prompt_tokens", "tool_use_prompt_tokens", "new_billable_component"])
def test_unknown_nonzero_usage_details_are_rejected(scope, key):
    responses = (response(),)
    usage = aggregate(responses)
    (responses[0].usage if scope == "response" else usage).details[key] = 1
    with pytest.raises(UsageReceiptUnavailable, match="Unsupported billable usage detail"):
        prepare(responses=responses, usage=usage)


def test_unknown_zero_details_do_not_invent_a_billed_component():
    responses = (response(usage=RequestUsage(
        input_tokens=1000, output_tokens=500, details={"new_billable_component": 0},
    )),)
    assert prepare_responses(responses).to_row()["total_tokens"] == 1500


@pytest.mark.parametrize("details", [
    {"thoughts_tokens": 501}, {"thoughts_tokens": "100"},
    {"cached_content_tokens": -1}, {"cached_content_tokens": 1001},
    {"new_billable_component": "0"},
])
def test_invalid_detailed_usage_cannot_be_priced_as_complete(details):
    with pytest.raises(UsageReceiptUnavailable):
        prepare_responses((response(usage=RequestUsage(input_tokens=1000, output_tokens=500, details=details)),))


def test_conflicting_cached_counts_cannot_choose_the_larger_discount():
    responses = (response(usage=RequestUsage(
        input_tokens=1000, output_tokens=500, cache_read_tokens=100,
        details={"cached_content_tokens": 900},
    )),)
    with pytest.raises(UsageReceiptUnavailable, match="Conflicting cached usage counts"):
        prepare_responses(responses)


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "cache_read_tokens"])
def test_aggregate_native_totals_must_match_all_response_usage(field):
    responses = (response(), response())
    usage = aggregate(responses)
    setattr(usage, field, getattr(usage, field) + 1)
    with pytest.raises(UsageReceiptUnavailable, match="Aggregate usage disagrees"):
        prepare_responses(responses, usage=usage)


@pytest.mark.parametrize("key", [
    "thoughts_tokens", "cached_content_tokens", "text_prompt_tokens", "text_candidates_tokens", "text_cache_tokens",
])
def test_aggregate_detail_snapshots_must_match_present_response_details(key):
    responses = (response(usage=RequestUsage(
        input_tokens=1000, output_tokens=500, cache_read_tokens=200,
        details={"thoughts_tokens": 100, "cached_content_tokens": 200,
                 "text_prompt_tokens": 1000, "text_candidates_tokens": 400, "text_cache_tokens": 200},
    )),)
    usage = aggregate(responses)
    usage.details[key] += 1
    with pytest.raises(UsageReceiptUnavailable, match="Aggregate usage"):
        prepare_responses(responses, usage=usage)


@pytest.mark.parametrize("key,value", [
    ("text_prompt_tokens", 999), ("text_candidates_tokens", 500), ("text_cache_tokens", 199),
])
def test_redundant_text_modality_counts_must_match_measured_counts(key, value):
    details = {"thoughts_tokens": 100, "cached_content_tokens": 200}
    details[key] = value
    responses = (response(usage=RequestUsage(
        input_tokens=1000, output_tokens=500, cache_read_tokens=200, details=details,
    )),)
    with pytest.raises(UsageReceiptUnavailable, match="Text modality details disagree"):
        prepare_responses(responses)


def test_optional_text_and_cached_details_need_not_appear_on_every_retry():
    responses = (
        response(usage=RequestUsage(
            input_tokens=1000, output_tokens=500, cache_read_tokens=200,
            details={"thoughts_tokens": 100, "cached_content_tokens": 200,
                     "text_prompt_tokens": 1000, "text_candidates_tokens": 400, "text_cache_tokens": 200},
        )),
        response(usage=RequestUsage(input_tokens=2000, output_tokens=300, cache_read_tokens=300)),
    )
    receipt = prepare_responses(responses)
    row = receipt.to_row()
    assert (row["prompt_tokens"], row["completion_tokens"], row["cached_tokens"], row["thinking_tokens"]) == (3000, 800, 500, 100)
    assert row["cost_usd"] == llm_pricing.cost_usd(MODEL, 3000, 800, cached_tokens=500)


def test_actual_sdk_text_thinking_and_cached_metadata_can_prepare_a_receipt():
    from google.genai import types
    from pydantic_ai.models.google import _metadata_as_usage

    def text_tokens(count):
        return [types.ModalityTokenCount(modality=types.MediaModality.TEXT, token_count=count)]

    native = types.GenerateContentResponse(
        model_version=MODEL,
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1000, candidates_token_count=400, thoughts_token_count=100,
            total_token_count=1500, cached_content_token_count=200,
            prompt_tokens_details=text_tokens(1000), candidates_tokens_details=text_tokens(400),
            cache_tokens_details=text_tokens(200),
        ),
    )
    usage = _metadata_as_usage(native, provider="google-gla", provider_url="https://generativelanguage.googleapis.com")
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens) == (1000, 500, 200)
    assert usage.details["text_candidates_tokens"] == 400
    row = prepare_responses((response(usage=usage),)).to_row()
    assert (row["thinking_tokens"], row["cached_tokens"], row["total_tokens"]) == (100, 200, 1500)


@pytest.mark.parametrize("approved,served", [
    (MODEL, MODEL), (f"google-gla:{MODEL}", MODEL), (MODEL, f"google-gla:{MODEL}"),
])
@pytest.mark.parametrize("provider", ["google", "google-gla"])
def test_approved_google_aliases_preserve_one_canonical_model(approved, served, provider):
    row = prepare_responses((response(model=served, provider=provider),), approved_model=approved).to_row()
    assert row["model"] == MODEL and row["provider"] == "gemini"


@pytest.mark.parametrize("model", [
    f"google-vertex:{MODEL}", f"typesafe:{MODEL}", f"openai:{MODEL}",
    "typesafe:jev-latest", "jev-latest", f"google-gla:google-gla:{MODEL}",
])
@pytest.mark.parametrize("location", ["approved", "response"])
def test_arbitrary_provider_prefixes_cannot_be_priced_as_gemini(model, location):
    changes = {"approved_model": model} if location == "approved" else {"responses": (response(model=model),)}
    with pytest.raises(UsageReceiptUnavailable):
        prepare(**changes)


@pytest.mark.parametrize("provider", [None, "google-vertex", "typesafe", "openai"])
def test_actual_provider_attribution_cannot_be_hidden_by_a_bare_gemini_name(provider):
    responses = (response(), response(provider=provider))
    with pytest.raises(UsageReceiptUnavailable, match="complete same-model responses"):
        prepare_responses(responses)


def test_mixed_models_cannot_be_priced_at_the_last_response_rate():
    responses = (response(), response(model="gemini-2.5-pro"))
    with pytest.raises(UsageReceiptUnavailable, match="complete same-model responses"):
        prepare_responses(responses)


@pytest.mark.parametrize("cost", [None, 0, -1, float("nan"), float("inf")])
def test_invalid_price_does_not_look_like_a_complete_bill(monkeypatch, cost):
    monkeypatch.setattr(llm_pricing, "cost_usd", lambda *args, **kwargs: cost)
    with pytest.raises(UsageReceiptUnavailable, match="valid positive price"):
        prepare()


def test_pricing_failure_returns_unavailable_without_leaking_failure_text(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private SDK failure text")

    monkeypatch.setattr(llm_pricing, "cost_usd", fail)
    with pytest.raises(UsageReceiptUnavailable, match="^Usage pricing is unavailable$"):
        prepare()


def test_anthropic_native_usage_receipt_is_priced_without_cache_or_duplicate_queue():
    responses = (response(model="claude-haiku-5-5-20261001", provider="anthropic", usage=RequestUsage(
        input_tokens=1000, output_tokens=500, details={"input_tokens": 1000, "output_tokens": 500},
    )),)
    row = prepare_responses(responses, approved_model="claude-haiku-5-5").to_row()
    assert row["provider"] == "anthropic"
    assert row["model"] == "claude-haiku-5-5"
    assert row["cost_usd"] == .00035
    assert row["cached_tokens"] == 0
    with pytest.raises(UsageReceiptUnavailable):
        prepare_responses((response(model="claude-haiku-5-5", provider="anthropic", usage=RequestUsage(
            input_tokens=1000, output_tokens=500, cache_read_tokens=100,
        )),), approved_model="claude-haiku-5-5")
