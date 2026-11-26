"""#866 audit K01 (owner decision 2026-11-19): a study guide's "Ask the tutor".

The study guide's rail question box and its concept map's Ask open a tutor
session and send the student's question as its first message, then open the
Tutor on it. A loop session opens in the check-in (probe), which by design
takes no teaching before the pretest, so that first message was refused and
every guide Ask failed. A `guide_ask` session instead starts teaching, the way
a quiz ask does (spec §13 A99): on the asked concept when the Ask names one
the student has in the course (the concept map's), else as an open teaching
session with no planned concept (the rail's question about the whole guide),
the shape an empty plan leaves.

No help row is recorded: a guide Ask is not about one graded question (the
quiz ask's is), and anything the tutor reveals of a check item is still
recorded by the served-text scan, as on every loop turn.
"""
from __future__ import annotations

import httpx

from db.connection import table

GUIDE_ASK_ORIGIN = "guide_ask"


def guide_ask_state(node_id: str | None) -> dict:
    """The loop document a guide-ask session starts with: `teach`, marked with
    its origin — on `node_id` as /plan/approve leaves a one-concept plan, or,
    with no concept, the empty plan GET /plan leaves when it has nothing to
    propose (services/loop/plan.py)."""
    if node_id:
        return {
            "phase": "teach",
            "origin": GUIDE_ASK_ORIGIN,
            "plan": {"approved": [node_id], "cursor": 0},
            "concept": node_id,
            "teach_turns": 0,
            "concept_checks": 0,
        }
    return {"phase": "teach", "origin": GUIDE_ASK_ORIGIN, "plan": {"approved": [], "cursor": 0}}


def guide_ask_node(user_id: str, course_id: str | None, concept_name: str) -> str | None:
    """The student's own node named `concept_name` in `course_id` (the concept
    map passes the node's stored name), or None: no course, no such concept,
    or a read that failed (the session then teaches with no planned concept)."""
    name = (concept_name or "").strip()
    if not course_id or not name:
        return None
    try:
        rows = table("graph_nodes").select(
            "id",
            filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}", "concept_name": f"eq.{name}"},
            limit=1,
        ) or []
    except (httpx.HTTPError, RuntimeError, ValueError):  # the Ask still opens, on no planned concept
        return None
    node = rows[0].get("id") if rows else None
    return node if isinstance(node, str) and node else None
