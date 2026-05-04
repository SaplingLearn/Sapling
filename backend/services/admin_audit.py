"""
Audit-log helper for admin mutations. Every admin write goes through here.
Failures are logged but never raised — audit must not block the operation.
"""

import logging
from typing import Any, Optional

from db.connection import table

log = logging.getLogger(__name__)


def log_admin_action(
    actor_id: str,
    action: str,
    target_type: str,
    target_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    row = {
        "actor_id": actor_id,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "payload": payload or {},
    }
    try:
        table("admin_audit_log").insert(row)
    except Exception:  # noqa: BLE001 — audit failures must not break the action
        log.exception(
            "admin_audit_log write failed action=%s target_type=%s",
            action,
            target_type,
        )
