"""
Profile routes — public profiles, settings, cosmetics, achievements, account management.
"""

import base64
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Query
from pydantic import BaseModel, Field

from config import MAX_AVATAR_SIZE
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
from services.http_cache import cached_json, conditional, make_etag
from services.storage_service import upload_avatar
from services.achievement_service import get_user_stat

router = APIRouter()


# Identity columns that stay on `users` after the 0024 split.
_USERS_COLS = "id,email,streak_count,created_at"

# Profile columns live on `user_profiles` (1:1 with users). 🔒 = encrypted at rest.
_PROFILE_COLS = (
    "user_id,username,name,first_name,last_name,avatar_url,"
    "year,majors,minors,bio,location,website,learning_style"
)
_PROFILE_ENCRYPTED = ("name", "first_name", "last_name", "bio", "location")


def _get_or_create_profile(user_id: str) -> dict:
    """Return the decrypted user_profiles row, creating it if missing."""
    rows = table("user_profiles").select(_PROFILE_COLS, filters={"user_id": f"eq.{user_id}"})
    if not rows:
        table("user_profiles").insert({"user_id": user_id})
        rows = table("user_profiles").select(_PROFILE_COLS, filters={"user_id": f"eq.{user_id}"})
    if not rows:
        return {"user_id": user_id}
    row = rows[0]
    for col in _PROFILE_ENCRYPTED:
        row[col] = decrypt_if_present(row.get(col))
    return row


def _get_user_or_404(user_id: str) -> dict:
    """Identity + profile merged into the legacy single-dict shape.

    `users` now holds only id/email/auth/activity; the public profile fields live
    on `user_profiles` (migration 0024). We read both and merge so callers keep the
    same flat dict they relied on before the split.
    """
    rows = table("users").select(_USERS_COLS, filters={"id": f"eq.{user_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    user = rows[0]
    user["email"] = decrypt_if_present(user.get("email"))
    profile = _get_or_create_profile(user_id)
    # Merge profile fields onto the identity row (id/email/streak/created_at win).
    merged = {**profile, **user}
    return merged


_SETTINGS_COLS = (
    "user_id,"
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
    return rows[0]


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
    # username now lives on user_profiles (keyed by user_id).
    existing = table("user_profiles").select("user_id", filters={"username": f"eq.{name}"})
    if not existing:
        return {"available": True}
    if user_id and existing[0]["user_id"] == user_id:
        return {"available": True, "reason": "self"}
    return {"available": False, "reason": "taken"}


# ── Public Profile ───────────────────────────────────────────────────────────

@router.get("/{user_id}")
def get_public_profile(user_id: str):
    user = _get_user_or_404(user_id)
    settings = _get_or_create_settings(user_id)
    roles = _get_user_roles(user_id)
    equipped = _get_equipped_cosmetics(settings)

    # Resolve school from user's enrolled courses.
    # School now lives behind enrollments.offering_id → course_offerings.course_id
    # → courses.school_id (a FK, currently unpopulated). Read through the join but
    # tolerate a missing/None school; it surfaces as None until school_id is linked.
    school = None
    enrollments = table("enrollments").select(
        "course_offerings(courses(school_id))",
        filters={"user_id": f"eq.{user_id}"},
        limit=1,
    )
    if enrollments:
        offering = enrollments[0].get("course_offerings") or {}
        course = offering.get("courses") or {} if isinstance(offering, dict) else {}
        if isinstance(course, dict) and course.get("school_id"):
            school = course["school_id"]

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

    # All of these fields now live on user_profiles (migration 0024) — one source of truth.
    updates_profile = {}

    if body.username is not None:
        # Check uniqueness against user_profiles.
        existing = table("user_profiles").select(
            "user_id", filters={"username": f"eq.{body.username}"}
        )
        if existing and existing[0]["user_id"] != user_id:
            raise HTTPException(status_code=409, detail="Username already taken")
        updates_profile["username"] = body.username

    if body.bio is not None:
        updates_profile["bio"] = encrypt_if_present(body.bio)
    if body.location is not None:
        updates_profile["location"] = encrypt_if_present(body.location)
    if body.website is not None:
        updates_profile["website"] = body.website

    if updates_profile:
        _get_or_create_profile(user_id)  # ensure a row exists to update
        table("user_profiles").update(updates_profile, filters={"user_id": f"eq.{user_id}"})

    return {"updated": True}


# ── Avatar Upload ────────────────────────────────────────────────────────────


class _AvatarUploadBody(BaseModel):
    """JSON body for the avatar upload endpoint.

    Multipart uploads with cookies were silently failing in some
    browser/extension/network configurations with `TypeError: Failed
    to fetch` (no response, request aborted before reaching the
    server). The route now accepts a base64-encoded body over JSON,
    which works in every environment that already runs the JSON
    profile-PATCH endpoint successfully.
    """

    # 10M base64 chars upper-bounds the body before any decode work.
    # Base64 expands binary by 4/3, so 10M chars decodes to ~7.5 MB
    # binary — comfortably above MAX_AVATAR_SIZE (5 MB) and below any
    # sensible JSON body limit. The actual binary cap is enforced
    # below after decoding.
    file_b64: str = Field(..., max_length=10_000_000)
    content_type: str = Field(default="image/png", max_length=64)


@router.post("/{user_id}/avatar")
async def upload_user_avatar(user_id: str, body: _AvatarUploadBody, request: Request):
    require_self(user_id, request)
    _get_user_or_404(user_id)

    # `file_b64` may arrive as a bare base64 string OR as a data URL
    # (`data:image/png;base64,...`) depending on how the client encoded
    # it. Strip the data-URL prefix if present.
    raw = body.file_b64
    if raw.startswith("data:"):
        comma = raw.find(",")
        if comma == -1:
            raise HTTPException(status_code=400, detail="Invalid data URL")
        raw = raw[comma + 1 :]

    try:
        file_bytes = base64.b64decode(raw, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 payload")

    # Enforce the binary size cap at the route layer so the 413 is
    # immediate and the response shape matches the multipart endpoint
    # the caller might still expect (per `services/storage_service.py
    # ::_validate_upload`). Without this, the cap fires one layer
    # deeper inside upload_avatar, which is correct but harder to
    # reason about from a route-test perspective.
    if len(file_bytes) > MAX_AVATAR_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_AVATAR_SIZE // (1024 * 1024)} MB",
        )

    avatar_url = upload_avatar(user_id, file_bytes, body.content_type)

    # avatar_url moved to user_profiles in migration 0024.
    _get_or_create_profile(user_id)  # ensure a row exists to update
    table("user_profiles").update(
        {"avatar_url": avatar_url}, filters={"user_id": f"eq.{user_id}"}
    )
    return {"avatar_url": avatar_url}


# ── Settings ─────────────────────────────────────────────────────────────────

@router.get("/{user_id}/settings")
def get_settings(user_id: str, request: Request):
    require_self(user_id, request)
    settings = _get_or_create_settings(user_id)
    # user_settings.updated_at is bumped on every patch → a clean single-source
    # ETag. A matching If-None-Match returns 304 without re-serializing.
    etag = make_etag("settings", user_id, settings.get("updated_at"))
    not_modified = conditional(request, etag)
    if not_modified is not None:
        return not_modified
    return cached_json(settings, etag)


@router.patch("/{user_id}/settings")
def update_settings(user_id: str, body: UpdateSettingsBody, request: Request):
    require_self(user_id, request)
    _get_or_create_settings(user_id)

    # Whitelist: only these fields may be patched via this endpoint.
    # bio/location/username/website live on user_profiles now (set via /profile
    # patch); role/admin/approval fields are excluded to prevent privilege escalation.
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

    return _get_or_create_settings(user_id)


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
