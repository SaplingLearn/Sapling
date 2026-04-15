"""
backend/routes/auth.py

Google OAuth sign-in with unified calendar access.
Restricts sign-in to @bu.edu email accounts only.
"""

import hashlib
import json
import base64
import secrets
import traceback
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


def _generate_pkce_pair():
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return code_verifier, code_challenge


def _encode_state(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


def _decode_state(state: str) -> dict:
    try:
        return json.loads(base64.urlsafe_b64decode(state.encode()).decode())
    except Exception:
        return {}


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
        state=_encode_state({"cv": code_verifier}),
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )
    return RedirectResponse(auth_url)


@router.get("/google/callback")
def google_callback(code: str = Query(...), state: str = Query(None)):
    """Exchange auth code for tokens, validate .edu email, upsert user."""
    if not GOOGLE_AVAILABLE:
        return RedirectResponse(f"{FRONTEND_URL}/?error=google_not_configured")

    try:
        print("[auth] step 1: fetching token")
        code_verifier = _decode_state(state).get("cv") if state else None
        print(f"[auth] code_verifier present: {bool(code_verifier)}")
        flow = Flow.from_client_config(_google_client_config(), scopes=AUTH_SCOPES)
        flow.redirect_uri = GOOGLE_AUTH_REDIRECT_URI
        flow.fetch_token(code=code, code_verifier=code_verifier)
        creds = flow.credentials
        print("[auth] step 2: token fetched OK")

        # Fetch user info from Google
        service = build("oauth2", "v2", credentials=creds)
        user_info = service.userinfo().get().execute()
        print(f"[auth] step 3: user_info email={user_info.get('email')}")

        email = user_info.get("email", "")
        google_id = user_info.get("id", "")
        name = user_info.get("name", "")
        avatar_url = user_info.get("picture", "")

        # Restrict to .edu accounts
        if not email.endswith(".edu"):
            print(f"[auth] rejected: not .edu ({email})")
            return RedirectResponse(f"{FRONTEND_URL}/?error=invalid_domain")

        is_new_user = False

        # Determine user_id: check if this Google ID already exists
        print("[auth] step 4: checking DB")
        computed_id = f"user_{google_id}"
        existing = table("users").select("id", filters={"google_id": f"eq.{google_id}"})
        if existing:
            user_id = existing[0]["id"]
            print(f"[auth] existing user (google_id match): {user_id}")
            table("users").update(
                {"name": name, "avatar_url": avatar_url, "email": email},
                filters={"id": f"eq.{user_id}"},
            )
        else:
            email_match = table("users").select("id", filters={"email": f"eq.{email}"})
            if email_match:
                user_id = email_match[0]["id"]
                print(f"[auth] existing user (email match): {user_id}")
                table("users").update(
                    {"google_id": google_id, "name": name, "avatar_url": avatar_url, "auth_provider": "google"},
                    filters={"id": f"eq.{user_id}"},
                )
            else:
                id_match = table("users").select("id", filters={"id": f"eq.{computed_id}"})
                if id_match:
                    # Partially created in a previous failed auth — treat as existing
                    user_id = id_match[0]["id"]
                    print(f"[auth] existing user (id match, partial prev insert): {user_id}")
                    table("users").update(
                        {"google_id": google_id, "name": name, "avatar_url": avatar_url, "email": email, "auth_provider": "google"},
                        filters={"id": f"eq.{user_id}"},
                    )
                else:
                    is_new_user = True
                    user_id = computed_id
                    print(f"[auth] creating new user: {user_id}")
                    table("users").insert({
                        "id": user_id,
                        "name": name,
                        "email": email,
                        "google_id": google_id,
                        "avatar_url": avatar_url,
                        "auth_provider": "google",
                    })

        print("[auth] step 5: upserting tokens")
        table("oauth_tokens").upsert(
            {
                "user_id": user_id,
                "access_token": creds.token,
                "refresh_token": creds.refresh_token or "",
                "expires_at": creds.expiry.isoformat() if creds.expiry else "",
            },
            on_conflict="user_id",
        )

        print(f"[auth] step 6: done, is_new={is_new_user}, redirecting")
        params = urlencode({
            "user_id": user_id,
            "name": name,
            "avatar": avatar_url,
            "is_new": "true" if is_new_user else "false",
        })
        return RedirectResponse(f"{FRONTEND_URL}/signin/callback?{params}")

    except Exception as e:
        traceback.print_exc()
        print(f"[auth] FAILED at step above: {e}")
        return RedirectResponse(f"{FRONTEND_URL}/?error=auth_failed")
