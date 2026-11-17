"""Tests for the rooms semantics (#405, "real ownership + public rooms").

Pins: create_room populates the 0032 columns (owner_id = creator, is_public
defaulting false, topic/course from the body); the kick gate keys on
OWNER_ID (ownership is transferable later — created_by stays the immutable
creator record); membership changes touch rooms.updated_at; and the minimal
public surface (GET /public-rooms + invite-less join) never leaks the
invite_code and 403s private rooms. Supabase mocked per
tests/test_social_messages.py's idiom.
"""
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import app
from tests.split_patches import patch_social

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
            rows = (data or {}).get(name, [])
            m.select.return_value = rows
            m.select_with_count.return_value = (rows, len(rows))
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
        with patch_social("table", side_effect=factory):
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
        with patch_social("table", side_effect=factory):
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
        with patch_social("table", side_effect=factory):
            r = client.delete("/api/social/rooms/r1/members/u2?requester_id=u-creator")
        assert r.status_code == 403

    def test_owner_kicks_and_touches_updated_at(self):
        factory, mocks = _tables({"rooms": [_room()]})
        with patch_social("table", side_effect=factory):
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
        with patch_social("table", side_effect=factory):
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
        with patch_social("table", side_effect=factory):
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
        with patch_social("table", side_effect=factory):
            r = client.post("/api/social/public-rooms/r-priv/join", json={"user_id": "u2"})
        assert r.status_code == 403

    def test_join_unknown_room_is_404(self):
        factory, _ = _tables()
        with patch_social("table", side_effect=factory):
            r = client.post("/api/social/public-rooms/r-nope/join", json={"user_id": "u2"})
        assert r.status_code == 404


#: PostgREST's `max_rows` on this deployment (db/connection.py::MAX_ROWS).
_MAX_ROWS = 1000


class _CappedMembers:
    """`room_members` as PostgREST serves it: an `in.(…)` filter, and never
    more than `max_rows` rows in one response, whatever was asked for. That
    cap answers 2xx (206) with the rows cut short, so a read that does not
    page is silently truncated — the fault this fake exists to expose."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def _matching(self, filters):
        ids = set(filters["room_id"].removeprefix("in.(").removesuffix(")").split(","))
        return [r for r in self.rows if r["room_id"] in ids]

    def select(self, columns="*", *, filters=None, limit=None, **_):
        self.calls.append(filters)
        rows = self._matching(filters)
        return rows[: min(limit or _MAX_ROWS, _MAX_ROWS)]

    def select_with_count(self, columns="*", *, filters=None, order=None,
                          limit=None, offset=0, **_):
        self.calls.append(filters)
        rows = sorted(self._matching(filters), key=lambda r: (r["room_id"], r["user_id"]))
        page = rows[offset: offset + min(limit or _MAX_ROWS, _MAX_ROWS)]
        return page, len(rows)


class TestMemberCountsAreBatched:
    """Both listings used to run one `room_members` query PER ROOM, in series.
    The public listing is the worse of the two — it reads every public room in
    the app with no limit, so the query count grew with the product."""

    def _rooms(self, n):
        return [{"id": f"r{i}", "name": f"Room {i}", "topic": None, "course": None,
                 "owner_id": "u1", "created_by": "u1", "created_at": "x",
                 "updated_at": "x", "is_public": True} for i in range(n)]

    def _run_public(self, n):
        from unittest.mock import MagicMock, patch

        from services.social import rooms as mod

        rooms_tbl = MagicMock()
        rooms_tbl.select.return_value = self._rooms(n)
        # Two members in r0, one in r1, none elsewhere.
        members_tbl = _CappedMembers([
            {"room_id": "r0", "user_id": "a"}, {"room_id": "r0", "user_id": "b"},
            {"room_id": "r1", "user_id": "a"},
        ])
        with patch.object(mod, "table",
                          side_effect=lambda name: rooms_tbl if name == "rooms" else members_tbl):
            out = mod.list_public_rooms("u1")
        return out, members_tbl

    def test_one_query_for_the_whole_listing(self):
        out, members_tbl = self._run_public(30)
        assert len(members_tbl.calls) == 1, "should batch, not query per room"
        by_id = {r["id"]: r["member_count"] for r in out["rooms"]}
        assert by_id["r0"] == 2
        assert by_id["r1"] == 1
        assert by_id["r2"] == 0

    def test_chunks_rather_than_one_huge_in_filter(self):
        _, members_tbl = self._run_public(120)
        assert len(members_tbl.calls) == 3  # 120 / _IN_CHUNK(50)
        for filters in members_tbl.calls:
            ids = filters["room_id"]
            assert ids.startswith("in.(")
            assert len(ids.split(",")) <= 50

    def test_no_rooms_means_no_member_query(self):
        _, members_tbl = self._run_public(0)
        assert members_tbl.calls == []

    def test_counts_are_not_cut_short_at_postgrest_max_rows(self):
        """50 rooms share one `in.(…)` read; 50 rooms of 30 members is 1,500
        rows, past PostgREST's 1,000-row cap. Every member must be counted."""
        from unittest.mock import patch

        from services.social import rooms as mod

        members = _CappedMembers([
            {"room_id": f"r{i}", "user_id": f"u{j}"} for i in range(50) for j in range(30)
        ])
        with patch.object(mod, "table", return_value=members):
            counts = mod._member_counts([f"r{i}" for i in range(50)])
        assert sum(counts.values()) == 1500
        assert set(counts.values()) == {30}

    def test_invite_code_is_still_never_in_the_public_payload(self):
        """The batching rewrote this projection; it must stay explicit."""
        out, _ = self._run_public(3)
        for room in out["rooms"]:
            assert "invite_code" not in room


class TestPublicRoomDiscoveryIsBoundedAndOrdered:
    """The discovery read had no limit and no ORDER BY: it pulled every public
    room in the app for every student who opened Social, and returned them in
    whatever order Postgres felt like — so the list reshuffled between loads."""

    def _call(self):
        from unittest.mock import MagicMock, patch

        from services.social import rooms as mod

        rooms_tbl = MagicMock()
        rooms_tbl.select.return_value = []
        members_tbl = MagicMock()
        members_tbl.select.return_value = []
        with patch.object(mod, "table",
                          side_effect=lambda name: rooms_tbl if name == "rooms" else members_tbl):
            mod.list_public_rooms("u1")
        return rooms_tbl.select.call_args

    def test_read_is_bounded(self):
        from services.social.rooms import PUBLIC_ROOMS_MAX

        assert self._call().kwargs["limit"] == PUBLIC_ROOMS_MAX

    def test_read_is_newest_first(self):
        assert self._call().kwargs["order"] == "created_at.desc"
