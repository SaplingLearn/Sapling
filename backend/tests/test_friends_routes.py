"""Friends endpoints — request, accept, decline, remove, list.

The TestAuthGuard class below covers the identity guard added after an
authorization-hole review: every endpoint that takes a user_id (body, query,
or path) must call `require_self` before touching the DB, matching the rest
of routes/social.py. conftest's autouse `_bypass_session_auth` fixture
stubs `routes.social.require_self` to a no-op for the rest of this file's
tests (so they can call routes with an arbitrary user_id and no session
token); the guard tests here re-patch `routes.social.require_self` on top
of that stub to assert it is actually invoked with the right user_id, and
that a rejection from it actually propagates rather than being swallowed.
"""
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _tables(handles):
    return lambda name: handles[name]


class TestSendRequest:
    def test_creates_a_pending_request(self):
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friendships"].select.return_value = []
        handles["friend_requests"].select.return_value = []
        handles["friend_requests"].insert.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2", "status": "pending"}
        ]
        with patch("routes.social.table", side_effect=_tables(handles)):
            r = client.post("/api/social/friends/request",
                            json={"from_user_id": "u1", "to_user_id": "u2"})
        assert r.status_code == 200
        assert r.json()["request"]["status"] == "pending"

    def test_rejects_self_friending(self):
        with patch("routes.social.table"):
            r = client.post("/api/social/friends/request",
                            json={"from_user_id": "u1", "to_user_id": "u1"})
        assert r.status_code == 400

    def test_rejects_when_already_friends(self):
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friendships"].select.return_value = [{"friend_id": "u2"}]
        with patch("routes.social.table", side_effect=_tables(handles)):
            r = client.post("/api/social/friends/request",
                            json={"from_user_id": "u1", "to_user_id": "u2"})
        assert r.status_code == 409


class TestAccept:
    def test_writes_both_directions_and_checks_both_users(self):
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friend_requests"].select.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2", "status": "pending"}
        ]
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.check_achievements") as check:
            r = client.post("/api/social/friends/requests/r1/accept?user_id=u2")
        assert r.status_code == 200
        inserted = handles["friendships"].insert.call_args[0][0]
        assert {"user_id": "u1", "friend_id": "u2"} in inserted
        assert {"user_id": "u2", "friend_id": "u1"} in inserted
        assert check.call_count == 2

    def test_only_the_recipient_may_accept(self):
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friend_requests"].select.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2", "status": "pending"}
        ]
        with patch("routes.social.table", side_effect=_tables(handles)):
            r = client.post("/api/social/friends/requests/r1/accept?user_id=u9")
        assert r.status_code == 403

    def test_missing_request_is_404(self):
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friend_requests"].select.return_value = []
        with patch("routes.social.table", side_effect=_tables(handles)):
            r = client.post("/api/social/friends/requests/nope/accept?user_id=u2")
        assert r.status_code == 404


class TestRemove:
    def test_deletes_both_directions(self):
        handles = {"friendships": MagicMock()}
        with patch("routes.social.table", side_effect=_tables(handles)):
            r = client.delete("/api/social/friends/u2?user_id=u1")
        assert r.status_code == 200
        assert handles["friendships"].delete.call_count == 2


class TestList:
    def test_returns_friends_with_level_and_xp(self):
        handles = {"friendships": MagicMock(), "users": MagicMock()}
        handles["friendships"].select.return_value = [{"friend_id": "u2"}]
        handles["users"].select.return_value = [{"id": "u2", "level": 7, "total_xp": 900}]
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.get_display_names", return_value={"u2": "Priya Nair"}):
            r = client.get("/api/social/friends/u1")
        assert r.json()["friends"] == [
            {"user_id": "u2", "name": "Priya Nair", "level": 7, "total_xp": 900}
        ]


class TestAuthGuard:
    """Each friends endpoint must call require_self(user_id, request) before
    touching the DB — matching the rest of routes/social.py. These patch
    routes.social.require_self directly (on top of conftest's autouse no-op
    stub) to assert the call actually happens with the right user_id, and
    that a rejection from it isn't swallowed."""

    def test_send_request_checks_from_user_id(self):
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friendships"].select.return_value = []
        handles["friend_requests"].select.return_value = []
        handles["friend_requests"].insert.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2", "status": "pending"}
        ]
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.require_self") as guard:
            r = client.post("/api/social/friends/request",
                            json={"from_user_id": "u1", "to_user_id": "u2"})
        assert r.status_code == 200
        assert guard.call_args[0][0] == "u1"

    def test_accept_checks_user_id(self):
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friend_requests"].select.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2", "status": "pending"}
        ]
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.check_achievements"), \
             patch("routes.social.require_self") as guard:
            r = client.post("/api/social/friends/requests/r1/accept?user_id=u2")
        assert r.status_code == 200
        assert guard.call_args[0][0] == "u2"

    def test_decline_checks_user_id(self):
        handles = {"friend_requests": MagicMock()}
        handles["friend_requests"].select.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2", "status": "pending"}
        ]
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.require_self") as guard:
            r = client.post("/api/social/friends/requests/r1/decline?user_id=u2")
        assert r.status_code == 200
        assert guard.call_args[0][0] == "u2"

    def test_remove_checks_user_id(self):
        handles = {"friendships": MagicMock()}
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.require_self") as guard:
            r = client.delete("/api/social/friends/u2?user_id=u1")
        assert r.status_code == 200
        assert guard.call_args[0][0] == "u1"

    def test_list_friends_checks_user_id(self):
        handles = {"friendships": MagicMock()}
        handles["friendships"].select.return_value = []
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.require_self") as guard:
            r = client.get("/api/social/friends/u1")
        assert r.status_code == 200
        assert guard.call_args[0][0] == "u1"

    def test_list_friend_requests_checks_user_id(self):
        handles = {"friend_requests": MagicMock()}
        handles["friend_requests"].select.return_value = []
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.require_self") as guard:
            r = client.get("/api/social/friends/requests?user_id=u1")
        assert r.status_code == 200
        assert guard.call_args[0][0] == "u1"

    def test_guard_rejection_propagates_not_swallowed(self):
        """Proves the guard isn't decorative: when require_self raises, the
        route must surface it rather than continuing on to the DB calls."""
        with patch("routes.social.require_self",
                   side_effect=HTTPException(status_code=403, detail="Forbidden: not your account")):
            r = client.get("/api/social/friends/u1")
        assert r.status_code == 403
