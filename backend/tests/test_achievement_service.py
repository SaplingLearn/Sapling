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
                m.select.return_value = [{"slug": "study_beginner"}]
            elif name == "achievement_cosmetics":
                m.select.return_value = []
            else:
                m.select.return_value = []
            return m

        with patch("services.achievement_service.table", side_effect=table_side_effect):
            from services.achievement_service import check_achievements
            result = check_achievements("u1", "session_count", {})

        assert "study_beginner" in result

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
                m.select.return_value = [{"slug": "first_upload"}]
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

        with patch("services.achievement_service.table", side_effect=table_side_effect):
            from services.achievement_service import check_achievements
            check_achievements("u1", "documents_uploaded", {})

        assert len(insert_calls) == 1
        assert insert_calls[0]["cosmetic_id"] == "cos_1"
