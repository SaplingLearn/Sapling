"""sessions.loop_state read/write (spec §4 PKG-06, §9). The only impure module
in the ZPD layer; policy.py stays free of db imports.

Sessions are lazy (routes/learn.py:36): the row may not exist until the first
chat turn. `save_loop_state` therefore updates by id and reports a miss; it
never inserts or upserts a sessions row (spec §9, §13 A11). The row is
materialised by the legacy `_consume_pending` insert (PKG-07) or by the A11
insert-if-missing helper (PKG-09).

Fails soft on the document, never on the database: a missing row is a fresh
`LoopState()`, and a malformed stored document logs WARNING and loads through
`LoopState.recover` (each malformed PKG-06 field starts fresh, every other
package's key survives, so the next save cannot erase them). A failed read or
write propagates — answering a read error with a fresh state would let the
next save overwrite the real one; the caller (PKG-07) handles it. Reads and
writes key on the session id alone; the caller has already checked that the
session is the requesting user's.

A save replaces the whole document (last writer wins): two overlapping
requests on one session that each load, change and save lose one writer's
changes. Callers load, change and save within one request, as late as they
can, and never save a state loaded before a long stream without re-loading.
"""

from __future__ import annotations

import logging

from db.connection import page_all, table
from learning.params import RUNG_NO_CREDIT_MIN
from learning.policy import LoopState

logger = logging.getLogger("sapling.learning.loop_state")


def load_loop_state(session_id: str) -> LoopState:
    rows = table("sessions").select("loop_state", filters={"id": f"eq.{session_id}"}, limit=1)
    if not rows:
        return LoopState()
    doc = rows[0].get("loop_state") or {}
    try:
        return LoopState.from_json(doc)
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning(
            "load_loop_state: malformed loop_state for %s (%s); its malformed PKG-06 "
            "fields start fresh, every other key is kept",
            session_id,
            exc,
        )
        return LoopState.recover(doc)


def save_loop_state(session_id: str, state: LoopState) -> bool:
    doc = state.to_json()
    rows = table("sessions").update({"loop_state": doc}, filters={"id": f"eq.{session_id}"})
    if not rows:
        logger.warning(
            "save_loop_state: sessions row %s not materialised; loop_state not saved", session_id
        )
        return False
    return True


# ── Seen / revealed question hashes (spec A23; PKG-07 adds these readers) ──


class _MasteryEventsRead:
    """A read-only `page_all` handle over node_mastery_events. Invariant 1
    (PKG-03's ast half) allows `table("node_mastery_events")` only as a direct
    `.select` / `.select_with_count` read, so the handle is never passed
    around: every page is one direct read (services/check_item_service.py's
    `_GraphNodesRead` precedent)."""

    name = "node_mastery_events"

    def select_with_count(self, *args, **kwargs):
        return table("node_mastery_events").select_with_count(*args, **kwargs)


def _evidence_rows(user_id: str) -> list[dict]:
    """The user's evidence rows (spec §5: event_type='evidence').
    node_mastery_events has no user_id; the graph_nodes!inner embed scopes it
    to the node owner in one PostgREST read per page, paged past MAX_ROWS."""
    return list(
        page_all(
            _MasteryEventsRead(),
            "question_hash,correct,max_rung,graph_nodes!inner(user_id)",
            filters={
                "graph_nodes.user_id": f"eq.{user_id}",
                "event_type": "eq.evidence",
                "question_hash": "not.is.null",
            },
            order="id",
        )
    )


def seen_hashes(user_id: str) -> set[str]:
    """Every question_hash the user has evidence on (A23)."""
    return {r["question_hash"] for r in _evidence_rows(user_id) if r.get("question_hash")}


def revealed_hashes(user_id: str) -> set[str]:
    """Items whose reference the user has seen (A23): a wrong attempt (the
    answer is released), an attempt at or above RUNG_NO_CREDIT_MIN, or an H4
    sibling shown in any session (the top-level loop_state["revealed"], A17)."""
    revealed = {
        r["question_hash"]
        for r in _evidence_rows(user_id)
        if r.get("question_hash")
        and (r.get("correct") is False or (r.get("max_rung") or 0) >= RUNG_NO_CREDIT_MIN)
    }
    for row in page_all(
        table("sessions"), "id,loop_state", filters={"user_id": f"eq.{user_id}"}, order="id"
    ):
        revealed.update((row.get("loop_state") or {}).get("revealed") or [])
    return revealed
