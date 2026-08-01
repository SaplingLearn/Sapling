"""
Unit tests for services/achievement_service.py

Tests cover:
  - _get_user_stat returns correct values for each trigger type
  - check_achievements grants achievements when threshold is met
  - check_achievements skips already-earned achievements
  - check_achievements grants linked cosmetics
  - check_achievements returns list of newly earned slugs
"""
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime


class TestGetUserStat:
    def test_login_streak(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [{"streak_count": 7}]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "login_streak") == 7

    def test_session_count(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "session_count") == 3

    def test_documents_uploaded(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [{"id": "d1"}]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "documents_uploaded") == 1

    def test_unknown_type_returns_zero(self):
        with patch("services.achievement_service.table") as t:
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "unknown_type") == 0

    def test_streak_missing_user_returns_zero(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = []
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "login_streak") == 0


class TestCheckAchievements:
    def test_grants_achievement_when_threshold_met(self):
        triggers = [{"id": "t1", "achievement_id": "a1", "trigger_type": "session_count", "trigger_threshold": 3}]

        def table_side_effect(name):
            m = MagicMock()
            if name == "achievement_triggers":
                m.select.return_value = triggers
            elif name == "user_achievements":
                m.select.return_value = []
                m.insert.return_value = [{}]
            elif name == "sessions":
                m.select.return_value = [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]
            elif name == "achievements":
                m.select.return_value = [{
                    "slug": "study_beginner", "name": "Study Beginner",
                    "xp_reward": 0, "status": "live",
                }]
            elif name == "achievement_cosmetics":
                m.select.return_value = []
            else:
                m.select.return_value = []
            return m

        with patch("services.achievement_service.table", side_effect=table_side_effect), \
             patch("services.achievement_service.award_xp_safe"):
            from services.achievement_service import check_achievements
            result = check_achievements("u1", "session_count", {})

        assert any(e["slug"] == "study_beginner" for e in result)

    def test_skips_already_earned(self):
        triggers = [{"id": "t1", "achievement_id": "a1", "trigger_type": "session_count", "trigger_threshold": 1}]

        def table_side_effect(name):
            m = MagicMock()
            if name == "achievement_triggers":
                m.select.return_value = triggers
            elif name == "user_achievements":
                m.select.return_value = [{"achievement_id": "a1"}]
            elif name == "sessions":
                m.select.return_value = [{"id": "s1"}, {"id": "s2"}]
            else:
                m.select.return_value = []
            return m

        with patch("services.achievement_service.table", side_effect=table_side_effect):
            from services.achievement_service import check_achievements
            result = check_achievements("u1", "session_count", {})

        assert result == []

    def test_no_triggers_returns_empty(self):
        def table_side_effect(name):
            m = MagicMock()
            m.select.return_value = []
            return m

        with patch("services.achievement_service.table", side_effect=table_side_effect):
            from services.achievement_service import check_achievements
            result = check_achievements("u1", "nonexistent_event", {})

        assert result == []

    def test_threshold_not_met_returns_empty(self):
        triggers = [{"id": "t1", "achievement_id": "a1", "trigger_type": "session_count", "trigger_threshold": 10}]

        def table_side_effect(name):
            m = MagicMock()
            if name == "achievement_triggers":
                m.select.return_value = triggers
            elif name == "user_achievements":
                m.select.return_value = []
            elif name == "sessions":
                m.select.return_value = [{"id": "s1"}]
            else:
                m.select.return_value = []
            return m

        with patch("services.achievement_service.table", side_effect=table_side_effect):
            from services.achievement_service import check_achievements
            result = check_achievements("u1", "session_count", {})

        assert result == []

    def test_grants_linked_cosmetics(self):
        triggers = [{"id": "t1", "achievement_id": "a1", "trigger_type": "documents_uploaded", "trigger_threshold": 1}]
        linked = [{"cosmetic_id": "cos_1"}]
        insert_calls = []

        def table_side_effect(name):
            m = MagicMock()
            if name == "achievement_triggers":
                m.select.return_value = triggers
            elif name == "user_achievements":
                m.select.return_value = []
                m.insert.return_value = [{}]
            elif name == "documents":
                m.select.return_value = [{"id": "d1"}]
            elif name == "achievements":
                m.select.return_value = [{
                    "slug": "first_upload", "name": "First Upload",
                    "xp_reward": 0, "status": "live",
                }]
            elif name == "achievement_cosmetics":
                m.select.return_value = linked
            elif name == "user_cosmetics":
                def track_insert(data):
                    insert_calls.append(data)
                    return [{}]
                m.insert.side_effect = track_insert
            else:
                m.select.return_value = []
            return m

        with patch("services.achievement_service.table", side_effect=table_side_effect), \
             patch("services.achievement_service.award_xp_safe"):
            from services.achievement_service import check_achievements
            check_achievements("u1", "documents_uploaded", {})

        assert len(insert_calls) == 1
        assert insert_calls[0]["cosmetic_id"] == "cos_1"


class TestNewTriggerTypes:
    def test_flashcards_reviewed_sums_times_reviewed(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [
                {"times_reviewed": 40}, {"times_reviewed": 61}
            ]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "flashcards_reviewed") == 101

    def test_concepts_mastered_counts_mastered_nodes(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [{"id": "n1"}, {"id": "n2"}]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "concepts_mastered") == 2

    def test_courses_with_mastery_counts_distinct_courses(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [
                {"course_id": "c1"}, {"course_id": "c1"}, {"course_id": "c2"}, {"course_id": None}
            ]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "courses_with_mastery") == 2

    def test_friends_count(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [{"friend_id": "u2"}, {"friend_id": "u3"}]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "friends_count") == 2

    def test_level_reads_the_cached_column(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [{"level": 17}]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "level") == 17

    def test_session_minutes_takes_the_longest_session(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [
                {"started_at": "2026-07-01T10:00:00+00:00", "ended_at": "2026-07-01T10:45:00+00:00"},
                {"started_at": "2026-07-02T10:00:00+00:00", "ended_at": "2026-07-02T12:30:00+00:00"},
            ]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "session_minutes") == 150

    def test_session_minutes_ignores_unfinished_sessions(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [
                {"started_at": "2026-07-01T10:00:00+00:00", "ended_at": None},
            ]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "session_minutes") == 0

    def test_xp_in_day_takes_the_best_day(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [
                {"amount": 200, "created_at": "2026-07-01T09:00:00+00:00"},
                {"amount": 150, "created_at": "2026-07-01T20:00:00+00:00"},
                {"amount": 300, "created_at": "2026-07-02T09:00:00+00:00"},
            ]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "xp_in_day") == 350


class TestGrantPaysXp:
    def test_granting_awards_the_badge_reward(self):
        with patch("services.achievement_service.table") as t, \
             patch("services.achievement_service.award_xp_safe") as award:
            def _select(columns="*", filters=None, **kw):
                if "trigger_type" in (filters or {}):
                    return [{"id": "t1", "achievement_id": "a1",
                             "trigger_type": "login_streak", "trigger_threshold": 7}]
                if columns.startswith("slug"):
                    return [{"slug": "on-fire", "name": "On Fire", "xp_reward": 120,
                             "status": "live"}]
                if columns == "achievement_id":
                    return []
                if columns == "streak_count":
                    return [{"streak_count": 9}]
                return []
            t.return_value.select.side_effect = _select
            from services.achievement_service import check_achievements
            earned = check_achievements("u1", "login_streak")
        assert earned == [{"slug": "on-fire", "name": "On Fire", "xp": 120}]
        award.assert_called_once_with(
            "u1", "achievement_unlocked", source_type="achievement",
            source_id="a1", amount=120,
        )


class TestDraftsAreNeverGranted:
    def test_a_draft_badge_is_not_awarded(self):
        with patch("services.achievement_service.table") as t, \
             patch("services.achievement_service.award_xp_safe") as award:
            def _select(columns="*", filters=None, **kw):
                if "trigger_type" in (filters or {}):
                    return [{"id": "t1", "achievement_id": "a1",
                             "trigger_type": "login_streak", "trigger_threshold": 7}]
                if columns.startswith("slug"):
                    return [{"slug": "streak_7", "name": "Week Warrior",
                             "xp_reward": 0, "status": "draft"}]
                if columns == "achievement_id":
                    return []
                if columns == "streak_count":
                    return [{"streak_count": 9}]
                return []
            t.return_value.select.side_effect = _select
            from services.achievement_service import check_achievements
            assert check_achievements("u1", "login_streak") == []
        t.return_value.insert.assert_not_called()
        award.assert_not_called()
