"""
backend/routes/auth.py

Google OAuth sign-in. Identity only (openid, email, profile): calendar access
has its own consent flow (routes/calendar_connect.py), and a student who granted it
before keeps it (services/auth/signin.py). Restricts sign-in to the configured
email domains (default @bu.edu).
"""

import asyncio
import hmac as _hmac
import logging
import re
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, ValidationError

# The module (not just its constants) so request-time gates can read the LIVE
# value of APP_ENV / SECURE_COOKIES / SESSION_SECRET instead of an import-time
# snapshot. See services/auth/dev_login.py::_test_auth_enabled.
import config
from config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_AUTH_REDIRECT_URI,
    AUTH_SCOPES,
    FRONTEND_URL,
    SESSION_SECRET,
    SECURE_COOKIES,
    APP_ENV,
)
from services import events_service
from services.auth import (
    AccountDeleted,
    AccountNotFound,
    account_overview,
    fetch_google_userinfo,
    join_waitlist,
    record_google_sign_in,
    welcome_and_achievements_after_sign_in,
)
from services.auth_guard import clear_account_state_cache, get_session_user_id, guard_off_loop
from services.session_tokens import SESSION_COOKIE_NAME, TOKEN_TYPE_HANDOFF, mint_session
# Re-exports (#118): moved names routes/calendar.py, routes/admin.py, scripts
# and tests still import from here.
from services.auth.accounts import _mark_welcomed, _stamp_last_sign_in_for_test, _welcome_due  # noqa: F401
from services.auth.dev_login import (  # noqa: F401
    TEST_AUTH_ENVS, TEST_LOGIN_DEFAULT_TTL_SECONDS, TEST_LOGIN_MAX_TTL_SECONDS, _test_auth_enabled,
)
from services.auth.oauth_state import (  # noqa: F401
    OAUTH_STATE_COOKIE, _OAUTH_COOKIE_MAX_AGE, _OAUTH_FALLBACK_STORE, _REDIRECT_TOKEN_TTL_SECONDS,
    _clamp_redirect_ttl, _clean_popup_id, _clean_return_to, _consume_oauth_nonce,
    _decode_oauth_cookie, _decode_state, _encode_oauth_cookie, _encode_state,
    _generate_pkce_pair, _google_client_config, _parse_redirect_ttl, clear_consumed_oauth_nonces,
)
from services.auth.pending import (  # noqa: F401
    _PENDING_TOKEN_TTL_SECONDS, _mint_pending_token, _pending_token_claims, _pending_token_email,
)
from services.auth.signin import _email_domain_allowed  # noqa: F401
from services.auth.waitlist import (  # noqa: F401
    _mark_waitlist_joined, _pending_standing, _waitlist_entries, _waitlist_entry,
)

try:
    from google_auth_oauthlib.flow import Flow
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleAuthRequest
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

logger = logging.getLogger(__name__)

router = APIRouter()

# Local-dev auto-approve fires ONLY for real local dev, NOT APP_ENV=test (which must
# keep the #285 approval gate). So gate on APP_ENV=="local", not the broader IS_LOCAL.
_LOCAL_AUTO_APPROVE = APP_ENV == "local"


@router.get("/me")
def get_me(request: Request):
    """Return approval and onboarding status for a given user_id."""
    # #756: reachable while unapproved — the frontend middleware reads
    # is_approved here to route that account to /pending.
    user_id = get_session_user_id(request, allow_unapproved=True)
    try:
        return account_overview(user_id)
    except AccountNotFound:
        raise HTTPException(status_code=404, detail="User not found")
    except AccountDeleted:
        raise HTTPException(status_code=401, detail="Not authenticated")


@router.get("/google")
def google_login(popup_id: str = Query(None), return_to: str = Query(None)):
    """Redirect to Google's consent screen for the identity scopes.

    ``include_granted_scopes`` makes the grant (and its tokens) also cover the
    scopes the student granted us before, so a student who connected the
    calendar keeps calendar-capable tokens across sign-ins."""
    if not GOOGLE_AVAILABLE or not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Google OAuth not configured")

    code_verifier, code_challenge = _generate_pkce_pair()
    nonce = secrets.token_urlsafe(32)
    clean_popup = _clean_popup_id(popup_id)
    # Kept in the signed state cookie, never re-read from the callback query: the
    # callback trusts only what /google validated and signed.
    clean_return_to = _clean_return_to(return_to)

    flow = Flow.from_client_config(_google_client_config(), scopes=AUTH_SCOPES)
    flow.redirect_uri = GOOGLE_AUTH_REDIRECT_URI
    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        include_granted_scopes="true",
        state=_encode_state({"action": "signin", "n": nonce}),
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )

    cookie_value = _encode_oauth_cookie({
        "n": nonce,
        "cv": code_verifier,
        "popup_id": clean_popup,
        **({"rt": clean_return_to} if clean_return_to else {}),
    })
    response = RedirectResponse(auth_url)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=cookie_value,
        max_age=_OAUTH_COOKIE_MAX_AGE,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="lax",
        path="/",
    )
    return response


#: The sign-in error code for a student who backed out of Google's screen.
SIGNIN_CANCELLED = "cancelled"

_GOOGLE_ERROR_RE = re.compile(r"^[a-z_]{1,64}$")


@router.get("/google/callback")
def google_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
):
    """Exchange auth code for tokens, validate @bu.edu, upsert user.

    Google comes back with ``error=access_denied`` and no ``code`` when the
    student cancels on its screen. That is a cancelled sign-in, not a bad
    request: it goes back through the sign-in error path as ``cancelled``
    (popup and same-tab alike), with nothing exchanged or written."""
    cookie_payload = _decode_oauth_cookie(request.cookies.get(OAUTH_STATE_COOKIE))
    code_verifier = cookie_payload.get("cv") if cookie_payload else None
    popup_id = _clean_popup_id(cookie_payload.get("popup_id")) if cookie_payload else None
    cookie_nonce = cookie_payload.get("n") if cookie_payload else None
    # Re-checked here as well as at /google, so the token only ever leaves for an
    # origin the CURRENT config allows; anything else lands on FRONTEND_URL.
    frontend_url = (
        _clean_return_to(cookie_payload.get("rt")) if cookie_payload else None
    ) or FRONTEND_URL

    def _fail_redirect(
        error_code: str, fallback_path: str = "/", extra: dict | None = None,
    ) -> RedirectResponse:
        # In popup mode, route failures through /auth/callback so the popup
        # can broadcast the error and self-close instead of stranding the opener.
        # Same-tab failures land on the landing page, which opens the sign-in
        # modal with the error's copy (#756). The frontend has no /auth page:
        # the old fallback path 404'd.
        if popup_id:
            params = urlencode({"error": error_code, "popup_id": popup_id, **(extra or {})})
            resp = RedirectResponse(f"{frontend_url}/auth/callback?{params}")
        else:
            resp = RedirectResponse(f"{frontend_url}{fallback_path}?error={error_code}")
        resp.set_cookie(
            key=OAUTH_STATE_COOKIE,
            value="",
            max_age=0,
            httponly=True,
            secure=SECURE_COOKIES,
            samesite="lax",
            path="/",
        )
        return resp

    def _not_approved(signin_email: str, signin_first_name: str) -> RedirectResponse:
        pending_token = _mint_pending_token(signin_email, signin_first_name)
        if popup_id:
            return _fail_redirect(
                "not_approved", extra={"pending_token": pending_token} if pending_token else None,
            )
        query = f"?{urlencode({'t': pending_token})}" if pending_token else ""
        resp = RedirectResponse(f"{frontend_url}/pending{query}")
        resp.set_cookie(
            key=OAUTH_STATE_COOKIE,
            value="",
            max_age=0,
            httponly=True,
            secure=SECURE_COOKIES,
            samesite="lax",
            path="/",
        )
        return resp

    if error or not code:
        logger.info(
            "google sign-in cancelled (%s)",
            error if error and _GOOGLE_ERROR_RE.match(error) else "no code",
        )
        return _fail_redirect(SIGNIN_CANCELLED)

    if not GOOGLE_AVAILABLE:
        return _fail_redirect("google_not_configured")

    state_data = _decode_state(state) if state else {}
    state_nonce = state_data.get("n")
    if not cookie_payload or not cookie_nonce or not state_nonce or not _hmac.compare_digest(str(state_nonce), str(cookie_nonce)):
        return _fail_redirect("invalid_state")
    # #756: one callback per state. Consumed before the code exchange, so a
    # replay is refused whatever the rest of this callback would have done.
    if not _consume_oauth_nonce(str(cookie_nonce)):
        return _fail_redirect("invalid_state")

    # No scopes on the exchange Flow: Google answers with the scopes granted,
    # which under include_granted_scopes is more than AUTH_SCOPES, and oauthlib
    # raises on any difference. record_google_sign_in reads the granted set
    # (oauth_state.granted_scopes) instead.
    flow = Flow.from_client_config(_google_client_config(), scopes=None)
    flow.redirect_uri = GOOGLE_AUTH_REDIRECT_URI
    try:
        flow.fetch_token(code=code, code_verifier=code_verifier)
    except Exception:
        return _fail_redirect("oauth_exchange_failed")
    creds = flow.credentials

    user_info = fetch_google_userinfo(creds.token)
    if user_info is None:
        return _fail_redirect("userinfo_fetch_failed")

    email = user_info.get("email", "")
    google_id = user_info.get("id", "")
    name = user_info.get("name", "")
    avatar_url = user_info.get("picture", "")

    # Split Google display name into first/last for the new columns
    name_parts = name.split(None, 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    # Restrict sign-in to the configured email-domain allowlist (default @bu.edu)
    if not _email_domain_allowed(email):
        return _fail_redirect("invalid_domain")

    signin = record_google_sign_in(
        email=email, google_id=google_id, name=name, first_name=first_name,
        last_name=last_name, avatar_url=avatar_url, creds=creds,
        local_auto_approve=_LOCAL_AUTO_APPROVE,
    )
    if signin.outcome == "account_deleted":
        return _fail_redirect("account_deleted")
    if signin.outcome == "not_approved":
        return _not_approved(email, first_name)
    user_id = signin.user_id
    # #756: this sign-in may just have created the account or flipped it to
    # approved (local auto-approve, waitlist re-approval above). Drop any
    # cached "missing"/"unapproved" answer so the new session is honoured on
    # its first request, not up to the guard's TTL later.
    clear_account_state_cache(user_id)

    welcome_and_achievements_after_sign_in(
        user_id, email=email, background_tasks=background_tasks,
        welcome_first_name=(user_info.get("given_name") or first_name or None),
    )

    # One-shot HMAC token so the frontend can verify this redirect without a
    # second round-trip. The frontend exchanges it for the real, long-lived
    # `sapling_session` cookie (see _REDIRECT_TOKEN_TTL_SECONDS above) — it is
    # NOT the session itself, so it expires quickly.
    #
    # Uses the shared minter (#381) with `typ=handoff` (#756): the API refuses a
    # handoff token as a credential, and the BFF exchanges nothing else, so a
    # live session can no longer be re-minted into a fresh one. The `if
    # SESSION_SECRET` guard is kept (and the secret passed explicitly) so this
    # path still degrades to "no auth_token in the redirect" rather than raising.
    auth_token = ""
    if SESSION_SECRET:
        auth_token = mint_session(
            user_id,
            ttl=_REDIRECT_TOKEN_TTL_SECONDS,
            secret=SESSION_SECRET,
            typ=TOKEN_TYPE_HANDOFF,
        )

    # #117: auth.login fires at the two real session-mint sites (here and
    # /test-login), NOT in auth_guard on session decode — decode runs on
    # every authenticated request, which would emit thousands of meaningless
    # "logins" per user per day and blow the analytics scan cap.
    events_service.log_event(
        "auth.login",
        category="audit",
        user_id=user_id,
        payload={"method": "google"},
    )

    params = urlencode({
        "user_id": user_id,
        "avatar": avatar_url,
        "is_approved": "true",
        **({"auth_token": auth_token} if auth_token else {}),
        **({"popup_id": popup_id} if popup_id else {}),
    })
    resp = RedirectResponse(f"{frontend_url}/auth/callback?{params}")
    resp.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value="",
        max_age=0,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="lax",
        path="/",
    )
    return resp


# ── POST /api/auth/test-login ─────────────────────────────────────────────────


class PendingTokenBody(BaseModel):
    token: str = Field(min_length=1, max_length=2048)


def _pending_claims(token: str) -> dict:
    """The sign-in email (and first name) a pending token carries; 401 otherwise."""
    claims = _pending_token_claims(token)
    if not claims:
        raise HTTPException(status_code=401, detail="Sign in again to continue.")
    return claims


@router.post("/pending/status")
def pending_status(body: PendingTokenBody):
    """Where an unapproved sign-in's email stands on the waitlist (/pending)."""
    email = _pending_claims(body.token)["email"]
    return _pending_standing(email, _waitlist_entry(email))


@router.post("/pending/join")
def pending_join(body: PendingTokenBody):
    """Put an unapproved sign-in's email on the waitlist. Idempotent."""
    claims = _pending_claims(body.token)
    email, first_name = claims["email"], claims["first_name"]
    entry = _waitlist_entry(email)
    try:
        join_waitlist(email, first_name, entry)
    except Exception:
        logger.exception("waitlist join from /pending failed")
        raise HTTPException(
            status_code=500, detail="Could not join the waitlist. Please try again.",
        )
    return {**_pending_standing(email, entry), "on_waitlist": True}


class MintTestSessionBody(BaseModel):
    """Body of POST /api/auth/test-login."""

    user_id: str = Field(min_length=1, max_length=255)
    ttl: int | None = Field(
        default=None,
        description="Session lifetime in seconds; clamped to [30, 86400].",
    )


@router.post("/test-login", include_in_schema=False)
async def mint_test_session(request: Request):
    """Mint a `sapling_session` cookie for a seeded user. LOCAL/TEST ONLY (#381).

    `GET /api/auth/dev-login` was removed and real Google OAuth cannot be driven
    headlessly, so the pytest integration suite and Playwright's global setup need
    a sanctioned way to obtain a session. This is that seam — and nothing more:
    it is NOT a sign-in flow, it is not browser-facing, and it must never be
    linked from the frontend.

    SECURITY
    - Hard-gated on `APP_ENV in {"local", "test"}` (see TEST_AUTH_ENVS), read at
      request time. Anywhere else this returns a plain 404 with the stock
      "Not Found" body — deliberately not 403, so the endpoint does not even
      advertise that it exists. `include_in_schema=False` keeps it out of
      /openapi.json in every environment for the same reason.
    - It performs NO credential check by design; the environment gate is the only
      thing standing between a caller and an arbitrary account. That is why the
      allowlist is two exact strings rather than the broader `config.IS_LOCAL`.
    - It does not touch the database: it neither creates users nor grants
      approval/roles. A token minted for an id with no `users` row (or a
      deleted or unapproved one) is refused by the auth guard (#756: 401, or
      403 `not_approved`) before any route runs — so it gets nowhere, and no
      `ensure_user_exists` stub row is created for it.

    Returns the token in the JSON body as well as in the cookie, so a Playwright
    global-setup step can inject it with `context.addCookies()` instead of
    replaying the response. `handoff_token` is the same user's OAuth-redirect
    token (`typ=handoff`, #756), for a journey that drives /auth/callback the
    way a real sign-in does: the session BFF exchanges only that type.
    """
    # The gate runs FIRST, before the body is even looked at. The body is parsed
    # and validated by hand rather than declared as a `MintTestSessionBody`
    # parameter precisely for this: FastAPI validates declared body params
    # *before* entering the handler, so in production a malformed body would have
    # answered 422 — and a 422 from a path that "does not exist" is exactly the
    # disclosure the 404 is there to prevent. Now every request shape gets the
    # same stock 404 outside local/test.
    if not _test_auth_enabled():
        raise HTTPException(status_code=404, detail="Not Found")

    try:
        raw = await request.json()
    except Exception:
        raw = None
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object.")
    try:
        body = MintTestSessionBody.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=[
                {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                for e in exc.errors()
            ],
        )

    user_id = body.user_id.strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id must not be blank")

    secret = (getattr(config, "SESSION_SECRET", "") or "").strip()
    if not secret:
        # config.validate_config() relaxes the SESSION_SECRET requirement for
        # IS_LOCAL, so local dev can legitimately have none. Fail loudly instead
        # of handing back a token _decode_session would reject anyway.
        raise HTTPException(
            status_code=500,
            detail="SESSION_SECRET is not configured; cannot mint a test session.",
        )

    requested = TEST_LOGIN_DEFAULT_TTL_SECONDS if body.ttl is None else body.ttl
    ttl = max(30, min(int(requested), TEST_LOGIN_MAX_TTL_SECONDS))
    token = mint_session(user_id, ttl=ttl, secret=secret)
    handoff_token = mint_session(
        user_id, ttl=_REDIRECT_TOKEN_TTL_SECONDS, secret=secret, typ=TOKEN_TYPE_HANDOFF
    )

    logger.warning("test-login: minted a session for %r (APP_ENV=%s)", user_id, config.APP_ENV)

    # #117: the second real session-mint site (see google_callback for why
    # auth.login is emitted at mint time, not on session decode).
    events_service.log_event(
        "auth.login",
        category="audit",
        user_id=user_id,
        payload={"method": "test_login"},
    )

    response = JSONResponse({
        "ok": True,
        "user_id": user_id,
        "cookie_name": SESSION_COOKIE_NAME,
        "token": token,
        "handoff_token": handoff_token,
        "expires_in": ttl,
    })
    # Same attributes the real session cookie carries (frontend BFF
    # /api/auth/session and the OAuth-state cookie above).
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=ttl,
        httponly=True,
        secure=bool(getattr(config, "SECURE_COOKIES", False)),
        samesite="lax",
        path="/",
    )
    return response


# ── GET /api/auth/local-seed ──────────────────────────────────────────────────


@router.get("/local-seed", include_in_schema=False)
async def local_seed_status(request: Request):
    """Where the signed-in account's local sample data stands (#715). LOCAL ONLY.

    On a developer's local stack, services/local_seed_watcher.py copies the
    rich sample dataset onto each Google account. The post-sign-in routing asks
    here first: `pending`/`seeding` sends a new account to the hold screen
    instead of /onboarding, `ready` straight to the dashboard, `failed` (with
    `error`) offers to continue to onboarding anyway.

    404 — the frontend's cue to keep its normal routing — whenever the watcher
    would not run (any non-local backend, gated per REQUEST on the same
    predicate as the seed CLI's guard, checked before the session) and for any
    account the watcher never seeds: a non-Google fixture account, a missing
    or soft-deleted one, an ensure_user_exists stub (no google_id). A `pending`
    answer wakes the watcher so a fresh sign-in waits one seed, not a poll.
    """
    from services import local_seed_watcher

    if not local_seed_watcher.watcher_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    user_id = await guard_off_loop(get_session_user_id, request)
    if not local_seed_watcher.is_oauth_account(user_id):
        raise HTTPException(status_code=404, detail="Not Found")
    status = await asyncio.to_thread(local_seed_watcher.status_for, user_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Not Found")
    if status["state"] == "pending":
        local_seed_watcher.nudge()
    return status


# ── GET /api/auth/realtime-token (RLS step 2e) ────────────────────────────────

#: ``detail.code`` of the ONE 503 the browser treats as "no live chat for this
#: page session" (frontend/src/lib/realtimeAuth.ts): the signing key is unset
#: or unusable, which no retry can fix. Every other 5xx on this route (the
#: session guard's account-state read, a restart, a cold start) carries no
#: such code, and the client retries it with backoff.
REALTIME_UNCONFIGURED = "realtime_unconfigured"

@router.get("/realtime-token")
def realtime_token(request: Request):
    """A short-lived JWT the browser's Supabase Realtime client authenticates
    with (``supabase.realtime.setAuth``), the only way to receive live
    study-room chat: ``room_messages`` has RLS on and no anon SELECT
    (20261109073255_room_messages_rls_enable.sql;
    docs/security/realtime-jwt-bridge-design.md).

    One general token per student, not per room: the room_messages SELECT
    policy (``app_auth.is_room_member_realtime``) does the scoping, and
    Realtime re-checks it for every change. ``iss`` is ``sapling-realtime``,
    which no other policy trusts. Answers ``{token, expires_at}`` (unix
    seconds); the client re-fetches before ``expires_at``.

    401/403 without a live, approved session; 503 with
    ``detail.code == "realtime_unconfigured"`` when SUPABASE_JWT_SIGNING_KEY
    is unset or unusable (fail closed: never a service-role or anon fallback;
    the room then works over REST only). Any other 503 (e.g. the guard could
    not read the account) is transient and has no such code. ``no-store``: it
    is a credential. No feature flag: the endpoint stopped reading
    ``realtime_rls`` with the anon path's removal (the flag stays registered
    one release for old bundles only; see services/feature_flags.py).
    """
    from db import user_jwt

    user_id = get_session_user_id(request)
    try:
        token, expires_at = user_jwt.mint_realtime(user_id)
    except user_jwt.SigningKeyError as exc:
        logger.warning("realtime-token: cannot mint (%s)", exc)
        raise HTTPException(
            status_code=503,
            detail={
                "code": REALTIME_UNCONFIGURED,
                "message": "Realtime authorization is not configured",
            },
        )
    return JSONResponse(
        {"token": token, "expires_at": expires_at},
        headers={"Cache-Control": "private, no-store"},
    )
