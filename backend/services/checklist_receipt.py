"""The topic checklist's bill, for whichever reserved model served the run.

A checklist run is held for every model that can serve it (the slot's model
and its llm_fallback model, services/checklist_budget.py). This module reads
the served model off the measured responses, checks the reservation was
priced for it, and prepares the one aggregate bill: a Gemini run through
services/usage_receipts.py, a Claude run here, to the same standard. Every
dispatched request has a complete measured response from that one model,
every billable counter is accounted for, the run's totals equal the sum of the
responses, and the price is services/llm_pricing's. Anything else raises
UsageReceiptUnavailable, so the caller keeps the whole hold (never a refund on
a guess). Pure: no model, database, queue or clock.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic_ai.messages import ModelResponse
from pydantic_ai.usage import RequestUsage, RunUsage

from services import checklist_budget
from services.events_service import build_llm_usage_row
from services.usage_receipts import (
    INT4_MAX,
    PreparedUsageReceipt,
    UsageReceiptUnavailable,
    prepare_checklist_usage_receipt,
)

_GOOGLE_PROVIDERS = frozenset({"google", "google-gla"})
_CLAUDE_PROVIDER = "anthropic"
#: Anthropic's own usage counters, which pydantic-ai keeps in `details`.
_CLAUDE_DETAILS = frozenset(
    {"input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"}
)
_MAX_COUNT = INT4_MAX  # llm_usage counters are INTEGER
#: A Claude snapshot suffix is a YYYYMMDD date (`claude-haiku-5-5-20261001`).
_SNAPSHOT_DATE_DIGITS = 8


def _count(value: object) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_COUNT:
        raise UsageReceiptUnavailable("Usage counters must be measured nonnegative integers")
    return value


def _reserved_model(models: tuple[str, ...], provider: object, name: object) -> str:
    """The reserved model a response's (provider, model) is, or raise. A Claude
    response may name a dated snapshot of the reserved model
    (`claude-haiku-5-5-20261001`, an 8-digit date); the bill names the
    reserved model."""
    if not isinstance(name, str) or not name or not isinstance(provider, str):
        raise UsageReceiptUnavailable("Invalid served model")
    if provider in _GOOGLE_PROVIDERS:
        bare = name.removeprefix("google-gla:")
        if checklist_budget.billing_label(bare) in models and bare.startswith("gemini-"):
            return bare
    elif provider == _CLAUDE_PROVIDER:
        for label in models:
            label_provider, _, reserved = label.partition(":")
            snapshot = name.removeprefix(f"{reserved}-")
            if label_provider == _CLAUDE_PROVIDER and (
                name == reserved or (snapshot != name and len(snapshot) == _SNAPSHOT_DATE_DIGITS and snapshot.isdigit())
            ):
                return reserved
    raise UsageReceiptUnavailable("The served model is outside the reserved price policy")


def _claude_counts(usage: RequestUsage) -> tuple[int, int, int, int]:
    """(input, output, cache reads, cache writes) of one Claude response.

    pydantic-ai's `input_tokens` already includes the cache reads and writes
    (llm_pricing prices it that way); Anthropic's own counters in `details`
    must agree with the extracted totals, and any other billable counter
    (audio, a compaction pass) is refused rather than left unpriced."""
    prompt, completion = _count(usage.input_tokens), _count(usage.output_tokens)
    if prompt == 0 or completion == 0:
        raise UsageReceiptUnavailable("Per-response text usage is incomplete")
    read, write = _count(usage.cache_read_tokens), _count(usage.cache_write_tokens)
    if any(
        _count(value) != 0
        for value in (usage.input_audio_tokens, usage.cache_audio_read_tokens, usage.output_audio_tokens)
    ):
        raise UsageReceiptUnavailable("Unsupported billable usage component")
    details = usage.details
    if not isinstance(details, dict) or not {"input_tokens", "output_tokens"} <= details.keys():
        raise UsageReceiptUnavailable("Usage details are unavailable")
    if any(key not in _CLAUDE_DETAILS and _count(value) != 0 for key, value in details.items()):
        raise UsageReceiptUnavailable("Unsupported billable usage detail")
    created = _count(details.get("cache_creation_input_tokens", 0))
    cached = _count(details.get("cache_read_input_tokens", 0))
    if (
        _count(details["input_tokens"]) + created + cached != prompt
        or _count(details["output_tokens"]) != completion
        or (cached, created) != (read, write)
    ):
        raise UsageReceiptUnavailable("Usage details disagree with measured totals")
    return prompt, completion, read, write


def _claude_receipt(
    *,
    model: str,
    reservation: checklist_budget.Reservation,
    responses: tuple[ModelResponse, ...],
    dispatched_requests: int,
    usage: RunUsage,
    request_id: str | None,
) -> PreparedUsageReceipt:
    requests = _count(usage.requests)
    if requests == 0 or len(responses) != requests or _count(dispatched_requests) != requests:
        raise UsageReceiptUnavailable("Every dispatched request needs a measured response")
    if _count(usage.tool_calls) != 0:
        raise UsageReceiptUnavailable("Checklist receipts cannot include function tools")
    measured = [_claude_counts(r.usage) for r in responses]
    totals = tuple(sum(values) for values in zip(*measured, strict=True))
    prompt, completion = _count(usage.input_tokens), _count(usage.output_tokens)
    run = (prompt, completion, _count(usage.cache_read_tokens), _count(usage.cache_write_tokens))
    if totals != run or _count(usage.total_tokens) != prompt + completion:
        raise UsageReceiptUnavailable("Aggregate usage disagrees with measured responses")
    if any(
        _count(value) != 0
        for value in (usage.input_audio_tokens, usage.cache_audio_read_tokens, usage.output_audio_tokens)
    ):
        raise UsageReceiptUnavailable("Unsupported billable usage component")
    try:
        row = build_llm_usage_row(
            feature="topic_checklist",
            task="topic_checklist",
            model=model,
            provider=_CLAUDE_PROVIDER,
            usage=usage,
            user_id=reservation.user_id,
            request_id=request_id,
            cached_tokens=run[2],
            # Claude bills its thinking inside output_tokens and reports no
            # separate count: unknown, never a measured zero.
            thinking_tokens=None,
            requests=requests,
        )
    except (ArithmeticError, TypeError, ValueError):
        raise UsageReceiptUnavailable("Usage pricing is unavailable") from None
    return _sealed(row, reservation)


def _sealed(row: dict, reservation: checklist_budget.Reservation) -> PreparedUsageReceipt:
    """The receipt identity and fingerprint, as services/usage_receipts.py seals a Gemini bill."""
    cost = row.get("cost_usd")
    if cost is None or not Decimal(str(cost)).is_finite() or Decimal(str(cost)) <= 0:
        raise UsageReceiptUnavailable("Approved model usage has no valid positive price")
    dispatched_at = reservation.dispatch_at
    if not isinstance(dispatched_at, datetime) or dispatched_at.utcoffset() is None:
        raise UsageReceiptUnavailable("An aware dispatch timestamp is required")
    receipt_id = str(uuid5(NAMESPACE_URL, f"sapling:checklist-receipt:{reservation.operation_id}"))
    row.update(id=receipt_id, created_at=dispatched_at.astimezone(timezone.utc).isoformat())
    row_json = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return PreparedUsageReceipt(receipt_id, hashlib.sha256(row_json.encode()).hexdigest(), row_json)


def prepare_checklist_receipt(
    *,
    reservation: checklist_budget.Reservation,
    responses: tuple[ModelResponse, ...],
    dispatched_requests: int,
    usage: RunUsage,
    completed: bool,
    request_id: str | None = None,
) -> PreparedUsageReceipt:
    """One aggregate bill for a complete run, served by one reserved model.

    The caller collects every response and counts dispatches independently,
    including those that returned none; an unknown or in-flight attempt
    cannot become a final receipt."""
    if completed is not True or not isinstance(usage, RunUsage):
        raise UsageReceiptUnavailable("Only complete measured runs can be finalized")
    if not isinstance(reservation.operation_id, UUID) or not reservation.user_id:
        raise UsageReceiptUnavailable("A stable operation and owner are required")
    if request_id is not None and (not isinstance(request_id, str) or not request_id.strip()):
        raise UsageReceiptUnavailable("Invalid request identity")
    if (
        not isinstance(responses, tuple)
        or not responses
        or any(not isinstance(r, ModelResponse) or r.state != "complete" for r in responses)
    ):
        raise UsageReceiptUnavailable("Every dispatched request needs a measured response")
    served = {(r.provider_name, r.model_name) for r in responses}
    if len(served) != 1:
        raise UsageReceiptUnavailable("An aggregate receipt requires complete same-model responses")
    [(provider, name)] = served
    model = _reserved_model(reservation.models, provider, name)
    if provider == _CLAUDE_PROVIDER:
        return _claude_receipt(
            model=model, reservation=reservation, responses=responses,
            dispatched_requests=dispatched_requests, usage=usage, request_id=request_id,
        )
    if reservation.dispatch_at is None:
        raise UsageReceiptUnavailable("An aware dispatch timestamp is required")
    return prepare_checklist_usage_receipt(
        operation_id=reservation.operation_id,
        user_id=reservation.user_id,
        approved_model=model,
        responses=responses,
        dispatched_requests=dispatched_requests,
        usage=usage,
        completed=completed,
        dispatched_at=reservation.dispatch_at,
        request_id=request_id,
    )
