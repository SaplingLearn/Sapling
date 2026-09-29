"""sessions.loop_state read/write (spec §4 PKG-06, §9). The only impure module
in the ZPD layer; policy.py stays free of db imports.

Sessions are lazy (routes/learn.py:36): the row may not exist until the first
chat turn. `save_loop_state` therefore updates by id and reports a miss; it
never inserts or upserts a sessions row (spec §9, §13 A11). The row is
materialised by the legacy `_consume_pending` insert (PKG-07) or by the A11
insert-if-missing helper (PKG-09).

Fails soft on the document, never on the database: a missing row is a fresh
`LoopState()` at revision 0, and a malformed stored document logs WARNING and
loads through `LoopState.recover` (each malformed PKG-06 field starts fresh,
every other package's key survives, so the next save cannot erase them). A
failed read or write propagates — answering a read error with a fresh state
would let the next save overwrite the real one; the caller (PKG-07) handles it.
Reads and writes key on the session id alone; the caller has already checked
that the session is the requesting user's.

Compare-and-set (owner decision A38 06(q)): a streamed teach turn and
`/check/next` can overlap on one session. `load_loop_state` returns the row's
`loop_state_rev` with the state; `save_loop_state` writes only when the stored
revision still equals `expected_rev` (PostgREST filter `loop_state_rev=eq.N`)
and sets it to N+1, returning an explicit `SaveOutcome`: SAVED, CONFLICT
(another writer saved first; the stored document is untouched) or MISSING (no
row). A zero-row update re-selects the row by id to tell the last two apart.
`update_loop_state(session_id, mutate)` is the usual entry point: load ->
mutate -> save, and on a conflict it re-loads and re-applies `mutate` to the
FRESH state, up to `params.LOOP_STATE_CAS_RETRIES` retries, then raises
`LoopStateConflict`. So `mutate` must express the caller's own change against
whatever state it is given (increment a counter, set a key), never copy a
state loaded earlier; a conflict never silently loses either writer's change.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Callable
from typing import NamedTuple

from db.connection import page_all, table
from learning import params
from learning.policy import LoopState

logger = logging.getLogger("sapling.learning.loop_state")


class SaveOutcome(str, enum.Enum):
    SAVED = "saved"
    CONFLICT = "conflict"  # the stored revision moved on; nothing was written
    MISSING = "missing"  # no sessions row (lazy sessions); nothing was written


class LoadedLoopState(NamedTuple):
    state: LoopState
    rev: int  # sessions.loop_state_rev as read; pass it back as expected_rev


class LoopStateConflict(RuntimeError):
    """update_loop_state lost the compare-and-set on every attempt."""


def load_loop_state(session_id: str) -> LoadedLoopState:
    rows = table("sessions").select(
        "loop_state,loop_state_rev", filters={"id": f"eq.{session_id}"}, limit=1
    )
    if not rows:
        return LoadedLoopState(LoopState(), 0)
    rev = int(rows[0].get("loop_state_rev") or 0)
    doc = rows[0].get("loop_state") or {}
    try:
        return LoadedLoopState(LoopState.from_json(doc), rev)
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning(
            "load_loop_state: malformed loop_state for %s (%s); its malformed PKG-06 "
            "fields start fresh, every other key is kept",
            session_id,
            exc,
        )
        return LoadedLoopState(LoopState.recover(doc), rev)


def save_loop_state(session_id: str, state: LoopState, *, expected_rev: int) -> SaveOutcome:
    doc = state.to_json()
    rows = table("sessions").update(
        {"loop_state": doc, "loop_state_rev": expected_rev + 1},
        filters={"id": f"eq.{session_id}", "loop_state_rev": f"eq.{expected_rev}"},
    )
    if rows:
        return SaveOutcome.SAVED
    if table("sessions").select("id", filters={"id": f"eq.{session_id}"}, limit=1):
        logger.info(
            "save_loop_state: sessions row %s moved past revision %s; not saved",
            session_id,
            expected_rev,
        )
        return SaveOutcome.CONFLICT
    logger.warning(
        "save_loop_state: sessions row %s not materialised; loop_state not saved", session_id
    )
    return SaveOutcome.MISSING


def update_loop_state(
    session_id: str, mutate: Callable[[LoopState], LoopState | None]
) -> LoadedLoopState | None:
    """Load, apply `mutate` (in place, or return a replacement state), save
    with compare-and-set. On CONFLICT it re-loads and re-applies `mutate` to
    the fresh state, at most `params.LOOP_STATE_CAS_RETRIES` times, then
    raises LoopStateConflict. Returns the saved state and its new revision, or
    None when the sessions row does not exist (nothing written)."""
    for _ in range(1 + params.LOOP_STATE_CAS_RETRIES):
        state, rev = load_loop_state(session_id)
        replaced = mutate(state)
        if replaced is not None:
            state = replaced
        outcome = save_loop_state(session_id, state, expected_rev=rev)
        if outcome is SaveOutcome.SAVED:
            return LoadedLoopState(state, rev + 1)
        if outcome is SaveOutcome.MISSING:
            return None
    raise LoopStateConflict(
        f"loop_state for session {session_id} conflicted "
        f"{1 + params.LOOP_STATE_CAS_RETRIES} times; not saved"
    )


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


def latest_evidence_released(user_id: str, node_id: str, *, since: str) -> bool | None:
    """PKG-10 (spec §13 A76, the session-hop half of the re-check rule): whether
    the student's LATEST evidence row on this node journaled since `since` was a
    release by revealed_hashes' rule (a wrong/idk answer, or max_rung >=
    RUNG_NO_CREDIT_MIN); None when there is no such row or the read failed
    (never raises). One direct read, scoped to the node's owner like
    _evidence_rows."""
    try:
        rows = table("node_mastery_events").select(
            "correct,max_rung,graph_nodes!inner(user_id)",
            filters={
                "graph_nodes.user_id": f"eq.{user_id}",
                "node_id": f"eq.{node_id}",
                "event_type": "eq.evidence",
                "created_at": f"gte.{since}",
            },
            order="created_at.desc,evidence_seq.desc",
            limit=1,
        )
    except Exception as exc:
        logger.warning("latest_evidence_released read failed: %s", type(exc).__name__)
        return None
    if not rows:
        return None
    row = rows[0]
    return row.get("correct") is False or (row.get("max_rung") or 0) >= params.RUNG_NO_CREDIT_MIN


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
        and (r.get("correct") is False or (r.get("max_rung") or 0) >= params.RUNG_NO_CREDIT_MIN)
    }
    # Bounded to what is needed (PKG-07 review round 3, m7): only the user's
    # sessions whose loop_state carries a revealed list, and only that list —
    # never every session's whole loop_state document.
    for row in page_all(
        table("sessions"),
        "id,revealed:loop_state->revealed",
        filters={"user_id": f"eq.{user_id}", "loop_state->revealed": "not.is.null"},
        order="id",
    ):
        revealed.update(row.get("revealed") or [])
    return revealed
