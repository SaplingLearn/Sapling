"""The public profile projection (#118, moved from ``routes/profile.py``):
what ``GET /api/profile/{user_id}`` reveals to a given viewer."""
from typing import Optional

from db.connection import table
from services.academics import school_peer_user_ids
from services.profile.achievements import _get_featured_achievements
from services.profile.cosmetics import _get_equipped_cosmetics, _strip_role_cosmetics
from services.profile.users import (
    _get_or_create_settings,
    _get_user_or_404,
    _get_user_roles,
    _get_user_stats,
)


def public_profile(user_id: str, viewer_id: Optional[str]) -> dict:
    """``user_id``'s profile as ``viewer_id`` (None = anonymous) may see it.
    Raises :class:`UserNotFound` for a missing or deleted account."""
    user = _get_user_or_404(user_id)
    settings = _get_or_create_settings(user_id)
    # Roles say who is staff/admin (#115): signed-in viewers only, the same
    # audience as GET /{user_id}/roles. The app renders profiles only behind
    # sign-in (frontend middleware), so anonymous gets [] — and skips the read.
    roles = _get_user_roles(user_id) if viewer_id is not None else []
    equipped = _get_equipped_cosmetics(settings)
    if viewer_id is None:
        # ...nor through the cosmetics: the featured role IS a role, and a
        # role-granted cosmetic (role_cosmetics, e.g. a staff title) names it.
        equipped = _strip_role_cosmetics(equipped)

    is_owner = viewer_id is not None and viewer_id == user_id

    # Effective visibility. The owner always sees everything. 'school' (0031)
    # reveals the extended profile only to viewers sharing a school with the
    # owner — resolved through services/academics.py, the same boundary the
    # #342 school directory uses — and otherwise behaves as 'private'.
    # Fail-closed: anonymous viewer / no shared school → private.
    visibility = settings.get("profile_visibility") or "public"
    if not is_owner and visibility == "school":
        same_school = (
            viewer_id is not None and viewer_id in school_peer_user_ids(user_id)
        )
        visibility = "public" if same_school else "private"

    profile = {
        "id": user["id"],
        "username": user.get("username"),
        "avatar_url": user.get("avatar_url"),
        "created_at": user.get("created_at"),
        "roles": roles,
        "equipped_cosmetics": equipped,
    }

    if not is_owner and visibility == "private":
        # Minimal stub: identity-adjacent decoration only. name/year/majors/
        # minors/school are personal data and stay hidden alongside
        # bio/location/website/featured/stats (#134). Keys are kept (nulled)
        # so the frontend's response shape is unchanged.
        profile.update({
            "name": "",
            "year": None,
            "majors": [],
            "minors": [],
            "school": None,
            "bio": None,
            "location": None,
            "website": None,
            "featured_achievements": [],
            "stats": {},
        })
        return profile

    # Resolve school from user's enrolled courses.
    # School now lives behind enrollments.offering_id → course_offerings.course_id
    # → courses.school_id (a FK, currently unpopulated). Read through the join but
    # tolerate a missing/None school; it surfaces as None until school_id is linked.
    school = None
    enrollments = table("enrollments").select(
        "course_offerings(courses(school_id))",
        filters={"user_id": f"eq.{user_id}"},
        limit=1,
    )
    if enrollments:
        offering = enrollments[0].get("course_offerings") or {}
        course = offering.get("courses") or {} if isinstance(offering, dict) else {}
        if isinstance(course, dict) and course.get("school_id"):
            school = course["school_id"]

    profile.update({
        "name": user.get("name", ""),
        "year": user.get("year"),
        "majors": user.get("majors") or [],
        "minors": user.get("minors") or [],
        "school": school,
        "bio": user.get("bio"),
        "location": user.get("location"),
        "website": user.get("website"),
        "featured_achievements": _get_featured_achievements(user_id),
        "stats": _get_user_stats(user_id),
    })
    return profile
