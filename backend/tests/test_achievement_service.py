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
from datetime import datetime, timezone


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
                def track_insert(data, **_kw):
                    insert_calls.append(data)
                    return [{}]
                m.upsert.side_effect = track_insert
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
            rows = [
                {"amount": 200, "created_at": "2026-07-01T09:00:00+00:00"},
                {"amount": 150, "created_at": "2026-07-01T20:00:00+00:00"},
                {"amount": 300, "created_at": "2026-07-02T09:00:00+00:00"},
            ]
            t.return_value.select_with_count.return_value = (rows, len(rows))
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "xp_in_day") == 350

    def test_session_before_hour_reports_the_earliest_finish_hour(self):
        """session_before_hour is LOWER_IS_BETTER: it reports the earliest UTC
        hour a session finished at, so the trigger_threshold stays the literal
        hour in the badge text ('before 7am' = 7)."""
        from services.achievement_service import NO_QUALIFYING_VALUE, _session_stat

        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [
                {"started_at": "2026-07-01T04:00:00+00:00", "ended_at": "2026-07-01T05:00:00+00:00"},
                {"started_at": "2026-07-02T12:00:00+00:00", "ended_at": "2026-07-02T13:00:00+00:00"},
            ]
            # The earliest finish wins, not the latest.
            assert _session_stat("u1", "session_before_hour") == 5

        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [
                {"started_at": "2026-07-01T12:00:00+00:00", "ended_at": "2026-07-01T13:00:00+00:00"},
            ]
            assert _session_stat("u1", "session_before_hour") == 13

        # No finished session at all must never qualify.
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [
                {"started_at": "2026-07-01T04:00:00+00:00", "ended_at": None},
            ]
            assert _session_stat("u1", "session_before_hour") == NO_QUALIFYING_VALUE

    def test_late_morning_session_does_not_earn_early_bird(self):
        """Regression: the old `24 - hour` encoding scored an 11:00 finish as
        13, which cleared early-bird's threshold of 7 — so "finish a study
        session before 7am" was granted for finishing at lunchtime. Anything
        at or after the threshold hour must not qualify; 06:00 still must."""
        from services import achievement_service

        def run(end_hour: str) -> list:
            def table_side_effect(name):
                m = MagicMock()
                if name == "achievement_triggers":
                    m.select.return_value = [{
                        "id": "t1", "achievement_id": "a1",
                        "trigger_type": "session_before_hour", "trigger_threshold": 7,
                    }]
                elif name == "user_achievements":
                    m.select.return_value = []
                elif name == "sessions":
                    m.select.return_value = [{
                        "started_at": f"2026-07-01T0{0}:00:00+00:00",
                        "ended_at": f"2026-07-01T{end_hour}:00:00+00:00",
                    }]
                elif name == "achievements":
                    m.select.return_value = [{
                        "slug": "early-bird", "name": "Early Bird",
                        "xp_reward": 60, "status": "live",
                    }]
                elif name == "achievement_cosmetics":
                    m.select.return_value = []
                return m

            with patch.object(achievement_service, "table", side_effect=table_side_effect), \
                 patch.object(achievement_service, "award_xp_safe"):
                return achievement_service.check_achievements("u1", "session_before_hour", {})

        assert run("11") == []          # 11:00 — the bug: used to be granted
        assert run("07") == []          # 07:00 — the boundary, "before 7" is exclusive
        assert [a["slug"] for a in run("06")] == ["early-bird"]

    def test_course_grade_a_counts_enrollments_computing_to_an_a(self):
        # e1 grades to 95% (an A); e2 grades to 70% (a C-). Each enrollment
        # triggers its own table("assignments") call, in enrollment order, so
        # a plain call counter (not a fresh side_effect per `table()` call)
        # is what lets the two enrollments see different assignment rows.
        assignments_by_call = [
            [{"id": "a1", "category_id": "c1", "points_possible": "100", "points_earned": "95"}],
            [{"id": "a2", "category_id": "c1", "points_possible": "100", "points_earned": "70"}],
        ]
        calls = {"assignments": 0}

        def table_side_effect(name):
            m = MagicMock()
            if name == "enrollments":
                m.select.return_value = [
                    {"id": "e1", "letter_scale": None, "curve_mode": "raw",
                     "curve_avg_target": None, "curve_sd_delta": None},
                    {"id": "e2", "letter_scale": None, "curve_mode": "raw",
                     "curve_avg_target": None, "curve_sd_delta": None},
                ]
            elif name == "gradebook_categories":
                m.select.return_value = [
                    {"id": "c1", "name": "Exams", "weight": 100, "sort_order": 0, "drop_lowest": 0},
                ]
            elif name == "assignments":
                idx = calls["assignments"]
                calls["assignments"] += 1
                m.select.return_value = assignments_by_call[idx]
            else:
                m.select.return_value = []
            return m

        with patch("services.achievement_service.table", side_effect=table_side_effect):
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "course_grade_a") == 1


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
        t.return_value.upsert.assert_not_called()
        award.assert_not_called()


class _GrantWorld:
    """In-memory tables for the grant pipeline (#767). `user_achievements` and
    `user_cosmetics` honour their PKs the way PostgREST's
    `resolution=ignore-duplicates` does: a conflicting row returns [] and is
    not written. A plain `insert` on a conflict raises, as the real one did."""

    def __init__(self, *, triggers, badges, links=(), earned=(), owned=(),
                 paid=(), stat_rows=None, fail_cosmetics=False):
        self.triggers = list(triggers)
        self.badges = {b["id"]: b for b in badges}
        self.links = list(links)
        self.earned = set(earned)
        self.owned = set(owned)
        self.paid = set(paid)
        self.stat_rows = stat_rows if stat_rows is not None else [{"user_id": "u1"}] * 5
        self.fail_cosmetics = fail_cosmetics
        self.achievement_upserts = []
        self.cosmetic_upserts = []

    @staticmethod
    def _in(filters, col):
        raw = (filters or {}).get(col, "")
        if raw.startswith("in.("):
            return set(raw[4:-1].split(","))
        if raw.startswith("eq."):
            return {raw[3:]}
        return None

    def table(self, name):
        m = MagicMock()
        world = self

        if name == "achievement_triggers":
            m.select.return_value = self.triggers
        elif name == "user_achievements":
            m.select.side_effect = lambda *a, **k: [
                {"achievement_id": a_id} for a_id in world.earned
            ]

            def _upsert(row, **kw):
                assert kw.get("on_conflict") == "user_id,achievement_id"
                assert kw.get("ignore_duplicates") is True
                world.achievement_upserts.append(row["achievement_id"])
                if row["achievement_id"] in world.earned:
                    return []
                world.earned.add(row["achievement_id"])
                return [row]

            def _insert(row):
                if row["achievement_id"] in world.earned:
                    raise RuntimeError("409 duplicate key")
                world.earned.add(row["achievement_id"])
                return [row]
            m.upsert.side_effect = _upsert
            m.insert.side_effect = _insert
        elif name == "achievements":
            def _select(columns="*", filters=None, **kw):
                ids = world._in(filters, "id")
                return [dict(b) for i, b in world.badges.items() if ids is None or i in ids]
            m.select.side_effect = _select
        elif name == "achievement_cosmetics":
            def _select(columns="*", filters=None, **kw):
                ids = world._in(filters, "achievement_id")
                return [dict(lc) for lc in world.links if ids is None or lc["achievement_id"] in ids]
            m.select.side_effect = _select
        elif name == "user_cosmetics":
            m.select.side_effect = lambda *a, **k: [{"cosmetic_id": c} for c in world.owned]

            def _upsert(row, **kw):
                if world.fail_cosmetics:
                    raise RuntimeError("pg down")
                assert kw.get("on_conflict") == "user_id,cosmetic_id"
                assert kw.get("ignore_duplicates") is True
                world.cosmetic_upserts.append(row["cosmetic_id"])
                if row["cosmetic_id"] in world.owned:
                    return []
                world.owned.add(row["cosmetic_id"])
                return [row]
            m.upsert.side_effect = _upsert
        elif name == "xp_events":
            def _select(columns="*", filters=None, **kw):
                ids = world._in(filters, "source_id")
                return [{"source_id": s} for s in world.paid if ids is None or s in ids]
            m.select.side_effect = _select
        else:
            m.select.return_value = self.stat_rows
        return m

    def award(self, user_id, rule_key, *, source_type, source_id, amount):
        self.paid.add(source_id)


def _badge(i, *, reward=0, status="live"):
    return {"id": i, "slug": i, "name": i.upper(), "xp_reward": reward, "status": status}


def _trigger(achievement_id, threshold=1, tid=None):
    return {"id": tid or f"t-{achievement_id}", "achievement_id": achievement_id,
            "trigger_type": "session_count", "trigger_threshold": threshold}


def _run(world, event="session_count"):
    award = MagicMock(side_effect=world.award)
    with patch("services.achievement_service.table", side_effect=world.table), \
         patch("services.achievement_service.award_xp_safe", award):
        from services.achievement_service import check_achievements
        return check_achievements("u1", event, {}), award


class TestGrantPipelineIsIdempotent:
    def test_two_triggers_for_one_badge_grant_it_once_and_keep_going(self):
        """Two triggers for one badge used to INSERT twice: the second raised
        on the PK and aborted every grant after it in the loop."""
        world = _GrantWorld(
            triggers=[_trigger("a1", 1, "t1"), _trigger("a1", 2, "t2"), _trigger("a2", 1)],
            badges=[_badge("a1"), _badge("a2")],
        )
        earned, _ = _run(world)
        assert [e["slug"] for e in earned] == ["a1", "a2"]
        assert world.achievement_upserts == ["a1", "a2"]

    def test_a_badge_a_concurrent_check_already_granted_is_not_reported_twice(self):
        """The race: our existence read said 'not earned', then a concurrent
        check inserted first. ON CONFLICT DO NOTHING → no exception, no second
        toast, but the reward is still (idempotently) ensured."""
        world = _GrantWorld(triggers=[_trigger("a1")], badges=[_badge("a1", reward=50)])
        real_table = world.table

        def racing_table(name):
            m = real_table(name)
            if name == "user_achievements":
                m.select.side_effect = lambda *a, **k: []   # stale read
                world.earned.add("a1")                      # the winner's row
            return m
        world.table = racing_table
        earned, award = _run(world)
        assert earned == []
        award.assert_called_once()

    def test_a_cosmetics_failure_does_not_abort_later_badges(self):
        world = _GrantWorld(
            triggers=[_trigger("a1"), _trigger("a2")],
            badges=[_badge("a1"), _badge("a2")],
            links=[{"achievement_id": "a1", "cosmetic_id": "c1"}],
            fail_cosmetics=True,
        )
        earned, _ = _run(world)
        assert [e["slug"] for e in earned] == ["a1", "a2"]


class TestGrantPipelineSelfHeals:
    def test_unpaid_xp_of_an_earned_badge_is_paid_on_a_later_check(self):
        world = _GrantWorld(
            triggers=[_trigger("a1")], badges=[_badge("a1", reward=120)], earned={"a1"},
        )
        earned, award = _run(world)
        assert earned == []
        award.assert_called_once_with(
            "u1", "achievement_unlocked", source_type="achievement",
            source_id="a1", amount=120,
        )

    def test_a_paid_badge_is_not_paid_again(self):
        world = _GrantWorld(
            triggers=[_trigger("a1")], badges=[_badge("a1", reward=120)],
            earned={"a1"}, paid={"a1"},
        )
        _, award = _run(world)
        award.assert_not_called()

    def test_a_missing_cosmetic_of_an_earned_badge_is_unlocked(self):
        world = _GrantWorld(
            triggers=[_trigger("a1")], badges=[_badge("a1")], earned={"a1"},
            links=[{"achievement_id": "a1", "cosmetic_id": "c1"},
                   {"achievement_id": "a1", "cosmetic_id": "c2"}],
            owned={"c2"},
        )
        _run(world)
        assert world.cosmetic_upserts == ["c1"]
        assert world.owned == {"c1", "c2"}

    def test_a_fully_granted_badge_writes_nothing(self):
        world = _GrantWorld(
            triggers=[_trigger("a1")], badges=[_badge("a1", reward=10)], earned={"a1"},
            paid={"a1"}, links=[{"achievement_id": "a1", "cosmetic_id": "c1"}], owned={"c1"},
        )
        _, award = _run(world)
        award.assert_not_called()
        assert world.cosmetic_upserts == []

    def test_a_draft_badge_is_not_healed(self):
        """live→draft keeps the grant row but hides it; it pays nothing more."""
        world = _GrantWorld(
            triggers=[_trigger("a1")], badges=[_badge("a1", reward=50, status="draft")],
            earned={"a1"}, links=[{"achievement_id": "a1", "cosmetic_id": "c1"}],
        )
        _, award = _run(world)
        award.assert_not_called()
        assert world.cosmetic_upserts == []

    def test_a_heal_failure_never_blocks_the_check(self):
        world = _GrantWorld(
            triggers=[_trigger("a1"), _trigger("a2")],
            badges=[_badge("a1", reward=5), _badge("a2")], earned={"a1"},
        )
        real_table = world.table

        def broken_xp(name):
            if name == "xp_events":
                raise RuntimeError("pg down")
            return real_table(name)
        world.table = broken_xp
        earned, _ = _run(world)
        assert [e["slug"] for e in earned] == ["a2"]


class TestGrantLinkedCosmeticsIsIdempotent:
    def test_an_already_owned_cosmetic_is_a_no_op_not_an_error(self):
        world = _GrantWorld(
            triggers=[], badges=[_badge("a1")],
            links=[{"achievement_id": "a1", "cosmetic_id": "c1"},
                   {"achievement_id": "a1", "cosmetic_id": "c2"}],
            owned={"c1"},
        )
        with patch("services.achievement_service.table", side_effect=world.table):
            from services.achievement_service import grant_linked_cosmetics
            grant_linked_cosmetics("u1", "a1")
            grant_linked_cosmetics("u1", "a1")
        assert world.owned == {"c1", "c2"}


class TestGoalStreakClamp:
    def test_non_positive_stored_goal_still_terminates(self):
        """daily_goal_xp has no CHECK enforcing positivity (0043-gamification.sql).
        A stored goal of 0 or less would make `0 >= goal` trivially true for
        every day with no XP events, so the backwards day-walk in _goal_streak
        would never stop. This pins the max(goal, 1) clamp: with a -1 stored
        goal and one day of real XP, the streak must still come back finite."""
        today = datetime.now(timezone.utc).date().isoformat()

        def table_side_effect(name):
            m = MagicMock()
            if name == "users":
                m.select.return_value = [{"daily_goal_xp": -1}]
            elif name == "xp_events":
                rows = [{"amount": 10, "created_at": f"{today}T09:00:00+00:00"}]
                m.select_with_count.return_value = (rows, len(rows))
            else:
                m.select.return_value = []
                m.select_with_count.return_value = ([], 0)
            return m

        with patch("services.achievement_service.table", side_effect=table_side_effect):
            from services.achievement_service import _goal_streak
            assert _goal_streak("u1") == 1


class TestDailyTotalsPaging:
    """`_daily_totals` backs xp_in_day (golden-hour) and goal_streak
    (perfect-week), and since the last wave `award_xp` dispatches xp_in_day on
    EVERY award — so this is a hot path over the whole xp_events ledger.

    PostgREST caps a response at `max_rows = 1000` (supabase/config.toml) and
    signals the truncation with 206 Partial Content — a 2xx, so
    db/connection.py's raise_for_status() never fires. An unpaginated select
    therefore silently sees only the first page: past ~1000 lifetime events a
    user's best-XP day and goal streak are computed over an arbitrary subset,
    making golden-hour unearnable and spuriously resetting perfect-week.
    """

    def _paged(self, pages):
        """Stub select_with_count to return `pages` in order, each with the
        exact same grand total, the way PostgREST's count=exact header does."""
        total = sum(len(p) for p in pages)
        handle = MagicMock()
        handle.select_with_count.side_effect = [(p, total) for p in pages]
        return handle, total

    def test_daily_totals_accumulates_every_page(self):
        """A full page followed by a short page: both must be summed. Fails if
        only the first page is taken."""
        from services.achievement_service import _XP_EVENTS_PAGE, _daily_totals

        day = "2026-07-30"
        first = [
            {"amount": 1, "created_at": f"{day}T09:00:00+00:00"}
            for _ in range(_XP_EVENTS_PAGE)
        ]
        second = [{"amount": 1, "created_at": f"{day}T10:00:00+00:00"} for _ in range(5)]
        handle, total = self._paged([first, second])

        with patch("services.achievement_service.table", return_value=handle):
            totals = _daily_totals("u1")

        assert totals == {day: total}
        assert handle.select_with_count.call_count == 2
        first_call, second_call = handle.select_with_count.call_args_list
        assert first_call.kwargs["offset"] == 0
        assert second_call.kwargs["offset"] == _XP_EVENTS_PAGE

    def test_daily_totals_keeps_paging_when_the_total_reads_zero(self):
        """PR #589 review E2, in the third copy of the same loop.

        `_paged` above always states a truthful total, so it only proved the
        loop CAN take a second lap. `select_with_count` reports `total = 0`
        for a missing or unparseable Content-Range, and `seen >= count` then
        holds on lap one holding a completely full page — golden-hour becomes
        unearnable and perfect-week resets, silently, on a 2xx.
        """
        from services.achievement_service import _XP_EVENTS_PAGE, _daily_totals

        day = "2026-07-30"
        first = [
            {"amount": 1, "created_at": f"{day}T09:00:00+00:00"}
            for _ in range(_XP_EVENTS_PAGE)
        ]
        second = [{"amount": 1, "created_at": f"{day}T10:00:00+00:00"} for _ in range(5)]
        handle = MagicMock()
        handle.select_with_count.side_effect = [(first, 0), (second, 0)]

        with patch("services.achievement_service.table", return_value=handle):
            totals = _daily_totals("u1")

        assert totals == {day: _XP_EVENTS_PAGE + 5}, (
            "an unparseable total truncated the ledger scan to page one"
        )
        assert handle.select_with_count.call_count == 2

    def test_paging_is_deterministically_ordered(self):
        """Without a stable sort, offset paging can skip or duplicate rows
        across the page boundary — same reasoning as xp_service._ledger_total."""
        from services.achievement_service import _XP_EVENTS_PAGE, _daily_totals

        handle, _ = self._paged([[]])
        with patch("services.achievement_service.table", return_value=handle):
            _daily_totals("u1")
        kwargs = handle.select_with_count.call_args.kwargs
        assert kwargs["order"] == "created_at.asc,id.asc"
        assert kwargs["limit"] == _XP_EVENTS_PAGE
        assert kwargs["filters"] == {"user_id": "eq.u1"}

    def test_best_day_xp_sees_events_past_the_first_page(self):
        """golden-hour is `xp_in_day >= 500`. The qualifying day sitting on the
        second page must still be the reported max — truncation here makes the
        badge unearnable for any user with a long ledger."""
        from services.achievement_service import _XP_EVENTS_PAGE, _get_user_stat

        # Spread the first page over ten days so no single day on it reaches
        # 500 — the only qualifying day is the one on the second page.
        first = [
            {"amount": 1, "created_at": f"2026-07-{1 + i % 10:02d}T09:00:00+00:00"}
            for i in range(_XP_EVENTS_PAGE)
        ]
        second = [{"amount": 500, "created_at": "2026-07-30T09:00:00+00:00"}]
        handle, _ = self._paged([first, second])

        with patch("services.achievement_service.table", return_value=handle):
            assert _get_user_stat("u1", "xp_in_day") == 500


class TestCountRowsSelectsAnExistingColumn:
    """_count_rows must not ask PostgREST for a column the table lacks.

    Every other test in this file replaces `table` with a bare MagicMock, so
    the requested column is never checked against anything — which is exactly
    how `_count_rows` shipped selecting `id` from two junction tables that have
    no `id` column. These tests give the fake a real column set so a bad
    projection fails the way PostgREST would.

    Column sets below are transcribed from the migrations:
      room_members  PRIMARY KEY (room_id, user_id)   0001_baseline_schema.sql
      friendships   PRIMARY KEY (user_id, friend_id) 20260731193214_gamification.sql
    """

    # PostgREST's error for an unknown column.
    COLUMNS = {
        "room_members": {"room_id", "user_id", "joined_at"},
        "friendships": {"user_id", "friend_id", "created_at"},
    }

    def _schema_aware_table(self):
        def _table(name):
            handle = MagicMock()

            def _select(columns, filters=None, **kwargs):
                known = self.COLUMNS[name]
                for col in columns.split(","):
                    if col.strip() not in known:
                        raise RuntimeError(
                            f'42703: column {name}.{col.strip()} does not exist'
                        )
                return [{"user_id": "u2"}, {"user_id": "u3"}]

            handle.select.side_effect = _select
            return handle

        return _table

    def test_rooms_joined_does_not_ask_for_a_nonexistent_id_column(self):
        from services.achievement_service import _get_user_stat
        with patch("services.achievement_service.table", self._schema_aware_table()):
            assert _get_user_stat("u1", "rooms_joined") == 2

    def test_friends_count_does_not_ask_for_a_nonexistent_id_column(self):
        from services.achievement_service import _get_user_stat
        with patch("services.achievement_service.table", self._schema_aware_table()):
            assert _get_user_stat("u1", "friends_count") == 2

    def test_owned_room_members_counts_members_of_each_owned_room(self):
        """The rooms lookup DOES select `id` — rooms has one. Only the
        room_members count must avoid it."""
        from services.achievement_service import _get_user_stat

        def _table(name):
            handle = MagicMock()
            if name == "rooms":
                handle.select.return_value = [{"id": "r1"}]
                return handle

            def _select(columns, filters=None, **kwargs):
                for col in columns.split(","):
                    if col.strip() not in self.COLUMNS["room_members"]:
                        raise RuntimeError(
                            f"42703: column room_members.{col.strip()} does not exist"
                        )
                return [{"user_id": f"u{i}"} for i in range(5)]

            handle.select.side_effect = _select
            return handle

        with patch("services.achievement_service.table", _table):
            assert _get_user_stat("u1", "owned_room_members") == 5
