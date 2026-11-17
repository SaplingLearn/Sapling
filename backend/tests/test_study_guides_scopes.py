"""What a guide can be for (services/study_guides/scopes.py).

Hermetic: `academics` is faked per function and `assignments` is an in-memory
stand-in that honours the filters, order and columns the module sends, so
"another student's assignment" is decided by the same enrollment filter
production uses.
"""
import asyncio

import pytest

from services import academics
from services.study_guides import scopes
from services.study_guides.errors import GuideInvalid, GuideNotFound

ME, OTHER = "user_me", "user_other"
COURSE = "course-cs"
FALL, SPRING = "off-cs-fall", "off-cs-spring"

ENROLLMENTS = {
    ME: [
        {"id": "enr-me-fall", "offering_id": FALL},
        {"id": "enr-me-bio", "offering_id": "off-bio-fall"},
    ],
    OTHER: [{"id": "enr-other-fall", "offering_id": FALL}],
}
ASSIGNMENTS = [
    {"id": "a-final", "enrollment_id": "enr-me-fall", "title": "Final", "due_date": "2026-12-15",
     "assignment_type": "exam", "notes": "ciphertext"},
    {"id": "a-hw1", "enrollment_id": "enr-me-fall", "title": "Homework 1", "due_date": "2026-09-20",
     "assignment_type": "homework", "notes": None},
    {"id": "a-midterm", "enrollment_id": "enr-me-fall", "title": "Midterm review sheet",
     "due_date": "2026-10-10", "assignment_type": "other", "notes": None},
    {"id": "a-undated", "enrollment_id": "enr-me-fall", "title": "Reading log", "due_date": None,
     "assignment_type": "reading", "notes": None},
    {"id": "a-bio", "enrollment_id": "enr-me-bio", "title": "Lab report", "due_date": "2026-09-01",
     "assignment_type": "project", "notes": None},
    {"id": "a-theirs", "enrollment_id": "enr-other-fall", "title": "Their exam",
     "due_date": "2026-09-05", "assignment_type": "exam", "notes": None},
]


def _matches(row: dict, filters: dict) -> bool:
    for column, condition in filters.items():
        value = str(row.get(column))
        if condition.startswith("eq."):
            if value != condition[3:]:
                return False
        elif condition.startswith("in.("):
            if value not in [v.strip('"') for v in condition[4:-1].split(",")]:
                return False
        else:
            raise AssertionError(f"filter {column}={condition} not modelled")
    return True


class _Assignments:
    def __init__(self):
        self.selects: list[str] = []

    async def aselect(self, columns="*", filters=None, order=None, limit=None, **_):
        self.selects.append(columns)
        rows = [r for r in ASSIGNMENTS if _matches(r, filters or {})]
        for part in reversed((order or "").split(",")):
            column = part.split(".")[0]
            if column:
                rows.sort(key=lambda r: (r.get(column) is None, r.get(column) or ""))
        return [{c: r.get(c) for c in columns.split(",")} for r in rows][:limit]


def _off_the_loop():
    """`academics` is sync and reads the DB: it must run in the threadpool."""
    with pytest.raises(RuntimeError):
        asyncio.get_running_loop()


@pytest.fixture
def db(monkeypatch):
    def enrolled_offering(user_id, course_id):
        _off_the_loop()
        return FALL if (user_id, course_id) in {(ME, COURSE), (OTHER, COURSE)} else None

    def term_id_for_label(label):
        _off_the_loop()
        return {"Fall 2026": "term-fall", "Spring 2026": "term-spring"}.get(label)

    def scoped_user_enrollments(user_id, *, course_id=None, term_id=None):
        _off_the_loop()
        if course_id != COURSE or term_id != "term-fall":
            return []
        return [e for e in ENROLLMENTS.get(user_id, []) if e["offering_id"] == FALL]

    def user_enrollment_ids(user_id):
        _off_the_loop()
        return ENROLLMENTS.get(user_id, [])

    monkeypatch.setattr(academics, "enrolled_offering_for_course", enrolled_offering)
    monkeypatch.setattr(academics, "term_id_for_label", term_id_for_label)
    monkeypatch.setattr(academics, "scoped_user_enrollments", scoped_user_enrollments)
    monkeypatch.setattr(academics, "user_enrollment_ids", user_enrollment_ids)
    assignments = _Assignments()

    def table(name):
        assert name == "assignments"
        return assignments

    monkeypatch.setattr(scopes, "table", table)
    return assignments


def run(coro):
    return asyncio.run(coro)


# ── The offering ──────────────────────────────────────────────────────────────


def test_no_semester_resolves_the_offering_the_student_is_enrolled_in(db):
    assert run(scopes.aresolve_offering(ME, COURSE, None)) == FALL


def test_a_class_the_student_is_not_in_is_not_found(db):
    with pytest.raises(GuideNotFound) as refused:
        run(scopes.aresolve_offering("user_stranger", COURSE, None))
    assert refused.value.status_code == 404
    with pytest.raises(GuideNotFound):
        run(scopes.aresolve_offering(ME, "course-unknown", None))


def test_a_semester_resolves_that_terms_enrollment(db):
    assert run(scopes.aresolve_offering(ME, COURSE, "Fall 2026")) == FALL


def test_a_semester_never_falls_back_to_another_term(db):
    # A real term the student did not take the class in, and an unknown label.
    with pytest.raises(GuideNotFound):
        run(scopes.aresolve_offering(ME, COURSE, "Spring 2026"))
    with pytest.raises(GuideNotFound):
        run(scopes.aresolve_offering(ME, COURSE, "Winter 1999"))


# ── The list ──────────────────────────────────────────────────────────────────


def test_scopes_are_the_whole_course_then_assignments_by_due_date(db):
    listed = run(scopes.alist_scopes(ME, FALL))
    assert listed[0] == scopes.Scope(kind="course", id=None, title="Whole course", due_date=None)
    assert [s.id for s in listed[1:]] == ["a-hw1", "a-midterm", "a-final", "a-undated"]
    assert listed[1] == scopes.Scope(
        kind="assignment", id="a-hw1", title="Homework 1", due_date="2026-09-20",
    )
    assert listed[-1].due_date is None


def test_an_exam_is_one_by_type_or_by_title(db):
    kinds = {s.id: s.kind for s in run(scopes.alist_scopes(ME, FALL))}
    assert kinds["a-final"] == "exam"       # assignment_type exam
    assert kinds["a-midterm"] == "exam"     # an exam-like title
    assert kinds["a-hw1"] == "assignment"


def test_only_this_students_assignments_in_this_class_are_listed(db):
    ids = {s.id for s in run(scopes.alist_scopes(ME, FALL))}
    assert "a-theirs" not in ids  # a classmate in the same offering
    assert "a-bio" not in ids     # the student's own, in another class
    theirs = {s.id for s in run(scopes.alist_scopes(OTHER, FALL))}
    assert theirs == {None, "a-theirs"}


def test_encrypted_assignment_columns_are_never_selected(db):
    run(scopes.alist_scopes(ME, FALL))
    assert db.selects == ["id,title,due_date,assignment_type"]


def test_listing_an_offering_the_student_is_not_in_reads_nothing(db):
    assert run(scopes.alist_scopes("user_stranger", FALL)) == [scopes.WHOLE_COURSE]
    assert db.selects == []


# ── One scope ─────────────────────────────────────────────────────────────────


def test_the_whole_course_scope_needs_no_read(db):
    assert run(scopes.ascope_of(ME, FALL, "course", None)) == scopes.WHOLE_COURSE
    assert db.selects == []


def test_a_scope_is_read_back_by_id(db):
    assert run(scopes.ascope_of(ME, FALL, "exam", "a-final")) == scopes.Scope(
        kind="exam", id="a-final", title="Final", due_date="2026-12-15",
    )


def test_the_row_decides_between_exam_and_assignment(db):
    assert run(scopes.ascope_of(ME, FALL, "assignment", "a-final")).kind == "exam"
    assert run(scopes.ascope_of(ME, FALL, "exam", "a-hw1")).kind == "assignment"


@pytest.mark.parametrize("kind, scope_id", [
    ("course", "a-final"),
    ("exam", None),
    ("assignment", None),
    ("assignment", ""),
])
def test_a_kind_and_id_that_disagree_are_invalid(db, kind, scope_id):
    with pytest.raises(GuideInvalid) as refused:
        run(scopes.ascope_of(ME, FALL, kind, scope_id))
    assert refused.value.status_code == 422
    assert db.selects == []


@pytest.mark.parametrize("scope_id", ["a-theirs", "a-bio", "a-missing"])
def test_an_assignment_that_is_not_the_students_in_this_class_is_not_found(db, scope_id):
    with pytest.raises(GuideNotFound):
        run(scopes.ascope_of(ME, FALL, "exam", scope_id))


def test_an_id_too_long_to_be_an_assignment_is_not_found_without_a_read(db):
    with pytest.raises(GuideNotFound):
        run(scopes.ascope_of(ME, FALL, "exam", "a" * (scopes.MAX_ID_CHARS + 1)))
    assert db.selects == []


def test_an_offering_the_student_is_not_enrolled_in_has_no_scopes(db):
    with pytest.raises(GuideNotFound):
        run(scopes.ascope_of(ME, SPRING, "exam", "a-final"))
    assert db.selects == []
