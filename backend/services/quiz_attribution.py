"""Per-question mastery attribution: which node did this question test?

Study roadmap §3.13. Mastery was awarded whole-attempt before this — one
delta against `quiz_attempts.concept_node_id` no matter what the individual
questions covered — which made per-subtopic mastery, and therefore the whole
roadmap, approximately fiction for any quiz that drifted across concepts.

Two halves:

  `resolve_node_id`   name -> node id, run ONCE when the response row is
                      written and then persisted. Resolving at read time
                      would look simpler and would rot: a later rename or
                      merge re-points a stored id (§3.11) but cannot fix a
                      name captured in a row it never updates.

  `group_responses`   responses -> per-node correct/total, so submit can
                      apply one `updated_nodes` entry per node inside a
                      SINGLE `apply_graph_update` call. One call matters:
                      the submit path's re-submit guard and streak bump are
                      per-call, so a loop would double-count both.

The resolution rule is deliberately the SAME normalisation
`graph_service._normalize_concept` applies (case-fold + collapse
whitespace). Inventing a second matching rule here would mean a question
could resolve to one node at attribution time and a different one inside
`apply_graph_update`, which is the exact class of bug this module exists to
remove.
"""
from __future__ import annotations

import logging
from typing import Iterable

from services.graph_service import _normalize_concept

logger = logging.getLogger(__name__)


def resolve_node_id(
    concept_name: str | None,
    course_nodes: Iterable[dict],
    *,
    fallback_node_id: str | None = None,
) -> tuple[str | None, bool]:
    """Map a question's `concept_tested` to a node id within one course.

    Returns ``(node_id, matched)``.

    `matched` is False when the name resolved to nothing — distinct from
    `node_id is None`, because a miss may still fall back to the attempt's
    launched-from node. The caller needs both facts: the id to store, and
    whether to report the miss (§3.13 step 6). A fallback is reported as a
    miss, because crediting the launched-from node is a guess, and the
    whole point of the signal is to measure how often we are guessing.

    No fuzzy matching. A near-miss credited to the wrong concept is worse
    than an honest NULL: the student sees mastery move on something they
    were never asked about, and no log says why.
    """
    if not concept_name or not concept_name.strip():
        return fallback_node_id, False

    target = _normalize_concept(concept_name)
    for n in course_nodes:
        if _normalize_concept(n.get("concept_name") or "") == target:
            return n.get("id"), True

    return fallback_node_id, False


def group_responses(
    responses: Iterable[dict],
    *,
    fallback_node_id: str | None = None,
) -> dict[str, dict[str, int]]:
    """Partition graded responses by node into ``{node_id: {correct, total}}``.

    Rows with no `concept_node_id` fall back to `fallback_node_id` (the
    attempt's launched-from concept) when one exists, and are otherwise
    dropped: a response attributable to nothing must move no mastery at all
    rather than quietly inflating whichever node happens to be nearby.

    Ordering of the returned mapping follows first appearance, so the
    `updated_nodes` list submit builds from it is deterministic — which
    keeps the resulting `node_mastery_events` rows reproducible in tests.
    """
    grouped: dict[str, dict[str, int]] = {}
    for r in responses:
        node_id = r.get("concept_node_id") or fallback_node_id
        if not node_id:
            continue
        bucket = grouped.setdefault(node_id, {"correct": 0, "total": 0})
        bucket["total"] += 1
        if r.get("is_correct"):
            bucket["correct"] += 1
    return grouped


def unattributed_count(responses: Iterable[dict]) -> int:
    """How many graded responses carry no node at all.

    Surfaced on the submit response so the student is told a question went
    uncredited, instead of wondering why ten right answers moved nothing.
    """
    return sum(1 for r in responses if not r.get("concept_node_id"))


def describe_grouping(grouped: dict[str, dict[str, int]]) -> str:
    """One-line log summary. Never includes concept NAMES — those are student
    content, and `routes/quiz.py:516` already establishes that rule for this
    path."""
    return ", ".join(
        f"{node_id[:8]}={v['correct']}/{v['total']}" for node_id, v in grouped.items()
    ) or "none"


def log_attribution(
    *,
    attempt_id: str,
    grouped: dict[str, dict[str, int]],
    unattributed: int,
) -> None:
    """Record what an attempt actually paid out, and to how many nodes.

    Worth logging even on the happy path: the single most likely silent
    failure of §3.13 is every question resolving to the same node, which
    looks exactly like the old whole-attempt behaviour and would otherwise
    go unnoticed for months.
    """
    if unattributed:
        logger.warning(
            "quiz attribution: attempt %s had %d unattributed response(s); nodes: %s",
            attempt_id, unattributed, describe_grouping(grouped),
        )
    else:
        logger.info(
            "quiz attribution: attempt %s paid %d node(s): %s",
            attempt_id, len(grouped), describe_grouping(grouped),
        )
