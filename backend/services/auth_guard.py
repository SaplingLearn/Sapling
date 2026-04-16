"""
Auth guard utilities for route protection.
Matches the HMAC session token pattern from routes/auth.py.
"""

import json
import base64
import hashlib
import hmac as _hmac
import time as _time

from fastapi import HTTPException, Request
from config import SESSION_SECRET
from db.connection import table


def _decode_session(request: Request) -> dict:
    """Extract and verify the session token from query params or cookies."""
    token = request.query_params.get("auth_token") or request.cookies.get("sapling_session")
    if not token or not SESSION_SECRET:
        raise HTTPException(status_code=401, detail="Not authenticated")

    parts = token.split(".")
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="Invalid session token")

    payload_b64, sig_b64 = parts

    # Verify signature
    expected_sig = _hmac.new(
        SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256
    ).digest()
    expected_b64 = base64.urlsafe_b64encode(expected_sig).decode().rstrip("=")

    if not _hmac.compare_digest(sig_b64, expected_b64):
        raise HTTPException(status_code=401, detail="Invalid session token")

    # Decode payload
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode())
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid session token")

    # Check expiry
    if payload.get("exp", 0) < int(_time.time()):
        raise HTTPException(status_code=401, detail="Session expired")

    return payload


def get_session_user_id(request: Request) -> str:
    """Get the authenticated user_id from the request, or fall back to query param."""
    # For dev/alpha: accept user_id from query params as the codebase currently does
    user_id = request.query_params.get("user_id")
    if user_id:
        return user_id
    try:
        payload = _decode_session(request)
        return payload["user_id"]
    except Exception:
        raise HTTPException(status_code=401, detail="Not authenticated")


def require_self(user_id: str, request: Request) -> None:
    """Verify the authenticated user matches the target user_id."""
    session_user = get_session_user_id(request)
    if session_user != user_id:
        raise HTTPException(status_code=403, detail="Forbidden: not your account")


def require_admin(request: Request) -> None:
    """Verify the authenticated user has the admin role."""
    session_user = get_session_user_id(request)
    roles = table("user_roles").select(
        "role_id,roles!inner(slug)",
        filters={"user_id": f"eq.{session_user}"},
    )
    slugs = [r.get("roles", {}).get("slug", "") for r in roles] if roles else []
    if "admin" not in slugs:
        raise HTTPException(status_code=403, detail="Admin access required")


def require_role(role_slug: str):
    """Returns a callable that checks if the user has the given role."""
    def _checker(request: Request):
        session_user = get_session_user_id(request)
        roles = table("user_roles").select(
            "role_id,roles!inner(slug)",
            filters={"user_id": f"eq.{session_user}"},
        )
        slugs = [r.get("roles", {}).get("slug", "") for r in roles] if roles else []
        if role_slug not in slugs:
            raise HTTPException(status_code=403, detail=f"Role '{role_slug}' required")
    return _checker
