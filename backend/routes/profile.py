"""
Profile routes — public profiles, settings, cosmetics, achievements, account management.
"""

import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Query

from db.connection import table
from services.encryption import encrypt_if_present, decrypt_if_present
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
from services.achievement_service import get_user_stat

router = APIRouter()


def _get_user_or_404(user_id: str) -> dict:
    rows = table("users").select(
        "id,username,name,first_name,last_name,email,avatar_url,school,major,year,majors,minors,bio,location,website,streak_count,created_at",
        filters={"id": f"eq.{user_id}"},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    row = rows[0]
    for col in ("name", "first_name", "last_name", "email", "bio", "location"):
        row[col] = decrypt_if_present(row.get(col))
    return row


_SETTINGS_COLS = (
    "user_id,username,display_name,bio,location,website,"
    "profile_visibility,activity_status_visible,"
    "notification_email,notification_push,notification_in_app,"
    "theme,font_size,accent_color,"
    "equipped_avatar_frame_id,equipped_banner_id,equipped_name_color_id,equipped_title_id,"
    "featured_role_id,featured_achievement_ids,updated_at"
)


def _get_or_create_settings(user_id: str) -> dict:
    rows = table("user_settings").select(_SETTINGS_COLS, filters={"user_id": f"eq.{user_id}"})
    if not rows:
        table("user_settings").insert({"user_id": user_id})
        rows = table("user_settings").select(_SETTINGS_COLS, filters={"user_id": f"eq.{user_id}"})
    if not rows:
        return {"user_id": user_id}
    row = rows[0]
    for col in ("bio", "location"):
        row[col] = decrypt_if_present(row.get(col))
    return row


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
            rows = table("cosmetics").select(
                "id,type,name,slug,asset_url,css_value,rarity",
                filters={"id": f"eq.{cosmetic_id}"},
            )
            if rows:
                equipped[slot] = rows[0]
    # Featured role
    featured_role_id = settings.get("featured_role_id")
    if featured_role_id:
        rows = table("roles").select(
            "id,name,slug,color,icon,description,is_staff_assigned,is_earnable,display_priority",
            filters={"id": f"eq.{featured_role_id}"},
        )
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


# ── Username Availability ────────────────────────────────────────────────────

_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,24}$")


@router.get("/username/check")
def check_username(username: str = Query(...), user_id: Optional[str] = Query(None)):
    name = (username or "").strip().lower()
    if not _USERNAME_RE.match(name):
        return {"available": False, "reason": "invalid"}
    existing = table("users").select("id", filters={"username": f"eq.{name}"})
    if not existing:
        return {"available": True}
    if user_id and existing[0]["id"] == user_id:
        return {"available": True, "reason": "self"}
    return {"available": False, "reason": "taken"}


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
        updates_user["bio"] = encrypt_if_present(body.bio)
        updates_settings["bio"] = encrypt_if_present(body.bio)
    if body.location is not None:
        updates_user["location"] = encrypt_if_present(body.location)
        updates_settings["location"] = encrypt_if_present(body.location)
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

    # Whitelist: only these fields may be patched via this endpoint.
    # EXCLUDES bio/location (encrypted later, set via /profile patch) and any
    # role/admin/approval fields to prevent privilege escalation.
    ALLOWED = {
        "profile_visibility", "activity_status_visible",
        "notification_email", "notification_push", "notification_in_app",
        "theme", "font_size", "accent_color",
    }
    incoming = body.model_dump(exclude_none=True)
    updates = {k: v for k, v in incoming.items() if k in ALLOWED}

    if updates:
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        table("user_settings").update(updates, filters={"user_id": f"eq.{user_id}"})

    return table("user_settings").select(_SETTINGS_COLS, filters={"user_id": f"eq.{user_id}"})[0]


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
    all_achs = table("achievements").select(
        "id,name,slug,description,icon,category,rarity,is_secret"
    )
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

    # Fetch triggers once and group by achievement_id so we can surface progress.
    trigger_rows = table("achievement_triggers").select(
        "achievement_id,trigger_type,trigger_threshold",
    )
    triggers_by_ach: dict = {}
    for t in trigger_rows or []:
        triggers_by_ach.setdefault(t["achievement_id"], []).append(t)

    # Cache stat lookups per trigger_type — most achievements share a handful of counters.
    stat_cache: dict = {}

    def _progress_for(ach_id: str) -> dict | None:
        ts = triggers_by_ach.get(ach_id)
        if not ts:
            return None
        # Pick the tightest gap (lowest current/target ratio) so the UI tracks the leading edge.
        best = None
        for t in ts:
            tt = t["trigger_type"]
            if tt == "manual_admin_grant":
                continue
            target = int(t.get("trigger_threshold") or 0)
            if target <= 0:
                continue
            if tt not in stat_cache:
                try:
                    stat_cache[tt] = get_user_stat(user_id, tt)
                except Exception:
                    stat_cache[tt] = 0
            current = min(stat_cache[tt], target)
            ratio = current / target
            if best is None or ratio < best["ratio"]:
                best = {"current": current, "target": target, "ratio": ratio}
        if best is None:
            return None
        return {"current": best["current"], "target": best["target"]}

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
                entry = {
                    "id": ach["id"],
                    "name": "Secret Achievement",
                    "slug": ach["slug"],
                    "description": "Keep exploring to discover this achievement",
                    "icon": None,
                    "category": ach["category"],
                    "rarity": ach["rarity"],
                    "is_secret": True,
                    "progress": None,
                }
            else:
                entry = {**ach, "progress": _progress_for(ach["id"])}
            available.append(entry)

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


@router.get("/{user_id}/cosmetics/catalog")
def get_cosmetics_catalog(user_id: str, request: Request):
    """All cosmetics grouped by type with an `owned` flag per item."""
    require_self(user_id, request)
    all_cosmetics = table("cosmetics").select("id,type,name,slug,asset_url,css_value,rarity,unlock_source")
    owned_rows = table("user_cosmetics").select(
        "cosmetic_id",
        filters={"user_id": f"eq.{user_id}"},
    )
    owned_ids = {r["cosmetic_id"] for r in (owned_rows or [])}

    grouped: dict = {"avatar_frame": [], "banner": [], "name_color": [], "title": []}
    for c in all_cosmetics or []:
        if c.get("type") not in grouped:
            continue
        grouped[c["type"]].append({**c, "owned": c["id"] in owned_ids})
    return {"catalog": grouped}


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
