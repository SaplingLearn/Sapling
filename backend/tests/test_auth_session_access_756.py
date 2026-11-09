"""
#756 (state-machine audit A1): sessions and account access.

- The guard reads the account, not just the signature: a missing or deleted
  `users` row is 401, an unapproved one 403 `not_approved` (except on /me).
- The answer is cached per process for a short TTL; failures are not cached.
- Tokens carry a `typ` claim; the API refuses the OAuth `handoff` token.
- A deleted account's Google sign-in is refused (`account_deleted`), with no
  writes — no silent un-delete.
- An OAuth state nonce is honoured once.

The suite-wide `_bypass_session_auth` stub replaces the guard everywhere, so
these tests reach the real one through the `_real_*` handles conftest keeps.
"""
import base64
import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import config
import routes.auth as auth_module
import services.achievement_service as ach_module
from services import auth_guard, session_tokens
from tests.route_patches import PROFILE_TABLE_MODULES, set_auth_session_secret, set_auth_table

SECRET = "issue-756-session-secret-at-least-32-bytes-long"


def _request(token: str | None = None, *, query: str = "") -> Request:
    headers = []
    if token is not None:
        headers.append((b"cookie", f"sapling_session={token}".encode()))
    return Request({
        "type": "http", "method": "GET", "path": "/probe",
        "headers": headers, "query_string": query.encode(),
    })


@pytest.fixture
def real_guard(monkeypatch):
    """Point the real decoder + guard at SECRET, with the users read mocked."""
    monkeypatch.setattr(auth_guard, "SESSION_SECRET", SECRET)
    monkeypatch.setattr(auth_guard, "_decode_session", auth_guard._real_decode_session)
    users = MagicMock(name="table:users")
    users.select.return_value = []
    roles = MagicMock(name="table:user_roles")
    roles.select.return_value = []

    def factory(name):
        return {"users": users, "user_roles": roles}[name]

    monkeypatch.setattr(auth_guard, "table", factory)
    return users


def _token(user_id="user_alice", typ="session", ttl=3600):
    return session_tokens.mint_session(user_id, ttl=ttl, secret=SECRET, typ=typ)


def _row(**overrides):
    return [{"id": "user_alice", "deleted_at": None, "is_approved": True, **overrides}]


# ── typ claim ────────────────────────────────────────────────────────────────


class TestTokenType:
    def test_session_token_is_accepted(self, real_guard):
        payload = auth_guard._real_decode_session(_request(_token()))
        assert payload["typ"] == "session"

    def test_handoff_token_is_not_an_api_credential(self, real_guard):
        """The 300 s OAuth-redirect token used to work as a full credential
        through `?auth_token=`."""
        for req in (_request(_token(typ="handoff")),
                    _request(query=f"auth_token={_token(typ='handoff')}")):
            with pytest.raises(HTTPException) as exc:
                auth_guard._real_decode_session(req)
            assert exc.value.status_code == 401

    def test_legacy_token_without_typ_is_a_session(self, real_guard):
        payload_b64 = base64.urlsafe_b64encode(
            json.dumps({"user_id": "user_alice", "exp": int(time.time()) + 60}).encode()
        ).decode().rstrip("=")
        sig = hmac.new(SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
        token = f"{payload_b64}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"
        assert auth_guard._real_decode_session(_request(token))["user_id"] == "user_alice"

    def test_minter_refuses_an_unknown_typ(self):
        with pytest.raises(ValueError):
            session_tokens.mint_session("u", secret=SECRET, typ="admin")


# ── account state ────────────────────────────────────────────────────────────


class TestAccountState:
    def test_active_account_authenticates(self, real_guard):
        real_guard.select.return_value = _row()
        req = _request(_token())
        assert auth_guard._real_get_session_user_id(req) == "user_alice"
        assert req.state.user_id == "user_alice"

    @pytest.mark.parametrize("rows", [[], _row(deleted_at="2026-11-01T00:00:00+00:00")])
    def test_missing_or_deleted_account_is_401(self, real_guard, rows):
        real_guard.select.return_value = rows
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_get_session_user_id(_request(_token()))
        assert exc.value.status_code == 401

    def test_unapproved_account_is_403_not_approved(self, real_guard):
        real_guard.select.return_value = _row(is_approved=False)
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_get_session_user_id(_request(_token()))
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "not_approved"

    def test_unapproved_account_may_read_me(self, real_guard):
        real_guard.select.return_value = _row(is_approved=False)
        uid = auth_guard._real_get_session_user_id(_request(_token()), allow_unapproved=True)
        assert uid == "user_alice"

    def test_allow_unapproved_still_refuses_a_deleted_account(self, real_guard):
        real_guard.select.return_value = _row(deleted_at="2026-11-01T00:00:00+00:00")
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_get_session_user_id(_request(_token()), allow_unapproved=True)
        assert exc.value.status_code == 401

    def test_deleted_admin_loses_require_admin(self, real_guard, monkeypatch):
        """The audit's headline: a deleted admin kept admin for 30 days."""
        monkeypatch.setattr(auth_guard, "get_session_user_id", auth_guard._real_get_session_user_id)
        real_guard.select.return_value = _row(deleted_at="2026-11-01T00:00:00+00:00")
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_require_admin(_request(_token()))
        assert exc.value.status_code == 401

    def test_state_is_cached_for_the_ttl(self, real_guard, monkeypatch):
        real_guard.select.return_value = _row()
        clock = [1000.0]
        monkeypatch.setattr(auth_guard._time, "monotonic", lambda: clock[0])
        for _ in range(3):
            auth_guard._real_get_session_user_id(_request(_token()))
        assert real_guard.select.call_count == 1
        # Past the TTL the account is read again — and a deletion lands.
        real_guard.select.return_value = _row(deleted_at="2026-11-01T00:00:00+00:00")
        clock[0] += auth_guard.ACCOUNT_STATE_TTL_SECONDS + 1
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_get_session_user_id(_request(_token()))
        assert exc.value.status_code == 401
        assert real_guard.select.call_count == 2

    def test_clear_hook_makes_a_change_immediate(self, real_guard):
        real_guard.select.return_value = _row()
        auth_guard._real_get_session_user_id(_request(_token()))
        real_guard.select.return_value = _row(deleted_at="2026-11-01T00:00:00+00:00")
        auth_guard.clear_account_state_cache("user_alice")
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_get_session_user_id(_request(_token()))
        assert exc.value.status_code == 401

    def test_unreadable_account_is_503_and_not_cached(self, real_guard):
        real_guard.select.side_effect = httpx.ConnectError("db down")
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_get_session_user_id(_request(_token()))
        assert exc.value.status_code == 503
        real_guard.select.side_effect = None
        real_guard.select.return_value = _row()
        assert auth_guard._real_get_session_user_id(_request(_token())) == "user_alice"


def test_delete_account_drops_the_cached_state(monkeypatch):
    import routes.profile as profile_module

    auth_guard._account_state_cache["user_alice"] = (float("inf"), auth_guard.ACCOUNT_ACTIVE)
    users = MagicMock()
    for module in PROFILE_TABLE_MODULES:
        monkeypatch.setattr(f"{module}.table", lambda name: users)
    monkeypatch.setattr(profile_module, "delete_posthog_person", lambda *_a, **_k: None)
    app = FastAPI()
    app.include_router(profile_module.router, prefix="/api/profile")
    resp = TestClient(app).request(
        "DELETE", "/api/profile/user_alice/account", json={"confirmation": "DELETE"},
    )
    assert resp.status_code == 200, resp.text
    assert "user_alice" not in auth_guard._account_state_cache


# ── /me ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def me_client(monkeypatch):
    tables: dict = {}

    def factory(name):
        if name not in tables:
            m = MagicMock(name=f"table:{name}")
            m.select.return_value = []
            tables[name] = m
        return tables[name]

    set_auth_table(monkeypatch, factory)
    seen = {}

    def _guard(request, **kwargs):
        seen.update(kwargs)
        return "user_alice"

    monkeypatch.setattr(auth_module, "get_session_user_id", _guard)
    app = FastAPI()
    app.include_router(auth_module.router, prefix="/api/auth")
    return TestClient(app), factory, seen


def test_me_is_reachable_while_unapproved(me_client):
    client, factory, seen = me_client
    factory("users").select.return_value = [
        {"id": "user_alice", "is_approved": False, "onboarding_completed": False, "deleted_at": None}
    ]
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["is_approved"] is False
    assert seen == {"allow_unapproved": True}


def test_me_refuses_a_deleted_account(me_client):
    client, factory, _ = me_client
    factory("users").select.return_value = [
        {"id": "user_alice", "is_approved": True, "onboarding_completed": True,
         "deleted_at": "2026-11-01T00:00:00+00:00"}
    ]
    assert client.get("/api/auth/me").status_code == 401


# ── Google callback ──────────────────────────────────────────────────────────


FRONTEND = "https://sapling.example"


@pytest.fixture
def callback(monkeypatch):
    """Drive the real /google/callback past the Google network hops."""
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(auth_module, "_LOCAL_AUTO_APPROVE", False)
    monkeypatch.setattr(auth_module, "FRONTEND_URL", FRONTEND)
    set_auth_session_secret(monkeypatch, SECRET)
    monkeypatch.setattr(auth_module, "GOOGLE_AVAILABLE", True)
    monkeypatch.setattr("services.auth.signin._welcome_due", lambda *_a, **_k: False)
    monkeypatch.setattr(ach_module, "check_achievements", lambda *a, **k: None)

    creds = MagicMock(token="access-tok", refresh_token="refresh-tok", expiry=None)
    flow = MagicMock(credentials=creds)
    flow_cls = MagicMock()
    flow_cls.from_client_config.return_value = flow
    monkeypatch.setattr(auth_module, "Flow", flow_cls, raising=False)

    userinfo = MagicMock()
    userinfo.raise_for_status.return_value = None
    userinfo.json.return_value = {
        "id": "112233", "email": "student@bu.edu",
        "name": "Ada Lovelace", "picture": "https://example.com/a.png",
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: userinfo)

    tables: dict = {}

    def factory(name):
        if name not in tables:
            m = MagicMock(name=f"table:{name}")
            for op in ("select", "insert", "update", "upsert"):
                getattr(m, op).return_value = []
            tables[name] = m
        return tables[name]

    set_auth_table(monkeypatch, factory)

    def _drive(nonce="n1"):
        cookie = auth_module._encode_oauth_cookie({"n": nonce, "cv": "verifier", "popup_id": None})
        state = auth_module._encode_state({"action": "signin", "n": nonce})
        client = TestClient(FastAPI())
        client.app.include_router(auth_module.router, prefix="/api/auth")
        client.cookies.set(auth_module.OAUTH_STATE_COOKIE, cookie)
        resp = client.get(f"/api/auth/google/callback?code=c&state={state}", follow_redirects=False)
        assert resp.status_code in (302, 307)
        return urlparse(resp.headers["location"])

    return _drive, factory, flow


def test_deleted_account_sign_in_is_refused_without_writes(callback):
    drive, factory, _ = callback
    factory("users").select.return_value = [
        {"id": "user_112233", "is_approved": True, "deleted_at": "2026-11-01T00:00:00+00:00"}
    ]
    loc = drive()
    assert parse_qs(loc.query)["error"] == ["account_deleted"]
    assert "auth_token" not in parse_qs(loc.query)
    # No silent un-delete: nothing about the account was written.
    for name in ("users", "user_profiles", "oauth_tokens"):
        t = factory(name)
        assert not t.update.called and not t.upsert.called and not t.insert.called, name


def test_live_account_gets_a_handoff_token(callback, monkeypatch):
    drive, factory, _ = callback
    factory("users").select.return_value = [
        {"id": "user_112233", "is_approved": True, "deleted_at": None}
    ]
    loc = drive()
    assert loc.path == "/auth/callback"
    token = parse_qs(loc.query)["auth_token"][0]
    # It is a handoff token: the API will not take it as a credential.
    monkeypatch.setattr(auth_guard, "SESSION_SECRET", SECRET)
    with pytest.raises(HTTPException) as exc:
        auth_guard._real_decode_session(_request(token))
    assert exc.value.status_code == 401


def test_oauth_state_nonce_is_single_use(callback):
    drive, factory, flow = callback
    factory("users").select.return_value = [
        {"id": "user_112233", "is_approved": True, "deleted_at": None}
    ]
    assert drive().path == "/auth/callback"
    replay = drive()
    assert parse_qs(replay.query)["error"] == ["invalid_state"]
    # Refused before the code exchange.
    assert flow.fetch_token.call_count == 1
    # A fresh nonce still works.
    assert drive(nonce="n2").path == "/auth/callback"


# ── test-login ───────────────────────────────────────────────────────────────


def test_test_login_returns_a_session_and_a_handoff_token(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "test")
    monkeypatch.setattr(config, "SESSION_SECRET", SECRET)
    monkeypatch.setattr(config, "SECURE_COOKIES", False)
    monkeypatch.setattr(auth_guard, "SESSION_SECRET", SECRET)
    app = FastAPI()
    app.include_router(auth_module.router, prefix="/api/auth")
    body = TestClient(app).post("/api/auth/test-login", json={"user_id": "rich-user-active"}).json()
    assert auth_guard._real_decode_session(_request(body["token"]))["typ"] == "session"
    with pytest.raises(HTTPException):
        auth_guard._real_decode_session(_request(body["handoff_token"]))


# ── admin approval changes drop the cached state ─────────────────────────────


def _cached(*uids):
    for uid in uids:
        auth_guard._account_state_cache[uid] = (float("inf"), auth_guard.ACCOUNT_ACTIVE)


def test_admin_unapprove_drops_the_cached_state(monkeypatch):
    import routes.admin as admin_module
    from tests.split_patches import ADMIN_MODULES, setattr_in

    _cached("user_bob")
    users = MagicMock()
    users.update.return_value = [{"id": "user_bob", "email": None}]
    setattr_in(monkeypatch, ADMIN_MODULES, "table", lambda name: users)
    monkeypatch.setattr(admin_module, "get_session_user_id", lambda request, **_k: "admin_1")
    setattr_in(monkeypatch, ADMIN_MODULES, "log_admin_action", lambda **_k: None)
    admin_module.unapprove_user("user_bob", MagicMock())
    assert "user_bob" not in auth_guard._account_state_cache


def test_admin_allowlist_revoke_and_grant_drop_the_cached_state(monkeypatch):
    import routes.admin as admin_module
    from tests.split_patches import ADMIN_MODULES, setattr_in
    import routes.auth as auth_routes
    from models import AllowlistEmailBody

    _cached("user_bob", "user_carol")
    tables: dict = {}

    def factory(name):
        if name not in tables:
            tables[name] = MagicMock(name=f"table:{name}")
            tables[name].update.return_value = []
        return tables[name]

    setattr_in(monkeypatch, ADMIN_MODULES, "table", factory)
    monkeypatch.setattr(admin_module, "get_session_user_id", lambda request, **_k: "admin_1")
    setattr_in(monkeypatch, ADMIN_MODULES, "log_admin_action", lambda **_k: None)
    monkeypatch.setattr(auth_routes, "_waitlist_entries", lambda *_a, **_k: [
        {"id": "w1", "email": "bob@bu.edu", "joined_user_id": "user_bob"},
    ])
    admin_module.revoke_allowlist(AllowlistEmailBody(email="bob@bu.edu"), MagicMock())
    assert "user_bob" not in auth_guard._account_state_cache

    admin_module._grant_linked_accounts(
        [{"id": "w2", "joined_user_id": "user_carol"}], "2026-11-05T00:00:00+00:00",
    )
    assert "user_carol" not in auth_guard._account_state_cache


# ── review follow-ups ────────────────────────────────────────────────────────


def test_successful_sign_in_drops_a_cached_unapproved_state(callback):
    """Local auto-approve / waitlist re-approval flip is_approved inside the
    callback; a worker that cached "unapproved" must not 403 the new session."""
    drive, factory, _ = callback
    auth_guard._account_state_cache["user_112233"] = (float("inf"), auth_guard.ACCOUNT_UNAPPROVED)
    factory("users").select.return_value = [
        {"id": "user_112233", "is_approved": True, "deleted_at": None}
    ]
    assert drive().path == "/auth/callback"
    assert "user_112233" not in auth_guard._account_state_cache


@pytest.mark.parametrize("method,path,body", [
    ("DELETE", "/api/profile/user_alice/account", {"confirmation": "DELETE"}),
    ("POST", "/api/profile/user_alice/export", None),
])
def test_removed_student_can_still_erase_and_export(real_guard, monkeypatch, method, path, body):
    """An unapproved (removed) account keeps its right to erase/export its data."""
    import routes.profile as profile_module

    monkeypatch.setattr(auth_guard, "get_session_user_id", auth_guard._real_get_session_user_id)
    monkeypatch.setattr(profile_module, "require_self", auth_guard._real_require_self)
    monkeypatch.setattr(profile_module, "delete_posthog_person", lambda *_a, **_k: None)
    data = MagicMock()
    data.select.return_value = [{"id": "user_alice"}]
    data.update.return_value = []
    data.upsert.return_value = [{}]
    for module in PROFILE_TABLE_MODULES:
        monkeypatch.setattr(f"{module}.table", lambda name: data)
    real_guard.select.return_value = _row(is_approved=False)
    app = FastAPI()
    app.include_router(profile_module.router, prefix="/api/profile")
    client = TestClient(app)
    client.cookies.set("sapling_session", _token())
    kwargs = {"json": body} if body else {}
    assert client.request(method, path, **kwargs).status_code == 200

    # ...but not a deleted one, and not on the rest of the profile API.
    auth_guard.clear_account_state_cache()
    real_guard.select.return_value = _row(deleted_at="2026-11-01T00:00:00+00:00")
    assert client.request(method, path, **kwargs).status_code == 401
    auth_guard.clear_account_state_cache()
    real_guard.select.return_value = _row(is_approved=False)
    assert client.get("/api/profile/user_alice/settings").status_code == 403


def test_async_route_reads_account_state_off_the_event_loop(real_guard, monkeypatch):
    """The account read is a blocking PostgREST call; an async route must not
    run it on the event loop (a cache miss would stall every request)."""
    import asyncio

    import routes.notes as notes_module

    seen: list[bool] = []

    def _read(uid):
        try:
            asyncio.get_running_loop()
            seen.append(True)
        except RuntimeError:
            seen.append(False)
        return auth_guard.ACCOUNT_ACTIVE

    monkeypatch.setattr(auth_guard, "_read_account_state", _read)
    monkeypatch.setattr(auth_guard, "get_session_user_id", auth_guard._real_get_session_user_id)
    monkeypatch.setattr(notes_module, "require_self", auth_guard._real_require_self)
    app = FastAPI()
    app.include_router(notes_module.router, prefix="/api/notes")
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set("sapling_session", _token())
    client.get("/api/notes/user/user_alice")  # whatever happens after the guard
    assert seen == [False]
    # A cache hit does no read at all (guard_off_loop then skips the hop).
    client.get("/api/notes/user/user_alice")
    assert seen == [False]


def test_guard_off_loop_hops_only_on_a_cache_miss(real_guard, monkeypatch):
    import asyncio

    hops = []

    async def _hop(fn, *args, **kwargs):
        hops.append(fn)
        return fn(*args, **kwargs)

    monkeypatch.setattr(auth_guard, "run_in_threadpool", _hop)
    real_guard.select.return_value = _row()
    req = _request(_token())
    guard = auth_guard._real_get_session_user_id
    assert asyncio.run(auth_guard.guard_off_loop(guard, req)) == "user_alice"
    assert len(hops) == 1  # miss → threadpool
    assert asyncio.run(auth_guard.guard_off_loop(guard, _request(_token()))) == "user_alice"
    assert len(hops) == 1  # hit → inline, no I/O
    with pytest.raises(HTTPException):  # refused at decode → inline, no I/O
        asyncio.run(auth_guard.guard_off_loop(guard, _request("garbage")))
    assert len(hops) == 1


def test_no_async_route_calls_the_guard_on_the_loop():
    """Static pin for the above, over every route module: inside `async def`,
    a guard is called only through `await run_in_threadpool(<guard>, ...)`."""
    import ast
    import pathlib

    guards = {"get_session_user_id", "require_self", "require_admin", "account_state"}
    offenders = []
    routes_dir = pathlib.Path(__file__).resolve().parent.parent / "routes"
    for path in sorted(routes_dir.glob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id in guards):
                    offenders.append(f"{path.name}:{node.lineno} {fn.name}")
    assert offenders == [], offenders
