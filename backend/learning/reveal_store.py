"""PKG-14 (spec §13 A88): the learning_reveals store — the open posed items a
SERVED tutor turn revealed, and the 'unscanned' fail-closed markers of turns
whose open items could not be read. Keyed by the student (not a session row),
so a reveal is durable the moment it is served, the loop opener included.
Hashes, ids and timestamps only — never item or tutor text. The read half of a
reveal is loop_state_store.revealed_hashes (A23), which every selection and
grading path already reads."""

from __future__ import annotations

from datetime import datetime

from db.connection import page_all, table

_REVEALS = "learning_reveals"  # loop_state_store.revealed_hashes reads it too

# ── served reveals (PKG-14, spec §13 A88) ──────────────────────────────────
# learning_reveals is keyed by the student: a reveal is durable the moment the
# turn is served, with or without a session row (the loop opener has none).



def record_reveals(user_id: str, hashes, *, session_id: str | None, source: str) -> None:
    """Append one 'reveal' row per question hash (raises on a failed write)."""
    rows = [
        {
            "user_id": user_id,
            "kind": "reveal",
            "question_hash": h,
            "session_id": session_id,
            "source": source,
        }
        for h in sorted(set(hashes or []))
    ]
    if rows:
        table(_REVEALS).insert(rows)


def record_unscanned(user_id: str, *, session_id: str | None, source: str, at: datetime) -> None:
    """Append an 'unscanned' marker: the turn's open items could not be read, so
    every item posed at or before `at` grades as assisted (raises on failure)."""
    table(_REVEALS).insert(
        {
            "user_id": user_id,
            "kind": "unscanned",
            "question_hash": None,
            "session_id": session_id,
            "source": source,
            "at": at.isoformat(),
        }
    )


def unscanned_since(user_id: str, posed_at: datetime | None) -> bool:
    """Whether a marker of this student lands at or after `posed_at` (None: any)
    — in learning_reveals or, the write fallback, a session's
    loop_state["reveal_unscanned"]. Raises on a failed read (callers fail closed)."""
    filters = {"user_id": f"eq.{user_id}", "kind": "eq.unscanned"}
    if posed_at is not None:
        filters["at"] = f"gte.{posed_at.isoformat()}"
    if table(_REVEALS).select("id", filters=filters, limit=1):
        return True
    floor = posed_at.timestamp() if posed_at is not None else None
    for _sid, mark in unscanned_reveals(user_id):
        at = mark.get("at")
        if floor is None or (isinstance(at, (int, float)) and float(at) >= floor):
            return True
    return False


def unscanned_reveals(user_id: str) -> list[tuple[str, dict]]:
    """PKG-14 (spec §13 A88): every (session_id, marker {"at"}) in
    loop_state["reveal_unscanned"] across the user's sessions — the fallback
    store when a learning_reveals write failed. Raises on a failed read (the
    caller fails closed)."""
    out: list[tuple[str, dict]] = []
    for row in page_all(
        table("sessions"),
        "id,marks:loop_state->reveal_unscanned",
        filters={"user_id": f"eq.{user_id}", "loop_state->reveal_unscanned": "not.is.null"},
        order="id",
    ):
        for mark in row.get("marks") or []:
            if isinstance(mark, dict):
                out.append((row["id"], mark))
    return out
