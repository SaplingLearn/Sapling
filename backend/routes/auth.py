"""
backend/routes/auth.py

Google OAuth sign-in with unified calendar access.
Restricts sign-in to @bu.edu email accounts only.
"""

import json
import base64
import hashlib
import hmac as _hmac
import logging
import os
import re
import secrets
import time as _time
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, ValidationError

# The module (not just its constants) so request-time gates can read the LIVE
# value of APP_ENV / SECURE_COOKIES / SESSION_SECRET instead of an import-time
# snapshot. See _test_auth_enabled below.
import config
from config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_AUTH_REDIRECT_URI,
    AUTH_SCOPES,
    FRONTEND_URL,
    SESSION_SECRET,
    SECURE_COOKIES,
    IS_LOCAL,
    APP_ENV,
    ALLOWED_EMAIL_DOMAINS,
)
from db.connection import table
from services.encryption import encrypt, encrypt_if_present, decrypt_if_present
from services.auth_guard import get_session_user_id
from services.session_tokens import SESSION_COOKIE_NAME, mint_session

try:
    from google_auth_oauthlib.flow import Flow
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleAuthRequest
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

logger = logging.getLogger(__name__)

router = APIRouter()

# Local-dev auto-approve fires ONLY for real local dev, NOT APP_ENV=test (which must
# keep the #285 approval gate). So gate on APP_ENV=="local", not the broader IS_LOCAL.
_LOCAL_AUTO_APPROVE = APP_ENV == "local"

# ── Test-only session minting (#381) ──────────────────────────────────────────
# The APP_ENVs in which POST /api/auth/test-login exists at all.
#
# DELIBERATELY NARROWER than config.IS_LOCAL ({local, development, dev, test}).
# This endpoint mints a valid session for an ARBITRARY user id with no credential
# whatsoever, so its blast radius is "full account takeover of every account" if
# it is ever reachable. `development`/`dev` are plausible values for a real
# shared deploy's APP_ENV, and IS_LOCAL is used for unrelated, far less dangerous
# relaxations (unsigned OAuth-state fallback, SESSION_SECRET strength check), so
# widening later by reusing IS_LOCAL would silently arm this too. `local` is the
# developer's own machine and `test` is the pytest/CI harness; nothing else.
TEST_AUTH_ENVS = frozenset({"local", "test"})

TEST_LOGIN_DEFAULT_TTL_SECONDS = 3600
TEST_LOGIN_MAX_TTL_SECONDS = 86400


def _test_auth_enabled() -> bool:
    """Whether POST /api/auth/test-login is available in this environment.

    Evaluated per REQUEST off the live `config` module attribute — never captured
    at import time. That makes the gate monkeypatchable (so the 404-under-
    production behaviour is actually testable) and means no import-ordering
    accident can freeze it in the open position.
    """
    return (getattr(config, "APP_ENV", "") or "").strip().lower() in TEST_AUTH_ENVS


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


def _stamp_last_sign_in_for_test(user_id: str) -> None:
    """Test seam: write last_sign_in_at to keep the callback path testable in
    isolation without round-tripping through the OAuth flow."""
    from datetime import datetime, timezone
    table("users").update(
        {"last_sign_in_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{user_id}"},
    )


OAUTH_STATE_COOKIE = "sapling_oauth_state"
_OAUTH_COOKIE_MAX_AGE = 600
_POPUP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# TTL of the one-shot HMAC token handed to the frontend on the OAuth-callback
# redirect. This is NOT the session lifetime (#168): the frontend session BFF
# (frontend/src/app/api/auth/session) verifies this token once and re-mints a
# long-lived `sapling_session` cookie (SESSION_MAX_AGE = 30 days) in the same
# backend-compatible HMAC format, which `auth_guard._decode_session` accepts.
# So this token only needs to outlive the redirect round-trip. Configurable for
# environments with slow OAuth hops. See docs/decisions/0018-session-token-lifecycle.md.
_DEFAULT_REDIRECT_TOKEN_TTL_SECONDS = 300


def _clamp_redirect_ttl(seconds: int) -> int:
    """Clamp the redirect-handoff token TTL to [30, 600]s.

    This one-shot token travels in the OAuth-callback URL, so a misconfigured
    override must not be able to turn it into a long-lived credential — it is
    NOT the session (see docs/decisions/0018-session-token-lifecycle.md). The
    floor keeps slow OAuth hops working; the ceiling keeps the handoff short.
    """
    return max(30, min(seconds, 600))


def _parse_redirect_ttl(raw: str | None) -> int:
    """Parse the SAPLING_AUTH_REDIRECT_TOKEN_TTL override into a clamped TTL.

    A non-numeric or empty override (e.g. the var declared in Railway/Wrangler
    with no value) must not take the whole app down: this module is imported at
    router-mount time, so an unguarded int() would raise ValueError and stop the
    app from booting. Fall back to the default and warn instead.
    """
    if raw is None:
        return _DEFAULT_REDIRECT_TOKEN_TTL_SECONDS
    try:
        return _clamp_redirect_ttl(int(raw))
    except ValueError:
        logger.warning(
            "Ignoring malformed SAPLING_AUTH_REDIRECT_TOKEN_TTL=%r (expected an "
            "integer number of seconds); falling back to %ss.",
            raw,
            _DEFAULT_REDIRECT_TOKEN_TTL_SECONDS,
        )
        return _DEFAULT_REDIRECT_TOKEN_TTL_SECONDS


_REDIRECT_TOKEN_TTL_SECONDS = _parse_redirect_ttl(
    os.getenv("SAPLING_AUTH_REDIRECT_TOKEN_TTL")
)

# Fallback in-memory store for environments without SESSION_SECRET; entries
# are keyed by nonce and expire after _OAUTH_COOKIE_MAX_AGE seconds.
_OAUTH_FALLBACK_STORE: dict[str, tuple[float, dict]] = {}


def _google_client_config() -> dict:
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uris": [GOOGLE_AUTH_REDIRECT_URI],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def _encode_state(data: dict) -> str:
    payload = json.dumps(data)
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_state(state: str) -> dict:
    try:
        payload = base64.urlsafe_b64decode(state.encode()).decode()
        return json.loads(payload)
    except Exception:
        return {}


def _generate_pkce_pair():
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode()
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode()
    return code_verifier, code_challenge


def _clean_popup_id(s: str | None) -> str | None:
    if not s:
        return None
    return s if _POPUP_ID_RE.match(s) else None


def _encode_oauth_cookie(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    payload_b64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    if SESSION_SECRET:
        sig_bytes = _hmac.new(SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")
        return f"{payload_b64}.{sig_b64}"
    # #174: the unsigned in-memory fallback is local-dev only. Outside local it
    # is a silent, insecure degradation (unsigned OAuth state) — fail closed.
    # (validate_config already blocks startup without SESSION_SECRET in prod;
    # this is defense in depth at the use site.)
    if not IS_LOCAL:
        raise RuntimeError(
            "SESSION_SECRET is required outside local dev; refusing to issue "
            "unsigned OAuth state."
        )
    nonce = payload.get("n", "")
    if nonce:
        _OAUTH_FALLBACK_STORE[nonce] = (_time.monotonic() + _OAUTH_COOKIE_MAX_AGE, payload)
        _prune_fallback_store()
    return payload_b64


def _decode_oauth_cookie(cookie_value: str | None) -> dict | None:
    if not cookie_value:
        return None
    if SESSION_SECRET:
        if "." not in cookie_value:
            return None
        try:
            payload_b64, sig_b64 = cookie_value.rsplit(".", 1)
        except ValueError:
            return None
        expected = _hmac.new(SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
        expected_b64 = base64.urlsafe_b64encode(expected).decode().rstrip("=")
        if not _hmac.compare_digest(expected_b64, sig_b64):
            return None
        try:
            padded = payload_b64 + "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None
    # #174: the unsigned in-memory path is local-dev only. Outside local,
    # refuse to accept unsigned OAuth state (symmetric with the encode-side
    # guard) so no unsigned cookie is ever honored in production.
    if not IS_LOCAL:
        return None
    try:
        padded = cookie_value + "=" * (-len(cookie_value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    nonce = payload.get("n")
    _prune_fallback_store()
    entry = _OAUTH_FALLBACK_STORE.get(nonce or "")
    if not entry:
        return None
    return entry[1]


def _prune_fallback_store() -> None:
    now = _time.monotonic()
    expired = [k for k, (exp, _) in _OAUTH_FALLBACK_STORE.items() if exp < now]
    for k in expired:
        _OAUTH_FALLBACK_STORE.pop(k, None)


@router.get("/me")
def get_me(request: Request):
    """Return approval and onboarding status for a given user_id."""
    user_id = get_session_user_id(request)
    user = table("users").select(
        "id,is_approved,onboarding_completed", filters={"id": f"eq.{user_id}"}
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

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


@router.get("/google")
def google_login(popup_id: str = Query(None)):
    """Redirect to Google consent screen with identity + calendar scopes."""
    if not GOOGLE_AVAILABLE or not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Google OAuth not configured")

    code_verifier, code_challenge = _generate_pkce_pair()
    nonce = secrets.token_urlsafe(32)
    clean_popup = _clean_popup_id(popup_id)

    flow = Flow.from_client_config(_google_client_config(), scopes=AUTH_SCOPES)
    flow.redirect_uri = GOOGLE_AUTH_REDIRECT_URI
    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        state=_encode_state({"action": "signin", "n": nonce}),
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )

    cookie_value = _encode_oauth_cookie({
        "n": nonce,
        "cv": code_verifier,
        "popup_id": clean_popup,
    })
    response = RedirectResponse(auth_url)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=cookie_value,
        max_age=_OAUTH_COOKIE_MAX_AGE,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/google/callback")
def google_callback(request: Request, code: str = Query(...), state: str = Query(None)):
    """Exchange auth code for tokens, validate @bu.edu, upsert user."""
    cookie_payload = _decode_oauth_cookie(request.cookies.get(OAUTH_STATE_COOKIE))
    code_verifier = cookie_payload.get("cv") if cookie_payload else None
    popup_id = _clean_popup_id(cookie_payload.get("popup_id")) if cookie_payload else None
    cookie_nonce = cookie_payload.get("n") if cookie_payload else None

    def _fail_redirect(error_code: str, fallback_path: str = "/auth") -> RedirectResponse:
        # In popup mode, route failures through /auth/callback so the popup
        # can broadcast the error and self-close instead of stranding the opener.
        if popup_id:
            params = urlencode({"error": error_code, "popup_id": popup_id})
            resp = RedirectResponse(f"{FRONTEND_URL}/auth/callback?{params}")
        else:
            resp = RedirectResponse(f"{FRONTEND_URL}{fallback_path}?error={error_code}")
        resp.set_cookie(
            key=OAUTH_STATE_COOKIE,
            value="",
            max_age=0,
            httponly=True,
            secure=SECURE_COOKIES,
            samesite="lax",
            path="/",
        )
        return resp

    if not GOOGLE_AVAILABLE:
        return _fail_redirect("google_not_configured")

    state_data = _decode_state(state) if state else {}
    state_nonce = state_data.get("n")
    if not cookie_payload or not cookie_nonce or not state_nonce or not _hmac.compare_digest(str(state_nonce), str(cookie_nonce)):
        return _fail_redirect("invalid_state")

    flow = Flow.from_client_config(_google_client_config(), scopes=AUTH_SCOPES)
    flow.redirect_uri = GOOGLE_AUTH_REDIRECT_URI
    try:
        flow.fetch_token(code=code, code_verifier=code_verifier)
    except Exception:
        return _fail_redirect("oauth_exchange_failed")
    creds = flow.credentials

    # Fetch user info from Google. Uses httpx (the codebase's sanctioned HTTP
    # client) instead of googleapiclient/httplib2 — httplib2 ignores
    # HTTPS_PROXY, which 500s on dev machines and proxy-bound deployments.
    import httpx
    try:
        resp = httpx.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        user_info = resp.json()
    except (httpx.HTTPError, ValueError):
        return _fail_redirect("userinfo_fetch_failed")
    if not isinstance(user_info, dict):
        return _fail_redirect("userinfo_fetch_failed")

    email = user_info.get("email", "")
    google_id = user_info.get("id", "")
    name = user_info.get("name", "")
    avatar_url = user_info.get("picture", "")

    # Split Google display name into first/last for the new columns
    name_parts = name.split(None, 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    # Restrict sign-in to the configured email-domain allowlist (default @bu.edu)
    if not _email_domain_allowed(email):
        return _fail_redirect("invalid_domain")

    # Profile fields (name/first_name/last_name/avatar_url) live on user_profiles
    # after migration 0024; `users` keeps identity + auth + activity only.
    profile_fields = {
        "name": encrypt_if_present(name),
        "first_name": encrypt_if_present(first_name),
        "last_name": encrypt_if_present(last_name),
        "avatar_url": avatar_url,
    }

    # Determine user_id: check if this Google ID already exists
    existing = table("users").select("id,is_approved", filters={"google_id": f"eq.{google_id}"})
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
        table("user_profiles").upsert(
            {"user_id": user_id, **profile_fields},
            on_conflict="user_id",
        )
    else:
        # Email-based account merge is disabled because emails are now encrypted
        # with random nonces; equality lookups by plaintext email cannot match.
        # New sign-ins for users without a google_id always create a fresh row.
        user_id = f"user_{google_id}"
        is_approved = _LOCAL_AUTO_APPROVE
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
        # reached onboarding already has a row here (onboarding.py upserts it).
        table("user_profiles").upsert(
            {"user_id": user_id, **profile_fields},
            on_conflict="user_id",
        )

    # Store OAuth tokens (calendar access included)
    # expires_at is TIMESTAMPTZ after migration 0024 — pass None (not "") when
    # there is no expiry, since "" is not a valid timestamptz.
    table("oauth_tokens").upsert(
        {
            "user_id": user_id,
            "access_token": encrypt(creds.token),
            "refresh_token": encrypt_if_present(creds.refresh_token),
            "expires_at": creds.expiry.isoformat() if creds.expiry else None,
        },
        on_conflict="user_id",
    )

    # Local dev bypass (#364): auto-approve so a real Google sign-in doesn't hit the
    # /pending wall. Strictly gated on APP_ENV=="local" — staging/prod AND the test
    # suite (APP_ENV=test) keep the real #285 approval gate and this can never approve
    # a user there. Persisted to the DB row so /api/auth/me and the frontend see the
    # approved state, not just this request.
    if _LOCAL_AUTO_APPROVE and not is_approved:
        is_approved = True
        table("users").update({"is_approved": True}, filters={"id": f"eq.{user_id}"})

    if not is_approved:
        if popup_id:
            return _fail_redirect("not_approved")
        resp = RedirectResponse(f"{FRONTEND_URL}/pending")
        resp.set_cookie(
            key=OAUTH_STATE_COOKIE,
            value="",
            max_age=0,
            httponly=True,
            secure=SECURE_COOKIES,
            samesite="lax",
            path="/",
        )
        return resp

    # One-shot HMAC token so the frontend can verify this redirect without a
    # second round-trip. The frontend exchanges it for the real, long-lived
    # `sapling_session` cookie (see _REDIRECT_TOKEN_TTL_SECONDS above) — it is
    # NOT the session itself, so it expires quickly.
    #
    # Uses the shared minter (#381). Byte-for-byte identical to the inline code
    # it replaces — same payload key order, same json.dumps separators, same
    # HMAC — so no behaviour changes here; only the TTL differs from a session,
    # and that is passed explicitly. The `if SESSION_SECRET` guard is kept (and
    # the secret passed explicitly) so this path still degrades to "no
    # auth_token in the redirect" rather than raising, exactly as before.
    auth_token = ""
    if SESSION_SECRET:
        auth_token = mint_session(
            user_id, ttl=_REDIRECT_TOKEN_TTL_SECONDS, secret=SESSION_SECRET
        )

    params = urlencode({
        "user_id": user_id,
        "avatar": avatar_url,
        "is_approved": "true",
        **({"auth_token": auth_token} if auth_token else {}),
        **({"popup_id": popup_id} if popup_id else {}),
    })
    resp = RedirectResponse(f"{FRONTEND_URL}/auth/callback?{params}")
    resp.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value="",
        max_age=0,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="lax",
        path="/",
    )
    return resp


# ── POST /api/auth/test-login ─────────────────────────────────────────────────


class MintTestSessionBody(BaseModel):
    """Body of POST /api/auth/test-login."""

    user_id: str = Field(min_length=1, max_length=255)
    ttl: int | None = Field(
        default=None,
        description="Session lifetime in seconds; clamped to [30, 86400].",
    )


@router.post("/test-login", include_in_schema=False)
async def mint_test_session(request: Request):
    """Mint a `sapling_session` cookie for a seeded user. LOCAL/TEST ONLY (#381).

    `GET /api/auth/dev-login` was removed and real Google OAuth cannot be driven
    headlessly, so the pytest integration suite and Playwright's global setup need
    a sanctioned way to obtain a session. This is that seam — and nothing more:
    it is NOT a sign-in flow, it is not browser-facing, and it must never be
    linked from the frontend.

    SECURITY
    - Hard-gated on `APP_ENV in {"local", "test"}` (see TEST_AUTH_ENVS), read at
      request time. Anywhere else this returns a plain 404 with the stock
      "Not Found" body — deliberately not 403, so the endpoint does not even
      advertise that it exists. `include_in_schema=False` keeps it out of
      /openapi.json in every environment for the same reason.
    - It performs NO credential check by design; the environment gate is the only
      thing standing between a caller and an arbitrary account. That is why the
      allowlist is two exact strings rather than the broader `config.IS_LOCAL`.
    - It does not touch the database: it neither creates users nor grants
      approval/roles, so a token minted for a non-seeded id authenticates as an
      account that does not exist and gets nowhere.

    Returns the token in the JSON body as well as in the cookie, so a Playwright
    global-setup step can inject it with `context.addCookies()` instead of
    replaying the response.
    """
    # The gate runs FIRST, before the body is even looked at. The body is parsed
    # and validated by hand rather than declared as a `MintTestSessionBody`
    # parameter precisely for this: FastAPI validates declared body params
    # *before* entering the handler, so in production a malformed body would have
    # answered 422 — and a 422 from a path that "does not exist" is exactly the
    # disclosure the 404 is there to prevent. Now every request shape gets the
    # same stock 404 outside local/test.
    if not _test_auth_enabled():
        raise HTTPException(status_code=404, detail="Not Found")

    try:
        raw = await request.json()
    except Exception:
        raw = None
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object.")
    try:
        body = MintTestSessionBody.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=[
                {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                for e in exc.errors()
            ],
        )

    user_id = body.user_id.strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id must not be blank")

    secret = (getattr(config, "SESSION_SECRET", "") or "").strip()
    if not secret:
        # config.validate_config() relaxes the SESSION_SECRET requirement for
        # IS_LOCAL, so local dev can legitimately have none. Fail loudly instead
        # of handing back a token _decode_session would reject anyway.
        raise HTTPException(
            status_code=500,
            detail="SESSION_SECRET is not configured; cannot mint a test session.",
        )

    requested = TEST_LOGIN_DEFAULT_TTL_SECONDS if body.ttl is None else body.ttl
    ttl = max(30, min(int(requested), TEST_LOGIN_MAX_TTL_SECONDS))
    token = mint_session(user_id, ttl=ttl, secret=secret)

    logger.warning("test-login: minted a session for %r (APP_ENV=%s)", user_id, config.APP_ENV)

    response = JSONResponse({
        "ok": True,
        "user_id": user_id,
        "cookie_name": SESSION_COOKIE_NAME,
        "token": token,
        "expires_in": ttl,
    })
    # Same attributes the real session cookie carries (frontend BFF
    # /api/auth/session and the OAuth-state cookie above).
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=ttl,
        httponly=True,
        secure=bool(getattr(config, "SECURE_COOKIES", False)),
        samesite="lax",
        path="/",
    )
    return response
