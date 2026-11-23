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
import routes.calendar as calendar_routes
import routes.calendar_connect as cal
from tests.split_patches import set_auth_session_secret

# Mount ONLY the calendar consent router so these tests don't pull in main.py's full
# router + logfire stack (mirrors test_auth_state.py).
_app = FastAPI()
_app.include_router(cal.router, prefix="/api/calendar")


@pytest.fixture(autouse=True)
def _signed_state(monkeypatch):
    # The reused OAuth cookie/state helpers read routes.auth.SESSION_SECRET;
    # set it so state cookies are HMAC-signed (the production path) in tests.
    set_auth_session_secret(monkeypatch, "test-secret-key")


IDENTITY = list(auth_module.AUTH_SCOPES)
CALENDAR = list(cal.GOOGLE_SCOPES)


def _mock_flow(monkeypatch, *, token="acc", refresh="ref", expiry=None,
               granted=IDENTITY + CALENDAR):
    """Patch routes.calendar_connect.Flow so no real Google network hop happens.
    `granted` is the token response's scope list (include_granted_scopes:
    the sign-in's identity scopes come back too)."""
    flow = MagicMock(name="flow")
    flow.authorization_url.return_value = (
        "https://accounts.google.com/o/oauth2/auth?scope=calendar",
        "state",
    )
    creds = MagicMock(name="creds")
    creds.token = token
    creds.refresh_token = refresh
    creds.expiry = expiry
    creds.granted_scopes = granted
    flow.credentials = creds
    flow_cls = MagicMock(name="Flow")
    flow_cls.from_client_config.return_value = flow
    monkeypatch.setattr(cal, "Flow", flow_cls, raising=False)
    monkeypatch.setattr(cal, "GOOGLE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(cal, "GOOGLE_CLIENT_ID", "cid", raising=False)
    return flow, creds


class TestCalendarAuthUrl:
    @pytest.mark.parametrize("value", [None, [], "calendar", 123])
    def test_shared_callback_rejects_non_object_state(self, value):
        app = FastAPI()
        app.include_router(auth_module.router, prefix="/api/auth")
        result = TestClient(app).get("/api/auth/google/callback", params={
            "code": "mock-code", "state": auth_module._encode_state(value),
        }, follow_redirects=False)
        assert result.status_code in (302, 307)
        assert "invalid_state" in result.headers["location"]

    @pytest.mark.parametrize("redirect_uri", [
        "http://localhost:5000/api/auth/google/callback",
        "http://localhost:5000/api/calendar/callback",
    ])
    def test_redirects_to_google_and_sets_signed_state_cookie(self, monkeypatch, redirect_uri):
        flow, _ = _mock_flow(monkeypatch)
        monkeypatch.setattr(cal, "GOOGLE_REDIRECT_URI", redirect_uri)
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
        assert flow.redirect_uri == redirect_uri

    def test_shared_signin_callback_routes_calendar_consent_to_calendar_only(self, monkeypatch):
        _mock_flow(monkeypatch)
        app = FastAPI()
        app.include_router(cal.router, prefix="/api/calendar")
        app.include_router(auth_module.router, prefix="/api/auth")
        client = TestClient(app)
        started = client.get("/api/calendar/auth-url?user_id=user_a", follow_redirects=False)
        payload = auth_module._decode_oauth_cookie(started.cookies[cal.CALENDAR_OAUTH_STATE_COOKIE])
        state = auth_module._encode_state({"action": "calendar", "n": payload["n"]})
        token_table = MagicMock()
        monkeypatch.setattr(cal, "table", lambda name: token_table)
        result = client.get("/api/auth/google/callback", params={"code": "mock-code", "state": state}, follow_redirects=False)
        assert result.headers["location"].endswith("/calendar?connected=true")
        assert token_table.upsert.call_args.args[0]["user_id"] == "user_a"
        assert "sapling_session" not in result.cookies

    def test_shared_callback_rejects_forged_calendar_state(self, monkeypatch):
        flow, _ = _mock_flow(monkeypatch)
        app = FastAPI()
        app.include_router(cal.router, prefix="/api/calendar")
        app.include_router(auth_module.router, prefix="/api/auth")
        client = TestClient(app)
        client.get("/api/calendar/auth-url?user_id=user_a", follow_redirects=False)
        state = auth_module._encode_state({"action": "calendar", "n": "wrong-nonce"})
        result = client.get("/api/auth/google/callback", params={"code": "mock-code", "state": state}, follow_redirects=False)
        assert "calendar_error=invalid_state" in result.headers["location"]
        flow.fetch_token.assert_not_called()

    def test_shared_callback_honors_calendar_visibility_for_the_consent_user(self, monkeypatch):
        flow, _ = _mock_flow(monkeypatch)
        app = FastAPI()
        app.include_router(cal.router, prefix="/api/calendar")
        app.include_router(auth_module.router, prefix="/api/auth")
        client = TestClient(app)
        started = client.get("/api/calendar/auth-url?user_id=user_a&next=/dashboard", follow_redirects=False)
        payload = auth_module._decode_oauth_cookie(started.cookies[cal.CALENDAR_OAUTH_STATE_COOKIE])
        state = auth_module._encode_state({"action": "calendar", "n": payload["n"]})
        flags = MagicMock(side_effect=lambda key, user_id: "on" if key == "hide_calendar" else "off")
        monkeypatch.setattr("services.feature_flags.flag_variant", flags)
        result = client.get("/api/auth/google/callback", params={"code": "mock-code", "state": state}, follow_redirects=False)
        assert result.headers["location"].endswith("/dashboard?calendar_error=calendar_unavailable")
        flags.assert_any_call("hide_calendar", "user_a")
        flow.fetch_token.assert_not_called()

    def test_google_callback_relays_to_the_host_with_the_state_cookie(self, monkeypatch):
        flow, _ = _mock_flow(monkeypatch)
        monkeypatch.setattr(cal, "FRONTEND_URL", "https://app.example.test")
        monkeypatch.setattr(cal, "SECURE_COOKIES", True)
        token_table = MagicMock()
        monkeypatch.setattr(cal, "table", lambda name: token_table)
        app = FastAPI()
        app.include_router(cal.router, prefix="/api/calendar")
        app.include_router(auth_module.router, prefix="/api/auth")
        browser = TestClient(app, base_url="https://app.example.test")
        browser.get("/api/calendar/auth-url?user_id=user_a&return_to=https://untrusted.example.test", follow_redirects=False)
        state = flow.authorization_url.call_args.kwargs["state"]

        relay = browser.get("https://api.example.test/api/auth/google/callback", params={
            "code": "mock-code", "state": state,
        }, follow_redirects=False)
        assert relay.headers["location"].startswith("https://app.example.test/api/calendar/callback?")
        assert relay.headers["referrer-policy"] == "no-referrer"
        flow.fetch_token.assert_not_called()

        no_cookie = TestClient(app).get(relay.headers["location"], follow_redirects=False)
        assert no_cookie.headers["location"].endswith("/calendar?calendar_error=invalid_state")
        token_table.upsert.assert_not_called()
        finished = browser.get(relay.headers["location"], follow_redirects=False)
        assert finished.headers["location"] == "https://app.example.test/calendar?connected=true"
        assert token_table.upsert.call_args.args[0]["user_id"] == "user_a"

    def test_400_when_google_not_configured(self, monkeypatch):
        monkeypatch.setattr(cal, "GOOGLE_AVAILABLE", False, raising=False)
        client = TestClient(_app)
        r = client.get(
            "/api/calendar/auth-url?user_id=user_a", follow_redirects=False
        )
        assert r.status_code == 400


class TestCalendarAuthUrlNext:
    """`next`: where a successful connect lands (onboarding's Connect step).
    Sealed in the signed cookie, allowlisted on the way in AND out."""

    def _cookie(self, monkeypatch, query):
        _mock_flow(monkeypatch)
        r = TestClient(_app).get(
            f"/api/calendar/auth-url?user_id=user_a{query}", follow_redirects=False,
        )
        assert r.status_code in (302, 307)
        return auth_module._decode_oauth_cookie(r.cookies.get(cal.CALENDAR_OAUTH_STATE_COOKIE))

    @pytest.mark.parametrize("path", ["/dashboard", "/gradebook", "/calendar"])
    def test_an_allowlisted_next_is_sealed_in_the_cookie(self, monkeypatch, path):
        assert self._cookie(monkeypatch, f"&next={path}")["next"] == path

    @pytest.mark.parametrize("path", [
        "https://evil.example/", "//evil.example", "/admin", "/dashboard?x=1",
        "/dashboard/", "dashboard", "", "/Dashboard",
    ])
    def test_anything_else_is_ignored(self, monkeypatch, path):
        from urllib.parse import quote
        payload = self._cookie(monkeypatch, f"&next={quote(path, safe='')}")
        assert "next" not in payload
        assert payload["uid"] == "user_a"

    def test_no_next_is_the_default(self, monkeypatch):
        assert "next" not in self._cookie(monkeypatch, "")

    def test_the_consent_screen_asks_for_calendar_scopes_only(self, monkeypatch):
        flow, _ = _mock_flow(monkeypatch)
        TestClient(_app).get("/api/calendar/auth-url?user_id=user_a", follow_redirects=False)
        flow_cls = cal.Flow
        assert flow_cls.from_client_config.call_args.kwargs["scopes"] == CALENDAR
        assert flow.authorization_url.call_args.kwargs["include_granted_scopes"] == "true"


class TestCalendarCallback:
    def _initiate(self, client, query=""):
        """Drive auth-url to obtain a valid signed state cookie + matching state
        query param (as Google would echo it back)."""
        r1 = client.get(
            f"/api/calendar/auth-url?user_id=user_a{query}", follow_redirects=False
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
        monkeypatch.setattr(cal, "encrypt", lambda v, **_: f"ENC({v})")

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

    def _upserts(self, monkeypatch):
        upserts = []
        fake_table = MagicMock()
        fake_table.return_value.upsert.side_effect = lambda *a, **k: upserts.append((a, k))
        monkeypatch.setattr(cal, "table", fake_table)
        monkeypatch.setattr(cal, "encrypt", lambda v, **_: f"ENC({v})")
        return upserts

    def test_success_lands_on_next(self, monkeypatch):
        _mock_flow(monkeypatch)
        upserts = self._upserts(monkeypatch)
        client = TestClient(_app)
        state = self._initiate(client, "&next=/dashboard")
        r = client.get(f"/api/calendar/callback?code=xyz&state={state}", follow_redirects=False)
        assert r.headers["location"].endswith("/dashboard?connected=true")
        assert upserts

    def test_a_signed_but_unlisted_next_still_lands_on_calendar(self, monkeypatch):
        """Re-checked at the callback, so only a path the allowlist holds NOW
        is ever a redirect target."""
        _mock_flow(monkeypatch)
        self._upserts(monkeypatch)
        client = TestClient(_app)
        client.cookies.set(cal.CALENDAR_OAUTH_STATE_COOKIE, auth_module._encode_oauth_cookie(
            {"n": "n1", "cv": "v", "uid": "user_a", "next": "https://evil.example"}))
        state = auth_module._encode_state({"action": "calendar", "n": "n1"})
        r = client.get(f"/api/calendar/callback?code=xyz&state={state}", follow_redirects=False)
        assert r.headers["location"].endswith("/calendar?connected=true")
        assert "evil" not in r.headers["location"]

    @pytest.mark.parametrize("next_path", ["/gradebook", "/dashboard"])
    def test_a_failure_lands_on_next_with_its_code(self, monkeypatch, next_path):
        """Onboarding hands a Gradescope student on to /gradebook through the
        connect; a failed connect must keep that hand-off (and with
        hide_calendar on, /calendar itself redirects away)."""
        _mock_flow(monkeypatch)
        self._upserts(monkeypatch)
        client = TestClient(_app)
        state = self._initiate(client, f"&next={next_path}")
        r = client.get(
            f"/api/calendar/callback?error=access_denied&state={state}", follow_redirects=False,
        )
        assert r.headers["location"].endswith(f"{next_path}?calendar_error=access_denied")

    def test_a_failure_without_next_lands_on_calendar(self, monkeypatch):
        _mock_flow(monkeypatch)
        self._upserts(monkeypatch)
        client = TestClient(_app)
        state = self._initiate(client)
        r = client.get(f"/api/calendar/callback?state={state}", follow_redirects=False)
        assert r.headers["location"].endswith("/calendar?calendar_error=missing_code")

    def test_a_failure_with_a_signed_but_unlisted_next_lands_on_calendar(self, monkeypatch):
        """The failure path re-checks `next` exactly as the success path does."""
        _mock_flow(monkeypatch)
        self._upserts(monkeypatch)
        client = TestClient(_app)
        client.cookies.set(cal.CALENDAR_OAUTH_STATE_COOKIE, auth_module._encode_oauth_cookie(
            {"n": "n1", "cv": "v", "uid": "user_a", "next": "https://evil.example"}))
        state = auth_module._encode_state({"action": "calendar", "n": "n1"})
        r = client.get(
            f"/api/calendar/callback?error=access_denied&state={state}", follow_redirects=False,
        )
        assert r.headers["location"].endswith("/calendar?calendar_error=access_denied")
        assert "evil" not in r.headers["location"]

    def test_a_failure_with_no_cookie_lands_on_calendar(self, monkeypatch):
        _mock_flow(monkeypatch)
        client = TestClient(_app)
        state = auth_module._encode_state({"action": "calendar", "n": "whatever"})
        r = client.get(f"/api/calendar/callback?code=xyz&state={state}", follow_redirects=False)
        assert r.headers["location"].endswith("/calendar?calendar_error=invalid_state")

    def test_a_replayed_state_is_refused_and_writes_nothing(self, monkeypatch):
        """Each state nonce is honoured once, as at sign-in (#756): within the
        cookie's 10 minutes a second callback with the same state and another
        code must not overwrite the student's calendar tokens."""
        flow, _ = _mock_flow(monkeypatch)
        upserts = self._upserts(monkeypatch)
        client = TestClient(_app)
        state = self._initiate(client)
        cookie = client.cookies.get(cal.CALENDAR_OAUTH_STATE_COOKIE)

        first = client.get(f"/api/calendar/callback?code=one&state={state}", follow_redirects=False)
        assert first.headers["location"].endswith("/calendar?connected=true")
        assert len(upserts) == 1

        # The callback clears the cookie; a replay brings the captured one back.
        client.cookies.set(cal.CALENDAR_OAUTH_STATE_COOKIE, cookie)
        replay = client.get(f"/api/calendar/callback?code=two&state={state}", follow_redirects=False)
        assert replay.headers["location"].endswith("/calendar?calendar_error=invalid_state")
        assert len(upserts) == 1
        codes = [c.kwargs.get("code") for c in flow.fetch_token.call_args_list]
        assert codes == ["one"], "a replay must be refused before the code exchange"

    def test_the_exchange_flow_carries_no_scopes(self, monkeypatch):
        """include_granted_scopes returns the identity scopes too; with the
        calendar scopes on the session oauthlib raised "Scope has changed" and
        every connect ended in oauth_exchange_failed."""
        _mock_flow(monkeypatch)
        self._upserts(monkeypatch)
        client = TestClient(_app)
        state = self._initiate(client)
        client.get(f"/api/calendar/callback?code=xyz&state={state}", follow_redirects=False)
        last = cal.Flow.from_client_config.call_args
        assert last.kwargs["scopes"] is None

    @pytest.mark.parametrize("granted", [IDENTITY, IDENTITY + CALENDAR[:1], []])
    def test_a_grant_without_every_calendar_scope_is_not_stored(self, monkeypatch, granted):
        """Google's per-scope consent lets a student untick a calendar box.
        Such a grant cannot reach the calendar: nothing is stored, so the
        Calendar page never shows it as connected."""
        _mock_flow(monkeypatch, granted=granted)
        upserts = self._upserts(monkeypatch)
        client = TestClient(_app)
        state = self._initiate(client, "&next=/dashboard")
        r = client.get(f"/api/calendar/callback?code=xyz&state={state}", follow_redirects=False)
        assert r.headers["location"].endswith("/dashboard?calendar_error=scope_denied")
        assert upserts == []

    def test_a_grant_with_no_scope_list_is_what_was_asked(self, monkeypatch):
        """RFC 6749 §5.1: `scope` may be left out when it equals the request."""
        _mock_flow(monkeypatch, granted=None)
        upserts = self._upserts(monkeypatch)
        client = TestClient(_app)
        state = self._initiate(client)
        r = client.get(f"/api/calendar/callback?code=xyz&state={state}", follow_redirects=False)
        assert r.headers["location"].endswith("/calendar?connected=true")
        assert upserts

    def test_no_refresh_token_keeps_the_stored_one(self, monkeypatch):
        _mock_flow(monkeypatch, refresh=None)
        upserts = self._upserts(monkeypatch)
        cal.table.return_value.select.return_value = [{"refresh_token": "ENC(old)"}]
        client = TestClient(_app)
        state = self._initiate(client)
        client.get(f"/api/calendar/callback?code=xyz&state={state}", follow_redirects=False)
        (args, _kwargs) = upserts[-1]
        assert "refresh_token" not in args[0]
        assert args[0]["access_token"] == "ENC(acc)"

    @pytest.mark.parametrize("stored", [[], [{"refresh_token": None}]])
    def test_a_first_connect_without_a_refresh_token_fails(self, monkeypatch, stored):
        """prompt=consent normally returns a refresh token. Without one, and
        with none stored, the access token dies within the hour while /status
        says "connected": nothing is stored and the connect reports a failure."""
        _mock_flow(monkeypatch, refresh=None)
        fake_table = MagicMock()
        fake_table.return_value.select.return_value = stored
        monkeypatch.setattr(cal, "table", fake_table)
        monkeypatch.setattr(cal, "encrypt", lambda v, **_: f"ENC({v})")
        client = TestClient(_app)
        state = self._initiate(client, "&next=/dashboard")
        r = client.get(f"/api/calendar/callback?code=xyz&state={state}", follow_redirects=False)
        assert r.headers["location"].endswith("/dashboard?calendar_error=no_refresh_token")
        fake_table.return_value.upsert.assert_not_called()

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


class TestStoredRefreshToken:
    def test_a_row_without_a_refresh_token_does_not_crash(self, monkeypatch):
        """A NULL refresh_token decrypts to None (there is nothing to refresh
        with); decrypt(None) raised a TypeError and 500'd every calendar call."""
        built = {}

        def _creds(**kw):
            built.update(kw)
            c = MagicMock()
            c.refresh_token = kw.get("refresh_token")
            return c

        monkeypatch.setattr(calendar_routes, "Credentials", _creds, raising=False)
        monkeypatch.setattr(calendar_routes, "decrypt", lambda v, **_: f"DEC({v})")
        fake_table = MagicMock()
        monkeypatch.setattr(calendar_routes, "table", fake_table)
        calendar_routes._get_refreshed_credentials({
            "user_id": "user_a", "access_token": "enc_acc", "refresh_token": None,
            "expires_at": "2000-01-01T00:00:00+00:00",
        })
        assert built["refresh_token"] is None
        assert built["token"] == "DEC(enc_acc)"
        fake_table.return_value.update.assert_not_called()


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
        monkeypatch.setattr(calendar_routes, "table", fake_table)
        monkeypatch.setattr(calendar_routes, "encrypt", lambda v, **_: f"ENC({v})")
        monkeypatch.setattr(calendar_routes, "decrypt", lambda v, **_: v)

        creds = MagicMock()
        creds.refresh_token = "ref"
        creds.token = "newacc"
        creds.expiry = None
        creds.refresh = MagicMock()
        monkeypatch.setattr(calendar_routes, "Credentials", MagicMock(return_value=creds), raising=False)
        monkeypatch.setattr(calendar_routes, "Request", MagicMock(), raising=False)

        token_row = {
            "user_id": "user_a",
            "access_token": "enc_acc",
            "refresh_token": "enc_ref",
            "expires_at": "2000-01-01T00:00:00+00:00",  # far past → forces refresh
        }
        calendar_routes._get_refreshed_credentials(token_row)

        assert updates, "expected an oauth_tokens update on refresh"
        (args, _kwargs) = updates[-1]
        assert args[0]["expires_at"] is None
