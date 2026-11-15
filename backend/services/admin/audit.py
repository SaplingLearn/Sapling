"""
backend/services/admin/audit.py

The admin audit log, paged and filterable.

Moved verbatim out of ``routes/admin.py`` (#118); the route keeps the
auth checks and maps ``services.admin.errors`` to HTTP statuses.
"""
from __future__ import annotations

from typing import Optional

from db.connection import table


def list_audit(
    page: int = 1,
    page_size: int = 50,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    actor_id: Optional[str] = None,
):
    page = max(1, int(page))
    page_size = max(1, min(200, int(page_size)))
    offset = (page - 1) * page_size
    filters: dict = {}
    if action:
        filters["action"] = f"eq.{action}"
    if target_type:
        filters["target_type"] = f"eq.{target_type}"
    if actor_id:
        filters["actor_id"] = f"eq.{actor_id}"
    rows, total = table("admin_audit_log").select_with_count(
        columns="id,actor_id,action,target_type,target_id,payload,created_at",
        filters=filters or None,
        order="created_at.desc",
        limit=page_size,
        offset=offset,
    )
    return {"entries": rows, "total": total, "page": page, "page_size": page_size}
