"""
Cross-service session-token contract (#168).

In every deployed environment the backend never sets the `sapling_session`
cookie itself — the frontend session BFF mints it (7-day `SESSION_MAX_AGE`, with
an `iat` claim) in a format that must stay compatible with what
`auth_guard._decode_session` verifies. (The one exception is `POST
/api/auth/test-login`, gated to `APP_ENV in {local, test}`; see
test_auth_test_login.py.) These tests assert the backend accepts a long-lived
token in that format (so sessions do NOT die at 5 minutes), still reads a
pre-`iat` 30-day cookie until it is 7 days old, and rejects expired/tampered
ones.

Scope caveat: `_mint` below is a Python re-implementation of the format, so this
suite verifies the backend decoder against a locally-minted token — it does not
execute the frontend's `signSession`, and so cannot catch drift on the frontend
side. A shared JSON fixture consumed by both this suite and a frontend test
would be the real cross-service lock; see the ADR follow-ups.

See docs/decisions/0018-session-token-lifecycle.md.
"""
import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from services import auth_guard

# Mirrors frontend/src/lib/sessionToken.ts SESSION_MAX_AGE (and backend
# config.SESSION_MAX_AGE_SECONDS).
FRONTEND_SESSION_MAX_AGE = 604800  # 7 days
# What the BFF minted before `iat` existed.
LEGACY_SESSION_MAX_AGE = 2592000  # 30 days
SHARED_SECRET = "shared-session-secret-at-least-32-bytes-long!!"


def _mint(user_id: str, ttl_seconds: int, secret: str, *, iat: int | None = None,
          legacy: bool = False) -> str:
    """Mint a token in the shape both services use:
    base64url(no pad) JSON {"user_id","exp","iat"} . base64url(HMAC-SHA256(payload_b64)).

    #756 added a `typ` claim to every NEW token; this one deliberately omits it,
    which the decoder must keep reading as a session. `legacy=True` also omits
    `iat`, the format the BFF minted before server-side revocation (30-day
    cookies), which the decoder dates as `exp - 30 days`.

    This mirrors the *backend* mint (services/session_tokens.mint_session)
    byte-for-byte. It is close to, but not byte-identical with, the frontend's
    signSession: Python's json.dumps emits `{"user_id": "x", "exp": 1}` (with
    spaces) where JS JSON.stringify emits `{"user_id":"x","exp":1}` (without).
    That difference is immaterial to the contract under test — the verifier HMACs
    the received `payload_b64` opaquely and never re-serializes the payload — but
    it does mean this helper is a Python re-implementation of the format, so
    these tests prove a *Python-minted* token is accepted, not a real
    frontend-minted one. See the ADR follow-ups for the shared-fixture idea that
    would close that gap.

    Kept deliberately independent of session_tokens.mint_session even after #381
    unified the production copies: its whole job is to pin the wire format from
    the outside, which it could not do by calling the code under test.
    (test_auth_test_login.py asserts the two agree byte-for-byte.)
    """
    now = int(time.time()) if iat is None else iat
    claims = {"user_id": user_id, "exp": now + ttl_seconds}
    if not legacy:
        claims["iat"] = now
    payload = json.dumps(claims).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{payload_b64}.{sig_b64}"


def _request(cookie: str | None = None, query: str = "") -> Request:
    headers = []
    if cookie is not None:
        headers.append((b"cookie", f"sapling_session={cookie}".encode()))
    scope = {
        "type": "http", "method": "GET", "path": "/",
        "headers": headers, "query_string": query.encode(),
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _shared_secret(monkeypatch):
    monkeypatch.setattr(auth_guard, "SESSION_SECRET", SHARED_SECRET)


def test_frontend_7_day_cookie_is_accepted_by_backend():
    token = _mint("user_alice", FRONTEND_SESSION_MAX_AGE, SHARED_SECRET)
    payload = auth_guard._real_decode_session(_request(cookie=token))
    assert payload["user_id"] == "user_alice"
    # The token is valid far beyond 5 minutes — no premature "Session expired".
    assert payload["exp"] - int(time.time()) > 6 * 24 * 3600


def test_session_older_than_the_max_age_is_expired_whatever_its_exp():
    """A session lives at most config.SESSION_MAX_AGE_SECONDS from `iat`, even
    when its `exp` says otherwise (a token minted with a longer lifetime)."""
    old = int(time.time()) - FRONTEND_SESSION_MAX_AGE - 60
    token = _mint("user_alice", LEGACY_SESSION_MAX_AGE, SHARED_SECRET, iat=old)
    with pytest.raises(HTTPException) as exc:
        auth_guard._real_decode_session(_request(cookie=token))
    assert exc.value.detail == "Session expired"


def test_session_issued_in_the_future_is_rejected():
    token = _mint("user_alice", 3600, SHARED_SECRET, iat=int(time.time()) + 3600)
    with pytest.raises(HTTPException) as exc:
        auth_guard._real_decode_session(_request(cookie=token))
    assert exc.value.status_code == 401


def test_legacy_30_day_cookie_without_iat_lives_7_days_from_issue():
    """A cookie the BFF minted before `iat` existed (30-day `exp`) is dated
    `exp - 30 days`: honoured while younger than 7 days, then expired."""
    fresh = _mint("user_alice", LEGACY_SESSION_MAX_AGE, SHARED_SECRET, legacy=True)
    payload = auth_guard._real_decode_session(_request(cookie=fresh))
    assert payload["user_id"] == "user_alice"
    eight_days_ago = int(time.time()) - 8 * 86400
    stale = _mint("user_alice", LEGACY_SESSION_MAX_AGE, SHARED_SECRET, iat=eight_days_ago, legacy=True)
    with pytest.raises(HTTPException) as exc:
        auth_guard._real_decode_session(_request(cookie=stale))
    assert exc.value.detail == "Session expired"


def test_auth_token_query_param_is_not_a_credential():
    """`?auth_token=` used to be read before the cookie, though no client sent
    it: routes/auth.py puts the redirect token in a URL pointing at the
    *frontend*, and frontend/src/app/auth/callback/page.tsx reads it there and
    POSTs it to the session BFF in a JSON body. Session tokens in URLs leak via
    access logs, Referer headers and browser history, so the channel is gone:
    a perfectly valid session in the query string authenticates nothing."""
    token = _mint("user_bob", FRONTEND_SESSION_MAX_AGE, SHARED_SECRET)
    with pytest.raises(HTTPException) as exc:
        auth_guard._real_decode_session(_request(query=f"auth_token={token}"))
    assert exc.value.status_code == 401
    assert auth_guard.presented_session_token(_request(query=f"auth_token={token}")) is None
    # The same token in the cookie is accepted, and the cookie wins over a query param.
    both = _request(cookie=token, query="auth_token=garbage.sig")
    assert auth_guard._real_decode_session(both)["user_id"] == "user_bob"


def test_expired_token_is_rejected():
    token = _mint("user_alice", -10, SHARED_SECRET)
    with pytest.raises(HTTPException) as exc:
        auth_guard._real_decode_session(_request(cookie=token))
    assert exc.value.status_code == 401
    assert exc.value.detail == "Session expired"


def test_tampered_signature_is_rejected():
    token = _mint("user_alice", FRONTEND_SESSION_MAX_AGE, SHARED_SECRET)
    payload_b64, sig_b64 = token.split(".")
    flipped = "A" if sig_b64[0] != "A" else "B"
    tampered = f"{payload_b64}.{flipped}{sig_b64[1:]}"
    with pytest.raises(HTTPException) as exc:
        auth_guard._real_decode_session(_request(cookie=tampered))
    assert exc.value.status_code == 401


def test_token_signed_with_a_different_secret_is_rejected():
    token = _mint("user_alice", FRONTEND_SESSION_MAX_AGE, "some-other-secret-value-32-bytes-xxxxx")
    with pytest.raises(HTTPException) as exc:
        auth_guard._real_decode_session(_request(cookie=token))
    assert exc.value.status_code == 401


def test_redirect_token_ttl_default_is_short():
    import routes.auth as auth
    # The redirect handoff token must stay short — it is not the session.
    assert auth._REDIRECT_TOKEN_TTL_SECONDS <= 600


def test_redirect_token_ttl_override_is_clamped():
    import routes.auth as auth
    # A misconfigured/hostile env override cannot lengthen the URL-borne
    # handoff token beyond the 600s ceiling, and cannot drop below the 30s floor.
    assert auth._clamp_redirect_ttl(86400) == 600
    assert auth._clamp_redirect_ttl(5) == 30
    assert auth._clamp_redirect_ttl(300) == 300


@pytest.mark.parametrize("raw", ["abc", "", "   ", "300s", "1e3", None])
def test_malformed_redirect_ttl_override_falls_back_instead_of_crashing(raw):
    """A malformed override must not break module import.

    routes.auth is imported at router-mount time, so an unguarded int() on the
    env var would raise ValueError and stop the app from booting. Empty-string is
    the realistic case: declaring the var in Railway/Wrangler without a value.
    """
    import routes.auth as auth
    assert auth._parse_redirect_ttl(raw) == 300


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("60", 60), ("86400", 600), ("5", 30), (" 300 ", 300)],
)
def test_wellformed_redirect_ttl_override_is_parsed_and_clamped(raw, expected):
    import routes.auth as auth
    assert auth._parse_redirect_ttl(raw) == expected


def test_malformed_redirect_ttl_override_warns(caplog):
    import routes.auth as auth
    with caplog.at_level("WARNING", logger="services.auth.oauth_state"):
        auth._parse_redirect_ttl("abc")
    assert "SAPLING_AUTH_REDIRECT_TOKEN_TTL" in caplog.text
