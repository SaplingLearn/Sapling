"""
Regression tests for GET /api/users (main.list_users) auth.

The roster endpoint returns each user's decrypted legal name, so it must
require an authenticated session. See issue #156: it previously had no
auth dependency and leaked the full roster to anonymous callers.

The autouse `_bypass_session_auth` fixture in conftest.py stubs the auth
guard so authenticated-path tests don't need real tokens; the
unauthenticated test restores the real guard to assert the 401.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


class TestListUsersAuth:
    def test_unauthenticated_returns_401(self):
        # Restore the real guard (and its session decoder) so a request with no
        # cookie/token => 401, undoing the autouse bypass from conftest.
        from services import auth_guard

        with patch.object(
            auth_guard, "get_session_user_id", auth_guard._real_get_session_user_id
        ), patch.object(
            auth_guard, "_decode_session", auth_guard._real_decode_session
        ):
            # No cookie, no auth_token: _decode_session raises 401 before any
            # DB access, so we never touch the (unmocked) users table.
            r = client.get("/api/users")

        assert r.status_code == 401

    def test_authenticated_returns_200_with_decrypted_names(self):
        rows = [
            {"id": "u1", "name": "ENC_BOB", "room_id": "r1"},
            {"id": "u2", "name": "ENC_ALICE", "room_id": "r2"},
        ]
        decrypt_map = {"ENC_BOB": "Bob", "ENC_ALICE": "Alice"}

        with patch("db.connection.table") as t, patch(
            "services.encryption.decrypt_if_present",
            side_effect=lambda v: decrypt_map.get(v, v),
        ):
            t.return_value.select.return_value = rows
            r = client.get("/api/users")

        assert r.status_code == 200
        names = [u["name"] for u in r.json()["users"]]
        # Sorted by decrypted name, lowercased.
        assert names == ["Alice", "Bob"]
