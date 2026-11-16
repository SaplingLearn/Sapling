"""
backend/services/admin/roles.py

Admin role management: CRUD, assign/revoke (with the self/last-admin
guards) and role↔cosmetic links. ``delete_role`` stays in the route: it calls
``routes/admin_flags.py::record_flag_change``, which a domain package may not
import.

Moved verbatim out of ``routes/admin.py`` (#118); the route keeps the
auth checks and maps ``services.admin.errors`` to HTTP statuses.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from db.connection import table
from models import AssignRoleBody, CreateRoleBody, LinkRoleCosmeticBody, RevokeRoleBody
from services.admin.errors import Conflict, InvalidRequest
from services.admin_audit import log_admin_action
from services.feature_flags import clear_user_roles_cache


def _role_slug(role_id: str) -> Optional[str]:
    rows = table("roles").select("id,slug", filters={"id": f"eq.{role_id}"})
    return rows[0]["slug"] if rows else None


def _admin_user_count() -> int:
    rows = table("user_roles").select(
        "user_id,roles!inner(slug)",
        filters={"roles.slug": "eq.admin"},
    )
    return len(rows or [])


def list_roles():
    rows = table("roles").select("*", order="display_priority.desc")
    return {"roles": rows or []}


def create_role(body: CreateRoleBody, actor: str | None):
    result = table("roles").insert({
        "name": body.name,
        "slug": body.slug,
        "color": body.color,
        "icon": body.icon,
        "description": body.description,
        "is_staff_assigned": body.is_staff_assigned,
        "is_earnable": body.is_earnable,
        "display_priority": body.display_priority,
    })
    role = result[0] if result else None
    log_admin_action(
        actor_id=actor, action="role.create", target_type="role",
        target_id=role["id"] if role else None,
        payload={"slug": body.slug, "name": body.name},
    )
    return {"role": role}


def update_role(role_id: str, body: dict, actor: str | None):
    allowed = {"name", "color", "icon", "description", "is_staff_assigned", "is_earnable", "display_priority"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise InvalidRequest("No valid fields to update")
    table("roles").update(updates, filters={"id": f"eq.{role_id}"})
    log_admin_action(actor_id=actor, action="role.update", target_type="role", target_id=role_id, payload=updates)
    # display_priority rides in every holder's cached roles (#620 role rules).
    clear_user_roles_cache()
    return {"updated": True}


def assign_role(body: AssignRoleBody, actor: str | None):
    granted_by = actor
    table("user_roles").upsert(
        {
            "user_id": body.user_id,
            "role_id": body.role_id,
            "granted_by": granted_by,
            "granted_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id,role_id",
    )
    log_admin_action(
        actor_id=actor, action="role.assign", target_type="role", target_id=body.role_id,
        payload={"user_id": body.user_id, "granted_by": granted_by},
    )
    clear_user_roles_cache(body.user_id)
    return {"assigned": True}


def revoke_role(body: RevokeRoleBody, actor: str | None):
    slug = _role_slug(body.role_id)
    if slug == "admin":
        if body.user_id == actor:
            raise Conflict("You cannot revoke your own admin role.")
        if _admin_user_count() <= 1:
            raise Conflict("Cannot revoke the last admin.")
    table("user_roles").delete(filters={
        "user_id": f"eq.{body.user_id}",
        "role_id": f"eq.{body.role_id}",
    })
    log_admin_action(
        actor_id=actor, action="role.revoke", target_type="role", target_id=body.role_id,
        payload={"user_id": body.user_id},
    )
    clear_user_roles_cache(body.user_id)
    return {"revoked": True}


def list_role_cosmetics(role_id: str):
    rows = table("role_cosmetics").select(
        "role_id,cosmetic_id",
        filters={"role_id": f"eq.{role_id}"},
    )
    return {"links": rows or []}


def link_role_cosmetic(body: LinkRoleCosmeticBody, actor: str | None):
    table("role_cosmetics").upsert(
        {"role_id": body.role_id, "cosmetic_id": body.cosmetic_id},
        on_conflict="role_id,cosmetic_id",
    )
    log_admin_action(
        actor_id=actor, action="role_cosmetic.link",
        target_type="role_cosmetic", target_id=body.role_id,
        payload={"cosmetic_id": body.cosmetic_id},
    )
    return {"linked": True}


def unlink_role_cosmetic(body: LinkRoleCosmeticBody, actor: str | None):
    table("role_cosmetics").delete(filters={
        "role_id": f"eq.{body.role_id}",
        "cosmetic_id": f"eq.{body.cosmetic_id}",
    })
    log_admin_action(
        actor_id=actor, action="role_cosmetic.unlink",
        target_type="role_cosmetic", target_id=body.role_id,
        payload={"cosmetic_id": body.cosmetic_id},
    )
    return {"unlinked": True}
