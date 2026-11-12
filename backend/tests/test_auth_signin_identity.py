"""Sign-in asks Google for identity only (owner decision, 2026-11-12).

* ``AUTH_SCOPES`` is openid/email/profile; calendar access has its own consent
  flow (routes/calendar.py). ``/google`` asks Google to include the scopes the
  student granted before, so a student who connected the calendar keeps
  calendar-capable tokens, and the callback stores tokens ONLY from a grant
  that covers the calendar scopes. An identity-only grant never replaces a
  stored calendar token, and never makes ``/api/calendar/status`` say
  "connected".
* The code exchange is built without scopes, because Google's answer under
  ``include_granted_scopes`` differs from the request and oauthlib raises on
  any difference; the granted set is checked in code.
* An existing account's sign-in keeps the name the student chose in
  onboarding; a profile with no name still starts from Google's. The avatar
  refreshes, except over one the student uploaded.
* Google's "cancel" (``error=access_denied``, no ``code``) is a cancelled
  sign-in on the existing error path, not a 422.
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
from services.encryption import decrypt, encrypt
from tests.split_patches import set_auth_session_secret, set_auth_table

_app = FastAPI()
_app.include_router(auth_module.router, prefix="/api/auth")

FRONTEND = "https://sapling.example"
GOOGLE_ID = "112233"
USER_ID = "user_112233"
IDENTITY = list(config.AUTH_SCOPES)
CALENDAR = list(config.GOOGLE_SCOPES)
UPLOADED = f"https://proj.supabase.co/storage/v1/object/public/{config.STORAGE_BUCKET}/user_112233/a.png"


def test_sign_in_scopes_are_identity_only():
    assert set(config.AUTH_SCOPES) == {
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    }
    assert not set(config.AUTH_SCOPES) & set(config.GOOGLE_SCOPES)


def test_google_login_asks_for_identity_and_previously_granted_scopes(monkeypatch):
    set_auth_session_secret(monkeypatch, "test-secret-key")
    monkeypatch.setattr(auth_module, "GOOGLE_AVAILABLE", True)
    monkeypatch.setattr(auth_module, "GOOGLE_CLIENT_ID", "cid")
    flow = MagicMock(name="flow")
    flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?x=1", "s")
    flow_cls = MagicMock(name="Flow")
    flow_cls.from_client_config.return_value = flow
    monkeypatch.setattr(auth_module, "Flow", flow_cls, raising=False)

    r = TestClient(_app).get("/api/auth/google", follow_redirects=False)

    assert r.status_code in (302, 307)
    assert flow_cls.from_client_config.call_args.kwargs["scopes"] == IDENTITY
    kwargs = flow.authorization_url.call_args.kwargs
    assert kwargs["include_granted_scopes"] == "true"
    # Offline + consent, as before: a calendar student's sign-in yields a new
    # calendar-capable refresh token, which is stored.
    assert kwargs["access_type"] == "offline"
    assert kwargs["prompt"] == "consent"


# ── the callback ────────────────────────────────────────────────────────────


@pytest.fixture
def signin(monkeypatch):
    """Drive the real /google/callback past Google's two network hops."""
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(auth_module, "_LOCAL_AUTO_APPROVE", False)
    monkeypatch.setattr(auth_module, "FRONTEND_URL", FRONTEND)
    set_auth_session_secret(monkeypatch, "test-secret-key")
    monkeypatch.setattr(auth_module, "GOOGLE_AVAILABLE", True)
    monkeypatch.setattr(ach_module, "check_achievements", lambda *a, **k: None)

    state = {"n": 0}

    def _drive(
        *, users_rows=None, profile_rows=None, granted=IDENTITY, refresh="refresh-tok",
        picture="https://lh3.googleusercontent.com/a/new.png", name="Ada Lovelace",
    ):
        creds = MagicMock(token="access-tok", refresh_token=refresh, expiry=None)
        creds.granted_scopes = granted
        flow_cls = MagicMock(name="Flow")
        flow_cls.from_client_config.return_value = MagicMock(credentials=creds)
        monkeypatch.setattr(auth_module, "Flow", flow_cls, raising=False)

        userinfo = MagicMock()
        userinfo.raise_for_status.return_value = None
        userinfo.json.return_value = {
            "id": GOOGLE_ID, "email": "ada@bu.edu", "name": name, "picture": picture,
        }
        monkeypatch.setattr(httpx, "get", lambda *a, **k: userinfo)

        tables: dict = {}

        def factory(name_):
            if name_ not in tables:
                m = MagicMock(name=f"table:{name_}")
                m.select.return_value = []
                m.insert.return_value = []
                m.update.return_value = []
                m.upsert.return_value = []
                tables[name_] = m
            return tables[name_]

        factory("users").select.return_value = (
            [{"id": USER_ID, "is_approved": True, "deleted_at": None}]
            if users_rows is None else users_rows
        )
        factory("user_profiles").select.return_value = profile_rows or []
        set_auth_table(monkeypatch, factory)

        state["n"] += 1
        nonce = f"nonce-{state['n']}"
        cookie = auth_module._encode_oauth_cookie({"n": nonce, "cv": "verifier", "popup_id": None})
        client = TestClient(_app)
        client.cookies.set(auth_module.OAUTH_STATE_COOKIE, cookie)
        st = auth_module._encode_state({"action": "signin", "n": nonce})
        r = client.get(f"/api/auth/google/callback?code=c&state={st}", follow_redirects=False)
        assert r.status_code in (302, 307), r.text
        return r, tables, flow_cls

    return _drive


def _profile_writes(tables):
    t = tables.get("user_profiles")
    if t is None:
        return [], []
    return t.upsert.call_args_list, t.update.call_args_list


class TestTheExchange:
    def test_the_exchange_flow_carries_no_scopes(self, signin):
        """oauthlib raises "Scope has changed" whenever Google's answer differs
        from the session's scopes, which include_granted_scopes guarantees for
        every student who connected the calendar."""
        _, _, flow_cls = signin(granted=IDENTITY + CALENDAR)
        assert flow_cls.from_client_config.call_args.kwargs["scopes"] is None

    def test_a_sign_in_still_gets_in(self, signin):
        r, _, _ = signin()
        assert urlparse(r.headers["location"]).path == "/auth/callback"


class TestCalendarTokensAtSignIn:
    def test_an_identity_only_grant_stores_no_tokens(self, signin):
        """A new student (or one who never connected the calendar): nothing in
        oauth_tokens, so /api/calendar/status stays "not connected"."""
        _, tables, _ = signin(granted=IDENTITY)
        assert "oauth_tokens" not in tables

    def test_a_grant_without_a_scope_list_is_identity_only(self, signin):
        _, tables, _ = signin(granted=None)
        assert "oauth_tokens" not in tables

    def test_a_partial_calendar_grant_stores_no_tokens(self, signin):
        _, tables, _ = signin(granted=IDENTITY + CALENDAR[:1])
        assert "oauth_tokens" not in tables

    def test_a_calendar_student_keeps_fresh_calendar_tokens(self, signin):
        """include_granted_scopes: the grant covers the calendar the student
        connected earlier, so its tokens replace the stored ones."""
        _, tables, _ = signin(granted=" ".join(IDENTITY + CALENDAR))
        t = tables["oauth_tokens"]
        t.upsert.assert_called_once()
        row = t.upsert.call_args.args[0]
        assert t.upsert.call_args.kwargs["on_conflict"] == "user_id"
        assert row["user_id"] == USER_ID
        assert decrypt(row["access_token"]) == "access-tok"
        assert decrypt(row["refresh_token"]) == "refresh-tok"
        assert row["expires_at"] is None
        t.delete.assert_not_called()

    def test_no_refresh_token_keeps_the_stored_one(self, signin):
        _, tables, _ = signin(granted=IDENTITY + CALENDAR, refresh=None)
        row = tables["oauth_tokens"].upsert.call_args.args[0]
        assert "refresh_token" not in row
        assert decrypt(row["access_token"]) == "access-tok"


class TestTheProfileAtSignIn:
    def test_an_onboarded_name_is_kept(self, signin):
        profile = {
            "name": encrypt("Ada L."), "first_name": encrypt("Ada"),
            "last_name": encrypt("L."), "avatar_url": "https://lh3.googleusercontent.com/a/old.png",
        }
        _, tables, _ = signin(profile_rows=[profile], name="Augusta Ada King")
        upserts, updates = _profile_writes(tables)
        assert upserts == []
        assert len(updates) == 1
        patch = updates[0].args[0]
        assert patch == {"avatar_url": "https://lh3.googleusercontent.com/a/new.png"}
        assert updates[0].kwargs["filters"] == {"user_id": f"eq.{USER_ID}"}

    def test_a_first_name_alone_counts_as_a_name(self, signin):
        profile = {"name": encrypt("Ada"), "first_name": encrypt("Ada"),
                   "last_name": encrypt(""), "avatar_url": None}
        _, tables, _ = signin(profile_rows=[profile])
        _, updates = _profile_writes(tables)
        assert all(not ({"name", "first_name", "last_name"} & set(c.args[0])) for c in updates)

    def test_an_uploaded_avatar_is_kept(self, signin):
        profile = {"name": encrypt("Ada"), "first_name": encrypt("Ada"),
                   "last_name": None, "avatar_url": UPLOADED}
        _, tables, _ = signin(profile_rows=[profile])
        upserts, updates = _profile_writes(tables)
        assert upserts == [] and updates == []

    def test_a_blank_google_picture_never_blanks_the_avatar(self, signin):
        profile = {"name": encrypt("Ada"), "first_name": encrypt("Ada"),
                   "last_name": None, "avatar_url": "https://lh3.googleusercontent.com/a/old.png"}
        _, tables, _ = signin(profile_rows=[profile], picture="")
        upserts, updates = _profile_writes(tables)
        assert upserts == [] and updates == []

    def test_a_profile_without_a_name_gets_googles(self, signin):
        """An empty name is still a ciphertext (of ""), so emptiness is read
        decrypted; the write is a compare-and-set on the name just read."""
        stored = encrypt("")
        profile = {"name": stored, "first_name": encrypt(""), "last_name": None,
                   "avatar_url": None}
        _, tables, _ = signin(profile_rows=[profile], name="Ada Lovelace")
        _, updates = _profile_writes(tables)
        [update] = updates
        patch = update.args[0]
        assert decrypt(patch["name"]) == "Ada Lovelace"
        assert decrypt(patch["first_name"]) == "Ada"
        assert decrypt(patch["last_name"]) == "Lovelace"
        assert patch["avatar_url"] == "https://lh3.googleusercontent.com/a/new.png"
        assert update.kwargs["filters"] == {"user_id": f"eq.{USER_ID}", "name": f"eq.{stored}"}

    def test_a_null_name_is_filled_only_while_still_null(self, signin):
        profile = {"name": None, "first_name": None, "last_name": None, "avatar_url": None}
        _, tables, _ = signin(profile_rows=[profile])
        _, updates = _profile_writes(tables)
        assert updates[0].kwargs["filters"] == {"user_id": f"eq.{USER_ID}", "name": "is.null"}

    def test_a_missing_profile_is_created_from_google_without_overwriting(self, signin):
        """DO NOTHING on conflict: a row that appeared since the read (an
        onboarding submit in another tab) is the student's."""
        _, tables, _ = signin(profile_rows=[])
        upserts, _ = _profile_writes(tables)
        [upsert] = upserts
        row = upsert.args[0]
        assert row["user_id"] == USER_ID
        assert decrypt(row["name"]) == "Ada Lovelace"
        assert row["avatar_url"] == "https://lh3.googleusercontent.com/a/new.png"
        assert upsert.kwargs == {"on_conflict": "user_id", "ignore_duplicates": True}


# ── cancel ──────────────────────────────────────────────────────────────────


class TestCancelledSignIn:
    def _client(self, monkeypatch, *, popup_id=None):
        set_auth_session_secret(monkeypatch, "test-secret-key")
        monkeypatch.setattr(auth_module, "GOOGLE_AVAILABLE", True)
        monkeypatch.setattr(auth_module, "FRONTEND_URL", FRONTEND)
        flow_cls = MagicMock(name="Flow")
        monkeypatch.setattr(auth_module, "Flow", flow_cls, raising=False)
        client = TestClient(_app)
        cookie = auth_module._encode_oauth_cookie({"n": "n1", "cv": "v", "popup_id": popup_id})
        client.cookies.set(auth_module.OAUTH_STATE_COOKIE, cookie)
        state = auth_module._encode_state({"action": "signin", "n": "n1"})
        return client, state, flow_cls

    def test_access_denied_same_tab_lands_on_the_sign_in_error(self, monkeypatch):
        client, state, flow_cls = self._client(monkeypatch)
        r = client.get(
            f"/api/auth/google/callback?error=access_denied&state={state}",
            follow_redirects=False,
        )
        assert r.status_code in (302, 307)
        assert r.headers["location"] == f"{FRONTEND}/?error=cancelled"
        flow_cls.from_client_config.assert_not_called()
        # The state cookie is cleared, as on every other callback outcome.
        assert f"{auth_module.OAUTH_STATE_COOKIE}=" in r.headers.get("set-cookie", "")
        assert "Max-Age=0" in r.headers.get("set-cookie", "")

    def test_access_denied_in_the_popup_reaches_the_opener(self, monkeypatch):
        client, state, _ = self._client(monkeypatch, popup_id="popup-1")
        r = client.get(
            f"/api/auth/google/callback?error=access_denied&state={state}",
            follow_redirects=False,
        )
        loc = urlparse(r.headers["location"])
        assert loc.path == "/auth/callback"
        assert parse_qs(loc.query) == {"error": ["cancelled"], "popup_id": ["popup-1"]}

    def test_no_code_at_all_is_cancelled_not_a_422(self, monkeypatch):
        client, state, flow_cls = self._client(monkeypatch)
        r = client.get(f"/api/auth/google/callback?state={state}", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert r.headers["location"].endswith("/?error=cancelled")
        flow_cls.from_client_config.assert_not_called()

    def test_a_bare_callback_is_cancelled_too(self, monkeypatch):
        client, _, _ = self._client(monkeypatch)
        r = client.get("/api/auth/google/callback", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert r.headers["location"].endswith("?error=cancelled")

    def test_any_google_error_is_a_cancel_and_writes_nothing(self, monkeypatch):
        tables: dict = {}

        def factory(name):
            tables.setdefault(name, MagicMock(name=f"table:{name}"))
            return tables[name]

        set_auth_table(monkeypatch, factory)
        client, state, _ = self._client(monkeypatch)
        r = client.get(
            f"/api/auth/google/callback?error=org_internal&code=c&state={state}",
            follow_redirects=False,
        )
        assert r.headers["location"].endswith("/?error=cancelled")
        assert tables == {}
