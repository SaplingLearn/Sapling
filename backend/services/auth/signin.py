"""The account side of a Google sign-in (#118, moved from ``routes/auth.py``):
the email-domain policy and the users / profile / OAuth-token / waitlist
writes the OAuth callback makes once Google has vouched for the student."""
import logging
from dataclasses import dataclass

from config import ALLOWED_EMAIL_DOMAINS, AUTH_SCOPES, STORAGE_BUCKET
from db.connection import table
from services import email_service
from services.auth.accounts import _mark_welcomed, _welcome_due
from services.auth.oauth_state import covers_calendar, granted_scopes
from services.auth.waitlist import _mark_waitlist_joined, _waitlist_entry
from services.encryption import decrypt_if_present, encrypt, encrypt_if_present

logger = logging.getLogger(__name__)


def _email_domain_allowed(email: str) -> bool:
    """Whether `email`'s domain is permitted to sign in.

    Controlled by config.ALLOWED_EMAIL_DOMAINS (default ["bu.edu"]). An empty
    allowlist permits any domain — used on staging, which is already gated by
    Cloudflare Access.
    """
    if not ALLOWED_EMAIL_DOMAINS:
        return True
    domain = email.strip().lower().rsplit("@", 1)[-1]
    return domain in ALLOWED_EMAIL_DOMAINS


def fetch_google_userinfo(access_token: str) -> dict | None:
    """Google's userinfo for the signed-in account, or None on any failure."""
    # Fetch user info from Google. Uses httpx (the codebase's sanctioned HTTP
    # client) instead of googleapiclient/httplib2 — httplib2 ignores
    # HTTPS_PROXY, which 500s on dev machines and proxy-bound deployments.
    import httpx
    try:
        resp = httpx.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        user_info = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(user_info, dict):
        return None
    return user_info


@dataclass(frozen=True)
class SignInResult:
    """What :func:`record_google_sign_in` decided.

    ``outcome``: ``account_deleted`` (refused, nothing written),
    ``not_approved`` (no session; ``user_id`` is None when no account exists
    or was created) or ``approved``.
    """

    outcome: str
    user_id: str | None = None


_NAME_COLS = ("name", "first_name", "last_name")

#: Where a student's own uploaded avatar lives (services/storage_service.py).
_UPLOADED_AVATAR_MARK = f"/storage/v1/object/public/{STORAGE_BUCKET}/"


def _has_name(row: dict) -> bool:
    # Decrypted, because an empty name is still a ciphertext (of "").
    return any((decrypt_if_present(row.get(c)) or "").strip() for c in _NAME_COLS)


def _refresh_profile(
    user_id: str, *, name: str, first_name: str, last_name: str, avatar_url: str,
) -> None:
    """Bring the profile up to date with Google without taking anything the
    student chose.

    The name is the student's once the profile has one: onboarding asks for
    it (a preferred name, often not Google's), and rewriting it from Google on
    every sign-in undid that choice. A profile with no name yet — a new
    account, or a stub that never reached onboarding (#285) — still starts
    from the Google name. The avatar refreshes from Google, except over one
    the student uploaded themselves, and never to a blank.
    """
    google_name = {
        "name": encrypt_if_present(name),
        "first_name": encrypt_if_present(first_name),
        "last_name": encrypt_if_present(last_name),
    }
    cols = "name,first_name,last_name,avatar_url"
    by_user = {"user_id": f"eq.{user_id}"}
    rows = table("user_profiles").select(cols, filters=by_user, limit=1)
    if not rows:
        # user_profiles.user_id is the PK (0024). DO NOTHING on conflict: a
        # row that appeared since the read (onboarding in another tab) is
        # the student's and is handled below like any existing one.
        created = table("user_profiles").upsert(
            {"user_id": user_id, **google_name, "avatar_url": avatar_url},
            on_conflict="user_id",
            ignore_duplicates=True,
        )
        if created:
            return
        rows = table("user_profiles").select(cols, filters=by_user, limit=1)
        if not rows:
            return
    current = rows[0]
    patch: dict = {}
    if avatar_url and _UPLOADED_AVATAR_MARK not in (current.get("avatar_url") or ""):
        patch["avatar_url"] = avatar_url
    filters = dict(by_user)
    if not _has_name(current):
        patch.update(google_name)
        # Compare-and-set on the stored name: one written since the read
        # above is the student's, and this update then matches no row.
        stored = current.get("name")
        filters["name"] = "is.null" if stored is None else f"eq.{stored}"
    if patch:
        table("user_profiles").update(patch, filters=filters)


def _store_calendar_tokens(user_id: str, creds) -> None:
    """Refresh the stored calendar tokens from this sign-in's grant.

    Called only for a grant that covers the calendar scopes: sign-in asks for
    identity alone, plus (include_granted_scopes) whatever the student
    granted before, so this is a student who connected the calendar. An
    identity-only grant is never stored: it would replace a working calendar
    token with one that cannot reach the calendar, and make
    `GET /api/calendar/status` report a calendar that is not connected.
    A grant without a refresh token keeps the stored one."""
    row = {
        "user_id": user_id,
        "access_token": encrypt(creds.token),
        # expires_at is TIMESTAMPTZ after migration 0024 — None (not "") when
        # there is no expiry, since "" is not a valid timestamptz.
        "expires_at": creds.expiry.isoformat() if creds.expiry else None,
    }
    if creds.refresh_token:
        row["refresh_token"] = encrypt(creds.refresh_token)
    table("oauth_tokens").upsert(row, on_conflict="user_id")


def record_google_sign_in(
    *,
    email: str,
    google_id: str,
    name: str,
    first_name: str,
    last_name: str,
    avatar_url: str,
    creds,
    local_auto_approve: bool,
) -> SignInResult:
    """Create or refresh the account behind a Google sign-in and decide
    whether it gets in. ``creds`` are the Google OAuth credentials."""
    # Profile fields (name/first_name/last_name/avatar_url) live on user_profiles
    # after migration 0024; `users` keeps identity + auth + activity only.
    profile = {
        "name": name, "first_name": first_name, "last_name": last_name,
        "avatar_url": avatar_url,
    }

    # Determine user_id: check if this Google ID already exists
    existing = table("users").select(
        "id,is_approved,deleted_at", filters={"google_id": f"eq.{google_id}"}
    )
    # #756: a deleted account stays deleted. Refused before anything is written
    # (sign-in time, profile, OAuth tokens, waitlist) — there is no silent
    # un-delete, and the guard would 401 a session minted for it anyway.
    if existing and existing[0].get("deleted_at"):
        logger.info("sign-in refused for deleted account %s", existing[0]["id"])
        return SignInResult("account_deleted")
    # The waitlist decides whether someone new gets an account at all: an admin
    # approving their email under Admin → Allowlist is the yes. Without it
    # nothing is stored for them (no users row, profile or OAuth tokens), and
    # /pending offers to put them on the waitlist instead.
    waitlist = _waitlist_entry(email)
    waitlist_approved = bool(waitlist and waitlist.get("approved_at"))
    if not existing and not (local_auto_approve or waitlist_approved):
        return SignInResult("not_approved")
    if existing:
        user_id = existing[0]["id"]
        is_approved = existing[0]["is_approved"]
        # Update auth fields on users; refresh profile fields on user_profiles.
        from datetime import datetime as _dt, timezone as _tz
        table("users").update(
            {
                "email": encrypt_if_present(email),
                "last_sign_in_at": _dt.now(_tz.utc).isoformat(),
            },
            filters={"id": f"eq.{user_id}"},
        )
        _refresh_profile(user_id, **profile)
    else:
        # Email-based account merge is disabled because emails are now encrypted
        # with random nonces; equality lookups by plaintext email cannot match.
        # New sign-ins for users without a google_id always create a fresh row.
        user_id = f"user_{google_id}"
        is_approved = True  # local dev, or approved on the waitlist (checked above)
        from datetime import datetime as _dt, timezone as _tz
        # Upsert, not insert (#285). `user_id` is deterministic, so a *stub* row
        # can already occupy this id: `graph_service.ensure_user_exists` inserts
        # {id, streak_count} with a NULL google_id for any authenticated request,
        # and the HMAC-signed `sapling_session` cookie outlives a row delete — so
        # a stale tab can create one for an account that no longer exists. The
        # lookup above is by google_id, which NULL never matches, so we land here
        # and a blind INSERT collided on users_pkey -> 409 -> unhandled -> a
        # permanent sign-in 500 loop.
        #
        # on_conflict MUST be the primary key: `google_id` is UNIQUE and would be
        # valid PostgREST, but the stub's google_id is NULL and NULLs never
        # conflict, so it would not resolve this. merge-duplicates fills the
        # stub's NULL auth columns in, promoting it to a real user.
        table("users").upsert({
            "id": user_id,
            "email": encrypt_if_present(email),
            "google_id": google_id,
            "auth_provider": "google",
            "is_approved": is_approved,
            "last_sign_in_at": _dt.now(_tz.utc).isoformat(),
        }, on_conflict="id")
        # Same hazard: user_profiles.user_id is the PK (0024), and a stub that
        # reached onboarding already has a row here (onboarding.py upserts it),
        # holding the name the student chose there.
        _refresh_profile(user_id, **profile)

    # Calendar tokens: only from a grant that can reach the calendar (a
    # student who connected it; see _store_calendar_tokens). An identity-only
    # sign-in leaves `oauth_tokens` alone.
    if covers_calendar(granted_scopes(creds, AUTH_SCOPES)):
        _store_calendar_tokens(user_id, creds)

    # Local dev bypass (#364): auto-approve so a real Google sign-in doesn't hit the
    # /pending wall. Strictly gated on APP_ENV=="local" — staging/prod AND the test
    # suite (APP_ENV=test) keep the real #285 approval gate and this can never approve
    # a user there. Persisted to the DB row so /api/auth/me and the frontend see the
    # approved state, not just this request.
    if local_auto_approve and not is_approved:
        is_approved = True
        table("users").update({"is_approved": True}, filters={"id": f"eq.{user_id}"})

    # An existing account that isn't approved (its access was removed under
    # Admin → Users, or it predates unapproved sign-ins no longer creating one)
    # is let back in once its email is approved on the waitlist. Revoking the
    # waitlist entry later (Admin → Allowlist → revoke, #757) removes it again:
    # that sets `users.is_approved = false` on the account its
    # `joined_user_id` links to, and the auth guard then refuses the session.
    if not is_approved and waitlist_approved:
        is_approved = True
        table("users").update({"is_approved": True}, filters={"id": f"eq.{user_id}"})
        logger.info("user %s approved via waitlist at sign-in", user_id)
    # Waitlist → joined, shown in Admin → Allowlist. Users' emails are encrypted
    # with per-call nonces, so this sign-in (plaintext email from Google in
    # hand) is the only place the two can be matched.
    if is_approved and waitlist and not waitlist.get("joined_at"):
        _mark_waitlist_joined(waitlist["id"], user_id)

    if not is_approved:
        return SignInResult("not_approved", user_id)
    return SignInResult("approved", user_id)


def welcome_and_achievements_after_sign_in(
    user_id: str, *, email: str, welcome_first_name: str | None, background_tasks,
) -> None:
    """The approved sign-in's follow-ups: queue the welcome email when it is
    due (``background_tasks`` runs the send after the redirect) and run the
    first-login achievement check."""
    # Welcome email, once per account, on the first sign-in that gets in (or a
    # later one, if that send was skipped or failed). The send runs after the
    # redirect is returned and stamps welcomed_at only once it is `sent`.
    if _welcome_due(user_id):
        email_service.queue_welcome(
            background_tasks,
            email=email,
            user_id=user_id,
            first_name=welcome_first_name,
            on_sent=lambda: _mark_welcomed(user_id),
        )

    # First-login achievement (F7). The login-streak achievements ("First Steps"
    # and friends) were only ever evaluated at study-session end (learn.py), so a
    # user who signs in but hasn't just finished a session sat at 100% progress
    # yet stayed LOCKED forever — unlike Document Collector, whose upload path
    # fires its own check. Fire the same grant check here on every approved
    # sign-in. `check_achievements` dedups against user_achievements (and the
    # (user_id, achievement_id) PK backstops it), so it awards at most once and is
    # safe to call on every login. Best-effort: a grant failure must never break
    # sign-in.
    try:
        from services.achievement_service import check_achievements
        check_achievements(user_id, "login_streak", {})
    except Exception:
        logger.warning(
            "sign-in achievement check failed for %r", user_id, exc_info=True
        )
