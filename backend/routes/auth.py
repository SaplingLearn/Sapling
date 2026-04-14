"""
backend/routes/auth.py

Google OAuth sign-in with unified calendar access.
Restricts sign-in to @bu.edu email accounts only.
"""

import json
import base64
import hashlib
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_AUTH_REDIRECT_URI,
    AUTH_SCOPES,
    FRONTEND_URL,
)
from db.connection import table

try:
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
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
        return RedirectResponse(f"{FRONTEND_URL}/signin?error=google_not_configured")

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

    # Restrict to @bu.edu accounts
    if not email.endswith("@bu.edu"):
        return RedirectResponse(
            f"{FRONTEND_URL}/signin?error=invalid_domain"
        )

    # Determine user_id: check if this Google ID already exists
    existing = table("users").select("id,is_approved", filters={"google_id": f"eq.{google_id}"})
    if existing:
        user_id = existing[0]["id"]
        is_approved = existing[0]["is_approved"]
        # Update name/avatar in case they changed
        table("users").update(
            {"name": name, "avatar_url": avatar_url, "email": email},
            filters={"id": f"eq.{user_id}"},
        )
    else:
        # Check if a user with this email exists (migration from old system)
        email_match = table("users").select("id,is_approved", filters={"email": f"eq.{email}"})
        if email_match:
            user_id = email_match[0]["id"]
            is_approved = email_match[0]["is_approved"]
            table("users").update(
                {
                    "google_id": google_id,
                    "name": name,
                    "avatar_url": avatar_url,
                    "auth_provider": "google",
                },
                filters={"id": f"eq.{user_id}"},
            )
        else:
            # Create new user
            user_id = f"user_{google_id}"
            is_approved = False
            table("users").insert({
                "id": user_id,
                "name": name,
                "email": email,
                "google_id": google_id,
                "avatar_url": avatar_url,
                "auth_provider": "google",
            })

    # Store OAuth tokens (calendar access included)
    table("oauth_tokens").upsert(
        {
            "user_id": user_id,
            "access_token": creds.token,
            "refresh_token": creds.refresh_token or "",
            "expires_at": creds.expiry.isoformat() if creds.expiry else "",
        },
        on_conflict="user_id",
    )

    if not is_approved:
        return RedirectResponse(f"{FRONTEND_URL}/signin?error=not_approved")

    # Redirect to frontend with user info
    params = urlencode({
        "user_id": user_id,
        "name": name,
        "avatar": avatar_url,
        "is_approved": "true",
    })
    return RedirectResponse(f"{FRONTEND_URL}/signin/callback?{params}")
