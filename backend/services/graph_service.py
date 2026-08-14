from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from config import get_mastery_tier
from db.connection import table
from services.streak_service import touch_streak_safe

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


def _user_enrolled_courses(user_id: str) -> list[dict]:
    """All courses a user is enrolled in, via enrollments → course_offerings →
    courses/terms, reshaped to the legacy flat shape (abstract course_id + nested
    courses dict + offering_id + term label)."""
    try:
        rows = table("enrollments").select(
            "id,offering_id,color,nickname,enrolled_at,"
            "course_offerings!inner(course_id,"
            "courses!inner(course_code,course_name,department),terms!inner(label))",
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


def get_graph(user_id: str, semester: str | None = None) -> dict:
    ensure_user_exists(user_id)

    # Get all enrolled courses for this user
    enrolled_courses = _user_enrolled_courses(user_id)

    # Optional semester scope (Path A): restrict to the courses the user is
    # enrolled in for that term. `allowed_course_ids is None` means "all terms".
    allowed_course_ids: set[str] | None = None
    if semester:
        from services.academics import term_id_for_label, user_course_ids_for_term
        term_id = term_id_for_label(semester)
        allowed_course_ids = (
            user_course_ids_for_term(user_id, term_id) if term_id else set()
        )
        enrolled_courses = [
            c for c in enrolled_courses if c.get("course_id") in allowed_course_ids
        ]

    # Get all graph nodes for this user
    nodes_raw = table("graph_nodes").select("*", filters={"user_id": f"eq.{user_id}"})
    nodes = nodes_raw or []
    if allowed_course_ids is not None:
        nodes = [n for n in nodes if n.get("course_id") in allowed_course_ids]
    node_ids = {n["id"] for n in nodes}

    edges_raw = table("graph_edges").select("*", filters={"user_id": f"eq.{user_id}"})
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

    # Mastery events live in the append-only node_mastery_events table (the
    # graph_nodes.mastery_events JSONB column was dropped in 0023). Batch-read all
    # of this user's node events in one query, then group by node id.
    events_by_node: dict[str, list] = {}
    if node_ids:
        try:
            event_rows = table("node_mastery_events").select(
                "node_id,delta,reason,created_at",
                filters={"node_id": f"in.({','.join(node_ids)})"},
                order="created_at.asc",
            ) or []
        except Exception:
            event_rows = []
        for ev in event_rows:
            events_by_node.setdefault(ev.get("node_id"), []).append(ev)

    # Enrich each node with learning velocity; trim event history for API response
    for n in nodes:
        events = events_by_node.get(n["id"], [])
        n["learning_velocity"] = _compute_velocity(events)
        n["mastery_events"] = events[-5:]  # keep last 5 for UI; full history lives in DB

    mastered   = sum(1 for n in nodes if n["mastery_tier"] == "mastered")
    learning   = sum(1 for n in nodes if n["mastery_tier"] == "learning")
    struggling = sum(1 for n in nodes if n["mastery_tier"] == "struggling")
    unexplored = sum(1 for n in nodes if n["mastery_tier"] == "unexplored")

    velocities = [n["learning_velocity"] for n in nodes if n["learning_velocity"] > 0]
    avg_velocity = round(sum(velocities) / len(velocities), 4) if velocities else 0.0

    user_rows = table("users").select("streak_count", filters={"id": f"eq.{user_id}"})
    streak = user_rows[0]["streak_count"] if user_rows else 0

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
    rows = _user_enrolled_courses(user_id)

    # Collapse enrollments to one representative row per abstract course_id,
    # preserving first-seen order, while accumulating every enrollment id / term.
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

    result = []
    for course_id in order:
        r = reps[course_id]
        course = r.get("courses", {}) if isinstance(r.get("courses"), dict) else {}

        # Count nodes for this course (graph keys on the abstract course id).
        # Counted once per distinct course — the fan-out used to run this per
        # enrollment, double-counting the same abstract course's nodes.
        node_rows = table("graph_nodes").select(
            "id",
            filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        ) or []

        result.append({
            "enrollment_id": r["id"],
            "course_id": course_id,
            "course_code": course.get("course_code", ""),
            "course_name": course.get("course_name", ""),
            "school": course.get("school", ""),
            "department": course.get("department", ""),
            "color": r.get("color"),
            "nickname": r.get("nickname"),
            "term": r.get("term", ""),
            "node_count": len(node_rows),
            "enrolled_at": r.get("enrolled_at"),
            "enrollment_ids": enrollment_ids[course_id],
            "terms": terms[course_id],
        })
    return result


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
    try:
        from services.course_context_service import update_course_context
        update_course_context(offering_id)
    except Exception:
        pass
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
        from services.course_context_service import update_course_context
        from services.academics import user_offering_ids_for_course
        for offering_id in user_offering_ids_for_course(user_id, course_id):
            try:
                update_course_context(offering_id)
            except Exception:
                pass
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


def delete_course(user_id: str, course_id: str) -> dict:
    """
    Unenroll a user from a course (delete their enrollment(s) for the abstract
    course's offerings). Graph nodes are kept for potential re-enrollment.
    """
    from services.academics import user_offering_ids_for_course
    offering_ids = user_offering_ids_for_course(user_id, course_id)
    from services.course_context_service import update_course_context
    for offering_id in offering_ids:
        table("enrollments").delete(
            {"user_id": f"eq.{user_id}", "offering_id": f"eq.{offering_id}"}
        )
        try:
            update_course_context(offering_id)
        except Exception:
            pass
    return {"deleted": True}


def _normalize_concept(name: str) -> str:
    """Case-fold + collapse whitespace so dedup is tolerant of LLM casing/spacing drift."""
    return " ".join((name or "").split()).casefold()


def _coerce_unit(value, default: float = 0.0) -> float:
    """Coerce an LLM-emitted scalar into a [0,1] float, tolerant of None/strings."""
    try:
        f = float(value if value is not None else default)
    except (TypeError, ValueError):
        f = default
    return max(0.0, min(1.0, f))


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


def apply_graph_update(user_id: str, graph_update: dict, course_id: str | None = None) -> list:
    """
    Apply a graph_update dict to the DB. Returns mastery_changes list.
    If course_id is provided, all new/updated nodes will be associated with that course.

    Concept dedup is case- and whitespace-insensitive: "Linear Regression",
    "linear regression", and " Linear  Regression " all resolve to the same node.
    """
    mastery_changes: list = []
    touched_courses: set = set()

    fetch_filters = {"user_id": f"eq.{user_id}"}
    if course_id:
        fetch_filters["course_id"] = f"eq.{course_id}"
    existing_rows = table("graph_nodes").select(
        "id,concept_name,mastery_score,times_studied,course_id",
        filters=fetch_filters,
    ) or []

    # Normalized name → row, scoped to (user_id [, course_id]). The UNIQUE
    # (user_id, course_id, concept_name) constraint from 0023 prevents duplicates;
    # this map resolves updated_nodes / new_edges against pre-existing rows.
    by_name: dict[str, dict] = {}
    for row in existing_rows:
        norm = _normalize_concept(row.get("concept_name") or "")
        if norm:
            by_name[norm] = row

    inserted_in_batch: dict[str, dict] = {}

    for new_node in graph_update.get("new_nodes", []):
        name = " ".join((new_node.get("concept_name") or "").split())
        if not name:
            continue
        norm = _normalize_concept(name)
        if norm in by_name or norm in inserted_in_batch:
            continue

        node_course_id = course_id or new_node.get("course_id")
        init_m = _coerce_unit(new_node.get("initial_mastery"), 0.0)

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
                "mastery_tier": get_mastery_tier(init_m),
                "course_id": node_course_id,
            },
            on_conflict="user_id,course_id,concept_name",
        )
        canonical_id = new_id
        if returned and isinstance(returned, list) and isinstance(returned[0], dict):
            canonical_id = returned[0].get("id", new_id)
        # Track in-batch inserts so subsequent updated_nodes / new_edges in the
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

    def _lookup(name: str) -> dict | None:
        norm = _normalize_concept(name)
        return by_name.get(norm) or inserted_in_batch.get(norm)

    for upd in graph_update.get("updated_nodes", []):
        name = (upd.get("concept_name") or "").strip()
        if not name:
            continue
        try:
            delta = float(upd.get("mastery_delta", 0.0) or 0.0)
        except (TypeError, ValueError):
            delta = 0.0
        row = _lookup(name)
        if not row:
            continue

        before = row["mastery_score"]
        after = max(0.0, min(1.0, before + delta))

        now = datetime.now(timezone.utc).isoformat()
        # Update only the scalar columns — the mastery_events JSONB blob is gone (0023).
        table("graph_nodes").update(
            {
                "mastery_score": after,
                "mastery_tier": get_mastery_tier(after),
                "times_studied": (row.get("times_studied") or 0) + 1,
                "last_studied_at": now,
            },
            filters={"id": f"eq.{row['id']}"},
        )
        # Append-only mastery event (fixes the non-atomic read-modify-write, #247).
        event_row = {
            "id": str(uuid.uuid4()),
            "node_id": row["id"],
            "delta": delta,
            "reason": upd.get("reason", ""),
            "created_at": now,
        }
        # E7: the caller's categorical read of WHY mastery moved
        # (quiz submit computes correct/partial/confusion from the score
        # ratio). It was computed and then dropped here for months, so the
        # event log recorded how much mastery moved but never what kind of
        # evidence moved it.
        #
        # Omitted rather than written as an explicit null when absent: every
        # non-quiz caller (tutor tools, the document pipeline, manual adds)
        # supplies none, and naming a column PostgREST's schema cache doesn't
        # have is a hard 400 — so omitting keeps THOSE paths working on an
        # environment that took this code before the migration.
        #
        # It does NOT make the quiz path safe there, and the failure is not
        # cosmetic: submit_quiz always supplies an event_type, so a
        # code-before-migration deploy 400s this insert, the exception
        # propagates out of apply_graph_update (submit does not wrap it),
        # and the 500 lands AFTER the atomic completed_at claim but BEFORE
        # score/answers are written — losing the graded attempt, not just
        # its mastery event. The migration
        # (20260814051517_node_mastery_events_event_type.sql) must be
        # applied strictly before this code ships to any environment.
        event_type = upd.get("event_type")
        if isinstance(event_type, str) and event_type.strip():
            event_row["event_type"] = event_type.strip()
        table("node_mastery_events").insert(event_row)
        mastery_changes.append({"concept": row["concept_name"], "before": before, "after": after})

        cid = row.get("course_id")
        if cid:
            touched_courses.add(cid)

    if mastery_changes:
        # services/streak_service.py::touch_streak is the sole writer of
        # streak_count/longest_streak (UTC calendar days); mastery activity
        # legitimately counts as a study day, so this stays a call site, but
        # the maths lives in exactly one place — not duplicated here.
        touch_streak_safe(user_id)

    for new_edge in graph_update.get("new_edges", []):
        src_name = " ".join((new_edge.get("source") or "").split())
        tgt_name = " ".join((new_edge.get("target") or "").split())
        if not src_name or not tgt_name:
            continue
        try:
            strength = float(new_edge.get("strength", 0.5) or 0.5)
        except (TypeError, ValueError):
            strength = 0.5
        strength = max(0.0, min(1.0, strength))
        relationship_type = new_edge.get("relationship_type", "related")

        src = _lookup(src_name)
        tgt = _lookup(tgt_name)
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
                "strength": strength,
                "relationship_type": relationship_type,
            },
            on_conflict="user_id,source_node_id,target_node_id,relationship_type",
        )

    if touched_courses:
        # touched_courses holds abstract course ids (the graph key). Analytics is
        # offering-scoped, so refresh each of this user's offerings of those courses.
        from services.course_context_service import update_course_context
        from services.academics import user_offering_ids_for_course
        for cid in touched_courses:
            for offering_id in user_offering_ids_for_course(user_id, cid):
                try:
                    update_course_context(offering_id)
                except Exception:
                    pass

    # The knowledge graph is the ONLY thing that advances these three stats, so
    # this is the only place they can be dispatched from. Without it `rooted`,
    # `branching`, `canopy` (concepts_mastered), `web` (graph_nodes_count) and
    # `polymath` (courses_with_mastery) are live badges nothing can ever award.
    # Placed at the end rather than beside the touch_streak_safe call inside
    # `if mastery_changes:` on purpose: graph_nodes_count grows when nodes are
    # created, which happens on updates that change no mastery at all.
    # Post-commit side effect — the graph is already written, so a failure here
    # must not propagate into the caller's turn.
    try:
        from services.achievement_service import check_achievements
        check_achievements(user_id, "graph_nodes_count", {})
        check_achievements(user_id, "concepts_mastered", {})
        check_achievements(user_id, "courses_with_mastery", {})
    except Exception:
        logger.exception("achievement dispatch failed after graph update user=%s", user_id)

    return mastery_changes


def get_recommendations(user_id: str, semester: str | None = None) -> list:
    filters = {
        "user_id": f"eq.{user_id}",
        "mastery_tier": "in.(struggling,learning,unexplored)",
    }
    if semester:
        from services.academics import term_id_for_label, user_course_ids_for_term
        term_id = term_id_for_label(semester)
        allowed = user_course_ids_for_term(user_id, term_id) if term_id else set()
        # Unresolved label / no enrollment in that term → no recommendations.
        if not allowed:
            return []
        filters["course_id"] = f"in.({','.join(allowed)})"

    rows = table("graph_nodes").select(
        "concept_name,mastery_score,mastery_tier,course_id",
        filters=filters,
        order="mastery_score.asc",
        limit=5,
    )
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
