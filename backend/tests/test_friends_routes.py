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

    def test_resend_after_decline_reactivates_the_existing_row(self):
        """UNIQUE(from_user_id, to_user_id) on friend_requests has no status
        carve-out, so a naive second insert() 500s once a declined row
        already occupies the pair. The route must UPDATE that row back to
        pending instead of inserting a duplicate."""
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friendships"].select.return_value = []  # not friends
        handles["friend_requests"].select.return_value = [
            {"id": "r1", "status": "declined"}
        ]
        handles["friend_requests"].update.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2",
             "status": "pending", "responded_at": None}
        ]
        with patch("routes.social.table", side_effect=_tables(handles)):
            r = client.post("/api/social/friends/request",
                            json={"from_user_id": "u1", "to_user_id": "u2"})
        assert r.status_code == 200
        assert r.json()["request"]["status"] == "pending"
        handles["friend_requests"].insert.assert_not_called()
        handles["friend_requests"].update.assert_called_once()
        data, kwargs = handles["friend_requests"].update.call_args[0], handles["friend_requests"].update.call_args[1]
        assert data[0]["status"] == "pending"
        assert data[0]["responded_at"] is None
        assert kwargs["filters"] == {"id": "eq.r1"}

    def test_resend_after_unfriend_reactivates_the_accepted_row(self):
        """remove_friend deliberately leaves the friend_requests row behind
        (it only deletes the symmetric friendships rows), so a later re-send
        finds an 'accepted' row rather than no row at all. Same reactivation
        path must apply, not just for 'declined'."""
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friendships"].select.return_value = []  # unfriended already
        handles["friend_requests"].select.return_value = [
            {"id": "r1", "status": "accepted"}
        ]
        handles["friend_requests"].update.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2",
             "status": "pending", "responded_at": None}
        ]
        with patch("routes.social.table", side_effect=_tables(handles)):
            r = client.post("/api/social/friends/request",
                            json={"from_user_id": "u1", "to_user_id": "u2"})
        assert r.status_code == 200
        assert r.json()["request"]["status"] == "pending"
        handles["friend_requests"].insert.assert_not_called()
        handles["friend_requests"].update.assert_called_once()


class TestAccept:
    def test_writes_both_directions_and_checks_both_users(self):
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friend_requests"].select.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2", "status": "pending"}
        ]
        handles["friendships"].select.return_value = []  # not friends yet
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.check_achievements") as check:
            r = client.post("/api/social/friends/requests/r1/accept?user_id=u2")
        assert r.status_code == 200
        written = handles["friendships"].upsert.call_args[0][0]
        assert {"user_id": "u1", "friend_id": "u2"} in written
        assert {"user_id": "u2", "friend_id": "u1"} in written
        assert check.call_count == 2

    def test_a_second_accept_is_a_no_op_not_a_500(self):
        """Double-click, or a retry: the request is already `accepted`, so the
        friendships rows exist. A second insert of the same pair violates
        PRIMARY KEY (user_id, friend_id) and 500s — and because the route
        never re-checked status, the row stayed where it was, so it 500d on
        every subsequent retry too. Accepting an already-accepted request must
        be an idempotent no-op."""
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friend_requests"].select.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2",
             "status": "accepted"}
        ]
        handles["friendships"].select.return_value = [{"friend_id": "u1"}]
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.check_achievements"):
            r = client.post("/api/social/friends/requests/r1/accept?user_id=u2")
        assert r.status_code == 200
        assert r.json()["accepted"] is True
        handles["friendships"].insert.assert_not_called()
        handles["friendships"].upsert.assert_not_called()

    def test_accepting_the_reverse_of_an_already_accepted_mutual_request(self):
        """send_friend_request only checks the exact (from, to) pair, never the
        reverse, so A->B and B->A can both sit pending. Once B accepts A->B the
        two are friends; A then clicking Accept on the still-pending B->A hits
        the same duplicate PRIMARY KEY. No adversary needed."""
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friend_requests"].select.return_value = [
            {"id": "r2", "from_user_id": "u2", "to_user_id": "u1",
             "status": "pending"}
        ]
        # Already friends from the first accept.
        handles["friendships"].select.return_value = [{"friend_id": "u2"}]
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.check_achievements"):
            r = client.post("/api/social/friends/requests/r2/accept?user_id=u1")
        assert r.status_code == 200
        assert r.json()["accepted"] is True
        handles["friendships"].insert.assert_not_called()
        handles["friendships"].upsert.assert_not_called()
        # The stale pending row is still resolved, so it stops showing up as
        # an actionable incoming request forever.
        handles["friend_requests"].update.assert_called_once()
        assert handles["friend_requests"].update.call_args[0][0]["status"] == "accepted"

    def test_accepting_a_declined_request_is_409_not_a_phantom_accept(self):
        """`already` used to be `status != "pending" or _are_friends(...)`,
        which lumped `declined` in with `accepted`. Accepting a declined
        request then skipped the friendships upsert, still stamped the row
        `accepted`, and returned success — a request recorded as accepted with
        no friendship behind it. Only an existing friendship makes this
        idempotent; anything else resolved must be rejected."""
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friend_requests"].select.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2",
             "status": "declined"}
        ]
        handles["friendships"].select.return_value = []  # not friends
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.check_achievements"):
            r = client.post("/api/social/friends/requests/r1/accept?user_id=u2")
        assert r.status_code == 409
        handles["friendships"].upsert.assert_not_called()
        # Critically, the declined row is NOT rewritten to accepted.
        handles["friend_requests"].update.assert_not_called()

    def test_the_friendship_write_is_conflict_safe(self):
        """Two simultaneous accepts (a genuine double-click fires both before
        either has updated the status) both read `pending`, so the status
        check alone is not enough — the write itself has to tolerate the
        duplicate. It goes through upsert on the (user_id, friend_id) primary
        key rather than a bare insert."""
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friend_requests"].select.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2",
             "status": "pending"}
        ]
        handles["friendships"].select.return_value = []
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.check_achievements"):
            r = client.post("/api/social/friends/requests/r1/accept?user_id=u2")
        assert r.status_code == 200
        handles["friendships"].insert.assert_not_called()
        assert handles["friendships"].upsert.call_args.kwargs["on_conflict"] == \
            "user_id,friend_id"

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
