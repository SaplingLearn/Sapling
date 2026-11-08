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

    def _cas_update(data, filters=None, **_kw):
        # The cache write is a compare-and-set on total_xp (#767): it matches
        # (and returns the row) only while the cache still holds the value the
        # award read. Reads `select.return_value` at call time so tests that
        # swap the cache between awards stay in charge of it.
        current = handles["users"].select.return_value
        if not current:
            return []
        want = (filters or {}).get("total_xp")
        have = current[0].get("total_xp")
        if want is not None and want != ("is.null" if have is None else f"eq.{have}"):
            return []
        return [{**current[0], **data}]

    handles["xp_rules"].select.return_value = rule_rows
    handles["xp_events"].insert.side_effect = insert or _insert
    handles["xp_events"].select_with_count.side_effect = \
        lambda *a, **k: (list(events), len(events))
    handles["users"].select.return_value = user_rows
    handles["users"].update.side_effect = _cas_update
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

    def test_the_ledger_read_keeps_paging_when_the_total_reads_zero(self):
        """PR #589 review E2, in the loop that sets `users.total_xp`.

        `select_with_count` reports `total = 0` for a missing or unparseable
        Content-Range, and every one of these loops stopped on `seen >= count`
        — satisfied immediately, with a full page in hand. Here that writes a
        truncated sum straight into the cache column the leaderboard and the
        hero card read, and nothing afterwards reconciles it against the
        ledger.
        """
        from services.xp_service import _XP_EVENTS_PAGE

        full_page = [{"amount": 1} for _ in range(_XP_EVENTS_PAGE)]
        short_page = [{"amount": 5}]

        tbl, handles = _tables()
        handles["xp_events"].select_with_count.side_effect = [
            (full_page, 0), (short_page, 0),
        ]
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")

        assert result.total_xp == _XP_EVENTS_PAGE + 5, (
            "an unparseable total truncated the ledger sum and wrote it to "
            "users.total_xp"
        )
        assert handles["xp_events"].select_with_count.call_count == 2


def _level(total):
    """A toy curve: one level per 50 XP."""
    return 1 + total // 50


class TestConcurrentAwards:
    """#767: the ledger insert and the users cache write are separate
    statements. The cache write is a compare-and-set on total_xp, so a stale
    sum can never overwrite a newer one and each level-up is reported once."""

    def test_the_cache_write_is_conditioned_on_the_total_it_read(self):
        tbl, handles = _tables(user_rows=[{"total_xp": 40, "level": 1}])
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", side_effect=_level):
            from services.xp_service import award_xp
            award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        filters = handles["users"].update.call_args.kwargs["filters"]
        assert filters == {"id": "eq.u1", "total_xp": "eq.40"}

    def test_a_null_cache_is_matched_with_is_null(self):
        tbl, handles = _tables(user_rows=[{"total_xp": None, "level": None}])
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", side_effect=_level):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        assert result.total_xp == 30
        assert handles["users"].update.call_args.kwargs["filters"]["total_xp"] == "is.null"

    def test_a_concurrent_award_that_already_landed_our_xp_is_not_overwritten(self):
        """We read the cache at 40/L1 and summed the ledger to 70; meanwhile a
        concurrent award (ledger now 70 + 30 = 100) wrote 100/L3 and reported
        the level-up. Our CAS on total_xp=40 must miss, and the retry must find
        the cache already current — no write, no second level-up report, and
        the cache never regresses to 70."""
        tbl, handles = _tables(user_rows=[{"total_xp": 40, "level": 1}])
        cas = handles["users"].update.side_effect
        state = {"raced": False}

        def racing_update(data, filters=None, **kw):
            if not state["raced"]:
                state["raced"] = True
                # The competitor's ledger row and its cache write land first.
                handles["xp_events"].insert.side_effect({"amount": 30})
                handles["users"].select.return_value = [{"total_xp": 100, "level": 3}]
            return cas(data, filters=filters, **kw)
        handles["users"].update.side_effect = racing_update

        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", side_effect=_level):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")

        assert handles["users"].update.call_count == 1      # only the lost CAS
        assert handles["users"].select.return_value == [{"total_xp": 100, "level": 3}]
        assert (result.total_xp, result.level) == (100, 3)
        assert result.leveled_up is False                   # the competitor reported it

    def test_a_lost_cas_retries_from_the_new_cache_and_reports_its_own_level_up(self):
        """The competitor wrote a cache that does NOT yet include our XP. Our
        retry CASes from the competitor's state, and the level-up our XP
        causes is ours to report."""
        tbl, handles = _tables(user_rows=[{"total_xp": 0, "level": 1}], ledger=[10])
        cas = handles["users"].update.side_effect
        state = {"raced": False}

        def racing_update(data, filters=None, **kw):
            if not state["raced"]:
                state["raced"] = True
                # A competitor's cache write (its own sum: 10, pre-our-row).
                handles["users"].select.return_value = [{"total_xp": 10, "level": 1}]
            result = cas(data, filters=filters, **kw)
            if result:
                handles["users"].select.return_value = [result[0]]
            return result
        handles["users"].update.side_effect = racing_update

        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", side_effect=_level):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1",
                              amount=45)

        assert handles["users"].update.call_count == 2
        assert handles["users"].update.call_args.kwargs["filters"]["total_xp"] == "eq.10"
        assert (result.total_xp, result.level, result.leveled_up) == (55, 2, True)

    def test_endless_contention_gives_up_without_raising(self):
        from services.xp_service import _CACHE_CAS_ATTEMPTS
        tbl, handles = _tables(user_rows=[{"total_xp": 0, "level": 1}])
        handles["users"].update.side_effect = lambda *a, **k: []
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", side_effect=_level):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        assert handles["users"].update.call_count == _CACHE_CAS_ATTEMPTS
        assert result.awarded == 30
        assert result.leveled_up is False


class TestRecordLedgerRow:
    def test_writes_the_supplied_created_at(self):
        tbl, handles = _tables()
        with patch("services.xp_service.table", side_effect=tbl):
            from services.xp_service import record_ledger_row
            assert record_ledger_row(
                "u1", "achievement_unlocked", source_type="achievement",
                source_id="a1", amount=50, created_at="2026-09-01T00:00:00+00:00",
            ) is True
        row = handles["xp_events"].insert.call_args[0][0]
        assert row["created_at"] == "2026-09-01T00:00:00+00:00"
        assert row["idempotency_key"] == "achievement_unlocked:achievement:a1"

    def test_omits_created_at_so_the_default_stamps_it(self):
        tbl, handles = _tables()
        with patch("services.xp_service.table", side_effect=tbl):
            from services.xp_service import record_ledger_row
            record_ledger_row("u1", "quiz_completed", source_type="quiz",
                              source_id="q1", amount=30)
        assert "created_at" not in handles["xp_events"].insert.call_args[0][0]

    def test_a_conflict_is_false_not_an_error(self):
        response = MagicMock(status_code=409)

        def _conflict(_data):
            raise httpx.HTTPStatusError("dup", request=MagicMock(), response=response)
        tbl, _ = _tables(insert=_conflict)
        with patch("services.xp_service.table", side_effect=tbl):
            from services.xp_service import record_ledger_row
            assert record_ledger_row("u1", "quiz_completed", source_type="quiz",
                                     source_id="q1", amount=30) is False


class TestSettleLedgerWrites:
    def test_refreshes_once_then_dispatches_with_the_level_up(self):
        with patch("services.xp_service._refresh_cache", return_value=(500, 3, True)) as r, \
             patch("services.xp_service._dispatch_xp_achievements") as d:
            from services.xp_service import settle_ledger_writes
            assert settle_ledger_writes("u1") == (500, 3, True)
        r.assert_called_once_with("u1")
        d.assert_called_once_with("u1", leveled_up=True)
