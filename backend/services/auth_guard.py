"""
Auth guard utilities for route protection.
Matches the HMAC session token pattern from routes/auth.py.
"""

import json
import base64
import hashlib
import hmac as _hmac
import logging
import threading
import time as _time

from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from config import SESSION_SECRET
from db.connection import table
from services import events_service
from services.session_tokens import SESSION_COOKIE_NAME, TOKEN_TYPE_SESSION

logger = logging.getLogger(__name__)

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


def presented_session_token(request: Request) -> str | None:
    """The raw session token the request carries, UNVERIFIED — the one place
    that knows where a session token may come from (the `auth_token` query
    param, then the `sapling_session` cookie). `_decode_session` verifies what
    this returns; `presents_credentials` only asks whether it is there."""
    return request.query_params.get("auth_token") or request.cookies.get(SESSION_COOKIE_NAME)


def presents_credentials(request: Request) -> bool:
    """Whether the request CLAIMS an identity: a session token (see
    `presented_session_token`) or an `Authorization` header (the bearer that
    server-to-server callers such as Canopy's metrics poll send). Presence
    only — nothing is verified, decoded or logged. Used by RequestIDMiddleware
    to tell our own clients' unrouted 404s from anonymous scanner noise
    (#690)."""
    return bool(presented_session_token(request) or request.headers.get("authorization"))


def _decode_session(request: Request) -> dict:
    """Extract and verify the session token from query params or cookies."""
    token = presented_session_token(request)
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

    if not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="Invalid session token")

    # Check expiry
    if payload.get("exp", 0) < int(_time.time()):
        raise HTTPException(status_code=401, detail="Session expired")

    # #756: only a `session` token is an API credential. The OAuth callback's
    # `handoff` token (300 s, carried in a URL) is for the session BFF alone;
    # without this check it worked as a full credential via `?auth_token=`. A
    # legacy token with no `typ` predates the claim and is a session.
    if payload.get("typ", TOKEN_TYPE_SESSION) != TOKEN_TYPE_SESSION:
        raise HTTPException(status_code=401, detail="Invalid session token")

    return payload


# ── Account state (#756) ─────────────────────────────────────────────────────
# A valid signature only says the token was issued; the account may since have
# been deleted (soft delete: `users.deleted_at`) or had its access removed
# (`users.is_approved = false`, Admin → Users). The guard therefore reads the
# `users` row too — through a short-TTL per-process cache, so an authenticated
# request does not pay a DB round-trip each time.
#
# Invalidation story (CLAUDE.md's cache rule): bounded staleness. An entry lives
# at most ACCOUNT_STATE_TTL_SECONDS, so a deletion or approval change made by
# ANY process is honoured everywhere within that window. Mutators in this
# process call `clear_account_state_cache(user_id)` to make it immediate
# (profile.delete_account does). Failures to read are never cached.
ACCOUNT_ACTIVE = "active"
ACCOUNT_MISSING = "missing"
ACCOUNT_DELETED = "deleted"
ACCOUNT_UNAPPROVED = "unapproved"

ACCOUNT_STATE_TTL_SECONDS = 30.0
_ACCOUNT_STATE_MAX_ENTRIES = 10_000
_account_state_cache: dict[str, tuple[float, str]] = {}
_account_state_lock = threading.Lock()


def clear_account_state_cache(user_id: str | None = None) -> None:
    """Forget the cached account state for `user_id` (or everyone)."""
    with _account_state_lock:
        if user_id is None:
            _account_state_cache.clear()
        else:
            _account_state_cache.pop(user_id, None)


def _read_account_state(user_id: str) -> str:
    rows = table("users").select(
        "id,deleted_at,is_approved", filters={"id": f"eq.{user_id}"}
    )
    if not rows:
        return ACCOUNT_MISSING
    row = rows[0]
    if row.get("deleted_at"):
        return ACCOUNT_DELETED
    if not row.get("is_approved"):
        return ACCOUNT_UNAPPROVED
    return ACCOUNT_ACTIVE


def account_state(user_id: str) -> str:
    """`active` | `missing` | `deleted` | `unapproved`, cached for a short TTL.

    Raises 503 if the row cannot be read: failing open would let a deleted
    account through whenever the DB blips, and the request needs the DB anyway.
    """
    now = _time.monotonic()
    with _account_state_lock:
        hit = _account_state_cache.get(user_id)
    if hit and hit[0] > now:
        return hit[1]
    try:
        state = _read_account_state(user_id)
    except Exception:
        logger.warning("auth guard: could not read account state for %r", user_id, exc_info=True)
        raise HTTPException(status_code=503, detail="Could not verify your account. Please try again.")
    with _account_state_lock:
        if len(_account_state_cache) >= _ACCOUNT_STATE_MAX_ENTRIES:
            expired = [k for k, (exp, _) in _account_state_cache.items() if exp <= now]
            for k in expired:
                del _account_state_cache[k]
            if len(_account_state_cache) >= _ACCOUNT_STATE_MAX_ENTRIES:
                _account_state_cache.clear()
        _account_state_cache[user_id] = (now + ACCOUNT_STATE_TTL_SECONDS, state)
    return state


def get_session_user_id(request: Request, *, allow_unapproved: bool = False) -> str:
    """Get the authenticated user_id from a verified session token. No fallbacks.

    #756: the token must also name a live account — a `users` row that is not
    soft-deleted (missing or deleted → 401) and is approved (unapproved → 403
    with `code=not_approved`). `allow_unapproved=True` is for `GET
    /api/auth/me` alone, which the frontend middleware reads to route an
    unapproved account to /pending.
    """
    try:
        payload = _decode_session(request)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = payload.get("user_id")
    if not user_id or not isinstance(user_id, str):
        raise HTTPException(status_code=401, detail="Not authenticated")
    state = account_state(user_id)
    if state in (ACCOUNT_MISSING, ACCOUNT_DELETED):
        raise HTTPException(status_code=401, detail="Not authenticated")
    if state == ACCOUNT_UNAPPROVED and not allow_unapproved:
        # Stamp the actor first so the 403 is attributable (see below).
        request.state.user_id = user_id
        raise HTTPException(
            status_code=403,
            detail={"code": "not_approved", "message": "Your account is not approved yet."},
        )
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


def _account_state_cached(request: Request) -> bool:
    """Whether the guard would answer `request` WITHOUT a DB read: the token is
    refused outright (decode is pure CPU), or its account state is cached."""
    try:
        payload = _decode_session(request)
    except Exception:
        return True
    user_id = payload.get("user_id") if isinstance(payload, dict) else None
    if not user_id or not isinstance(user_id, str):
        return True
    with _account_state_lock:
        hit = _account_state_cache.get(user_id)
    return bool(hit and hit[0] > _time.monotonic())


async def guard_off_loop(guard, *args, **kwargs):
    """Run a SYNC session guard (`require_self` / `get_session_user_id`) from
    an `async def` route without blocking the event loop (#756 review).

    The guard's account read is a blocking PostgREST call. On a cache hit (the
    common case: the TTL above) the guard does no I/O, so it runs inline; on a
    miss it runs in the threadpool. Pass the route module's own guard name, so
    a test that patches it there still takes effect. `require_admin` reads
    roles on every call: hop with `run_in_threadpool` directly.
    """
    request = next(
        (a for a in (*args, *kwargs.values()) if isinstance(a, Request)), None
    )
    if request is not None and _account_state_cached(request):
        return guard(*args, **kwargs)
    return await run_in_threadpool(guard, *args, **kwargs)


def require_self(user_id: str, request: Request, *, allow_unapproved: bool = False) -> None:
    """Verify the authenticated user matches the target user_id.

    `allow_unapproved=True` is for the routes a removed (unapproved, NOT
    deleted) student must keep: erasing and exporting their own data
    (profile.delete_account / export_data)."""
    session_user = get_session_user_id(request, allow_unapproved=allow_unapproved)
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
