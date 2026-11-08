"""RLS step 2e: GET /api/auth/realtime-token and db/user_jwt.py::mint_realtime.

docs/security/realtime-jwt-bridge-design.md. Hermetic: the session guard is
patched, the flag resolves through its env override, and the signing key is a
test JWK. What is pinned:

* the token: iss ``sapling-realtime`` (never ``sapling-api``, which
  app_auth.uid() trusts), sub = the session user, role/aud authenticated,
  exp = iat + REALTIME_TOKEN_TTL_S, signed with SUPABASE_JWT_SIGNING_KEY
  (HS256 verified here; ES256 shares the signer with mint());
* the gate: no session -> 401, flag off -> 404, key unset/unusable -> 503
  (fail closed), ``Cache-Control: private, no-store``;
* the flag: registered off-first and client-visible (Social.tsx reads it);
* mint() for the backend's own token is unchanged by the refactor.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from db import user_jwt
from main import app
from services import feature_flags as ff

client = TestClient(app)

SECRET = b"super-secret-jwt-token-with-at-least-32-characters-long"
OCT_JWK = json.dumps({"kty": "oct", "k": base64.urlsafe_b64encode(SECRET).rstrip(b"=").decode()})
FLAG_ENV = "SAPLING_FLAG_REALTIME_RLS"
URL = "/api/auth/realtime-token"


def _b64d(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _decode(token: str) -> tuple[dict, dict, bytes, bytes]:
    h, p, s = token.split(".")
    return json.loads(_b64d(h)), json.loads(_b64d(p)), f"{h}.{p}".encode(), _b64d(s)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    user_jwt.clear_token_cache()
    monkeypatch.delenv(user_jwt.SIGNING_KEY_ENV, raising=False)
    monkeypatch.delenv(FLAG_ENV, raising=False)
    yield
    user_jwt.clear_token_cache()


def _signed_in(user_id="user_rt"):
    return patch("routes.auth.get_session_user_id", return_value=user_id)


# ── mint_realtime ──────────────────────────────────────────────────────────


def test_mint_realtime_claims_and_hs256_signature(monkeypatch):
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    token, exp = user_jwt.mint_realtime("user_rt", now=1_000_000)
    header, claims, signing_input, sig = _decode(token)
    assert header == {"alg": "HS256", "typ": "JWT"}
    assert claims == {
        "iss": "sapling-realtime", "sub": "user_rt", "role": "authenticated",
        "aud": "authenticated", "iat": 1_000_000, "exp": 1_000_000 + user_jwt.REALTIME_TOKEN_TTL_S,
    }
    assert exp == claims["exp"]
    assert hmac.compare_digest(sig, hmac.new(SECRET, signing_input, hashlib.sha256).digest())


def test_realtime_issuer_is_not_the_backend_issuer():
    # app_auth.uid() (every policy but room_messages SELECT) trusts ISSUER
    # only. If these ever matched, a browser token would be a full user token.
    assert user_jwt.REALTIME_ISSUER == "sapling-realtime"
    assert user_jwt.REALTIME_ISSUER != user_jwt.ISSUER


def test_mint_realtime_uses_the_clock_seam(monkeypatch):
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    monkeypatch.setattr(user_jwt, "_now", lambda: 2_000_000)
    token, exp = user_jwt.mint_realtime("u1")
    assert _decode(token)[1]["iat"] == 2_000_000
    assert exp == 2_000_000 + user_jwt.REALTIME_TOKEN_TTL_S


def test_mint_realtime_needs_a_subject_and_a_key(monkeypatch):
    with pytest.raises(user_jwt.SigningKeyError):
        user_jwt.mint_realtime("u1")
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    with pytest.raises(ValueError):
        user_jwt.mint_realtime("")


def test_backend_token_is_unchanged_by_the_refactor(monkeypatch):
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    _, claims, signing_input, sig = _decode(user_jwt.mint("u1", now=1_000_000))
    assert claims == {"iss": "sapling-api", "sub": "u1", "role": "authenticated",
                      "aud": "authenticated", "iat": 1_000_000,
                      "exp": 1_000_000 + user_jwt.TOKEN_TTL_S}
    assert hmac.compare_digest(sig, hmac.new(SECRET, signing_input, hashlib.sha256).digest())


# ── GET /api/auth/realtime-token ────────────────────────────────────────────


def test_flag_on_returns_a_token_for_the_session_user(monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "on")
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    with _signed_in("user_rt"):
        r = client.get(URL)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"token", "expires_at"}
    _, claims, _, _ = _decode(body["token"])
    assert (claims["iss"], claims["sub"], claims["role"]) == ("sapling-realtime", "user_rt", "authenticated")
    assert body["expires_at"] == claims["exp"]
    assert claims["exp"] - claims["iat"] == user_jwt.REALTIME_TOKEN_TTL_S
    assert r.headers["cache-control"] == "private, no-store"


def test_flag_off_is_404_and_mints_nothing(monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "off")
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    with _signed_in(), patch.object(user_jwt, "mint_realtime") as mint:
        r = client.get(URL)
    assert r.status_code == 404
    mint.assert_not_called()


def test_flag_is_resolved_for_the_session_user(monkeypatch):
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    with _signed_in("user_rt"), \
         patch("services.feature_flags.flag_on", return_value=True) as flag_on:
        r = client.get(URL)
    assert r.status_code == 200
    flag_on.assert_called_once_with("realtime_rls", "user_rt")


def test_no_session_is_401_before_any_flag_read(monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "on")
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    with patch("routes.auth.get_session_user_id",
               side_effect=HTTPException(status_code=401, detail="Not authenticated")), \
         patch("services.feature_flags.flag_on") as flag_on:
        r = client.get(URL)
    assert r.status_code == 401
    flag_on.assert_not_called()


def test_unset_signing_key_fails_closed_503(monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "on")
    with _signed_in():
        r = client.get(URL)
    assert r.status_code == 503
    assert "token" not in r.text


@pytest.mark.parametrize("bad", ["not json", '{"kty": "oct", "k": "c2hvcnQ"}', '{"kty": "RSA"}'])
def test_unusable_signing_key_fails_closed_503(monkeypatch, bad):
    monkeypatch.setenv(FLAG_ENV, "on")
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, bad)
    with _signed_in():
        r = client.get(URL)
    assert r.status_code == 503


# ── The flag ────────────────────────────────────────────────────────────────


def test_realtime_rls_flag_is_off_first_and_client_visible():
    fd = ff.REGISTRY["realtime_rls"]
    assert fd.variants == ("off", "on")
    assert fd.client_visible  # frontend Social.tsx: useFlag("realtime_rls")


def test_realtime_rls_defaults_off_with_no_stored_config(monkeypatch):
    with patch("services.feature_flags._get_snapshot", return_value=ff.Snapshot(flags={}, targets={})):
        assert ff.flag_variant("realtime_rls", "user_rt") == "off"
