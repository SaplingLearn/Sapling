"""sec2 auth/session hardening (M1 host-only cookie + CSRF origin check, M2
single-use browser-bound OAuth handoff).

M1: the session cookie is `__Host-sapling_session` over https; the backend
reads the plain legacy name on a deployed (SECURE_COOKIES) backend only for a
session minted before the host-only cookie (no `cookie: host` claim).
CsrfOriginMiddleware refuses a cookie-carrying unsafe request from an origin
off the allowlist.

M2: the handoff carries `jti` + `bh`; POST /api/auth/handoff/exchange
consumes it once and only for the browser whose sign-in nonce hashes to `bh`.
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
import routes.auth_handoff as handoff_routes
from services import auth_guard, csrf_origin, session_tokens
from services.auth import handoff
from tests.split_patches import set_auth_table

SECRET = "sec2-auth-sessions-secret-at-least-32-bytes-long"
NONCE = "n" * 43


def _request(cookies: dict[str, str]) -> Request:
    header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return Request({
        "type": "http", "method": "GET", "path": "/probe",
        "headers": [(b"cookie", header.encode())] if header else [], "query_string": b"",
    })


def _sign(payload: dict) -> str:
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return f"{payload_b64}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


def _session(*, host_claim: bool) -> str:
    """A session as the frontend BFF mints it (with or without the claim)."""
    now = time.time()
    payload = {"user_id": "user_alice", "exp": int(now) + 3600, "typ": "session",
               "iat": now, "iat_precision": "ms"}
    if host_claim:
        payload["cookie"] = "host"
    return _sign(payload)


@pytest.fixture
def guard(monkeypatch):
    monkeypatch.setattr(auth_guard, "SESSION_SECRET", SECRET)
    return auth_guard._real_decode_session


# ── M1: which cookie the backend reads ──────────────────────────────────────


class TestSessionCookieNames:
    def test_host_cookie_is_read_on_a_deployed_backend(self, guard, monkeypatch):
        monkeypatch.setattr(config, "SECURE_COOKIES", True)
        token = _session(host_claim=True)
        assert guard(_request({"__Host-sapling_session": token}))["user_id"] == "user_alice"

    def test_host_cookie_wins_over_the_plain_one(self, guard, monkeypatch):
        monkeypatch.setattr(config, "SECURE_COOKIES", True)
        req = _request({"sapling_session": "junk.junk", "__Host-sapling_session": _session(host_claim=True)})
        assert guard(req)["user_id"] == "user_alice"

    def test_legacy_cookie_without_the_claim_is_honoured_read_only(self, guard, monkeypatch):
        """A session the old BFF minted (Domain=.saplinglearn.com, no claim)
        keeps working until it expires: nobody is logged out by the deploy."""
        monkeypatch.setattr(config, "SECURE_COOKIES", True)
        assert guard(_request({"sapling_session": _session(host_claim=False)}))["user_id"] == "user_alice"

    def test_current_session_tossed_under_the_legacy_name_is_refused(self, guard, monkeypatch):
        """A sibling subdomain planting a CURRENT session (it carries the
        claim) under the old, domain-wide name is cookie tossing: refused."""
        monkeypatch.setattr(config, "SECURE_COOKIES", True)
        with pytest.raises(HTTPException) as exc:
            guard(_request({"sapling_session": _session(host_claim=True)}))
        assert exc.value.status_code == 401

    def test_plain_cookie_is_the_session_on_an_http_backend(self, guard, monkeypatch):
        monkeypatch.setattr(config, "SECURE_COOKIES", False)
        assert guard(_request({"sapling_session": _session(host_claim=True)}))["user_id"] == "user_alice"
        assert guard(_request({"sapling_session": _session(host_claim=False)}))["user_id"] == "user_alice"

    def test_presented_session_token_and_credentials_see_both_names(self):
        assert auth_guard.presented_session_token(_request({"__Host-sapling_session": "a.b"})) == "a.b"
        assert auth_guard.presented_session_token(_request({"sapling_session": "c.d"})) == "c.d"
        assert auth_guard.presented_session_token(_request({})) is None

    def test_session_cookie_name_helper(self):
        assert session_tokens.session_cookie_name(True) == "__Host-sapling_session"
        assert session_tokens.session_cookie_name(False) == "sapling_session"

    def test_mint_session_claims_cannot_override_the_format(self):
        with pytest.raises(ValueError):
            session_tokens.mint_session("u", secret=SECRET, claims={"typ": "session"})


def _login_app(monkeypatch, *, secure: bool) -> TestClient:
    monkeypatch.setattr(config, "APP_ENV", "test")
    monkeypatch.setattr(config, "SESSION_SECRET", SECRET)
    monkeypatch.setattr(config, "SECURE_COOKIES", secure)
    app = FastAPI()
    app.include_router(auth_module.router, prefix="/api/auth")
    app.include_router(handoff_routes.router, prefix="/api/auth")
    return TestClient(app)


class TestTestLoginCookieName:
    def test_http_stack_gets_the_plain_name(self, monkeypatch):
        resp = _login_app(monkeypatch, secure=False).post("/api/auth/test-login", json={"user_id": "u1"})
        assert resp.json()["cookie_name"] == "sapling_session"
        assert resp.json()["signin_cookie_name"] == "sapling_signin"
        assert resp.headers["set-cookie"].startswith("sapling_session=")

    def test_secure_backend_gets_the_host_prefixed_cookie(self, monkeypatch):
        resp = _login_app(monkeypatch, secure=True).post("/api/auth/test-login", json={"user_id": "u1"})
        body = resp.json()
        assert body["cookie_name"] == "__Host-sapling_session"
        assert body["signin_cookie_name"] == "__Host-sapling_signin"
        set_cookie = resp.headers["set-cookie"]
        assert set_cookie.startswith("__Host-sapling_session=")
        # The prefix's contract: Secure, Path=/, no Domain.
        assert "Secure" in set_cookie and "Path=/" in set_cookie
        assert "domain=" not in set_cookie.lower()

    def test_handoff_from_test_login_exchanges_with_its_nonce(self, monkeypatch):
        consumed: set[str] = set()
        monkeypatch.setattr(handoff, "_consume_jti", lambda jti, ttl: not (jti in consumed or consumed.add(jti)))
        client = _login_app(monkeypatch, secure=False)
        body = client.post("/api/auth/test-login", json={"user_id": "u1"}).json()
        resp = client.post("/api/auth/handoff/exchange",
                           json={"token": body["handoff_token"], "nonce": body["signin_nonce"]})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"user_id": "u1"}


# ── M1: CSRF origin check ───────────────────────────────────────────────────

TRUSTED = frozenset({"https://saplinglearn.com", "https://www.saplinglearn.com"})
COOKIE = {"cookie": "theme=dark; __Host-sapling_session=t.s"}


def _decide(method="POST", path="/api/notes", headers=None):
    return csrf_origin.decide(method, path, headers or {}, TRUSTED, extra_trusted=lambda o: False)


class TestCsrfDecide:
    def test_same_origin_post_with_cookie_passes(self):
        assert _decide(headers={**COOKIE, "origin": "https://saplinglearn.com",
                                "sec-fetch-site": "same-origin"}) is None

    def test_sibling_subdomain_post_with_cookie_is_refused(self):
        assert _decide(headers={**COOKIE, "origin": "https://staging.saplinglearn.com",
                                "sec-fetch-site": "same-site"}) is not None

    def test_null_origin_is_refused(self):
        assert _decide(headers={**COOKIE, "origin": "null"}) is not None

    @pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
    def test_every_unsafe_method_is_checked(self, method):
        assert _decide(method=method, headers={**COOKIE, "origin": "https://evil.example"}) is not None

    def test_safe_methods_are_never_checked(self):
        assert _decide(method="GET", headers={**COOKIE, "origin": "https://evil.example"}) is None

    def test_no_session_cookie_no_check(self):
        assert _decide(headers={"cookie": "theme=dark", "origin": "https://evil.example"}) is None
        assert _decide(headers={"cookie": "xsapling_session=a", "origin": "https://evil.example"}) is None

    def test_legacy_cookie_name_counts_as_a_session(self):
        assert _decide(headers={"cookie": "sapling_session=a.b",
                                "origin": "https://evil.example"}) is not None

    def test_referer_is_the_fallback_when_origin_is_missing(self):
        assert _decide(headers={**COOKIE, "referer": "https://saplinglearn.com/notes",
                                "sec-fetch-site": "same-origin"}) is None
        assert _decide(headers={**COOKIE, "referer": "https://staging.saplinglearn.com/x",
                                "sec-fetch-site": "same-site"}) is not None

    def test_browser_request_without_origin_or_referer_is_refused(self):
        assert _decide(headers={**COOKIE, "sec-fetch-site": "same-site"}) is not None

    def test_server_side_call_without_browser_headers_passes(self):
        """The session BFF's sign-out revoke (POST /api/auth/logout with the
        cookie, from the frontend server): no Origin, no Sec-Fetch-*."""
        assert _decide(path="/api/auth/logout", headers=dict(COOKIE)) is None

    @pytest.mark.parametrize("path", ["/api/internal/account-sync/import", "/api/internal/metrics",
                                      "/api/email/unsubscribe"])
    def test_token_authenticated_paths_are_exempt(self, path):
        assert _decide(path=path, headers={**COOKIE, "origin": "https://evil.example"}) is None

    def test_staging_previews_are_trusted_on_the_staging_backend(self, monkeypatch):
        preview = "https://pr-12-frontend-staging.saplinglearn.workers.dev"
        headers = {**COOKIE, "origin": preview}
        monkeypatch.setattr(config, "APP_ENV", "staging")
        assert csrf_origin.decide("POST", "/api/notes", headers, TRUSTED) is None
        monkeypatch.setattr(config, "APP_ENV", "production")
        assert csrf_origin.decide("POST", "/api/notes", headers, TRUSTED) is not None

    @pytest.mark.parametrize("origin", ["http://localhost:3104", "http://127.0.0.1:3104"])
    def test_loopback_origins_only_on_a_local_or_test_backend(self, monkeypatch, origin):
        headers = {**COOKIE, "origin": origin}
        monkeypatch.setattr(config, "APP_ENV", "test")
        assert csrf_origin.decide("POST", "/api/notes", headers, TRUSTED) is None
        monkeypatch.setattr(config, "APP_ENV", "production")
        assert csrf_origin.decide("POST", "/api/notes", headers, TRUSTED) is not None
        monkeypatch.setattr(config, "APP_ENV", "test")
        assert csrf_origin.decide("POST", "/api/notes", {**COOKIE, "origin": "https://localhost.evil.example"},
                                  TRUSTED) is not None


class TestCsrfMiddlewareOnTheApp:
    """Through main.app's real middleware stack (CORS allowlist from config)."""

    @pytest.fixture
    def client(self):
        from main import app

        return TestClient(app, raise_server_exceptions=False)

    def test_cross_origin_cookie_post_is_403_before_routing(self, client):
        resp = client.post("/api/no-such-route", headers={
            "Origin": "https://staging.saplinglearn.com",
            "Cookie": "__Host-sapling_session=t.s",
        })
        assert resp.status_code == 403
        assert resp.json() == {"detail": "Cross-origin request refused"}

    def test_allowlisted_origin_reaches_routing(self, client):
        resp = client.post("/api/no-such-route", headers={
            "Origin": "https://saplinglearn.com",
            "Cookie": "__Host-sapling_session=t.s",
        })
        assert resp.status_code == 404

    def test_the_handoff_exchange_is_mounted_and_refuses_garbage(self, client):
        resp = client.post("/api/auth/handoff/exchange", json={"token": "a.b", "nonce": NONCE})
        assert resp.status_code == 401

    def test_cookieless_cross_origin_post_is_not_this_middlewares_business(self, client):
        resp = client.post("/api/no-such-route", headers={"Origin": "https://evil.example"})
        assert resp.status_code == 404


# ── M2: single-use, browser-bound handoff ───────────────────────────────────


@pytest.fixture
def store(monkeypatch):
    """An in-memory stand-in for consume_auth_handoff()."""
    consumed: set[str] = set()

    def consume(jti, ttl):
        assert 1 <= ttl <= 3600
        if jti in consumed:
            return False
        consumed.add(jti)
        return True

    monkeypatch.setattr(handoff, "_consume_jti", consume)
    return consumed


@pytest.fixture
def exchange_client(monkeypatch):
    monkeypatch.setattr(config, "SESSION_SECRET", SECRET)
    app = FastAPI()
    app.include_router(auth_module.router, prefix="/api/auth")
    app.include_router(handoff_routes.router, prefix="/api/auth")
    return TestClient(app)


def _handoff(binding: str | None = handoff.binding_for_nonce(NONCE), user_id="user_alice"):
    return handoff.mint_handoff(user_id, ttl=300, secret=SECRET, binding=binding)


class TestHandoffExchange:
    def test_normal_flow_returns_the_user(self, exchange_client, store):
        resp = exchange_client.post("/api/auth/handoff/exchange", json={"token": _handoff(), "nonce": NONCE})
        assert resp.status_code == 200
        assert resp.json() == {"user_id": "user_alice"}
        assert resp.headers["cache-control"] == "no-store"

    def test_replay_is_refused(self, exchange_client, store):
        token = _handoff()
        assert exchange_client.post("/api/auth/handoff/exchange",
                                    json={"token": token, "nonce": NONCE}).status_code == 200
        replay = exchange_client.post("/api/auth/handoff/exchange", json={"token": token, "nonce": NONCE})
        assert replay.status_code == 401

    def test_another_browser_without_the_nonce_is_refused(self, exchange_client, store):
        resp = exchange_client.post("/api/auth/handoff/exchange", json={"token": _handoff()})
        assert resp.status_code == 401
        assert not store  # refused before the jti was spent

    def test_another_browser_with_its_own_nonce_is_refused(self, exchange_client, store):
        resp = exchange_client.post("/api/auth/handoff/exchange",
                                    json={"token": _handoff(), "nonce": "x" * 43})
        assert resp.status_code == 401
        assert not store

    def test_unbound_handoff_is_refused(self, exchange_client, store):
        resp = exchange_client.post("/api/auth/handoff/exchange",
                                    json={"token": _handoff(binding=None), "nonce": NONCE})
        assert resp.status_code == 401

    def test_handoff_without_jti_is_refused(self, exchange_client, store):
        legacy = session_tokens.mint_session("user_alice", ttl=300, secret=SECRET, typ="handoff",
                                             claims={"bh": handoff.binding_for_nonce(NONCE)})
        resp = exchange_client.post("/api/auth/handoff/exchange", json={"token": legacy, "nonce": NONCE})
        assert resp.status_code == 401

    def test_a_session_token_is_not_a_handoff(self, exchange_client, store):
        session = session_tokens.mint_session("user_alice", ttl=300, secret=SECRET,
                                              claims={"jti": "j" * 24, "bh": handoff.binding_for_nonce(NONCE)})
        resp = exchange_client.post("/api/auth/handoff/exchange", json={"token": session, "nonce": NONCE})
        assert resp.status_code == 401

    def test_forged_and_expired_handoffs_are_refused(self, exchange_client, store, monkeypatch):
        other = handoff.mint_handoff("user_alice", ttl=300, secret="another-secret-of-at-least-32-bytes!!",
                                     binding=handoff.binding_for_nonce(NONCE))
        assert exchange_client.post("/api/auth/handoff/exchange",
                                    json={"token": other, "nonce": NONCE}).status_code == 401
        token = _handoff()
        real_time = time.time
        monkeypatch.setattr(handoff.time, "time", lambda: real_time() + 3600)
        assert exchange_client.post("/api/auth/handoff/exchange",
                                    json={"token": token, "nonce": NONCE}).status_code == 401

    def test_store_down_fails_closed(self, exchange_client, monkeypatch):
        def boom(*a, **k):
            raise httpx.ConnectError("down")

        monkeypatch.setattr("db.connection.rpc", boom)
        resp = exchange_client.post("/api/auth/handoff/exchange", json={"token": _handoff(), "nonce": NONCE})
        assert resp.status_code == 503

    def test_consume_calls_the_sql_function_with_the_jti_hash(self, monkeypatch):
        calls = []

        def fake_rpc(name, params, *, timeout=None):
            calls.append((name, params))
            return True

        monkeypatch.setattr("db.connection.rpc", fake_rpc)
        assert handoff._consume_jti("the-jti-value-123456", 400) is True
        name, params = calls[0]
        assert name == "consume_auth_handoff"
        assert params == {"p_jti_hash": hashlib.sha256(b"the-jti-value-123456").hexdigest(), "p_ttl_sec": 400}

    def test_consume_unexpected_answer_is_unavailable(self, monkeypatch):
        monkeypatch.setattr("db.connection.rpc", lambda *a, **k: [{"x": 1, "y": 2}])
        with pytest.raises(handoff.HandoffStoreUnavailable):
            handoff._consume_jti("the-jti-value-123456", 400)


# ── M2: /google seals the binding, the callback signs it into the handoff ───


@pytest.fixture
def oauth(monkeypatch):
    monkeypatch.setattr(auth_module, "GOOGLE_AVAILABLE", True)
    monkeypatch.setattr(auth_module, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(auth_module, "SESSION_SECRET", SECRET)
    monkeypatch.setattr("services.auth.oauth_state.SESSION_SECRET", SECRET)
    auth_module.clear_consumed_oauth_nonces()
    flow = MagicMock()
    flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?x=1", "s")
    flow.credentials = MagicMock(token="access", refresh_token="refresh", expiry=None)
    flow_cls = MagicMock()
    flow_cls.from_client_config.return_value = flow
    monkeypatch.setattr(auth_module, "Flow", flow_cls, raising=False)
    userinfo = MagicMock()
    userinfo.raise_for_status.return_value = None
    userinfo.json.return_value = {"id": "4455", "email": "s@bu.edu", "name": "S T",
                                  "picture": "", "verified_email": True}
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
    factory("users").select.return_value = [{"id": "user_4455", "is_approved": True, "deleted_at": None}]
    app = FastAPI()
    app.include_router(auth_module.router, prefix="/api/auth")
    app.include_router(handoff_routes.router, prefix="/api/auth")
    return TestClient(app)


def _payload(token: str) -> dict:
    b64 = token.split(".")[0]
    return json.loads(base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)))


class TestBindingThroughOAuth:
    def _sign_in(self, client, binding):
        q = f"?binding={binding}" if binding else ""
        start = client.get(f"/api/auth/google{q}", follow_redirects=False)
        assert start.status_code in (302, 307)
        cookie = auth_module._decode_oauth_cookie(client.cookies.get(auth_module.OAUTH_STATE_COOKIE))
        state = auth_module._encode_state({"action": "signin", "n": cookie["n"]})
        done = client.get(f"/api/auth/google/callback?code=c&state={state}", follow_redirects=False)
        token = parse_qs(urlparse(done.headers["location"]).query)["auth_token"][0]
        return cookie, _payload(token), token

    def test_binding_is_sealed_and_signed_into_the_handoff(self, oauth):
        binding = handoff.binding_for_nonce(NONCE)
        cookie, payload, _ = self._sign_in(oauth, binding)
        assert cookie["bh"] == binding
        assert payload["typ"] == "handoff"
        assert payload["bh"] == binding
        assert len(payload["jti"]) >= 16

    def test_malformed_binding_is_dropped(self, oauth):
        cookie, payload, _ = self._sign_in(oauth, "not-a-binding")
        assert "bh" not in cookie and "bh" not in payload

    def test_each_sign_in_gets_a_fresh_jti(self, oauth):
        binding = handoff.binding_for_nonce(NONCE)
        _, first, _ = self._sign_in(oauth, binding)
        _, second, _ = self._sign_in(oauth, binding)
        assert first["jti"] != second["jti"]

    def test_full_flow_exchanges_once(self, oauth, store, monkeypatch):
        monkeypatch.setattr(config, "SESSION_SECRET", SECRET)
        _, _, token = self._sign_in(oauth, handoff.binding_for_nonce(NONCE))
        first = oauth.post("/api/auth/handoff/exchange", json={"token": token, "nonce": NONCE})
        assert first.status_code == 200 and first.json() == {"user_id": "user_4455"}
        again = oauth.post("/api/auth/handoff/exchange", json={"token": token, "nonce": NONCE})
        assert again.status_code == 401
