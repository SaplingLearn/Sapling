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
from services import events_service
from services.session_tokens import SESSION_COOKIE_NAME

# #117 note: the 401 paths in _decode_session/get_session_user_id are
# deliberately NOT instrumented — RequestIDMiddleware already records every
# 4xx response as an error.4xx event, and a 401 carries no information the
# middleware row doesn't already have. The 403 *decisions* below are
# different: they DO emit auth.permission_denied (category=audit) IN
# ADDITION to the middleware's error.4xx for the same request — deliberate,
# not a double-count bug (PR #465 review): the audit event carries the
# denial `reason` and the authenticated actor, which the HTTP-level error
# row cannot know. The two land in different categories and serve different
# rollups (audit trail vs. error dashboard); consumers counting "requests
# that failed" should use error.*, and "denial decisions" auth.permission_denied.


def _decode_session(request: Request) -> dict:
    """Extract and verify the session token from query params or cookies."""
    token = request.query_params.get("auth_token") or request.cookies.get(SESSION_COOKIE_NAME)
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
    """Get the authenticated user_id from a verified session token. No fallbacks."""
    try:
        payload = _decode_session(request)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # #117 (1b): stamp the authenticated user onto request.state so the
    # error-event seam in RequestIDMiddleware can attribute 4xx/5xx responses
    # to a user. It must be request.state (the shared ASGI scope), NOT a
    # contextvar — BaseHTTPMiddleware runs the downstream app in a child
    # anyio task, so a contextvar set here never propagates back out; the
    # shared Request scope is the only thing that does.
    request.state.user_id = user_id
    return user_id


def _log_permission_denied(session_user: str, request: Request, reason: str) -> None:
    """#117: audit-trail a 403 decision. Route path only — never the full URL
    (query strings carry user input)."""
    events_service.log_event(
        "auth.permission_denied",
        category="audit",
        user_id=session_user,
        payload={"reason": reason, "route": request.url.path},
    )


def require_self(user_id: str, request: Request) -> None:
    """Verify the authenticated user matches the target user_id."""
    session_user = get_session_user_id(request)
    if session_user != user_id:
        _log_permission_denied(session_user, request, "not_self")
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
        _log_permission_denied(session_user, request, "not_admin")
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
            _log_permission_denied(session_user, request, f"missing_role:{role_slug}")
            raise HTTPException(status_code=403, detail=f"Role '{role_slug}' required")
    return _checker
