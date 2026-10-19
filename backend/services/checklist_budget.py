"""Durable, checklist-participant capacity holds through backend-only RPCs.

This is not a global spend cap: other features do not take the mutex. The fixed
price envelope uses the native counter's estimate, not an invoice guarantee.
Unknown started bills keep their hold in their original UTC dispatch windows.
A new refresh after the two-minute grace can reserve *additional* capacity; it
never restarts an old operation. No timer refunds a possible bill.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import config
from fastapi import HTTPException

from db.connection import rpc
from services import llm_pricing
from services.usage_receipts import PreparedUsageReceipt

POLICY = "flash-50k-3x8192-v1"
MODEL = "gemini-2.5-flash"
HOLD_USD = Decimal("0.0764400000")
HOLD_TOKENS = 74_576


def verify_price_profile() -> None:
    # A price/config/model change must not silently run against a stale DB hold.
    from agents.topic_checklist import CHECKLIST_LIMITS, CHECKLIST_MAX_OUTPUT_TOKENS

    try:
        matches = (
            Decimal(str(llm_pricing.cost_usd(MODEL, 50_000, 3 * 8192))) == HOLD_USD
            and Decimal(str(llm_pricing.cost_usd(MODEL, 1000, 0))) == Decimal(".0003")
            and Decimal(str(llm_pricing.cost_usd(MODEL, 0, 1000))) == Decimal(".0025")
            and Decimal(str(llm_pricing.cost_usd(MODEL, 1000, 0, cached_tokens=1000))) == Decimal(".00003")
        )
    except (InvalidOperation, TypeError, ValueError):
        matches = False
    matches = matches and CHECKLIST_LIMITS.input_tokens_limit == 50_000 and CHECKLIST_LIMITS.request_limit == 3 and CHECKLIST_MAX_OUTPUT_TOKENS == 8192 and CHECKLIST_LIMITS.count_tokens_before_request
    if not matches:
        raise HTTPException(503, "Checklist price policy needs an update. Please try again later.")


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
    return HTTPException(503, "Checklist usage could not be confirmed. Please retry; an earlier request may still reserve allowance.", headers={"Retry-After": "120"})


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

    @classmethod
    def from_row(cls, row: dict) -> Reservation:
        try:
            if type(row["fence"]) is not int or row["fence"] <= 0:
                raise ValueError("Invalid fence")
            for key in ("user_id", "enrollment_id", "input_hash"):
                if not isinstance(row[key], str) or not row[key]:
                    raise ValueError("Invalid identity")
            dispatched_at = datetime.fromisoformat(row["dispatch_at"].replace("Z", "+00:00")) if row.get("dispatch_at") else None
            if dispatched_at is not None and dispatched_at.utcoffset() is None:
                raise ValueError("Invalid dispatch clock")
            return cls(UUID(row["operation_id"]), row["user_id"], row["enrollment_id"], row["input_hash"], row["fence"], dispatched_at)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise _unavailable() from None

    def params(self) -> dict:
        return {"p_user_id": self.user_id, "p_operation_id": str(self.operation_id), "p_fence": self.fence}


def admit(user_id: str, enrollment_id: str, input_hash: str) -> Reservation | None:
    verify_price_profile()
    operation_id = uuid4()
    params = {"p_user_id": user_id, "p_enrollment_id": enrollment_id, "p_input_hash": input_hash,
              "p_operation_id": str(operation_id), "p_receipt_id": str(uuid5(NAMESPACE_URL, f"sapling:checklist-receipt:{operation_id}")),
              "p_policy": POLICY,
              "p_daily_usd": _cap(config.STUDENT_DAILY_BUDGET_USD),
              "p_monthly_usd": _cap(config.STUDENT_MONTHLY_BUDGET_USD),
              "p_daily_tokens": _token_cap(config.STUDENT_DAILY_TOKENS)}
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
        if row.get("state") == "prepared" and row.get("operation_id") == str(operation_id) and row.get("user_id") == user_id and row.get("input_hash") == input_hash and row.get("enrollment_id") == enrollment_id:
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
        raise HTTPException(409, "A checklist request is still in progress. Retry in two minutes; an uncertain earlier bill will remain reserved.", headers={"Retry-After": "120"})
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
        raise HTTPException(409, "Checklist request expired or changed. Please refresh again.", headers={"Retry-After": "2"})
    row = result.get("reservation", {})
    if (row.get("state") != "started" or row.get("operation_id") != str(reservation.operation_id)
        or row.get("fence") != reservation.fence or not row.get("dispatch_at")
        or row.get("user_id") != reservation.user_id or row.get("enrollment_id") != reservation.enrollment_id
        or row.get("input_hash") != reservation.input_hash):
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
