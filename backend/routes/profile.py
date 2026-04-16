"""
Profile routes — public profiles, settings, cosmetics, achievements, account management.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Query

from db.connection import table
from models import (
    UpdateProfileBody,
    UpdateSettingsBody,
    EquipCosmeticBody,
    SetFeaturedRoleBody,
    SetFeaturedAchievementsBody,
    DeleteAccountBody,
)
from services.auth_guard import require_self, get_session_user_id
from services.storage_service import upload_avatar

router = APIRouter()


def _get_user_or_404(user_id: str) -> dict:
    rows = table("users").select("*", filters={"id": f"eq.{user_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    return rows[0]


def _get_or_create_settings(user_id: str) -> dict:
    rows = table("user_settings").select("*", filters={"user_id": f"eq.{user_id}"})
    if rows:
        return rows[0]
    table("user_settings").insert({"user_id": user_id})
    rows = table("user_settings").select("*", filters={"user_id": f"eq.{user_id}"})
    return rows[0] if rows else {"user_id": user_id}


def _get_user_roles(user_id: str) -> list:
    rows = table("user_roles").select(
        "granted_at,roles(id,name,slug,color,icon,description,is_staff_assigned,is_earnable,display_priority)",
        filters={"user_id": f"eq.{user_id}"},
    )
    if not rows:
        return []
    result = []
    for r in rows:
        role_data = r.get("roles", {})
        if role_data:
            result.append({"role": role_data, "granted_at": r.get("granted_at")})
    return result


def _get_equipped_cosmetics(settings: dict) -> dict:
    equipped = {}
    slot_map = {
        "avatar_frame": "equipped_avatar_frame_id",
        "banner": "equipped_banner_id",
        "name_color": "equipped_name_color_id",
        "title": "equipped_title_id",
    }
    for slot, col in slot_map.items():
        cosmetic_id = settings.get(col)
        if cosmetic_id:
            rows = table("cosmetics").select("*", filters={"id": f"eq.{cosmetic_id}"})
            if rows:
                equipped[slot] = rows[0]
    # Featured role
    featured_role_id = settings.get("featured_role_id")
    if featured_role_id:
        rows = table("roles").select("*", filters={"id": f"eq.{featured_role_id}"})
        if rows:
            equipped["featured_role"] = rows[0]
    return equipped


def _get_featured_achievements(user_id: str) -> list:
    rows = table("user_achievements").select(
        "earned_at,is_featured,achievements(id,name,slug,description,icon,category,rarity,is_secret)",
        filters={"user_id": f"eq.{user_id}", "is_featured": "eq.true"},
    )
    if not rows:
        return []
    result = []
    for r in rows:
        ach = r.get("achievements", {})
        if ach:
            result.append({
                "achievement": ach,
                "earned_at": r.get("earned_at"),
                "is_featured": True,
            })
    return result


def _get_user_stats(user_id: str) -> dict:
    user = table("users").select("streak_count", filters={"id": f"eq.{user_id}"})
    streak = user[0].get("streak_count", 0) if user else 0

    sessions = table("sessions").select("id", filters={"user_id": f"eq.{user_id}"})
    session_count = len(sessions) if sessions else 0

    docs = table("documents").select("id", filters={"user_id": f"eq.{user_id}"})
    documents_count = len(docs) if docs else 0

    achs = table("user_achievements").select("achievement_id", filters={"user_id": f"eq.{user_id}"})
    achievements_count = len(achs) if achs else 0

    return {
        "streak_count": streak,
        "session_count": session_count,
        "documents_count": documents_count,
        "achievements_count": achievements_count,
    }


# ── Public Profile ───────────────────────────────────────────────────────────

@router.get("/{user_id}")
def get_public_profile(user_id: str):
    user = _get_user_or_404(user_id)
    settings = _get_or_create_settings(user_id)
    roles = _get_user_roles(user_id)
    equipped = _get_equipped_cosmetics(settings)

    # Resolve school from user's enrolled courses
    school = None
    enrollments = table("user_courses").select(
        "courses(school)",
        filters={"user_id": f"eq.{user_id}"},
        limit=1,
    )
    if enrollments and enrollments[0].get("courses", {}).get("school"):
        school = enrollments[0]["courses"]["school"]

    profile = {
        "id": user["id"],
        "name": user.get("name", ""),
        "username": user.get("username"),
        "avatar_url": user.get("avatar_url"),
        "created_at": user.get("created_at"),
        "year": user.get("year"),
        "majors": user.get("majors") or [],
        "minors": user.get("minors") or [],
        "school": school,
        "roles": roles,
        "equipped_cosmetics": equipped,
    }

    # Respect profile visibility
    if settings.get("profile_visibility") != "private":
        profile["bio"] = user.get("bio")
        profile["location"] = user.get("location")
        profile["website"] = user.get("website")
        profile["featured_achievements"] = _get_featured_achievements(user_id)
        profile["stats"] = _get_user_stats(user_id)
    else:
        profile["bio"] = None
        profile["location"] = None
        profile["website"] = None
        profile["featured_achievements"] = []
        profile["stats"] = {}

    return profile


# ── Update Profile ───────────────────────────────────────────────────────────

@router.patch("/{user_id}")
def update_profile(user_id: str, body: UpdateProfileBody, request: Request):
    require_self(user_id, request)
    _get_user_or_404(user_id)

    updates_user = {}
    updates_settings = {}

    if body.username is not None:
        # Check uniqueness
        existing = table("users").select("id", filters={"username": f"eq.{body.username}"})
        if existing and existing[0]["id"] != user_id:
            raise HTTPException(status_code=409, detail="Username already taken")
        updates_user["username"] = body.username
        updates_settings["username"] = body.username

    if body.display_name is not None:
        updates_settings["display_name"] = body.display_name
    if body.bio is not None:
        updates_user["bio"] = body.bio
        updates_settings["bio"] = body.bio
    if body.location is not None:
        updates_user["location"] = body.location
        updates_settings["location"] = body.location
    if body.website is not None:
        updates_user["website"] = body.website
        updates_settings["website"] = body.website

    if updates_user:
        table("users").update(updates_user, filters={"id": f"eq.{user_id}"})
    if updates_settings:
        updates_settings["updated_at"] = datetime.now(timezone.utc).isoformat()
        _get_or_create_settings(user_id)
        table("user_settings").update(updates_settings, filters={"user_id": f"eq.{user_id}"})

    return {"updated": True}


# ── Avatar Upload ────────────────────────────────────────────────────────────

@router.post("/{user_id}/avatar")
async def upload_user_avatar(user_id: str, request: Request, file: UploadFile = File(...)):
    require_self(user_id, request)
    _get_user_or_404(user_id)

    file_bytes = await file.read()
    content_type = file.content_type or "image/png"
    avatar_url = upload_avatar(user_id, file_bytes, content_type)

    table("users").update({"avatar_url": avatar_url}, filters={"id": f"eq.{user_id}"})
    return {"avatar_url": avatar_url}


# ── Settings ─────────────────────────────────────────────────────────────────

@router.get("/{user_id}/settings")
def get_settings(user_id: str, request: Request):
    require_self(user_id, request)
    settings = _get_or_create_settings(user_id)
    return settings


@router.patch("/{user_id}/settings")
def update_settings(user_id: str, body: UpdateSettingsBody, request: Request):
    require_self(user_id, request)
    _get_or_create_settings(user_id)

    updates = {}
    for field in [
        "profile_visibility", "activity_status_visible",
        "notification_email", "notification_push", "notification_in_app",
        "theme", "font_size", "accent_color",
    ]:
        val = getattr(body, field)
        if val is not None:
            updates[field] = val

    if updates:
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        table("user_settings").update(updates, filters={"user_id": f"eq.{user_id}"})

    return table("user_settings").select("*", filters={"user_id": f"eq.{user_id}"})[0]


# ── Equip Cosmetic ───────────────────────────────────────────────────────────

@router.post("/{user_id}/equip")
def equip_cosmetic(user_id: str, body: EquipCosmeticBody, request: Request):
    require_self(user_id, request)
    _get_or_create_settings(user_id)

    slot_col_map = {
        "avatar_frame": "equipped_avatar_frame_id",
        "banner": "equipped_banner_id",
        "name_color": "equipped_name_color_id",
        "title": "equipped_title_id",
    }

    if body.slot not in slot_col_map:
        raise HTTPException(status_code=400, detail=f"Invalid slot: {body.slot}")

    col = slot_col_map[body.slot]

    if body.cosmetic_id:
        # Verify user owns this cosmetic
        owned = table("user_cosmetics").select(
            "cosmetic_id",
            filters={"user_id": f"eq.{user_id}", "cosmetic_id": f"eq.{body.cosmetic_id}"},
        )
        if not owned:
            raise HTTPException(status_code=403, detail="You do not own this cosmetic")

        table("user_settings").update(
            {col: body.cosmetic_id, "updated_at": datetime.now(timezone.utc).isoformat()},
            filters={"user_id": f"eq.{user_id}"},
        )
    else:
        # Unequip
        table("user_settings").update(
            {col: None, "updated_at": datetime.now(timezone.utc).isoformat()},
            filters={"user_id": f"eq.{user_id}"},
        )

    return {"equipped": True}


# ── Featured Role ────────────────────────────────────────────────────────────

@router.post("/{user_id}/featured-role")
def set_featured_role(user_id: str, body: SetFeaturedRoleBody, request: Request):
    require_self(user_id, request)
    _get_or_create_settings(user_id)

    if body.role_id:
        # Verify user has this role
        has_role = table("user_roles").select(
            "role_id",
            filters={"user_id": f"eq.{user_id}", "role_id": f"eq.{body.role_id}"},
        )
        if not has_role:
            raise HTTPException(status_code=403, detail="You do not have this role")

    table("user_settings").update(
        {"featured_role_id": body.role_id, "updated_at": datetime.now(timezone.utc).isoformat()},
        filters={"user_id": f"eq.{user_id}"},
    )
    return {"updated": True}


# ── Featured Achievements ────────────────────────────────────────────────────

@router.post("/{user_id}/featured-achievements")
def set_featured_achievements(user_id: str, body: SetFeaturedAchievementsBody, request: Request):
    require_self(user_id, request)

    if len(body.achievement_ids) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 featured achievements")

    # Verify user earned each achievement
    for aid in body.achievement_ids:
        earned = table("user_achievements").select(
            "achievement_id",
            filters={"user_id": f"eq.{user_id}", "achievement_id": f"eq.{aid}"},
        )
        if not earned:
            raise HTTPException(status_code=403, detail=f"Achievement {aid} not earned")

    # Clear old featured flags
    existing = table("user_achievements").select(
        "achievement_id,is_featured",
        filters={"user_id": f"eq.{user_id}", "is_featured": "eq.true"},
    )
    if existing:
        for row in existing:
            table("user_achievements").update(
                {"is_featured": False},
                filters={"user_id": f"eq.{user_id}", "achievement_id": f"eq.{row['achievement_id']}"},
            )

    # Set new featured
    for aid in body.achievement_ids:
        table("user_achievements").update(
            {"is_featured": True},
            filters={"user_id": f"eq.{user_id}", "achievement_id": f"eq.{aid}"},
        )

    # Also store in settings
    _get_or_create_settings(user_id)
    table("user_settings").update(
        {"featured_achievement_ids": body.achievement_ids, "updated_at": datetime.now(timezone.utc).isoformat()},
        filters={"user_id": f"eq.{user_id}"},
    )

    return {"updated": True}


# ── Achievements ─────────────────────────────────────────────────────────────

@router.get("/{user_id}/achievements")
def get_achievements(user_id: str):
    all_achs = table("achievements").select("*")
    if not all_achs:
        return {"earned": [], "available": []}

    earned_rows = table("user_achievements").select(
        "achievement_id,earned_at,is_featured",
        filters={"user_id": f"eq.{user_id}"},
    )
    earned_ids = {}
    if earned_rows:
        for r in earned_rows:
            earned_ids[r["achievement_id"]] = r

    earned = []
    available = []

    for ach in all_achs:
        if ach["id"] in earned_ids:
            earned.append({
                "achievement": ach,
                "earned_at": earned_ids[ach["id"]]["earned_at"],
                "is_featured": earned_ids[ach["id"]]["is_featured"],
            })
        else:
            if ach.get("is_secret"):
                available.append({
                    "id": ach["id"],
                    "name": "Secret Achievement",
                    "slug": ach["slug"],
                    "description": "Keep exploring to discover this achievement",
                    "icon": None,
                    "category": ach["category"],
                    "rarity": ach["rarity"],
                    "is_secret": True,
                })
            else:
                available.append(ach)

    return {"earned": earned, "available": available}


# ── Cosmetics ────────────────────────────────────────────────────────────────

@router.get("/{user_id}/cosmetics")
def get_cosmetics(user_id: str, request: Request):
    require_self(user_id, request)
    settings = _get_or_create_settings(user_id)

    owned = table("user_cosmetics").select(
        "unlocked_at,cosmetics(id,type,name,slug,asset_url,css_value,rarity)",
        filters={"user_id": f"eq.{user_id}"},
    )

    grouped = {"avatar_frame": [], "banner": [], "name_color": [], "title": []}
    if owned:
        for row in owned:
            cosmetic = row.get("cosmetics", {})
            if cosmetic and cosmetic.get("type") in grouped:
                grouped[cosmetic["type"]].append({
                    "cosmetic": cosmetic,
                    "unlocked_at": row["unlocked_at"],
                })

    return {"cosmetics": grouped, "equipped": _get_equipped_cosmetics(settings)}


# ── Roles ────────────────────────────────────────────────────────────────────

@router.get("/{user_id}/roles")
def get_roles(user_id: str):
    return {"roles": _get_user_roles(user_id)}


# ── Delete Account ───────────────────────────────────────────────────────────

@router.delete("/{user_id}/account")
def delete_account(user_id: str, body: DeleteAccountBody, request: Request):
    require_self(user_id, request)

    if body.confirmation != "DELETE":
        raise HTTPException(status_code=400, detail="Confirmation must be 'DELETE'")

    table("users").update(
        {"deleted_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{user_id}"},
    )
    return {"deleted": True}


# ── Data Export ──────────────────────────────────────────────────────────────

@router.post("/{user_id}/export")
def export_data(user_id: str, request: Request):
    require_self(user_id, request)

    user = _get_user_or_404(user_id)
    settings = _get_or_create_settings(user_id)
    roles = _get_user_roles(user_id)

    earned = table("user_achievements").select(
        "achievement_id,earned_at,is_featured,achievements(name,slug)",
        filters={"user_id": f"eq.{user_id}"},
    )

    owned_cosmetics = table("user_cosmetics").select(
        "cosmetic_id,unlocked_at,cosmetics(name,slug,type)",
        filters={"user_id": f"eq.{user_id}"},
    )

    return {
        "user": user,
        "settings": settings,
        "roles": roles,
        "achievements": earned or [],
        "cosmetics": owned_cosmetics or [],
    }
