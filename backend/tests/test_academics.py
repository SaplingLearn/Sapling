"""Tests for services/academics.py — the term/offering/enrollment resolver
that the academics-split code slice is built on.

Each test patches `services.academics.table` with a factory that returns a
MagicMock per table name, seeded with canned `.select()` rows and recording
`.insert()` calls — the same hermetic pattern the rest of the suite uses.
"""
from unittest.mock import MagicMock, patch

import httpx
import pytest

import services.academics as ac


def _factory(rows_by_table, recorder=None, select_seqs=None, counts=None):
    """Return a `table(name)` stand-in, caching one mock per table name so that
    repeated `table(name)` calls share `.select` side-effect sequencing (the
    helper queries some tables twice: a primary query then a fallback).

    - `rows_by_table[name]` seeds a constant `.select()` return.
    - `select_seqs[name]` (optional) seeds an ordered list of `.select()` results
      for tables queried more than once.
    - `counts[name]` (optional) overrides the `select_with_count` total, to
      simulate a read that overran its cap.
    - `.insert()` echoes its payload and records it.
    """
    cache: dict = {}
    select_seqs = select_seqs or {}

    def make(name):
        if name in cache:
            return cache[name]
        m = MagicMock(name=f"table({name})")
        if name in select_seqs:
            m.select.side_effect = list(select_seqs[name])
        else:
            m.select.return_value = rows_by_table.get(name, [])
        # `select_with_count` seeded from the same rows, with an exact count —
        # the offering read uses it to tell a complete list from a truncated
        # one. `counts[name]` overrides the total to simulate truncation.
        _rows = rows_by_table.get(name, [])
        m.select_with_count.return_value = (
            _rows, (counts or {}).get(name, len(_rows)),
        )

        def _insert(data):
            if recorder is not None:
                recorder.append((name, data))
            return [data]

        m.insert.side_effect = _insert
        cache[name] = m
        return m
    return make


# ── current_term ──────────────────────────────────────────────────────────

def test_current_term_returns_row_in_range():
    rows = {"terms": [{"id": "t-spring", "label": "Spring 2026", "sort_key": 20261}]}
    with patch.object(ac, "table", side_effect=_factory(rows)):
        assert ac.current_term()["id"] == "t-spring"


def test_current_term_falls_back_to_latest_when_no_range_matches():
    # First select (range query) returns []; the fallback select returns the latest.
    factory = _factory({}, select_seqs={"terms": [
        [],  # range query: nothing contains today
        [{"id": "t-summer", "label": "Summer 2026", "sort_key": 20262}],  # latest
    ]})
    with patch.object(ac, "table", side_effect=factory):
        assert ac.current_term()["id"] == "t-summer"


def test_current_term_none_when_no_terms():
    with patch.object(ac, "table", side_effect=_factory({"terms": []})):
        assert ac.current_term() is None


# ── resolve_offering ────────────────────────────────────────────────────────

def test_resolve_offering_returns_existing():
    rows = {
        "terms": [{"id": "t1", "label": "Spring 2026", "sort_key": 20261}],
        "course_offerings": [{"id": "off-1"}],
    }
    with patch.object(ac, "table", side_effect=_factory(rows)):
        assert ac.resolve_offering("course-1") == "off-1"


def test_resolve_offering_creates_when_missing_and_create_true():
    recorder = []
    rows = {"terms": [{"id": "t1", "label": "Spring 2026", "sort_key": 20261}],
            "course_offerings": []}
    with patch.object(ac, "table", side_effect=_factory(rows, recorder)):
        off_id = ac.resolve_offering("course-1", term_id="t1", create=True)
    assert off_id  # a fresh uuid
    assert recorder, "should have inserted an offering"
    name, payload = recorder[0]
    assert name == "course_offerings"
    assert payload["course_id"] == "course-1"
    assert payload["term_id"] == "t1"
    assert payload["id"] == off_id


def _conflict_error() -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://test/course_offerings")
    return httpx.HTTPStatusError(
        "conflict", request=req, response=httpx.Response(409, request=req)
    )


def test_resolve_offering_create_conflict_reselects_winner():
    """Losing the create race to the 0036 partial unique index re-selects the
    now-existing offering and returns it instead of raising."""
    factory = _factory(
        {"terms": [{"id": "t1", "sort_key": 1}]},
        # pre-insert term lookup misses, post-conflict re-select finds the winner
        select_seqs={"course_offerings": [[], [{"id": "off-winner"}]]},
    )
    cache: dict = {}

    def make(name):
        m = cache.get(name) or factory(name)
        cache[name] = m
        if name == "course_offerings":
            m.insert.side_effect = _conflict_error()
        return m

    with patch.object(ac, "table", side_effect=make):
        assert ac.resolve_offering("course-1", term_id="t1", create=True) == "off-winner"


def test_resolve_offering_conflict_reselect_uses_the_same_order():
    """The 409 re-select must sort like the steady-state read 20 lines above it.

    It is the one path that can return a row the non-racing reader would not: the
    sections of a course are written by one batch insert, so `created_at.asc` alone
    ties and the winner is the planner's.
    """
    factory = _factory(
        {"terms": [{"id": "t1", "sort_key": 1}]},
        select_seqs={"course_offerings": [[], [{"id": "off-winner"}]]},
    )
    cache: dict = {}

    def make(name):
        m = cache.get(name) or factory(name)
        cache[name] = m
        if name == "course_offerings":
            m.insert.side_effect = _conflict_error()
        return m

    with patch.object(ac, "table", side_effect=make):
        ac.resolve_offering("course-1", term_id="t1", create=True)
    order = cache["course_offerings"].select.call_args_list[-1].kwargs["order"]
    assert order == "section.asc,created_at.asc", f"re-select must match, got {order!r}"


def test_resolve_offering_create_non_conflict_error_propagates():
    """Only 409 means 'someone else created it' — other HTTP errors re-raise."""
    req = httpx.Request("POST", "http://test/course_offerings")
    err = httpx.HTTPStatusError(
        "boom", request=req, response=httpx.Response(500, request=req)
    )
    factory = _factory({"terms": [{"id": "t1", "sort_key": 1}], "course_offerings": []})
    cache: dict = {}

    def make(name):
        m = cache.get(name) or factory(name)
        cache[name] = m
        if name == "course_offerings":
            m.insert.side_effect = err
        return m

    with patch.object(ac, "table", side_effect=make):
        with pytest.raises(httpx.HTTPStatusError):
            ac.resolve_offering("course-1", term_id="t1", create=True)


def test_resolve_offering_orders_by_section_for_determinism():
    """Since #280 a course has one offering per section, all written by one batch
    insert — so they share a created_at and `created_at.asc` alone leaves the
    winner to the planner. Ordering by section first makes the pick stable, so a
    user's documents/notes can't drift between sections across calls.
    """
    factory = _factory(
        {
            "terms": [{"id": "t1", "label": "Fall 2026", "sort_key": 20263}],
            "course_offerings": [{"id": "off-a1"}],
        }
    )
    with patch.object(ac, "table", side_effect=factory):
        ac.resolve_offering("course-1", term_id="t1")
        order = factory("course_offerings").select.call_args.kwargs["order"]
    assert order.startswith("section.asc"), f"section must be the primary sort, got {order!r}"


def test_resolve_offering_cross_term_fallback_is_ordered_too():
    """The fallback query spans EVERY term, so since #280 it picks among all of a
    course's sections in all of them (CAS CS 330 alone has 7 in fall-2026).
    Unordered, consecutive calls could hand one user different sections and split
    their documents/notes — masked today only because current_term() resolves to the
    newest seeded term, and live as soon as a later term is added.
    """
    factory = _factory(
        {"terms": [{"id": "t1", "sort_key": 1}]},
        select_seqs={"course_offerings": [[], [{"id": "off-legacy"}]]},  # term miss, then any
    )
    with patch.object(ac, "table", side_effect=factory):
        assert ac.resolve_offering("course-1", create=False) == "off-legacy"
        order = factory("course_offerings").select.call_args_list[-1].kwargs["order"]
    assert order == "section.asc,created_at.asc", f"fallback must be ordered, got {order!r}"


def test_resolve_offering_no_create_falls_back_to_any_offering():
    # No offering in the target term, but the course has one elsewhere.
    factory = _factory(
        {"terms": [{"id": "t1", "sort_key": 1}]},
        select_seqs={"course_offerings": [[], [{"id": "off-legacy"}]]},  # term miss, then any
    )
    with patch.object(ac, "table", side_effect=factory):
        assert ac.resolve_offering("course-1", create=False) == "off-legacy"


def test_resolve_offering_fallback_false_returns_none_on_term_miss():
    """#141: an explicitly targeted term with no offering must NOT silently
    resolve to another term's offering. fallback=False returns None so the
    caller degrades to its own empty/404 behavior instead."""
    factory = _factory(
        {"terms": [{"id": "t1", "sort_key": 1}]},
        # The any-offering row exists, proving the fallback would have hit it.
        select_seqs={"course_offerings": [[], [{"id": "off-legacy"}]]},
    )
    with patch.object(ac, "table", side_effect=factory):
        assert ac.resolve_offering("course-1", term_id="t1", fallback=False) is None


def test_resolve_offering_fallback_false_still_returns_term_match():
    factory = _factory(
        {"terms": [{"id": "t1", "sort_key": 1}],
         "course_offerings": [{"id": "off-t1"}]},
    )
    with patch.object(ac, "table", side_effect=factory):
        assert ac.resolve_offering("course-1", term_id="t1", fallback=False) == "off-t1"


# ── user_offering_ids_for_course ────────────────────────────────────────────

def test_user_offering_ids_for_course_intersects():
    rows = {
        "course_offerings": [{"id": "off-1"}, {"id": "off-2"}],
        "enrollments": [{"offering_id": "off-2"}, {"offering_id": "off-9"}],
    }
    with patch.object(ac, "table", side_effect=_factory(rows)):
        got = ac.user_offering_ids_for_course("user-1", "course-1")
    assert got == ["off-2"]  # off-9 isn't an offering of this course


def test_user_offering_ids_for_course_empty_when_course_has_no_offerings():
    with patch.object(ac, "table", side_effect=_factory({"course_offerings": []})):
        assert ac.user_offering_ids_for_course("user-1", "course-1") == []


# ── course_offering_ids ─────────────────────────────────────────────────────
#
# The keyspace `sessions.offering_id` and `flashcards.offering_id` are written
# in: every writer resolves through `resolve_offering` (current term, created
# if absent) and none of them consults `enrollments`. Reading those tables
# back through `user_offering_ids_for_course` is a foreign keyspace in the
# #553/#529 shape, and it diverges permanently at the first term rollover.
# Moved here from `services/quiz_signals.py` — CLAUDE.md names this module as
# the single home for term/offering/enrollment resolution.

def test_course_offering_ids_returns_every_offering_of_the_course():
    rows = {"course_offerings": [{"id": "off-fall"}, {"id": "off-spring"}]}
    with patch.object(ac, "table", side_effect=_factory(rows)):
        assert ac.course_offering_ids("course-1") == ["off-fall", "off-spring"]


def test_course_offering_ids_never_consults_enrollments():
    """The divergence, stated as a query shape. Ownership on the tables that
    use this scope comes from `user_id`, so intersecting with enrollments adds
    no safety — it only subtracts the offerings the writers actually use."""
    seen: list[str] = []

    def recording(name):
        seen.append(name)
        return _factory({"course_offerings": [{"id": "off-1"}]})(name)

    with patch.object(ac, "table", side_effect=recording):
        ac.course_offering_ids("course-1")

    assert "enrollments" not in seen


def test_course_offering_ids_no_course_is_unknown():
    assert ac.course_offering_ids(None) is None
    assert ac.course_offering_ids("") is None


def test_course_offering_ids_a_failing_read_is_unknown_and_LOUD(caplog):
    """A transient PostgREST outage must not look like a course with no
    offerings. At debug it was invisible in production — the exact bug class
    F5 exists to end, one layer up."""
    def boom(name):
        m = MagicMock()
        m.select_with_count.side_effect = RuntimeError("postgrest 503")
        return m

    with (
        patch.object(ac, "table", side_effect=boom),
        caplog.at_level("WARNING", logger="services.academics"),
    ):
        assert ac.course_offering_ids("course-1") is None

    assert any(
        r.levelname == "WARNING" and "offering resolution failed" in r.message
        for r in caplog.records
    ), "a real DB failure must reach the operator, not just a debug line"


def test_course_offering_ids_a_truncated_read_is_unknown_not_a_partial_list():
    """Every signal keyed on this scope would undercount against a truncated
    offering list — and report the undercount as a fact."""
    rows = {"course_offerings": [{"id": "off-1"}]}
    with patch.object(
        ac, "table", side_effect=_factory(rows, counts={"course_offerings": 5000}),
    ):
        assert ac.course_offering_ids("course-1") is None


def test_user_offering_ids_for_course_keeps_its_own_raising_read():
    """The two resolvers look alike and deliberately do not share a read.
    This one has no tri-state to express "couldn't tell", so it lets the read
    raise — degrading to `[]` would assert the student is enrolled in nothing,
    which is the undercount-as-fact bug the counted form exists to avoid."""
    def boom(name):
        m = MagicMock()
        m.select.side_effect = RuntimeError("postgrest 503")
        return m

    with patch.object(ac, "table", side_effect=boom):
        with pytest.raises(RuntimeError):
            ac.user_offering_ids_for_course("user-1", "course-1")


# ── offering_course_id / term_for_offering ──────────────────────────────────

def test_offering_course_id():
    rows = {"course_offerings": [{"course_id": "course-7"}]}
    with patch.object(ac, "table", side_effect=_factory(rows)):
        assert ac.offering_course_id("off-1") == "course-7"


def test_term_for_offering():
    rows = {
        "course_offerings": [{"term_id": "t-3"}],
        "terms": [{"id": "t-3", "label": "Fall 2026"}],
    }
    with patch.object(ac, "table", side_effect=_factory(rows)):
        assert ac.term_for_offering("off-1")["label"] == "Fall 2026"


# ── term_id_for_label ────────────────────────────────────────────────────────

def test_term_id_for_label_resolves_by_label():
    rows = {"terms": [{"id": "t-spring"}]}
    with patch.object(ac, "table", side_effect=_factory(rows)):
        assert ac.term_id_for_label("Spring 2026") == "t-spring"


def test_term_id_for_label_falls_back_to_id():
    # First select (by label) empty; second (by id) returns the row.
    factory = _factory({}, select_seqs={"terms": [[], [{"id": "t-xyz"}]]})
    with patch.object(ac, "table", side_effect=factory):
        assert ac.term_id_for_label("t-xyz") == "t-xyz"


def test_term_id_for_label_none_for_empty():
    with patch.object(ac, "table", side_effect=_factory({})):
        assert ac.term_id_for_label("") is None


# ── user_course_ids_for_term ─────────────────────────────────────────────────

def test_user_course_ids_for_term_intersects_enrollments_and_term():
    rows = {
        "enrollments": [{"offering_id": "off-1"}, {"offering_id": "off-2"}],
        # course_offerings filtered by (id in off-1,off-2) AND term_id eq t-spring
        "course_offerings": [{"course_id": "bio-101"}],
    }
    with patch.object(ac, "table", side_effect=_factory(rows)):
        assert ac.user_course_ids_for_term("user_andres", "t-spring") == {"bio-101"}


def test_user_course_ids_for_term_empty_when_no_enrollments():
    with patch.object(ac, "table", side_effect=_factory({"enrollments": []})):
        assert ac.user_course_ids_for_term("user_andres", "t-spring") == set()


def test_user_course_ids_for_term_empty_args():
    with patch.object(ac, "table", side_effect=_factory({})):
        assert ac.user_course_ids_for_term("", "t") == set()
        assert ac.user_course_ids_for_term("u", "") == set()
