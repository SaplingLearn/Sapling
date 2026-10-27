"""Strict preparation for a completed checklist bill; no persistence or refund.

Analytics remain best-effort. A future protected settlement must persist this
receipt and its reservation transition atomically, without also queueing it.
Preparation alone is not admission, acknowledgment or a spending guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import re
import json
from uuid import UUID, NAMESPACE_URL, uuid5

from pydantic_ai.messages import ModelResponse
from pydantic_ai.usage import RunUsage

from services.events_service import build_llm_usage_row


class UsageReceiptUnavailable(ValueError):
    """Incomplete or inconsistent usage must retain financial exposure."""


@dataclass(frozen=True)
class PreparedUsageReceipt:
    receipt_id: str
    fingerprint: str
    row_json: str

    def to_row(self) -> dict:
        """Return an independent copy; mutation cannot change receipt identity."""
        return json.loads(self.row_json)


def _count(value: object) -> int:
    # SQL llm_usage counters are INTEGER; bool/string/float coercion would hide
    # malformed native usage that the permissive analytics seam can tolerate.
    if type(value) is not int or not 0 <= value <= 2_147_483_647:
        raise UsageReceiptUnavailable("Usage counters must be measured nonnegative integers")
    return value


def _label(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise UsageReceiptUnavailable(f"Invalid {name}")
    return value


def _model(value: object) -> str:
    name = _label(value, "model")
    if ":" in name:
        provider, name = name.split(":", 1)
        if provider not in {"google-gla", "anthropic"} or (provider == "anthropic") != name.startswith("claude-"):
            raise UsageReceiptUnavailable("Unsupported receipt provider")
    if re.fullmatch(r"claude-haiku-5-5(?:-[0-9]{8})?", name):
        return "claude-haiku-5-5"
    if not name.startswith("gemini-") or ":" in name:
        raise UsageReceiptUnavailable("Unsupported receipt model")
    return name


def _text_counts(usage, *, aggregate: bool = False, anthropic: bool = False) -> tuple[int, int, int, int]:
    prompt, completion = _count(usage.input_tokens), _count(usage.output_tokens)
    # Every complete structured checklist response has nonempty output and
    # nonempty instructions. Zero counters cannot certify an extracted bill.
    if prompt == 0 or completion == 0:
        raise UsageReceiptUnavailable("Per-response text usage is incomplete")
    for key, value in vars(usage).items():
        if key not in {
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "details",
            "requests",
            "tool_calls",
        }:
            if _count(value) != 0:
                raise UsageReceiptUnavailable("Unsupported billable usage component")
    details = usage.details
    if not isinstance(details, dict):
        raise UsageReceiptUnavailable("Usage details are unavailable")
    if anthropic:
        allowed = {"input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"}
        if usage.cache_read_tokens or any(_count(value) != 0 for key, value in details.items() if key not in allowed):
            raise UsageReceiptUnavailable("Unsupported Anthropic usage component")
        if details.get("cache_creation_input_tokens", 0) or details.get("cache_read_input_tokens", 0):
            raise UsageReceiptUnavailable("Assessment guides do not authorize prompt caching")
        for key, count in (("input_tokens", prompt), ("output_tokens", completion)):
            if key in details and _count(details[key]) != count:
                raise UsageReceiptUnavailable("Anthropic counters disagree")
        return prompt, completion, 0, 0
    text_details = {"text_prompt_tokens", "text_candidates_tokens", "text_cache_tokens"}
    for key, value in details.items():
        if (
            key not in {"thoughts_tokens", "cached_content_tokens"} | text_details
            and _count(value) != 0
        ):
            raise UsageReceiptUnavailable("Unsupported billable usage detail")
    cached = _count(usage.cache_read_tokens)
    if (
        not aggregate
        and "cached_content_tokens" in details
        and _count(details["cached_content_tokens"]) != cached
    ):
        raise UsageReceiptUnavailable("Conflicting cached usage counts")
    thinking = _count(details.get("thoughts_tokens", 0))
    if cached > prompt or thinking > completion:
        raise UsageReceiptUnavailable("Usage detail counters exceed measured totals")
    expected_text = {
        "text_prompt_tokens": prompt,
        "text_candidates_tokens": completion - thinking,
        "text_cache_tokens": cached,
    }
    if not aggregate and any(
        key in details and _count(details[key]) != expected
        for key, expected in expected_text.items()
    ):
        raise UsageReceiptUnavailable("Text modality details disagree with measured totals")
    return prompt, completion, cached, thinking


def prepare_checklist_usage_receipt(
    *,
    operation_id: UUID,
    user_id: str,
    approved_model: str,
    responses: tuple[ModelResponse, ...],
    dispatched_requests: int,
    usage: RunUsage,
    completed: bool,
    dispatched_at: datetime,
    request_id: str | None = None,
) -> PreparedUsageReceipt:
    """Prepare one aggregate receipt for complete, same-model attempts only.

    The caller must collect every response and independently count dispatches,
    including those without a response. Unknown/in-flight attempts cannot
    become a final receipt. Dispatch time is
    explicit so a later transaction can preserve the reserved UTC period.
    No model, DB, queue, clock, logging gate or reservation write occurs here.
    """
    if completed is not True or not isinstance(usage, RunUsage):
        raise UsageReceiptUnavailable("Only complete measured runs can be finalized")
    if not isinstance(operation_id, UUID):
        raise UsageReceiptUnavailable("A stable operation UUID is required")
    user_id = _label(user_id, "owner")
    canonical = _model(approved_model)
    if request_id is not None:
        _label(request_id, "request identity")
    if not isinstance(dispatched_at, datetime) or dispatched_at.utcoffset() is None:
        raise UsageReceiptUnavailable("An aware dispatch timestamp is required")
    requests = _count(usage.requests)
    prompt = _count(usage.input_tokens)
    completion = _count(usage.output_tokens)
    total = _count(usage.total_tokens)
    if requests == 0 or total == 0 or total != prompt + completion:
        raise UsageReceiptUnavailable("A bill requires complete nonzero measured usage")
    if _count(usage.tool_calls) != 0:
        raise UsageReceiptUnavailable("Checklist receipts cannot include function tools")
    if (
        not isinstance(responses, tuple)
        or len(responses) != requests
        or _count(dispatched_requests) != requests
    ):
        raise UsageReceiptUnavailable("Every dispatched request needs a measured response")
    anthropic = canonical == "claude-haiku-5-5"
    providers = {"anthropic"} if anthropic else {"google", "google-gla"}
    if any(
        not isinstance(r, ModelResponse)
        or r.state != "complete"
        or r.provider_name not in providers
        or _model(r.model_name) != canonical
        for r in responses
    ):
        raise UsageReceiptUnavailable("An aggregate receipt requires complete same-model responses")
    measured = [_text_counts(r.usage, anthropic=anthropic) for r in responses]
    prompt, completion, cached, thinking = _text_counts(usage, aggregate=True, anthropic=anthropic)
    if tuple(sum(values) for values in zip(*measured, strict=True)) != (
        prompt,
        completion,
        cached,
        thinking,
    ):
        raise UsageReceiptUnavailable("Aggregate usage disagrees with measured responses")
    for key in {
        "cached_content_tokens",
        "thoughts_tokens",
        "text_prompt_tokens",
        "text_candidates_tokens",
        "text_cache_tokens",
    }:
        if _count(usage.details.get(key, 0)) != sum(
            _count(r.usage.details.get(key, 0)) for r in responses
        ):
            raise UsageReceiptUnavailable(
                "Aggregate usage details disagree with measured responses"
            )
    try:
        row = build_llm_usage_row(
            feature="topic_checklist",
            task="topic_checklist",
            model=canonical,
            provider="anthropic" if anthropic else "gemini",
            usage=usage,
            user_id=user_id,
            request_id=request_id,
            cached_tokens=cached,
            thinking_tokens=thinking,
        )
    except Exception:
        raise UsageReceiptUnavailable("Usage pricing is unavailable") from None
    cost = row["cost_usd"]
    if cost is None or not Decimal(str(cost)).is_finite() or Decimal(str(cost)) <= 0:
        raise UsageReceiptUnavailable("Approved model usage has no valid positive price")
    receipt_id = str(uuid5(NAMESPACE_URL, f"sapling:checklist-receipt:{operation_id}"))
    row.update(id=receipt_id, created_at=dispatched_at.astimezone(timezone.utc).isoformat())
    row_json = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return PreparedUsageReceipt(receipt_id, hashlib.sha256(row_json.encode()).hexdigest(), row_json)
