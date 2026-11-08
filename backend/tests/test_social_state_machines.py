"""#764 — the social state machines (rooms, bans, friend requests, messages).

Every transition here is either conditional (a PostgREST filter that only
matches the expected FROM state) or ordered so the winner of a race does the
side effect. A MagicMock that returns the same rows for every call cannot tell
a conditional write from a blind one, so these run against a tiny in-memory
PostgREST: `eq.` / `neq.` / `in.()` / `not.in.()` / `is.null` / `not.is.null`
filters, `order=`, and writes that return only the rows they matched — which is
exactly what makes a lost race visible to the route.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _match(row: dict, filters: dict | None) -> bool:
    for col, expr in (filters or {}).items():
        val = row.get(col)
        if expr == "is.null":
            ok = val is None
        elif expr == "not.is.null":
            ok = val is not None
        elif expr.startswith("not.in.("):
            ok = str(val) not in expr[len("not.in.("):-1].split(",")
        elif expr.startswith("in.("):
            ok = str(val) in expr[len("in.("):-1].split(",")
        elif expr.startswith("neq."):
            ok = _norm(val) != expr[4:]
        elif expr.startswith("eq."):
            ok = _norm(val) == expr[3:]
        else:  # pragma: no cover - a filter this fake does not model
            raise AssertionError(f"unmodelled filter {col}={expr}")
        if not ok:
            return False
    return True


def _norm(val) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)


class FakeTable:
    def __init__(self, db: "FakeDB", name: str):
        self.db, self.name = db, name

    @property
    def rows(self) -> list[dict]:
        return self.db.data.setdefault(self.name, [])

    def select(self, columns="*", filters=None, order=None, limit=None, **_):
        out = [dict(r) for r in self.rows if _match(r, filters)]
        if order:
            for part in reversed(order.split(",")):
                col, _, direction = part.partition(".")
                out.sort(key=lambda r: (r.get(col) is None, r.get(col) or ""),
                         reverse=direction.startswith("desc"))
        return out[:limit] if limit else out

    def insert(self, data):
        rows = data if isinstance(data, list) else [data]
        self.rows.extend(dict(r) for r in rows)
        return [dict(r) for r in rows]

    def update(self, data, filters, **_):
        hit = [r for r in self.rows if _match(r, filters)]
        for r in hit:
            r.update(data)
        return [dict(r) for r in hit]

    def upsert(self, data, on_conflict="id", *, ignore_duplicates=False, **_):
        keys = on_conflict.split(",")
        out = []
        for row in (data if isinstance(data, list) else [data]):
            existing = next((r for r in self.rows if all(r.get(k) == row.get(k) for k in keys)), None)
            if existing is None:
                self.rows.append(dict(row))
                out.append(dict(row))
            elif not ignore_duplicates:
                existing.update(row)
                out.append(dict(existing))
        return out

    def delete(self, filters):
        hit = [r for r in self.rows if _match(r, filters)]
        self.db.data[self.name] = [r for r in self.rows if r not in hit]
        return hit


class FakeDB:
    def __init__(self, **tables):
        self.data = {k: [dict(r) for r in v] for k, v in tables.items()}

    def table(self, name):
        return FakeTable(self, name)

    def rows(self, name):
        return self.data.get(name, [])


@pytest.fixture
def db():
    fake = FakeDB()
    with patch("routes.social.table", side_effect=fake.table), \
         patch("routes.social.invalidate_summary"), \
         patch("services.achievement_service.check_achievements"), \
         patch("routes.social.check_achievements"):
        yield fake


def _room(id="r1", owner="u1", code="ABC123", is_public=False):
    return {"id": id, "name": "Room", "invite_code": code, "owner_id": owner,
            "created_by": owner, "is_public": is_public, "topic": None, "course": None,
            "created_at": "2026-07-01T00:00:00Z", "updated_at": None}


def _member(uid, joined, room="r1"):
    return {"room_id": room, "user_id": uid, "joined_at": joined}


# ── Rooms: ownership transfer, deletion, bans ──────────────────────────────


class TestLeave:
    def test_owner_leaving_transfers_to_the_earliest_remaining_member(self, db):
        db.data.update(
            rooms=[_room(owner="u1")],
            room_members=[_member("u1", "2026-01-01"), _member("u3", "2026-03-01"),
                          _member("u2", "2026-02-01")],
        )
        r = client.post("/api/social/rooms/r1/leave", json={"user_id": "u1"})
        assert r.status_code == 200
        assert r.json() == {"left": True, "room_deleted": False, "owner_id": "u2"}
        assert db.rows("rooms")[0]["owner_id"] == "u2"
        assert {m["user_id"] for m in db.rows("room_members")} == {"u2", "u3"}

    def test_new_owner_can_kick_and_the_old_owner_cannot(self, db):
        db.data.update(
            rooms=[_room(owner="u1")],
            room_members=[_member("u1", "2026-01-01"), _member("u2", "2026-02-01"),
                          _member("u3", "2026-03-01")],
        )
        client.post("/api/social/rooms/r1/leave", json={"user_id": "u1"})
        assert client.delete("/api/social/rooms/r1/members/u3?requester_id=u1").status_code == 403
        assert client.delete("/api/social/rooms/r1/members/u3?requester_id=u2").status_code == 200

    def test_non_owner_leaving_keeps_the_owner(self, db):
        db.data.update(
            rooms=[_room(owner="u1")],
            room_members=[_member("u1", "2026-01-01"), _member("u2", "2026-02-01")],
        )
        r = client.post("/api/social/rooms/r1/leave", json={"user_id": "u2"})
        assert r.json()["owner_id"] == "u1"
        assert db.rows("rooms")[0]["owner_id"] == "u1"

    def test_last_member_leaving_deletes_the_room_and_kills_the_code(self, db):
        db.data.update(rooms=[_room(owner="u1")], room_members=[_member("u1", "2026-01-01")])
        r = client.post("/api/social/rooms/r1/leave", json={"user_id": "u1"})
        assert r.json() == {"left": True, "room_deleted": True, "owner_id": None}
        assert db.rows("rooms") == []
        # The invite code is dead with it.
        r = client.post("/api/social/rooms/join", json={"user_id": "u9", "invite_code": "ABC123"})
        assert r.status_code == 404

    def test_a_room_orphaned_before_the_fix_heals_on_the_next_leave(self, db):
        # owner u1 left under the old code; u2 leaving now must still leave
        # the room owned by a member.
        db.data.update(
            rooms=[_room(owner="u1")],
            room_members=[_member("u2", "2026-02-01"), _member("u3", "2026-03-01")],
        )
        client.post("/api/social/rooms/r1/leave", json={"user_id": "u2"})
        assert db.rows("rooms")[0]["owner_id"] == "u3"

    def test_transfer_is_conditional_on_the_stale_owner(self, db):
        """Two leaves racing: if ownership already moved, the late writer's
        conditional update matches nothing and must not clobber it."""
        db.data.update(
            rooms=[_room(owner="u1")],
            room_members=[_member("u1", "2026-01-01"), _member("u2", "2026-02-01"),
                          _member("u3", "2026-03-01")],
        )
        real_select = FakeTable.select

        def select_then_race(self, columns="*", filters=None, **kw):
            out = real_select(self, columns, filters, **kw)
            if self.name == "rooms" and columns == "owner_id":
                # A racing writer moves ownership after our read.
                self.db.data["rooms"][0]["owner_id"] = "u3"
            return out
        with patch.object(FakeTable, "select", select_then_race):
            r = client.post("/api/social/rooms/r1/leave", json={"user_id": "u1"})
        assert r.status_code == 200
        assert db.rows("rooms")[0]["owner_id"] == "u3"


class TestKickIsABan:
    def test_kicked_member_cannot_rejoin_by_code(self, db):
        db.data.update(
            rooms=[_room(owner="u1")],
            room_members=[_member("u1", "2026-01-01"), _member("u2", "2026-02-01")],
        )
        assert client.delete("/api/social/rooms/r1/members/u2?requester_id=u1").status_code == 200
        assert db.rows("room_bans")[0]["user_id"] == "u2"
        r = client.post("/api/social/rooms/join", json={"user_id": "u2", "invite_code": "ABC123"})
        assert r.status_code == 403
        assert {m["user_id"] for m in db.rows("room_members")} == {"u1"}

    def test_kicked_member_cannot_rejoin_a_public_room(self, db):
        db.data.update(
            rooms=[_room(owner="u1", is_public=True)],
            room_members=[_member("u1", "2026-01-01"), _member("u2", "2026-02-01")],
        )
        client.delete("/api/social/rooms/r1/members/u2?requester_id=u1")
        r = client.post("/api/social/public-rooms/r1/join", json={"user_id": "u2"})
        assert r.status_code == 403
        assert {m["user_id"] for m in db.rows("room_members")} == {"u1"}

    def test_others_still_join(self, db):
        db.data.update(rooms=[_room(owner="u1")], room_members=[_member("u1", "2026-01-01")],
                       room_bans=[{"room_id": "r1", "user_id": "u2"}])
        r = client.post("/api/social/rooms/join", json={"user_id": "u3", "invite_code": "ABC123"})
        assert r.status_code == 200

    def test_owner_cannot_kick_themselves(self, db):
        db.data.update(rooms=[_room(owner="u1")], room_members=[_member("u1", "2026-01-01")])
        r = client.delete("/api/social/rooms/r1/members/u1?requester_id=u1")
        assert r.status_code == 400
        assert db.rows("room_members") and not db.rows("room_bans")


class TestMatchRequiresMembership:
    def test_non_member_is_403_and_reads_no_graph(self, db):
        db.data.update(rooms=[_room()], room_members=[_member("u1", "2026-01-01")])
        with patch("routes.social.get_graph") as graph, \
             patch("routes.social.find_study_matches") as match:
            r = client.post("/api/social/rooms/r1/match", json={"user_id": "u9"})
        assert r.status_code == 403
        graph.assert_not_called()
        match.assert_not_called()

    def test_member_matches(self, db):
        db.data.update(rooms=[_room()], room_members=[_member("u1", "2026-01-01"),
                                                     _member("u2", "2026-01-02")])
        with patch("routes.social.get_graph", return_value={"nodes": [], "edges": []}), \
             patch("routes.social.get_display_names", return_value={}), \
             patch("routes.social.find_study_matches", return_value=[]):
            r = client.post("/api/social/rooms/r1/match", json={"user_id": "u1"})
        assert r.status_code == 200


class TestSchoolMatchExcludesNonStudents:
    def test_stubs_pending_and_deleted_users_are_not_candidates(self, db):
        real = {"id": "u-real", "email": "ct", "is_approved": True, "deleted_at": None}
        db.data.update(users=[
            {"id": "u1", "email": "ct", "is_approved": True, "deleted_at": None},
            real,
            {"id": "u-stub", "email": None, "is_approved": False, "deleted_at": None},
            {"id": "u-pending", "email": "ct", "is_approved": False, "deleted_at": None},
            {"id": "u-deleted", "email": "ct", "is_approved": True, "deleted_at": "2026-01-01"},
        ])
        peers = {"u1", "u-real", "u-stub", "u-pending", "u-deleted"}
        with patch("routes.social.academics.school_peer_user_ids", return_value=peers), \
             patch("routes.social.get_graph", return_value={"nodes": [], "edges": []}), \
             patch("routes.social.get_display_names", return_value={}), \
             patch("routes.social.get_display_name", return_value="Me"), \
             patch("routes.social.find_study_matches", return_value=[]) as match:
            r = client.post("/api/social/school-match", json={"user_id": "u1"})
        assert r.status_code == 200
        candidates = [m["user_id"] for m in match.call_args.args[1]]
        assert candidates == ["u1", "u-real"]


class TestDirectoryExcludesNonStudents:
    def test_stubs_pending_and_deleted_users_are_not_listed(self, db):
        db.data.update(users=[
            {"id": "u-real", "email": "ct", "is_approved": True, "deleted_at": None},
            {"id": "u-stub", "email": None, "is_approved": False, "deleted_at": None},
            {"id": "u-pending", "email": "ct", "is_approved": False, "deleted_at": None},
            {"id": "u-deleted", "email": "ct", "is_approved": True, "deleted_at": "2026-01-01"},
        ])
        peers = {"u-real", "u-stub", "u-pending", "u-deleted"}
        with patch("routes.social.academics.school_peer_user_ids", return_value=peers), \
             patch("routes.social.get_display_names", return_value={}):
            r = client.get("/api/social/students")
        assert r.status_code == 200
        assert [s["user_id"] for s in r.json()["students"]] == ["u-real"]


# ── Friend requests ────────────────────────────────────────────────────────


def _req(status="pending", id="fr1", frm="u1", to="u2", responded_at=None):
    return {"id": id, "from_user_id": frm, "to_user_id": to, "status": status,
            "created_at": "2026-01-01T00:00:00+00:00", "responded_at": responded_at}


class TestFriendRequestTransitions:
    def test_decline_cannot_flip_an_accepted_request(self, db):
        db.data.update(friend_requests=[_req("accepted")],
                       friendships=[{"user_id": "u1", "friend_id": "u2"},
                                    {"user_id": "u2", "friend_id": "u1"}])
        r = client.post("/api/social/friends/requests/fr1/decline?user_id=u2")
        assert r.status_code == 409
        assert db.rows("friend_requests")[0]["status"] == "accepted"

    def test_decline_of_pending(self, db):
        db.data.update(friend_requests=[_req()])
        r = client.post("/api/social/friends/requests/fr1/decline?user_id=u2")
        assert r.status_code == 200
        assert db.rows("friend_requests")[0]["status"] == "declined"

    def test_double_decline_is_idempotent(self, db):
        db.data.update(friend_requests=[_req("declined")])
        r = client.post("/api/social/friends/requests/fr1/decline?user_id=u2")
        assert r.status_code == 200

    def test_accept_losing_to_a_concurrent_decline_is_409_and_writes_no_friendship(self, db):
        """The route read `pending`, then the decline landed before its write:
        the conditional claim matches nothing, so no friendship is created."""
        db.data.update(friend_requests=[_req("pending")])
        real_select = FakeTable.select

        def select_then_decline(self, columns="*", filters=None, **kw):
            out = real_select(self, columns, filters, **kw)
            if self.name == "friend_requests" and columns.startswith("id,from_user_id"):
                self.db.data["friend_requests"][0]["status"] = "declined"
            return out
        with patch.object(FakeTable, "select", select_then_decline):
            r = client.post("/api/social/friends/requests/fr1/accept?user_id=u2")
        assert r.status_code == 409
        assert db.rows("friendships") == []
        assert db.rows("friend_requests")[0]["status"] == "declined"

    def test_accept_losing_to_its_double_click_twin_is_idempotent(self, db):
        db.data.update(friend_requests=[_req("pending")])
        real_select = FakeTable.select

        def select_then_accept(self, columns="*", filters=None, **kw):
            out = real_select(self, columns, filters, **kw)
            if self.name == "friend_requests" and columns.startswith("id,from_user_id"):
                self.db.data["friend_requests"][0]["status"] = "accepted"
            return out
        with patch.object(FakeTable, "select", select_then_accept):
            r = client.post("/api/social/friends/requests/fr1/accept?user_id=u2")
        assert r.status_code == 200
        assert r.json() == {"accepted": True}

    def test_accept_writes_the_friendship_and_resolves_the_row(self, db):
        db.data.update(friend_requests=[_req()])
        r = client.post("/api/social/friends/requests/fr1/accept?user_id=u2")
        assert r.status_code == 200
        assert db.rows("friend_requests")[0]["status"] == "accepted"
        assert len(db.rows("friendships")) == 2

    def test_a_failed_friendship_write_hands_the_claim_back(self, db):
        db.data.update(friend_requests=[_req()])
        real_table = db.table

        def failing(name):
            t = real_table(name)
            if name == "friendships":
                def boom(*a, **k):
                    raise RuntimeError("db down")
                t.upsert = boom
            return t
        with patch("routes.social.table", side_effect=failing), \
             TestClient(app, raise_server_exceptions=False) as c:
            r = c.post("/api/social/friends/requests/fr1/accept?user_id=u2")
        assert r.status_code == 500
        assert db.rows("friend_requests")[0]["status"] == "pending"

    def test_already_friends_does_not_flip_a_declined_row(self, db):
        db.data.update(friend_requests=[_req("declined")],
                       friendships=[{"user_id": "u1", "friend_id": "u2"},
                                    {"user_id": "u2", "friend_id": "u1"}])
        r = client.post("/api/social/friends/requests/fr1/accept?user_id=u2")
        assert r.status_code == 200
        assert db.rows("friend_requests")[0]["status"] == "declined"


class TestCancel:
    def test_sender_cancels_a_pending_request(self, db):
        db.data.update(friend_requests=[_req()])
        r = client.delete("/api/social/friends/requests/fr1?user_id=u1")
        assert r.status_code == 200
        assert r.json() == {"cancelled": True}
        assert db.rows("friend_requests") == []

    def test_recipient_cannot_cancel(self, db):
        db.data.update(friend_requests=[_req()])
        r = client.delete("/api/social/friends/requests/fr1?user_id=u2")
        assert r.status_code == 403
        assert db.rows("friend_requests")

    def test_cannot_cancel_a_resolved_request(self, db):
        db.data.update(friend_requests=[_req("declined")])
        r = client.delete("/api/social/friends/requests/fr1?user_id=u1")
        assert r.status_code == 409
        assert db.rows("friend_requests")[0]["status"] == "declined"

    def test_missing_is_404(self, db):
        r = client.delete("/api/social/friends/requests/nope?user_id=u1")
        assert r.status_code == 404

    def test_after_cancel_the_recipient_can_no_longer_accept(self, db):
        db.data.update(friend_requests=[_req()])
        client.delete("/api/social/friends/requests/fr1?user_id=u1")
        r = client.post("/api/social/friends/requests/fr1/accept?user_id=u2")
        assert r.status_code == 404
        assert db.rows("friendships") == []


class TestDeclineCooldown:
    def _send(self):
        return client.post("/api/social/friends/request",
                           json={"from_user_id": "u1", "to_user_id": "u2"})

    def test_recent_decline_blocks_a_resend(self, db):
        recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db.data.update(friend_requests=[_req("declined", responded_at=recent)])
        r = self._send()
        assert r.status_code == 429
        assert db.rows("friend_requests")[0]["status"] == "declined"

    def test_resend_after_the_cooldown_repends(self, db):
        old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        db.data.update(friend_requests=[_req("declined", responded_at=old)])
        r = self._send()
        assert r.status_code == 200
        assert db.rows("friend_requests")[0]["status"] == "pending"

    def test_unfriended_accepted_row_repends_immediately(self, db):
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db.data.update(friend_requests=[_req("accepted", responded_at=recent)])
        assert self._send().status_code == 200

    def test_repend_is_conditional_on_the_status_read(self, db):
        old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        db.data.update(friend_requests=[_req("declined", responded_at=old)])
        real_select = FakeTable.select

        def select_then_change(self, columns="*", filters=None, **kw):
            out = real_select(self, columns, filters, **kw)
            if self.name == "friend_requests" and columns.startswith("id,status"):
                self.db.data["friend_requests"][0]["status"] = "pending"
            return out
        with patch.object(FakeTable, "select", select_then_change):
            r = self._send()
        assert r.status_code == 409


# ── Messages ───────────────────────────────────────────────────────────────


def _msg(**kw):
    row = {"id": "m1", "room_id": "r1", "user_id": "u1", "user_name": "A",
           "text": "ciphertext", "image_url": "https://x/img.png", "is_deleted": False,
           "edited_at": None}
    row.update(kw)
    return row


class TestMessageDeleteAndEdit:
    def test_delete_clears_the_ciphertext(self, db):
        db.data.update(room_messages=[_msg()])
        r = client.delete("/api/social/rooms/r1/messages/m1?user_id=u1")
        assert r.status_code == 200
        row = db.rows("room_messages")[0]
        assert row["is_deleted"] is True
        assert row["text"] is None
        assert row["image_url"] is None

    def test_edit_of_a_deleted_message_is_refused(self, db):
        db.data.update(room_messages=[_msg(is_deleted=True, text=None)])
        r = client.patch("/api/social/rooms/r1/messages/m1",
                         json={"user_id": "u1", "text": "new"})
        assert r.status_code == 400
        assert db.rows("room_messages")[0]["text"] is None

    def test_edit_racing_a_delete_writes_nothing(self, db):
        """The route read is_deleted=false, then the delete landed: the
        conditional write must match nothing rather than resurrect text."""
        db.data.update(room_messages=[_msg()])
        real_select = FakeTable.select

        def select_then_delete(self, columns="*", filters=None, **kw):
            out = real_select(self, columns, filters, **kw)
            if self.name == "room_messages" and columns == "user_id,is_deleted":
                self.db.data["room_messages"][0].update(is_deleted=True, text=None)
            return out
        with patch.object(FakeTable, "select", select_then_delete):
            r = client.patch("/api/social/rooms/r1/messages/m1",
                             json={"user_id": "u1", "text": "resurrected"})
        assert r.status_code == 409
        assert db.rows("room_messages")[0]["text"] is None

    def test_edit_of_a_live_message(self, db):
        db.data.update(room_messages=[_msg()])
        r = client.patch("/api/social/rooms/r1/messages/m1",
                         json={"user_id": "u1", "text": "new"})
        assert r.status_code == 200
        row = db.rows("room_messages")[0]
        assert row["text"] != "ciphertext" and row["edited_at"]


# ── Cross-user boundaries (#115) ───────────────────────────────────────────
#
# Each class pins one leak the cross-user matrix (tests/cross_user_matrix.py)
# reproduced, and the legitimate path next to it. The attacker is u9: a real
# user, member of the shared room r1 at most, never of A's private room r2.

M_SHARED = "11111111-1111-4111-8111-000000000001"
M_SHARED_2 = "11111111-1111-4111-8111-000000000002"
M_PRIVATE = "22222222-2222-4222-8222-000000000001"
PRIVATE_TEXT = "only u1 can read this"


def _two_rooms(db, *, u9_in_shared=True):
    from services.encryption import encrypt_if_present

    members = [_member("u1", "2026-01-01", room="r1"), _member("u1", "2026-01-01", room="r2")]
    if u9_in_shared:
        members.append(_member("u9", "2026-02-01", room="r1"))
    db.data.update(
        rooms=[_room(id="r1", owner="u1", code="SHARED"), _room(id="r2", owner="u1", code="PRIV")],
        room_members=members,
        room_messages=[
            _msg(id=M_SHARED, room_id="r1", text=encrypt_if_present("hello room"),
                 created_at="2026-03-01T00:00:00Z", reply_to_id=None),
            _msg(id=M_PRIVATE, room_id="r2", text=encrypt_if_present(PRIVATE_TEXT),
                 created_at="2026-03-01T00:00:00Z", reply_to_id=None),
        ],
    )


class TestReplyToIsRoomScoped:
    def _post(self, reply_to_id, *, user="u9", room="r1"):
        return client.post(f"/api/social/rooms/{room}/messages", json={
            "user_id": user, "user_name": "Nine", "text": "re", "reply_to_id": reply_to_id,
        })

    def test_reply_to_a_message_in_another_room_is_404_and_stores_nothing(self, db):
        _two_rooms(db)
        r = self._post(M_PRIVATE)
        assert r.status_code == 404
        assert PRIVATE_TEXT not in r.text
        assert len(db.rows("room_messages")) == 2

    def test_unknown_and_malformed_reply_ids_get_the_same_404(self, db):
        _two_rooms(db)
        for bad in ("33333333-3333-4333-8333-000000000009", "not-a-uuid", "eq.x"):
            r = self._post(bad)
            assert r.status_code == 404, bad
            assert r.json()["detail"] == "Message not found"
        assert len(db.rows("room_messages")) == 2

    def test_non_member_is_still_403(self, db):
        _two_rooms(db, u9_in_shared=False)
        assert self._post(M_SHARED).status_code == 403

    def test_reply_within_the_room_is_stored_and_renders_its_snippet(self, db):
        _two_rooms(db)
        r = self._post(M_SHARED)
        assert r.status_code == 200
        stored = [m for m in db.rows("room_messages") if m.get("reply_to_id")]
        assert [m["reply_to_id"] for m in stored] == [M_SHARED]

        # The fake assigns no id/created_at; the real table defaults both.
        stored[0].update(id=M_SHARED_2, created_at="2026-03-02T00:00:00Z")
        r = client.get("/api/social/rooms/r1/messages?user_id=u9")
        assert r.status_code == 200
        reply = next(m for m in r.json()["messages"] if m.get("reply_to_id"))
        assert reply["reply_to"] == {"id": M_SHARED, "user_name": "A", "text": "hello room"}

    def test_a_stored_cross_room_reply_renders_no_snippet(self, db):
        """Rows written before the post-side check: the read must not resolve
        them, and the row itself is left as it is (no data rewrite)."""
        _two_rooms(db)
        db.data["room_messages"].append(_msg(
            id=M_SHARED_2, room_id="r1", user_id="u9", user_name="Nine", text=None,
            image_url=None, created_at="2026-03-02T00:00:00Z", reply_to_id=M_PRIVATE,
        ))
        r = client.get("/api/social/rooms/r1/messages?user_id=u9")
        assert r.status_code == 200
        assert PRIVATE_TEXT not in r.text
        row = next(m for m in r.json()["messages"] if m["id"] == M_SHARED_2)
        assert row["reply_to"] is None
        assert row["reply_to_id"] == M_PRIVATE  # untouched


class TestReactionsRequireMembershipAndRoom:
    def _react(self, room, message_id, *, user="u9", emoji="👍"):
        return client.post(f"/api/social/rooms/{room}/messages/{message_id}/reactions",
                           json={"user_id": user, "emoji": emoji})

    def test_non_member_is_403_and_writes_nothing(self, db):
        _two_rooms(db)
        r = self._react("r2", M_PRIVATE)
        assert r.status_code == 403
        assert db.rows("room_reactions") == []

    def test_member_reacting_to_another_rooms_message_is_404(self, db):
        """u9 is in r1; naming r1 with r2's message id must not reach it."""
        _two_rooms(db)
        r = self._react("r1", M_PRIVATE)
        assert r.status_code == 404
        assert r.json()["detail"] == "Message not found"
        assert db.rows("room_reactions") == []

    def test_unknown_message_gets_the_same_404(self, db):
        _two_rooms(db)
        for bad in ("33333333-3333-4333-8333-000000000009", "not-a-uuid"):
            r = self._react("r1", bad)
            assert r.status_code == 404
            assert r.json()["detail"] == "Message not found"
        assert db.rows("room_reactions") == []

    def test_member_toggles_a_reaction_in_their_room(self, db):
        _two_rooms(db)
        r = self._react("r1", M_SHARED)
        assert r.status_code == 200 and r.json() == {"added": True}
        assert [(x["message_id"], x["user_id"]) for x in db.rows("room_reactions")] == [(M_SHARED, "u9")]
        db.rows("room_reactions")[0]["id"] = "rx1"  # the real table defaults it
        r = self._react("r1", M_SHARED)
        assert r.json() == {"added": False}


class TestLeaveRequiresMembership:
    def test_non_member_is_403_with_no_side_effects(self, db):
        db.data.update(
            rooms=[_room(owner="u1")],
            room_members=[_member("u1", "2026-01-01"), _member("u2", "2026-02-01")],
        )
        before_rooms = [dict(r) for r in db.rows("rooms")]
        before_members = [dict(r) for r in db.rows("room_members")]
        with patch("routes.social.invalidate_summary") as inv:
            r = client.post("/api/social/rooms/r1/leave", json={"user_id": "u9"})
        assert r.status_code == 403
        assert "owner_id" not in r.text
        inv.assert_not_called()
        assert db.rows("rooms") == before_rooms
        assert db.rows("room_members") == before_members

    def test_non_member_cannot_trigger_an_ownership_transfer(self, db):
        """A room whose owner had already gone (pre-#764 orphan): only a
        member's leave may heal it, never a stranger's."""
        db.data.update(
            rooms=[_room(owner="u1")],
            room_members=[_member("u2", "2026-02-01"), _member("u3", "2026-03-01")],
        )
        r = client.post("/api/social/rooms/r1/leave", json={"user_id": "u9"})
        assert r.status_code == 403
        assert db.rows("rooms")[0]["owner_id"] == "u1"
        assert db.rows("rooms")[0]["updated_at"] is None

    def test_a_missing_room_is_the_same_403(self, db):
        r = client.post("/api/social/rooms/nope/leave", json={"user_id": "u9"})
        assert r.status_code == 403


class TestSchoolMatchScope:
    """school_match follows the /students directory's rules: same school,
    private profiles opted out, listable accounts only."""

    def _users(self, *ids):
        return [{"id": i, "email": "ct", "is_approved": True, "deleted_at": None} for i in ids]

    def _run(self, peers):
        with patch("routes.social.academics.school_peer_user_ids", return_value=peers), \
             patch("routes.social.get_graph", return_value={"nodes": [], "edges": []}), \
             patch("routes.social.get_display_names", return_value={}), \
             patch("routes.social.get_display_name", return_value="Me"), \
             patch("routes.social.find_study_matches", return_value=[]) as match:
            r = client.post("/api/social/school-match", json={"user_id": "u1"})
        assert r.status_code == 200
        return [m["user_id"] for m in match.call_args.args[1]]

    def test_private_profiles_and_other_schools_are_not_candidates(self, db):
        db.data.update(
            users=self._users("u1", "u-public", "u-school", "u-private", "u-elsewhere"),
            user_settings=[
                {"user_id": "u-public", "profile_visibility": "public"},
                {"user_id": "u-school", "profile_visibility": "school"},
                {"user_id": "u-private", "profile_visibility": "private"},
            ],
        )
        peers = {"u1", "u-public", "u-school", "u-private"}  # u-elsewhere: another school
        assert self._run(peers) == ["u1", "u-public", "u-school"]

    def test_room_mates_are_still_excluded(self, db):
        db.data.update(
            users=self._users("u1", "u-mate", "u-peer"),
            room_members=[_member("u1", "2026-01-01"), _member("u-mate", "2026-01-02")],
        )
        assert self._run({"u1", "u-mate", "u-peer"}) == ["u1", "u-peer"]

    def test_no_school_means_no_candidates(self, db):
        db.data.update(users=self._users("u1", "u-anyone"))
        assert self._run(set()) == ["u1"]
