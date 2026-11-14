"""
Auth guard utilities for route protection.
Matches the HMAC session token pattern from routes/auth.py.
"""

import json
import base64
import hashlib
import hmac as _hmac
import logging
import math
import threading
import time as _time
from datetime import datetime, timezone
from typing import NamedTuple

from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool

import config
from config import SESSION_SECRET
from db.connection import table
from db.scope import service_scope
from services import events_service
from services.session_tokens import (
    IAT_PRECISION_CLAIM,
    IAT_PRECISION_MS,
    SESSION_COOKIE_NAME,
    TOKEN_TYPE_SESSION,
)

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
    that knows where a session token may come from: the `sapling_session`
    cookie, and nothing else. `_decode_session` verifies what this returns;
    `presents_credentials` only asks whether it is there.

    An `?auth_token=` query parameter used to be read first. No client sent it
    (the OAuth handoff token travels in the FRONTEND's callback URL and reaches
    the session BFF in a JSON body; the browser reaches the API with the
    cookie), and a credential in a URL lands in access logs, Referer headers
    and browser history, so the channel is gone."""
    return request.cookies.get(SESSION_COOKIE_NAME)


def presents_credentials(request: Request) -> bool:
    """Whether the request CLAIMS an identity: a session token (see
    `presented_session_token`) or an `Authorization` header (the bearer that
    server-to-server callers such as Canopy's metrics poll send). Presence
    only — nothing is verified, decoded or logged. Used by RequestIDMiddleware
    to tell our own clients' unrouted 404s from anonymous scanner noise
    (#690)."""
    return bool(presented_session_token(request) or request.headers.get("authorization"))


# ── Session age (iat) ────────────────────────────────────────────────────────
# Every token minted since server-side revocation carries `iat`. A LEGACY
# session (minted before the claim) has none; the frontend BFF minted those
# with a 30-day `exp`, so `exp - 30 days` is when it was issued. That estimate
# is exact for a legacy BFF cookie and earlier than the truth for anything
# shorter-lived, which only ever makes such a token look older (fail closed).
LEGACY_SESSION_LIFETIME_SECONDS = 30 * 24 * 3600
# Tolerance for an `iat` slightly in the future: the frontend worker and this
# backend each read their own clock.
_IAT_CLOCK_SKEW_SECONDS = 300


def session_issued_at(payload: dict) -> float:
    """When the verified session `payload` was issued (unix seconds; fractional
    for a token minted to the millisecond)."""
    iat = payload.get("iat")
    if isinstance(iat, (int, float)) and not isinstance(iat, bool):
        return iat
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and not isinstance(exp, bool):
        return int(exp) - LEGACY_SESSION_LIFETIME_SECONDS
    return 0


def issued_before(payload: dict, cut_off: float) -> bool:
    """Whether the session `payload` was issued before `cut_off` (unix seconds,
    sub-second: `users.sessions_valid_after`), i.e. is revoked by it.

    A token that says its `iat` is to the millisecond (`iat_precision: "ms"`:
    every token minted now, by the backend and the BFF, truncated so it is
    never later than the mint) compares exactly, whether or not that iat
    falls on a whole second. Anything else (a legacy whole-second `iat`, or
    the legacy `exp`-derived estimate) could have been minted anywhere in its
    second, so one from the cut-off's own second counts as issued before it:
    no benefit of the doubt.
    """
    iat = session_issued_at(payload)
    minted_iat = payload.get("iat")
    if (
        payload.get(IAT_PRECISION_CLAIM) == IAT_PRECISION_MS
        and isinstance(minted_iat, (int, float))
        and not isinstance(minted_iat, bool)
    ):
        return iat < cut_off
    return math.floor(iat) <= math.floor(cut_off)


def _decode_session(request: Request) -> dict:
    """Extract and verify the session token from the session cookie: the
    signature, `exp`, `typ`, and the session's age (`iat`, at most
    config.SESSION_MAX_AGE_SECONDS). Pure CPU — no DB read; revocation
    (`users.sessions_valid_after`) is checked by `get_session_user_id`."""
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
    now = int(_time.time())
    exp = payload.get("exp", 0)
    if not isinstance(exp, (int, float)) or isinstance(exp, bool) or exp < now:
        raise HTTPException(status_code=401, detail="Session expired")

    # #756: only a `session` token is an API credential. The OAuth callback's
    # `handoff` token (300 s, carried in a URL) is for the session BFF alone;
    # without this check it worked as a full credential via `?auth_token=`. A
    # legacy token with no `typ` predates the claim and is a session.
    if payload.get("typ", TOKEN_TYPE_SESSION) != TOKEN_TYPE_SESSION:
        raise HTTPException(status_code=401, detail="Invalid session token")

    # The session's age, whatever its `exp` says: a session lives at most
    # SESSION_MAX_AGE_SECONDS from issue (a pre-iat 30-day cookie included),
    # and one "issued" in the future is forged or from a broken clock.
    iat = session_issued_at(payload)
    if iat > now + _IAT_CLOCK_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="Invalid session token")
    if now - iat > config.SESSION_MAX_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="Session expired")

    return payload


# ── Account state (#756) ─────────────────────────────────────────────────────
# A valid signature only says the token was issued; the account may since have
# been deleted (soft delete: `users.deleted_at`), had its access removed
# (`users.is_approved = false`, Admin → Users), or signed out, which revokes
# every session issued before it (`users.sessions_valid_after`). The guard
# therefore reads the `users` row too — through a short-TTL per-process cache,
# so an authenticated request does not pay a DB round-trip each time.
#
# Invalidation story (CLAUDE.md's cache rule): bounded staleness. An entry lives
# at most ACCOUNT_STATE_TTL_SECONDS, so a deletion, approval change or sign-out
# made by ANY process is honoured everywhere within that window. Mutators in
# this process call `clear_account_state_cache(user_id)` to make it immediate
# (profile.delete_account and POST /api/auth/logout do). Failures to read are
# never cached.
ACCOUNT_ACTIVE = "active"
ACCOUNT_MISSING = "missing"
ACCOUNT_DELETED = "deleted"
ACCOUNT_UNAPPROVED = "unapproved"

ACCOUNT_STATE_TTL_SECONDS = 30.0
_ACCOUNT_STATE_MAX_ENTRIES = 10_000


class AccountRecord(NamedTuple):
    """What the guard knows about a session's account."""

    state: str
    #: Unix seconds (sub-second, as stored). A session issued (`iat`) before
    #: it is revoked (`issued_before`); None when the account never signed out.
    sessions_valid_after: float | None = None


_account_state_cache: dict[str, tuple[float, AccountRecord]] = {}
_account_state_lock = threading.Lock()


def clear_account_state_cache(user_id: str | None = None) -> None:
    """Forget the cached account state for `user_id` (or everyone)."""
    with _account_state_lock:
        if user_id is None:
            _account_state_cache.clear()
        else:
            _account_state_cache.pop(user_id, None)


def _parse_timestamp(value) -> float | None:
    """A PostgREST timestamptz as unix seconds; None for NULL. Raises on
    anything else, so a malformed value is a read failure (503, not cached)."""
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _read_account_state(user_id: str) -> AccountRecord:
    # Service role (#115): this read DECIDES whether the subject is a live
    # account, so it cannot run as that subject. Every guarded request makes
    # it; a scoped miss here would 500 every request under enforce.
    with service_scope():
        rows = table("users").select(
            "id,deleted_at,is_approved,sessions_valid_after", filters={"id": f"eq.{user_id}"}
        )
    if not rows:
        return AccountRecord(ACCOUNT_MISSING)
    row = rows[0]
    valid_after = _parse_timestamp(row.get("sessions_valid_after"))
    if row.get("deleted_at"):
        return AccountRecord(ACCOUNT_DELETED, valid_after)
    if not row.get("is_approved"):
        return AccountRecord(ACCOUNT_UNAPPROVED, valid_after)
    return AccountRecord(ACCOUNT_ACTIVE, valid_after)


def account_record(user_id: str) -> AccountRecord:
    """The account's state and session cut-off, cached for a short TTL.

    Raises 503 if the row cannot be read: failing open would let a deleted
    account through whenever the DB blips, and the request needs the DB anyway.
    """
    now = _time.monotonic()
    with _account_state_lock:
        hit = _account_state_cache.get(user_id)
    if hit and hit[0] > now:
        return hit[1]
    try:
        record = _read_account_state(user_id)
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
        _account_state_cache[user_id] = (now + ACCOUNT_STATE_TTL_SECONDS, record)
    return record


def account_state(user_id: str) -> str:
    """`active` | `missing` | `deleted` | `unapproved` (see `account_record`)."""
    return account_record(user_id).state


def get_session_user_id(request: Request, *, allow_unapproved: bool = False) -> str:
    """Get the authenticated user_id from a verified session token. No fallbacks.

    #756: the token must also name a live account — a `users` row that is not
    soft-deleted (missing or deleted → 401) and is approved (unapproved → 403
    with `code=not_approved`). `allow_unapproved=True` is for `GET
    /api/auth/me` alone, which the frontend middleware reads to route an
    unapproved account to /pending.

    A session issued before the account's `sessions_valid_after` (set by
    sign-out, POST /api/auth/logout) is revoked: 401.
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
    record = account_record(user_id)
    if record.state in (ACCOUNT_MISSING, ACCOUNT_DELETED):
        raise HTTPException(status_code=401, detail="Not authenticated")
    if record.sessions_valid_after is not None and issued_before(
        payload, record.sessions_valid_after
    ):
        raise HTTPException(status_code=401, detail="Session revoked")
    if record.state == ACCOUNT_UNAPPROVED and not allow_unapproved:
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


# ── Admin step-up ────────────────────────────────────────────────────────────
# Admins have no second factor, so their power is tied to a RECENT Google
# sign-in instead of the session's full lifetime: an admin route needs a
# session issued (`iat`) within config.ADMIN_REAUTH_WINDOW_SECONDS, and a
# destructive one within config.ADMIN_DESTRUCTIVE_REAUTH_WINDOW_SECONDS.
# Otherwise 401 with `detail.code == "reauth_required"`, which the frontend
# answers by sending the admin through Google sign-in again (a fresh sign-in
# mints a fresh session). A non-admin still gets the 403 first.
REAUTH_REQUIRED = "reauth_required"


def _require_recent_session(request: Request, window_seconds: int) -> None:
    payload = _decode_session(request)
    age = int(_time.time()) - session_issued_at(payload)
    if age > window_seconds:
        raise HTTPException(
            status_code=401,
            detail={
                "code": REAUTH_REQUIRED,
                "message": "For your security, sign in again to continue.",
                "max_session_age_seconds": window_seconds,
            },
        )


def require_admin(request: Request, *, max_session_age: int | None = None) -> None:
    """Verify the authenticated user has the admin role, on a session issued
    within `max_session_age` seconds (default config.ADMIN_REAUTH_WINDOW_SECONDS;
    401 `reauth_required` otherwise)."""
    session_user = get_session_user_id(request)
    with service_scope():  # #115: an authorization read, like the account read
        roles = table("user_roles").select(
            "role_id,roles!inner(slug)",
            filters={"user_id": f"eq.{session_user}"},
        )
    slugs = [r.get("roles", {}).get("slug", "") for r in roles] if roles else []
    if "admin" not in slugs:
        _log_permission_denied(session_user, request, "not_admin")
        raise HTTPException(status_code=403, detail="Admin access required")
    _require_recent_session(
        request,
        config.ADMIN_REAUTH_WINDOW_SECONDS if max_session_age is None else max_session_age,
    )


def require_admin_recent(request: Request) -> None:
    """`require_admin` for a destructive action (account wipe/seed/copy, role
    changes, email broadcasts, feature-flag changes): the session must be
    issued within config.ADMIN_DESTRUCTIVE_REAUTH_WINDOW_SECONDS."""
    require_admin(request, max_session_age=config.ADMIN_DESTRUCTIVE_REAUTH_WINDOW_SECONDS)


def require_role(role_slug: str):
    """Returns a callable that checks if the user has the given role."""
    def _checker(request: Request):
        session_user = get_session_user_id(request)
        with service_scope():  # #115: an authorization read
            roles = table("user_roles").select(
                "role_id,roles!inner(slug)",
                filters={"user_id": f"eq.{session_user}"},
            )
        slugs = [r.get("roles", {}).get("slug", "") for r in roles] if roles else []
        if role_slug not in slugs:
            _log_permission_denied(session_user, request, f"missing_role:{role_slug}")
            raise HTTPException(status_code=403, detail=f"Role '{role_slug}' required")
    return _checker
