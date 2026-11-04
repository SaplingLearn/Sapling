"""
Sign-in from Cloudflare PR previews of frontend-staging.

Google only accepts exact redirect URIs, so a preview
(<alias>-frontend-staging.saplinglearn.workers.dev) starts sign-in on the
staging backend with ?return_to=<its origin>. /google validates it and signs it
into the OAuth state cookie; the callback (still the one registered URI) sends
the one-shot auth_token back to that origin instead of FRONTEND_URL.

The return_to target receives a credential, so these tests pin the allowlist:
staging only, exact preview origins only, and never read from the callback query.
"""
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
import routes.auth as auth_module
import services.achievement_service as ach_module

_app = FastAPI()
_app.include_router(auth_module.router, prefix="/api/auth")

PREVIEW = "https://pr-742-frontend-staging.saplinglearn.workers.dev"
STAGING_FRONTEND = "https://staging.saplinglearn.com"


@pytest.fixture
def staging(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "staging")
    monkeypatch.setattr(auth_module, "FRONTEND_URL", STAGING_FRONTEND)
    monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")
    monkeypatch.setattr(auth_module, "GOOGLE_AVAILABLE", True)


# ── allowlist ─────────────────────────────────────────────────────────────────


class TestCleanReturnTo:
    @pytest.mark.parametrize("origin", [
        PREVIEW,
        "https://a1b2c3d4-frontend-staging.saplinglearn.workers.dev",
        "https://x-frontend-staging.saplinglearn.workers.dev",
    ])
    def test_preview_origin_accepted_on_staging(self, staging, origin):
        assert auth_module._clean_return_to(origin) == origin

    @pytest.mark.parametrize("origin", [
        None,
        "",
        STAGING_FRONTEND,
        "http://pr-742-frontend-staging.saplinglearn.workers.dev",
        PREVIEW + "/",
        PREVIEW + "/auth/callback",
        PREVIEW + ".evil.com",
        PREVIEW + ":8443",
        "https://pr-742-frontend.saplinglearn.workers.dev",
        "https://pr-742-frontend-staging.attacker.workers.dev",
        "https://evil.com/-frontend-staging.saplinglearn.workers.dev",
        "https://a.b-frontend-staging.saplinglearn.workers.dev",
        "https://-frontend-staging.saplinglearn.workers.dev",
        "https://PR-742-frontend-staging.saplinglearn.workers.dev",
        "https://" + "a" * 47 + "-frontend-staging.saplinglearn.workers.dev",
        PREVIEW + "\n",
    ])
    def test_everything_else_rejected(self, staging, origin):
        assert auth_module._clean_return_to(origin) is None

    @pytest.mark.parametrize("env", ["production", "local", "test", ""])
    def test_preview_origin_ignored_outside_staging(self, monkeypatch, env):
        monkeypatch.setattr(config, "APP_ENV", env)
        assert auth_module._clean_return_to(PREVIEW) is None


# ── /google signs return_to into the state cookie ─────────────────────────────


def _start_signin(monkeypatch, query: str) -> dict:
    flow = MagicMock()
    flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth", None)
    flow_cls = MagicMock()
    flow_cls.from_client_config.return_value = flow
    monkeypatch.setattr(auth_module, "Flow", flow_cls, raising=False)
    monkeypatch.setattr(auth_module, "GOOGLE_CLIENT_ID", "client-id")

    resp = TestClient(_app).get(f"/api/auth/google{query}", follow_redirects=False)
    assert resp.status_code in (302, 307)
    cookie = resp.cookies.get(auth_module.OAUTH_STATE_COOKIE)
    payload = auth_module._decode_oauth_cookie(cookie)
    assert payload is not None
    return payload


def test_google_login_stores_valid_return_to(staging, monkeypatch):
    payload = _start_signin(monkeypatch, f"?return_to={PREVIEW}&popup_id=p1")
    assert payload["rt"] == PREVIEW
    assert payload["popup_id"] == "p1"


def test_google_login_drops_invalid_return_to(staging, monkeypatch):
    payload = _start_signin(monkeypatch, "?return_to=https://evil.example")
    assert "rt" not in payload


def test_google_login_drops_return_to_in_production(staging, monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "production")
    payload = _start_signin(monkeypatch, f"?return_to={PREVIEW}")
    assert "rt" not in payload


# ── the callback redirects to the signed origin ───────────────────────────────


@pytest.fixture
def drive_callback(staging, monkeypatch):
    """Drive the real /google/callback past the Google network hops."""
    creds = MagicMock(token="access-tok", refresh_token="refresh-tok", expiry=None)
    flow_cls = MagicMock()
    flow_cls.from_client_config.return_value = MagicMock(credentials=creds)
    monkeypatch.setattr(auth_module, "Flow", flow_cls, raising=False)

    userinfo = MagicMock()
    userinfo.raise_for_status.return_value = None
    userinfo.json.return_value = {
        "id": "112233", "email": "student@bu.edu",
        "name": "Ada Lovelace", "picture": "https://example.com/a.png",
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: userinfo)
    monkeypatch.setattr(ach_module, "check_achievements", lambda *a, **k: None)

    def _drive(cookie_extra: dict, *, approved: bool = True, nonce_in_state: str = "n1",
               query_extra: str = ""):
        tables: dict = {}

        def factory(name):
            if name not in tables:
                m = MagicMock(name=f"table:{name}")
                m.select.return_value = []
                m.insert.return_value = []
                m.update.return_value = []
                m.upsert.return_value = []
                tables[name] = m
            return tables[name]

        factory("users").select.return_value = [
            {"id": "user_112233", "is_approved": approved, "streak_count": 1}
        ]
        monkeypatch.setattr(auth_module, "table", factory)

        cookie = auth_module._encode_oauth_cookie(
            {"n": "n1", "cv": "verifier", "popup_id": None, **cookie_extra}
        )
        state = auth_module._encode_state({"action": "signin", "n": nonce_in_state})
        client = TestClient(_app)
        client.cookies.set(auth_module.OAUTH_STATE_COOKIE, cookie)
        resp = client.get(
            f"/api/auth/google/callback?code=c&state={state}{query_extra}",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 307)
        return resp.headers["location"]

    return _drive


def _origin(location: str) -> str:
    u = urlparse(location)
    return f"{u.scheme}://{u.netloc}"


def test_success_hands_token_to_preview(drive_callback):
    location = drive_callback({"rt": PREVIEW})
    assert _origin(location) == PREVIEW
    assert urlparse(location).path == "/auth/callback"
    assert parse_qs(urlparse(location).query)["auth_token"]


def test_success_without_return_to_uses_frontend_url(drive_callback):
    location = drive_callback({})
    assert _origin(location) == STAGING_FRONTEND


def test_pending_user_lands_on_preview_pending(drive_callback):
    location = drive_callback({"rt": PREVIEW}, approved=False)
    # The query is the pending token /pending uses to offer the waitlist.
    assert location.split("?", 1)[0] == f"{PREVIEW}/pending"


def test_failure_redirect_goes_to_preview(drive_callback):
    location = drive_callback({"rt": PREVIEW}, nonce_in_state="other")
    assert location == f"{PREVIEW}/auth?error=invalid_state"


def test_return_to_on_callback_query_is_ignored(drive_callback):
    # Only the signed cookie can choose the destination.
    location = drive_callback({}, query_extra=f"&return_to={PREVIEW}")
    assert _origin(location) == STAGING_FRONTEND


def test_signed_return_to_rechecked_at_callback(drive_callback, monkeypatch):
    # A cookie carrying a non-allowlisted rt (or one signed before APP_ENV
    # changed) must still fall back to FRONTEND_URL, not follow it.
    location = drive_callback({"rt": "https://evil.example"})
    assert _origin(location) == STAGING_FRONTEND

    monkeypatch.setattr(config, "APP_ENV", "production")
    location = drive_callback({"rt": PREVIEW})
    assert _origin(location) == STAGING_FRONTEND
