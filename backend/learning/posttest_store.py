"""The delayed post-test's concept anchors (spec §13 A112, A126).

A concept's post-test windows run from its ANCHOR — its first graded evidence,
the earliest `node_mastery_events` row with event_type 'evidence' (A112;
`loop_state_store.evidence_spans` reads the same first time per course). Two
readers need the anchors of more than one course at once: the student's
"retention check due" read (GET /api/learn/loop/posttest/due) and the admin
learning-gain funnel (every student's windows that opened in a range).
PostgREST cannot GROUP BY, so the `posttest_anchors` SQL function
(20261108093359_learning_posttest_outcomes.sql) answers one row per node,
keyset-paged by node id. Read-only; outside the PKG-06 layer, so the admin
report can use it without loading the loop's.
"""

from __future__ import annotations

from datetime import datetime

from db.connection import MAX_ROWS, rpc

#: the SQL function, and its page size — a PostgREST response never holds more
#: than db.connection.MAX_ROWS rows (the function clamps p_limit to it too)
_ANCHORS_RPC = "posttest_anchors"
_ANCHORS_PAGE = MAX_ROWS


def posttest_anchors(
    *,
    user_id: str | None = None,
    anchor_from: datetime | None = None,
    anchor_to: datetime | None = None,
    limit: int | None = None,
) -> tuple[list[dict], bool]:
    """Concept anchors: rows {node_id, user_id, course_id, concept_name,
    anchor_at}, in node-id order — one student's nodes (`user_id`) or every
    student's (None: the admin funnel); `anchor_from` / `anchor_to` bound the
    anchor time (inclusive). A node with no course is never returned (it is
    never posed). Returns (rows, truncated): reaching `limit` stops the read
    and says whether more could follow. A failed read raises — never an empty
    answer it cannot vouch for."""
    rows: list[dict] = []
    after: str | None = None
    while True:
        page = rpc(
            _ANCHORS_RPC,
            {
                "p_user_id": user_id,
                "p_anchor_from": anchor_from.isoformat() if anchor_from else None,
                "p_anchor_to": anchor_to.isoformat() if anchor_to else None,
                "p_after_node_id": after,
                "p_limit": _ANCHORS_PAGE,
            },
        ) or []
        rows.extend(page)
        if limit is not None and len(rows) >= limit:
            return rows[:limit], len(page) == _ANCHORS_PAGE or len(rows) > limit
        if len(page) < _ANCHORS_PAGE:
            return rows, False
        after = str(page[-1]["node_id"])
