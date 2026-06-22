"""
Cross-service session-token contract (#168).

The backend never sets the `sapling_session` cookie itself — the frontend
session BFF mints it (30-day `SESSION_MAX_AGE`) in a format that must stay
byte-compatible with what `auth_guard._decode_session` verifies. This test
reproduces the frontend's exact signing and asserts the backend accepts a
long-lived token (so sessions do NOT die at 5 minutes) and rejects
expired/tampered ones.

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

# Mirrors frontend/src/lib/sessionToken.ts SESSION_MAX_AGE.
FRONTEND_SESSION_MAX_AGE = 2592000  # 30 days
SHARED_SECRET = "shared-session-secret-at-least-32-bytes-long!!"


def _mint(user_id: str, ttl_seconds: int, secret: str) -> str:
    """Sign a token exactly like the backend mint AND the frontend signSession:
    base64url(no pad) JSON {"user_id","exp"} . base64url(HMAC-SHA256(payload))."""
    payload = json.dumps({"user_id": user_id, "exp": int(time.time()) + ttl_seconds}).encode()
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


def test_frontend_30_day_cookie_is_accepted_by_backend():
    token = _mint("user_alice", FRONTEND_SESSION_MAX_AGE, SHARED_SECRET)
    payload = auth_guard._real_decode_session(_request(cookie=token))
    assert payload["user_id"] == "user_alice"
    # The token is valid far beyond 5 minutes — no premature "Session expired".
    assert payload["exp"] - int(time.time()) > 29 * 24 * 3600


def test_redirect_auth_token_query_param_is_accepted():
    # The short-lived redirect token arrives as ?auth_token while fresh.
    token = _mint("user_bob", 300, SHARED_SECRET)
    payload = auth_guard._real_decode_session(_request(query=f"auth_token={token}"))
    assert payload["user_id"] == "user_bob"


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
