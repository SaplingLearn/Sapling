"""
Regression tests for #285 — Google sign-in 500s when a *stub* users row exists.

A stub row (`{"id": ..., "streak_count": 0}`, `google_id` NULL) is created by
`services.graph_service.ensure_user_exists`, which `get_graph` calls for any
authenticated request. Because the `sapling_session` cookie is HMAC-signed and
survives a DB row delete, a still-"logged in" tab can create a stub for an
account that no longer exists.

The callback looked users up by `google_id` ONLY, so the stub (google_id NULL)
was invisible to it. Control fell through to a blind INSERT on the deterministic
id `user_{google_id}` — the stub's own id — and collided on `users_pkey`:

    HTTP 409: {"code":"23505","message":"duplicate key value violates unique
               constraint \"users_pkey\""}

`connection.py`'s `raise_for_status()` turned that into an unhandled exception →
`main.py`'s handler → an opaque 500, permanently, for that account.

These tests drive the REAL `/google/callback` route (only the Google network hops
are mocked) and pin all three provisioning outcomes:

  (a) a stub exists      -> promoted in place; sign-in succeeds
  (b) a brand-new user   -> still provisioned
  (c) a full user exists -> still takes the UPDATE path (id preserved)

The fence: the mocked `users`/`user_profiles` tables raise the production 409 on
`.insert(...)`. The fixed code never blind-inserts, so any regression to `insert`
fails these tests with the exact error from the bug report rather than silently.
"""
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.auth as auth_module

# Mount ONLY the auth router — main.py pulls in logfire and the full stack.
_app = FastAPI()
_app.include_router(auth_module.router, prefix="/api/auth")

GOOGLE_ID = "108451234567890123456"
USER_ID = f"user_{GOOGLE_ID}"
EMAIL = "student@bu.edu"


def _pkey_409(*_args, **_kwargs):
    """Raise the exact PostgREST error #285 reported, the way connection.py does."""
    request = httpx.Request("POST", "https://example.supabase.co/rest/v1/users")
    response = httpx.Response(
        409,
        json={
            "code": "23505",
            "details": f"Key (id)=({USER_ID}) already exists.",
            "message": 'duplicate key value violates unique constraint "users_pkey"',
        },
        request=request,
    )
    raise httpx.HTTPStatusError("409 Conflict", request=request, response=response)


def _mock_table_factory(users_rows):
    """Per-table mocks. `users.select` returns `users_rows` (the google_id lookup).

    `.insert` raises the production 409 on the two tables the callback writes, so
    a blind insert can never pass silently.
    """
    mocks: dict = {}

    def factory(name):
        if name not in mocks:
            m = MagicMock(name=f"table:{name}")
            m.select.return_value = []
            m.insert.return_value = []
            m.update.return_value = []
            m.upsert.return_value = []
            mocks[name] = m
        return mocks[name]

    factory("users").select.return_value = users_rows
    factory("users").insert.side_effect = _pkey_409
    factory("user_profiles").insert.side_effect = _pkey_409
    return factory, mocks


@pytest.fixture
def drive_callback(monkeypatch):
    """Drive the real callback past the two Google network hops."""
    monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")
    monkeypatch.setattr(auth_module, "GOOGLE_AVAILABLE", True)

    creds = MagicMock(token="access-tok", refresh_token="refresh-tok", expiry=None)
    flow = MagicMock(credentials=creds)
    fake_flow_cls = MagicMock()
    fake_flow_cls.from_client_config.return_value = flow
    monkeypatch.setattr(auth_module, "Flow", fake_flow_cls, raising=False)

    userinfo = MagicMock()
    userinfo.raise_for_status.return_value = None
    userinfo.json.return_value = {
        "id": GOOGLE_ID,
        "email": EMAIL,
        "name": "Ada Lovelace",
        "picture": "https://example.com/a.png",
    }
    # auth.py does `import httpx` inside the function, so patch the module attr.
    monkeypatch.setattr(httpx, "get", lambda *a, **k: userinfo)

    def _drive(users_rows):
        factory, mocks = _mock_table_factory(users_rows)
        monkeypatch.setattr(auth_module, "table", factory)

        nonce = "nonce-abc"
        cookie = auth_module._encode_oauth_cookie(
            {"n": nonce, "cv": "verifier", "popup_id": None}
        )
        state = auth_module._encode_state({"action": "signin", "n": nonce})
        client = TestClient(_app)
        client.cookies.set(auth_module.OAUTH_STATE_COOKIE, cookie)
        response = client.get(
            f"/api/auth/google/callback?code=auth-code&state={state}",
            follow_redirects=False,
        )
        return response, mocks

    return _drive


class TestStubUserPromotion:
    """(a) A stub row must be adopted, not collided with."""

    def test_stub_signin_succeeds_and_does_not_500(self, drive_callback):
        # The stub is invisible to a google_id lookup -> select returns [].
        response, _ = drive_callback(users_rows=[])
        # Before the fix this raised HTTPStatusError(409) -> 500.
        assert response.status_code in (302, 307), (
            f"expected a redirect, got {response.status_code} — the 409 escaped"
        )

    def test_stub_is_promoted_via_upsert_on_id_not_insert(self, drive_callback):
        _, mocks = drive_callback(users_rows=[])

        mocks["users"].insert.assert_not_called()
        mocks["users"].upsert.assert_called_once()

        payload = mocks["users"].upsert.call_args.args[0]
        kwargs = mocks["users"].upsert.call_args.kwargs
        # on_conflict MUST target the primary key. `google_id` would not resolve
        # #285: the stub's google_id is NULL and NULLs never conflict.
        assert kwargs.get("on_conflict", "id") == "id"
        assert payload["id"] == USER_ID
        assert payload["google_id"] == GOOGLE_ID, "the stub's NULL google_id must be filled in"
        assert payload["auth_provider"] == "google"
        assert "last_sign_in_at" in payload

    def test_profile_row_is_also_upserted(self, drive_callback):
        """A stub that completed onboarding already has a user_profiles row
        (user_id is the PK), so that insert 409s too."""
        _, mocks = drive_callback(users_rows=[])

        mocks["user_profiles"].insert.assert_not_called()
        mocks["user_profiles"].upsert.assert_called_once()
        assert mocks["user_profiles"].upsert.call_args.kwargs.get("on_conflict") == "user_id"
        assert mocks["user_profiles"].upsert.call_args.args[0]["user_id"] == USER_ID

    def test_unapproved_new_user_still_gated_to_pending(self, drive_callback):
        """Promotion must not smuggle anyone past the approval gate."""
        response, _ = drive_callback(users_rows=[])
        assert "/pending" in response.headers["location"]


class TestBrandNewUser:
    """(b) The no-stub path must still provision a user."""

    def test_new_user_row_is_created(self, drive_callback):
        response, mocks = drive_callback(users_rows=[])
        assert response.status_code in (302, 307)
        mocks["users"].upsert.assert_called_once()
        assert mocks["users"].upsert.call_args.args[0]["id"] == USER_ID


class TestExistingUserUnchanged:
    """(c) A fully-provisioned user must still take the UPDATE path."""

    def test_existing_user_updates_and_keeps_its_own_id(self, drive_callback):
        # A legacy row whose id is NOT `user_{google_id}` — the reason the two
        # branches must stay separate rather than collapsing into one upsert
        # keyed on the derived id.
        legacy_id = "legacy-uuid-0001"
        response, mocks = drive_callback(
            users_rows=[{"id": legacy_id, "is_approved": True}]
        )

        assert response.status_code in (302, 307)
        mocks["users"].update.assert_called_once()
        assert mocks["users"].update.call_args.kwargs["filters"] == {"id": f"eq.{legacy_id}"}
        mocks["users"].upsert.assert_not_called()
        mocks["users"].insert.assert_not_called()

    def test_approved_user_is_not_sent_to_pending(self, drive_callback):
        response, _ = drive_callback(
            users_rows=[{"id": USER_ID, "is_approved": True}]
        )
        assert "/pending" not in response.headers["location"]
