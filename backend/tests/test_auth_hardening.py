"""
Auth hardening: server-side session revocation, admin step-up, the cookie as
the only session channel, verified Google emails and the API docs gate.

- Tokens carry `iat`; sign-out (POST /api/auth/logout) stamps
  `users.sessions_valid_after`, and the guard refuses a session issued before
  it (through its bounded account cache).
- Admin routes need a session issued within ADMIN_REAUTH_WINDOW_SECONDS, the
  destructive ones within ADMIN_DESTRUCTIVE_REAUTH_WINDOW_SECONDS; otherwise
  401 `reauth_required`. A non-admin still gets 403.
- An unverified Google email cannot sign in.

The suite-wide `_bypass_session_auth` stub replaces the guard everywhere, so
these tests reach the real one through the `_real_*` handles conftest keeps.
"""
import ast
import json
import pathlib
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import config
import routes.auth as auth_module
from services import auth_guard, session_tokens
from tests.split_patches import set_auth_table
# Fixtures (`real_guard`, `callback`: imported fixtures register under their
# declared names) and helpers shared with the #756 suite.
from tests.test_auth_session_access_756 import (  # noqa: F401
    SECRET,
    _request,
    _row,
    _callback,
    _real_guard,
)


def _token_at(iat: int, user_id: str = "user_alice", ttl: int = config.SESSION_MAX_AGE_SECONDS) -> str:
    """A session token issued at `iat` (unix seconds)."""
    original = session_tokens._now
    session_tokens._now = lambda: iat
    try:
        return session_tokens.mint_session(user_id, ttl=ttl, secret=SECRET)
    finally:
        session_tokens._now = original


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _payload(token: str) -> dict:
    import base64

    b64 = token.split(".")[0]
    return json.loads(base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)))


# ── iat ──────────────────────────────────────────────────────────────────────


def test_minted_tokens_carry_iat_and_cap_the_lifetime():
    now = int(time.time())
    payload = _payload(session_tokens.mint_session("u", ttl=90 * 86400, secret=SECRET))
    assert abs(payload["iat"] - now) <= 2
    assert payload["exp"] - payload["iat"] == config.SESSION_MAX_AGE_SECONDS


def test_session_max_age_is_seven_days():
    assert config.SESSION_MAX_AGE_SECONDS == 7 * 24 * 3600
    frontend = pathlib.Path(__file__).resolve().parents[2] / "frontend/src/lib/sessionToken.ts"
    assert "export const SESSION_MAX_AGE = 604800;" in frontend.read_text()


# ── revocation ───────────────────────────────────────────────────────────────


class TestRevocation:
    def test_session_issued_before_the_cut_off_is_revoked(self, real_guard):
        now = int(time.time())
        real_guard.select.return_value = _row(sessions_valid_after=_iso(now - 60))
        old = _token_at(now - 120)
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_get_session_user_id(_request(old))
        assert exc.value.status_code == 401
        assert exc.value.detail == "Session revoked"

    def test_session_issued_after_the_cut_off_is_honoured(self, real_guard):
        now = int(time.time())
        real_guard.select.return_value = _row(sessions_valid_after=_iso(now - 60))
        assert auth_guard._real_get_session_user_id(_request(_token_at(now - 30))) == "user_alice"

    def test_never_signed_out_revokes_nothing(self, real_guard):
        real_guard.select.return_value = _row(sessions_valid_after=None)
        assert auth_guard._real_get_session_user_id(_request(_token_at(int(time.time()) - 3600))) == "user_alice"

    def test_the_guard_reads_the_cut_off_column(self, real_guard):
        real_guard.select.return_value = _row()
        auth_guard._real_get_session_user_id(_request(_token_at(int(time.time()))))
        columns = real_guard.select.call_args.args[0]
        assert "sessions_valid_after" in columns.split(",")

    def test_a_malformed_cut_off_is_503_and_not_cached(self, real_guard):
        real_guard.select.return_value = _row(sessions_valid_after="not-a-time")
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_get_session_user_id(_request(_token_at(int(time.time()))))
        assert exc.value.status_code == 503
        assert "user_alice" not in auth_guard._account_state_cache

    def test_revocation_also_applies_to_an_unapproved_account(self, real_guard):
        now = int(time.time())
        real_guard.select.return_value = _row(is_approved=False, sessions_valid_after=_iso(now))
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_get_session_user_id(_request(_token_at(now - 60)), allow_unapproved=True)
        assert exc.value.detail == "Session revoked"


@pytest.fixture
def logout_client(real_guard, monkeypatch):
    """The auth router over the real guard; `users` writes are recorded."""
    monkeypatch.setattr(auth_module, "get_session_user_id", auth_guard._real_get_session_user_id)
    set_auth_table(monkeypatch, lambda name: real_guard)
    app = FastAPI()
    app.include_router(auth_module.router, prefix="/api/auth")
    return TestClient(app), real_guard


class TestLogout:
    def test_logout_stamps_the_cut_off_and_kills_the_old_session(self, logout_client):
        client, users = logout_client
        users.select.return_value = _row()
        token = _token_at(int(time.time()) - 5)
        client.cookies.set("sapling_session", token)
        # Warm the guard's cache: logout must clear it, not wait out the TTL.
        auth_guard._real_get_session_user_id(_request(token))

        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200, resp.text
        assert resp.headers["Cache-Control"] == "no-store"
        data, = users.update.call_args.args[:1]
        assert set(data) == {"sessions_valid_after"}
        assert users.update.call_args.kwargs["filters"] == {"id": "eq.user_alice"}
        stamp = datetime.fromisoformat(data["sessions_valid_after"]).timestamp()
        assert abs(stamp - time.time()) < 5
        assert "user_alice" not in auth_guard._account_state_cache

        # The database now says so; the same cookie is refused.
        users.select.return_value = _row(sessions_valid_after=data["sessions_valid_after"])
        assert client.get("/api/auth/me").status_code == 401
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_get_session_user_id(_request(token))
        assert exc.value.detail == "Session revoked"

    def test_logout_without_a_session_is_401_and_writes_nothing(self, logout_client):
        client, users = logout_client
        assert client.post("/api/auth/logout").status_code == 401
        assert not users.update.called

    def test_logout_ignores_a_token_in_the_query_string(self, logout_client):
        client, users = logout_client
        users.select.return_value = _row()
        token = _token_at(int(time.time()))
        assert client.post(f"/api/auth/logout?auth_token={token}").status_code == 401
        assert not users.update.called

    def test_a_failed_write_is_not_reported_as_signed_out(self, logout_client):
        client, users = logout_client
        users.select.return_value = _row()
        users.update.side_effect = httpx.ConnectError("db down")
        client.cookies.set("sapling_session", _token_at(int(time.time())))
        assert client.post("/api/auth/logout").status_code == 503


# ── admin step-up ────────────────────────────────────────────────────────────


@pytest.fixture
def admin_guard(real_guard, monkeypatch):
    """The real admin guard over an approved account with the admin role."""
    real_guard.select.return_value = _row()
    roles = auth_guard.table("user_roles")
    roles.select.return_value = [{"role_id": 1, "roles": {"slug": "admin"}}]
    monkeypatch.setattr(auth_guard, "get_session_user_id", auth_guard._real_get_session_user_id)
    monkeypatch.setattr(auth_guard, "require_admin", auth_guard._real_require_admin)
    return roles


def _reauth(exc: pytest.ExceptionInfo) -> bool:
    return (
        exc.value.status_code == 401
        and isinstance(exc.value.detail, dict)
        and exc.value.detail.get("code") == auth_guard.REAUTH_REQUIRED
    )


class TestAdminStepUp:
    def test_recent_admin_session_is_accepted(self, admin_guard):
        auth_guard._real_require_admin(_request(_token_at(int(time.time()) - 3600)))

    def test_admin_session_older_than_the_window_must_reauthenticate(self, admin_guard):
        old = int(time.time()) - config.ADMIN_REAUTH_WINDOW_SECONDS - 60
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_require_admin(_request(_token_at(old)))
        assert _reauth(exc)
        assert exc.value.detail["max_session_age_seconds"] == config.ADMIN_REAUTH_WINDOW_SECONDS

    def test_window_defaults(self):
        assert config.ADMIN_REAUTH_WINDOW_SECONDS == 12 * 3600
        assert config.ADMIN_DESTRUCTIVE_REAUTH_WINDOW_SECONDS == 30 * 60

    def test_destructive_actions_need_a_fresher_session(self, admin_guard):
        now = int(time.time())
        auth_guard._real_require_admin_recent(_request(_token_at(now - 10 * 60)))
        stale = now - config.ADMIN_DESTRUCTIVE_REAUTH_WINDOW_SECONDS - 60
        auth_guard._real_require_admin(_request(_token_at(stale)))  # fine for reads
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_require_admin_recent(_request(_token_at(stale)))
        assert _reauth(exc)

    def test_a_non_admin_gets_403_not_a_reauth_prompt(self, admin_guard):
        admin_guard.select.return_value = []
        old = int(time.time()) - 2 * 86400
        for guard in (auth_guard._real_require_admin, auth_guard._real_require_admin_recent):
            with pytest.raises(HTTPException) as exc:
                guard(_request(_token_at(old)))
            assert exc.value.status_code == 403

    def test_legacy_cookie_is_dated_by_its_30_day_exp(self, admin_guard):
        """A pre-iat BFF cookie minted 13 h ago (exp = mint + 30 d)."""
        import base64
        import hashlib
        import hmac

        minted = int(time.time()) - 13 * 3600
        payload_b64 = base64.urlsafe_b64encode(json.dumps(
            {"user_id": "user_alice", "exp": minted + 30 * 86400}).encode()).decode().rstrip("=")
        sig = hmac.new(SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
        token = f"{payload_b64}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_require_admin(_request(token))
        assert _reauth(exc)


# Each destructive admin action, by (route module, handler).
DESTRUCTIVE = [
    ("routes/admin_accounts.py", "seed_account"),
    ("routes/admin_accounts.py", "wipe_account"),
    ("routes/admin_account_sync.py", "copy_account"),
    ("routes/admin.py", "assign_role"),
    ("routes/admin.py", "revoke_role"),
    ("routes/admin_email.py", "create_broadcast"),
    ("routes/admin_email.py", "resume_broadcast"),
    ("routes/admin_flags.py", "update_flag"),
    ("routes/admin_flags.py", "upsert_target"),
    ("routes/admin_flags.py", "delete_target"),
]


@pytest.mark.parametrize(("path", "handler"), DESTRUCTIVE)
def test_destructive_admin_actions_use_the_strict_window(path, handler):
    backend = pathlib.Path(__file__).resolve().parent.parent
    tree = ast.parse((backend / path).read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == handler)
    first_guard = next(
        n.func.id for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id in {"require_admin", "require_admin_recent"}
    )
    assert first_guard == "require_admin_recent", f"{path}::{handler}"


def test_reauth_is_answered_by_the_destructive_route(admin_guard, monkeypatch):
    """Through a real route: a 20-hour-old admin session cannot wipe."""
    import routes.admin_accounts as admin_accounts

    monkeypatch.setattr(admin_accounts, "require_admin_recent", auth_guard._real_require_admin_recent)
    app = FastAPI()
    app.include_router(admin_accounts.router, prefix="/api/admin/accounts")
    client = TestClient(app)
    client.cookies.set("sapling_session", _token_at(int(time.time()) - 20 * 3600))
    resp = client.post("/api/admin/accounts/user_target/wipe", json={"confirm": "WIPE"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "reauth_required"


# ── verified Google email ────────────────────────────────────────────────────


@pytest.mark.parametrize("verified", [False, None, "true", 1])
def test_unverified_google_email_cannot_sign_in(callback, monkeypatch, verified):
    drive, factory, _ = callback
    factory("users").select.return_value = [
        {"id": "user_112233", "is_approved": True, "deleted_at": None}
    ]
    info = {"id": "112233", "email": "student@bu.edu", "name": "Ada Lovelace"}
    if verified is not None:
        info["verified_email"] = verified

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return info

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
    loc = drive()
    query = parse_qs(loc.query)
    assert query["error"] == ["email_not_verified"]
    assert "auth_token" not in query
    for name in ("users", "user_profiles", "oauth_tokens"):
        t = factory(name)
        assert not t.update.called and not t.upsert.called and not t.insert.called, name


def test_verified_google_email_signs_in(callback):
    drive, factory, _ = callback
    factory("users").select.return_value = [
        {"id": "user_112233", "is_approved": True, "deleted_at": None}
    ]
    assert parse_qs(drive().query).get("auth_token")


# ── API docs ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("app_env", "served"), [
    ("local", True), ("test", True), ("production", False), ("staging", False), ("dev", False),
])
def test_api_docs_are_served_only_locally(app_env, served):
    import main

    app = FastAPI(**main.api_docs_urls(app_env))

    @app.get("/api/thing")
    def _thing():
        return {}

    client = TestClient(app)
    for path in ("/docs", "/redoc", "/openapi.json"):
        status = client.get(path).status_code
        assert (status == 200) is served, (app_env, path, status)


def test_the_app_is_built_with_the_docs_gate():
    import main

    assert main.app.openapi_url == main.api_docs_urls(config.APP_ENV)["openapi_url"]
    assert main.app.docs_url == main.api_docs_urls(config.APP_ENV)["docs_url"]
