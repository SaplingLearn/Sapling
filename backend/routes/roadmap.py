"""Study-roadmap read API.

`GET /api/roadmap/{course_id}` is the one endpoint the roadmap page needs:
the course's topics and subtopics in order, each with mastery, freshness and
tier, plus the exam list and the readiness figure for whichever exam is
selected.

This module is a THIN fetch-and-shape wrapper. Every rule — hierarchy,
ordering, freshness, readiness — lives in `services/roadmap.py` as pure
functions, and the payload carries the computed values rather than the
inputs. The frontend must never re-derive readiness: a second implementation
is a second chance to disagree with the "why?" panel that claims to explain
it.

Spec: .plans/course-study-roadmap-spec.md §3.1–§3.7, §5.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from db.connection import table
from services.academics import user_offering_ids_for_course
from services.auth_guard import require_self
from services.http_cache import cached_json, conditional, make_etag
from services.roadmap import (
    build_hierarchy,
    order_roadmap,
    readiness,
    start_here_id,
    subtopic_readiness,
    topic_summary,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _course_graph(user_id: str, course_id: str) -> tuple[list[dict], list[dict]]:
    """The course's nodes and the edges among them.

    Edges are filtered to BOTH endpoints being in the course's node set.
    `graph_edges` has no `course_id` of its own, so a cross-course edge would
    otherwise drag a foreign concept into the ordering — and `source_node_id`
    alone is not enough to rule that out.
    """
    nodes = table("graph_nodes").select(
        "id,concept_name,mastery_score,mastery_tier,times_studied,"
        "last_studied_at,color,course_id,created_at",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    ) or []
    if not nodes:
        return [], []

    ids = {n["id"] for n in nodes}
    edges = table("graph_edges").select(
        "source_node_id,target_node_id,relationship_type,strength",
        filters={"user_id": f"eq.{user_id}"},
    ) or []
    return nodes, [
        e for e in edges
        if e.get("source_node_id") in ids and e.get("target_node_id") in ids
    ]


def _exams(user_id: str, course_id: str) -> list[dict]:
    """The course's exams, soonest first.

    `assignments` is enrollment-keyed (0021), so this goes
    course -> offerings -> enrollments -> assignments. Exams with no due date
    are dropped: an exam you cannot date cannot anchor freshness (§3.7) or be
    chosen as a deadline, so listing it would offer the student a filter that
    silently does nothing.
    """
    try:
        offering_ids = user_offering_ids_for_course(user_id, course_id)
    except Exception:
        logger.warning(
            "roadmap: offering lookup failed for course=%s", course_id, exc_info=True,
        )
        return []
    if not offering_ids:
        return []

    enrollments = [
        e for e in (table("enrollments").select(
            "id,offering_id", filters={"user_id": f"eq.{user_id}"},
        ) or [])
        if e.get("offering_id") in set(offering_ids)
    ]
    if not enrollments:
        return []

    rows = table("assignments").select(
        "id,title,due_date,assignment_type,enrollment_id",
        filters={
            "enrollment_id": f"in.({','.join(e['id'] for e in enrollments)})",
            "assignment_type": "eq.exam",
        },
    ) or []

    exams = [
        {
            # title is NOT encrypted on assignments; notes and points are.
            # Kept explicit so a future schema change can't silently start
            # shipping ciphertext to the client.
            "id": r["id"],
            "title": r.get("title") or "Exam",
            "due_date": r.get("due_date"),
        }
        for r in rows
        if r.get("due_date")
    ]
    return sorted(exams, key=lambda e: e["due_date"])


def _last_correct_by_node(user_id: str, node_ids: set[str]) -> dict[str, str]:
    """When did this student last PROVE each concept? (§3.7)

    `max(answered_at) WHERE is_correct AND concept_node_id = n`, which is
    exactly what the partial index on quiz_responses serves.

    Rows written before the attribution migration carry no node and are
    invisible here. That is deliberate — see the migration's note on why
    there is no backfill — and it means freshness reads as fully fresh for
    historical answers rather than inventing a date for them.
    """
    if not node_ids:
        return {}

    attempts = table("quiz_attempts").select(
        "id", filters={"user_id": f"eq.{user_id}"},
    ) or []
    if not attempts:
        return {}

    rows = table("quiz_responses").select(
        "concept_node_id,answered_at",
        filters={
            "attempt_id": f"in.({','.join(a['id'] for a in attempts)})",
            "is_correct": "eq.true",
            "concept_node_id": "not.is.null",
        },
    ) or []

    latest: dict[str, str] = {}
    for r in rows:
        nid, at = r.get("concept_node_id"), r.get("answered_at")
        if not nid or nid not in node_ids or not at:
            continue
        if nid not in latest or at > latest[nid]:
            latest[nid] = at
    return latest


def _selected_exam(exams: list[dict], exam_id: str | None) -> dict | None:
    """The exam the page is scoped to.

    An explicit `exam_id` wins. With none given the page falls back to the
    NEXT upcoming exam rather than to nothing, because that is the deadline a
    student opening the page is almost always thinking about. An `exam_id`
    naming an exam that is not this course's resolves to None rather than
    raising — the page degrades to course readiness (§3.6).
    """
    if exam_id:
        return next((e for e in exams if e["id"] == exam_id), None)
    today = datetime.now(timezone.utc).date().isoformat()
    return next((e for e in exams if e["due_date"] >= today), None)


@router.get("/{course_id}")
def get_roadmap(course_id: str, user_id: str, request: Request, exam_id: str | None = None):
    """The whole roadmap for one course.

    `Cache-Control: private` is not negotiable here — the payload is
    user-scoped and carries app-decrypted content, so a shared proxy must
    never hold it. The ETag is built from cheap change-keys rather than the
    rendered body, per the project's HTTP-caching convention.
    """
    require_self(user_id, request)

    nodes, edges = _course_graph(user_id, course_id)
    exams = _exams(user_id, course_id)
    selected = _selected_exam(exams, exam_id)
    exam_date = selected["due_date"] if selected else None

    last_correct = _last_correct_by_node(user_id, {n["id"] for n in nodes})

    # Change-keys, not the payload: node/edge counts plus the newest mutation
    # timestamp cover every way this page's content can change, and all of
    # them are already in hand.
    newest = max(
        (str(n.get("last_studied_at") or n.get("created_at") or "") for n in nodes),
        default="",
    )
    etag = make_etag(
        user_id, course_id, len(nodes), len(edges), newest,
        exam_id or (selected or {}).get("id") or "", len(last_correct),
    )
    not_mod = conditional(request, etag)
    if not_mod:
        return not_mod

    ordered = order_roadmap(build_hierarchy(nodes, edges), edges)
    cycles = ordered["cycle_node_ids"]

    def _row(node: dict) -> dict:
        r = subtopic_readiness(
            node,
            last_correct_at=last_correct.get(node["id"]),
            exam_date=exam_date,
        )
        r["color"] = node.get("color")
        r["times_studied"] = node.get("times_studied") or 0
        r["last_studied_at"] = node.get("last_studied_at")
        r["in_cycle"] = node["id"] in cycles
        return r

    topics = []
    all_rows: list[dict] = []
    for entry in ordered["topics"]:
        sub_rows = [_row(s) for s in entry["subtopics"]]
        all_rows.extend(sub_rows)
        topics.append({
            "id": entry["node"]["id"],
            "concept_name": entry["node"]["concept_name"],
            "color": entry["node"].get("color"),
            "in_cycle": entry["node"]["id"] in cycles,
            "subtopics": sub_rows,
            "summary": topic_summary(sub_rows),
        })

    unfiled_rows = [_row(n) for n in ordered["unfiled"]]
    # Unfiled concepts count toward readiness. They are part of the course
    # whether or not anything has grouped them, and excluding them would let
    # the ring read 100% while a third of the material sat ungrouped below.
    all_rows.extend(unfiled_rows)

    return cached_json({
        "course_id": course_id,
        "topics": topics,
        "unfiled": unfiled_rows,
        "exams": exams,
        "selected_exam": selected,
        "start_here_topic_id": start_here_id(ordered["topics"]),
        "readiness": readiness(all_rows),
        "summary": topic_summary(all_rows),
        # The page renders a flat list plus an "Organise" action in this
        # state (§3.16); it is not an error, and the client should not have
        # to infer it from an empty topics array.
        "needs_structure": not topics and bool(unfiled_rows),
    }, etag)


@router.get("/{course_id}/readiness")
def get_readiness(course_id: str, user_id: str, request: Request, exam_id: str | None = None):
    """The "why?" breakdown behind the ring.

    Returns one row per topic with its factors and contribution, plus the
    overall figure. Computed from the same functions the ring uses, so the
    explanation cannot disagree with the number it explains.
    """
    require_self(user_id, request)

    nodes, edges = _course_graph(user_id, course_id)
    exams = _exams(user_id, course_id)
    selected = _selected_exam(exams, exam_id)
    exam_date = selected["due_date"] if selected else None
    last_correct = _last_correct_by_node(user_id, {n["id"] for n in nodes})

    ordered = order_roadmap(build_hierarchy(nodes, edges), edges)

    def _rows(group: list[dict]) -> list[dict]:
        return [
            subtopic_readiness(
                n, last_correct_at=last_correct.get(n["id"]), exam_date=exam_date,
            )
            for n in group
        ]

    factors = []
    all_rows: list[dict] = []
    for entry in ordered["topics"]:
        rows = _rows(entry["subtopics"])
        all_rows.extend(rows)
        summary = topic_summary(rows)
        factors.append({
            "topic_id": entry["node"]["id"],
            "concept_name": entry["node"]["concept_name"],
            "mastered": summary["mastered"],
            "total": summary["total"],
            "stale": summary["stale"],
            # The mean freshness across the topic's subtopics — the number
            # the breakdown prints next to the count.
            "freshness": (
                sum(r["freshness"] for r in rows) / len(rows) if rows else 1.0
            ),
            "weight": sum(r["weight"] for r in rows),
            "contribution": sum(r["contribution"] for r in rows),
        })

    unfiled = _rows(ordered["unfiled"])
    all_rows.extend(unfiled)
    if unfiled:
        summary = topic_summary(unfiled)
        factors.append({
            "topic_id": None,
            "concept_name": "Unfiled concepts",
            "mastered": summary["mastered"],
            "total": summary["total"],
            "stale": summary["stale"],
            "freshness": sum(r["freshness"] for r in unfiled) / len(unfiled),
            "weight": sum(r["weight"] for r in unfiled),
            "contribution": sum(r["contribution"] for r in unfiled),
        })

    return {
        "course_id": course_id,
        "exam": selected,
        "factors": factors,
        "readiness": readiness(all_rows),
    }
