"""W8.6: shared learner-next read for Hub / Quiz launcher / Dashboard.

Assembles the student's concept states once and returns the three buckets
`learning.learner_next.learner_next` computes (due reviews, open
misconceptions, ready fringe) with concept names and course ids on the wire.

Quiz plan (A143) still goes through `services.quiz_learning.concept_plan`
today — that path shares the same pure ranking via
`learning.quiz_plan.rank_concepts` → `learning.learner_next`. Study Focus /
Dashboard / a future Quiz launcher that wants the three buckets separately
call `learner_next` here so Hub and Quiz cannot diverge on the set or order.

No flag gate of its own: callers decide (e.g. `quiz_concept_plan`,
`learning_loop`, or Study's own surface). Reads only; raises on a failed
node or state read so a route can answer 503.
"""

from __future__ import annotations

from datetime import datetime, timezone

from learning.learner_next import learner_next as compute_next
from services import quiz_learning as ql


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts else None


def _wire(concept, by_id: dict) -> dict:
    node = by_id[concept.node_id]
    return {
        "node_id": concept.node_id,
        "concept_name": node.name,
        "course_id": node.course_id,
        "reason": concept.reason,
        "p_known": round(concept.p_known, 4),
        "band": concept.band,
        "due_at": _iso(concept.due_at),
        "open_misconceptions": concept.open_misconceptions,
    }


def learner_next(
    user_id: str,
    course_id: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Due reviews, open-misconception concepts, and ready fringe for one
    student (optionally one course).

    Returns::

        {
          "due": [...],             # FSRS-due, DASH order
          "misconceptions": [...],  # open misconceptions, count then p then id
          "ready": [...],           # planner.outer_fringe order
        }

    Each entry matches one `GET /api/quiz/plan` concept dict (node_id,
    concept_name, course_id, reason, p_known, band, due_at,
    open_misconceptions). Uncapped — Quiz applies QUIZ_PLAN_MAX_CONCEPTS via
    `quiz_plan.rank_concepts`; Study/Dashboard apply their own limits.
    """
    now = now or datetime.now(timezone.utc)
    # Same reads concept_plan uses (patched on quiz_learning in its tests).
    nodes = ql._nodes(user_id, course_id)
    if not nodes:
        return {"due": [], "misconceptions": [], "ready": []}
    by_id = {n.id: n for n in nodes}
    states = ql._concept_states(user_id, nodes, now)
    edges = ql._prereq_edges(user_id, by_id)
    nxt = compute_next(states, edges, now)
    return {
        "due": [_wire(c, by_id) for c in nxt.due],
        "misconceptions": [_wire(c, by_id) for c in nxt.misconceptions],
        "ready": [_wire(c, by_id) for c in nxt.ready],
    }
