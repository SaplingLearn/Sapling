"""
backend/services/admin/xp_rules.py

Admin XP-rule editing (amount / enabled per rule key).

Moved verbatim out of ``routes/admin.py`` (#118); the route keeps the
auth checks and maps ``services.admin.errors`` to HTTP statuses.
"""
from __future__ import annotations

from datetime import datetime, timezone

from db.connection import table
from models import UpdateXpRuleBody
from services.admin.errors import InvalidRequest
from services.admin_audit import log_admin_action


def list_xp_rules():
    rows = table("xp_rules").select("*", order="key.asc")
    return {"rules": rows or []}


def update_xp_rule(key: str, body: UpdateXpRuleBody, actor: str | None):
    updates: dict = {}
    if body.amount is not None:
        if body.amount < 0:
            raise InvalidRequest("amount must be >= 0")
        updates["amount"] = body.amount
    if body.enabled is not None:
        updates["enabled"] = body.enabled
    if not updates:
        raise InvalidRequest("No valid fields to update")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    table("xp_rules").update(updates, filters={"key": f"eq.{key}"})
    log_admin_action(
        actor_id=actor, action="xp_rule.update", target_type="xp_rule",
        target_id=key, payload=updates,
    )
    return {"updated": True}
