"""
backend/routes/auth.py

Google Sign-In OAuth flow.
GET /api/auth/google          → redirects to Google consent screen
GET /api/auth/google/callback → exchanges code, upserts user, redirects to frontend
"""

import uuid

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

from config import (
    GOOGLE_CLIENT_ID_SIGN_IN,
    GOOGLE_CLIENT_SECRET_SIGN_IN,
    GOOGLE_AUTH_REDIRECT_URI,
    FRONTEND_URL,
)
from db.connection import table

try:
    from google_auth_oauthlib.flow import Flow
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

router = APIRouter()

AUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


def _client_config() -> dict:
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID_SIGN_IN,
            "client_secret": GOOGLE_CLIENT_SECRET_SIGN_IN,
            "redirect_uris": [GOOGLE_AUTH_REDIRECT_URI],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


@router.get("/google")
def google_login():
    if not GOOGLE_AVAILABLE or not GOOGLE_CLIENT_ID_SIGN_IN:
        return RedirectResponse(f"{FRONTEND_URL}/signin?error=not_configured")
    flow = Flow.from_client_config(_client_config(), scopes=AUTH_SCOPES)
    flow.redirect_uri = GOOGLE_AUTH_REDIRECT_URI
    auth_url, _ = flow.authorization_url(prompt="select_account", access_type="offline")
    return RedirectResponse(auth_url)


@router.get("/google/callback")
def google_callback(code: str = Query(...), state: str = Query(None)):
    if not GOOGLE_AVAILABLE:
        return RedirectResponse(f"{FRONTEND_URL}/signin?error=not_configured")

    try:
        flow = Flow.from_client_config(_client_config(), scopes=AUTH_SCOPES)
        flow.redirect_uri = GOOGLE_AUTH_REDIRECT_URI
        flow.fetch_token(code=code)
        creds = flow.credentials

        # Fetch Google profile
        import httpx
        resp = httpx.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=10,
        )
        profile = resp.json()
        google_id = profile.get("id", "")
        name = profile.get("name", "")
        email = profile.get("email", "")
        avatar_url = profile.get("picture", "")
    except Exception as e:
        return RedirectResponse(f"{FRONTEND_URL}/signin?error=oauth_failed")

    # Look up existing user by google_id
    existing = table("users").select("id,name", filters={"google_id": f"eq.{google_id}"})
    if existing:
        user_id = existing[0]["id"]
        # Keep name in sync in case they changed it on Google
        table("users").update(
            {"name": name, "avatar_url": avatar_url},
            filters={"id": f"eq.{user_id}"},
        )
    else:
        # New user — create a row
        user_id = f"guser_{uuid.uuid4().hex[:12]}"
        table("users").insert([{
            "id": user_id,
            "name": name,
            "email": email,
            "google_id": google_id,
            "avatar_url": avatar_url,
            "auth_provider": "google",
        }])

    redirect = (
        f"{FRONTEND_URL}/signin/callback"
        f"?user_id={user_id}&name={name}&avatar={avatar_url}"
    )
    return RedirectResponse(redirect)
