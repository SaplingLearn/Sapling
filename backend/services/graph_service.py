from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import partial

from starlette.concurrency import run_in_threadpool

from db.connection import table
from db.scope import runs_as_service
from learning import bkt, evidence_replay
from learning.evidence import (
    EVIDENCE_EVENT_TYPE,
    PREREQ_RELATIONSHIP_TYPE,
    Evidence,
    evidence_weight,
    planning_observation,
)
from learning.learner_state import LearnerState, state_row
from learning.params import (
    EDGE_PREREQ_SOURCE_IS_PREREQ,
    FSRS_RETENTION_DEFAULT,
)
from learning.void_store import voided_event_ids
from services.streak_service import effective_streak, touch_streak_safe
# Module imports, not names: tests patch these on their home modules, and a
# call-time attribute lookup keeps those patches effective (#118 removed the
# function-local imports that hid an ImportError under a broad except).
# course_context_service is the one exception, imported in
# _refresh_touched_course_contexts: see there.
from services import academics, achievement_service
from services.graph_update_model import (  # noqa: F401  (_coerce_unit: re-export, #118)
    GraphUpdate,
    NewEdge,
    NewNode,
    _coerce_unit,
)

logger = logging.getLogger(__name__)


def _reshape_enrollment(r: dict) -> dict:
    """Flatten an enrollments→course_offerings→courses/terms join row into the
    legacy flat shape consumers expect:

    - ``course_id`` = the *abstract* course id (the knowledge-graph key),
    - ``courses``   = {course_code, course_name, department, school},
    - plus the new ``offering_id`` and ``term`` (label).
    """
    off = r.get("course_offerings") or {}
    if not isinstance(off, dict):
        off = {}
    course = off.get("courses") or {}
    if not isinstance(course, dict):
        course = {}
    term = off.get("terms") or {}
    if not isinstance(term, dict):
        term = {}
    return {
        "id": r.get("id"),
        "offering_id": r.get("offering_id"),
        "course_id": off.get("course_id"),  # ABSTRACT course id — graph keys on this
        "color": r.get("color"),
        "nickname": r.get("nickname"),
        "enrolled_at": r.get("enrolled_at"),
        "term": term.get("label", ""),
        "courses": {
            "course_code": course.get("course_code", ""),
            "course_name": course.get("course_name", ""),
            "department": course.get("department", ""),
            # Free-text school retired in the academics split; school_id is unpopulated.
            "school": "",
        },
    }


_ENROLLED_COURSES_SELECT = (
    "id,offering_id,color,nickname,enrolled_at,"
    "course_offerings!inner(course_id,"
    "courses!inner(course_code,course_name,department),terms!inner(label))"
)


def _user_enrolled_courses(user_id: str) -> list[dict]:
    """All courses a user is enrolled in, via enrollments → course_offerings →
    courses/terms, reshaped to the legacy flat shape (abstract course_id + nested
    courses dict + offering_id + term label)."""
    try:
        rows = table("enrollments").select(
            _ENROLLED_COURSES_SELECT,
            filters={"user_id": f"eq.{user_id}"},
            order="enrolled_at.asc",
        )
    except Exception:
        return []
    return [_reshape_enrollment(r) for r in (rows or [])]


async def _auser_enrolled_courses(user_id: str) -> list[dict]:
    """Async twin of :func:`_user_enrolled_courses` (#117)."""
    try:
        rows = await table("enrollments").aselect(
            _ENROLLED_COURSES_SELECT,
            filters={"user_id": f"eq.{user_id}"},
            order="enrolled_at.asc",
        )
    except Exception:
        return []
    return [_reshape_enrollment(r) for r in (rows or [])]


def _get_course_nodes(user_id: str, course_id: str) -> list:
    """Get graph nodes for a specific course."""
    return table("graph_nodes").select(
        "*",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    ) or []


@runs_as_service  # #115: inserts a users row (service-only)
def ensure_user_exists(user_id: str) -> None:
    """Create a user row if one doesn't exist yet (prevents FK violations).

    Insert only columns that still live on `users` after the 0024 identity split
    — the public profile (incl. `name`) moved to `user_profiles`. A stub user has
    no display name yet; onboarding/oauth populate `user_profiles` separately, so
    we deliberately do NOT create a profile row here.
    """
    existing = table("users").select("id", filters={"id": f"eq.{user_id}"})
    if not existing:
        try:
            table("users").insert({"id": user_id, "streak_count": 0})
        except Exception:
            pass  # already exists (race condition) — safe to ignore


@runs_as_service  # #115: inserts a users row (service-only)
async def aensure_user_exists(user_id: str) -> None:
    """Async twin of :func:`ensure_user_exists` (#117)."""
    existing = await table("users").aselect("id", filters={"id": f"eq.{user_id}"})
    if not existing:
        try:
            await table("users").ainsert({"id": user_id, "streak_count": 0})
        except Exception:
            pass  # already exists (race condition) — safe to ignore


def _event_ts(e: dict) -> str | None:
    """Pull a timestamp off a mastery event row. node_mastery_events rows key on
    ``created_at``; tolerate the legacy ``ts`` key too."""
    return e.get("created_at") or e.get("ts")


def _parse_event_ts(raw: str) -> datetime:
    """Parse a mastery-event timestamp to an aware-UTC datetime.

    Rows in the wild carry three shapes: tz-aware ISO (TIMESTAMPTZ reads via
    PostgREST, and every write after the #248 sweep), legacy naive strings
    (pre-sweep ``utcnow()`` writes — UTC by construction), and Z-suffixed
    strings. Normalize all three to aware UTC so arithmetic against
    ``datetime.now(timezone.utc)`` never mixes naive and aware."""
    ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _compute_velocity(events: list) -> float:
    """Mastery gained per day over the last 14 days. Returns 0.0 if insufficient data.

    Operates on ``node_mastery_events`` rows ({delta, created_at, ...}); the legacy
    JSON-blob ``ts`` key is still accepted via ``_event_ts``.
    """
    if not events:
        return 0.0
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    recent = []
    for e in events:
        try:
            if _parse_event_ts(_event_ts(e)) > cutoff:
                recent.append(e)
        except Exception:
            pass
    if not recent:
        return 0.0
    positive_gain = sum(e.get("delta", 0) for e in recent if e.get("delta", 0) > 0)
    if positive_gain == 0:
        return 0.0
    try:
        first_ts = _parse_event_ts(_event_ts(recent[0]))
        days = max(1, (datetime.now(timezone.utc) - first_ts).days)
    except Exception:
        days = 1
    return round(positive_gain / days, 4)


def _semester_course_ids(user_id: str, semester: str | None) -> set[str] | None:
    """Optional semester scope (Path A): the courses the user is enrolled in for
    that term. ``None`` means "all terms"; an unresolved label is the empty set.
    Sync (services/academics.py): the async readers hop it off the loop."""
    if not semester:
        return None
    from services.academics import term_id_for_label, user_course_ids_for_term
    term_id = term_id_for_label(semester)
    return user_course_ids_for_term(user_id, term_id) if term_id else set()


def _scope_nodes(nodes_raw: list | None, allowed_course_ids: set[str] | None) -> list:
    nodes = nodes_raw or []
    if allowed_course_ids is not None:
        nodes = [n for n in nodes if n.get("course_id") in allowed_course_ids]
    return nodes


#: Mastery events live in the append-only node_mastery_events table (the
#: graph_nodes.mastery_events JSONB column was dropped in 0023). Batch-read all
#: of this user's node events in one query, then group by node id.
#: `id` names a row for the spec §13 A123 void rule (a void row is no part of
#: the velocity); it is not part of the API shape (`_assemble_graph` drops it).
_NODE_EVENTS_SELECT = "id,node_id,delta,reason,created_at"


def _node_events_filters(nodes: list) -> dict | None:
    node_ids = {n["id"] for n in nodes}
    return {"node_id": f"in.({','.join(node_ids)})"} if node_ids else None


def _not_void(event_rows: list, voided: set) -> list:
    """spec §13 A123: a void row (graded against an item staff retired) moved
    no mastery that stands — it is no part of the velocity."""
    return [ev for ev in event_rows if ev.get("id") not in voided]


def _node_events(nodes: list, user_id: str) -> list:
    filters = _node_events_filters(nodes)
    if filters is None:
        return []
    try:
        rows = table("node_mastery_events").select(
            _NODE_EVENTS_SELECT, filters=filters, order="created_at.asc",
        ) or []
        voided = voided_event_ids(user_id=user_id) if rows else set()
    except Exception:
        return []
    return _not_void(rows, voided)


async def _anode_events(nodes: list, user_id: str) -> list:
    filters = _node_events_filters(nodes)
    if filters is None:
        return []
    try:
        rows = await table("node_mastery_events").aselect(
            _NODE_EVENTS_SELECT, filters=filters, order="created_at.asc",
        ) or []
        # the void read is sync (learning/void_store.py): off the event loop
        voided = await run_in_threadpool(voided_event_ids, user_id=user_id) if rows else set()
    except Exception:
        return []
    return _not_void(rows, voided)


#: The STORED streak_count is only reset on the student's next activity, so a
#: lapsed streak would still display; effective_streak reads it as of today
#: (#767).
_STREAK_SELECT = "streak_count,last_active_date"


def get_graph(user_id: str, semester: str | None = None) -> dict:
    ensure_user_exists(user_id)
    enrolled_courses = _user_enrolled_courses(user_id)
    allowed_course_ids = _semester_course_ids(user_id, semester)
    nodes = _scope_nodes(
        table("graph_nodes").select("*", filters={"user_id": f"eq.{user_id}"}),
        allowed_course_ids,
    )
    edges_raw = table("graph_edges").select("*", filters={"user_id": f"eq.{user_id}"})
    event_rows = _node_events(nodes, user_id)
    user_rows = table("users").select(_STREAK_SELECT, filters={"id": f"eq.{user_id}"})
    return _assemble_graph(
        user_id, enrolled_courses, allowed_course_ids, nodes, edges_raw, event_rows, user_rows,
    )


async def _none() -> None:
    """An awaitable None, for a gather slot with nothing to read."""
    return None


async def aget_graph(user_id: str, semester: str | None = None) -> dict:
    """Async twin of :func:`get_graph` (#117): the same reads through the
    ``a*`` seam, the academics term lookup hopped off the loop. The user row
    is ensured first (the streak read depends on it); the five independent
    reads then run concurrently, and the node-events read follows the nodes."""
    await aensure_user_exists(user_id)
    user_filter = {"user_id": f"eq.{user_id}"}
    enrolled_courses, allowed_course_ids, nodes_raw, edges_raw, user_rows = await asyncio.gather(
        _auser_enrolled_courses(user_id),
        run_in_threadpool(_semester_course_ids, user_id, semester) if semester else _none(),
        table("graph_nodes").aselect("*", filters=user_filter),
        table("graph_edges").aselect("*", filters=user_filter),
        table("users").aselect(_STREAK_SELECT, filters={"id": f"eq.{user_id}"}),
    )
    nodes = _scope_nodes(nodes_raw, allowed_course_ids)
    event_rows = await _anode_events(nodes, user_id)
    return _assemble_graph(
        user_id, enrolled_courses, allowed_course_ids, nodes, edges_raw, event_rows, user_rows,
    )


def _assemble_graph(
    user_id: str,
    enrolled_courses: list[dict],
    allowed_course_ids: set[str] | None,
    nodes: list,
    edges_raw: list,
    event_rows: list,
    user_rows: list | None,
) -> dict:
    """The pure half of :func:`get_graph` / :func:`aget_graph`: no I/O."""
    if allowed_course_ids is not None:
        enrolled_courses = [
            c for c in enrolled_courses if c.get("course_id") in allowed_course_ids
        ]
    node_ids = {n["id"] for n in nodes}

    edges = [
        {
            "id": e["id"],
            "source": e["source_node_id"],
            "target": e["target_node_id"],
            "strength": e["strength"],
            "relationship_type": e.get("relationship_type", "related"),
        }
        for e in edges_raw
        if e["source_node_id"] in node_ids and e["target_node_id"] in node_ids
    ]

    events_by_node: dict[str, list] = {}
    for ev in event_rows:
        events_by_node.setdefault(ev.get("node_id"), []).append(ev)

    # Enrich each node with learning velocity; trim event history for API response
    for n in nodes:
        events = events_by_node.get(n["id"], [])
        n["learning_velocity"] = _compute_velocity(events)
        # keep last 5 for UI (the read's row id is not part of the API shape);
        # full history lives in DB
        n["mastery_events"] = [{k: v for k, v in e.items() if k != "id"} for e in events[-5:]]

    mastered   = sum(1 for n in nodes if n["mastery_tier"] == "mastered")
    learning   = sum(1 for n in nodes if n["mastery_tier"] == "learning")
    struggling = sum(1 for n in nodes if n["mastery_tier"] == "struggling")
    unexplored = sum(1 for n in nodes if n["mastery_tier"] == "unexplored")

    velocities = [n["learning_velocity"] for n in nodes if n["learning_velocity"] > 0]
    avg_velocity = round(sum(velocities) / len(velocities), 4) if velocities else 0.0

    streak = effective_streak(user_rows[0] if user_rows else None)

    stats = {
        "total_nodes": len(nodes),
        "mastered": mastered,
        "learning": learning,
        "struggling": struggling,
        "unexplored": unexplored,
        "streak": streak,
        "avg_learning_velocity": avg_velocity,
    }

    # Build a course_id → color + name lookup from enrollments
    course_color_map: dict[str, str | None] = {}
    course_name_map: dict[str, str] = {}
    for enrollment in enrolled_courses:
        cid = enrollment["course_id"]
        course = enrollment.get("courses", {}) if isinstance(enrollment.get("courses"), dict) else {}
        course_color_map[cid] = enrollment.get("color")
        course_name_map[cid] = course.get("course_name", "")

    # Stamp each node's subject from its course_id so the frontend has a
    # consistent key, and attach the enrollment color directly. The per-node
    # `color` override (if set) is left in place so the UI can prefer it.
    for n in nodes:
        cid = n.get("course_id")
        if cid and cid in course_name_map:
            n["subject"] = course_name_map[cid]
        if cid and cid in course_color_map:
            n["course_color"] = course_color_map[cid]

    # Build subject root hubs from enrolled courses — one root per DISTINCT
    # abstract course, not per enrollment. A user can hold two offerings of the
    # same abstract course (e.g. re-taking it, or two sections); the graph stays
    # keyed on the abstract course_id, so without this dedup the synthesized
    # subject_root node (and its hub-spoke edges) would be duplicated once per
    # extra enrollment (#355).
    subject_nodes = []
    subject_edges = []
    seen_course_ids: set[str] = set()

    for enrollment in enrolled_courses:
        course_id = enrollment["course_id"]
        if course_id in seen_course_ids:
            continue
        seen_course_ids.add(course_id)
        course = enrollment.get("courses", {}) if isinstance(enrollment.get("courses"), dict) else {}
        course_code = course.get("course_code", "")
        course_name = course.get("course_name", "")

        # Use "Course Code - Course Name" as the subject label
        subject_label = f"{course_code} - {course_name}" if course_code else course_name

        # Find all nodes belonging to this course
        subj_nodes = [n for n in nodes if n.get("course_id") == course_id]

        root_id = f"subject_root__{course_id}"
        if subj_nodes:
            avg_mastery = sum(n["mastery_score"] for n in subj_nodes) / len(subj_nodes)
        else:
            avg_mastery = 0.0

        subject_nodes.append({
            "id": root_id,
            "user_id": user_id,
            "concept_name": subject_label,
            "mastery_score": round(avg_mastery, 4),
            "mastery_tier": "subject_root",
            "course_id": course_id,
            "subject": course_name,
            "course_color": course_color_map.get(course_id),
            "times_studied": sum(n.get("times_studied", 0) for n in subj_nodes),
            "last_studied_at": None,
            "is_subject_root": True,
        })

        for n in subj_nodes:
            subject_edges.append({
                "id": f"subject_edge__{root_id}__{n['id']}",
                "source": root_id,
                "target": n["id"],
                "strength": 0.7,
                "relationship_type": "related",
            })

    return {"nodes": nodes + subject_nodes, "edges": edges + subject_edges, "stats": stats}


# ── Course management ──────────────────────────────────────────────────────────

def get_courses(user_id: str) -> list:
    """
    Return the user's enrolled courses, collapsed to ONE row per **abstract**
    ``course_id``.

    A user can hold the same abstract course across multiple terms (e.g. CS101 in
    Fall 2025 *and* Spring 2026 = two enrollments/offerings sharing one abstract
    ``course_id``). This list is consumed as *abstract courses* — the dashboard
    course count, the /tree filter chips, and the quiz / study / notetaker /
    upload course pickers all key on ``course_id`` — so the old per-enrollment
    fan-out surfaced the same course twice (#449, findings F1/F3). We collapse
    here instead of leaving every consumer to de-dupe.

    Collapse rule: one row per ``course_id``; the **most recent** enrollment
    (latest ``enrolled_at`` — rows arrive ordered ``enrolled_at.asc``, so the
    last occurrence wins) is the representative for
    ``enrollment_id``/``color``/``nickname``/``term``/``enrolled_at``.
    ``node_count`` is the graph-node count for the abstract course (the graph
    keys on ``course_id``), counted **once** — never doubled across offerings.
    Per-enrollment detail is preserved, not dropped: ``enrollment_ids`` and
    ``terms`` carry every offering the user holds for the course. (Gradebook /
    analytics still resolve per-enrollment/term via their own enrollment-keyed
    endpoints, not this abstract-course list.)

    Returns list of dicts with: enrollment_id, course_id (abstract), course_code,
    course_name, school, department, color, nickname, term, node_count,
    enrolled_at, enrollment_ids, terms.
    """
    return [
        _course_entry(group, len(_course_node_ids(user_id, group[0])))
        for group in _collapse_enrollments(_user_enrolled_courses(user_id))
    ]


#: Per-course node-count reads in flight at once in :func:`aget_courses`.
_COURSE_COUNT_CONCURRENCY = 8


async def aget_courses(user_id: str) -> list:
    """Async twin of :func:`get_courses` (#117): the per-course node counts
    run concurrently (at most ``_COURSE_COUNT_CONCURRENCY`` at a time), in
    the same order."""
    gate = asyncio.Semaphore(_COURSE_COUNT_CONCURRENCY)

    async def entry(group) -> dict:
        async with gate:
            node_rows = await table("graph_nodes").aselect(
                "id", filters=_course_nodes_filters(user_id, group[0]),
            ) or []
        return _course_entry(group, len(node_rows))

    groups = _collapse_enrollments(await _auser_enrolled_courses(user_id))
    return list(await asyncio.gather(*(entry(g) for g in groups)))


def _collapse_enrollments(
    rows: list[dict],
) -> list[tuple[str, dict, list[str], list[str]]]:
    """Collapse enrollments to one representative row per abstract course_id,
    preserving first-seen order, while accumulating every enrollment id / term.
    Returns ``(course_id, representative, enrollment_ids, terms)`` groups."""
    order: list[str] = []
    reps: dict[str, dict] = {}
    enrollment_ids: dict[str, list[str]] = {}
    terms: dict[str, list[str]] = {}
    for r in rows:
        course_id = r.get("course_id")  # abstract
        if not course_id:
            continue
        if course_id not in reps:
            order.append(course_id)
            enrollment_ids[course_id] = []
            terms[course_id] = []
        reps[course_id] = r  # last (most recent enrolled_at) wins as representative
        eid = r.get("id")
        if eid and eid not in enrollment_ids[course_id]:
            enrollment_ids[course_id].append(eid)
        term_label = r.get("term")
        if term_label and term_label not in terms[course_id]:
            terms[course_id].append(term_label)
    return [(cid, reps[cid], enrollment_ids[cid], terms[cid]) for cid in order]


def _course_nodes_filters(user_id: str, course_id: str) -> dict:
    # Count nodes for this course (graph keys on the abstract course id).
    # Counted once per distinct course — the fan-out used to run this per
    # enrollment, double-counting the same abstract course's nodes.
    return {"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"}


def _course_node_ids(user_id: str, course_id: str) -> list:
    return table("graph_nodes").select(
        "id", filters=_course_nodes_filters(user_id, course_id),
    ) or []


def _course_entry(group: tuple[str, dict, list[str], list[str]], node_count: int) -> dict:
    course_id, r, enrollment_ids, terms = group
    course = r.get("courses", {}) if isinstance(r.get("courses"), dict) else {}
    return {
        "enrollment_id": r["id"],
        "course_id": course_id,
        "course_code": course.get("course_code", ""),
        "course_name": course.get("course_name", ""),
        "school": course.get("school", ""),
        "department": course.get("department", ""),
        "color": r.get("color"),
        "nickname": r.get("nickname"),
        "term": r.get("term", ""),
        "node_count": node_count,
        "enrolled_at": r.get("enrolled_at"),
        "enrollment_ids": enrollment_ids,
        "terms": terms,
    }


def _refresh_course_context(offering_id: str, user_id: str) -> None:
    """Refresh one offering's class aggregates after a write that touched them.

    A post-commit side effect: the write it follows stands, so a failure never
    reaches the caller, but it is logged with its traceback, never swallowed.
    The import sits outside the try, as in `_refresh_touched_course_contexts`:
    a broken import is a bug and propagates.
    """
    from services import course_context_service

    try:
        # inline, or a queued job when `jobs_queue` is on for the student (#116)
        course_context_service.refresh_course_context(offering_id, user_id=user_id)
    except Exception:
        logger.warning(
            "graph: course-context refresh failed offering=%s user=%s "
            "(the write it follows stands)",
            offering_id, user_id, exc_info=True,
        )


def add_course(
    user_id: str,
    course_id: str,
    color: str | None = None,
    nickname: str | None = None,
    term: str | None = None,
) -> dict:
    """
    Enroll a user in a course. ``course_id`` is the abstract catalog course id;
    the enrollment is created against an offering of that course (created if the
    catalog lacks one).

    ``term`` is an optional semester **label** (e.g. "Fall 2026") — the semester
    the caller is enrolling into (the active tab in the Courses & Semesters hub).
    When given and resolvable it picks that term's offering, so the course shows
    up under the tab the user was viewing instead of being silently dropped into
    the date-derived current term. When omitted/unresolvable it falls back to the
    current term.

    Single return contract: ``{course_id, already_existed, ...}`` —
    ``already_existed=True`` carries ``term`` (the label the course is already
    taken in; "" when unknown), ``already_existed=False`` means a fresh
    enrollment was created — or ``{course_id, error}`` when the course/term
    can't be resolved. The up-front no-retake check is the only
    already-existed path: ``resolve_offering``'s conflict retry (migration
    0036) makes a lost create race land on the winner's offering.
    """
    # Verify the abstract course exists in the catalog
    course_check = table("courses").select("id", filters={"id": f"eq.{course_id}"})
    if not course_check:
        return {"course_id": course_id, "error": "Course not found in catalog"}

    from services.academics import (
        resolve_offering,
        user_offering_ids_for_course,
        term_for_offering,
        term_id_for_label,
    )

    # No-retake rule: a course already enrolled in ANY term can't be added again.
    # (Broadens the old current-term-only check so cross-semester duplicates are
    # rejected instead of silently creating a second enrollment.)
    existing_offerings = user_offering_ids_for_course(user_id, course_id)
    if existing_offerings:
        existing_term = term_for_offering(existing_offerings[0]) or {}
        return {
            "course_id": course_id,
            "already_existed": True,
            "term": existing_term.get("label", ""),
        }

    # Resolve the requested semester label → term id. An unknown label yields
    # None, which resolve_offering treats as "current term".
    term_id = term_id_for_label(term) if term else None
    offering_id = resolve_offering(course_id, term_id=term_id, create=True)
    if not offering_id:
        return {"course_id": course_id, "error": "No term available to enroll into"}

    table("enrollments").insert({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "offering_id": offering_id,
        "color": color,
        "nickname": nickname,
    })
    _refresh_course_context(offering_id, user_id)
    return {"course_id": course_id, "already_existed": False}


def update_course_color(user_id: str, course_id: str, color: str) -> dict:
    """Update the color for a user's enrollment(s) of an abstract course."""
    from services.academics import user_offering_ids_for_course
    offering_ids = user_offering_ids_for_course(user_id, course_id)
    if not offering_ids:
        return {"updated": False}
    table("enrollments").update(
        {"color": color},
        filters={"user_id": f"eq.{user_id}", "offering_id": f"in.({','.join(offering_ids)})"},
    )
    return {"updated": True}


def update_course_nickname(user_id: str, course_id: str, nickname: str) -> dict:
    """Update the nickname for a user's enrollment(s) of an abstract course."""
    from services.academics import user_offering_ids_for_course
    offering_ids = user_offering_ids_for_course(user_id, course_id)
    if not offering_ids:
        return {"updated": False}
    table("enrollments").update(
        {"nickname": nickname},
        filters={"user_id": f"eq.{user_id}", "offering_id": f"in.({','.join(offering_ids)})"},
    )
    return {"updated": True}


def delete_node(user_id: str, node_id: str) -> dict:
    """Delete a single graph node and its edges. Owner-scoped.

    Returns 404 if the node doesn't belong to the user.
    """
    rows = table("graph_nodes").select(
        "id,course_id",
        filters={"id": f"eq.{node_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    ) or []
    if not rows:
        return {"error": "Node not found", "deleted": False}
    course_id = rows[0].get("course_id")

    table("graph_edges").delete(filters={"user_id": f"eq.{user_id}", "source_node_id": f"eq.{node_id}"})
    table("graph_edges").delete(filters={"user_id": f"eq.{user_id}", "target_node_id": f"eq.{node_id}"})
    table("graph_nodes").delete(filters={"id": f"eq.{node_id}", "user_id": f"eq.{user_id}"})

    if course_id:
        # course_id from graph_nodes is the abstract course; refresh each of the
        # user's offerings of that course (analytics is offering-scoped).
        from services.academics import user_offering_ids_for_course
        for offering_id in user_offering_ids_for_course(user_id, course_id):
            _refresh_course_context(offering_id, user_id)
    return {"deleted": True}


def update_node_color(user_id: str, node_id: str, color: str | None) -> dict:
    """Set or clear the per-node color override. Pass None to reset to course default."""
    rows = table("graph_nodes").select(
        "id",
        filters={"id": f"eq.{node_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    ) or []
    if not rows:
        return {"error": "Node not found", "updated": False}
    table("graph_nodes").update(
        {"color": color},
        filters={"id": f"eq.{node_id}", "user_id": f"eq.{user_id}"},
    )
    return {"updated": True}


def delete_course(user_id: str, course_id: str, term: str | None = None) -> dict:
    """
    Drop ONE term's enrollment in an abstract course (#766).

    ``term`` is a semester label (or term id) — the tab the student removed the
    course from. Omitted, it means the current term. Only enrollments in that
    term's offerings are deleted: an enrollment row cascades to its
    assignments, grades, gradescope links and topic checklists (0021/0027 and
    later), so deleting every term's enrollment — the old behavior — erased a
    student's PAST terms' gradebooks to drop this term's class.

    Graph nodes are never touched: the knowledge graph lives on the abstract
    course and mastery is cumulative across terms, so the nodes stay for any
    remaining enrollment and for a later re-enrollment.

    Returns ``{"deleted": bool}``; ``{"deleted": False, "error": ...}`` when the
    term label doesn't resolve, or when no term was given and the student holds
    this course only in other terms (the caller must name which one to drop).
    Nothing to delete in the targeted term is an idempotent ``deleted: False``.
    """
    from services.academics import (
        current_term,
        term_for_offering,
        term_id_for_label,
        user_offering_ids_for_course,
    )
    if term:
        term_id = term_id_for_label(term)
        if not term_id:
            return {"deleted": False, "error": f"Unknown term: {term}"}
    else:
        cur = current_term()
        term_id = cur["id"] if cur else None
    held = user_offering_ids_for_course(user_id, course_id)
    offering_ids = [
        oid for oid in held
        if term_id and (term_for_offering(oid) or {}).get("id") == term_id
    ]
    if not offering_ids:
        if held and not term:
            return {
                "deleted": False,
                "error": "Not enrolled in this course in the current term; "
                         "pass the term to drop",
            }
        return {"deleted": False}
    for offering_id in offering_ids:
        table("enrollments").delete(
            {"user_id": f"eq.{user_id}", "offering_id": f"eq.{offering_id}"}
        )
        _refresh_course_context(offering_id, user_id)
    return {"deleted": True}


def _normalize_concept(name: str) -> str:
    """Case-fold + collapse whitespace so dedup is tolerant of LLM casing/spacing drift."""
    return " ".join((name or "").split()).casefold()


def add_node(
    user_id: str,
    concept_name: str,
    course_id: str,
    anchor_node_id: str | None = None,
    initial_mastery: float = 0.0,
) -> dict:
    """Create-or-merge one manually named concept (#330).

    A thin wrapper over apply_graph_update so the dedup, edge machinery, and
    offering-analytics refresh stay in one place (routes never write
    graph_nodes/graph_edges directly). The anchor id resolves to its concept
    NAME because apply_graph_update's edge _lookup is name-keyed; a stale or
    out-of-course anchor silently drops the edge, never the node. Returns
    {"node": <canonical row>, "already_existed": bool} so the UI can toast
    merge-vs-create and reconcile its optimistic id.

    Dedup caveat (pre-existing, inherited from apply_graph_update): the
    case/whitespace folding is Python-side, while the 0023 constraint is a
    case-SENSITIVE UNIQUE. Two concurrent adds differing only in case can
    therefore both land, and `already_existed` is computed from a pre-read
    that can go stale under the same race. Sequential use — every path the
    UI offers — dedups correctly. Tracked separately for a citext/functional
    index rather than widened here.
    """
    name = " ".join((concept_name or "").split())
    if not name:
        raise ValueError("concept_name must be non-empty")
    if not course_id:
        raise ValueError("course_id is required")
    norm = _normalize_concept(name)
    scope = {"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"}

    pre = table("graph_nodes").select("id,concept_name", filters=scope) or []
    already_existed = any(
        _normalize_concept(r.get("concept_name") or "") == norm for r in pre
    )

    update: dict = {
        "new_nodes": [
            {"concept_name": name, "course_id": course_id, "initial_mastery": initial_mastery},
        ],
    }
    if anchor_node_id:
        # Scoped to the target course as well as the user: apply_graph_update
        # resolves edge endpoints by NAME *within* the course, so an anchor
        # from another course could silently wire to a same-named node here
        # instead of being dropped as stale (PR #485 review).
        anchor_rows = table("graph_nodes").select(
            "id,concept_name",
            filters={
                "id": f"eq.{anchor_node_id}",
                "user_id": f"eq.{user_id}",
                "course_id": f"eq.{course_id}",
            },
        ) or []
        anchor_name = (anchor_rows[0].get("concept_name") if anchor_rows else "") or ""
        if anchor_name and _normalize_concept(anchor_name) != norm:
            update["new_edges"] = [
                {"source": anchor_name, "target": name, "relationship_type": "related", "strength": 0.5},
            ]

    apply_graph_update(user_id, update, course_id=course_id)

    rows = table("graph_nodes").select(
        "id,concept_name,course_id,mastery_score,mastery_tier", filters=scope,
    ) or []
    node = next(
        (r for r in rows if _normalize_concept(r.get("concept_name") or "") == norm),
        None,
    )
    if node is None:
        raise RuntimeError(f"add_node: {name!r} missing after apply_graph_update")
    return {"node": node, "already_existed": already_existed}


# ── PKG-03: the evidence path (spec §5) ──────────────────────────────────────
# Everything in this section runs only when a graph update carries a non-empty
# "evidence" list (or, for the §13 A123 void, a "void_evidence" alone); the
# topology keys (new_nodes / new_edges) never reach it.


def _prerequisite_edges(user_id: str, node_id: str) -> list[tuple[str, str]]:
    """(source_node_id, target_node_id) prerequisite pairs touching node_id.
    Two reads: the filter dict has no OR across columns (graph_read.py)."""
    pairs: set[tuple[str, str]] = set()
    for col in ("source_node_id", "target_node_id"):
        rows = table("graph_edges").select(
            "source_node_id,target_node_id",
            filters={
                "user_id": f"eq.{user_id}",
                "relationship_type": f"eq.{PREREQ_RELATIONSHIP_TYPE}",
                col: f"eq.{node_id}",
            },
        ) or []
        for r in rows:
            src, tgt = r.get("source_node_id"), r.get("target_node_id")
            if src and tgt:
                pairs.add((src, tgt))
    return sorted(pairs)


def _propagation_targets(user_id: str, ev: Evidence) -> list[bkt.Propagation]:
    """ADAPTER — the one place bkt.propagate_prereq's signature is assumed
    (HANDOFF-01: `propagate_prereq(evidence_correct, parents, children) ->
    [(node_id, channel, correct, weight)]`). Resolves the evidence node's
    prerequisite parents and dependent children from graph_edges, honoring
    EDGE_PREREQ_SOURCE_IS_PREREQ; bkt picks which side moves."""
    edges = _prerequisite_edges(user_id, ev.node_id)
    if not edges:
        return []
    parents: list[str] = []
    children: list[str] = []
    for src, tgt in edges:
        prereq, dependent = (src, tgt) if EDGE_PREREQ_SOURCE_IS_PREREQ else (tgt, src)
        if dependent == ev.node_id and prereq != ev.node_id:
            parents.append(prereq)
        elif prereq == ev.node_id and dependent != ev.node_id:
            children.append(dependent)
    # idk evidence is never correct (Evidence validates it), so it walks the
    # incorrect side like any miss.
    return bkt.propagate_prereq(ev.correct, parents, children)


def _fsrs_after(
    st: LearnerState, ev: Evidence, now: datetime, retention: float | None = None
) -> None:
    """learning.evidence_replay.fsrs_after over an Evidence (the FSRS adapter
    lives there since spec §13 A123, shared with the journal replay)."""
    evidence_replay.fsrs_after(
        st, channel=ev.channel, correct=ev.correct, max_rung=ev.max_rung, idk=ev.idk,
        now=now, retention=retention,
    )


#: The propagation decay-anchor adapter (learning.evidence_replay since A123).
_keep_decay_anchor = evidence_replay.keep_decay_anchor


def _apply_evidence(
    user_id: str,
    evidences: list[Evidence],
    by_id: dict[str, dict],
    touched_courses: set,
    now: datetime,
    retention: float | None = None,
    *,
    _course_id: str | None = None,
) -> tuple[list[dict], bool]:
    """All graded evidence commits through one transactional RPC, or none does.

    Untagged quiz/review/posttest provenance remains NULL. Only the graph
    entry point reaches this transport; no unsafe table-write fallback exists.
    """
    from learning.evidence_transaction import commit_evidence_transaction

    def compute(prepared):
        return _calculate_evidence(user_id, evidences, prepared, retention)

    changes, _receipt, newly_committed = commit_evidence_transaction(
        user_id, _course_id, evidences, retention, compute
    )
    for ev in evidences:
        row = by_id.get(ev.node_id)
        if row and row.get("course_id"):
            touched_courses.add(row["course_id"])
    return changes, newly_committed


def _calculate_evidence(user_id: str, evidences: list[Evidence], prepared, retention) -> list[dict]:
    """The existing Python BKT/FSRS math, preparing rows without database I/O.

    Per evidence, in order: ownership → same-session recheck → weight →
    decayed read → bkt.update → counters → FSRS → learner_state → graph_nodes
    mirror → ONE journal row → one-hop propagation (learner_state + mirror
    only). Propagated updates are derived from the journaled evidence, so
    they are not journaled themselves. `by_id` is the user- and
    course-scoped existing_rows; a node outside it is never read or written.

    The journal rows of one call share `created_at` and have random ids, so
    each carries `evidence_seq` = 0..n−1 in apply order (§13 A36): a replay
    orders by (created_at, evidence_seq). A skipped evidence takes no number.

    §13 A123: the state transition is learning.evidence_replay's `observe` /
    `propagate` — the same code the journal replay runs — and each row also
    journals what its replay needs beyond the observation: the FSRS
    `retention` it was scheduled at, its final `same_session_recheck` flag and
    the nodes its propagation moved (`propagated_to`).
    """
    by_id, now = prepared.nodes, prepared.now
    changes: list[dict] = []
    now_iso = now.isoformat()
    target_retention = FSRS_RETENTION_DEFAULT if retention is None else retention
    owned = [ev.node_id for ev in evidences if ev.node_id in by_id]
    # One batched read; nodes with no row start at the prior. The cache means
    # a later evidence on the same node sees the earlier posterior (elapsed
    # time between the two is zero: they share `now`).
    states = prepared.states
    for node_id in owned:
        states.setdefault(node_id, LearnerState(user_id=user_id, node_id=node_id))
    seen_checks: set[tuple[str, str]] = set()
    exposed_hashes: set[str] = set()
    seq = 0  # next evidence_seq: counts journaled rows only

    for ev in evidences:
        row = by_id.get(ev.node_id)
        if row is None:
            logger.warning(
                "graph: evidence skipped node=%s user=%s (not owned or outside course)",
                ev.node_id, user_id,
            )
            continue
        if ev.session_id and ev.question_hash:
            key = (ev.session_id, ev.question_hash)
            if (key in seen_checks or prepared.prior_check(ev)) and not ev.same_session_recheck:
                ev = Evidence.model_validate({**ev.model_dump(), "same_session_recheck": True})
            seen_checks.add(key)
        if ev.question_hash:
            already_exposed = ev.question_hash in exposed_hashes or prepared.prior_exposure(ev)
            if (already_exposed and ev.planning_provenance is not None
                    and not ev.planning_provenance.previously_seen):
                ev = Evidence.model_validate({
                    **ev.model_dump(),
                    "planning_provenance": {
                        **ev.planning_provenance.model_dump(), "previously_seen": True,
                    },
                })
            exposed_hashes.add(ev.question_hash)
        w = evidence_weight(ev)

        st = states[ev.node_id]
        # weight 0.0 (correct after H4..H6) returns p_before unchanged; a
        # correct re-check of a question already asked this session is not a
        # first attempt (spec §3.3): an opportunity only, it neither extends
        # nor breaks the streak †.
        p_before, p_after = evidence_replay.observe(
            st, channel=ev.channel, correct=ev.correct, idk=ev.idk, assisted=ev.assisted,
            max_rung=ev.max_rung, weight=w, recheck=ev.same_session_recheck, now=now,
            retention=retention,
        )
        prepared.state_rows[st.node_id] = state_row(st, now)
        st.exists = True
        # The propagated observation carries the evidence's own weight too
        # (spec §5: weight = product of the applicable §3.1 weights) †, and
        # w == 0.0 (correct after H4..H6, §3.3 "no upward BKT evidence")
        # moves no neighbour.
        targets = evidence_replay.propagation_targets(
            ev.node_id, ev.correct, w, prepared.snapshot["edges"], by_id
        )

        # A tagged grade needs durable readiness provenance before any scalar
        # or mirrored BKT mutation. A failed append cannot silently lose it.
        reason = f"evidence:{ev.channel}:idk" if ev.idk else f"evidence:{ev.channel}"
        event_row = {
            "id": prepared.event_id(seq), "node_id": row["id"], "delta": p_after - p_before,
            "reason": reason, "created_at": now_iso, "event_type": EVIDENCE_EVENT_TYPE,
            "channel": ev.channel, "correct": ev.correct, "weight": w,
            "assisted": ev.assisted, "max_rung": ev.max_rung,
            "p_before": p_before, "p_after": p_after, "session_id": ev.session_id,
            "check_item_id": ev.check_item_id, "question_hash": ev.question_hash,
            "confidence": ev.confidence, "grader_backend": ev.grader_backend,
            "evidence_seq": seq,
            # §13 A123: what a replay of this row needs beyond the observation
            "retention": target_retention,
            "same_session_recheck": ev.same_session_recheck,
            "propagated_to": [target_id for target_id, *_ in targets],
        }
        if ev.student_confidence is not None:
            # Spec §13 A127: the student's stated confidence, beside the
            # grader's `confidence` (never the same column). Absent when none
            # was stated, so an evidence row without one is the row it was
            # before A127 — its plan, and its operation's fingerprint, unchanged.
            event_row["student_confidence"] = ev.student_confidence
        if ev.multi_concept:
            # Spec §13 A141: the row a multi-concept item graded says so in the
            # journal itself — the item's own row may later be withdrawn (A23)
            # or retired (A123), and the item statistics must still tell it
            # from the apex's own items. Absent on every other row, so its
            # plan, and its operation's fingerprint, are unchanged.
            event_row["multi_concept"] = True
        provenance = planning_observation(ev)
        if provenance is not None:
            event_row["planning_observation"] = provenance

        times = (row.get("times_studied") or 0) + 1
        mirror = {
                "mastery_score": p_after,
                "mastery_tier": bkt.tier_for(p_after),
                "times_studied": times,
                "last_studied_at": now_iso,
            }
        prepared.mirrors[row["id"]] = {**prepared.mirrors.get(row["id"], {}), "id": row["id"], **mirror}
        row["times_studied"] = times
        row["mastery_score"] = p_after

        prepared.events.append(event_row)
        seq += 1
        changes.append({"concept": row["concept_name"], "before": p_before, "after": p_after})

        for target_id, channel, target_correct, weight in targets:
            trow = by_id[target_id]
            tst = states.get(target_id)
            if tst is None:
                tst = LearnerState(
                    user_id=user_id, node_id=target_id
                )
                states[target_id] = tst
            # tst.p_known stays the belief AT now (a later evidence in this
            # call reads it); the row is stored against the kept anchor.
            p_stored = evidence_replay.propagate(
                tst, channel=channel, correct=target_correct, weight=weight,
                source_weight=w, now=now,
            )
            prepared.state_rows[tst.node_id] = state_row(replace(tst, p_known=p_stored), now)
            tst.exists = True
            mirror = {"mastery_score": tst.p_known, "mastery_tier": bkt.tier_for(tst.p_known)}
            prepared.mirrors[target_id] = {**prepared.mirrors.get(target_id, {}), "id": target_id, **mirror}
            trow["mastery_score"] = tst.p_known
    return changes


# ── §13 A123: void + recompute (a branch of the same single writer) ─────────


def _apply_void(user_id: str, course_id: str, question_hash: str) -> tuple[list[dict], dict]:
    """Void every evidence row this student has graded against the retired
    course item and write their recomputed state, in ONE transaction
    (learning.evidence_transaction.commit_void_transaction). Returns (the
    recomputed nodes' {concept, before, after}, the commit's counts)."""
    from learning.evidence_transaction import commit_void_transaction

    def compute(snapshot):
        return _calculate_void(user_id, course_id, question_hash, snapshot)

    return commit_void_transaction(user_id, course_id, question_hash, compute)


def _calculate_void(user_id: str, course_id: str, question_hash: str, snapshot: dict):
    """The void plan, from a void snapshot, without database I/O.

    Voids: every one of the student's evidence rows graded against the item
    (a check_item_id and the item's question_hash; rows already void are named
    too, so the commit can check the set is whole). Recomputed: every node such
    a row moved — its own concept and the nodes its propagation moved
    (learning.evidence_replay.moved_by) — at the state a replay of the course's
    NON-void journal (this item's rows and every earlier void left out) gives:
    the learner_state row the writer would have stored and the mirror it would
    hold. A node no non-void row reaches any more is back at the BKT prior
    (exactly what read_state answers for a node with no row), its row stamped
    with the latest voided row that touched it, so the plan is a pure function
    of the journal and a re-run writes nothing. Misconceptions: the open rows
    every supporting attempt of which was graded against a retired item of
    the course (learning.evidence_void.closable_misconceptions)."""
    from learning.evidence_transaction import EvidenceVoidRefused, VoidPlan
    from learning.evidence_void import closable_misconceptions

    if snapshot.get("retired") is not True:
        raise EvidenceVoidRefused("The check item is not retired")
    nodes = {n["id"]: n for n in snapshot["nodes"]}
    owned = frozenset(nodes)
    edges = snapshot["edges"]
    journal = snapshot["journal"]
    item_rows = [
        r for r in journal if r.get("question_hash") == question_hash and r.get("check_item_id")
    ]
    void_ids = {r["id"] for r in journal if r.get("void")} | {r["id"] for r in item_rows}
    replayed = evidence_replay.replay(
        [evidence_replay.observation(r) for r in journal if r["id"] not in void_ids],
        user_id=user_id, edges=edges, owned=owned,
    )
    touched_by_void: dict[str, datetime] = {}
    for row in item_rows:
        ob = evidence_replay.observation(row)
        for node_id in evidence_replay.moved_by(ob, edges=edges, owned=owned):
            if node_id in owned:
                touched_by_void[node_id] = max(touched_by_void.get(node_id, ob.at), ob.at)
    stored = {s["node_id"]: s for s in snapshot["states"]}
    state_rows, mirrors, changes = [], [], []
    for node_id in sorted(touched_by_void):
        if node_id in replayed.state_rows:
            row, belief = replayed.state_rows[node_id], replayed.mirrors[node_id]
        else:
            row = state_row(LearnerState(user_id=user_id, node_id=node_id), touched_by_void[node_id])
            belief = row["p_known"]
        state_rows.append(row)
        mirrors.append({"id": node_id, "mastery_score": belief, "mastery_tier": bkt.tier_for(belief)})
        changes.append({
            "concept": nodes[node_id].get("concept_name"),
            "before": nodes[node_id].get("mastery_score"),
            "after": belief,
        })
    retired = set(snapshot.get("retired_hashes") or []) | {question_hash}
    misconceptions = closable_misconceptions(
        snapshot.get("misconceptions") or [],
        course_id=course_id,
        retired_hashes=retired,
        retired_check_ids={
            r["check_item_id"] for r in journal
            if r.get("check_item_id") and r.get("question_hash") in retired
        },
    )
    return VoidPlan(
        payload={
            "voids": sorted(r["id"] for r in item_rows),
            "nodes": [{"id": n, "version": nodes[n]["evidence_version"]} for n in sorted(touched_by_void)],
            "states_expected": [
                {"node_id": n, "version": stored[n]["evidence_version"] if n in stored else None}
                for n in sorted(touched_by_void)
            ],
            "edges": edges,
            "state_rows": state_rows,
            "mirrors": mirrors,
            "misconceptions": misconceptions,
        },
        changes=changes,
    )


def _existing_node_rows(user_id: str, course_id: str | None) -> list[dict]:
    """The user's existing node rows (scoped to the course when given): the
    update's one read of graph_nodes. The evidence branch keys them by id (a
    node outside them is never read or written), the topology by name."""
    fetch_filters = {"user_id": f"eq.{user_id}"}
    if course_id:
        fetch_filters["course_id"] = f"eq.{course_id}"
    return table("graph_nodes").select(
        "id,concept_name,mastery_score,times_studied,course_id",
        filters=fetch_filters,
    ) or []


def _existing_nodes_by_name(existing_rows: list[dict]) -> dict[str, dict]:
    """Normalized name → the user's existing node row.

    The UNIQUE (user_id, course_id, concept_name) constraint from 0023 prevents
    duplicates; this map resolves evidence / new_edges against pre-existing
    rows.
    """
    by_name: dict[str, dict] = {}
    for row in existing_rows:
        norm = _normalize_concept(row.get("concept_name") or "")
        if norm:
            by_name[norm] = row
    return by_name


def _upsert_new_nodes(
    user_id: str,
    new_nodes: list[NewNode],
    course_id: str | None,
    by_name: dict[str, dict],
    touched_courses: set,
) -> dict[str, dict]:
    """Create the batch's new concepts; return them keyed by normalized name.

    A concept that already exists (or appeared earlier in the batch) is skipped,
    as is a blank name.
    """
    inserted_in_batch: dict[str, dict] = {}
    for new_node in new_nodes:
        name = new_node.concept_name
        if not name:
            continue
        norm = _normalize_concept(name)
        if norm in by_name or norm in inserted_in_batch:
            continue

        node_course_id = course_id or new_node.course_id
        init_m = new_node.initial_mastery

        new_id = str(uuid.uuid4())
        # UNIQUE-backed upsert (0023) replaces the old select-then-insert. On a
        # pre-existing (user_id, course_id, concept_name) the row is merged rather
        # than duplicated. Read the canonical id back from the representation so
        # later edge/update writes target the surviving row.
        returned = table("graph_nodes").upsert(
            {
                "id": new_id,
                "user_id": user_id,
                "concept_name": name,
                "mastery_score": init_m,
                "mastery_tier": bkt.tier_for(init_m),
                "course_id": node_course_id,
            },
            on_conflict="user_id,course_id,concept_name",
        )
        canonical_id = new_id
        if returned and isinstance(returned, list) and isinstance(returned[0], dict):
            canonical_id = returned[0].get("id", new_id)
        # Track in-batch inserts so subsequent new_edges in the
        # same call resolve against just-created nodes.
        inserted_in_batch[norm] = {
            "id": canonical_id,
            "concept_name": name,
            "mastery_score": init_m,
            "times_studied": 0,
            "course_id": node_course_id,
        }
        if node_course_id:
            touched_courses.add(node_course_id)
    return inserted_in_batch


def _upsert_new_edges(user_id: str, new_edges: list[NewEdge], lookup) -> None:
    """Wire each edge whose two endpoints resolve to distinct known concepts."""
    for new_edge in new_edges:
        if not new_edge.source or not new_edge.target:
            continue
        src = lookup(new_edge.source)
        tgt = lookup(new_edge.target)
        if not src or not tgt:
            continue
        if src["id"] == tgt["id"]:
            continue

        # UNIQUE-backed upsert (0023) on (user_id, source, target, relationship_type)
        # replaces the old select-then-insert; the DB dedups, so re-emitted edges
        # are idempotent.
        table("graph_edges").upsert(
            {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "source_node_id": src["id"],
                "target_node_id": tgt["id"],
                "strength": new_edge.strength,
                "relationship_type": new_edge.relationship_type,
            },
            on_conflict="user_id,source_node_id,target_node_id,relationship_type",
        )


def _refresh_touched_course_contexts(user_id: str, touched_courses: set) -> None:
    """Refresh the offering-scoped course context of every course the batch touched.

    touched_courses holds abstract course ids (the graph key). Analytics is
    offering-scoped, so refresh each of this user's offerings of those courses.
    Best-effort — the graph is already written — but a failure is logged, not
    swallowed.
    """
    # Function-level on purpose: course_context_service runs the course-summary
    # agent, so a top-level import drags the agents stack into every
    # graph_service importer and closes a loop (agents.tools.graph ->
    # graph_service -> course_context_service -> agents.course_summary). It
    # sits OUTSIDE the try below: an ImportError is a bug and propagates; only
    # the refresh's runtime failure is logged and passed over.
    from services import course_context_service

    for cid in touched_courses:
        for offering_id in academics.user_offering_ids_for_course(user_id, cid):
            try:
                course_context_service.refresh_course_context(offering_id, user_id=user_id)
            except Exception:
                logger.warning(
                    "graph: course-context refresh failed after graph update "
                    "user=%s offering=%s", user_id, offering_id, exc_info=True,
                )


def _dispatch_graph_achievements(user_id: str) -> None:
    """Fire the three graph-driven achievement stats.

    The knowledge graph is the ONLY thing that advances these three stats, so
    this is the only place they can be dispatched from. Without it `rooted`,
    `branching`, `canopy` (concepts_mastered), `web` (graph_nodes_count) and
    `polymath` (courses_with_mastery) are live badges nothing can ever award.
    Dispatched at the end rather than beside the touch_streak_safe call on
    purpose: graph_nodes_count grows when nodes are created, which happens on
    updates that change no mastery at all. Post-commit side effect — the graph
    is already written, so a failure here must not propagate into the caller's
    turn.
    """
    try:
        achievement_service.check_achievements(user_id, "graph_nodes_count", {})
        achievement_service.check_achievements(user_id, "concepts_mastered", {})
        achievement_service.check_achievements(user_id, "courses_with_mastery", {})
    except Exception:
        logger.exception("achievement dispatch failed after graph update user=%s", user_id)


def _refuse_flat_deltas(graph_update: GraphUpdate | dict) -> None:
    """PKG-14b (spec §11.2): the flat-delta path is gone — the legacy tutor's
    mastery tool and the quiz deltas were its only producers. Loud, and before
    any read or write, so a stale caller can never half-apply."""
    if isinstance(graph_update, dict) and "updated_nodes" in graph_update:
        raise ValueError("updated_nodes is no longer accepted (PKG-14b): pass evidence")


def _void_question_hash(graph_update: dict, course_id: str | None) -> str:
    """§13 A123: the retired item's question_hash a `void_evidence` update
    names — applied alone (never mixed with evidence or topology), in the
    item's course; a malformed one raises before any read or write."""
    void = graph_update["void_evidence"]
    question_hash = void.get("question_hash") if isinstance(void, dict) else None
    if set(graph_update) != {"void_evidence"} or not course_id:
        raise ValueError("void_evidence is applied alone, in the item's course")
    if not isinstance(question_hash, str) or not question_hash:
        raise ValueError("void_evidence names the retired item's question_hash")
    return question_hash


def _after_void(user_id: str, course_id: str, counts: dict) -> None:
    """§13 A123: after a void commit (`_apply_void`, called by
    apply_graph_update itself: the single writer's private branch), log what it
    did; the offering aggregates read the mirrors it moved, so they are
    refreshed after the commit."""
    logger.info(
        "graph: evidence void user=%s course=%s voided=%d states=%d mirrors=%d "
        "misconceptions_closed=%d",
        user_id, course_id, counts["voided"], counts["states"], counts["mirrors"],
        counts["misconceptions"],
    )
    if counts["states"] or counts["mirrors"]:
        _refresh_touched_course_contexts(user_id, {course_id})


def _validated_evidence(update: GraphUpdate) -> list[Evidence]:
    """PKG-03: every evidence validated BEFORE any read or write; an invalid
    item raises pydantic.ValidationError (the caller maps it to a 4xx). An
    Evidence instance is re-validated from its dump too: the model is mutable,
    and an attribute set after construction skips the validators. Tagged
    evidence (planning provenance) never rides with topology mutations."""
    evidences = [
        Evidence.model_validate(e.model_dump() if isinstance(e, Evidence) else e)
        for e in update.evidence
    ]
    if any(ev.planning_provenance is not None for ev in evidences) and (
        update.new_nodes or update.new_edges
    ):
        raise ValueError("Tagged evidence cannot be mixed with graph topology mutations")
    return evidences


def apply_graph_update(
    user_id: str,
    graph_update: GraphUpdate | dict,
    course_id: str | None = None,
    *,
    retention: float | None = None,
    defer: Callable[[Callable[[], None]], object] | None = None,
) -> list:
    """
    Apply a graph update to the DB. Returns mastery_changes list.
    If course_id is provided, all new/updated nodes will be associated with that course.

    Graded evidence (``evidence``, learning-loop PKG-03) is the ONLY thing that
    moves a belief (PKG-14b, spec §11.2): an ``updated_nodes`` flat delta is
    refused before any read or write. ``void_evidence`` (spec §13 A123) is the
    staff-retire branch of the same single writer, applied alone.

    `retention` (PKG-12, a PKG-03 reopen) is the FSRS retention target the
    evidence branch schedules `fsrs_due_at` at; None keeps
    FSRS_RETENTION_DEFAULT. Only the evidence branch reads it.

    `defer`: where to run the class-aggregate refresh this update triggers
    (`refresh_course_context` for each touched offering). That refresh can make
    an LLM call (the offering summary, regenerated whenever the stats change),
    and nothing the caller returns depends on it — so a route that can run work
    after its response passes `background_tasks.add_task` here. Omitted, the
    refresh runs inline, as it always has.

    ``graph_update`` is a :class:`services.graph_update_model.GraphUpdate` or the
    dict of that shape (``new_nodes`` / ``new_edges`` / ``evidence``); a dict is
    validated into the model first, as leniently as this function always read
    its topology (see that module).

    Concept dedup is case- and whitespace-insensitive: "Linear Regression",
    "linear regression", and " Linear  Regression " all resolve to the same node.
    """
    _refuse_flat_deltas(graph_update)
    if isinstance(graph_update, dict) and "void_evidence" in graph_update:
        # §13 A123: a staff retire voids this student's evidence graded against
        # the course item and writes the state a replay of the non-void journal
        # gives — alone, in the item's course, before any other read or write.
        changes, counts = _apply_void(user_id, course_id, _void_question_hash(graph_update, course_id))
        _after_void(user_id, course_id, counts)
        return changes
    update = GraphUpdate.coerce(graph_update)
    evidences = _validated_evidence(update)
    touched_courses: set = set()

    existing_rows = _existing_node_rows(user_id, course_id)
    by_name = _existing_nodes_by_name(existing_rows)
    inserted_in_batch = _upsert_new_nodes(
        user_id, update.new_nodes, course_id, by_name, touched_courses,
    )

    def _lookup(name: str) -> dict | None:
        norm = _normalize_concept(name)
        return by_name.get(norm) or inserted_in_batch.get(norm)

    mastery_changes: list = []
    newly_committed = False
    if evidences:
        # PKG-03: graded evidence is the only thing that moves p_known (spec
        # §1). This block is skipped entirely when the payload carries none.
        by_id = {r["id"]: r for r in existing_rows if r.get("id")}
        mastery_changes, newly_committed = _apply_evidence(
            user_id,
            evidences,
            by_id,
            touched_courses,
            datetime.now(timezone.utc),
            retention,
            _course_id=course_id,
        )
    if mastery_changes and newly_committed:
        # services/streak_service.py::touch_streak is the sole writer of
        # streak_count/longest_streak (UTC calendar days); mastery activity
        # legitimately counts as a study day. Receipt replay is recovery of
        # earlier activity, never a new study day. This stays a call site, but
        # the maths lives in exactly one place — not duplicated here.
        touch_streak_safe(user_id)

    _upsert_new_edges(user_id, update.new_edges, _lookup)
    if touched_courses:
        refresh = partial(_refresh_touched_course_contexts, user_id, frozenset(touched_courses))
        if defer is not None:
            defer(refresh)
        else:
            refresh()
    _dispatch_graph_achievements(user_id)
    return mastery_changes


def _recommendation_filters(user_id: str, semester: str | None) -> dict | None:
    """The graph_nodes filters for the user's recommendations, or None when the
    semester scope leaves nothing to recommend. Sync: a semester resolves
    through services/academics.py (the async reader hops it off the loop)."""
    filters = {
        "user_id": f"eq.{user_id}",
        "mastery_tier": "in.(struggling,learning,unexplored)",
    }
    if semester:
        allowed = _semester_course_ids(user_id, semester)
        # Unresolved label / no enrollment in that term → no recommendations.
        if not allowed:
            return None
        filters["course_id"] = f"in.({','.join(allowed)})"
    return filters


_RECOMMENDATION_READ = {
    "order": "mastery_score.asc",
    "limit": 5,
}
_RECOMMENDATION_COLUMNS = "concept_name,mastery_score,mastery_tier,course_id"


def get_recommendations(user_id: str, semester: str | None = None) -> list:
    filters = _recommendation_filters(user_id, semester)
    if filters is None:
        return []
    rows = table("graph_nodes").select(
        _RECOMMENDATION_COLUMNS, filters=filters, **_RECOMMENDATION_READ,
    )
    return _recommendations_from(rows)


async def aget_recommendations(user_id: str, semester: str | None = None) -> list:
    """Async twin of :func:`get_recommendations` (#117)."""
    filters = (
        await run_in_threadpool(_recommendation_filters, user_id, semester)
        if semester else _recommendation_filters(user_id, None)
    )
    if filters is None:
        return []
    rows = await table("graph_nodes").aselect(
        _RECOMMENDATION_COLUMNS, filters=filters, **_RECOMMENDATION_READ,
    )
    return _recommendations_from(rows)


def _recommendations_from(rows: list) -> list:
    recs = []
    for r in rows:
        tier = r["mastery_tier"]
        if tier == "unexplored":
            reason = "You haven't studied this yet — a great place to start."
        elif tier == "struggling":
            reason = f"You're struggling here ({int(r['mastery_score']*100)}%) — focus here to improve."
        else:
            reason = f"You're making progress ({int(r['mastery_score']*100)}%) — keep going!"
        recs.append({"concept_name": r["concept_name"], "reason": reason})
    return recs
