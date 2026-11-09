"""
backend/services/social/directory.py

The school-scoped student directory (#342) and the visibility rules every
cross-user listing shares (#115, #764).

Moved verbatim out of ``routes/social.py`` (#118); the route keeps the
caller checks (``require_self`` / the session user) and maps
``services.social.errors`` to HTTP statuses.
"""
from __future__ import annotations

from collections import defaultdict

from db.connection import table
from services import academics
from services.profiles import get_display_names


def _visible_profile_ids(user_ids) -> list[str]:
    """`user_ids` minus those whose profile_visibility is 'private', sorted.

    The one opt-out rule for every cross-user listing (#342 directory, #115
    school match). Users with no settings row default to 'public' (the column
    default), so they stay. 'public' and 'school' are equivalent here: both
    callers are already school-scoped.
    """
    ids = sorted(set(user_ids))
    if not ids:
        return []
    settings_rows = table("user_settings").select(
        "user_id,profile_visibility",
        filters={"user_id": f"in.({','.join(ids)})"},
    ) or []
    hidden = {
        s["user_id"] for s in settings_rows if s.get("profile_visibility") == "private"
    }
    return [uid for uid in ids if uid not in hidden]


#: Who counts as a real, listable student (#764). A stub is the bare
#: {id, streak_count} row graph_service.ensure_user_exists inserts, and it has
#: no email. (google_id is NOT the test: every seeded local/E2E/showcase user
#: carries an email but no google_id, so keying on it would empty the
#: directory on every seeded stack.) Pending and soft-deleted accounts are
#: neither matchable nor browsable.
_LISTABLE_USER_FILTERS = {
    "email": "not.is.null",
    "is_approved": "eq.true",
    "deleted_at": "is.null",
}


def get_students(user_id: str):
    """A lightweight directory of students who share the viewer's school.

    Scoped for #342. Before this, the endpoint returned a profile for *every*
    user in the DB to any authenticated caller — the `user_id` was bound and
    never used, so it authenticated without authorizing. Two boundaries now
    apply:

    - **School scope**: only users enrolled at the same school as the viewer
      (via ``academics.school_peer_user_ids``). An empty scope (viewer not
      enrolled / course carries no school) yields an empty directory — fail
      closed, mirroring the enrollment-scoping pattern in ``calendar.py``.
    - **profile_visibility**: users who set their profile to ``private`` opt out
      of the directory entirely. ``public`` and ``school`` are both listed (the
      endpoint is already school-scoped, so they're equivalent here).

    The payload is deliberately lightweight — name, streak, course names — and
    carries **no mastery data**: per-concept mastery is academic-performance
    information that belongs on the profile page (which already gates detail on
    profile_visibility), not in a browsable directory.
    """

    peer_ids = academics.school_peer_user_ids(user_id)
    if not peer_ids:
        return {"students": []}
    peer_list = sorted(peer_ids)

    # Honor profile_visibility: drop 'private' users from the listing.
    visible_ids = _visible_profile_ids(peer_list)
    if not visible_ids:
        return {"students": []}

    # effective_streak, not the raw column: a lapsed streak still stores its
    # old count until the next activity (#767).
    from services.streak_service import effective_streak
    users = table("users").select(
        "id,streak_count,last_active_date",
        filters={"id": f"in.({','.join(visible_ids)})", **_LISTABLE_USER_FILTERS},
    ) or []
    # Display names live on user_profiles (0024); resolve in bulk and decrypt.
    name_map = get_display_names([u["id"] for u in users])

    # A user's courses resolve through the enrollment chain
    # (enrollments → course_offerings → courses); the abstract `courses` catalog
    # no longer carries a per-user row. Read the offering's abstract course name
    # via the embedded join and dedup, since one abstract course may have several
    # offerings (per term/section) the user is enrolled in.
    enrollment_rows = table("enrollments").select(
        "user_id,course_offerings(courses(course_name))",
        filters={"user_id": f"in.({','.join(visible_ids)})"},
    ) or []
    courses_by_user: dict = defaultdict(set)
    for e in enrollment_rows:
        offering = e.get("course_offerings") or {}
        course = offering.get("courses") or {} if isinstance(offering, dict) else {}
        course_name = course.get("course_name") if isinstance(course, dict) else None
        if course_name:
            courses_by_user[e["user_id"]].add(course_name)

    students = [
        {
            "user_id": u["id"],
            "name": name_map.get(u["id"], ""),
            "streak": effective_streak(u),
            "courses": sorted(courses_by_user[u["id"]]),
        }
        for u in users
    ]
    students.sort(key=lambda s: (s["name"] or ""))
    return {"students": students}
