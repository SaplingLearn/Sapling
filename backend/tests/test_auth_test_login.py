"""
Tests for the test-only session-minting endpoint `POST /api/auth/test-login` (#381).

`GET /api/auth/dev-login` was removed and real Google OAuth is not headless-
automatable, so pytest and the Playwright global setup need a sanctioned way to
obtain an authenticated session. This endpoint mints the same HMAC
`sapling_session` cookie that `services/auth_guard._decode_session` verifies.

The security-critical properties asserted here:

- It returns **404** (not 403) outside `APP_ENV in {"local", "test"}`, with the
  stock FastAPI "Not Found" body, so it does not advertise its own existence.
- The allowed set is deliberately NARROWER than `config.IS_LOCAL`
  (`{local, development, dev, test}`) — `development`/`dev` must 404 too.
- The gate is evaluated per REQUEST off the live `config` module attribute, so
  no import-order accident can freeze it open.
- The minted cookie is not merely string-shaped: it round-trips through the real
  `auth_guard` decoder.
- The unified `services.session_tokens.mint_session` is byte-identical to the
  format the decoder verifies, and the two former copies of that code now
  delegate to it instead of re-implementing it.
"""
import base64
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import config
import routes.auth as auth_module
from services import auth_guard, session_tokens

SECRET = "test-login-shared-session-secret-at-least-32-bytes"
FROZEN_NOW = 1_700_000_000


def _reference_token(user_id: str, exp: int, secret: str) -> str:
    """Independent re-implementation of the token format `_decode_session` verifies.

    Deliberately written out longhand (not via session_tokens) so that a change
    to the canonical helper that broke the wire format would fail this test.
    """
    payload = json.dumps({"user_id": user_id, "exp": exp}).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return f"{payload_b64}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


@pytest.fixture
def secrets_wired(monkeypatch):
    """Point the minter and the verifier at the same secret, and keep cookies
    non-Secure so TestClient's (plain http) jar actually stores them."""
    monkeypatch.setattr(config, "SESSION_SECRET", SECRET)
    monkeypatch.setattr(config, "SECURE_COOKIES", False)
    monkeypatch.setattr(auth_guard, "SESSION_SECRET", SECRET)


@pytest.fixture
def client(secrets_wired):
    """Minimal app: just the auth router plus a probe that runs the REAL decoder.

    conftest's autouse `_bypass_session_auth` stubs `auth_guard._decode_session`
    for the rest of the suite and stashes the original on `_real_decode_session`;
    the probe uses the original so the round-trip is genuine.
    """
    app = FastAPI()
    app.include_router(auth_module.router, prefix="/api/auth")

    @app.get("/probe")
    def _probe(request: Request):
        return auth_guard._real_decode_session(request)

    return TestClient(app)


# ── Production gate ───────────────────────────────────────────────────────────


class TestProductionGate:
    def test_returns_404_under_production(self, client, monkeypatch):
        monkeypatch.setattr(config, "APP_ENV", "production")
        resp = client.post("/api/auth/test-login", json={"user_id": "user_alice"})
        assert resp.status_code == 404
        # Indistinguishable from a route that does not exist.
        assert resp.json() == {"detail": "Not Found"}
        # And nothing was handed out.
        assert "sapling_session" not in resp.headers.get("set-cookie", "")
        assert "sapling_session" not in client.cookies

    @pytest.mark.parametrize(
        "app_env",
        [
            "production",
            "staging",
            # `development`/`dev` ARE in config.IS_LOCAL. This endpoint uses a
            # strictly narrower allowlist, so they must still 404.
            "development",
            "dev",
            "",
            "prod",
            "localhost",
            "testing",
        ],
    )
    def test_returns_404_outside_local_and_test(self, client, monkeypatch, app_env):
        monkeypatch.setattr(config, "APP_ENV", app_env)
        resp = client.post("/api/auth/test-login", json={"user_id": "user_alice"})
        assert resp.status_code == 404, f"APP_ENV={app_env!r} must not expose test-login"

    def test_allowlist_is_narrower_than_is_local(self):
        assert auth_module.TEST_AUTH_ENVS == frozenset({"local", "test"})
        # Guard the intent: IS_LOCAL is broader, and we must not drift onto it.
        assert {"development", "dev"} - auth_module.TEST_AUTH_ENVS == {"development", "dev"}

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"json": {}},                                   # missing user_id -> would be 422
            {"json": {"user_id": ""}},                      # too short -> would be 422
            {"json": {"user_id": "u", "ttl": "not-an-int"}},  # bad type -> would be 422
            {"json": []},                                   # not an object
            {"content": b"not json at all"},                # unparseable body
            {},                                             # no body at all
        ],
    )
    def test_production_answers_404_for_every_body_shape(self, client, monkeypatch, kwargs):
        """A 422 from a path that "does not exist" is exactly the disclosure the
        404 exists to prevent. FastAPI validates *declared* body params before the
        handler runs, so the gate must be reached before any body parsing."""
        monkeypatch.setattr(config, "APP_ENV", "production")
        resp = client.post("/api/auth/test-login", **kwargs)
        assert resp.status_code == 404, f"leaked {resp.status_code} for {kwargs}"
        assert resp.json() == {"detail": "Not Found"}

    def test_production_404_matches_a_genuinely_absent_path(self, client, monkeypatch):
        monkeypatch.setattr(config, "APP_ENV", "production")
        gated = client.post("/api/auth/test-login", json={"user_id": "u"})
        absent = client.post("/api/auth/no-such-endpoint", json={"user_id": "u"})
        assert (gated.status_code, gated.json()) == (absent.status_code, absent.json())

    def test_route_exists_but_is_gated(self, client, monkeypatch):
        """404 must come from the gate, not from an unmounted route — otherwise
        this test would pass trivially even if the endpoint were deleted."""
        paths = {getattr(r, "path", None) for r in client.app.routes}
        assert "/api/auth/test-login" in paths
        monkeypatch.setattr(config, "APP_ENV", "production")
        assert client.post("/api/auth/test-login", json={"user_id": "u"}).status_code == 404

    def test_gate_is_evaluated_at_request_time(self, client, monkeypatch):
        """`config.APP_ENV` is read at import time by other modules; this gate must
        not be. Flip it back and forth against a single live app instance."""
        monkeypatch.setattr(config, "APP_ENV", "production")
        assert client.post("/api/auth/test-login", json={"user_id": "u"}).status_code == 404
        monkeypatch.setattr(config, "APP_ENV", "local")
        assert client.post("/api/auth/test-login", json={"user_id": "u"}).status_code == 200
        monkeypatch.setattr(config, "APP_ENV", "production")
        assert client.post("/api/auth/test-login", json={"user_id": "u"}).status_code == 404

    def test_hidden_from_the_openapi_schema(self, client, monkeypatch):
        monkeypatch.setattr(config, "APP_ENV", "local")
        assert "/api/auth/test-login" not in client.app.openapi().get("paths", {})


# ── Success path ──────────────────────────────────────────────────────────────


class TestMintsAcceptedSession:
    @pytest.mark.parametrize("app_env", ["local", "test", "LOCAL", " Test "])
    def test_success_under_local_and_test(self, client, monkeypatch, app_env):
        monkeypatch.setattr(config, "APP_ENV", app_env)
        resp = client.post("/api/auth/test-login", json={"user_id": "user_alice"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["user_id"] == "user_alice"

    def test_sets_a_cookie_the_real_auth_guard_accepts(self, client, monkeypatch):
        monkeypatch.setattr(config, "APP_ENV", "test")
        resp = client.post("/api/auth/test-login", json={"user_id": "user_playwright"})
        assert resp.status_code == 200

        # The cookie landed in the jar, so a following request is authenticated
        # with no extra plumbing — this is the pytest ergonomics the issue asks for.
        assert client.cookies["sapling_session"]
        probe = client.get("/probe")
        assert probe.status_code == 200
        assert probe.json()["user_id"] == "user_playwright"

    def test_cookie_attributes_match_the_real_session_cookie(self, client, monkeypatch):
        monkeypatch.setattr(config, "APP_ENV", "test")
        resp = client.post("/api/auth/test-login", json={"user_id": "user_alice"})
        set_cookie = resp.headers["set-cookie"]
        assert set_cookie.startswith("sapling_session=")
        assert "HttpOnly" in set_cookie
        assert "Path=/" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert "Secure" not in set_cookie  # SECURE_COOKIES is False in this fixture

    def test_secure_flag_follows_secure_cookies_config(self, client, monkeypatch):
        monkeypatch.setattr(config, "APP_ENV", "test")
        monkeypatch.setattr(config, "SECURE_COOKIES", True)
        resp = client.post("/api/auth/test-login", json={"user_id": "user_alice"})
        assert "Secure" in resp.headers["set-cookie"]

    def test_token_is_returned_in_the_body_for_playwright_add_cookies(self, client, monkeypatch):
        """Playwright global setup injects the token via context.addCookies(), so
        the body token and the Set-Cookie value must be the same string."""
        monkeypatch.setattr(config, "APP_ENV", "test")
        resp = client.post("/api/auth/test-login", json={"user_id": "user_alice"})
        body = resp.json()
        assert body["cookie_name"] == "sapling_session"
        assert body["token"] == client.cookies["sapling_session"]
        assert body["expires_in"] > 0

        # And that raw token, presented as a cookie by a *different* client,
        # authenticates — exactly what context.addCookies() does.
        fresh = TestClient(client.app)
        fresh.cookies.set("sapling_session", body["token"])
        assert fresh.get("/probe").json()["user_id"] == "user_alice"

    def test_default_and_custom_ttl(self, client, monkeypatch):
        monkeypatch.setattr(config, "APP_ENV", "test")
        default = client.post("/api/auth/test-login", json={"user_id": "u"}).json()
        assert default["expires_in"] == auth_module.TEST_LOGIN_DEFAULT_TTL_SECONDS

        custom = client.post("/api/auth/test-login", json={"user_id": "u", "ttl": 120}).json()
        assert custom["expires_in"] == 120

    def test_ttl_is_clamped(self, client, monkeypatch):
        monkeypatch.setattr(config, "APP_ENV", "test")
        huge = client.post("/api/auth/test-login", json={"user_id": "u", "ttl": 10**9}).json()
        assert huge["expires_in"] == auth_module.TEST_LOGIN_MAX_TTL_SECONDS
        tiny = client.post("/api/auth/test-login", json={"user_id": "u", "ttl": 0}).json()
        assert tiny["expires_in"] == 30

    @pytest.mark.parametrize("body", [{}, {"user_id": ""}, {"user_id": "   "}, {"user_id": "x" * 300}])
    def test_rejects_bad_user_id(self, client, monkeypatch, body):
        monkeypatch.setattr(config, "APP_ENV", "test")
        assert client.post("/api/auth/test-login", json=body).status_code == 422

    @pytest.mark.parametrize(
        "kwargs",
        [{"json": []}, {"json": "nope"}, {"content": b"not json at all"}, {}],
    )
    def test_rejects_non_object_bodies(self, client, monkeypatch, kwargs):
        monkeypatch.setattr(config, "APP_ENV", "test")
        assert client.post("/api/auth/test-login", **kwargs).status_code == 422

    def test_rejects_bad_ttl_type(self, client, monkeypatch):
        monkeypatch.setattr(config, "APP_ENV", "test")
        resp = client.post("/api/auth/test-login", json={"user_id": "u", "ttl": "soon"})
        assert resp.status_code == 422

    def test_500_when_session_secret_is_unset(self, client, monkeypatch):
        """Local dev may legitimately run without SESSION_SECRET (config relaxes the
        check for IS_LOCAL). Refuse loudly rather than hand out a token signed with
        an empty key, which the guard would reject anyway."""
        monkeypatch.setattr(config, "APP_ENV", "local")
        monkeypatch.setattr(config, "SESSION_SECRET", "")
        resp = client.post("/api/auth/test-login", json={"user_id": "u"})
        assert resp.status_code == 500
        assert "sapling_session" not in resp.headers.get("set-cookie", "")


# ── The unified minter ────────────────────────────────────────────────────────


class TestUnifiedMintSession:
    def test_byte_identical_to_the_verified_format(self, monkeypatch):
        monkeypatch.setattr(session_tokens, "_now", lambda: FROZEN_NOW)
        minted = session_tokens.mint_session("user_alice", ttl=3600, secret=SECRET)
        assert minted == _reference_token("user_alice", FROZEN_NOW + 3600, SECRET)

    def test_output_is_accepted_by_the_real_decoder(self, secrets_wired):
        token = session_tokens.mint_session("user_alice", ttl=3600)
        scope = {
            "type": "http", "method": "GET", "path": "/",
            "headers": [(b"cookie", f"sapling_session={token}".encode())],
            "query_string": b"",
        }
        payload = auth_guard._real_decode_session(Request(scope))
        assert payload["user_id"] == "user_alice"

    def test_reads_the_secret_from_config_at_call_time(self, monkeypatch):
        monkeypatch.setattr(session_tokens, "_now", lambda: FROZEN_NOW)
        monkeypatch.setattr(config, "SESSION_SECRET", SECRET)
        assert session_tokens.mint_session("u") == _reference_token("u", FROZEN_NOW + 3600, SECRET)
        monkeypatch.setattr(config, "SESSION_SECRET", "a-completely-different-secret-value")
        assert session_tokens.mint_session("u") != _reference_token("u", FROZEN_NOW + 3600, SECRET)

    def test_refuses_to_mint_without_a_secret(self, monkeypatch):
        monkeypatch.setattr(config, "SESSION_SECRET", "")
        with pytest.raises(RuntimeError, match="SESSION_SECRET"):
            session_tokens.mint_session("u")

    def test_e2e_staging_helper_is_the_canonical_one(self):
        """db/e2e_staging_http.py must not keep its own copy (#381)."""
        from db import e2e_staging_http

        assert e2e_staging_http.mint_session is session_tokens.mint_session

    def test_integration_conftest_delegates_to_the_canonical_one(self, monkeypatch):
        """tests/integration/conftest.py keeps a thin wrapper (it must not import
        `config` at module scope, so the .env override still wins), but the token
        it produces must come from the canonical implementation."""
        path = Path(__file__).resolve().parent / "integration" / "conftest.py"
        spec = importlib.util.spec_from_file_location("_integration_conftest_probe", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        source = path.read_text()
        assert "session_tokens" in source, "integration conftest must delegate, not re-implement"
        assert "hmac.new(" not in source, "integration conftest still re-implements the HMAC mint"

        monkeypatch.setattr(session_tokens, "_now", lambda: FROZEN_NOW)
        monkeypatch.setattr(config, "SESSION_SECRET", SECRET)
        assert module.mint_session("u", 3600) == session_tokens.mint_session("u", 3600)

    def test_routes_auth_redirect_token_uses_the_canonical_minter(self):
        """The OAuth-callback redirect handoff token is the same wire format; it
        must not keep a fourth inline copy of the HMAC code."""
        source = Path(auth_module.__file__).read_text()
        redirect_block = source[source.index("One-shot HMAC token"):]
        assert "hmac.new(" not in redirect_block
        assert "_hmac.new(" not in redirect_block
