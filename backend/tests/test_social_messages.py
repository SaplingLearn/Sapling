"""
Unit tests for routes/social.py message endpoints — focused on the new
pagination behavior (`before` and `limit` query params, `has_more` flag).
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

ROOM_ID = "room_1"


def _mk_msg(i: int, ts: str) -> dict:
    return {
        "id": f"m{i}", "room_id": ROOM_ID, "user_id": "u1", "user_name": "Alice",
        "text": f"msg {i}", "image_url": None, "created_at": ts,
        "reply_to_id": None, "is_deleted": False, "edited_at": None,
    }


class TestGetRoomMessages:
    def test_default_limit_returns_ascending(self):
        # Route fetches newest-first from the DB, then reverses to ascending.
        desc_rows = [_mk_msg(3, "2026-04-03T00:00:00Z"),
                     _mk_msg(2, "2026-04-02T00:00:00Z"),
                     _mk_msg(1, "2026-04-01T00:00:00Z")]
        def table_side_effect(name):
            m = MagicMock()
            if name == "room_messages":
                m.select.return_value = desc_rows
            elif name == "room_reactions":
                m.select.return_value = []
            else:
                m.select.return_value = []
            return m

        with patch("routes.social.table", side_effect=table_side_effect):
            r = client.get(f"/api/social/rooms/{ROOM_ID}/messages")

        assert r.status_code == 200
        body = r.json()
        ids = [m["id"] for m in body["messages"]]
        assert ids == ["m1", "m2", "m3"]  # ascending
        assert body["has_more"] is False  # fewer than default limit (50)

    def test_has_more_true_when_page_is_full(self):
        rows = [_mk_msg(i, f"2026-04-{i:02d}T00:00:00Z") for i in range(1, 6)]  # 5 rows
        def table_side_effect(name):
            m = MagicMock()
            if name == "room_messages":
                m.select.return_value = list(reversed(rows))  # DB returns desc
            elif name == "room_reactions":
                m.select.return_value = []
            else:
                m.select.return_value = []
            return m

        with patch("routes.social.table", side_effect=table_side_effect):
            r = client.get(f"/api/social/rooms/{ROOM_ID}/messages?limit=5")

        body = r.json()
        assert body["has_more"] is True
        assert len(body["messages"]) == 5

    def test_before_filter_is_passed_through(self):
        captured = {}
        def table_side_effect(name):
            m = MagicMock()
            if name == "room_messages":
                def _select(cols, filters=None, order=None, limit=None):
                    captured["filters"] = filters
                    captured["order"] = order
                    captured["limit"] = limit
                    return []
                m.select.side_effect = _select
            elif name == "room_reactions":
                m.select.return_value = []
            else:
                m.select.return_value = []
            return m

        with patch("routes.social.table", side_effect=table_side_effect):
            r = client.get(f"/api/social/rooms/{ROOM_ID}/messages?before=2026-04-02T00:00:00Z&limit=20")

        assert r.status_code == 200
        assert captured["filters"]["created_at"] == "lt.2026-04-02T00:00:00Z"
        assert captured["order"] == "created_at.desc"
        assert captured["limit"] == 20

    def test_invalid_before_rejected(self):
        # Guards against PostgREST operator injection (e.g. ?before=null or
        # ?before=gt.2026-01-01). Anything not parseable as ISO 8601 is 400.
        with patch("routes.social.table"):
            for bad in ["null", "gt.2026-01-01", "not-a-date", "is.null", ""]:
                if not bad:  # empty string skips the `if before:` branch; still valid
                    continue
                r = client.get(f"/api/social/rooms/{ROOM_ID}/messages?before={bad}")
                assert r.status_code == 400, f"expected 400 for before={bad!r}"

    def test_empty_room_returns_no_more(self):
        with patch("routes.social.table") as t:
            t.return_value.select.return_value = []
            r = client.get(f"/api/social/rooms/{ROOM_ID}/messages")
        assert r.status_code == 200
        assert r.json() == {"messages": [], "has_more": False}

    def test_limit_is_clamped_to_max(self):
        captured = {}
        def table_side_effect(name):
            m = MagicMock()
            if name == "room_messages":
                def _select(cols, filters=None, order=None, limit=None):
                    captured["limit"] = limit
                    return []
                m.select.side_effect = _select
            elif name == "room_reactions":
                m.select.return_value = []
            else:
                m.select.return_value = []
            return m

        with patch("routes.social.table", side_effect=table_side_effect):
            r = client.get(f"/api/social/rooms/{ROOM_ID}/messages?limit=9999")

        assert r.status_code == 200
        assert captured["limit"] == 200  # clamped

    def test_limit_floor_is_one(self):
        captured = {}
        def table_side_effect(name):
            m = MagicMock()
            if name == "room_messages":
                def _select(cols, filters=None, order=None, limit=None):
                    captured["limit"] = limit
                    return []
                m.select.side_effect = _select
            elif name == "room_reactions":
                m.select.return_value = []
            else:
                m.select.return_value = []
            return m

        with patch("routes.social.table", side_effect=table_side_effect):
            r = client.get(f"/api/social/rooms/{ROOM_ID}/messages?limit=0")

        assert r.status_code == 200
        assert captured["limit"] == 1
