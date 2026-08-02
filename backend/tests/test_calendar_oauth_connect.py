"""
Tests for the Google Calendar OAuth *connect* flow (#61).

The calendar OAuth routes — ``GET /api/calendar/auth-url`` and
``GET /api/calendar/callback`` — were dropped during the SQLite→Supabase
migration, but ``config.GOOGLE_SCOPES`` / ``config.GOOGLE_REDIRECT_URI`` and the
frontend "Connect Google" button (``Calendar.tsx`` → ``calendarAuthUrl``) still
point at them. With the routes gone, clicking "Connect Google" 404'd, so a user
could never (re)grant calendar access and ``/sync`` · ``/export`` · ``/import``
all failed with 401 "Not connected to Google Calendar."

These tests cover the restored routes plus the security boundary the connect
flow must hold (the "auth scoping holistically" ask on #61, sibling of the #123
export IDOR): the freshly minted tokens are bound to the **session-authenticated
user carried in the HMAC-signed state cookie**, never to an attacker-controllable
request parameter, and a forged/mismatched state can never drive a token write.
"""
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.auth as auth_module
import routes.calendar as cal

# Mount ONLY the calendar router so these tests don't pull in main.py's full
# router + logfire stack (mirrors test_auth_state.py).
_app = FastAPI()
_app.include_router(cal.router, prefix="/api/calendar")


@pytest.fixture(autouse=True)
def _signed_state(monkeypatch):
    # The reused OAuth cookie/state helpers read routes.auth.SESSION_SECRET;
    # set it so state cookies are HMAC-signed (the production path) in tests.
    monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")


def _mock_flow(monkeypatch, *, token="acc", refresh="ref", expiry=None):
    """Patch routes.calendar.Flow so no real Google network hop happens."""
    flow = MagicMock(name="flow")
    flow.authorization_url.return_value = (
        "https://accounts.google.com/o/oauth2/auth?scope=calendar",
        "state",
    )
    creds = MagicMock(name="creds")
    creds.token = token
    creds.refresh_token = refresh
    creds.expiry = expiry
    flow.credentials = creds
    flow_cls = MagicMock(name="Flow")
    flow_cls.from_client_config.return_value = flow
    monkeypatch.setattr(cal, "Flow", flow_cls, raising=False)
    monkeypatch.setattr(cal, "GOOGLE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(cal, "GOOGLE_CLIENT_ID", "cid", raising=False)
    return flow, creds


class TestCalendarAuthUrl:
    def test_redirects_to_google_and_sets_signed_state_cookie(self, monkeypatch):
        flow, _ = _mock_flow(monkeypatch)
        client = TestClient(_app)
        r = client.get(
            "/api/calendar/auth-url?user_id=user_a", follow_redirects=False
        )
        assert r.status_code in (302, 307)
        assert "accounts.google.com" in r.headers["location"]
        # A state cookie must be set so the callback can bind tokens to user_a.
        assert cal.CALENDAR_OAUTH_STATE_COOKIE in r.headers.get("set-cookie", "")
        # Must request an offline refresh token + explicit consent (so a refresh
        # token is actually returned) — otherwise long-lived sync breaks.
        _, kwargs = flow.authorization_url.call_args
        assert kwargs.get("access_type") == "offline"
        assert kwargs.get("prompt") == "consent"

    def test_400_when_google_not_configured(self, monkeypatch):
        monkeypatch.setattr(cal, "GOOGLE_AVAILABLE", False, raising=False)
        client = TestClient(_app)
        r = client.get(
            "/api/calendar/auth-url?user_id=user_a", follow_redirects=False
        )
        assert r.status_code == 400


class TestCalendarCallback:
    def _initiate(self, client):
        """Drive auth-url to obtain a valid signed state cookie + matching state
        query param (as Google would echo it back)."""
        r1 = client.get(
            "/api/calendar/auth-url?user_id=user_a", follow_redirects=False
        )
        cookie_val = r1.cookies.get(cal.CALENDAR_OAUTH_STATE_COOKIE)
        payload = auth_module._decode_oauth_cookie(cookie_val)
        state = auth_module._encode_state(
            {"action": "calendar", "n": payload["n"]}
        )
        return state

    def test_happy_path_stores_tokens_scoped_to_cookie_user(self, monkeypatch):
        _mock_flow(monkeypatch)
        upserts = []
        fake_table = MagicMock()
        fake_table.return_value.upsert.side_effect = (
            lambda *a, **k: upserts.append((a, k))
        )
        monkeypatch.setattr(cal, "table", fake_table)
        monkeypatch.setattr(cal, "encrypt", lambda v: f"ENC({v})")
        monkeypatch.setattr(
            cal, "encrypt_if_present", lambda v: f"ENC({v})" if v else v
        )

        client = TestClient(_app)
        state = self._initiate(client)
        r = client.get(
            f"/api/calendar/callback?code=xyz&state={state}",
            follow_redirects=False,
        )

        assert r.status_code in (302, 307)
        assert "/calendar?connected=true" in r.headers["location"]
        assert upserts, "expected an oauth_tokens upsert"
        (args, kwargs) = upserts[-1]
        row = args[0]
        # Bound to the cookie's user_id — never a request parameter.
        assert row["user_id"] == "user_a"
        assert row["access_token"] == "ENC(acc)"
        assert row["refresh_token"] == "ENC(ref)"
        # expiry None → None, never "" (invalid TIMESTAMPTZ, migration 0024).
        assert row["expires_at"] is None
        assert kwargs.get("on_conflict") == "user_id"

    def test_nonce_mismatch_rejected_no_token_write(self, monkeypatch):
        _mock_flow(monkeypatch)
        fake_table = MagicMock()
        monkeypatch.setattr(cal, "table", fake_table)

        client = TestClient(_app)
        self._initiate(client)  # sets a valid cookie in the jar
        # Attacker-forged state with a nonce that does NOT match the signed cookie.
        forged = auth_module._encode_state(
            {"action": "calendar", "n": "attacker-nonce"}
        )
        r = client.get(
            f"/api/calendar/callback?code=xyz&state={forged}",
            follow_redirects=False,
        )
        assert r.status_code in (302, 307)
        assert "connected=true" not in r.headers["location"]
        fake_table.return_value.upsert.assert_not_called()

    def test_missing_cookie_rejected_no_token_write(self, monkeypatch):
        _mock_flow(monkeypatch)
        fake_table = MagicMock()
        monkeypatch.setattr(cal, "table", fake_table)

        client = TestClient(_app)  # never calls auth-url → no state cookie
        state = auth_module._encode_state({"action": "calendar", "n": "whatever"})
        r = client.get(
            f"/api/calendar/callback?code=xyz&state={state}",
            follow_redirects=False,
        )
        assert r.status_code in (302, 307)
        assert "connected=true" not in r.headers["location"]
        fake_table.return_value.upsert.assert_not_called()

    def test_google_error_param_rejected_no_token_write(self, monkeypatch):
        _mock_flow(monkeypatch)
        fake_table = MagicMock()
        monkeypatch.setattr(cal, "table", fake_table)

        client = TestClient(_app)
        state = self._initiate(client)
        # User denied consent: Google redirects back with ?error=access_denied.
        r = client.get(
            f"/api/calendar/callback?error=access_denied&state={state}",
            follow_redirects=False,
        )
        assert r.status_code in (302, 307)
        assert "connected=true" not in r.headers["location"]
        fake_table.return_value.upsert.assert_not_called()


class TestRefreshExpiresAt:
    def test_refresh_writes_none_not_empty_string_when_no_expiry(self, monkeypatch):
        """_get_refreshed_credentials must never persist expires_at="" — it's an
        invalid TIMESTAMPTZ after migration 0024 (see the auth.py callback which
        fixed the same hazard). When a refresh yields no expiry, write None."""
        updates = []
        fake_table = MagicMock()
        fake_table.return_value.update.side_effect = (
            lambda *a, **k: updates.append((a, k))
        )
        monkeypatch.setattr(cal, "table", fake_table)
        monkeypatch.setattr(cal, "encrypt", lambda v: f"ENC({v})")
        monkeypatch.setattr(cal, "decrypt", lambda v: v)

        creds = MagicMock()
        creds.refresh_token = "ref"
        creds.token = "newacc"
        creds.expiry = None
        creds.refresh = MagicMock()
        monkeypatch.setattr(cal, "Credentials", MagicMock(return_value=creds), raising=False)
        monkeypatch.setattr(cal, "Request", MagicMock(), raising=False)

        token_row = {
            "user_id": "user_a",
            "access_token": "enc_acc",
            "refresh_token": "enc_ref",
            "expires_at": "2000-01-01T00:00:00+00:00",  # far past → forces refresh
        }
        cal._get_refreshed_credentials(token_row)

        assert updates, "expected an oauth_tokens update on refresh"
        (args, _kwargs) = updates[-1]
        assert args[0]["expires_at"] is None
