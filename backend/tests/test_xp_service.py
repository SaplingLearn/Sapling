"""Unit tests for services/xp_service.py."""
import pytest
from unittest.mock import MagicMock, patch

import httpx

RULE = [{"key": "quiz_completed", "label": "Completed a quiz", "amount": 30, "enabled": True}]


def _tables(rule_rows=RULE, user_rows=None, insert=None, ledger=None):
    """Build a `table` stub that dispatches on table name.

    xp_events is a real in-memory ledger rather than a bare MagicMock:
    award_xp recomputes users.total_xp by summing the ledger (it must not
    do `prev_total + value` — see TestLedgerRecompute), so the stub has to
    reflect what was actually inserted. By default the ledger is seeded to
    agree with users.total_xp; pass `ledger` (a list of amounts) to model a
    cache that has drifted from the ledger.
    """
    user_rows = user_rows if user_rows is not None else [{"total_xp": 0, "level": 1}]
    if ledger is None:
        seed = int((user_rows[0].get("total_xp") or 0)) if user_rows else 0
        ledger = [seed] if seed else []
    events = [{"amount": a} for a in ledger]

    handles = {
        "xp_rules": MagicMock(),
        "xp_events": MagicMock(),
        "users": MagicMock(),
    }

    def _insert(data):
        events.append({"amount": data["amount"]})
        return [data]

    handles["xp_rules"].select.return_value = rule_rows
    handles["xp_events"].insert.side_effect = insert or _insert
    handles["xp_events"].select_with_count.side_effect = \
        lambda *a, **k: (list(events), len(events))
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


class TestLedgerRecompute:
    """users.total_xp / users.level are a CACHE of the append-only xp_events
    ledger. Deriving them as `prev_total + value` makes them lossy: two
    concurrent awards both read the same prev_total and the second UPDATE
    clobbers the first, permanently, with no reconciler anywhere. It is also
    user-visible — /activity and the xp_in_day / goal_streak achievement
    triggers sum xp_events directly while /me and the leaderboard read the
    cache, so a user sees an activity chart totalling more XP than their hero
    card claims. Recompute from the ledger instead: the cache then self-heals
    on the very next award."""

    def test_two_sequential_awards_land_at_the_ledger_sum(self):
        tbl, handles = _tables()
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1):
            from services.xp_service import award_xp
            first = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
            # Simulate the cache the first award wrote being what the second
            # award reads (the normal, uncontended case).
            handles["users"].select.return_value = [
                {"total_xp": first.total_xp, "level": 1}
            ]
            second = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q2")

        assert first.total_xp == 30
        assert second.total_xp == 60
        assert handles["users"].update.call_args[0][0]["total_xp"] == 60

    def test_a_lost_update_heals_on_the_next_award(self):
        """The cache says 0 but the ledger holds 100 — exactly the state a
        lost update leaves behind. The next award must land on 130 (the true
        ledger sum), not 30 (`stale prev_total + value`)."""
        tbl, handles = _tables(user_rows=[{"total_xp": 0, "level": 1}],
                               ledger=[100])
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")

        assert result.total_xp == 130
        assert handles["users"].update.call_args[0][0]["total_xp"] == 130

    def test_the_ledger_read_is_scoped_to_the_user(self):
        tbl, handles = _tables()
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1):
            from services.xp_service import award_xp
            award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        filters = handles["xp_events"].select_with_count.call_args.kwargs["filters"]
        assert filters == {"user_id": "eq.u1"}

    def test_the_ledger_read_pages_past_postgrest_max_rows(self):
        """PostgREST caps a single response at max_rows (1000) and signals the
        cut with 206 Partial Content — a 2xx, so raise_for_status never fires
        and the truncation is silent. A heavy user's ledger crossing that cap
        must not silently reset their total_xp to the first page's sum."""
        from services.xp_service import _XP_EVENTS_PAGE

        full_page = [{"amount": 1} for _ in range(_XP_EVENTS_PAGE)]
        short_page = [{"amount": 5}]
        total = len(full_page) + len(short_page)

        tbl, handles = _tables()
        handles["xp_events"].select_with_count.side_effect = [
            (full_page, total), (short_page, total),
        ]
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")

        assert result.total_xp == _XP_EVENTS_PAGE + 5
        assert handles["xp_events"].select_with_count.call_count == 2
        calls = handles["xp_events"].select_with_count.call_args_list
        assert calls[0].kwargs["offset"] == 0
        assert calls[1].kwargs["offset"] == _XP_EVENTS_PAGE
