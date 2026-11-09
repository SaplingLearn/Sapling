"""
Profile routes — public profiles, settings, cosmetics, achievements, account management.
"""

import base64
import functools
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile, File, Query

from services.chunk_visibility import resync_user_chunk_visibility
from services.check_item_service import retire_items_for_uploader
from services.course_context_service import refresh_course_context
from pydantic import BaseModel, Field

from config import MAX_AVATAR_SIZE
from db.connection import table
from db.scope import service_route, service_scope
from services.encryption import encrypt_if_present
from models import (
    UpdateProfileBody,
    UpdateSettingsBody,
    EquipCosmeticBody,
    SetFeaturedRoleBody,
    SetFeaturedAchievementsBody,
    DeleteAccountBody,
)
from services.analytics_consent import clear_analytics_consent_cache
from services.auth_guard import clear_account_state_cache, require_self, get_session_user_id
from services.http_cache import cached_json, conditional, make_etag
from services.posthog_client import delete_person as delete_posthog_person
from services.storage_service import upload_avatar
from services.profile import (
    UserNotFound,
    achievements_view,
    cosmetics_catalog,
    export_account_data,
    owned_cosmetics_by_type,
    public_profile,
    replace_featured_achievements,
)
from services.profile import users as _users
from services.profile.achievements import _get_featured_achievements  # noqa: F401  (re-export, #118)
from services.profile.cosmetics import _get_equipped_cosmetics
from services.profile.users import (  # noqa: F401  (re-export, #118)
    _PROFILE_COLS,
    _SETTINGS_COLS,
    _SETTINGS_ETAG_VERSION,
    _get_user_roles,
    _get_user_stats,
)

router = APIRouter()


def _user_not_found_as_404(fn):
    """``fn`` with the profile domain's :class:`UserNotFound` answered as the
    routes' long-standing ``404 {"detail": "User not found"}`` (#118)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except UserNotFound as exc:
            raise HTTPException(status_code=404, detail="User not found") from exc
    return wrapper


_get_or_create_profile = _user_not_found_as_404(_users._get_or_create_profile)
_get_or_create_settings = _user_not_found_as_404(_users._get_or_create_settings)
_live_user_or_404 = _user_not_found_as_404(_users._live_user_or_404)
_get_user_or_404 = _user_not_found_as_404(_users._get_user_or_404)
_public_profile = _user_not_found_as_404(public_profile)
_export_account_data = _user_not_found_as_404(export_account_data)
_replace_featured_achievements = _user_not_found_as_404(replace_featured_achievements)


def _optional_viewer(request: Request) -> Optional[str]:
    """The signed-in viewer's id, or None when there is no usable session.

    Only "no usable session" is anonymous: a 401 (no/invalid/expired token, or
    an account that is missing or deleted) and the 403 `not_approved` (an
    unapproved account gets the reduced anonymous view rather than an error,
    as before). Anything else propagates — above all the 503 the guard raises
    when the account state cannot be read: silently serving the anonymous view
    on a DB blip would hand a signed-in viewer a wrong page that looks right."""
    try:
        return get_session_user_id(request)
    except HTTPException as exc:
        if exc.status_code in (401, 403):
            return None
        raise


# ── Username Availability ────────────────────────────────────────────────────

_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,24}$")


# #115: unauthenticated, and answers about OTHER users' usernames -> service role.
@router.get("/username/check", dependencies=[Depends(service_route)])
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

# #115: a cross-user projection (anonymous viewers too). It reads the
# target's rows, creates their missing settings/profile rows, and applies
# profile_visibility in code below -> service role.
@router.get("/{user_id}", dependencies=[Depends(service_route)])
def get_public_profile(user_id: str, request: Request):
    # Resolve the viewer first — profiles are viewable anonymously; identity
    # only decides how much is revealed (#134). A 503 (account state
    # unreadable) propagates instead of degrading to the anonymous view.
    viewer_id = _optional_viewer(request)

    return _public_profile(user_id, viewer_id)


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
def upload_user_avatar(user_id: str, body: _AvatarUploadBody, request: Request):
    # #117: a plain `def` -- FastAPI runs it in the threadpool once, so the
    # guard's account read, the PostgREST calls and the Storage PUT below
    # never block the event loop (it awaited nothing else).
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
    etag = make_etag("settings", _SETTINGS_ETAG_VERSION, user_id, settings.get("updated_at"))
    not_modified = conditional(request, etag)
    if not_modified is not None:
        return not_modified
    return cached_json(settings, etag)


@router.patch("/{user_id}/settings")
def update_settings(
    user_id: str,
    body: UpdateSettingsBody,
    background_tasks: BackgroundTasks,
    request: Request,
):
    require_self(user_id, request)
    _get_or_create_settings(user_id)

    # Whitelist: only these fields may be patched via this endpoint.
    # bio/location/username/website live on user_profiles now (set via /profile
    # patch); role/admin/approval fields are excluded to prevent privilege escalation.
    ALLOWED = {
        "profile_visibility", "activity_status_visible",
        "notification_email", "notification_push", "notification_in_app",
        "theme", "font_size", "accent_color",
        # #72: Class Intel opt-out — persisted so the WRITE path
        # (course_context_service.update_course_context) can honor it; the
        # SharedContextToggle PATCHes it best-effort (migration 0037).
        "share_class_context",
        # ADR 0028: PostHog opt-out. Read per event through the cached
        # analytics_consent lookup, which is invalidated below.
        "analytics_opt_out",
    }
    incoming = body.model_dump(exclude_none=True)
    updates = {k: v for k, v in incoming.items() if k in ALLOWED}

    # Validate profile_visibility against its DB CHECK enum (0031 widened it to
    # include 'school'). Without this, an out-of-enum value reaches PostgREST as
    # a raw CHECK violation → unhandled 500; a clean 400 is the honest response.
    if "profile_visibility" in updates and updates["profile_visibility"] not in (
        "public",
        "school",
        "private",
    ):
        raise HTTPException(status_code=400, detail="Invalid profile_visibility")

    if updates:
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        table("user_settings").update(updates, filters={"user_id": f"eq.{user_id}"})

    # The consent cache's invalidation hook: an opt-out stops this process's
    # mirroring from the very next event (other processes: within the TTL).
    if "analytics_opt_out" in updates:
        clear_analytics_consent_cache(user_id)

    # #72 (PR #464 review): flipping the Class Intel opt-out must take effect
    # NOW, not whenever some classmate's activity next fires the aggregation.
    # Refresh every offering the user is enrolled in as a post-response task —
    # update_course_context re-reads user_settings, so the just-written value
    # is what the chokepoint filter sees, and an opted-out user's data drops
    # out of offering_concept_stats/offering_summary immediately.
    if "share_class_context" in updates:
        enrollment_rows = table("enrollments").select(
            "offering_id", filters={"user_id": f"eq.{user_id}"}
        )
        for offering_id in {r["offering_id"] for r in enrollment_rows or []}:
            background_tasks.add_task(
                refresh_course_context, offering_id, user_id=user_id)
        # #629: the aggregates above are recomputed from scratch, so dropping
        # out of them is enough. RAG rows are not — an upload that already
        # landed in the shared course pool stays there until something flips
        # it, so opting out would read as applied while the documents it was
        # meant to withdraw stayed published to the whole class.
        background_tasks.add_task(resync_user_chunk_visibility, user_id)
        # Learning loop PKG-04 (A23): items drafted from this student's shared
        # documents leave the class pool too. Deleted, so turning the toggle
        # back on restores nothing; never gated on LEARNING_LOOP_ENABLED.
        if updates["share_class_context"] is False:
            background_tasks.add_task(retire_items_for_uploader, user_id)

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

    _replace_featured_achievements(user_id, body.achievement_ids)

    return {"updated": True}


# ── Achievements ─────────────────────────────────────────────────────────────

@router.get("/{user_id}/achievements")
def get_achievements(user_id: str, request: Request):
    # `user_id` off the path is a claim, not an identity. This payload carries
    # per-user earned state and per-user progress counters (_progress_for runs
    # get_user_stat against `user_id`), so it is a self-only read like every
    # other /api/profile/{user_id}/... endpoint. The frontend only ever calls
    # it for the signed-in user.
    require_self(user_id, request)
    return achievements_view(user_id)


# ── Cosmetics ────────────────────────────────────────────────────────────────

@router.get("/{user_id}/cosmetics")
def get_cosmetics(user_id: str, request: Request):
    require_self(user_id, request)
    settings = _get_or_create_settings(user_id)

    return {"cosmetics": owned_cosmetics_by_type(user_id), "equipped": _get_equipped_cosmetics(settings)}


@router.get("/{user_id}/cosmetics/catalog")
def get_cosmetics_catalog(user_id: str, request: Request):
    """All cosmetics grouped by type with an `owned` flag per item."""
    require_self(user_id, request)
    return {"catalog": cosmetics_catalog(user_id)}


# ── Roles ────────────────────────────────────────────────────────────────────

# #115: roles of any live user, for any SIGNED-IN viewer -> service role.
# Roles reveal who is an admin, so an anonymous caller gets a 401; a
# signed-in one sees exactly what the public profile already shows them
# (its role badges), and a soft-deleted or missing user is a 404.
@router.get("/{user_id}/roles", dependencies=[Depends(service_route)])
def get_roles(user_id: str, request: Request):
    get_session_user_id(request)
    _live_user_or_404(user_id)
    return {"roles": _get_user_roles(user_id)}


# ── Delete Account ───────────────────────────────────────────────────────────

@router.delete("/{user_id}/account")
def delete_account(
    user_id: str,
    body: DeleteAccountBody,
    request: Request,
    background_tasks: BackgroundTasks,
):
    # #756: a removed (unapproved) student may still erase their account.
    require_self(user_id, request, allow_unapproved=True)

    if body.confirmation != "DELETE":
        raise HTTPException(status_code=400, detail="Confirmation must be 'DELETE'")

    # #115: the soft delete is account state (`users` is SELECT-only for the
    # student's token) -> service role.
    with service_scope():
        table("users").update(
            {"deleted_at": datetime.now(timezone.utc).isoformat()},
            filters={"id": f"eq.{user_id}"},
        )
    # ADR 0028: from here on the PostHog worker's consent check reads
    # deleted_at, so nothing — not even items already queued — names this user
    # (which would re-create the person the delete below removes). Drop the
    # cached "allowed" answer now.
    clear_analytics_consent_cache(user_id)
    # #756: the auth guard refuses a deleted account; drop its cached "active"
    # answer so this process stops honouring the session now, not at the TTL.
    clear_account_state_cache(user_id)
    # Best-effort PostHog person + event delete, AFTER the response so it adds
    # no latency and cannot fail the deletion (it never raises; unconfigured
    # -> WARN + skip). It drains our queue and the SDK's first, and repeats
    # after the consent TTL. Only reached once the soft delete landed.
    background_tasks.add_task(delete_posthog_person, user_id)
    return {"deleted": True}


# ── Data Export ──────────────────────────────────────────────────────────────

@router.post("/{user_id}/export")
def export_data(user_id: str, request: Request):
    # #756: a removed (unapproved) student may still export their data.
    require_self(user_id, request, allow_unapproved=True)

    return _export_account_data(user_id)
