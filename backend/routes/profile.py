"""
Profile routes — public profiles, settings, cosmetics, achievements, account management.
"""

import base64
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile, File, Query

from services.chunk_visibility import resync_user_chunk_visibility
from services.course_context_service import refresh_course_context
from pydantic import BaseModel, Field

from config import MAX_AVATAR_SIZE
from db.connection import table
from db.scope import service_route, service_scope
from services.encryption import encrypt_if_present, decrypt_if_present
from models import (
    UpdateProfileBody,
    UpdateSettingsBody,
    EquipCosmeticBody,
    SetFeaturedRoleBody,
    SetFeaturedAchievementsBody,
    DeleteAccountBody,
)
from services.academics import school_peer_user_ids
from services.analytics_consent import clear_analytics_consent_cache
from services.auth_guard import clear_account_state_cache, require_self, get_session_user_id, guard_off_loop
from services.http_cache import cached_json, conditional, make_etag
from services.posthog_client import delete_person as delete_posthog_person
from services.storage_service import upload_avatar
from services.achievement_service import LOWER_IS_BETTER, get_user_stat

router = APIRouter()


# Identity columns that stay on `users` after the 0024 split.
_USERS_COLS = "id,email,streak_count,created_at"

# Profile columns live on `user_profiles` (1:1 with users). 🔒 = encrypted at rest.
_PROFILE_COLS = (
    "user_id,username,name,first_name,last_name,avatar_url,"
    "year,majors,minors,bio,location,website,learning_style"
)
_PROFILE_ENCRYPTED = ("name", "first_name", "last_name", "bio", "location")


# Postgres foreign_key_violation. PostgREST answers it with a 409, the same
# status as the unique/PK conflict ON CONFLICT DO NOTHING absorbs, so only
# the body's SQLSTATE tells the two apart.
_FK_VIOLATION = "23503"


def _is_fk_violation(exc: httpx.HTTPStatusError) -> bool:
    if exc.response.status_code != 409:
        return False
    try:
        body = exc.response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("code") == _FK_VIOLATION


def _missing_users_row() -> HTTPException:
    return HTTPException(status_code=404, detail="User not found")


def _get_or_create_row(name: str, columns: str, user_id: str) -> dict:
    """Read the 1:1 `user_id`-keyed row of `name`, creating it if missing.

    Race-safe (#674): Settings.tsx loads /settings and the public profile in
    parallel, both land here for a first-time user, and a blind INSERT from
    the loser 409s into a 500. ON CONFLICT DO NOTHING, not a merge, whose
    DO UPDATE would fire the updated_at trigger and move the winner's ETag.

    The upsert's own representation is the row when this call inserted it;
    only a lost race (DO NOTHING returns `[]`) needs a second read.

    Both tables FK to `users` with ON DELETE CASCADE. A session whose `users`
    row is missing (hard-deleted, e.g. a cookie that outlived a manually
    removed row, the #285 class) violates that FK, which DO NOTHING does not
    absorb. That is a 404 like every other missing-user path here
    (`_get_user_or_404`, `/api/auth/me`), not a 500. The same holds when the
    re-read after a lost race finds nothing: the row existed a moment ago, so
    it vanished, which a cascade from a hard-deleted `users` row explains.
    Serving a made-up `{"user_id": ...}` there would be a 200 with a fixed
    ETag for a row that does not exist.

    The app's own account deletion is a SOFT delete (`users.deleted_at`); a
    soft-deleted user still has the row, so none of this fires for them.
    """
    filters = {"user_id": f"eq.{user_id}"}
    rows = table(name).select(columns, filters=filters)
    if rows:
        return rows[0]
    try:
        rows = table(name).upsert(
            {"user_id": user_id},
            on_conflict="user_id",
            ignore_duplicates=True,
            columns=columns,
        )
    except httpx.HTTPStatusError as exc:
        if _is_fk_violation(exc):
            raise _missing_users_row() from exc
        raise
    if rows:
        return rows[0]
    rows = table(name).select(columns, filters=filters)
    if not rows:
        raise _missing_users_row()
    return rows[0]


def _get_or_create_profile(user_id: str) -> dict:
    """Return the decrypted user_profiles row, creating it if missing."""
    row = _get_or_create_row("user_profiles", _PROFILE_COLS, user_id)
    for col in _PROFILE_ENCRYPTED:
        row[col] = decrypt_if_present(row.get(col))
    return row


def _live_user_or_404(user_id: str, cols: str = "id") -> dict:
    """The `users` row (`cols`) of a LIVE account, or a 404.

    A soft-deleted account (`users.deleted_at`) is a 404 exactly like a missing
    one (#115): nothing public about it may outlive the deletion. The one
    check behind both the public profile and `GET /{user_id}/roles`."""
    rows = table("users").select(
        cols, filters={"id": f"eq.{user_id}", "deleted_at": "is.null"}
    )
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    return rows[0]


def _get_user_or_404(user_id: str) -> dict:
    """Identity + profile merged into the legacy single-dict shape.

    `users` now holds only id/email/auth/activity; the public profile fields live
    on `user_profiles` (migration 0024). We read both and merge so callers keep the
    same flat dict they relied on before the split.

    A soft-deleted account is a 404 (`_live_user_or_404`). For the public read
    that is the whole fix. The other callers are behind `require_self`, whose
    account-state check refuses a deleted account's session — but that state is
    cached per worker for `auth_guard.ACCOUNT_STATE_TTL_SECONDS` (30 s), and only
    the worker that ran the delete clears its entry, so for up to that window a
    deleted session can still reach them; this filter is what turns those into
    a 404 too (and keeps the profile/settings rows from being re-created).
    """
    user = dict(_live_user_or_404(user_id, _USERS_COLS))
    user["email"] = decrypt_if_present(user.get("email"))
    profile = _get_or_create_profile(user_id)
    # Merge profile fields onto the identity row (id/email/streak/created_at win).
    merged = {**profile, **user}
    return merged


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


_SETTINGS_COLS = (
    "user_id,"
    "profile_visibility,activity_status_visible,"
    "notification_email,notification_push,notification_in_app,"
    "theme,font_size,accent_color,share_class_context,analytics_opt_out,"
    "equipped_avatar_frame_id,equipped_banner_id,equipped_name_color_id,equipped_title_id,"
    "featured_role_id,featured_achievement_ids,updated_at"
)

#: Folded into the GET /settings ETag; bump it whenever the body's SHAPE
#: changes (here: analytics_opt_out joined _SETTINGS_COLS, ADR 0028). An
#: unchanged tag over a changed shape would 304 a browser's pre-deploy cached
#: body — without the new field — for as long as the row's updated_at holds.
_SETTINGS_ETAG_VERSION = "2"


def _get_or_create_settings(user_id: str) -> dict:
    return _get_or_create_row("user_settings", _SETTINGS_COLS, user_id)


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


def _strip_role_cosmetics(equipped: dict) -> dict:
    """`equipped` minus anything that reveals a role, for anonymous viewers
    (#115): the featured role itself, and every equipped cosmetic a role grants
    (`role_cosmetics`). Conservative: a cosmetic granted by ANY role goes, staff
    or earnable, since the slot alone cannot say which."""
    out = {k: v for k, v in equipped.items() if k != "featured_role"}
    ids = [c["id"] for c in out.values() if isinstance(c, dict) and c.get("id")]
    if not ids:
        return out
    granted = {
        r["cosmetic_id"]
        for r in table("role_cosmetics").select(
            "cosmetic_id", filters={"cosmetic_id": f"in.({','.join(ids)})"}
        ) or []
    }
    return {k: v for k, v in out.items() if v.get("id") not in granted}


def _get_featured_achievements(user_id: str) -> list:
    # `achievements!inner(...)` + the `achievements.status` filter is the
    # embed-side equivalent of the `status = live` filter every top-level
    # achievements read carries. Without the !inner the filter can't apply to
    # the embedded table at all, and a badge the wiki has since unpublished
    # (or one of the ten legacy seeds 0044 demotes to draft) stays pinned on
    # the showcase — visible to other users, while absent from the grid and
    # the "N of M" count. This showcase is served by GET /api/profile/{id},
    # which other users can read subject to visibility, so a draft leaking
    # here leaks work-in-progress off-team.
    rows = table("user_achievements").select(
        "earned_at,is_featured,"
        "achievements!inner(id,name,slug,description,icon,category,rarity,"
        "is_secret,xp_reward,icon_url,sort_order,status)",
        filters={
            "user_id": f"eq.{user_id}",
            "is_featured": "eq.true",
            "achievements.status": "eq.live",
        },
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
    # effective_streak: a lapsed streak keeps its stored count until the next
    # activity (#767).
    from services.streak_service import effective_streak
    user = table("users").select(
        "streak_count,last_active_date", filters={"id": f"eq.{user_id}"}
    )
    streak = effective_streak(user[0] if user else None)

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

    user = _get_user_or_404(user_id)
    settings = _get_or_create_settings(user_id)
    # Roles say who is staff/admin (#115): signed-in viewers only, the same
    # audience as GET /{user_id}/roles. The app renders profiles only behind
    # sign-in (frontend middleware), so anonymous gets [] — and skips the read.
    roles = _get_user_roles(user_id) if viewer_id is not None else []
    equipped = _get_equipped_cosmetics(settings)
    if viewer_id is None:
        # ...nor through the cosmetics: the featured role IS a role, and a
        # role-granted cosmetic (role_cosmetics, e.g. a staff title) names it.
        equipped = _strip_role_cosmetics(equipped)

    is_owner = viewer_id is not None and viewer_id == user_id

    # Effective visibility. The owner always sees everything. 'school' (0031)
    # reveals the extended profile only to viewers sharing a school with the
    # owner — resolved through services/academics.py, the same boundary the
    # #342 school directory uses — and otherwise behaves as 'private'.
    # Fail-closed: anonymous viewer / no shared school → private.
    visibility = settings.get("profile_visibility") or "public"
    if not is_owner and visibility == "school":
        same_school = (
            viewer_id is not None and viewer_id in school_peer_user_ids(user_id)
        )
        visibility = "public" if same_school else "private"

    profile = {
        "id": user["id"],
        "username": user.get("username"),
        "avatar_url": user.get("avatar_url"),
        "created_at": user.get("created_at"),
        "roles": roles,
        "equipped_cosmetics": equipped,
    }

    if not is_owner and visibility == "private":
        # Minimal stub: identity-adjacent decoration only. name/year/majors/
        # minors/school are personal data and stay hidden alongside
        # bio/location/website/featured/stats (#134). Keys are kept (nulled)
        # so the frontend's response shape is unchanged.
        profile.update({
            "name": "",
            "year": None,
            "majors": [],
            "minors": [],
            "school": None,
            "bio": None,
            "location": None,
            "website": None,
            "featured_achievements": [],
            "stats": {},
        })
        return profile

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

    profile.update({
        "name": user.get("name", ""),
        "year": user.get("year"),
        "majors": user.get("majors") or [],
        "minors": user.get("minors") or [],
        "school": school,
        "bio": user.get("bio"),
        "location": user.get("location"),
        "website": user.get("website"),
        "featured_achievements": _get_featured_achievements(user_id),
        "stats": _get_user_stats(user_id),
    })
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
    await guard_off_loop(require_self, user_id, request)
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
def get_achievements(user_id: str, request: Request):
    # `user_id` off the path is a claim, not an identity. This payload carries
    # per-user earned state and per-user progress counters (_progress_for runs
    # get_user_stat against `user_id`), so it is a self-only read like every
    # other /api/profile/{user_id}/... endpoint. The frontend only ever calls
    # it for the signed-in user.
    require_self(user_id, request)
    # The select must carry every field frontend/src/lib/types.ts::Achievement
    # declares required — the response is cast, never validated, so a missing
    # column surfaces as `+undefined XP` and, worse, `iconUrl={undefined}`,
    # which makes every admin-uploaded icon invisible to users (the admin wiki
    # reads a different endpoint that selects `*`, so admins never see it).
    all_achs = table("achievements").select(
        "id,name,slug,description,icon,category,rarity,is_secret,"
        "xp_reward,icon_url,sort_order,status",
        filters={"status": "eq.live"},
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
            # LOWER_IS_BETTER stats (session_before_hour) count DOWN to their
            # threshold — it's a wall-clock hour, not a target to accumulate
            # towards. "5 of 7" would be nonsense, and the `min(stat, target)`
            # clamp below would render the unearned badge as 100% complete.
            # These badges are pass/fail, so they carry no progress bar.
            if tt in LOWER_IS_BETTER:
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
                # Hand-built rather than a row spread so the masked entry can
                # never leak the real name/description/icon. It still has to
                # carry every field the Achievement type declares required —
                # xp_reward is the honest reward (the UI shows what it pays,
                # which is not a spoiler), icon_url is nulled alongside icon.
                entry = {
                    "id": ach["id"],
                    "name": "Secret Achievement",
                    "slug": ach["slug"],
                    "description": "Keep exploring to discover this achievement",
                    "icon": None,
                    "icon_url": None,
                    "category": ach["category"],
                    "rarity": ach["rarity"],
                    "is_secret": True,
                    "xp_reward": ach.get("xp_reward") or 0,
                    "sort_order": ach.get("sort_order") or 0,
                    "status": ach.get("status") or "live",
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

    user = _get_user_or_404(user_id)
    settings = _get_or_create_settings(user_id)
    roles = _get_user_roles(user_id)

    # Deliberately NOT filtered to status = live, unlike the showcase and the
    # badge grid: this is the user's own data export of what they actually
    # earned. If a badge they hold was later unpublished, omitting it here
    # would make the export a lie about their own history.
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
