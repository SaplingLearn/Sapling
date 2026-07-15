"""
Regression tests for GET /api/users (main.list_users) auth.

The roster endpoint returns each user's decrypted legal name, so it must
require an authenticated session. See issue #156: it previously had no
auth dependency and leaked the full roster to anonymous callers.

The autouse `_bypass_session_auth` fixture in conftest.py stubs the auth
guard so authenticated-path tests don't need real tokens; the
unauthenticated test restores the real guard to assert the 401.
"""
from unittest.mock import MagicMock, patch

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
        # users now carries id + current_room_id (0024 dropped name, renamed
        # room_id); the display name resolves off user_profiles via
        # services.profiles.get_display_names, which decrypts. The route imports
        # both names locally from their modules, so patch at the source modules.
        users_rows = [
            {"id": "u1", "current_room_id": "r1"},
            {"id": "u2", "current_room_id": "r2"},
        ]
        names_map = {"u1": "Bob", "u2": "Alice"}

        def by_name(name):
            m = MagicMock()
            m.select.return_value = users_rows if name == "users" else []
            return m

        with patch("db.connection.table", side_effect=by_name), patch(
            "services.profiles.get_display_names", return_value=names_map
        ):
            r = client.get("/api/users")

        assert r.status_code == 200
        result = r.json()["users"]
        names = [u["name"] for u in result]
        # Sorted by decrypted name, lowercased.
        assert names == ["Alice", "Bob"]
        # Legacy room_id response key preserved, sourced from current_room_id.
        by_id = {u["name"]: u for u in result}
        assert by_id["Bob"]["room_id"] == "r1"
        assert by_id["Alice"]["room_id"] == "r2"
