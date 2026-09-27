"""sessions.loop_state read/write (spec §4 PKG-06, §9). The only impure module
in the ZPD layer; policy.py stays free of db imports.

Sessions are lazy (routes/learn.py:36): the row may not exist until the first
chat turn. `save_loop_state` therefore updates by id and reports a miss; it
never inserts or upserts a sessions row (spec §9, §13 A11). The row is
materialised by the legacy `_consume_pending` insert (PKG-07) or by the A11
insert-if-missing helper (PKG-09).

Fails soft on the document, never on the database: a missing row or a
malformed stored document is a fresh `LoopState()` (malformed logs WARNING),
but a failed read or write propagates — answering a read error with a fresh
state would let the next save overwrite the real one. Reads and writes key on
the session id alone; the caller has already checked that the session is the
requesting user's.
"""

from __future__ import annotations

import logging

from db.connection import table
from learning.policy import LoopState

logger = logging.getLogger("sapling.learning.loop_state")


def load_loop_state(session_id: str) -> LoopState:
    rows = table("sessions").select("loop_state", filters={"id": f"eq.{session_id}"}, limit=1)
    if not rows:
        return LoopState()
    try:
        return LoopState.from_json(rows[0].get("loop_state") or {})
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning(
            "load_loop_state: malformed loop_state for %s (%s); starting fresh", session_id, exc
        )
        return LoopState()


def save_loop_state(session_id: str, state: LoopState) -> bool:
    doc = state.to_json()
    rows = table("sessions").update({"loop_state": doc}, filters={"id": f"eq.{session_id}"})
    if not rows:
        logger.warning(
            "save_loop_state: sessions row %s not materialised; loop_state not saved", session_id
        )
        return False
    return True
