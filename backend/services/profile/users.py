"""Identity, profile and settings rows behind the profile routes (#118, moved
from ``routes/profile.py``).

A missing or soft-deleted account raises :class:`UserNotFound`, which the
route answers as a 404.
"""
import httpx

from db.connection import table
from services.encryption import decrypt_if_present
from services.session_modes import NOT_REVIEW
from services.profile.errors import UserNotFound


# Identity columns that stay on `users` after the 0024 split.
_USERS_COLS = "id,email,streak_count,created_at"

# Profile columns live on `user_profiles` (1:1 with users). 🔒 = encrypted at rest.
_PROFILE_COLS = (
    "user_id,username,name,first_name,last_name,avatar_url,"
    "year,majors,minors,bio,location,website"
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


def _missing_users_row() -> UserNotFound:
    return UserNotFound()


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
        raise UserNotFound()
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


def _get_user_stats(user_id: str) -> dict:
    # effective_streak: a lapsed streak keeps its stored count until the next
    # activity (#767).
    from services.streak_service import effective_streak
    user = table("users").select(
        "streak_count,last_active_date", filters={"id": f"eq.{user_id}"}
    )
    streak = effective_streak(user[0] if user else None)

    sessions = table("sessions").select("id", filters={"user_id": f"eq.{user_id}", **NOT_REVIEW})
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
