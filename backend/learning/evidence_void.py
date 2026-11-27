"""Void evidence: the one rule (learning-loop spec §13 A123). Pure: stdlib only.

AN OBSERVATION GRADED AGAINST A CHECK ITEM STAFF RETIRED IS VOID.

A check item is identified course-wide by (course_id, question_hash) (A113);
staff retire one in the admin queue, after students' reports quarantined it or
on their own (a report alone never retires anything). A retired item was
retired as broken — a wrong key, an unanswerable or misaligned question — so
no outcome graded against it measures the student. The rule is applied to:

  • journal rows — `learning_evidence_voids` (one append-only row per voided
    evidence id, written with the replayed learner_state by the single graph
    writer) materialises it per row, and every reader that reads evidence as
    evidence leaves those rows out;
  • the admin reports — BKT calibration and the A112 learning gain (its
    post-test outcomes and their pretest anchors) apply `is_void_row` /
    `pose_is_void` to the staff-retired items directly, so an outcome whose
    grade was refused at commit (the item was retired while it was in flight:
    the pose kept its outcome, no evidence row was written) is left out too,
    and a sweep still in progress already reads as finished;
  • misconceptions — `closable_misconceptions` names the open rows every
    supporting attempt of which was graded against a retired item.

An item merely gone is no retire (A23's consent withdrawal and A119's re-key
delete rows too, and that evidence stands), and neither is a quarantine, a
report or an approval. A row with no check_item_id (a quiz question, never a
check item) is never void.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from typing import Any

#: learning_evidence_voids.reason (migration 20261108072715): the one reason.
VOID_REASON = "item_retired"
#: misconceptions.resolved_reason of a misconception closed because every
#: attempt supporting it was graded against a retired item.
MISCONCEPTION_VOID_REASON = "evidence_void"

ItemKey = tuple[str, str]


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def row_course(row: Mapping[str, Any]) -> str | None:
    """A journal row's course: its own `course_id`, else the course of its
    node from a `graph_nodes!inner(course_id)` embed."""
    course = _text(row.get("course_id"))
    if course is None and isinstance(row.get("graph_nodes"), Mapping):
        course = _text(row["graph_nodes"].get("course_id"))
    return course


def graded_item(row: Mapping[str, Any], course_id: str | None = None) -> ItemKey | None:
    """The course check item a journal row was graded against — (course_id,
    question_hash) — or None when it was none (no check_item_id: a quiz
    question) or the course is unknown. `course_id` stands in for a row that
    carries no course of its own (the caller knows its node's course)."""
    if _text(row.get("check_item_id")) is None:
        return None
    course = course_id or row_course(row)
    question_hash = _text(row.get("question_hash"))
    if course is None or question_hash is None:
        return None
    return course, question_hash


def is_void_row(row: Mapping[str, Any], retired: Collection[ItemKey], course_id: str | None = None) -> bool:
    """The rule on one journal row: graded against a retired item."""
    item = graded_item(row, course_id)
    return item is not None and item in retired


def pose_is_void(pose: Mapping[str, Any], retired: Collection[ItemKey]) -> bool:
    """The rule on one post-test pose (its course item: course_id,
    question_hash)."""
    course, question_hash = _text(pose.get("course_id")), _text(pose.get("question_hash"))
    return course is not None and question_hash is not None and (course, question_hash) in retired


def closable_misconceptions(
    rows: Iterable[Mapping[str, Any]],
    *,
    course_id: str,
    retired_hashes: Collection[str],
    retired_check_ids: Collection[str],
) -> list[dict]:
    """The open misconceptions (`rows`: {id, count, check_item_id, attempts:
    [{course_id, question_hash, check_item_id}]}) whose EVERY supporting
    attempt was graded against a retired item of `course_id`:

      • recorded attempts that account for the whole count (one per
        increment since A123), each on a retired item of the course; or
      • a row from before attempts were recorded (none) with a count of 1 —
        its one attempt is the item its `check_item_id` names — whose item is
        one a retired item's evidence carried (`retired_check_ids`).

    Anything else (a support on a live item, an attempt whose item is
    unknown, older increments nobody recorded) keeps the row open. Returns
    [{id, count}] (the count the commit re-checks), in row order."""
    out: list[dict] = []
    for row in rows:
        mid, count = _text(row.get("id")), row.get("count")
        if mid is None or isinstance(count, bool) or not isinstance(count, int) or count < 1:
            continue
        attempts = [a for a in row.get("attempts") or [] if isinstance(a, Mapping)]
        if attempts:
            void = len(attempts) == count and all(
                a.get("course_id") == course_id and a.get("question_hash") in retired_hashes
                for a in attempts
            )
        else:
            void = count == 1 and row.get("check_item_id") in retired_check_ids
        if void:
            out.append({"id": mid, "count": count})
    return out
