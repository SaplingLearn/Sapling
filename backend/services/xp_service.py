"""The single XP award path.

Every XP grant in the product goes through `award_xp`. It writes one row to the
append-only `xp_events` ledger and then refreshes the `users.total_xp` /
`users.level` caches from it.

Idempotency is the reason this is a service and not three inline inserts: a
retried quiz submit, a re-delivered background task or a double-clicked upload
must not pay out twice. Each event carries a deterministic key backed by a
UNIQUE index; a 409 from Postgres means "already paid" and is a clean no-op,
not an error.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from db.connection import table
from services.growth import level_for_xp

logger = logging.getLogger(__name__)


@dataclass
class XpAward:
    awarded: int
    total_xp: int
    level: int
    leveled_up: bool
    duplicate: bool = False


def idempotency_key(rule_key: str, source_type: str | None, source_id: str | None) -> str:
    return f"{rule_key}:{source_type or '-'}:{source_id or '-'}"


def _rule_amount(rule_key: str) -> int:
    rows = table("xp_rules").select(
        "key,amount,enabled", filters={"key": f"eq.{rule_key}"}
    )
    if not rows:
        logger.warning("award_xp: unknown rule_key=%s", rule_key)
        return 0
    rule = rows[0]
    if not rule.get("enabled", True):
        return 0
    return int(rule.get("amount") or 0)


def _user_state(user_id: str) -> tuple[int, int]:
    rows = table("users").select("total_xp,level", filters={"id": f"eq.{user_id}"})
    if not rows:
        return 0, 1
    return int(rows[0].get("total_xp") or 0), int(rows[0].get("level") or 1)


def award_xp(
    user_id: str,
    rule_key: str,
    *,
    source_type: str | None = None,
    source_id: str | None = None,
    amount: int | None = None,
) -> XpAward:
    """Grant XP once. `amount` overrides the rule (achievement rewards use it)."""
    value = amount if amount is not None else _rule_amount(rule_key)
    if value <= 0:
        total_xp, level = _user_state(user_id)
        return XpAward(awarded=0, total_xp=total_xp, level=level, leveled_up=False)

    key = idempotency_key(rule_key, source_type, source_id)
    try:
        table("xp_events").insert({
            "user_id": user_id,
            "rule_key": rule_key,
            "amount": value,
            "source_type": source_type,
            "source_id": source_id,
            "idempotency_key": key,
        })
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 409:
            raise
        # Already paid out — report current state without touching the cache.
        total_xp, level = _user_state(user_id)
        return XpAward(awarded=0, total_xp=total_xp, level=level,
                       leveled_up=False, duplicate=True)

    prev_total, prev_level = _user_state(user_id)
    total_xp = prev_total + value
    level = level_for_xp(total_xp)
    table("users").update(
        {"total_xp": total_xp, "level": level}, filters={"id": f"eq.{user_id}"}
    )
    return XpAward(
        awarded=value, total_xp=total_xp, level=level,
        leveled_up=level > prev_level,
    )


def award_xp_safe(*args, **kwargs) -> XpAward | None:
    """award_xp that never raises. Use this on request paths — XP must not be
    able to fail the action that earned it."""
    try:
        return award_xp(*args, **kwargs)
    except Exception:
        logger.exception("award_xp failed rule=%s", args[1] if len(args) > 1 else kwargs.get("rule_key"))
        return None
