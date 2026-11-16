"""RLS step 2e: GET /api/auth/realtime-token and db/user_jwt.py::mint_realtime.

docs/security/realtime-jwt-bridge-design.md. Hermetic: the session guard is
patched and the signing key is a test JWK. What is pinned:

* the token: iss ``sapling-realtime`` (never ``sapling-api``, which
  app_auth.uid() trusts), sub = the session user, role/aud authenticated,
  exp = iat + REALTIME_TOKEN_TTL_S, signed with SUPABASE_JWT_SIGNING_KEY
  (HS256 verified here; ES256 shares the signer with mint());
* the gate: no session -> 401, key unset/unusable -> 503 with
  ``detail.code == "realtime_unconfigured"`` (fail closed; the ONE reason the
  browser stops asking for the page session), a transient 503 (the session
  guard's account-state read) carries no such code,
  ``Cache-Control: private, no-store``;
* no flag: the endpoint and Social.tsx stopped reading ``realtime_rls`` (the
  anon Realtime path is gone and room_messages has RLS on everywhere), so an
  env override left behind on a deploy cannot switch the endpoint off. The
  flag itself stays registered and client-visible for one release, for
  frontend bundles older than this change;
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
RETIRED_FLAG_ENV = "SAPLING_FLAG_REALTIME_RLS"
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
    monkeypatch.delenv(RETIRED_FLAG_ENV, raising=False)
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


def test_mint_realtime_expires_at_is_the_signed_exp(monkeypatch):
    """`expires_at` is the `exp` _sign put in the token, not a recomputation:
    a clock that moves between reads cannot make the two disagree."""
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    ticks = iter(range(3_000_000, 3_000_100))
    monkeypatch.setattr(user_jwt, "_now", lambda: next(ticks))
    for _ in range(3):
        token, exp = user_jwt.mint_realtime("u1")
        assert exp == _decode(token)[1]["exp"]


def test_mint_realtime_returns_whatever_exp_sign_signed(monkeypatch):
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    real_sign = user_jwt._sign
    seen = {}

    def spy(subject, issuer, ttl_s, now):
        token, exp = real_sign(subject, issuer, ttl_s, now)
        seen["exp"] = exp
        return token, exp

    monkeypatch.setattr(user_jwt, "_sign", spy)
    token, exp = user_jwt.mint_realtime("u1", now=4_000_000)
    assert exp == seen["exp"] == _decode(token)[1]["exp"]


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


def test_returns_a_token_for_the_session_user(monkeypatch):
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


def test_no_flag_is_consulted(monkeypatch):
    # Graduated: neither the flag store nor a stale SAPLING_FLAG_REALTIME_RLS=off
    # left on a deploy can turn the only live-chat path off.
    monkeypatch.setenv(RETIRED_FLAG_ENV, "off")
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    with _signed_in("user_rt"), \
         patch("services.feature_flags.flag_on") as flag_on, \
         patch("services.feature_flags.flag_variant") as flag_variant:
        r = client.get(URL)
    assert r.status_code == 200
    flag_on.assert_not_called()
    flag_variant.assert_not_called()


def test_no_session_is_401_and_mints_nothing(monkeypatch):
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    with patch("routes.auth.get_session_user_id",
               side_effect=HTTPException(status_code=401, detail="Not authenticated")), \
         patch.object(user_jwt, "mint_realtime") as mint:
        r = client.get(URL)
    assert r.status_code == 401
    mint.assert_not_called()


def _detail_code(r) -> str | None:
    detail = r.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


def test_unset_signing_key_fails_closed_503(monkeypatch):
    with _signed_in():
        r = client.get(URL)
    assert r.status_code == 503
    assert "token" not in r.json()
    assert _detail_code(r) == "realtime_unconfigured"


@pytest.mark.parametrize("bad", ["not json", '{"kty": "oct", "k": "c2hvcnQ"}', '{"kty": "RSA"}'])
def test_unusable_signing_key_fails_closed_503(monkeypatch, bad):
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, bad)
    with _signed_in():
        r = client.get(URL)
    assert r.status_code == 503
    assert _detail_code(r) == "realtime_unconfigured"


def test_a_transient_503_is_not_the_unconfigured_reason(monkeypatch):
    # The session guard 503s when it cannot read the account
    # (services/auth_guard.py::account_state). The browser must retry that
    # one, so it must not carry the code that stops live chat for the page.
    from services import auth_guard

    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    auth_guard.clear_account_state_cache()
    # conftest stubs the guard everywhere; run the real one for this request.
    with patch("routes.auth.get_session_user_id", side_effect=auth_guard._real_get_session_user_id), \
         patch("services.auth_guard._decode_session", return_value={"user_id": "user_rt"}), \
         patch("services.auth_guard._read_account_state", side_effect=RuntimeError("db down")), \
         patch.object(user_jwt, "mint_realtime") as mint:
        r = client.get(URL)
    assert r.status_code == 503
    assert _detail_code(r) != "realtime_unconfigured"
    assert "realtime_unconfigured" not in r.text
    mint.assert_not_called()


# ── The flag kept for old bundles ───────────────────────────────────────────


def test_realtime_rls_stays_registered_for_old_bundles():
    # Kept one release so a browser on the previous bundle, which reads it
    # from GET /api/flags and takes the (now dead) anon path unless it is
    # "on", keeps live chat until it reloads. Deleted, with its stored rows,
    # in the follow-up.
    fd = ff.REGISTRY["realtime_rls"]
    assert fd.client_visible
    assert fd.variants == ("off", "on")


def test_nothing_in_this_release_reads_realtime_rls():
    # Only the registry may name the key as a value; a comment may mention it.
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    reads = re.compile(r"""["']realtime_rls["']|\.realtime_rls\b""")
    offenders = []
    sources = [p for p in (root / "backend").rglob("*.py")
               if not ({"venv", ".venv", "tests", "site-packages"} & set(p.parts))]
    sources += [p for ext in ("ts", "tsx") for p in (root / "frontend" / "src").rglob(f"*.{ext}")
                if not re.search(r"\.test\.tsx?$", p.name)]
    for path in sources:
        if path.name == "feature_flags.py":
            continue
        if reads.search(path.read_text(encoding="utf-8", errors="replace")):
            offenders.append(str(path.relative_to(root)))
    assert not offenders, f"new code must not read the old-bundle-only flag: {offenders}"
