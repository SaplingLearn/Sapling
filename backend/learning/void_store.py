"""Reads of the void record (learning-loop spec §13 A123): which evidence journal
rows are void.

`learning_evidence_voids` holds one append-only row per voided
node_mastery_events row (keyed by its id), written only inside the single
graph writer's void transaction (services/graph_service.py::_apply_void), so a
row is void exactly when the state was recomputed without it. Every reader
that reads the journal AS EVIDENCE leaves these rows out (the learner's
evidence spans for the post-test windows, the planning history, a session's
close and its measured-before read, the learner brief's past closes, the
learning velocity, the ZPD metrics, the band-control window, the trial
export's anchors). Readers of EXPOSURE do not: a void row still means the student saw
the question (the seen / revealed sets, the re-check-after-release rule, the
post-test's "practised since the pose" floor) — and its item is retired, so it
is never served again anyway. The admin reports apply the same rule to the
retired items directly (learning/evidence_void.py).

Owner- or node-scoped reads, paged; a failed read raises (the caller decides:
a planning read fails closed, a cosmetic one degrades)."""

from __future__ import annotations

from db.connection import page_all, table

VOIDS = "learning_evidence_voids"


def voided_event_ids(
    *, user_id: str | None = None, node_id: str | None = None, session_id: str | None = None
) -> set[str]:
    """The ids of the void journal rows of one student, one node or one
    session (at least one scope; they combine)."""
    filters: dict[str, str] = {}
    if user_id:
        filters["user_id"] = f"eq.{user_id}"
    if node_id:
        filters["node_id"] = f"eq.{node_id}"
    if session_id:
        filters["session_id"] = f"eq.{session_id}"
    if not filters:
        raise ValueError("a void read names the student, node or session it is for")
    return {
        row["event_id"]
        for row in page_all(table(VOIDS), "event_id", filters=filters, order="event_id")
        if row.get("event_id")
    }


def voided_by_node(user_id: str) -> dict[str, set[str]]:
    """The student's void journal row ids, grouped by node: one paged read for
    a reader that then reads several of the student's nodes one at a time."""
    out: dict[str, set[str]] = {}
    for row in page_all(
        table(VOIDS), "event_id,node_id", filters={"user_id": f"eq.{user_id}"}, order="event_id"
    ):
        if row.get("event_id") and row.get("node_id"):
            out.setdefault(row["node_id"], set()).add(row["event_id"])
    return out


def voided_sessions(user_id: str) -> set[str]:
    """The sessions in which the student was graded against an item since
    retired (their evidence there is void)."""
    return {
        row["session_id"]
        for row in page_all(
            table(VOIDS),
            "event_id,session_id",
            filters={"user_id": f"eq.{user_id}", "session_id": "not.is.null"},
            order="event_id",
        )
        if row.get("session_id")
    }
