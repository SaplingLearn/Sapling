"""Streak advancement — the thing that makes streak_count mean anything.

`_today()` mirrors services.streak_service._today() (UTC calendar day) rather
than using `date.today()` (local wall-clock day). The two diverge for several
hours a day on any machine west of UTC, which would otherwise make these
assertions flaky depending on what time of day the suite runs.
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _user(last_active, streak, longest=0):
    t = MagicMock()
    t.select.return_value = [{
        "last_active_date": last_active,
        "streak_count": streak,
        "longest_streak": longest,
    }]
    t.update.return_value = []
    return t


class TestTouchStreak:
    def test_first_ever_activity_starts_at_one(self):
        t = _user(None, 0)
        with patch("services.streak_service.table", return_value=t):
            from services.streak_service import touch_streak
            assert touch_streak("u1") == 1

    def test_same_day_repeat_does_not_advance(self):
        today = _today().isoformat()
        t = _user(today, 4)
        with patch("services.streak_service.table", return_value=t):
            from services.streak_service import touch_streak
            assert touch_streak("u1") == 4
        t.update.assert_not_called()

    def test_yesterday_advances_by_one(self):
        yesterday = (_today() - timedelta(days=1)).isoformat()
        t = _user(yesterday, 4)
        with patch("services.streak_service.table", return_value=t):
            from services.streak_service import touch_streak
            assert touch_streak("u1") == 5

    def test_a_gap_resets_to_one(self):
        stale = (_today() - timedelta(days=3)).isoformat()
        t = _user(stale, 20)
        with patch("services.streak_service.table", return_value=t):
            from services.streak_service import touch_streak
            assert touch_streak("u1") == 1

    def test_longest_streak_ratchets_up(self):
        yesterday = (_today() - timedelta(days=1)).isoformat()
        t = _user(yesterday, 9, longest=9)
        with patch("services.streak_service.table", return_value=t):
            from services.streak_service import touch_streak
            touch_streak("u1")
        assert t.update.call_args[0][0]["longest_streak"] == 10

    def test_longest_streak_is_not_lowered_by_a_reset(self):
        stale = (_today() - timedelta(days=5)).isoformat()
        t = _user(stale, 30, longest=30)
        with patch("services.streak_service.table", return_value=t):
            from services.streak_service import touch_streak
            touch_streak("u1")
        assert t.update.call_args[0][0]["longest_streak"] == 30
