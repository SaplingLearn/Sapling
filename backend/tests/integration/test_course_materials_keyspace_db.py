"""#562 — `search_course_materials`' keyspace, real-DB half.

The bug: the tool filtered `documents.course_id`, a column migration 0025
dropped (documents key on `offering_id`). PostgREST 400'd, the tool's
degrade-to-[] contract swallowed it, and the tutor and note chat lost every
course document for every student, silently.

Why this file has to exist: the hermetic suite mocks `table()`. Its fakes are
now schema-faithful, but a fake's idea of the schema is still something a
person typed. These run the real tool against the real schema, including the
two things a fake cannot vouch for: that the writer's keyspace ("every
offering of the course") is what the reader resolves, and that the F5 probe's
embedded `course_offerings!inner` filter means what we think it means to a
real PostgREST.
"""
import asyncio

import pytest

pytestmark = pytest.mark.integration

USER_ACTIVE = "rich-user-active"
USER_SECOND = "rich-user-second"   # enrolled in CS101 S26 only
COURSE_CS = "rich-course-cs101"
COURSE_CHEM = "rich-course-chem121"
OFF_CS_F25 = "rich-off-cs101-f25"


def _search(course_id, query, user_id):
    from agents.tools.chat_context import search_course_materials

    return asyncio.run(search_course_materials(course_id, query, user_id=user_id))


def _insert_document(db_conn, doc_id, user_id, offering_id, summary, deleted=False):
    from services.encryption import encrypt_if_present

    db_conn.execute(
        """
        INSERT INTO documents (id, user_id, offering_id, file_name, category, summary, deleted_at)
        VALUES (%s, %s, %s, %s, 'lecture_notes', %s, CASE WHEN %s THEN now() END)
        """,
        (doc_id, user_id, offering_id, f"{doc_id}.pdf", encrypt_if_present(summary), deleted),
    )


def test_the_seeded_syllabus_reaches_the_tool():
    """The headline: on main this returned [] for every student."""
    result = _search(COURSE_CS, "syllabus homework midterm", USER_ACTIVE)

    assert "rich-doc-cs-syllabus" in [m.document_id for m in result]
    assert all(m.summary and not m.summary.startswith("enc:") for m in result)


def test_a_document_on_an_offering_the_student_is_not_enrolled_in_is_found(db_conn):
    """Uploads are stamped with `resolve_offering` (the term current at upload
    time), never with an enrollment. USER_SECOND is enrolled in S26 only; this
    document sits on F25 — the rollover shape. An enrollment-keyed read misses
    it while the Library still lists it."""
    _insert_document(db_conn, "itest-562-f25", USER_SECOND, OFF_CS_F25, "recursion base cases")

    result = _search(COURSE_CS, "recursion", USER_SECOND)

    assert [m.document_id for m in result] == ["itest-562-f25"]


def test_another_students_documents_never_leak_through_the_wider_scope(db_conn):
    """#125. Widening the offering scope must not widen the owner scope:
    USER_SECOND shares CS101 with USER_ACTIVE and must not see their syllabus."""
    result = _search(COURSE_CS, "syllabus homework midterm", USER_SECOND)

    assert result == []


def test_soft_deleted_documents_stay_out(db_conn):
    _insert_document(db_conn, "itest-562-gone", USER_SECOND, OFF_CS_F25, "deleted notes", deleted=True)

    assert _search(COURSE_CS, "deleted notes", USER_SECOND) == []


def test_the_f5_documents_probe_is_course_scoped_by_a_real_postgrest(db_conn):
    """The probe filters on an EMBEDDED resource. If the embed were not
    `!inner` (or not in the select) PostgREST would ignore the filter and
    answer "has documents" for every course the moment a student has one
    anywhere — a false alarm on every multi-course student."""
    from services.tool_signals import Expect, _user_plausibly_has_data

    def scope(course_id):
        return {"course_offerings.course_id": f"eq.{course_id}"}

    assert _user_plausibly_has_data(USER_ACTIVE, Expect.HAS_DOCUMENTS, scope(COURSE_CS)) is True
    # USER_ACTIVE has documents, but none in chemistry.
    assert _user_plausibly_has_data(USER_ACTIVE, Expect.HAS_DOCUMENTS, scope(COURSE_CHEM)) is False
    # USER_SECOND has no documents at all.
    assert _user_plausibly_has_data(USER_SECOND, Expect.HAS_DOCUMENTS, scope(COURSE_CS)) is False
