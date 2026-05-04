"""
Admin routes — role, achievement, cosmetic, and user management.
All routes require admin role.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Depends

from db.connection import table
from models import (
    CreateRoleBody,
    AssignRoleBody,
    RevokeRoleBody,
    CreateAchievementBody,
    CreateAchievementTriggerBody,
    UpdateAchievementTriggerBody,
    GrantAchievementBody,
    CreateCosmeticBody,
    LinkAchievementCosmeticBody,
)
from services.admin_audit import log_admin_action
from services.auth_guard import require_admin, get_session_user_id
from services.achievement_service import check_achievements
from services.users_search import paginate_users

router = APIRouter()


def _role_slug(role_id: str) -> Optional[str]:
    rows = table("roles").select("id,slug", filters={"id": f"eq.{role_id}"})
    return rows[0]["slug"] if rows else None


def _admin_user_count() -> int:
    rows = table("user_roles").select(
        "user_id,roles!inner(slug)",
        filters={"roles.slug": "eq.admin"},
    )
    return len(rows or [])


# ── Roles ────────────────────────────────────────────────────────────────────

@router.get("/roles")
def list_roles(request: Request):
    require_admin(request)
    rows = table("roles").select("*", order="display_priority.desc")
    return {"roles": rows or []}


@router.post("/roles")
def create_role(body: CreateRoleBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
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


@router.patch("/roles/{role_id}")
def update_role(role_id: str, request: Request, body: dict = {}):
    require_admin(request)
    actor = get_session_user_id(request)
    allowed = {"name", "color", "icon", "description", "is_staff_assigned", "is_earnable", "display_priority"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    table("roles").update(updates, filters={"id": f"eq.{role_id}"})
    log_admin_action(actor_id=actor, action="role.update", target_type="role", target_id=role_id, payload=updates)
    return {"updated": True}


@router.post("/roles/assign")
def assign_role(body: AssignRoleBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    granted_by = body.granted_by or actor
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
    return {"assigned": True}


@router.delete("/roles/revoke")
def revoke_role(body: RevokeRoleBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    slug = _role_slug(body.role_id)
    if slug == "admin":
        if body.user_id == actor:
            raise HTTPException(status_code=409, detail="You cannot revoke your own admin role.")
        if _admin_user_count() <= 1:
            raise HTTPException(status_code=409, detail="Cannot revoke the last admin.")
    table("user_roles").delete(filters={
        "user_id": f"eq.{body.user_id}",
        "role_id": f"eq.{body.role_id}",
    })
    log_admin_action(
        actor_id=actor, action="role.revoke", target_type="role", target_id=body.role_id,
        payload={"user_id": body.user_id},
    )
    return {"revoked": True}


@router.delete("/roles/{role_id}")
def delete_role(role_id: str, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    if _role_slug(role_id) == "admin":
        raise HTTPException(status_code=409, detail="Cannot delete the admin role.")
    table("roles").delete(filters={"id": f"eq.{role_id}"})
    log_admin_action(actor_id=actor, action="role.delete", target_type="role", target_id=role_id)
    return {"deleted": True}


# ── Achievements ─────────────────────────────────────────────────────────────

@router.get("/achievements")
def list_achievements(request: Request):
    require_admin(request)
    rows = table("achievements").select("*", order="created_at.desc")
    return {"achievements": rows or []}


@router.post("/achievements")
def create_achievement(body: CreateAchievementBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    result = table("achievements").insert({
        "name": body.name,
        "slug": body.slug,
        "description": body.description,
        "icon": body.icon,
        "category": body.category,
        "rarity": body.rarity,
        "is_secret": body.is_secret,
    })
    log_admin_action(
        actor_id=actor, action="achievement.create", target_type="achievement",
        target_id=result[0]["id"] if result else None,
        payload={"slug": body.slug, "name": body.name},
    )
    return {"achievement": result[0] if result else None}


@router.patch("/achievements/{achievement_id}")
def update_achievement(achievement_id: str, request: Request, body: dict = {}):
    require_admin(request)
    actor = get_session_user_id(request)
    allowed = {"name", "description", "icon", "category", "rarity", "is_secret"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    table("achievements").update(updates, filters={"id": f"eq.{achievement_id}"})
    log_admin_action(
        actor_id=actor, action="achievement.update", target_type="achievement",
        target_id=achievement_id, payload=updates,
    )
    return {"updated": True}


@router.delete("/achievements/cosmetics")
def unlink_achievement_cosmetic(body: LinkAchievementCosmeticBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    table("achievement_cosmetics").delete(filters={
        "achievement_id": f"eq.{body.achievement_id}",
        "cosmetic_id": f"eq.{body.cosmetic_id}",
    })
    log_admin_action(
        actor_id=actor, action="achievement_cosmetic.unlink",
        target_type="achievement_cosmetic", target_id=body.achievement_id,
        payload={"cosmetic_id": body.cosmetic_id},
    )
    return {"unlinked": True}


@router.delete("/achievements/{achievement_id}")
def delete_achievement(achievement_id: str, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    table("achievements").delete(filters={"id": f"eq.{achievement_id}"})
    log_admin_action(
        actor_id=actor, action="achievement.delete", target_type="achievement",
        target_id=achievement_id,
    )
    return {"deleted": True}


@router.post("/achievements/grant")
def grant_achievement(body: GrantAchievementBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    # Check if already earned
    existing = table("user_achievements").select(
        "achievement_id",
        filters={"user_id": f"eq.{body.user_id}", "achievement_id": f"eq.{body.achievement_id}"},
    )
    if existing:
        raise HTTPException(status_code=409, detail="User already has this achievement")

    table("user_achievements").insert({
        "user_id": body.user_id,
        "achievement_id": body.achievement_id,
        "earned_at": datetime.now(timezone.utc).isoformat(),
        "is_featured": False,
    })
    log_admin_action(
        actor_id=actor, action="achievement.grant", target_type="achievement",
        target_id=body.achievement_id, payload={"user_id": body.user_id},
    )

    # Trigger linked cosmetics via achievement service
    check_achievements(body.user_id, "manual_admin_grant", {})

    return {"granted": True}


@router.post("/achievements/triggers")
def create_trigger(body: CreateAchievementTriggerBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    result = table("achievement_triggers").insert({
        "achievement_id": body.achievement_id,
        "trigger_type": body.trigger_type,
        "trigger_threshold": body.trigger_threshold,
    })
    log_admin_action(
        actor_id=actor, action="trigger.create", target_type="trigger",
        target_id=result[0]["id"] if result else None,
        payload={
            "achievement_id": body.achievement_id,
            "trigger_type": body.trigger_type,
            "trigger_threshold": body.trigger_threshold,
        },
    )
    return {"trigger": result[0] if result else None}


@router.get("/achievements/{achievement_id}/triggers")
def list_triggers(achievement_id: str, request: Request):
    require_admin(request)
    rows = table("achievement_triggers").select(
        "id,achievement_id,trigger_type,trigger_threshold",
        filters={"achievement_id": f"eq.{achievement_id}"},
    )
    return {"triggers": rows or []}


@router.patch("/achievements/triggers/{trigger_id}")
def update_trigger(trigger_id: str, body: UpdateAchievementTriggerBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    table("achievement_triggers").update(updates, filters={"id": f"eq.{trigger_id}"})
    log_admin_action(actor_id=actor, action="trigger.update", target_type="trigger", target_id=trigger_id, payload=updates)
    return {"updated": True}


@router.delete("/achievements/triggers/{trigger_id}")
def delete_trigger(trigger_id: str, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    table("achievement_triggers").delete(filters={"id": f"eq.{trigger_id}"})
    log_admin_action(actor_id=actor, action="trigger.delete", target_type="trigger", target_id=trigger_id)
    return {"deleted": True}


@router.get("/achievements/{achievement_id}/cosmetics")
def list_achievement_cosmetics(achievement_id: str, request: Request):
    require_admin(request)
    rows = table("achievement_cosmetics").select(
        "achievement_id,cosmetic_id",
        filters={"achievement_id": f"eq.{achievement_id}"},
    )
    return {"links": rows or []}


@router.post("/achievements/cosmetics")
def link_achievement_cosmetic(body: LinkAchievementCosmeticBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    table("achievement_cosmetics").upsert(
        {"achievement_id": body.achievement_id, "cosmetic_id": body.cosmetic_id},
        on_conflict="achievement_id,cosmetic_id",
    )
    log_admin_action(
        actor_id=actor, action="achievement_cosmetic.link",
        target_type="achievement_cosmetic", target_id=body.achievement_id,
        payload={"cosmetic_id": body.cosmetic_id},
    )
    return {"linked": True}


# ── Cosmetics ────────────────────────────────────────────────────────────────

@router.get("/cosmetics")
def list_cosmetics(request: Request):
    require_admin(request)
    rows = table("cosmetics").select("*", order="type.asc")
    return {"cosmetics": rows or []}


@router.post("/cosmetics")
def create_cosmetic(body: CreateCosmeticBody, request: Request):
    require_admin(request)
    result = table("cosmetics").insert({
        "type": body.type,
        "name": body.name,
        "slug": body.slug,
        "asset_url": body.asset_url,
        "css_value": body.css_value,
        "rarity": body.rarity,
        "unlock_source": body.unlock_source,
    })
    return {"cosmetic": result[0] if result else None}


@router.patch("/cosmetics/{cosmetic_id}")
def update_cosmetic(cosmetic_id: str, request: Request, body: dict = {}):
    require_admin(request)
    allowed = {"name", "asset_url", "css_value", "rarity", "unlock_source"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    table("cosmetics").update(updates, filters={"id": f"eq.{cosmetic_id}"})
    return {"updated": True}


@router.delete("/cosmetics/{cosmetic_id}")
def delete_cosmetic(cosmetic_id: str, request: Request):
    require_admin(request)
    table("cosmetics").delete(filters={"id": f"eq.{cosmetic_id}"})
    return {"deleted": True}


# ── Users ────────────────────────────────────────────────────────────────────

@router.get("/users")
def list_users(
    request: Request,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    require_admin(request)
    return paginate_users(q=q, page=page, page_size=page_size)


@router.patch("/users/{user_id}/approve")
def approve_user(user_id: str, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    table("users").update({"is_approved": True}, filters={"id": f"eq.{user_id}"})
    log_admin_action(actor_id=actor, action="user.approve", target_type="user", target_id=user_id)
    return {"approved": True}


@router.patch("/users/{user_id}/unapprove")
def unapprove_user(user_id: str, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    if user_id == actor:
        raise HTTPException(status_code=409, detail="You cannot unapprove yourself.")
    table("users").update({"is_approved": False}, filters={"id": f"eq.{user_id}"})
    log_admin_action(actor_id=actor, action="user.unapprove", target_type="user", target_id=user_id)
    return {"unapproved": True}
