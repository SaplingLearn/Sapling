"""Gamification endpoints — hero card, leaderboards, activity."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

STAGE = {"slug": "seed", "name": "Seed", "blurb": "b", "min_level": 10,
         "xp_to_complete": 500, "sort_order": 2}


def _tables(handles):
    return lambda name: handles[name]


class TestMe:
    def test_reports_level_stage_and_progress(self):
        handles = {"users": MagicMock(), "xp_events": MagicMock(),
                   "user_achievements": MagicMock(), "achievements": MagicMock()}
        handles["users"].select.return_value = [{
            "total_xp": 720, "level": 12, "streak_count": 23,
            "longest_streak": 31, "daily_goal_xp": 50,
        }]
        handles["xp_events"].select.return_value = [
            {"amount": 40, "created_at": datetime.now(timezone.utc).isoformat()}
        ]
        handles["user_achievements"].select.return_value = [{"achievement_id": "a1"}]
        handles["achievements"].select.return_value = [{"id": "a1"}, {"id": "a2"}]
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.xp_into_level", return_value=(20, 100)):
            r = client.get("/api/gamification/me?user_id=u1")
        body = r.json()
        assert body["level"] == 12
        assert body["stage"]["name"] == "Seed"
        assert body["xp_into_level"] == 20
        assert body["level_pct"] == 20
        assert body["today_xp"] == 40
        assert body["earned_count"] == 1
        assert body["total_count"] == 2

    def test_the_badge_total_counts_live_only(self):
        handles = {"users": MagicMock(), "xp_events": MagicMock(),
                   "user_achievements": MagicMock(), "achievements": MagicMock()}
        handles["users"].select.return_value = [{"total_xp": 0, "level": 1}]
        for k in ("xp_events", "user_achievements", "achievements"):
            handles[k].select.return_value = []
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.xp_into_level", return_value=(0, 50)):
            client.get("/api/gamification/me?user_id=u1")
        # Drafts are work-in-progress and must not inflate the denominator.
        assert handles["achievements"].select.call_args.kwargs["filters"] == {
            "status": "eq.live"
        }

    def test_sends_a_private_cache_control(self):
        handles = {"users": MagicMock(), "xp_events": MagicMock(),
                   "user_achievements": MagicMock(), "achievements": MagicMock()}
        handles["users"].select.return_value = [{"total_xp": 0, "level": 1}]
        for k in ("xp_events", "user_achievements", "achievements"):
            handles[k].select.return_value = []
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.xp_into_level", return_value=(0, 50)):
            r = client.get("/api/gamification/me?user_id=u1")
        assert "private" in r.headers["cache-control"]
        assert "public" not in r.headers["cache-control"]


class TestLeaderboard:
    def _week_events(self):
        now = datetime.now(timezone.utc).isoformat()
        return [
            {"user_id": "u1", "amount": 300, "created_at": now},
            {"user_id": "u2", "amount": 500, "created_at": now},
            {"user_id": "u3", "amount": 100, "created_at": now},
        ]

    def test_ranks_by_weekly_xp_descending(self):
        handles = {"xp_events": MagicMock(), "users": MagicMock(),
                   "user_settings": MagicMock(), "friendships": MagicMock()}
        handles["xp_events"].select.return_value = self._week_events()
        handles["users"].select.return_value = [
            {"id": "u1", "level": 5, "total_xp": 900, "streak_count": 3},
            {"id": "u2", "level": 9, "total_xp": 2000, "streak_count": 12},
            {"id": "u3", "level": 2, "total_xp": 200, "streak_count": 1},
        ]
        handles["user_settings"].select.return_value = []
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.get_display_names",
                   return_value={"u1": "A", "u2": "B", "u3": "C"}):
            r = client.get("/api/gamification/leaderboard?user_id=u1&scope=everyone")
        rows = r.json()["rows"]
        assert [x["rank"] for x in rows] == [1, 2, 3]
        assert rows[0]["user_id"] == "u2"
        assert rows[1]["is_you"] is True

    def test_private_users_are_hidden_but_still_see_themselves(self):
        handles = {"xp_events": MagicMock(), "users": MagicMock(),
                   "user_settings": MagicMock(), "friendships": MagicMock()}
        handles["xp_events"].select.return_value = self._week_events()
        handles["users"].select.return_value = [
            {"id": "u1", "level": 5, "total_xp": 900, "streak_count": 3},
            {"id": "u2", "level": 9, "total_xp": 2000, "streak_count": 12},
            {"id": "u3", "level": 2, "total_xp": 200, "streak_count": 1},
        ]
        handles["user_settings"].select.return_value = [
            {"user_id": "u2", "profile_visibility": "private"}
        ]
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.get_display_names",
                   return_value={"u1": "A", "u3": "C"}):
            r = client.get("/api/gamification/leaderboard?user_id=u1&scope=everyone")
        ids = [x["user_id"] for x in r.json()["rows"]]
        assert "u2" not in ids
        assert r.json()["you"]["user_id"] == "u1"

    def test_private_viewer_sees_their_own_row(self):
        handles = {"xp_events": MagicMock(), "users": MagicMock(),
                   "user_settings": MagicMock(), "friendships": MagicMock()}
        handles["xp_events"].select.return_value = self._week_events()
        handles["users"].select.return_value = [
            {"id": "u1", "level": 5, "total_xp": 900, "streak_count": 3},
        ]
        handles["user_settings"].select.return_value = [
            {"user_id": "u1", "profile_visibility": "private"}
        ]
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.get_display_names", return_value={"u1": "A"}):
            r = client.get("/api/gamification/leaderboard?user_id=u1&scope=everyone")
        assert r.json()["you"]["user_id"] == "u1"

    def test_friends_scope_filters_to_friends_plus_self(self):
        handles = {"xp_events": MagicMock(), "users": MagicMock(),
                   "user_settings": MagicMock(), "friendships": MagicMock()}
        handles["friendships"].select.return_value = [{"friend_id": "u3"}]
        handles["xp_events"].select.return_value = self._week_events()
        handles["users"].select.return_value = [
            {"id": "u1", "level": 5, "total_xp": 900, "streak_count": 3},
            {"id": "u3", "level": 2, "total_xp": 200, "streak_count": 1},
        ]
        handles["user_settings"].select.return_value = []
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.get_display_names",
                   return_value={"u1": "A", "u3": "C"}):
            r = client.get("/api/gamification/leaderboard?user_id=u1&scope=friends")
        assert {x["user_id"] for x in r.json()["rows"]} == {"u1", "u3"}

    def test_rejects_an_unknown_scope(self):
        with patch("routes.gamification.table"):
            r = client.get("/api/gamification/leaderboard?user_id=u1&scope=galaxy")
        assert r.status_code == 400


class TestActivity:
    def test_buckets_the_last_seven_days(self):
        now = datetime.now(timezone.utc)
        handles = {"xp_events": MagicMock(), "users": MagicMock()}
        handles["xp_events"].select.return_value = [
            {"amount": 40, "created_at": now.isoformat()},
            {"amount": 60, "created_at": (now - timedelta(days=1)).isoformat()},
            {"amount": 25, "created_at": (now - timedelta(days=40)).isoformat()},
        ]
        handles["users"].select.return_value = [
            {"streak_count": 4, "daily_goal_xp": 50}
        ]
        with patch("routes.gamification.table", side_effect=_tables(handles)):
            r = client.get("/api/gamification/activity?user_id=u1")
        body = r.json()
        assert len(body["week"]) == 7
        assert body["week"][-1]["xp"] == 40
        assert body["week"][-2]["xp"] == 60
        assert body["tiles"]["week_total"] == 100
        assert len(body["trend"]) == 8
