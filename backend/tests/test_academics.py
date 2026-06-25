"""Tests for services/academics.py — the term/offering/enrollment resolver
that the academics-split code slice is built on.

Each test patches `services.academics.table` with a factory that returns a
MagicMock per table name, seeded with canned `.select()` rows and recording
`.insert()` calls — the same hermetic pattern the rest of the suite uses.
"""
from unittest.mock import MagicMock, patch

import services.academics as ac


def _factory(rows_by_table, recorder=None, select_seqs=None):
    """Return a `table(name)` stand-in, caching one mock per table name so that
    repeated `table(name)` calls share `.select` side-effect sequencing (the
    helper queries some tables twice: a primary query then a fallback).

    - `rows_by_table[name]` seeds a constant `.select()` return.
    - `select_seqs[name]` (optional) seeds an ordered list of `.select()` results
      for tables queried more than once.
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


def test_resolve_offering_no_create_falls_back_to_any_offering():
    # No offering in the target term, but the course has one elsewhere.
    factory = _factory(
        {"terms": [{"id": "t1", "sort_key": 1}]},
        select_seqs={"course_offerings": [[], [{"id": "off-legacy"}]]},  # term miss, then any
    )
    with patch.object(ac, "table", side_effect=factory):
        assert ac.resolve_offering("course-1", create=False) == "off-legacy"


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
