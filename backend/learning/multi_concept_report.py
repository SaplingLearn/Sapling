"""The admin report on multi-concept items (learning-loop spec §13 A141).

Pure: stdlib, learning.item_audit (the Wilson interval), learning.checks (the
hold) and learning.multi_concept; listed in
tests/test_learning_loop_invariants.py::PURE_MODULES.

Per course and overall, with every n: how many multi-concept items are
stored (and held), how many were served in the range (`learn.multi_concept_
served`), and their outcomes in the range — the graded answers on them (the
evidence rows naming such an item; void rows already left out by the caller,
A123), how many were right, how many were unassisted (rung 0, no help, no
re-check after a release — item_stats' definition) and right, the distinct
students who answered, and the correct rate with its Wilson 95% interval. A
rate is None when its n is 0, never a zero.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from learning.checks import held_flags
from learning.item_audit import wilson
from learning.item_stats import unassisted


def _student(row: Mapping[str, Any]) -> str | None:
    embed = row.get("graph_nodes")
    user = embed.get("user_id") if isinstance(embed, Mapping) else row.get("user_id")
    return user if isinstance(user, str) and user else None


def _course(row: Mapping[str, Any]) -> str | None:
    embed = row.get("graph_nodes")
    course = embed.get("course_id") if isinstance(embed, Mapping) else row.get("course_id")
    return course if isinstance(course, str) and course else None


def _block(course_id: str | None) -> dict:
    return {
        "course_id": course_id,
        "items": 0,
        "held": 0,
        "served": 0,
        "answered": 0,
        "correct": 0,
        "unassisted": 0,
        "unassisted_correct": 0,
        "students": 0,
        "correct_rate": None,
        "correct_ci_low": None,
        "correct_ci_high": None,
    }


def _close(block: dict, students: set[str]) -> dict:
    block["students"] = len(students)
    if block["answered"]:
        block["correct_rate"] = block["correct"] / block["answered"]
        block["correct_ci_low"], block["correct_ci_high"] = wilson(block["correct"], block["answered"])
    return block


def multi_concept_report(
    items: Iterable[Mapping[str, Any]],
    served: Iterable[Mapping[str, Any]],
    evidence: Iterable[Mapping[str, Any]],
) -> dict:
    """`items`: the stored multi-concept rows (id, course_id, question_hash,
    lint_flags, canonical_verified); `served`: the range's
    learn.multi_concept_served payloads (course_id, question_hash); `evidence`:
    the range's non-void evidence rows (check_item_id, correct, assisted,
    max_rung, same_session_recheck, weight, channel, reason, the node's
    graph_nodes embed with user_id and course_id). Rows on another item are
    ignored. Returns {"overall": block, "courses": [block, ...]} by course id."""
    courses: dict[str | None, dict] = {}
    students: dict[str | None, set[str]] = defaultdict(set)
    overall, everyone = _block(None), set()

    def block(course_id):
        if course_id not in courses:
            courses[course_id] = _block(course_id)
        return courses[course_id]

    ids: dict[str, str | None] = {}
    for row in items:
        course = row.get("course_id")
        ids[row.get("id")] = course
        for b in (block(course), overall):
            b["items"] += 1
            if held_flags(row.get("lint_flags"), row.get("canonical_verified")):
                b["held"] += 1
    for payload in served:
        for b in (block(payload.get("course_id")), overall):
            b["served"] += 1
    for row in evidence:
        if row.get("check_item_id") not in ids or not isinstance(row.get("correct"), bool):
            continue
        course = _course(row) or ids[row["check_item_id"]]
        right = row["correct"] and row.get("reason") != f"evidence:{row.get('channel')}:idk"
        alone = unassisted(row)
        user = _student(row)
        for b, who in ((block(course), students[course]), (overall, everyone)):
            b["answered"] += 1
            b["correct"] += int(right)
            b["unassisted"] += int(alone)
            b["unassisted_correct"] += int(alone and right)
            if user:
                who.add(user)
    return {
        "overall": _close(overall, everyone),
        "courses": [
            _close(courses[c], students[c]) for c in sorted(courses, key=lambda c: str(c or ""))
        ],
    }
