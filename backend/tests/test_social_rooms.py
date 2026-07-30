"""Tests for the rooms semantics (#405, "real ownership + public rooms").

Pins: create_room populates the 0032 columns (owner_id = creator, is_public
defaulting false, topic/course from the body); the kick gate keys on
OWNER_ID (ownership is transferable later — created_by stays the immutable
creator record); membership changes touch rooms.updated_at; and the minimal
public surface (GET /public-rooms + invite-less join) never leaks the
invite_code and 403s private rooms. Supabase mocked per
tests/test_social_messages.py's idiom.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _room(id="r1", owner="u-owner", creator="u-creator", is_public=False, **kw):
    return {
        "id": id, "name": "Room", "topic": None, "course": None,
        "owner_id": owner, "created_by": creator, "invite_code": "ABC123",
        "created_at": "2026-07-01T00:00:00Z", "updated_at": None,
        "is_public": is_public, **kw,
    }


def _tables(data=None):
    cache: dict = {}

    def factory(name):
        if name not in cache:
            m = MagicMock()
            m.select.return_value = (data or {}).get(name, [])
            m.insert.return_value = []
            m.upsert.return_value = []
            m.update.return_value = []
            m.delete.return_value = []
            cache[name] = m
        return cache[name]
    return factory, cache


class TestCreateRoomPopulates:
    def test_defaults(self):
        factory, mocks = _tables()
        with patch("routes.social.table", side_effect=factory):
            r = client.post("/api/social/rooms/create",
                            json={"user_id": "u1", "room_name": "Algebra crew"})
        assert r.status_code == 200
        row = mocks["rooms"].insert.call_args.args[0]
        assert row["owner_id"] == "u1"    # real ownership column, populated
        assert row["created_by"] == "u1"  # immutable creator record
        assert row["is_public"] is False
        assert row["topic"] is None
        assert row["course"] is None

    def test_optional_fields(self):
        factory, mocks = _tables()
        with patch("routes.social.table", side_effect=factory):
            r = client.post("/api/social/rooms/create", json={
                "user_id": "u1", "room_name": "Algebra crew",
                "topic": "Midterm prep", "course": "MATH210", "is_public": True,
            })
        assert r.status_code == 200
        row = mocks["rooms"].insert.call_args.args[0]
        assert row["topic"] == "Midterm prep"
        assert row["course"] == "MATH210"
        assert row["is_public"] is True


class TestKickAuthKeysOnOwner:
    def test_creator_who_is_not_owner_cannot_kick(self):
        factory, _ = _tables({"rooms": [_room()]})
        with patch("routes.social.table", side_effect=factory):
            r = client.delete("/api/social/rooms/r1/members/u2?requester_id=u-creator")
        assert r.status_code == 403

    def test_owner_kicks_and_touches_updated_at(self):
        factory, mocks = _tables({"rooms": [_room()]})
        with patch("routes.social.table", side_effect=factory):
            r = client.delete("/api/social/rooms/r1/members/u2?requester_id=u-owner")
        assert r.status_code == 200
        mocks["room_members"].delete.assert_called_once()
        assert "updated_at" in mocks["rooms"].update.call_args.args[0]


class TestPublicRooms:
    def test_list_filters_public_and_never_leaks_the_invite_code(self):
        factory, mocks = _tables({
            "rooms": [_room(id="r-pub", is_public=True)],
            "room_members": [{"room_id": "r-pub", "user_id": "u9"}],
        })
        with patch("routes.social.table", side_effect=factory):
            r = client.get("/api/social/public-rooms?user_id=u9")
        assert r.status_code == 200
        rooms = r.json()["rooms"]
        assert rooms[0]["id"] == "r-pub"
        assert rooms[0]["member_count"] == 1
        assert "invite_code" not in rooms[0]
        filters = mocks["rooms"].select.call_args.kwargs.get("filters") or {}
        assert filters.get("is_public") == "eq.true"

    def test_join_public_room_inserts_membership(self):
        factory, mocks = _tables({"rooms": [_room(id="r-pub", is_public=True)]})
        with patch("routes.social.table", side_effect=factory):
            r = client.post("/api/social/public-rooms/r-pub/join", json={"user_id": "u2"})
        assert r.status_code == 200
        # UPSERT, not insert: a double-click racing itself must no-op on the
        # room_members PK rather than 500 (PR #485 review).
        member = mocks["room_members"].upsert.call_args.args[0]
        assert member == {"room_id": "r-pub", "user_id": "u2"}
        assert mocks["room_members"].upsert.call_args.kwargs["on_conflict"] == "room_id,user_id"
        assert "updated_at" in mocks["rooms"].update.call_args.args[0]

    def test_join_private_room_is_403(self):
        factory, _ = _tables({"rooms": [_room(id="r-priv", is_public=False)]})
        with patch("routes.social.table", side_effect=factory):
            r = client.post("/api/social/public-rooms/r-priv/join", json={"user_id": "u2"})
        assert r.status_code == 403

    def test_join_unknown_room_is_404(self):
        factory, _ = _tables()
        with patch("routes.social.table", side_effect=factory):
            r = client.post("/api/social/public-rooms/r-nope/join", json={"user_id": "u2"})
        assert r.status_code == 404
