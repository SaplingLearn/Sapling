"""Tests for the per-process lru_caches (#98): academics resolvers and
course-context, including the invalidation hook.

The autouse `_clear_lru_caches` fixture in conftest clears these before each
test, so each starts with an empty cache."""
from unittest.mock import MagicMock, patch

from services import academics, course_context_service


class TestOfferingCourseIdCache:
    def test_second_call_served_from_cache(self):
        calls = {"n": 0}

        def _table(name):
            m = MagicMock()
            def _select(*a, **k):
                calls["n"] += 1
                return [{"course_id": "c1"}]
            m.select.side_effect = _select
            return m

        with patch("services.academics.table", side_effect=_table):
            assert academics.offering_course_id("off1") == "c1"
            assert academics.offering_course_id("off1") == "c1"
        assert calls["n"] == 1  # only the first call hit the DB

    def test_distinct_offerings_not_conflated(self):
        def _table(name):
            m = MagicMock()
            def _select(cols, filters=None, **k):
                off = filters["id"].split(".")[-1]
                return [{"course_id": f"c-{off}"}]
            m.select.side_effect = _select
            return m

        with patch("services.academics.table", side_effect=_table):
            assert academics.offering_course_id("A") == "c-A"
            assert academics.offering_course_id("B") == "c-B"


class TestTermForOfferingCache:
    def _table(self, name):
        m = MagicMock()
        if name == "course_offerings":
            m.select.return_value = [{"term_id": "t1"}]
        elif name == "terms":
            m.select.return_value = [{"id": "t1", "name": "Fall 2026"}]
        else:
            m.select.return_value = []
        return m

    def test_returns_defensive_copy(self):
        with patch("services.academics.table", side_effect=self._table):
            t1 = academics.term_for_offering("off1")
            t1["name"] = "MUTATED"          # caller mutates the returned dict
            t2 = academics.term_for_offering("off1")
        assert t2["name"] == "Fall 2026"    # cache not corrupted


class TestCourseContextCacheInvalidation:
    def _ctx_table(self, summary_text):
        def _table(name):
            m = MagicMock()
            if name == "offering_summary":
                m.select.return_value = [{
                    "offering_id": "o1", "student_count": 1,
                    "avg_class_mastery": 0.5, "summary_text": summary_text,
                    "updated_at": "t",
                }]
            else:
                m.select.return_value = []
            return m
        return _table

    def test_cached_until_explicitly_cleared(self):
        with patch("services.course_context_service.table", side_effect=self._ctx_table("v1")):
            c1 = course_context_service.get_course_context("o1")
        assert c1["course_summary"]["summary_text"] == "v1"

        # DB now returns v2, but the cache still serves v1 until cleared.
        with patch("services.course_context_service.table", side_effect=self._ctx_table("v2")):
            cached = course_context_service.get_course_context("o1")
            assert cached["course_summary"]["summary_text"] == "v1"
            course_context_service.clear_course_context_cache()
            fresh = course_context_service.get_course_context("o1")
            assert fresh["course_summary"]["summary_text"] == "v2"

    def test_update_course_context_invalidates(self):
        # Prime the cache with v1.
        with patch("services.course_context_service.table", side_effect=self._ctx_table("v1")):
            course_context_service.get_course_context("o1")

        # update_course_context with no enrollments → purge path → cache_clear.
        def _no_enrollments(name):
            m = MagicMock()
            m.select.return_value = []
            return m
        with patch("services.course_context_service.table", side_effect=_no_enrollments):
            course_context_service.update_course_context("o1")

        # Cache was invalidated, so the next read re-fetches (now v2).
        with patch("services.course_context_service.table", side_effect=self._ctx_table("v2")):
            after = course_context_service.get_course_context("o1")
        assert after["course_summary"]["summary_text"] == "v2"

    def test_returns_defensive_copy(self):
        with patch("services.course_context_service.table", side_effect=self._ctx_table("v1")):
            a = course_context_service.get_course_context("o1")
            a["course_summary"]["summary_text"] = "MUTATED"
            b = course_context_service.get_course_context("o1")
        assert b["course_summary"]["summary_text"] == "v1"  # cache intact
