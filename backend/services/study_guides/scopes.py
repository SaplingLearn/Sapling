"""What a study guide can be for: the student's offering of a class, and the
exams and assignments in it.

The HTTP boundary speaks the abstract course id and a term label. A guide is
stored against an offering, and ``assignments`` is keyed on the enrollment
only. Every resolution here starts from the student's own enrollments, so a
guide cannot be made for a class the student is not in.
"""
from __future__ import annotations

from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from db.connection import pg_quote_value, table
from models.study_guide import ScopeKind
from services import academics
from services.exam_proximity import is_exam
from services.study_guides.errors import GuideInvalid, GuideNotFound

#: Far above a real class's exams and assignments; it only bounds the read.
MAX_ASSIGNMENTS = 200
#: No id of ours is longer (a uuid is 36 characters). A longer one in a
#: request names nothing, and is never put into a query.
MAX_ID_CHARS = 100


@dataclass(frozen=True)
class Scope:
    """One thing a guide can be for. ``id`` is the ``assignments`` row, or
    None for the whole course; ``due_date`` is ``YYYY-MM-DD`` or None."""

    kind: ScopeKind
    id: str | None
    title: str
    due_date: str | None


WHOLE_COURSE = Scope(kind="course", id=None, title="Whole course", due_date=None)


def _enrolled_offering(user_id: str, course_id: str, semester: str | None) -> str | None:
    """The offering of the course the student is enrolled in, or None.

    No ``semester``: the current term's when the student holds it, else their
    latest one, which is where their uploads for the class are filed. With a
    ``semester`` the lookup is strict: an unknown label, or a term the student
    did not take the class in, is None and never another term's offering.
    """
    if not semester:
        return academics.enrolled_offering_for_course(user_id, course_id)
    term_id = academics.term_id_for_label(semester)
    if not term_id:
        return None
    enrollments = academics.scoped_user_enrollments(
        user_id, course_id=course_id, term_id=term_id,
    )
    return next((e["offering_id"] for e in enrollments if e.get("offering_id")), None)


async def aresolve_offering(user_id: str, course_id: str, semester: str | None) -> str:
    """The student's offering of the class for that term label (None = their
    current one). ``GuideNotFound`` when there is none: the same answer for a
    class that does not exist and one the student is not in."""
    offering_id = await run_in_threadpool(_enrolled_offering, user_id, course_id, semester)
    if not offering_id:
        raise GuideNotFound("Class not found.")
    return offering_id


async def _aassignments(
    user_id: str, offering_id: str, assignment_id: str | None = None,
) -> list[dict]:
    """The assignment rows of the student's enrollment(s) in the offering, by
    due date; only ``assignment_id`` when one is named."""
    enrollments = await run_in_threadpool(academics.user_enrollment_ids, user_id)
    mine = [e["id"] for e in enrollments if e.get("offering_id") == offering_id]
    if not mine:
        return []
    filters = {"enrollment_id": f"in.({','.join(pg_quote_value(e) for e in mine)})"}
    if assignment_id is not None:
        filters["id"] = f"eq.{assignment_id}"
    return await table("assignments").aselect(
        "id,title,due_date,assignment_type",
        filters=filters,
        order="due_date.asc.nullslast,title.asc",
        limit=MAX_ASSIGNMENTS,
    ) or []


def _scope(row: dict) -> Scope:
    return Scope(
        kind="exam" if is_exam(row) else "assignment",
        id=row["id"],
        title=row.get("title") or "",
        due_date=row.get("due_date") or None,
    )


async def alist_scopes(user_id: str, course_id: str, semester: str | None) -> list[Scope]:
    """Everything a guide for this class can be for: the whole course first,
    then the class's exams and assignments by due date."""
    offering_id = await aresolve_offering(user_id, course_id, semester)
    rows = await _aassignments(user_id, offering_id)
    return [WHOLE_COURSE, *(_scope(row) for row in rows)]


async def ascope_of(
    user_id: str, offering_id: str, scope_kind: ScopeKind, scope_id: str | None,
) -> Scope:
    """One scope, read back by id.

    ``GuideInvalid`` when the kind and the id disagree (a whole-course guide
    with an id, or an exam or assignment without one). ``GuideNotFound`` when
    the row is not in the student's enrollment in that offering. Between
    ``exam`` and ``assignment`` the row decides: the returned ``kind`` is what
    the row reads as now, since a retitled row can change sides.
    """
    if scope_kind == "course":
        if scope_id is not None:
            raise GuideInvalid("A whole-course guide is not for one exam or assignment.")
        return WHOLE_COURSE
    if not scope_id:
        raise GuideInvalid("Pick the exam or assignment this guide is for.")
    known = len(scope_id) <= MAX_ID_CHARS
    rows = await _aassignments(user_id, offering_id, scope_id) if known else []
    if not rows:
        raise GuideNotFound("That exam or assignment was not found. Pick another one.")
    return _scope(rows[0])
