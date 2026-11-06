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

    def test_expires_after_the_ttl(self, monkeypatch):
        """#771: another worker's update never reaches this process's cache;
        the TTL bounds how long it serves the old context."""
        clock = {"t": 1000.0}
        monkeypatch.setattr(course_context_service.time, "monotonic", lambda: clock["t"])
        with patch("services.course_context_service.table", side_effect=self._ctx_table("v1")):
            course_context_service.get_course_context("o1")
        with patch("services.course_context_service.table", side_effect=self._ctx_table("v2")):
            assert course_context_service.get_course_context("o1")["course_summary"]["summary_text"] == "v1"
            clock["t"] += course_context_service.COURSE_CONTEXT_TTL_S
            assert course_context_service.get_course_context("o1")["course_summary"]["summary_text"] == "v2"

    def _counting_table(self, reads):
        def _table(name):
            m = MagicMock()

            def select(cols, filters=None, **_k):
                oid = (filters or {}).get("offering_id", "")[3:]
                if name == "offering_summary":
                    reads.append(oid)
                    return [{"offering_id": oid, "student_count": 1,
                             "avg_class_mastery": 0.5, "summary_text": oid,
                             "updated_at": "t"}]
                return []
            m.select.side_effect = select
            return m
        return _table

    def test_entries_expire_on_their_own_clock(self, monkeypatch):
        """Review of #786: the TTL was a time-bucket lru_cache key, so EVERY
        entry expired at the same boundary (a refetch herd each minute). Now
        an entry lives one (jittered) TTL from when it was read."""
        clock = {"t": 1000.0}
        monkeypatch.setattr(course_context_service.time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(course_context_service, "_TTL_JITTER", 0.0)
        ttl = course_context_service.COURSE_CONTEXT_TTL_S
        reads: list = []
        with patch("services.course_context_service.table", side_effect=self._counting_table(reads)):
            course_context_service.get_course_context("a")      # read at t=1000
            clock["t"] += ttl / 2
            course_context_service.get_course_context("b")      # read at t=1030
            clock["t"] += ttl / 2 + 1                           # t=1061
            course_context_service.get_course_context("a")      # a expired
            course_context_service.get_course_context("b")      # b still fresh
        assert reads == ["a", "b", "a"]

    def test_expiry_is_jittered_within_the_ttl(self, monkeypatch):
        clock = {"t": 0.0}
        monkeypatch.setattr(course_context_service.time, "monotonic", lambda: clock["t"])
        reads: list = []
        with patch("services.course_context_service.table", side_effect=self._counting_table(reads)):
            for i in range(50):
                course_context_service.get_course_context(f"o{i}")
        ttl = course_context_service.COURSE_CONTEXT_TTL_S
        expiries = {exp for exp, _ in course_context_service._cache.values()}
        assert len(expiries) > 1, "every entry expires at the same instant"
        assert all(ttl * (1 - course_context_service._TTL_JITTER) <= e <= ttl for e in expiries)

    def test_expired_entries_do_not_hold_slots(self, monkeypatch):
        """Dead time buckets used to occupy the LRU's slots; the bound now
        evicts expired entries first, and one offering holds one slot."""
        clock = {"t": 0.0}
        monkeypatch.setattr(course_context_service.time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(course_context_service, "COURSE_CONTEXT_CACHE_MAX", 3)
        ttl = course_context_service.COURSE_CONTEXT_TTL_S
        reads: list = []
        with patch("services.course_context_service.table", side_effect=self._counting_table(reads)):
            for _ in range(5):                       # one offering across 5 TTLs
                course_context_service.get_course_context("hot")
                clock["t"] += ttl + 1
            assert list(course_context_service._cache) == ["hot"]
            course_context_service.get_course_context("x")   # hot is expired now
            course_context_service.get_course_context("y")
            course_context_service.get_course_context("z")   # over the bound
            assert set(course_context_service._cache) == {"x", "y", "z"}
            course_context_service.get_course_context("w")   # LRU goes next
            assert list(course_context_service._cache) == ["y", "z", "w"]

    def test_a_clear_during_a_read_wins(self):
        """A read that began before update_course_context's clear must not
        store its pre-update result after it."""
        def _table(name):
            m = MagicMock()

            def select(cols, filters=None, **_k):
                if name == "offering_summary":
                    course_context_service.clear_course_context_cache()  # lands mid-read
                    return [{"offering_id": "o1", "student_count": 1,
                             "avg_class_mastery": 0.5, "summary_text": "old",
                             "updated_at": "t"}]
                return []
            m.select.side_effect = select
            return m

        with patch("services.course_context_service.table", side_effect=_table):
            assert course_context_service.get_course_context("o1")["course_summary"]["summary_text"] == "old"
        assert "o1" not in course_context_service._cache

    def test_a_failed_read_is_not_cached(self):
        def _boom(name):
            raise RuntimeError("db down")

        with patch("services.course_context_service.table", side_effect=_boom):
            assert course_context_service.get_course_context("o1") == {}
        with patch("services.course_context_service.table", side_effect=self._ctx_table("v1")):
            assert course_context_service.get_course_context("o1")["course_summary"]["summary_text"] == "v1"

    def test_returns_defensive_copy(self):
        with patch("services.course_context_service.table", side_effect=self._ctx_table("v1")):
            a = course_context_service.get_course_context("o1")
            a["course_summary"]["summary_text"] = "MUTATED"
            b = course_context_service.get_course_context("o1")
        assert b["course_summary"]["summary_text"] == "v1"  # cache intact
