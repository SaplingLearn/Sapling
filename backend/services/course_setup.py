"""Concepts a student takes out of a course (the Tutor's course setup,
"Untick any that aren't part of your course"; Tutor redesign, owner decision
2026-11-26), behind the `course_setup` flag.

`exclude_concepts` records each removed concept's normalized name in
`course_concept_exclusions`, then deletes its graph node through
`graph_service.delete_node` (edges and loop rows go with it).
`apply_graph_update` reads the same rows (`excluded_keys`) and never
re-creates an excluded concept, so the next upload of the same material does
not bring it back.

Only a concept the student has not started can be removed: a node with any
mastery evidence (a `node_mastery_events` row) is kept and reported back, so
setup never erases progress. The record is written BEFORE the node is
deleted: a failure in between leaves the concept excluded and its node still
there, and a retry finishes the job (the node read finds it again).
"""
from __future__ import annotations

from collections.abc import Iterable

from db.connection import table
from services.feature_flags import flag_on

TABLE = "course_concept_exclusions"
COURSE_SETUP_FLAG = "course_setup"

#: One setup removes at most a course's worth of concepts in one request.
MAX_PER_REQUEST = 200


def course_setup_on(user_id: str | None) -> bool:
    """The `course_setup` flag for this student. Not a loop flag: a concept
    the student removed stays out of their uploads whether or not the loop is
    on for them (the setup itself opens only from the loop's Tutor), and
    apply_graph_update, which reads it, runs outside any route that could
    carry the loop's gate. Blocking on a cold flag cache: call it off the
    event loop."""
    return bool(user_id) and flag_on(COURSE_SETUP_FLAG, user_id)


def normalize(name: str) -> str:
    """The graph's dedup key (graph_service._normalize_concept): case-folded,
    whitespace collapsed."""
    return " ".join((name or "").split()).casefold()


def excluded_keys(user_id: str, course_ids: Iterable[str]) -> set[tuple[str, str]]:
    """(course_id, concept_key) pairs this student removed, for these courses."""
    ids = sorted({c for c in course_ids if isinstance(c, str) and c})
    if not user_id or not ids:
        return set()
    rows = table(TABLE).select(
        "course_id,concept_key",
        filters={"user_id": f"eq.{user_id}", "course_id": f"in.({','.join(ids)})"},
    ) or []
    return {(r["course_id"], r["concept_key"]) for r in rows if r.get("course_id") and r.get("concept_key")}


def _started(node_ids: list[str]) -> set[str]:
    """The nodes with any evidence. The journal has no user_id; the ids were
    read off the student's own graph_nodes rows."""
    rows = table("node_mastery_events").select(
        "node_id", filters={"node_id": f"in.({','.join(node_ids)})"},
    ) or []
    return {r["node_id"] for r in rows if r.get("node_id")}


def exclude_concepts(user_id: str, course_id: str, node_ids: list[str]) -> dict:
    """Remove these concepts from the student's course. Returns the ids
    removed and the ids kept because the student has started them; an id that
    is not one of the student's nodes in this course is ignored."""
    from services.graph_service import delete_node

    wanted = list(dict.fromkeys(n for n in node_ids if n))[:MAX_PER_REQUEST]
    if not wanted:
        return {"removed": [], "kept": []}
    nodes = table("graph_nodes").select(
        "id,concept_name",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}", "id": f"in.({','.join(wanted)})"},
    ) or []
    found = {r["id"]: r.get("concept_name") or "" for r in nodes if r.get("id")}
    started = _started(list(found)) if found else set()
    removable = [n for n in wanted if n in found and n not in started and normalize(found[n])]
    if removable:
        table(TABLE).upsert(
            [{"user_id": user_id, "course_id": course_id, "concept_key": normalize(found[n])} for n in removable],
            on_conflict="user_id,course_id,concept_key",
            ignore_duplicates=True,
        )
    for node_id in removable:
        delete_node(user_id, node_id)
    return {"removed": removable, "kept": [n for n in wanted if n in started]}
