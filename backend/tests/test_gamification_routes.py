"""Gamification endpoints — hero card, leaderboards, activity."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

STAGE = {"slug": "seed", "name": "Seed", "blurb": "b", "min_level": 10,
         "xp_to_complete": 500, "sort_order": 2}


def _tables(handles):
    return lambda name: handles[name]


def _one_page(handle, rows):
    """Stub a single-page select_with_count response (rows == total)."""
    handle.select_with_count.return_value = (rows, len(rows))


class TestMe:
    def test_reports_level_stage_and_progress(self):
        handles = {"users": MagicMock(), "xp_events": MagicMock(),
                   "user_achievements": MagicMock(), "achievements": MagicMock()}
        handles["users"].select.return_value = [{
            "total_xp": 720, "level": 12, "streak_count": 23,
            "longest_streak": 31, "daily_goal_xp": 50,
        }]
        _one_page(handles["xp_events"], [
            {"amount": 40, "created_at": datetime.now(timezone.utc).isoformat()}
        ])
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
        _one_page(handles["xp_events"], [])
        for k in ("user_achievements", "achievements"):
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
        _one_page(handles["xp_events"], [])
        for k in ("user_achievements", "achievements"):
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
        _one_page(handles["xp_events"], self._week_events())
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
        _one_page(handles["xp_events"], self._week_events())
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
        _one_page(handles["xp_events"], self._week_events())
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
        _one_page(handles["xp_events"], self._week_events())
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

    def test_school_scope_filters_to_peers_plus_self(self):
        handles = {"xp_events": MagicMock(), "users": MagicMock(),
                   "user_settings": MagicMock(), "friendships": MagicMock()}
        _one_page(handles["xp_events"], self._week_events())
        handles["users"].select.return_value = [
            {"id": "u1", "level": 5, "total_xp": 900, "streak_count": 3},
            {"id": "u3", "level": 2, "total_xp": 200, "streak_count": 1},
        ]
        handles["user_settings"].select.return_value = []
        # u2 is present in the week's events but is not a school peer of u1 —
        # school_peer_user_ids returning {u1, u3} must exclude them from rows.
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.academics.school_peer_user_ids",
                   return_value={"u1", "u3"}), \
             patch("routes.gamification.get_display_names",
                   return_value={"u1": "A", "u3": "C"}):
            r = client.get("/api/gamification/leaderboard?user_id=u1&scope=school")
        ids = {x["user_id"] for x in r.json()["rows"]}
        assert ids == {"u1", "u3"}
        assert "u2" not in ids

    def test_rejects_an_unknown_scope(self):
        with patch("routes.gamification.table"):
            r = client.get("/api/gamification/leaderboard?user_id=u1&scope=galaxy")
        assert r.status_code == 400


class TestActivity:
    def test_buckets_the_last_seven_days(self):
        now = datetime.now(timezone.utc)
        handles = {"xp_events": MagicMock(), "users": MagicMock()}
        _one_page(handles["xp_events"], [
            {"amount": 40, "created_at": now.isoformat()},
            {"amount": 60, "created_at": (now - timedelta(days=1)).isoformat()},
            {"amount": 25, "created_at": (now - timedelta(days=40)).isoformat()},
        ])
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


class TestEventsSincePagination:
    def test_pages_past_a_full_page_of_xp_events(self):
        """PostgREST caps a single response at supabase/config.toml's
        max_rows (1000) and signals the cut with 206 Partial Content — a 2xx,
        so a single unbounded select would silently drop rows past the cap.
        This proves _events_since keeps paging until a short page comes back,
        rather than stopping after the first (full) page."""
        from routes.gamification import _XP_EVENTS_PAGE, _events_since

        now = datetime.now(timezone.utc).isoformat()
        full_page = [
            {"user_id": "u1", "amount": 1, "created_at": now}
            for _ in range(_XP_EVENTS_PAGE)
        ]
        short_page = [{"user_id": "u1", "amount": 2, "created_at": now}]
        total = len(full_page) + len(short_page)

        handle = MagicMock()
        handle.select_with_count.side_effect = [
            (full_page, total),
            (short_page, total),
        ]
        with patch("routes.gamification.table", return_value=handle):
            rows = _events_since("u1", datetime.now(timezone.utc) - timedelta(days=1))

        assert len(rows) == total
        # This amount only exists on the second page — proves both pages
        # were accumulated, not just the first.
        assert sum(1 for r in rows if r["amount"] == 2) == 1
        assert handle.select_with_count.call_count == 2
        first_call, second_call = handle.select_with_count.call_args_list
        assert first_call.kwargs["offset"] == 0
        assert second_call.kwargs["offset"] == _XP_EVENTS_PAGE


# ── Auth guard ───────────────────────────────────────────────────────────────

class TestAuthGuard:
    """Every /api/gamification endpoint takes `user_id` as a query parameter,
    so each one must call `require_self(user_id, request)` before touching the
    DB — otherwise `?user_id=<victim>` is an unauthenticated read of another
    user's XP, streaks and friends list, and `leaderboard?scope=everyone`
    enumerates every user with an app-decrypted display name.

    conftest's autouse `_bypass_session_auth` fixture stubs
    `routes.gamification.require_self` to a no-op for the rest of this file,
    so merely calling the endpoint proves nothing. These re-patch it on top of
    that stub to assert it is actually invoked with the right user id, and
    that a rejection propagates rather than being swallowed.
    """

    def _handles(self):
        handles = {
            "users": MagicMock(), "xp_events": MagicMock(),
            "user_achievements": MagicMock(), "achievements": MagicMock(),
            "friendships": MagicMock(), "user_settings": MagicMock(),
        }
        handles["users"].select.return_value = [{
            "id": "u1", "total_xp": 0, "level": 1, "streak_count": 0,
            "longest_streak": 0, "daily_goal_xp": 50,
        }]
        _one_page(handles["xp_events"], [])
        handles["user_achievements"].select.return_value = []
        handles["achievements"].select.return_value = []
        handles["friendships"].select.return_value = []
        handles["user_settings"].select.return_value = []
        return handles

    def test_me_checks_the_user_id(self):
        handles = self._handles()
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.require_self") as guard:
            r = client.get("/api/gamification/me?user_id=u1")
        assert r.status_code == 200
        assert guard.call_args[0][0] == "u1"

    def test_leaderboard_checks_the_user_id(self):
        handles = self._handles()
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.get_display_names", return_value={}), \
             patch("routes.gamification.require_self") as guard:
            r = client.get("/api/gamification/leaderboard?user_id=u1&scope=everyone")
        assert r.status_code == 200
        assert guard.call_args[0][0] == "u1"

    def test_activity_checks_the_user_id(self):
        handles = self._handles()
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.require_self") as guard:
            r = client.get("/api/gamification/activity?user_id=u1")
        assert r.status_code == 200
        assert guard.call_args[0][0] == "u1"

    def test_me_rejection_propagates(self):
        handles = self._handles()
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.require_self",
                   side_effect=HTTPException(status_code=403, detail="nope")):
            r = client.get("/api/gamification/me?user_id=victim")
        assert r.status_code == 403

    def test_leaderboard_rejection_propagates(self):
        handles = self._handles()
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.require_self",
                   side_effect=HTTPException(status_code=403, detail="nope")):
            r = client.get("/api/gamification/leaderboard?user_id=victim&scope=friends")
        assert r.status_code == 403

    def test_activity_rejection_propagates(self):
        handles = self._handles()
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.require_self",
                   side_effect=HTTPException(status_code=403, detail="nope")):
            r = client.get("/api/gamification/activity?user_id=victim")
        assert r.status_code == 403

    def test_the_guard_runs_before_any_db_read(self):
        """Fail-closed ordering: a rejected caller must not have caused a
        single row to be read (an unauthenticated 403 that still enumerated
        the leaderboard would leak through logs/timing)."""
        handles = self._handles()
        with patch("routes.gamification.table", side_effect=_tables(handles)) as tbl, \
             patch("routes.gamification.require_self",
                   side_effect=HTTPException(status_code=403, detail="nope")):
            client.get("/api/gamification/leaderboard?user_id=victim")
        tbl.assert_not_called()


class TestLiveCountersRevalidate:
    """The XP surfaces must never be reused from the browser's cache without
    asking us first.

    Regression for the bug frontend/e2e/gamification.spec.ts caught on its
    first real run against the live stack: these routes shipped with
    http_cache.CACHE_CONTROL ("private, max-age=30, ..."), so after XP was
    earned and the page reloaded, Chromium answered /api/gamification/me from
    its own still-fresh copy and the hero card kept rendering "0 XP total" for
    up to 30 seconds. The ETag was already correct and could not help — a
    response inside its freshness window is never revalidated.

    Asserting the exact directive is the point: the difference between
    max-age=30 and no-cache IS the bug.
    """

    ROUTES = ("/api/gamification/me", "/api/gamification/leaderboard",
              "/api/gamification/activity")

    @staticmethod
    def _empty_tables():
        """Every table read returns nothing — these tests are about headers,
        and an empty stack still produces a 200 with a stable ETag."""
        def _factory(name):
            h = MagicMock()
            h.select.return_value = []
            h.select_with_count.return_value = ([], 0)
            return h
        return _factory

    def _get(self, route, headers=None):
        with patch("routes.gamification.table", side_effect=self._empty_tables()), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.xp_into_level", return_value=(0, 100)):
            return client.get(route, params={"user_id": "u1"}, headers=headers)

    def test_every_live_counter_route_forbids_unrevalidated_reuse(self):
        for route in self.ROUTES:
            r = self._get(route)
            assert r.status_code == 200, f"{route} -> {r.status_code}"
            cc = r.headers.get("cache-control", "")
            assert "no-cache" in cc, f"{route} may be reused unrevalidated: {cc!r}"
            assert "max-age=30" not in cc, f"{route} still has a no-ask window: {cc!r}"
            # Never shared-cacheable — user-scoped, app-decrypted data (CLAUDE.md).
            assert "private" in cc, f"{route} is not private: {cc!r}"

    def test_the_304_carries_the_same_directive_as_the_200(self):
        """A 304 refreshes the stored response's headers. If it carried the
        default max-age=30, the very next revalidation would hand the browser
        a fresh no-ask window and reintroduce the bug one request later."""
        for route in self.ROUTES:
            first = self._get(route)
            etag = first.headers.get("etag")
            assert etag, f"{route} served no ETag"
            second = self._get(route, headers={"If-None-Match": etag})
            assert second.status_code == 304, f"{route} -> {second.status_code}"
            assert second.headers.get("cache-control") == first.headers.get("cache-control"), \
                f"{route}: 304 and 200 disagree on Cache-Control"
