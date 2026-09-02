"""Hermetic tests for db/import_offerings.py (#280).

No real DB: `db.import_offerings.table` is patched to the shared PostgREST fake
from tests/conftest.py (`fake_postgrest`), which mimics the semantics the importer
actually uses — paged select_with_count, eq/in filters, insert, update, and
upsert-on-conflict — and is shared with test_seed_staging.py so both scripts are
checked against one model of PostgREST rather than two forks of one.

The invariants under test are the ones that cost real data if they break:
per-section row creation, **adoption** of the hollow legacy offering in place
(staging has enrollments and sessions pointing at those ids), and idempotency on
re-run.
"""
import json

import pytest

import db.import_offerings as imp


# ─── Fake PostgREST ──────────────────────────────────────────────────────────


@pytest.fixture
def store(fake_postgrest):
    # `terms` is read and never written — migration 0019 seeds the canonical rows.
    return fake_postgrest(imp, tables={"terms": [{"id": "fall-2026", "label": "Fall 2026"}]})


# ─── Fixtures ────────────────────────────────────────────────────────────────


def _course(code="CAS CS 330", sections=(("A1", "Erdos", "TR 2:00 pm-3:15 pm", "LSE B01"),), **kw):
    rec = {
        "course_code": code,
        "title": "Introduction to Analysis of Algorithms",
        "credits": 4,
        "description": "Covers algorithm design.",
        "semester_offered": ["Fall 2026"],
        "sections": [
            {
                "term": kw.get("term", "Fall 2026"),
                "section": s,
                "instructor_name": instr,
                "meeting_times": times,
                "location": loc,
                "notes": None,
            }
            for s, instr, times, loc in sections
        ],
    }
    return rec


def _catalog_file(tmp_path, courses):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(courses), encoding="utf-8")
    return path


def _run(tmp_path, courses, store, **kw):
    imp.run(
        term=kw.pop("term", "fall-2026"),
        apply=kw.pop("apply", True),
        catalog_path=_catalog_file(tmp_path, courses),
        **kw,
    )
    return store.rows("course_offerings")


def _seed_course(store, code="CAS CS 330", cid="course-cs330"):
    store.seed("courses", {"id": cid, "course_code": code, "school_id": None})
    return cid


# ─── Per-section creation ────────────────────────────────────────────────────


def test_creates_one_offering_per_section(tmp_path, store):
    _seed_course(store)
    course = _course(sections=(
        ("A1", "Erdos", "TR 2:00 pm-3:15 pm", "LSE B01"),
        ("A2", "Erdos", "TR 3:30 pm-4:45 pm", "EPC 207"),
        ("B4", None, "F 1:25 pm-2:15 pm", None),
    ))
    offerings = _run(tmp_path, [course], store)

    assert len(offerings) == 3
    assert {o["section"] for o in offerings} == {"A1", "A2", "B4"}
    a1 = next(o for o in offerings if o["section"] == "A1")
    assert a1["instructor_name"] == "Erdos"
    assert a1["meeting_times"] == "TR 2:00 pm-3:15 pm"
    assert a1["location"] == "LSE B01"
    assert a1["course_id"] == "course-cs330"
    assert a1["term_id"] == "fall-2026"
    # Unassigned instructor / arranged location stay NULL rather than "Staff"/"".
    b4 = next(o for o in offerings if o["section"] == "B4")
    assert b4["instructor_name"] is None and b4["location"] is None


def test_sections_from_other_terms_are_ignored(tmp_path, store):
    _seed_course(store)
    course = _course(sections=(("A1", "Erdos", "TR 2:00 pm", "LSE B01"),), term="Spring 2027")
    assert _run(tmp_path, [course], store) == []


def test_multiple_meeting_patterns_are_merged_not_dropped(tmp_path, store):
    """A section can have several published meetings (lecture + exam block).

    `course_offerings` allows one row per section, so the patterns are joined.
    Keeping only the first would lose a real meeting time — 308 Fall 2026
    sections publish more than one.
    """
    _seed_course(store)
    course = _course(sections=(
        ("A1", "Srinivasan", "R 6:30 pm-8:30 pm", "NO ROOM"),
        ("A1", "Srinivasan", "MWF 9:05 am-9:55 am", "STO B50"),
    ))
    (offering,) = _run(tmp_path, [course], store)

    assert offering["section"] == "A1"
    assert offering["meeting_times"] == "R 6:30 pm-8:30 pm; MWF 9:05 am-9:55 am"
    # "NO ROOM" is a placeholder, so only the real room survives.
    assert offering["location"] == "STO B50"
    assert offering["instructor_name"] == "Srinivasan"


def test_placeholder_locations_and_schedules_become_null(tmp_path, store):
    """Both student-facing columns get the same treatment as "Staff" on instructor.

    An older catalog file (written before the scraper nulled these) is the case
    that matters: leaving "ARR" in `meeting_times` puts a schedule in front of
    students that the registrar never published.
    """
    _seed_course(store)
    (offering,) = _run(
        tmp_path,
        [_course(sections=(("A1", "Erdos", "ARR 12:00 am-12:00 am", "NO ROOM"),))],
        store,
    )
    assert offering["location"] is None
    assert offering["meeting_times"] is None


def test_a_real_pattern_beside_a_placeholder_survives(tmp_path, store):
    """One meeting ARR, one real: the real pattern must not be dropped with it."""
    _seed_course(store)
    (offering,) = _run(tmp_path, [_course(sections=(
        ("A1", "Erdos", "ARR", "NO ROOM"),
        ("A1", "Erdos", "MWF 9:05 am-9:55 am", "STO B50"),
    ))], store)
    assert offering["meeting_times"] == "MWF 9:05 am-9:55 am"


def test_distinct_rooms_are_both_kept(tmp_path, store):
    _seed_course(store)
    (offering,) = _run(tmp_path, [_course(sections=(
        ("A1", "Chang", "MWF 12:20 pm-1:10 pm", "STO B50"),
        ("A1", "Chang", "R 6:30 pm-8:30 pm", "COM 101"),
    ))], store)
    assert offering["location"] == "STO B50; COM 101"


def test_repeated_identical_rows_collapse_to_one_value(tmp_path, store):
    _seed_course(store)
    (offering,) = _run(tmp_path, [_course(sections=(
        ("A1", "Erdos", "MWF 9:05 am", "STO B50"),
        ("A1", "Erdos", "MWF 9:05 am", "STO B50"),
    ))], store)
    assert offering["meeting_times"] == "MWF 9:05 am"
    assert offering["location"] == "STO B50"


def test_cross_listed_duplicate_codes_do_not_double_sections(tmp_path, store):
    """BU lists CAS graduate courses under GRS too — same code, same sections."""
    _seed_course(store)
    dup = _course(sections=(("A1", "Erdos", "TR 2:00 pm", "LSE B01"),))
    assert len(_run(tmp_path, [dup, dict(dup)], store)) == 1


# ─── Adoption of the hollow legacy offering ──────────────────────────────────


def test_adopts_hollow_offering_in_place(tmp_path, store):
    """Staging's section-less rows carry enrollments and sessions — the id must survive.

    Re-creating instead of adopting would orphan sessions (offering_id SET NULL)
    and cascade-delete documents/notes.
    """
    cid = _seed_course(store)
    store.seed("course_offerings", {
        "id": "legacy-offering", "course_id": cid, "term_id": "fall-2026",
        "section": None, "instructor_name": "Erdos", "meeting_times": None, "location": None,
    })
    offerings = _run(tmp_path, [_course(sections=(
        ("A1", "Erdos", "TR 2:00 pm-3:15 pm", "LSE B01"),
        ("A2", "Kfoury", "TR 3:30 pm-4:45 pm", "EPC 207"),
    ))], store)

    assert len(offerings) == 2, "the hollow row must be upgraded, not left beside new rows"
    adopted = next(o for o in offerings if o["id"] == "legacy-offering")
    assert adopted["section"] == "A1"
    assert adopted["meeting_times"] == "TR 2:00 pm-3:15 pm"
    assert adopted["location"] == "LSE B01"


def test_adoption_is_stable_across_runs(tmp_path, store):
    cid = _seed_course(store)
    store.seed("course_offerings", {
        "id": "legacy-offering", "course_id": cid, "term_id": "fall-2026",
        "section": None, "instructor_name": None, "meeting_times": None, "location": None,
    })
    course = _course(sections=(("A1", "Erdos", "TR 2:00 pm", "LSE B01"),))
    _run(tmp_path, [course], store)
    _run(tmp_path, [course], store)
    offerings = store.rows("course_offerings")
    assert [o["id"] for o in offerings] == ["legacy-offering"]


# ─── Idempotency ─────────────────────────────────────────────────────────────


def test_rerun_writes_nothing(tmp_path, store):
    _seed_course(store)
    course = _course(sections=(
        ("A1", "Erdos", "TR 2:00 pm-3:15 pm", "LSE B01"),
        ("A2", "Erdos", "TR 3:30 pm-4:45 pm", "EPC 207"),
    ))
    first = [dict(o) for o in _run(tmp_path, [course], store)]
    second = _run(tmp_path, [course], store)
    assert second == first, "second run must be a no-op (FakeTable would raise on dup insert)"


def test_rerun_updates_changed_instructor_in_place(tmp_path, store):
    _seed_course(store)
    _run(tmp_path, [_course(sections=(("A1", "Erdos", "TR 2:00 pm", "LSE B01"),))], store)
    offerings = _run(tmp_path, [_course(sections=(("A1", "Kfoury", "TR 2:00 pm", "CAS 226"),))], store)

    assert len(offerings) == 1
    assert offerings[0]["instructor_name"] == "Kfoury"
    assert offerings[0]["location"] == "CAS 226"


def test_dry_run_writes_nothing(tmp_path, store):
    _seed_course(store)
    course = _course(sections=(("A1", "Erdos", "TR 2:00 pm", "LSE B01"),))
    assert _run(tmp_path, [course], store, apply=False) == []


# ─── course_code → course resolution ─────────────────────────────────────────


def test_unknown_code_is_skipped_without_create_missing(tmp_path, store):
    course = _course(code="CAS XX 999")
    assert _run(tmp_path, [course], store) == []
    assert store.rows("courses") == []


def test_create_missing_adds_the_catalog_course(tmp_path, store):
    course = _course(code="CAS XX 999")
    offerings = _run(tmp_path, [course], store, create_missing=True)

    (new,) = store.rows("courses")
    assert new["course_code"] == "CAS XX 999"
    assert new["course_name"] == "Introduction to Analysis of Algorithms"
    assert new["department"] == "XX"
    assert new["credits"] == 4
    assert len(offerings) == 1
    assert offerings[0]["course_id"] == new["id"]


def test_fractional_credits_become_null(tmp_path, store):
    """courses.credits is INTEGER; 0.5-unit CFA courses would 400. NULL beats rounding."""
    course = _course(code="CFA ML 100")
    course["credits"] = 0.5
    _run(tmp_path, [course], store, create_missing=True)
    assert store.rows("courses")[0]["credits"] is None


def test_stale_offerings_are_left_alone(tmp_path, store):
    """A section the scrape no longer lists is reported, never deleted."""
    cid = _seed_course(store)
    store.seed("course_offerings", {
        "id": "off-c1", "course_id": cid, "term_id": "fall-2026",
        "section": "C1", "instructor_name": "Ghost", "meeting_times": None, "location": None,
    })
    offerings = _run(tmp_path, [_course(sections=(("A1", "Erdos", "TR 2:00 pm", "LSE B01"),))], store)
    assert any(o["id"] == "off-c1" for o in offerings)


def test_other_terms_are_untouched(tmp_path, store):
    cid = _seed_course(store)
    store.seed("course_offerings", {
        "id": "spring-off", "course_id": cid, "term_id": "spring-2026",
        "section": None, "instructor_name": None, "meeting_times": None, "location": None,
    })
    _run(tmp_path, [_course(sections=(("A1", "Erdos", "TR 2:00 pm", "LSE B01"),))], store)
    spring = next(o for o in store.rows("course_offerings") if o["term_id"] == "spring-2026")
    assert spring["section"] is None, "a spring offering must not be adopted by a fall section"


# ─── School linkage (#280 task 3) ────────────────────────────────────────────


def test_link_school_creates_bu_and_links_unlinked_courses(store):
    _seed_course(store, cid="c1")
    _seed_course(store, code="CAS MA 123", cid="c2")
    imp.link_school(apply=True)

    (school,) = store.rows("schools")
    assert school["slug"] == "boston-university"
    assert all(c["school_id"] == school["id"] for c in store.rows("courses"))


def test_link_school_refuses_on_duplicate_codes(store):
    """UNIQUE (school_id, course_code) is NULL-distinct today, so dups can hide."""
    _seed_course(store, cid="c1")
    _seed_course(store, cid="c2")     # same course_code, different id
    imp.link_school(apply=True)

    assert store.rows("schools") == [], "must not create the school row on a failed precheck"
    assert all(c["school_id"] is None for c in store.rows("courses"))


def test_link_school_leaves_other_schools_alone(store):
    store.seed(
        "courses", {"id": "demo", "course_code": "CS101", "school_id": "seed-school-demo"}
    )
    _seed_course(store, cid="c1")
    imp.link_school(apply=True)

    demo = next(c for c in store.rows("courses") if c["id"] == "demo")
    assert demo["school_id"] == "seed-school-demo"


def test_link_school_still_runs_when_offerings_are_already_in_sync(tmp_path, store):
    """`--link-school` is owed even when the offering sync has nothing to do.

    This is the retry path the flag exists for: link_school [FAIL]s on duplicate
    course_codes and tells the operator to merge them and run again — by which time
    the offerings are in sync. An unconditional early return there meant the
    documented runbook command silently linked nothing on every re-run.
    """
    _seed_course(store)
    course = _course(sections=(("A1", "Erdos", "TR 2:00 pm", "LSE B01"),))
    _run(tmp_path, [course], store)                        # the sync itself
    _run(tmp_path, [course], store, do_link_school=True)   # nothing to sync, still links

    (school,) = store.rows("schools")
    assert school["slug"] == "boston-university"
    assert all(c["school_id"] == school["id"] for c in store.rows("courses"))


def test_in_sync_run_without_the_flag_writes_nothing(tmp_path, store):
    _seed_course(store)
    course = _course(sections=(("A1", "Erdos", "TR 2:00 pm", "LSE B01"),))
    _run(tmp_path, [course], store)
    writes_before = len(store.calls)
    _run(tmp_path, [course], store)

    assert store.calls[writes_before:] == [], "an in-sync run must issue no writes"
    assert store.rows("schools") == []


def test_in_sync_dry_run_does_not_link(tmp_path, store):
    """The nothing-to-do branch must still respect --apply's absence."""
    _seed_course(store)
    course = _course(sections=(("A1", "Erdos", "TR 2:00 pm", "LSE B01"),))
    _run(tmp_path, [course], store)
    _run(tmp_path, [course], store, apply=False, do_link_school=True)

    assert store.rows("schools") == [], "a dry run must not create the school row"
    assert all(c["school_id"] is None for c in store.rows("courses"))


# ─── Write shape ─────────────────────────────────────────────────────────────


def test_updates_are_batched_not_one_request_per_row(tmp_path, store):
    """Adoptions and updates share the inserts' batching.

    One PATCH per row made a routine refresh O(sections) sequential HTTP requests
    — 4,122 of them for staging's hollow fall-2026 offerings alone — each its own
    transaction, each firing trg_course_offerings_updated_at.
    """
    _seed_course(store)
    before = _course(sections=tuple((f"A{i}", "Erdos", "TR 2:00 pm", "LSE B01") for i in (1, 2, 3)))
    _run(tmp_path, [before], store)
    writes_before = len(store.calls)

    after = _course(sections=tuple((f"A{i}", "Kfoury", "TR 2:00 pm", "CAS 226") for i in (1, 2, 3)))
    offerings = _run(tmp_path, [after], store)

    assert store.calls[writes_before:] == [("course_offerings", "upsert", 3)], (
        "three changed sections must go out as one batched upsert, not three PATCHes"
    )
    assert len(offerings) == 3, "upsert on id must update in place, never insert a twin"
    assert {o["section"] for o in offerings} == {"A1", "A2", "A3"}
    assert all(o["instructor_name"] == "Kfoury" and o["location"] == "CAS 226" for o in offerings)


def test_paging_continues_when_the_row_count_is_unreadable(tmp_path, store, monkeypatch):
    """`select_with_count` reports total=0 when Content-Range is missing/unparseable.

    The old `offset >= total` guard then read `PAGE >= 0` and returned page one as
    the whole table. Truncating `existing` is the dangerous direction: the importer
    queues inserts for sections that already exist and takes a duplicate-key 409
    mid-batch (here: a second row for A2 under a fresh uuid).
    """
    monkeypatch.setattr(imp, "PAGE", 1)
    cid = _seed_course(store)
    for section in ("A1", "A2"):
        store.seed("course_offerings", {
            "id": f"off-{section.lower()}", "course_id": cid, "term_id": "fall-2026",
            "section": section, "instructor_name": "Erdos",
            "meeting_times": "TR 2:00 pm", "location": "LSE B01",
        })

    def countless_table(name):
        """The shared fake, with the row count stripped as a missing header does."""
        t = store.table(name)
        paged = t.select_with_count
        t.select_with_count = lambda *a, **kw: (paged(*a, **kw)[0], 0)
        return t

    monkeypatch.setattr(imp, "table", countless_table)
    offerings = _run(tmp_path, [_course(sections=(
        ("A1", "Erdos", "TR 2:00 pm", "LSE B01"),
        ("A2", "Erdos", "TR 2:00 pm", "LSE B01"),
    ))], store)

    assert [o["id"] for o in offerings] == ["off-a1", "off-a2"]
