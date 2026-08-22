"""#553 (Workstream H1, epic #537) — the misconceptions keyspace, real-DB half.

The bug: `read_misconceptions_for_course` filters
`offering_concept_stats.offering_id`, which holds `course_offerings.id`, but
the tool handed it `ctx.deps.course_id` — the abstract `courses.id`. Two
disjoint keyspaces, so the read matched nothing for every student since the
tool was written, and an empty list is exactly what "this class has no
misconceptions yet" looks like.

Verified live on 2026-08-22 before the fix: staging held 72 stats rows, 72 of
which joined `course_offerings` and 0 of which joined `courses`; prod held 73
with the same split. Filtering by course id returned 0 rows in both; filtering
by the student's offerings returned 68 + 4 (staging) and 73 (prod).

Why this file has to exist at all: the hermetic suite mocks `table()`, so it
can assert the filter STRING without ever learning that the string selects
nothing. That is the same blind spot that let #529 survive 51 days. These
assertions run against real rows in the real schema.
"""
import asyncio
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.integration

USER_ACTIVE = "rich-user-active"
USER_SECOND = "rich-user-second"
COURSE_CS = "rich-course-cs101"
OFF_CS_F25 = "rich-off-cs101-f25"
OFF_CS_S26 = "rich-off-cs101-s26"
OFF_HIST_F25 = "rich-off-hist200-f25"

HIST_MISCONCEPTION = "A primary source is any source written by a historian"


def _read(offering_ids):
    from agents.tools.graph_read import read_misconceptions_for_course

    return asyncio.run(read_misconceptions_for_course(offering_ids))


def test_seed_stats_key_on_offerings_never_on_courses(db_conn):
    """The premise. If this ever inverts, the rest of the file is testing a
    keyspace that no longer exists."""
    row = db_conn.execute(
        """
        SELECT count(*) FILTER (WHERE o.id IS NOT NULL) AS via_offering,
               count(*) FILTER (WHERE c.id IS NOT NULL) AS via_course,
               count(*)                                 AS total
        FROM offering_concept_stats s
        LEFT JOIN course_offerings o ON o.id = s.offering_id
        LEFT JOIN courses          c ON c.id = s.offering_id
        """
    ).fetchone()
    assert row["total"] > 0, "rich seed should provide offering_concept_stats rows"
    assert row["via_offering"] == row["total"]
    assert row["via_course"] == 0


def test_the_abstract_course_id_matches_nothing(db_conn):
    """The bug, pinned as a fact about the data rather than about the code:
    passing the course id where an offering id belongs selects zero rows. A
    future refactor that reintroduces it cannot pass this file."""
    row = db_conn.execute(
        "SELECT count(*) AS n FROM offering_concept_stats WHERE offering_id = %s",
        (COURSE_CS,),
    ).fetchone()
    assert row["n"] == 0
    assert _read([COURSE_CS]) == []


def test_reads_misconceptions_across_all_of_the_students_offerings():
    """The fix. Non-zero rows on the rich seed, as #553 requires — and drawn
    from BOTH of the student's offerings of the same abstract course, so a
    fix that resolves a single "current" offering still fails here."""
    out = _read([OFF_CS_F25, OFF_CS_S26])
    texts = {m.text for m in out}

    assert texts, "the fixed keyspace must return real misconceptions"
    assert any("base case is optional" in t for t in texts), "missing F25 offering"
    assert any("`else if` evaluates every branch" in t for t in texts), "missing S26 offering"
    # Concept attribution survives the flattening — the agent routes
    # distractors per-concept.
    assert {m.related_concept for m in out} >= {"Recursion", "Control Flow"}


def test_another_classs_misconceptions_never_leak():
    """The negative half, and the reason the offering filter can't simply be
    dropped: HIST200 has misconception text, and the active user is not in it."""
    out = _read([OFF_CS_F25, OFF_CS_S26])
    assert all(HIST_MISCONCEPTION != m.text for m in out)

    # ...and it IS readable when its own offering is the one asked for, so the
    # assertion above is about scoping, not about the row being absent.
    assert any(HIST_MISCONCEPTION == m.text for m in _read([OFF_HIST_F25]))


def test_empty_arrays_contribute_nothing_but_are_not_an_error():
    """A stats row with no text is the normal early-term state (0 of 72 rows
    on staging carried text). It must flatten to nothing without suppressing
    its siblings in the same offering."""
    out = _read([OFF_CS_S26])
    assert [m.text for m in out] == ["`else if` evaluates every branch before choosing one"]


def test_tool_wrapper_resolves_the_course_through_the_students_enrollments():
    """End to end through the wrapper the agent actually calls: give it the
    ABSTRACT course id in deps — the shape `routes/quiz.py` passes — and it
    must still come back with the class's misconceptions."""
    from agents.tools.graph_read import read_misconceptions_for_course_tool

    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            user_id=USER_ACTIVE, course_id=COURSE_CS, feature="quiz",
        )
    )
    out = asyncio.run(read_misconceptions_for_course_tool(ctx))
    assert {m.text for m in out}, "wrapper must resolve course -> offerings"
    assert all(HIST_MISCONCEPTION != m.text for m in out)


def test_a_student_in_a_different_offering_sees_their_own_class():
    """Scoping is per-student, not per-course: the second user holds only the
    S26 offering of CS, so the F25 class's misconceptions are not theirs."""
    from agents.tools.graph_read import read_misconceptions_for_course_tool

    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            user_id=USER_SECOND, course_id=COURSE_CS, feature="quiz",
        )
    )
    texts = {m.text for m in asyncio.run(read_misconceptions_for_course_tool(ctx))}
    assert any("`else if` evaluates every branch" in t for t in texts)
    assert not any("base case is optional" in t for t in texts), (
        "USER_SECOND is not enrolled in the F25 offering"
    )
