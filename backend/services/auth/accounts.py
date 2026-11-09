"""Account reads and stamps behind the auth routes (#118, moved from
``routes/auth.py``): the ``/me`` overview and the welcome / sign-in stamps."""
import logging

from db.connection import table
from services.auth.errors import AccountDeleted, AccountNotFound
from services.encryption import decrypt_if_present

logger = logging.getLogger(__name__)


def _welcome_due(user_id: str) -> bool:
    """Whether this account still needs its welcome email (`welcomed_at` NULL).

    Read-only: `welcomed_at` is stamped by `_mark_welcomed` only AFTER a `sent`
    outcome, so a welcome that was `skipped` (no RESEND_API_KEY yet) or
    `failed` is retried on a later sign-in (#763). Two concurrent first
    sign-ins can both get here; the `welcome:<user_id>` dedupe key in
    `email_sends` keeps it to one delivery. Backfilled for every account
    approved before the email system existed (migration *_email.sql), so
    existing students are never welcomed late. Best-effort: a failure
    (including the column not existing yet during a deploy) just means no
    welcome this time, never a broken sign-in.
    """
    try:
        rows = table("users").select("welcomed_at", filters={"id": f"eq.{user_id}"}, limit=1)
    except Exception:
        logger.warning("welcome check failed for %r", user_id, exc_info=True)
        return False
    return bool(rows) and not rows[0].get("welcomed_at")


def _mark_welcomed(user_id: str) -> None:
    """Stamp `welcomed_at` once the welcome has gone out. Conditional on NULL
    so the first delivery's time sticks; raises are swallowed by the caller."""
    from datetime import datetime, timezone
    table("users").update(
        {"welcomed_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{user_id}", "welcomed_at": "is.null"},
    )


def _stamp_last_sign_in_for_test(user_id: str) -> None:
    """Test seam: write last_sign_in_at to keep the callback path testable in
    isolation without round-tripping through the OAuth flow."""
    from datetime import datetime, timezone
    table("users").update(
        {"last_sign_in_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{user_id}"},
    )


def account_overview(user_id: str) -> dict:
    """Approval/onboarding state, profile basics, roles and equipped cosmetics
    for ``GET /api/auth/me``. Raises :class:`AccountNotFound` (no row) or
    :class:`AccountDeleted` (soft-deleted)."""
    user = table("users").select(
        "id,is_approved,onboarding_completed,deleted_at", filters={"id": f"eq.{user_id}"}
    )
    if not user:
        raise AccountNotFound()
    # The guard's account-state cache may be up to its TTL old; this fresh row
    # makes a deletion end the session on the very next /me.
    if user[0].get("deleted_at"):
        raise AccountDeleted()

    # Profile fields (username/name/avatar_url) moved to user_profiles in migration 0024.
    profile_rows = table("user_profiles").select(
        "username,name,avatar_url", filters={"user_id": f"eq.{user_id}"}
    )
    profile = profile_rows[0] if profile_rows else {}

    # Fetch user roles
    role_rows = table("user_roles").select(
        "granted_at,roles(id,name,slug,color,icon,description,is_staff_assigned,is_earnable,display_priority)",
        filters={"user_id": f"eq.{user_id}"},
    )
    roles = []
    is_admin = False
    if role_rows:
        for r in role_rows:
            role_data = r.get("roles", {})
            if role_data:
                roles.append({"role": role_data, "granted_at": r.get("granted_at")})
                if role_data.get("slug") == "admin":
                    is_admin = True

    # Fetch equipped cosmetics from settings
    equipped_cosmetics = {}
    settings_rows = table("user_settings").select(
        "equipped_avatar_frame_id,equipped_banner_id,equipped_name_color_id,equipped_title_id,featured_role_id",
        filters={"user_id": f"eq.{user_id}"},
    )
    if settings_rows:
        s = settings_rows[0]
        slot_map = {
            "avatar_frame": "equipped_avatar_frame_id",
            "banner": "equipped_banner_id",
            "name_color": "equipped_name_color_id",
            "title": "equipped_title_id",
        }
        for slot, col in slot_map.items():
            cid = s.get(col)
            if cid:
                cosmetic_rows = table("cosmetics").select("*", filters={"id": f"eq.{cid}"})
                if cosmetic_rows:
                    equipped_cosmetics[slot] = cosmetic_rows[0]
        frid = s.get("featured_role_id")
        if frid:
            fr_rows = table("roles").select("*", filters={"id": f"eq.{frid}"})
            if fr_rows:
                equipped_cosmetics["featured_role"] = fr_rows[0]

    return {
        "user_id": user_id,
        "is_approved": bool(user[0]["is_approved"]),
        "onboarding_completed": bool(user[0].get("onboarding_completed", False)),
        "username": profile.get("username"),
        "name": decrypt_if_present(profile.get("name")) or "",
        "avatar_url": profile.get("avatar_url") or "",
        "roles": roles,
        "equipped_cosmetics": equipped_cosmetics,
        "is_admin": is_admin,
    }
