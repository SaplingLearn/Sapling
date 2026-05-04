"""
Unit tests for routes/auth.py OAuth state hardening.

Covers:
- HMAC cookie round-trip (encode -> decode)
- Tampered cookie rejection (MAC and payload)
- _clean_popup_id charset/length validation
- _decode_state happy path
- Callback rejects when state nonce doesn't match cookie nonce
- Callback handles missing/malformed cookie via popup-aware error redirect
"""
import json
import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.auth as auth_module

# Build a minimal app that mounts ONLY the auth router so these tests don't
# pull in main.py (which imports logfire and the full router stack).
_app = FastAPI()
_app.include_router(auth_module.router, prefix="/api/auth")
client = TestClient(_app)


# ── HMAC cookie round-trip ────────────────────────────────────────────────────


class TestOAuthCookieRoundTrip:
    def test_round_trip_returns_same_payload(self, monkeypatch):
        monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")
        payload = {"n": "abc123", "cv": "verifier", "popup_id": "popup-1"}
        cookie = auth_module._encode_oauth_cookie(payload)
        decoded = auth_module._decode_oauth_cookie(cookie)
        assert decoded == payload

    def test_tampered_mac_rejected(self, monkeypatch):
        monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")
        cookie = auth_module._encode_oauth_cookie(
            {"n": "abc123", "cv": "verifier", "popup_id": None}
        )
        payload_b64, sig_b64 = cookie.rsplit(".", 1)
        # flip a character in the signature
        bad_sig = ("A" if sig_b64[0] != "A" else "B") + sig_b64[1:]
        tampered = f"{payload_b64}.{bad_sig}"
        assert auth_module._decode_oauth_cookie(tampered) is None

    def test_tampered_payload_rejected(self, monkeypatch):
        monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")
        cookie = auth_module._encode_oauth_cookie(
            {"n": "abc123", "cv": "verifier", "popup_id": None}
        )
        _, sig_b64 = cookie.rsplit(".", 1)
        bogus_payload = base64.urlsafe_b64encode(
            json.dumps({"n": "evil", "cv": "x", "popup_id": None}).encode()
        ).decode().rstrip("=")
        tampered = f"{bogus_payload}.{sig_b64}"
        assert auth_module._decode_oauth_cookie(tampered) is None

    def test_missing_cookie_returns_none(self, monkeypatch):
        monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")
        assert auth_module._decode_oauth_cookie(None) is None
        assert auth_module._decode_oauth_cookie("") is None

    def test_malformed_cookie_returns_none(self, monkeypatch):
        monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")
        assert auth_module._decode_oauth_cookie("not-a-valid-cookie") is None
        assert auth_module._decode_oauth_cookie("only_payload_no_dot") is None

    def test_fallback_in_memory_store_round_trip(self, monkeypatch):
        # Without SESSION_SECRET, encode stashes the payload in an in-memory
        # dict keyed by nonce. Decode retrieves it.
        monkeypatch.setattr(auth_module, "SESSION_SECRET", "")
        auth_module._OAUTH_FALLBACK_STORE.clear()
        payload = {"n": "fallback-nonce", "cv": "verifier", "popup_id": "p"}
        cookie = auth_module._encode_oauth_cookie(payload)
        decoded = auth_module._decode_oauth_cookie(cookie)
        assert decoded == payload

    def test_fallback_unknown_nonce_returns_none(self, monkeypatch):
        monkeypatch.setattr(auth_module, "SESSION_SECRET", "")
        auth_module._OAUTH_FALLBACK_STORE.clear()
        # Build a cookie payload whose nonce was never registered
        bogus = base64.urlsafe_b64encode(
            json.dumps({"n": "ghost", "cv": "x", "popup_id": None}).encode()
        ).decode().rstrip("=")
        assert auth_module._decode_oauth_cookie(bogus) is None


# ── _clean_popup_id ───────────────────────────────────────────────────────────


class TestCleanPopupId:
    def test_valid_uuid_returned_as_is(self):
        uid = "550e8400-e29b-41d4-a716-446655440000"
        assert auth_module._clean_popup_id(uid) == uid

    def test_alphanumeric_with_underscore_ok(self):
        assert auth_module._clean_popup_id("popup_abc_123") == "popup_abc_123"

    def test_slash_rejected(self):
        assert auth_module._clean_popup_id("abc/def") is None

    def test_empty_string_rejected(self):
        assert auth_module._clean_popup_id("") is None

    def test_none_returns_none(self):
        assert auth_module._clean_popup_id(None) is None

    def test_overlong_rejected(self):
        assert auth_module._clean_popup_id("a" * 129) is None

    def test_max_length_accepted(self):
        s = "a" * 128
        assert auth_module._clean_popup_id(s) == s

    def test_special_chars_rejected(self):
        assert auth_module._clean_popup_id("abc def") is None
        assert auth_module._clean_popup_id("abc<script>") is None
        assert auth_module._clean_popup_id("abc.def") is None


# ── _decode_state happy path ──────────────────────────────────────────────────


class TestDecodeState:
    def test_round_trip(self):
        original = {"action": "signin", "n": "nonce-value"}
        encoded = auth_module._encode_state(original)
        assert auth_module._decode_state(encoded) == original

    def test_invalid_state_returns_empty(self):
        assert auth_module._decode_state("!!!not-base64!!!") == {}

    def test_empty_state_returns_empty(self):
        assert auth_module._decode_state("") == {}


# ── Callback nonce-mismatch / missing cookie via TestClient ───────────────────


class TestCallbackStateValidation:
    def test_missing_cookie_redirects_with_invalid_state(self, monkeypatch):
        monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")
        monkeypatch.setattr(auth_module, "GOOGLE_AVAILABLE", True)
        state_param = auth_module._encode_state({"action": "signin", "n": "any"})
        r = client.get(
            f"/api/auth/google/callback?code=foo&state={state_param}",
            follow_redirects=False,
        )
        assert r.status_code in (302, 307)
        assert "error=invalid_state" in r.headers["location"]

    def test_nonce_mismatch_redirects_with_invalid_state(self, monkeypatch):
        monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")
        monkeypatch.setattr(auth_module, "GOOGLE_AVAILABLE", True)
        cookie = auth_module._encode_oauth_cookie(
            {"n": "cookie-nonce", "cv": "verifier", "popup_id": None}
        )
        state_param = auth_module._encode_state(
            {"action": "signin", "n": "different-nonce"}
        )
        c = TestClient(_app)
        c.cookies.set(auth_module.OAUTH_STATE_COOKIE, cookie)
        r = c.get(
            f"/api/auth/google/callback?code=foo&state={state_param}",
            follow_redirects=False,
        )
        assert r.status_code in (302, 307)
        assert "error=invalid_state" in r.headers["location"]

    def test_popup_id_missing_when_cookie_missing(self, monkeypatch):
        # When cookie is missing, popup_id is unknown so failure goes through
        # the non-popup branch (fallback path /auth) and doesn't include popup_id.
        monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")
        monkeypatch.setattr(auth_module, "GOOGLE_AVAILABLE", True)
        state_param = auth_module._encode_state({"action": "signin", "n": "any"})
        r = client.get(
            f"/api/auth/google/callback?code=foo&state={state_param}",
            follow_redirects=False,
        )
        assert "popup_id" not in r.headers["location"]
        assert "/auth?" in r.headers["location"]

    def test_tampered_cookie_redirects_with_invalid_state(self, monkeypatch):
        monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")
        monkeypatch.setattr(auth_module, "GOOGLE_AVAILABLE", True)
        state_param = auth_module._encode_state({"action": "signin", "n": "n1"})
        c = TestClient(_app)
        c.cookies.set(auth_module.OAUTH_STATE_COOKIE, "garbage.cookie.value")
        r = c.get(
            f"/api/auth/google/callback?code=foo&state={state_param}",
            follow_redirects=False,
        )
        assert r.status_code in (302, 307)
        assert "error=invalid_state" in r.headers["location"]

    def test_google_not_available_returns_error_redirect(self, monkeypatch):
        monkeypatch.setattr(auth_module, "GOOGLE_AVAILABLE", False)
        r = client.get(
            "/api/auth/google/callback?code=foo&state=bar",
            follow_redirects=False,
        )
        assert r.status_code in (302, 307)
        assert "error=google_not_configured" in r.headers["location"]


from unittest.mock import MagicMock, patch


class TestLastSignInStamp:
    def test_stamp_seam_writes_last_sign_in_at(self):
        from routes import auth as auth_routes

        with patch.object(auth_routes, "table") as t:
            users_table = MagicMock()
            users_table.update = MagicMock(return_value=[{}])
            t.return_value = users_table

            auth_routes._stamp_last_sign_in_for_test("u1")

        users_table.update.assert_called_once()
        update_payload = users_table.update.call_args.args[0]
        assert "last_sign_in_at" in update_payload
        assert update_payload["last_sign_in_at"]
        filters = users_table.update.call_args.args[1] if len(users_table.update.call_args.args) > 1 else users_table.update.call_args.kwargs.get("filters")
        assert filters == {"id": "eq.u1"}
