"""
backend/routes/auth.py

Google OAuth sign-in with unified calendar access.
Restricts sign-in to @bu.edu email accounts only.
"""

import json
import base64
import hashlib
import hmac as _hmac
import re
import secrets
import time as _time
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_AUTH_REDIRECT_URI,
    AUTH_SCOPES,
    FRONTEND_URL,
    SESSION_SECRET,
)
from db.connection import table
from services.encryption import encrypt, encrypt_if_present, decrypt_if_present
from services.auth_guard import get_session_user_id

try:
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleAuthRequest
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

router = APIRouter()


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
    user = table("users").select("id,is_approved,onboarding_completed,username,name,avatar_url", filters={"id": f"eq.{user_id}"})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

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
        "username": user[0].get("username"),
        "name": decrypt_if_present(user[0].get("name")) or "",
        "avatar_url": user[0].get("avatar_url") or "",
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
        secure=True,
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
            secure=True,
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

    # Fetch user info from Google
    service = build("oauth2", "v2", credentials=creds)
    user_info = service.userinfo().get().execute()

    email = user_info.get("email", "")
    google_id = user_info.get("id", "")
    name = user_info.get("name", "")
    avatar_url = user_info.get("picture", "")

    # Split Google display name into first/last for the new columns
    name_parts = name.split(None, 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    # Restrict to @bu.edu accounts
    if not email.endswith("@bu.edu"):
        return _fail_redirect("invalid_domain")

    # Determine user_id: check if this Google ID already exists
    existing = table("users").select("id,is_approved", filters={"google_id": f"eq.{google_id}"})
    if existing:
        user_id = existing[0]["id"]
        is_approved = existing[0]["is_approved"]
        # Update name/avatar in case they changed
        from datetime import datetime as _dt, timezone as _tz
        table("users").update(
            {
                "name": encrypt_if_present(name),
                "first_name": encrypt_if_present(first_name),
                "last_name": encrypt_if_present(last_name),
                "avatar_url": avatar_url,
                "email": encrypt_if_present(email),
                "last_sign_in_at": _dt.now(_tz.utc).isoformat(),
            },
            filters={"id": f"eq.{user_id}"},
        )
    else:
        # Email-based account merge is disabled because emails are now encrypted
        # with random nonces; equality lookups by plaintext email cannot match.
        # New sign-ins for users without a google_id always create a fresh row.
        user_id = f"user_{google_id}"
        is_approved = False
        from datetime import datetime as _dt, timezone as _tz
        table("users").insert({
            "id": user_id,
            "name": encrypt_if_present(name),
            "first_name": encrypt_if_present(first_name),
            "last_name": encrypt_if_present(last_name),
            "email": encrypt_if_present(email),
            "google_id": google_id,
            "avatar_url": avatar_url,
            "auth_provider": "google",
            "last_sign_in_at": _dt.now(_tz.utc).isoformat(),
        })

    # Store OAuth tokens (calendar access included)
    table("oauth_tokens").upsert(
        {
            "user_id": user_id,
            "access_token": encrypt(creds.token),
            "refresh_token": encrypt_if_present(creds.refresh_token),
            "expires_at": creds.expiry.isoformat() if creds.expiry else "",
        },
        on_conflict="user_id",
    )

    if not is_approved:
        if popup_id:
            return _fail_redirect("not_approved")
        resp = RedirectResponse(f"{FRONTEND_URL}/pending")
        resp.set_cookie(
            key=OAUTH_STATE_COOKIE,
            value="",
            max_age=0,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
        return resp

    # Build a short-lived HMAC token so the frontend can verify this redirect
    # without a second round-trip to the backend.
    auth_token = ""
    if SESSION_SECRET:
        payload = json.dumps({"user_id": user_id, "exp": int(_time.time()) + 300}).encode()
        payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        sig_bytes = _hmac.new(SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")
        auth_token = f"{payload_b64}.{sig_b64}"

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
        secure=True,
        samesite="lax",
        path="/",
    )
    return resp
