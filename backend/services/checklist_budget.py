"""Durable, checklist-participant capacity holds through backend-only RPCs.

This is not a global spend cap: other features do not take the mutex. The hold
is the worst-case price, from services/llm_pricing, of one policy run
(`CHECKLIST_LIMITS`: 50,000 counted input tokens, three 8,192-token outputs) on
the one model that can serve it: the `topic_checklist` slot's model. The
budgeted run is single-attempt (`agents._resilience.SINGLE_ATTEMPT_SETTING`:
no retry and no llm_fallback hidden inside a dispatch, #866 b1-budget review),
so `checklist_model_names(with_fallback=False)` is what the hold prices. The
reservation records that model, and settlement accepts a bill from it only. The fixed envelope uses the native counter's estimate, not an
invoice guarantee. Unknown started bills keep their hold in their original UTC
dispatch windows. A new refresh after the two-minute grace can reserve
*additional* capacity; it never restarts an old operation. No timer refunds a
possible bill.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import config
from fastapi import HTTPException

from db.connection import rpc
from db.scope import runs_as_service
from services import llm_pricing
from services.usage_receipts import PreparedUsageReceipt

_logger = logging.getLogger(__name__)

POLICY = "checklist-50k-3x8192-v2"
#: The run the hold prices (agents/topic_checklist.py CHECKLIST_LIMITS): the
#: cumulative counted input, and every attempt's full completion budget.
INPUT_TOKENS = 50_000
REQUESTS = 3
OUTPUT_TOKENS_PER_REQUEST = 8192
HOLD_TOKENS = INPUT_TOKENS + REQUESTS * OUTPUT_TOKENS_PER_REQUEST
#: llm_usage / checklist_budget_reservations money scale: NUMERIC(18,10).
_USD_QUANTUM = Decimal(1).scaleb(-llm_pricing.COST_SCALE)
#: The providers a checklist bill can come from (llm_pricing.usage_provider).
_BILLABLE_PROVIDERS = frozenset({"anthropic", "gemini"})
#: Retry-After (seconds) while an earlier request may still hold the mutex or
#: an unconfirmed bill: the two-minute grace. _BUSY_WAIT_WORDS is the same wait
#: in the 409's words; change both together.
BUSY_RETRY_AFTER_S = 120
_BUSY_WAIT_WORDS = "two minutes"
#: Retry-After (seconds) when the reservation expired or changed under a start.
CHANGED_RETRY_AFTER_S = 2


def billing_label(model_name: str) -> str:
    """`provider:model`: how a reservation names a model it may be billed under,
    and how settlement matches a bill's llm_usage provider and model to it."""
    return f"{llm_pricing.usage_provider(model_name)}:{model_name}"


@dataclass(frozen=True)
class Hold:
    """What one admission reserves: the models priced, the USD and the tokens."""

    models: tuple[str, ...]
    usd: Decimal
    tokens: int


def _policy_error() -> HTTPException:
    return HTTPException(503, "Checklist price policy needs an update. Please try again later.")


def _positive_price(value) -> Decimal:
    price = Decimal(str(value)) if value is not None else None
    if price is None or not price.is_finite() or price <= 0:
        raise ValueError("Unpriced checklist model")
    return price


def price_hold(model_names: tuple[str, ...]) -> Hold:
    """The hold for one checklist run on any of `model_names`. Each component
    is priced at its worst case over the models, since one run's attempts can
    be served by either (the fallback is per request): the counted input at
    full price or, on a provider whose cache writes cost more, all written to
    the prompt cache; every attempt's completion at its output price. An
    unpriced model, a provider that cannot bill a checklist or bounds other
    than the policy's are refused before any database call (503)."""
    from agents.topic_checklist import CHECKLIST_LIMITS, CHECKLIST_MAX_OUTPUT_TOKENS

    if not (
        CHECKLIST_LIMITS.input_tokens_limit == INPUT_TOKENS
        and CHECKLIST_LIMITS.request_limit == REQUESTS
        and CHECKLIST_MAX_OUTPUT_TOKENS == OUTPUT_TOKENS_PER_REQUEST
        and CHECKLIST_LIMITS.count_tokens_before_request
    ):
        raise _policy_error()
    output = REQUESTS * OUTPUT_TOKENS_PER_REQUEST
    try:
        names = tuple(dict.fromkeys(model_names))
        labels = tuple(billing_label(name) for name in names)
        if not names or any(label.split(":", 1)[0] not in _BILLABLE_PROVIDERS for label in labels):
            raise ValueError("No billable checklist model")
        input_usd = max(
            max(
                _positive_price(llm_pricing.cost_usd(name, INPUT_TOKENS, 0)),
                _positive_price(llm_pricing.cost_usd(
                    name, INPUT_TOKENS, 0, cache_write_tokens=INPUT_TOKENS)),
            )
            for name in names
        )
        output_usd = max(_positive_price(llm_pricing.cost_usd(name, 0, output)) for name in names)
    except (InvalidOperation, TypeError, ValueError):
        raise _policy_error() from None
    usd = (input_usd + output_usd).quantize(_USD_QUANTUM, rounding=ROUND_CEILING)
    return Hold(labels, usd, HOLD_TOKENS)


def _cap(value) -> str:
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            raise ValueError("Invalid cap")
        return str(number)
    except (InvalidOperation, TypeError, ValueError):
        raise _unavailable() from None


def _token_cap(value) -> int:
    if type(value) is not int or value <= 0:
        raise _unavailable()
    return value


def _unavailable() -> HTTPException:
    return HTTPException(503, "Checklist usage could not be confirmed. Please retry; an earlier request may still reserve allowance.", headers={"Retry-After": str(BUSY_RETRY_AFTER_S)})


@runs_as_service  # spec §13 A148: the checklist_budget_* RPCs and tables are service-only
def _call(name: str, params: dict) -> dict:
    try:
        result = rpc(f"checklist_budget_{name}", params)
        if not isinstance(result, dict) or not isinstance(result.get("status"), str):
            raise ValueError("Invalid budget acknowledgment")
        return result
    except Exception:
        raise _unavailable() from None


@dataclass(frozen=True)
class Reservation:
    operation_id: UUID
    user_id: str
    enrollment_id: str
    input_hash: str
    fence: int
    dispatch_at: datetime | None = None
    #: The `billing_label`s the hold was priced for; a run may dispatch to and
    #: be billed under these only. Empty: nothing billable may dispatch.
    models: tuple[str, ...] = ()

    @classmethod
    def from_row(cls, row: dict) -> Reservation:
        try:
            if type(row["fence"]) is not int or row["fence"] <= 0:
                raise ValueError("Invalid fence")
            for key in ("user_id", "enrollment_id", "input_hash"):
                if not isinstance(row[key], str) or not row[key]:
                    raise ValueError("Invalid identity")
            models = row["models"]
            if not isinstance(models, list) or not models or not all(isinstance(m, str) and m for m in models):
                raise ValueError("Invalid reserved models")
            dispatched_at = datetime.fromisoformat(row["dispatch_at"].replace("Z", "+00:00")) if row.get("dispatch_at") else None
            if dispatched_at is not None and dispatched_at.utcoffset() is None:
                raise ValueError("Invalid dispatch clock")
            return cls(UUID(row["operation_id"]), row["user_id"], row["enrollment_id"], row["input_hash"], row["fence"],
                       dispatched_at, tuple(models))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise _unavailable() from None

    def params(self) -> dict:
        return {"p_user_id": self.user_id, "p_operation_id": str(self.operation_id), "p_fence": self.fence}


def _holds(row: dict, hold: Hold) -> bool:
    """The reservation row records exactly this hold."""
    try:
        return (row.get("models") == list(hold.models) and row.get("held_tokens") == hold.tokens
                and Decimal(str(row.get("held_usd"))) == hold.usd)
    except (InvalidOperation, TypeError, ValueError):
        return False


def admit(user_id: str, enrollment_id: str, input_hash: str, model_names: tuple[str, ...]) -> Reservation | None:
    """Admit one paid refresh, holding `price_hold(model_names)`."""
    hold = price_hold(model_names)
    daily_usd = _cap(config.STUDENT_DAILY_BUDGET_USD)
    if hold.usd > Decimal(daily_usd):
        # #866 review (b1-budget, defect 1): the SQL admit denies a hold above
        # the daily cap even at zero spend, so every refresh would read as "no
        # allowance left". Say what is wrong instead, before any database call.
        _logger.error(
            "checklist hold %s USD on %s exceeds the daily cap %s USD: no paid "
            "refresh can ever be admitted; point the topic_checklist slot at a "
            "cheaper model or raise STUDENT_DAILY_BUDGET_USD",
            hold.usd, list(hold.models), daily_usd,
        )
        raise _policy_error()
    operation_id = uuid4()
    params = {"p_user_id": user_id, "p_enrollment_id": enrollment_id, "p_input_hash": input_hash,
              "p_operation_id": str(operation_id), "p_receipt_id": str(uuid5(NAMESPACE_URL, f"sapling:checklist-receipt:{operation_id}")),
              "p_policy": POLICY,
              "p_daily_usd": daily_usd,
              "p_monthly_usd": _cap(config.STUDENT_MONTHLY_BUDGET_USD),
              "p_daily_tokens": _token_cap(config.STUDENT_DAILY_TOKENS),
              "p_held_usd": str(hold.usd), "p_held_tokens": hold.tokens, "p_models": list(hold.models)}
    # Only admission is retried, with exactly the same operation identity. An
    # ambiguous admission cannot create a second hold or authorize generation.
    try:
        result = _call("admit", params)
    except HTTPException:
        result = _call("admit", params)
    status = result["status"]
    if status == "cached":
        return None
    if status in {"admitted", "replay"}:
        row = result.get("reservation", {})
        if (row.get("state") == "prepared" and row.get("operation_id") == str(operation_id) and row.get("user_id") == user_id
                and row.get("input_hash") == input_hash and row.get("enrollment_id") == enrollment_id and _holds(row, hold)):
            return Reservation.from_row(row)
        raise _unavailable()
    if status == "ownership":
        raise HTTPException(404, "Course enrollment is no longer available.")
    if status in {"denied", "blocked"}:
        detail = "There is not enough checklist allowance for another request. Unconfirmed requests keep their allowance reserved."
        if result.get("retry_at"):
            detail += f" The next allowance window starts at {result['retry_at']}."
        if status == "blocked":
            detail = "Checklist usage needs reconciliation before another paid refresh. Your saved checklist is still available."
        raise HTTPException(429, detail)
    if status == "busy":
        raise HTTPException(409, f"A checklist request is still in progress. Retry in {_BUSY_WAIT_WORDS}; an uncertain earlier bill will remain reserved.", headers={"Retry-After": str(BUSY_RETRY_AFTER_S)})
    raise _unavailable()


def start(reservation: Reservation) -> Reservation:
    # Never retry start: only the first successful CAS authorizes a dispatch.
    # On a lost ACK the caller has not invoked the generation handler and may
    # reconcile no_dispatch, or leave a conservative hold if DB is unavailable.
    result = _call("start", reservation.params())
    if result["status"] == "denied":
        raise HTTPException(429, "Checklist allowance changed before generation. Please try again in the next allowance window.")
    if result["status"] == "usage_unavailable":
        raise _unavailable()
    if result["status"] != "started":
        raise HTTPException(409, "Checklist request expired or changed. Please refresh again.", headers={"Retry-After": str(CHANGED_RETRY_AFTER_S)})
    row = result.get("reservation", {})
    if (row.get("state") != "started" or row.get("operation_id") != str(reservation.operation_id)
        or row.get("fence") != reservation.fence or not row.get("dispatch_at")
        or row.get("user_id") != reservation.user_id or row.get("enrollment_id") != reservation.enrollment_id
        or row.get("input_hash") != reservation.input_hash or row.get("models") != list(reservation.models)):
        raise _unavailable()
    return Reservation.from_row(row)


def read(reservation: Reservation) -> dict:
    return _call("read", {"p_user_id": reservation.user_id, "p_operation_id": str(reservation.operation_id)})


def reconcile(reservation: Reservation, *, receipt: PreparedUsageReceipt | None = None,
              content: str | None = None, no_dispatch: bool = False) -> dict:
    action = "settle" if receipt else "no_dispatch" if no_dispatch else "unknown"
    params = {**reservation.params(), "p_action": action,
              "p_receipt": receipt.to_row() if receipt else None,
              "p_fingerprint": receipt.fingerprint if receipt else None, "p_content": content}
    try:
        result = _call("reconcile", params)
    except HTTPException:
        # Exactly the same receipt/action is replayed. PostgreSQL commits the
        # canonical bill, cache and state together, so a lost ACK cannot double bill.
        try:
            result = _call("reconcile", params)
        except HTTPException:
            result = read(reservation)
            row = result.get("reservation", {})
            if receipt and row.get("state") == "settled" and row.get("fingerprint") == receipt.fingerprint and row.get("receipt") == receipt.to_row():
                return row
            if no_dispatch and row.get("state") == "released":
                return row
            raise _unavailable() from None
    if result["status"] == "conflict":
        raise HTTPException(503, "Checklist accounting needs reconciliation. Your existing checklist is still available.")
    row = result.get("reservation", {})
    if receipt and (row.get("state") != "settled" or row.get("fingerprint") != receipt.fingerprint or row.get("receipt") != receipt.to_row()):
        raise _unavailable()
    if no_dispatch and row.get("state") != "released":
        raise _unavailable()
    return row
