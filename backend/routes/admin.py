"""
Admin routes — role, achievement, cosmetic, and user management.
All routes require admin role.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Depends

from db.connection import table
from models import (
    CreateRoleBody,
    AssignRoleBody,
    RevokeRoleBody,
    CreateAchievementBody,
    CreateAchievementTriggerBody,
    GrantAchievementBody,
    CreateCosmeticBody,
)
from services.auth_guard import require_admin
from services.achievement_service import check_achievements

router = APIRouter()


# ── Roles ────────────────────────────────────────────────────────────────────

@router.get("/roles")
def list_roles(request: Request):
    require_admin(request)
    rows = table("roles").select("*", order="display_priority.desc")
    return {"roles": rows or []}


@router.post("/roles")
def create_role(body: CreateRoleBody, request: Request):
    require_admin(request)
    result = table("roles").insert({
        "name": body.name,  # ENCRYPTED LATER
        "slug": body.slug,
        "color": body.color,
        "icon": body.icon,
        "description": body.description,
        "is_staff_assigned": body.is_staff_assigned,
        "is_earnable": body.is_earnable,
        "display_priority": body.display_priority,
    })
    return {"role": result[0] if result else None}


@router.patch("/roles/{role_id}")
def update_role(role_id: str, request: Request, body: dict = {}):
    require_admin(request)
    allowed = {"name", "color", "icon", "description", "is_staff_assigned", "is_earnable", "display_priority"}  # ENCRYPTED LATER
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    table("roles").update(updates, filters={"id": f"eq.{role_id}"})
    return {"updated": True}


@router.post("/roles/assign")
def assign_role(body: AssignRoleBody, request: Request):
    require_admin(request)
    table("user_roles").insert({
        "user_id": body.user_id,
        "role_id": body.role_id,
        "granted_by": body.granted_by,
        "granted_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"assigned": True}


@router.delete("/roles/revoke")
def revoke_role(body: RevokeRoleBody, request: Request):
    require_admin(request)
    table("user_roles").delete(filters={
        "user_id": f"eq.{body.user_id}",
        "role_id": f"eq.{body.role_id}",
    })
    return {"revoked": True}


@router.delete("/roles/{role_id}")
def delete_role(role_id: str, request: Request):
    require_admin(request)
    table("roles").delete(filters={"id": f"eq.{role_id}"})
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
    result = table("achievements").insert({
        "name": body.name,  # ENCRYPTED LATER
        "slug": body.slug,
        "description": body.description,
        "icon": body.icon,
        "category": body.category,
        "rarity": body.rarity,
        "is_secret": body.is_secret,
    })
    return {"achievement": result[0] if result else None}


@router.patch("/achievements/{achievement_id}")
def update_achievement(achievement_id: str, request: Request, body: dict = {}):
    require_admin(request)
    allowed = {"name", "description", "icon", "category", "rarity", "is_secret"}  # ENCRYPTED LATER
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    table("achievements").update(updates, filters={"id": f"eq.{achievement_id}"})
    return {"updated": True}


@router.delete("/achievements/{achievement_id}")
def delete_achievement(achievement_id: str, request: Request):
    require_admin(request)
    table("achievements").delete(filters={"id": f"eq.{achievement_id}"})
    return {"deleted": True}


@router.post("/achievements/grant")
def grant_achievement(body: GrantAchievementBody, request: Request):
    require_admin(request)
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

    # Trigger linked cosmetics via achievement service
    check_achievements(body.user_id, "manual_admin_grant", {})

    return {"granted": True}


@router.post("/achievements/triggers")
def create_trigger(body: CreateAchievementTriggerBody, request: Request):
    require_admin(request)
    result = table("achievement_triggers").insert({
        "achievement_id": body.achievement_id,
        "trigger_type": body.trigger_type,
        "trigger_threshold": body.trigger_threshold,
    })
    return {"trigger": result[0] if result else None}


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
        "name": body.name,  # ENCRYPTED LATER
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
    allowed = {"name", "asset_url", "css_value", "rarity", "unlock_source"}  # ENCRYPTED LATER
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
def list_users(request: Request):
    require_admin(request)
    users = table("users").select("id,name,email,is_approved,created_at")  # ENCRYPTED LATER
    if not users:
        return {"users": []}

    # Attach roles to each user
    for user in users:
        roles = table("user_roles").select(
            "roles(id,name,slug,color)",  # ENCRYPTED LATER
            filters={"user_id": f"eq.{user['id']}"},
        )
        user["roles"] = [r.get("roles", {}) for r in roles] if roles else []

    return {"users": users}


@router.patch("/users/{user_id}/approve")
def approve_user(user_id: str, request: Request):
    require_admin(request)
    table("users").update({"is_approved": True}, filters={"id": f"eq.{user_id}"})
    return {"approved": True}
