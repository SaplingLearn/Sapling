"""Unit tests for services/xp_service.py."""
import pytest
from unittest.mock import MagicMock, patch

import httpx

RULE = [{"key": "quiz_completed", "label": "Completed a quiz", "amount": 30, "enabled": True}]


def _tables(rule_rows=RULE, user_rows=None, insert=None):
    """Build a `table` stub that dispatches on table name."""
    user_rows = user_rows if user_rows is not None else [{"total_xp": 0, "level": 1}]
    handles = {
        "xp_rules": MagicMock(),
        "xp_events": MagicMock(),
        "users": MagicMock(),
    }
    handles["xp_rules"].select.return_value = rule_rows
    handles["xp_events"].insert.side_effect = insert or (lambda data: [data])
    handles["users"].select.return_value = user_rows
    handles["users"].update.return_value = []
    return lambda name: handles[name], handles


class TestAwardXp:
    def test_awards_the_rule_amount(self):
        tbl, handles = _tables()
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        assert result.awarded == 30
        assert result.total_xp == 30
        assert result.duplicate is False

    def test_explicit_amount_overrides_the_rule(self):
        tbl, _ = _tables()
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1):
            from services.xp_service import award_xp
            result = award_xp("u1", "achievement_unlocked", amount=120,
                              source_type="achievement", source_id="a1")
        assert result.awarded == 120

    def test_disabled_rule_pays_nothing(self):
        tbl, handles = _tables(rule_rows=[{**RULE[0], "enabled": False}])
        with patch("services.xp_service.table", side_effect=tbl):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        assert result.awarded == 0
        handles["xp_events"].insert.assert_not_called()

    def test_unknown_rule_pays_nothing(self):
        tbl, handles = _tables(rule_rows=[])
        with patch("services.xp_service.table", side_effect=tbl):
            from services.xp_service import award_xp
            result = award_xp("u1", "nope", source_type="quiz", source_id="q1")
        assert result.awarded == 0
        handles["xp_events"].insert.assert_not_called()

    def test_duplicate_idempotency_key_is_a_no_op(self):
        """A 409 from the unique index means someone already paid this out."""
        response = MagicMock(status_code=409)
        def _conflict(_data):
            raise httpx.HTTPStatusError("duplicate", request=MagicMock(), response=response)

        tbl, handles = _tables(insert=_conflict, user_rows=[{"total_xp": 30, "level": 1}])
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        assert result.duplicate is True
        assert result.awarded == 0
        assert result.total_xp == 30
        handles["users"].update.assert_not_called()

    def test_non_conflict_http_error_propagates(self):
        response = MagicMock(status_code=500)
        def _boom(_data):
            raise httpx.HTTPStatusError("server error", request=MagicMock(), response=response)

        tbl, _ = _tables(insert=_boom)
        with patch("services.xp_service.table", side_effect=tbl):
            from services.xp_service import award_xp
            with pytest.raises(httpx.HTTPStatusError):
                award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")

    def test_reports_a_level_up(self):
        tbl, handles = _tables(user_rows=[{"total_xp": 40, "level": 1}])
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=2):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        assert result.leveled_up is True
        assert result.level == 2
        handles["users"].update.assert_called_once()
        assert handles["users"].update.call_args[0][0] == {"total_xp": 70, "level": 2}


class TestIdempotencyKey:
    def test_is_stable_for_the_same_source(self):
        from services.xp_service import idempotency_key
        assert idempotency_key("quiz_completed", "quiz", "q1") == \
               idempotency_key("quiz_completed", "quiz", "q1")

    def test_differs_across_sources(self):
        from services.xp_service import idempotency_key
        assert idempotency_key("quiz_completed", "quiz", "q1") != \
               idempotency_key("quiz_completed", "quiz", "q2")


class TestAwardXpSafe:
    def test_swallows_errors(self):
        with patch("services.xp_service.award_xp", side_effect=RuntimeError("db down")):
            from services.xp_service import award_xp_safe
            assert award_xp_safe("u1", "quiz_completed", source_type="quiz", source_id="q1") is None
