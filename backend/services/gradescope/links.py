"""
backend/services/gradescope/links.py

Gradescope course links (#118, moved from routes/gradescope.py): (user,
abstract course, semester) -> the enrollments a link keys on, and the link
reads/writes behind GET /links, POST /link and POST /sync.
"""
from __future__ import annotations

from db.connection import table
from services.academics import (
    current_term,
    enrollment_id_for,
    offering_course_id,
    scoped_user_enrollments,
    term_id_for_label,
)
from services.gradescope.errors import (
    AmbiguousEnrollment,
    AmbiguousLink,
    CourseNotFound,
    NoCourseLink,
)


def _enrollment_for(user_id: str, sapling_course_id: str) -> str | None:
    """Resolve (user, abstract course) → the user's enrollment id, or None.

    Doubles as the ownership check this module used to do against
    `user_courses` — a table that stopped existing when 0020 renamed it to
    `enrollments` (offering-keyed). No enrollment means the user isn't in the
    course, which is the same 404 the old check produced.

    Gradescope links key on `enrollment_id` (0027), not the abstract course:
    grades land on enrollment-scoped `assignments` (0021), so a link has to
    name the specific class instance the grades belong to — otherwise a retake
    gives two enrollments and the sync cannot tell which term's assignments to
    write. The HTTP boundary still speaks `course_id` per the repo convention;
    resolution happens here.
    """
    return enrollment_id_for(user_id, sapling_course_id)


def _enrollments_in(user_id: str, semester: str | None, sapling_course_id: str | None = None) -> list[dict]:
    """The user's enrollments ({id, offering_id}), optionally narrowed to a
    course and/or a semester label.

    An explicit semester that doesn't resolve to a term matches nothing — it
    never widens to every term.
    """
    term_id = None
    if semester is not None:
        term_id = term_id_for_label(semester)
        if not term_id:
            return []
    return scoped_user_enrollments(user_id, course_id=sapling_course_id, term_id=term_id)


def _all_enrollments_for(user_id: str, sapling_course_id: str, semester: str | None = None) -> list[str]:
    """Owned enrollments in this course, optionally restricted to a semester.

    An explicit term never falls back to a different enrollment. Without a
    term, search all enrollments so legacy links survive a term rollover.
    """
    return [e["id"] for e in _enrollments_in(user_id, semester, sapling_course_id)]


def course_links(user_id: str, semester: str | None = None) -> list[dict]:
    """GET /links's rows: every sapling-course -> gradescope-course mapping of
    the user (one semester's, when given), in the API's course vocabulary."""
    enrollments = _enrollments_in(user_id, semester)
    if not enrollments:
        return []

    course_by_enrollment = {
        e["id"]: offering_course_id(e.get("offering_id")) for e in enrollments
    }
    rows = table("gradescope_course_links").select(
        "id,enrollment_id,gradescope_course_id,last_synced_at",
        filters={"enrollment_id": f"in.({','.join(course_by_enrollment)})"},
    )
    links = [
        {
            "id": r["id"],
            "sapling_course_id": course_by_enrollment[r.get("enrollment_id")],
            "gradescope_course_id": r.get("gradescope_course_id"),
            "last_synced_at": r.get("last_synced_at"),
        }
        for r in rows
        # Drop rather than answer sapling_course_id: null — an offering whose
        # course can't be resolved has no id the client could act on, and a
        # null there reads as a real link the UI can't do anything with.
        if course_by_enrollment.get(r.get("enrollment_id"))
    ]
    return links


def link_course(user_id: str, sapling_course_id: str, gradescope_course_id: str,
                semester: str | None = None) -> dict | None:
    """POST /link: create or replace the link between a Sapling course and a
    Gradescope course. Raises CourseNotFound / AmbiguousEnrollment."""
    scoped = _all_enrollments_for(user_id, sapling_course_id, semester)
    if semester is not None:
        if len(scoped) > 1:
            raise AmbiguousEnrollment("Multiple enrollments match this semester. Contact support to resolve the course enrollment.")
        enrollment_id = scoped[0] if scoped else None
    else:
        enrollment_id = _enrollment_for(user_id, sapling_course_id)
    if not enrollment_id:
        raise CourseNotFound("Sapling course not found for user")

    # Legacy callers replace the course's mapping across terms. Semester-aware
    # callers replace only that term, preserving mappings for other enrollments.
    all_enrollments = scoped
    if all_enrollments:
        table("gradescope_course_links").delete(
            filters={"enrollment_id": f"in.({','.join(all_enrollments)})"}
        )
    inserted = table("gradescope_course_links").insert({
        "enrollment_id": enrollment_id,
        "gradescope_course_id": gradescope_course_id,
    })
    link = dict(inserted[0]) if inserted else None
    if link is not None:
        # Answer in the API's vocabulary, not the table's.
        link["sapling_course_id"] = sapling_course_id
    return link


def linked_course(user_id: str, sapling_course_id: str, semester: str | None = None) -> tuple[str, str, str]:
    """POST /sync's link: (gradescope course id, enrollment id, link id).
    Raises CourseNotFound / NoCourseLink / AmbiguousLink."""
    all_enrollments = _all_enrollments_for(user_id, sapling_course_id, semester)
    if not all_enrollments:
        raise CourseNotFound("Sapling course not found for user")

    # Find the link across every enrollment in the course, then key the whole
    # sync on THAT row's enrollment — not on a re-derived term guess. The
    # grades belong to the class instance the link was made against, and after
    # a term rollover the heuristic points at a different one (#265 review).
    link_rows = table("gradescope_course_links").select(
        "id,enrollment_id,gradescope_course_id",
        filters={"enrollment_id": f"in.({','.join(all_enrollments)})"},
    )
    if not link_rows:
        raise NoCourseLink("No Gradescope course is linked to this Sapling course")
    if len(link_rows) > 1 and semester is None:
        # A retake leaves a link on each term's enrollment. A caller that names
        # no semester means the current one; only stay ambiguous when the
        # current term doesn't settle it.
        term = current_term()
        current = {
            e["id"]
            for e in scoped_user_enrollments(user_id, course_id=sapling_course_id, term_id=term["id"])
        } if term else set()
        link_rows = [r for r in link_rows if r.get("enrollment_id") in current] or link_rows
    if len(link_rows) != 1:
        raise AmbiguousLink("Multiple Gradescope links match this course. Select a semester and reconnect the course.")
    gs_course_id = link_rows[0]["gradescope_course_id"]
    enrollment_id = link_rows[0]["enrollment_id"]
    link_id = link_rows[0]["id"]
    return gs_course_id, enrollment_id, link_id
