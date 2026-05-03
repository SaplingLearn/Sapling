"""
backend/routes/auth.py

Google OAuth sign-in with unified calendar access.
Restricts sign-in to @bu.edu email accounts only.
"""

import json
import base64
import hashlib
import hmac as _hmac
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
from services.encryption import encrypt, encrypt_if_present
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


@router.get("/me")
def get_me(request: Request):
    """Return approval and onboarding status for a given user_id."""
    user_id = get_session_user_id(request)
    user = table("users").select("id,is_approved,onboarding_completed,username", filters={"id": f"eq.{user_id}"})
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
        "roles": roles,
        "equipped_cosmetics": equipped_cosmetics,
        "is_admin": is_admin,
    }


@router.get("/google")
def google_login():
    """Redirect to Google consent screen with identity + calendar scopes."""
    if not GOOGLE_AVAILABLE or not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Google OAuth not configured")

    code_verifier, code_challenge = _generate_pkce_pair()
    flow = Flow.from_client_config(_google_client_config(), scopes=AUTH_SCOPES)
    flow.redirect_uri = GOOGLE_AUTH_REDIRECT_URI
    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        state=_encode_state({"action": "signin", "cv": code_verifier}),
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )
    return RedirectResponse(auth_url)


@router.get("/google/callback")
def google_callback(code: str = Query(...), state: str = Query(None)):
    """Exchange auth code for tokens, validate @bu.edu, upsert user."""
    if not GOOGLE_AVAILABLE:
        return RedirectResponse(f"{FRONTEND_URL}/auth?error=google_not_configured")

    state_data = _decode_state(state) if state else {}
    code_verifier = state_data.get("cv")

    flow = Flow.from_client_config(_google_client_config(), scopes=AUTH_SCOPES)
    flow.redirect_uri = GOOGLE_AUTH_REDIRECT_URI
    flow.fetch_token(code=code, code_verifier=code_verifier)
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
        return RedirectResponse(
            f"{FRONTEND_URL}/auth?error=invalid_domain"
        )

    # Determine user_id: check if this Google ID already exists
    existing = table("users").select("id,is_approved", filters={"google_id": f"eq.{google_id}"})
    if existing:
        user_id = existing[0]["id"]
        is_approved = existing[0]["is_approved"]
        # Update name/avatar in case they changed
        table("users").update(
            {
                "name": encrypt_if_present(name),
                "first_name": encrypt_if_present(first_name),
                "last_name": encrypt_if_present(last_name),
                "avatar_url": avatar_url,
                "email": encrypt_if_present(email),
            },
            filters={"id": f"eq.{user_id}"},
        )
    else:
        # Email-based account merge is disabled because emails are now encrypted
        # with random nonces; equality lookups by plaintext email cannot match.
        # New sign-ins for users without a google_id always create a fresh row.
        user_id = f"user_{google_id}"
        is_approved = False
        table("users").insert({
            "id": user_id,
            "name": encrypt_if_present(name),
            "first_name": encrypt_if_present(first_name),
            "last_name": encrypt_if_present(last_name),
            "email": encrypt_if_present(email),
            "google_id": google_id,
            "avatar_url": avatar_url,
            "auth_provider": "google",
        })

    # Store OAuth tokens (calendar access included)
    table("oauth_tokens").upsert(
        {
            "user_id": user_id,
            "access_token": encrypt(creds.token),
            "refresh_token": encrypt(creds.refresh_token or ""),
            "expires_at": creds.expiry.isoformat() if creds.expiry else "",
        },
        on_conflict="user_id",
    )

    if not is_approved:
        return RedirectResponse(f"{FRONTEND_URL}/pending")

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
    })
    return RedirectResponse(f"{FRONTEND_URL}/auth/callback?{params}")
