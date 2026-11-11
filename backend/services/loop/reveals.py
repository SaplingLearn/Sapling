"""Reveals and the help floor (A88, A93): what a served turn revealed, the
reveal floor a grade reads, the planning-evidence tags and the help ledger.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from learning.evidence import PlanningProvenance
from learning.loop_state_store import revealed_hashes
from learning.reveal_store import record_reveals, record_unscanned, unscanned_since
from learning.help_ledger import earliest_open_pose, max_help
from learning.params import RUNG_ASSISTED_MIN, RUNG_NO_CREDIT_MIN

from services.loop.state import _update_loop_state

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


def _mark_revealed(state: dict, hashes, mark: dict | None) -> None:
    """The loop_state fallback of a failed learning_reveals write: hashes join
    loop_state["revealed"] (A23); a marker joins loop_state["reveal_unscanned"]."""
    if hashes:
        revealed = list(state.get("revealed") or [])
        state["revealed"] = revealed + [h for h in hashes if h not in revealed]
    if mark is not None:
        state["reveal_unscanned"] = [*(state.get("reveal_unscanned") or []), mark]


def _persist_reveals(
    user_id: str, session_id: str | None, hashes, *, unscanned: bool, source: str, at: datetime
) -> bool:
    """Record the reveals (or the marker) in learning_reveals; on a failed write
    fall back to the session's loop_state; if that fails too, log an ERROR.
    True when either store holds them (A138 second review: a caller that would
    stop scanning the items once revealed must know when they were not)."""
    try:
        if unscanned:
            record_unscanned(user_id, session_id=session_id, source=source, at=at)
        elif hashes:
            record_reveals(user_id, hashes, session_id=session_id, source=source)
        return True
    except Exception:
        logger.warning("learning_reveals write failed; falling back to loop_state", exc_info=True)
    mark = {"at": at.timestamp(), "source": source} if unscanned else None
    try:
        if not session_id:
            raise RuntimeError("no session row to fall back to")
        _update_loop_state(session_id, lambda st: _mark_revealed(st, hashes, mark))
        return True
    except Exception:
        logger.error("served reveals of %s LOST (both stores failed)", user_id, exc_info=True)
        return False


def _reveal_floor(user_id: str, item, posed_at: datetime | None = None) -> int:
    """The lowest rung a grade of `item` may claim — A93's help floor (owner
    decision 1): the MAX help ever recorded for (student, item) in the help
    ledger, across every session and surface (a served reveal counts as
    RUNG_NO_CREDIT_MIN); RUNG_NO_CREDIT_MIN when the item is revealed by the
    evidence journal or a session's revealed list (A23); RUNG_ASSISTED_MIN while
    an 'unscanned' marker lands at or after the item's FIRST ungraded pose (or
    `posed_at`; None: any marker). A failed read is RUNG_NO_CREDIT_MIN (fail
    closed, minor 8)."""
    try:
        floor = max_help(user_id, item.question_hash)
        if item.question_hash in revealed_hashes(user_id):
            floor = max(floor, RUNG_NO_CREDIT_MIN)
        first = earliest_open_pose(user_id, item.question_hash)
        anchor = min((t for t in (first, posed_at) if t is not None), default=None)
        if floor < RUNG_ASSISTED_MIN and unscanned_since(user_id, anchor):
            floor = RUNG_ASSISTED_MIN
    except Exception:
        logger.warning("help ledger reads failed; the grade carries no credit", exc_info=True)
        return RUNG_NO_CREDIT_MIN
    return floor


def _refloor(evidence: list, user_id: str, item, posed_at: datetime | None, used: int) -> int:
    """A93: the help floor re-read INSIDE the grading claim, right before the one
    evidence write — so help served while the grade ran (a hint in another
    session, a reveal streaming meanwhile) is seen. Raises the pending Evidence
    rows of `item` to the new floor (apply_graph_update re-derives the weight);
    returns the rung the grade carries."""
    floor = _reveal_floor(user_id, item, posed_at)
    if floor > int(used):
        for row in evidence:
            if row.get("question_hash") == item.question_hash and int(row.get("max_rung") or 0) < floor:
                row["max_rung"] = floor
                if floor >= RUNG_ASSISTED_MIN:
                    row["assisted"] = True
    return max(floor, int(used))


def _tag_planning_evidence(pending: list, item, *, synthetic_idk: bool, previously_seen: bool,
                           operation_id: str | None = None, observed_at: float | None = None) -> None:
    """Actual probe/check grades, goal or not; never answers or inferred history."""
    provenance = PlanningProvenance(
        check_item_id=item.id, difficulty=item.difficulty,
        synthetic_idk=synthetic_idk, previously_seen=previously_seen,
    ).model_dump()
    for row in pending:
        if row.get("question_hash") == item.question_hash and row.get("check_item_id") == item.id:
            row["planning_provenance"] = provenance
            if operation_id is not None:
                row["operation_id"] = operation_id
                row["observed_at"] = datetime.fromtimestamp(observed_at, tz=timezone.utc).isoformat()


def _ledger(write, *args, **kwargs) -> None:
    """A help-ledger write under the accepted DB-down rule: the session-local
    record (the step's rung, loop_state["revealed"]) stands and an ERROR is
    logged; never raises."""
    try:
        write(*args, **kwargs)
    except Exception:
        logger.error("help ledger write %s failed", getattr(write, "__name__", "?"), exc_info=True)
