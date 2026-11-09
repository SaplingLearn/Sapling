"""Admin account tools' review step: `services/account_summary.summarize_account`.

Driven against the wipe suite's in-memory PostgREST (tests/test_account_wipe.py),
so "what the review says will be deleted" is checked against what the real
wipe then deletes from the same rows.
"""
import pytest

from services import account_summary as acs
from services import account_wipe as aw
from services import chunk_visibility as cv
from tests.test_account_wipe import FakeDB, _seed_user

U, OTHER = "user_sum", "user_other"


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    for mod in (acs, aw, cv):
        monkeypatch.setattr(mod, "table", fake.table)
    return fake


def _catalog(db, uid, n):
    """Give each of the user's `n` enrollments an offering + catalog course."""
    for i in range(n):
        enr = db.of("enrollments", id=f"{uid}-enr{i}")[0]
        enr["offering_id"] = f"{uid}-off{i}"
        db.add("course_offerings", id=f"{uid}-off{i}", course_id=f"crs{i}", term_id="fall-2026")
        if not db.of("courses", id=f"crs{i}"):
            db.add("courses", id=f"crs{i}", course_code=f"CAS CS 1{i}{i}", course_name=f"Course {i}")


def test_every_counted_table_is_one_the_wipe_empties():
    # A count the action would not actually delete would mislead the review.
    assert {name for name, _ in acs.SUMMARY_TABLES} <= aw.wiped_tables()


def test_missing_account_is_not_exists_with_zero_counts(db):
    out = acs.summarize_account("nobody")
    assert out == acs.empty_summary()
    assert out["exists"] is False and out["empty"] is True
    assert set(out["counts"]) == {name for name, _ in acs.SUMMARY_TABLES}
    assert not any(out["counts"].values())


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_blank_user_id_is_not_exists(db, bad):
    assert acs.summarize_account(bad)["exists"] is False
    assert db.log == []


def test_soft_deleted_account_is_not_exists(db):
    db.add("users", id=U, total_xp=10, deleted_at="2026-11-01T00:00:00Z")
    db.add("notes", id="n1", user_id=U)
    assert acs.summarize_account(U) == acs.empty_summary()


def test_counts_courses_and_xp(db):
    _seed_user(db, U, n=3)
    _seed_user(db, OTHER, n=5)  # never counted
    _catalog(db, U, 3)
    db.add("assignments", id=f"{U}-asg-extra", enrollment_id=f"{U}-enr0")

    out = acs.summarize_account(U)

    assert out["exists"] is True and out["empty"] is False
    assert out["total_xp"] == 420
    assert out["counts"] == {
        "enrollments": 3, "assignments": 4, "graph_nodes": 3, "notes": 3, "documents": 3,
        "flashcards": 3, "quiz_attempts": 3, "sessions": 3, "study_guides": 3,
        "xp_events": 3, "user_achievements": 3,
    }
    assert out["courses"] == [
        {"code": "CAS CS 100", "name": "Course 0", "term_id": "fall-2026"},
        {"code": "CAS CS 111", "name": "Course 1", "term_id": "fall-2026"},
        {"code": "CAS CS 122", "name": "Course 2", "term_id": "fall-2026"},
    ]


def test_summary_matches_what_the_wipe_deletes(db):
    _seed_user(db, U, n=2)
    _seed_user(db, OTHER, n=1)
    before = acs.summarize_account(U)

    wiped = aw.wipe_account_data(U)

    for name, n in before["counts"].items():
        if name in wiped:
            assert wiped[name] == n, name
    after = acs.summarize_account(U)
    assert after["exists"] is True and after["empty"] is True
    assert not any(after["counts"].values()) and after["total_xp"] == 0


def test_account_with_only_xp_is_not_empty(db):
    db.add("users", id=U, total_xp=50)
    out = acs.summarize_account(U)
    assert out["empty"] is False and not any(out["counts"].values())


def test_is_read_only(db):
    _seed_user(db, U, n=1)
    acs.summarize_account(U)
    assert {op for op, _, _ in db.log} == {"select"}


def test_counts_are_one_row_reads(db, monkeypatch):
    _seed_user(db, U, n=4)
    calls = []
    real = db.table

    def spy(name):
        t = real(name)
        inner = t.select_with_count

        def swc(columns="*", **kw):
            calls.append((name, kw.get("limit")))
            return inner(columns, **kw)
        t.select_with_count = swc
        return t
    monkeypatch.setattr(acs, "table", spy)
    acs.summarize_account(U)
    assert ("notes", 1) in calls and ("xp_events", 1) in calls


def test_missing_content_range_falls_back_to_paging(db, monkeypatch):
    _seed_user(db, U, n=3)
    real = db.table

    def no_total(name):
        t = real(name)
        inner = t.select_with_count

        def swc(*a, **kw):
            rows, _ = inner(*a, **kw)
            return rows, 0  # what an unparseable Content-Range reports
        t.select_with_count = swc
        return t
    monkeypatch.setattr(acs, "table", no_total)
    counts = acs.summarize_account(U)["counts"]
    assert counts["notes"] == 3 and counts["assignments"] == 3
