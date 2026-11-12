"""
backend/routes/calendar_connect.py

The Google Calendar consent flow: GET /api/calendar/auth-url and
GET /api/calendar/callback. Split out of routes/calendar.py (the route-length
ratchet, #118); calendar.py includes this router, so it keeps the
/api/calendar mount and the hide_calendar gate (main.py).
"""

import hmac as _hmac
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Request as FastAPIRequest
from fastapi.responses import RedirectResponse

from config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_REDIRECT_URI,
    GOOGLE_SCOPES,
    FRONTEND_URL,
    SECURE_COOKIES,
)
from db.connection import table
from db.scope import service_route
from services.auth_guard import require_self
from services.encryption import encrypt
# Reuse the sign-in flow's OAuth primitives (PKCE + HMAC-signed state cookie) as
# the single source of truth for CSRF handling — see services/auth/oauth_state.py.
# These are pure helpers with no request state, so importing them keeps the
# calendar connect flow DRY without duplicating the security-critical bits.
from services.auth.oauth_state import (
    _google_client_config,
    _encode_state,
    _decode_state,
    _generate_pkce_pair,
    _encode_oauth_cookie,
    _decode_oauth_cookie,
    covers_calendar,
    granted_scopes,
)

try:
    from google_auth_oauthlib.flow import Flow
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

router = APIRouter()


# ── Google Calendar OAuth connect ─────────────────────────────────────────────
# The dedicated calendar consent flow (auth-url → Google → callback), and since
# sign-in asks for identity only, the ONLY way calendar access is first granted
# (onboarding's Connect step, the Calendar page). It asks for GOOGLE_SCOPES and
# lands the tokens in `oauth_tokens` only when the grant covers all of them. It
# was dropped in the SQLite→Supabase migration (#61) even though
# config.GOOGLE_SCOPES / GOOGLE_REDIRECT_URI and the frontend "Connect Google"
# button still target it.
#
# `oauth_tokens` therefore holds a row only for a grant that reaches the
# calendar: this callback and sign-in (services/auth/signin.py) both refuse to
# store anything less. A row written before that rule came from a flow that
# asked for the calendar scopes, and oauthlib's scope check (on until this
# change) failed that flow's exchange unless Google granted exactly the scopes
# it asked for. That is what lets GET /status read "connected" off the row.

CALENDAR_OAUTH_STATE_COOKIE = "sapling_calendar_oauth_state"
_CALENDAR_OAUTH_COOKIE_MAX_AGE = 600

#: Where a successful connect may send the student (`next` on /auth-url): an
#: internal path, exactly one of these. Anything else is ignored.
CALENDAR_NEXT_PATHS = frozenset({"/dashboard", "/gradebook", "/calendar"})
_CALENDAR_DEFAULT_NEXT = "/calendar"


def _clean_calendar_next(value) -> str | None:
    return value if isinstance(value, str) and value in CALENDAR_NEXT_PATHS else None


def _calendar_client_config() -> dict:
    """Sign-in client config, re-pointed at the calendar redirect URI. The
    consent flow and the token exchange must use the SAME redirect_uri or Google
    rejects the code, so both routes go through this."""
    cfg = _google_client_config()
    cfg["web"]["redirect_uris"] = [GOOGLE_REDIRECT_URI]
    return cfg


@router.get("/auth-url")
def calendar_auth_url(
    request: FastAPIRequest,
    user_id: str = Query(...),
    next_path: str | None = Query(None, alias="next"),
):
    """Begin the Google Calendar consent flow for the authenticated user.

    ``require_self`` ties the initiating request to the caller's session, and the
    user_id is then sealed into the HMAC-signed state cookie — so the callback
    binds the resulting tokens to *this* user and never to an attacker-supplied
    parameter (the holistic auth-scoping concern on #61, sibling of #123).

    ``next`` (optional) is where a successful connect lands: one of
    ``CALENDAR_NEXT_PATHS``, anything else ignored. It is sealed in the same
    signed cookie and re-checked at the callback, so the redirect target is
    only ever one this route allowed.
    """
    require_self(user_id, request)
    if not GOOGLE_AVAILABLE or not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Google Calendar not configured")

    code_verifier, code_challenge = _generate_pkce_pair()
    nonce = secrets.token_urlsafe(32)

    flow = Flow.from_client_config(_calendar_client_config(), scopes=GOOGLE_SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    auth_url, _ = flow.authorization_url(
        prompt="consent",             # force a refresh_token even on re-consent
        access_type="offline",        # so long-lived sync survives token expiry
        include_granted_scopes="true",
        state=_encode_state({"action": "calendar", "n": nonce}),
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )

    cookie = {"n": nonce, "cv": code_verifier, "uid": user_id}
    clean_next = _clean_calendar_next(next_path)
    if clean_next:
        cookie["next"] = clean_next

    resp = RedirectResponse(auth_url)
    resp.set_cookie(
        key=CALENDAR_OAUTH_STATE_COOKIE,
        value=_encode_oauth_cookie(cookie),
        max_age=_CALENDAR_OAUTH_COOKIE_MAX_AGE,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="lax",
        path="/",
    )
    return resp


# #115: Google's redirect carries no session; the user comes from the signed
# state cookie -> service role under db_user_scope.
@router.get("/callback", dependencies=[Depends(service_route)])
def calendar_callback(
    request: FastAPIRequest,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
):
    """Handle Google's redirect: validate CSRF state, exchange the code, and
    store the tokens scoped to the user sealed in the signed state cookie.

    Success lands on the cookie's ``next`` (default /calendar) with
    ``connected=true``; every failure on /calendar with ``calendar_error``."""
    cookie_payload = _decode_oauth_cookie(request.cookies.get(CALENDAR_OAUTH_STATE_COOKIE))

    def _finish(query: str, path: str = _CALENDAR_DEFAULT_NEXT) -> RedirectResponse:
        resp = RedirectResponse(f"{FRONTEND_URL}{path}?{query}")
        resp.set_cookie(
            key=CALENDAR_OAUTH_STATE_COOKIE,
            value="",
            max_age=0,
            httponly=True,
            secure=SECURE_COOKIES,
            samesite="lax",
            path="/",
        )
        return resp

    if error:
        # User denied consent (or Google returned an error) — bounce cleanly.
        return _finish("calendar_error=access_denied")
    if not GOOGLE_AVAILABLE:
        return _finish("calendar_error=google_not_configured")
    if not code:
        return _finish("calendar_error=missing_code")

    # CSRF: the state nonce must match the one sealed in the signed cookie, and
    # the user_id is read from that cookie (not a request param) so tokens can
    # only ever bind to the session that initiated the connect.
    state_nonce = (_decode_state(state) or {}).get("n") if state else None
    cookie_nonce = cookie_payload.get("n") if cookie_payload else None
    user_id = cookie_payload.get("uid") if cookie_payload else None
    if (
        not cookie_payload
        or not cookie_nonce
        or not state_nonce
        or not user_id
        or not _hmac.compare_digest(str(state_nonce), str(cookie_nonce))
    ):
        return _finish("calendar_error=invalid_state")

    # No scopes on the exchange Flow. include_granted_scopes makes Google
    # answer with every scope granted (sign-in's identity scopes too), and a
    # student can untick a calendar box on Google's screen; oauthlib raises
    # "Scope has changed" on either, which failed every connect as
    # oauth_exchange_failed. The granted set is checked below instead.
    flow = Flow.from_client_config(_calendar_client_config(), scopes=None)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    try:
        flow.fetch_token(code=code, code_verifier=cookie_payload.get("cv"))
    except Exception:
        return _finish("calendar_error=oauth_exchange_failed")
    creds = flow.credentials

    # Connected means calendar access: a grant missing a calendar scope is
    # not stored, so a stored token is always one that reaches the calendar.
    if not covers_calendar(granted_scopes(creds, GOOGLE_SCOPES)):
        return _finish("calendar_error=scope_denied")

    row = {
        "user_id": user_id,
        "access_token": encrypt(creds.token),
        # expires_at is TIMESTAMPTZ (0024): None, not "", when absent.
        "expires_at": creds.expiry.isoformat() if creds.expiry else None,
    }
    # prompt=consent normally returns one; without it, keep the stored one.
    if creds.refresh_token:
        row["refresh_token"] = encrypt(creds.refresh_token)
    table("oauth_tokens").upsert(row, on_conflict="user_id")
    return _finish(
        "connected=true",
        _clean_calendar_next(cookie_payload.get("next")) or _CALENDAR_DEFAULT_NEXT,
    )
