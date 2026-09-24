"""Hermetic tests for db/seed_staging.py (#258).

No real DB: `db.seed_helpers.table` (the shared idempotency helpers seed_staging
delegates to — #363 prep) is patched to the shared PostgREST fake in
tests/conftest.py (`fake_postgrest`), which models PostgREST's eq-filter select,
insert, and upsert(merge-duplicates) semantics closely enough to exercise the
seed's idempotency, FK consistency, enum validity, multi-term, and encryption
boundaries. It is the same fake test_import_offerings.py uses: the two used to be
separate forks, so a divergence in one was invisible to the other.
"""
import pytest

import db.seed_staging as seed
from db import seed_helpers
from services.encryption import decrypt

# CHECK-enum sets read off migrations 0019–0027 (the seed must stay within these).
MASTERY_TIERS = {"unexplored", "struggling", "learning", "mastered", "subject_root"}
RELATIONSHIP_TYPES = {"related", "prerequisite", "builds_on", "part_of"}
ASSIGNMENT_TYPES = {"homework", "exam", "reading", "project", "quiz", "other"}
ASSIGNMENT_SOURCES = {"manual", "syllabus"}
DOC_CATEGORIES = {
    "syllabus", "lecture_notes", "slides", "reading", "assignment",
    "study_guide", "other",
}
CURVE_MODES = {"raw", "curved"}

# Terms pre-seeded by 0019 — the seed references these but never writes them.
# summer-2026 is deliberately absent: 0019 seeds it, but 0032_retire_summer_2026
# deletes it, so a fake DB that still offers it would let a seed referencing a
# nonexistent term pass here and fail against a real database.
PRESEEDED_TERMS = {"fall-2025", "spring-2026", "fall-2026"}


# `user_profiles` is keyed on user_id, not id — everything else uses `id`.
_PK_COLUMNS = {"user_profiles": "user_id"}


@pytest.fixture
def store(fake_postgrest):
    # Terms are pre-populated because 0019 seeds them and the seed only reads them.
    return fake_postgrest(
        seed_helpers,
        pk_columns=_PK_COLUMNS,
        tables={"terms": [{"id": t} for t in PRESEEDED_TERMS]},
    )


def _run(store):
    seed.main()
    return store


# ─── Insertion coverage ──────────────────────────────────────────────────────


def test_seeds_all_expected_tables(store):
    _run(store)
    expected = {
        "schools", "courses", "course_offerings", "users", "user_profiles",
        "enrollments", "graph_nodes", "graph_edges", "node_mastery_events",
        "gradebook_categories", "assignments", "documents", "notes",
    }
    for name in expected:
        assert store.tables.get(name), f"{name} got no rows"


def test_terms_are_never_written(store):
    before = dict(store.tables["terms"])
    _run(store)
    assert store.tables["terms"] == before, "seed must not write canonical terms"


def test_expected_counts(store):
    _run(store)
    n = lambda t: len(store.tables[t])  # noqa: E731
    assert n("schools") == 1
    assert n("courses") == 3
    assert n("course_offerings") == 4
    assert n("users") == 1
    assert n("user_profiles") == 1
    assert n("enrollments") == 4
    assert n("graph_nodes") == 9
    assert n("graph_edges") == 4
    assert n("node_mastery_events") == 6
    assert n("gradebook_categories") == 4
    assert n("assignments") == 6
    assert n("documents") == 1
    assert n("notes") == 1


# ─── FK consistency ──────────────────────────────────────────────────────────


def test_fk_consistency(store):
    _run(store)
    course_ids = set(store.tables["courses"])
    offering_ids = set(store.tables["course_offerings"])
    user_ids = set(store.tables["users"])
    node_ids = set(store.tables["graph_nodes"])
    enrollment_ids = set(store.tables["enrollments"])
    category_ids = set(store.tables["gradebook_categories"])

    for off in store.tables["course_offerings"].values():
        assert off["course_id"] in course_ids
        assert off["term_id"] in PRESEEDED_TERMS

    assert set(store.tables["user_profiles"]) <= user_ids

    for enr in store.tables["enrollments"].values():
        assert enr["user_id"] in user_ids
        assert enr["offering_id"] in offering_ids

    for node in store.tables["graph_nodes"].values():
        assert node["user_id"] in user_ids
        assert node["course_id"] in course_ids  # graph keyed on ABSTRACT course

    for edge in store.tables["graph_edges"].values():
        assert edge["source_node_id"] in node_ids
        assert edge["target_node_id"] in node_ids

    for evt in store.tables["node_mastery_events"].values():
        assert evt["node_id"] in node_ids

    for cat in store.tables["gradebook_categories"].values():
        assert cat["enrollment_id"] in enrollment_ids

    for asg in store.tables["assignments"].values():
        assert asg["enrollment_id"] in enrollment_ids
        assert asg["category_id"] in category_ids

    for doc in store.tables["documents"].values():
        assert doc["user_id"] in user_ids
        assert doc["offering_id"] in offering_ids

    for note in store.tables["notes"].values():
        assert note["user_id"] in user_ids
        assert note["offering_id"] in offering_ids


# ─── Enum validity ───────────────────────────────────────────────────────────


def test_enum_values_within_check_sets(store):
    _run(store)
    for node in store.tables["graph_nodes"].values():
        assert node["mastery_tier"] in MASTERY_TIERS
    for edge in store.tables["graph_edges"].values():
        assert edge["relationship_type"] in RELATIONSHIP_TYPES
    for enr in store.tables["enrollments"].values():
        assert enr["curve_mode"] in CURVE_MODES
    for asg in store.tables["assignments"].values():
        assert asg["assignment_type"] in ASSIGNMENT_TYPES
        assert asg["source"] in ASSIGNMENT_SOURCES
    for doc in store.tables["documents"].values():
        assert doc["category"] in DOC_CATEGORIES


def test_mastery_tier_matches_score(store):
    from config import get_mastery_tier
    _run(store)
    for node in store.tables["graph_nodes"].values():
        assert node["mastery_tier"] == get_mastery_tier(node["mastery_score"])


# ─── Multi-term ──────────────────────────────────────────────────────────────


def test_multi_term_same_course_two_terms(store):
    _run(store)
    cs_course = "seed-course-cs101"
    cs_offerings = [
        o for o in store.tables["course_offerings"].values()
        if o["course_id"] == cs_course
    ]
    terms = {o["term_id"] for o in cs_offerings}
    assert len(terms) >= 2, "CS101 must be offered in >=2 terms"
    assert {"fall-2025", "spring-2026"} <= terms

    # Demo user enrolled in both CS101 offerings.
    cs_off_ids = {o["id"] for o in cs_offerings}
    enrolled_offs = {
        e["offering_id"] for e in store.tables["enrollments"].values()
    }
    assert cs_off_ids <= enrolled_offs, "user must be enrolled in both CS101 terms"


# ─── Encryption boundary ─────────────────────────────────────────────────────


def test_sensitive_columns_encrypted_at_rest(store):
    _run(store)
    profile = next(iter(store.tables["user_profiles"].values()))
    assert profile["name"] != "Demo Student"
    assert decrypt(profile["name"]) == "Demo Student"
    assert decrypt(profile["first_name"]) == "Demo"

    note = next(iter(store.tables["notes"].values()))
    assert note["title"] != "Week 1 — Variables"
    assert decrypt(note["title"]) == "Week 1 — Variables"

    doc = next(iter(store.tables["documents"].values()))
    assert decrypt(doc["summary"]).startswith("CS101 syllabus")

    asg = store.tables["assignments"]["seed-asg-cs-fall-hw1"]
    assert asg["points_possible"] != "100"
    assert decrypt(asg["points_possible"]) == "100"
    assert decrypt(asg["points_earned"]) == "92"

    # None points stay None (encrypt_if_present is a no-op on None).
    unsubmitted = store.tables["assignments"]["seed-asg-cs-spring-hw1"]
    assert unsubmitted["points_earned"] is None

    # users.email is encrypted too.
    user = next(iter(store.tables["users"].values()))
    assert user["email"] != "demo.student@staging.saplinglearn.com"
    assert decrypt(user["email"]) == "demo.student@staging.saplinglearn.com"


# ─── Idempotency ─────────────────────────────────────────────────────────────


def test_second_run_adds_no_rows(store):
    _run(store)
    counts_after_first = {name: len(rows) for name, rows in store.tables.items()}

    # A 2nd run must not insert duplicates. The shared fake's insert asserts on a
    # duplicate primary key, so this also fails loudly if insert-if-absent regresses.
    seed.main()

    counts_after_second = {name: len(rows) for name, rows in store.tables.items()}
    assert counts_after_second == counts_after_first, (
        "second run changed row counts — seed is not idempotent"
    )
