"""Gradescope link routes against the REAL schema (#265).

Why this file exists: `routes/gradescope.py` shipped for months naming four
things the migrated schema does not have — the `user_courses` table (renamed to
`enrollments` in 0020), `gradescope_course_links.user_id` /
`.sapling_course_id` (0027 keys the table on `enrollment_id`), `assignments`'
`user_id` / `course_id` (0021 made assignments enrollment-scoped), and the
`course_categories` table (0021 renamed it `gradebook_categories`). Every one of
those endpoints returned a PostgREST 400 in production.

The mocked suite could not see any of it: `tests/conftest.py` stubs Supabase, so
a `select("a,b,c")` naming columns that do not exist still "passes" — the mock
agrees with whatever the caller asserts. That is the exact gap the subcutaneous
lane was built for (#397), so the regression guard belongs here rather than
alongside the unit tests.

The lane's rule: writes go through the app, assertions read back with raw SQL.

Not covered here: `POST /sync/{id}`, which drives a live Gradescope login and
scrape. Its DB surface (the enrollment-keyed `assignments` and
`gradebook_categories` reads, and the `source='gradescope'` write that
migration 0042 made legal) has no offline seam to exercise.
"""
import pytest

from tests.integration.conftest import COURSE_CS, USER_ACTIVE

pytestmark = pytest.mark.integration


def _enrollment_for_cs(db_conn) -> str:
    """The seeded user's enrollment in CS101 — whichever offering the
    resolver would pick. Read with raw SQL so the fixture doesn't lean on the
    same layer under test."""
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.id
              FROM enrollments e
              JOIN course_offerings o ON o.id = e.offering_id
             WHERE e.user_id = %s AND o.course_id = %s
             ORDER BY e.id
            """,
            (USER_ACTIVE, COURSE_CS),
        )
        rows = cur.fetchall()
    assert rows, "seed should give rich-user-active at least one CS101 enrollment"
    return rows[0]["id"]


def test_link_round_trips_through_the_real_columns(authed_client, db_conn):
    """The whole point: these three calls hit the real PostgREST column lists.
    Before #265 every one of them was a 400."""
    r = authed_client.post(
        "/api/gradescope/link",
        json={
            "user_id": USER_ACTIVE,
            "sapling_course_id": COURSE_CS,
            "gradescope_course_id": "gs-integration-1",
        },
    )
    assert r.status_code == 200, r.text

    # Raw SQL read-back: the row is keyed on enrollment_id, and the columns the
    # pre-redesign code wrote do not exist to be written.
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT enrollment_id, gradescope_course_id "
            "FROM gradescope_course_links WHERE gradescope_course_id = %s",
            ("gs-integration-1",),
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["enrollment_id"] is not None
    assert rows[0]["gradescope_course_id"] == "gs-integration-1"

    # And the API still answers in course-id vocabulary, not enrollment ids.
    listed = authed_client.get("/api/gradescope/links", params={"user_id": USER_ACTIVE})
    assert listed.status_code == 200, listed.text
    links = [
        link for link in listed.json()["links"]
        if link["gradescope_course_id"] == "gs-integration-1"
    ]
    assert len(links) == 1
    assert links[0]["sapling_course_id"] == COURSE_CS

    # Delete resolves the same way.
    removed = authed_client.delete(
        f"/api/gradescope/link/{COURSE_CS}", params={"user_id": USER_ACTIVE}
    )
    assert removed.status_code == 200, removed.text
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM gradescope_course_links WHERE gradescope_course_id = %s",
            ("gs-integration-1",),
        )
        assert cur.fetchone()["count"] == 0


def test_relinking_replaces_rather_than_duplicating(authed_client, db_conn):
    """UNIQUE is (enrollment_id, gradescope_course_id), so a second link for the
    same class instance must replace the first — one Sapling class instance
    points at exactly one Gradescope course."""
    enrollment_id = _enrollment_for_cs(db_conn)

    for gs_id in ("gs-first", "gs-second"):
        r = authed_client.post(
            "/api/gradescope/link",
            json={
                "user_id": USER_ACTIVE,
                "sapling_course_id": COURSE_CS,
                "gradescope_course_id": gs_id,
            },
        )
        assert r.status_code == 200, r.text

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT gradescope_course_id FROM gradescope_course_links "
            "WHERE enrollment_id = %s",
            (enrollment_id,),
        )
        rows = cur.fetchall()
    assert [r["gradescope_course_id"] for r in rows] == ["gs-second"]


def test_linking_a_course_the_user_is_not_enrolled_in_404s(authed_client):
    """The IDOR guard that used to read `user_courses`."""
    r = authed_client.post(
        "/api/gradescope/link",
        json={
            "user_id": USER_ACTIVE,
            "sapling_course_id": "course-that-does-not-exist",
            "gradescope_course_id": "gs-nope",
        },
    )
    assert r.status_code == 404


def test_gradescope_is_a_legal_assignment_source(db_conn):
    """Migration 0042. 0021's CHECK allowed only {manual, syllabus}, so every
    synced row would have failed the constraint even with the columns fixed —
    the sync had no valid value to write."""
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'assignments_source_check'"
        )
        row = cur.fetchone()
    assert row, "assignments_source_check should exist"
    assert "gradescope" in row["pg_get_constraintdef"]
