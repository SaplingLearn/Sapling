"""services/academics.py

Term / offering / enrollment resolution for the academics-split schema.

The public API speaks in **abstract** course ids (the catalog), while the
storage layer keys enrollments and class artifacts on a **course_offering**
(a course taught in a specific term). These helpers bridge the two:

- the knowledge graph stays on the abstract ``course_id`` (cumulative mastery),
- enrollments / gradebook / analytics resolve to an ``offering_id`` per term.

"Current term" is date-derived: the term whose ``[start_date, end_date]``
contains today. When today falls outside every seeded range we fall back to the
latest term by ``sort_key`` so resolution never dead-ends.
"""
from __future__ import annotations

import copy
import uuid
from datetime import date
from functools import lru_cache

import httpx

from db.connection import table


def current_term(today: date | None = None) -> dict | None:
    """The current term row, or None if no terms are seeded.

    Date-derived: today ∈ [start_date, end_date]. Falls back to the most recent
    term (highest sort_key) so a date in a gap between terms still resolves.
    """
    d = (today or date.today()).isoformat()
    rows = table("terms").select(
        "*",
        filters={"start_date": f"lte.{d}", "end_date": f"gte.{d}"},
        order="sort_key.desc",
        limit=1,
    )
    if rows:
        return rows[0]
    latest = table("terms").select("*", order="sort_key.desc", limit=1)
    return latest[0] if latest else None


def list_terms() -> list[dict]:
    """All terms, most recent first — backs GET /api/semesters."""
    return table("terms").select(
        "id,term,year,label,start_date,end_date,sort_key",
        order="sort_key.desc",
    ) or []


def term_id_for_label(label: str | None) -> str | None:
    """Resolve a semester **label** (e.g. "Spring 2026") to a term id.

    Falls back to treating the value as a term id directly. ``None``/empty → None.
    The canonical mapping for ``semester`` query values across the API —
    ``routes/gradebook.py`` and the graph/recommendations scoping both use it.
    """
    if not label:
        return None
    rows = table("terms").select("id", filters={"label": f"eq.{label}"}, limit=1)
    if rows:
        return rows[0]["id"]
    rows = table("terms").select("id", filters={"id": f"eq.{label}"}, limit=1)
    return rows[0]["id"] if rows else None


def user_course_ids_for_term(user_id: str, term_id: str) -> set[str]:
    """The abstract ``course_id``s the user is enrolled in for a given term.

    ``enrollments (user_id) → offering_id → course_offerings (term_id) → course_id``.
    Multi-step reads (this module avoids PostgREST embedded filters); short-circuits
    on empty sets. Deliberately **not** cached — enrollments mutate.
    """
    if not user_id or not term_id:
        return set()
    enr = table("enrollments").select(
        "offering_id", filters={"user_id": f"eq.{user_id}"}
    ) or []
    off_ids = {e["offering_id"] for e in enr if e.get("offering_id")}
    if not off_ids:
        return set()
    offs = table("course_offerings").select(
        "course_id",
        filters={"id": f"in.({','.join(off_ids)})", "term_id": f"eq.{term_id}"},
    ) or []
    return {o["course_id"] for o in offs if o.get("course_id")}


def resolve_offering(
    course_id: str,
    term_id: str | None = None,
    *,
    create: bool = False,
) -> str | None:
    """Return the offering id for (course, term).

    ``term_id`` defaults to the current term. If no matching offering exists:
    - ``create=True`` inserts one (NULL section) and returns its id, so a fresh
      enrollment lands in the real current semester instead of a legacy term.
      Race-safe: losing a concurrent create to the partial unique index
      (migration 0036) re-selects and returns the winner's row instead of
      surfacing the conflict;
    - ``create=False`` falls back to any existing offering of the course.
    Returns None only when the course has no offering and we can't/shouldn't make one.
    """
    if not course_id:
        return None
    if not term_id:
        t = current_term()
        term_id = t["id"] if t else None

    if term_id:
        rows = table("course_offerings").select(
            "id",
            filters={"course_id": f"eq.{course_id}", "term_id": f"eq.{term_id}"},
            order="created_at.asc",
            limit=1,
        )
        if rows:
            return rows[0]["id"]

    if create and term_id:
        new_id = str(uuid.uuid4())
        try:
            table("course_offerings").insert(
                {"id": new_id, "course_id": course_id, "term_id": term_id}
            )
            return new_id
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                raise
            # Lost a create race: the NULL-section partial unique index (0036)
            # rejected a second offering for (course, term). The winner's row
            # exists now — return it.
            rows = table("course_offerings").select(
                "id",
                filters={"course_id": f"eq.{course_id}", "term_id": f"eq.{term_id}"},
                order="created_at.asc",
                limit=1,
            )
            if rows:
                return rows[0]["id"]
            raise

    # No offering in the target term and not creating — fall back to any offering
    # of this course so reads still resolve to something sensible.
    any_off = table("course_offerings").select(
        "id", filters={"course_id": f"eq.{course_id}"}, limit=1
    )
    return any_off[0]["id"] if any_off else None


@lru_cache(maxsize=4096)
def offering_course_id(offering_id: str) -> str | None:
    """The abstract course id an offering belongs to (offering → graph bridge).

    Cached per-process (#98): an offering's ``course_id`` is set at creation and
    never changes, so this is a deterministic immutable mapping — no invalidation
    hook needed. Returns an immutable ``str``/``None`` (safe to share)."""
    if not offering_id:
        return None
    rows = table("course_offerings").select(
        "course_id", filters={"id": f"eq.{offering_id}"}, limit=1
    )
    return rows[0]["course_id"] if rows else None


def user_offering_ids_for_course(user_id: str, course_id: str) -> list[str]:
    """The offerings of an abstract course that ``user_id`` is enrolled in.

    Two-step (offerings of the course, then the user's enrollments intersected)
    to avoid fragile PostgREST embedded-filter syntax.
    """
    offs = table("course_offerings").select(
        "id", filters={"course_id": f"eq.{course_id}"}
    ) or []
    off_ids = {o["id"] for o in offs}
    if not off_ids:
        return []
    enr = table("enrollments").select(
        "offering_id", filters={"user_id": f"eq.{user_id}"}
    ) or []
    return [e["offering_id"] for e in enr if e.get("offering_id") in off_ids]


@lru_cache(maxsize=4096)
def _term_for_offering_cached(offering_id: str) -> dict | None:
    if not offering_id:
        return None
    rows = table("course_offerings").select(
        "term_id", filters={"id": f"eq.{offering_id}"}, limit=1
    )
    if not rows:
        return None
    term_id = rows[0].get("term_id")
    if not term_id:
        return None
    terms = table("terms").select("*", filters={"id": f"eq.{term_id}"}, limit=1)
    return terms[0] if terms else None


def term_for_offering(offering_id: str) -> dict | None:
    """The term row for an offering (for semester labels).

    Cached per-process (#98): the offering→term mapping is immutable and terms
    are seeded reference data that don't change at runtime. Returns a deep copy
    so callers can't mutate the shared cached row."""
    cached = _term_for_offering_cached(offering_id)
    return copy.deepcopy(cached) if cached is not None else None


def clear_academics_caches() -> None:
    """Clear the per-process academics caches. Called from test setup (so mocked
    DB state doesn't leak across tests); rarely needed at runtime since the
    cached mappings are immutable."""
    offering_course_id.cache_clear()
    _term_for_offering_cached.cache_clear()


def user_enrollment_ids(user_id: str) -> list[dict]:
    """The user's enrollments as ``{id, offering_id}`` rows (read + scoping helper)."""
    if not user_id:
        return []
    return table("enrollments").select(
        "id,offering_id", filters={"user_id": f"eq.{user_id}"}
    ) or []


def school_peer_user_ids(user_id: str) -> set[str]:
    """The set of user_ids who share a school with ``user_id`` (includes them).

    A user's school(s) are derived from the abstract courses behind their
    enrollments (``enrollments`` → ``course_offerings.course_id`` →
    ``courses.school_id``); peers are everyone enrolled in any offering of any
    course at those schools. Backs the #342 school-scoped directory.

    Multi-step reads (rather than PostgREST embedded filters) per this module's
    house style. Deliberately **not** cached: enrollments mutate and this is a
    visibility boundary, so a stale set would leak or hide users. Each step
    short-circuits on an empty set — both to skip work and to avoid the
    degenerate ``in.()`` filter that ``','.join(set())`` would produce.
    """
    if not user_id:
        return set()

    # 1. the viewer's own offerings
    my_offerings = {
        e["offering_id"] for e in user_enrollment_ids(user_id) if e.get("offering_id")
    }
    if not my_offerings:
        return set()

    # 2. offerings → abstract course ids
    my_course_ids = {
        r["course_id"]
        for r in (
            table("course_offerings").select(
                "course_id", filters={"id": f"in.({','.join(my_offerings)})"}
            )
            or []
        )
        if r.get("course_id")
    }
    if not my_course_ids:
        return set()

    # 3. courses → the viewer's school ids
    school_ids = {
        r["school_id"]
        for r in (
            table("courses").select(
                "school_id", filters={"id": f"in.({','.join(my_course_ids)})"}
            )
            or []
        )
        if r.get("school_id")
    }
    if not school_ids:
        return set()

    # 4. school ids → every course at those schools
    school_course_ids = {
        r["id"]
        for r in (
            table("courses").select(
                "id", filters={"school_id": f"in.({','.join(school_ids)})"}
            )
            or []
        )
    }
    if not school_course_ids:
        return set()

    # 5. those courses → every offering
    school_offering_ids = {
        r["id"]
        for r in (
            table("course_offerings").select(
                "id", filters={"course_id": f"in.({','.join(school_course_ids)})"}
            )
            or []
        )
    }
    if not school_offering_ids:
        return set()

    # 6. those offerings → every enrolled user
    return {
        r["user_id"]
        for r in (
            table("enrollments").select(
                "user_id", filters={"offering_id": f"in.({','.join(school_offering_ids)})"}
            )
            or []
        )
        if r.get("user_id")
    }


def enrollment_id_for(user_id: str, course_id: str, *, create: bool = False) -> str | None:
    """Resolve (user, abstract course) → the user's current-term enrollment id.

    Prefer the user's enrollment in the course's current-term offering, else
    their only offering of the course. With ``create=True``, ensure an offering
    (current term) and an enrollment row exist so a write never silently drops.
    """
    if not user_id or not course_id:
        return None

    offering_ids = user_offering_ids_for_course(user_id, course_id)
    if offering_ids:
        chosen = offering_ids[0]
        cur = current_term()
        cur_id = cur["id"] if cur else None
        if cur_id:
            for oid in offering_ids:
                t = term_for_offering(oid)
                if t and t.get("id") == cur_id:
                    chosen = oid
                    break
        rows = table("enrollments").select(
            "id",
            filters={"user_id": f"eq.{user_id}", "offering_id": f"eq.{chosen}"},
            limit=1,
        )
        if rows:
            return rows[0]["id"]

    if not create:
        return None

    offering_id = resolve_offering(course_id, create=True)
    if not offering_id:
        return None
    existing = table("enrollments").select(
        "id",
        filters={"user_id": f"eq.{user_id}", "offering_id": f"eq.{offering_id}"},
        limit=1,
    )
    if existing:
        return existing[0]["id"]
    new_id = str(uuid.uuid4())
    table("enrollments").insert(
        {"id": new_id, "user_id": user_id, "offering_id": offering_id}
    )
    return new_id
