"""Two findings from probing the running app.

1. An over-long id answered 500. Every id a request supplies is interpolated
   into a PostgREST filter (`filters={"id": f"eq.{...}"}`); past a certain
   length the query URL is too long to send, PostgREST rejects it, and the
   unhandled error becomes a 500. A merely WRONG id correctly answers 404,
   so this was reachable by anyone willing to hold down a key.

2. A friend request to an id that names nobody answered 500.
   `friend_requests.to_user_id` is a FOREIGN KEY to users(id), so the insert
   violated the constraint. This one needed no absurd input at all — an
   ordinary 100-character string did it, as would a typo or a classmate who
   has since deleted their account.
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app
from models import ID_MAX
from tests.split_patches import patch_social

client = TestClient(app)


class TestOverLongIdsAreRefusedNot500:
    """422 (the request is malformed) rather than 500 (we fell over)."""

    def test_tutor_session_id(self):
        r = client.post("/api/learn/chat", json={
            "session_id": "x" * (ID_MAX + 1), "user_id": "u1", "message": "hi",
        })
        assert r.status_code == 422

    def test_quiz_concept_node_id(self):
        r = client.post("/api/quiz/generate", json={
            "user_id": "u1", "concept_node_id": "x" * (ID_MAX + 1),
        })
        assert r.status_code == 422

    def test_quiz_submit_id(self):
        r = client.post("/api/quiz/submit", json={
            "quiz_id": "x" * (ID_MAX + 1), "answers": [],
        })
        assert r.status_code == 422

    def test_friend_request_target_id(self):
        r = client.post("/api/social/friends/request", json={
            "from_user_id": "u1", "to_user_id": "x" * (ID_MAX + 1),
        })
        assert r.status_code == 422

    def test_a_normal_length_id_still_gets_through_validation(self):
        """422 here would mean the bound is too tight to use."""
        r = client.post("/api/learn/chat", json={
            "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "user_id": "u1", "message": "hi",
        })
        assert r.status_code != 422


class TestFriendRequestToANonexistentUser:
    def _send(self, live: bool):
        def table_side_effect(name):
            m = MagicMock()
            m.select.return_value = []
            m.insert.return_value = [{"id": "fr1"}]
            return m

        with (
            patch_social("table", side_effect=table_side_effect),
            patch_social("require_self", return_value=None),
            patch("services.social.friends.live_user_ids",
                  return_value={"target"} if live else set()),
            patch("services.social.friends._are_friends", return_value=False),
        ):
            return client.post("/api/social/friends/request",
                               json={"from_user_id": "u1", "to_user_id": "target"})

    def test_unknown_recipient_is_404_not_500(self):
        """Was a foreign-key violation surfacing as 500."""
        assert self._send(live=False).status_code == 404

    def test_a_live_recipient_still_works(self):
        assert self._send(live=True).status_code == 200
