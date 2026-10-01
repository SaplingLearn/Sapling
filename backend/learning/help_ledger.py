"""PKG-14 (review fix round, owner decision 1, spec §13 A93): the per-student
HELP LEDGER, on half A's `learning_reveals` table (migration
20261001010805_learning_help_ledger.sql).

Every unit of help a student got on an item — a hint rung above H0 in any
session or surface, an H4 sibling payload, an H6 release, worked solution or
deterministic reference, a served-text reveal — is a row keyed by
(student, question_hash), written AS THE HELP IS SERVED. Every grade's floor is
the MAX help ever recorded for that pair (`max_help`), across loop checks,
review, the post-test and the probe; the grading routes re-read it inside their
claim, right before the one evidence write.

The ledger also records every item POSED to the student ('posed', with
`graded_at` set once graded): the served-text scan set is every posed item not
yet graded, newest first, bounded by LOOP_SCAN_POSED_MAX (`ungraded_posed`).

Hashes, ids, rungs and timestamps only — never item or tutor text. Every
reader and writer RAISES on a failed store call; the callers decide (a failed
floor read is RUNG_NO_CREDIT_MIN, a failed write follows the accepted DB-down
rule: the session-local record stands and an ERROR is logged)."""

from __future__ import annotations

from datetime import datetime, timezone

from db.connection import table
from learning.params import LADDER_MAX_RUNG, RUNG_NO_CREDIT_MIN

_LEDGER = "learning_reveals"

#: where a unit of help or a pose came from (`source`)
SOURCES = ("loop", "review", "posttest", "probe", "scan")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_help(
    user_id: str, question_hash: str, rung: int, *, source: str, session_id: str | None = None
) -> None:
    """One 'help' row: `question_hash` got help at `rung` (raises on failure)."""
    rung = int(rung)
    if not question_hash or rung <= 0:
        return
    table(_LEDGER).insert(
        {
            "user_id": user_id,
            "kind": "help",
            "question_hash": question_hash,
            "rung": min(rung, LADDER_MAX_RUNG),
            "session_id": session_id,
            "source": source,
            "at": _now_iso(),
        }
    )


def record_posed(
    user_id: str, question_hash: str, *, source: str, session_id: str | None = None
) -> None:
    """One 'posed' row: the student was shown the item's prompt (raises)."""
    if not question_hash:
        return
    table(_LEDGER).insert(
        {
            "user_id": user_id,
            "kind": "posed",
            "question_hash": question_hash,
            "session_id": session_id,
            "source": source,
            "at": _now_iso(),
        }
    )


def mark_graded(user_id: str, question_hash: str) -> None:
    """Close every ungraded 'posed' row of the item: it leaves the scan set (raises)."""
    table(_LEDGER).update(
        {"graded_at": _now_iso()},
        filters={
            "user_id": f"eq.{user_id}",
            "kind": "eq.posed",
            "question_hash": f"eq.{question_hash}",
            "graded_at": "is.null",
        },
        prefer_return_minimal=True,
    )


def max_help(user_id: str, question_hash: str) -> int:
    """The highest help ever recorded for (student, item): a 'help' row's rung,
    a 'reveal' row counting as RUNG_NO_CREDIT_MIN; 0 with none (raises)."""
    rows = table(_LEDGER).select(
        "kind,rung",
        filters={
            "user_id": f"eq.{user_id}",
            "question_hash": f"eq.{question_hash}",
            "kind": "in.(help,reveal)",
        },
    ) or []
    floor = 0
    for row in rows:
        if row.get("kind") == "reveal":
            floor = max(floor, RUNG_NO_CREDIT_MIN)
        elif row.get("rung") is not None:
            floor = max(floor, int(row["rung"]))
    return min(floor, LADDER_MAX_RUNG)


def earliest_open_pose(user_id: str, question_hash: str) -> datetime | None:
    """When the item was FIRST posed and not yet graded (None: no such row; raises)."""
    rows = table(_LEDGER).select(
        "at",
        filters={
            "user_id": f"eq.{user_id}",
            "kind": "eq.posed",
            "question_hash": f"eq.{question_hash}",
            "graded_at": "is.null",
        },
        order="at.asc",
        limit=1,
    ) or []
    return _ts(rows[0].get("at")) if rows else None


def ungraded_posed(user_id: str, limit: int) -> list[tuple[str, datetime | None]]:
    """(question_hash, first posed at) for the student's posed-and-ungraded
    items, newest first, at most `limit` DISTINCT items (raises)."""
    rows = table(_LEDGER).select(
        "question_hash,at",
        filters={"user_id": f"eq.{user_id}", "kind": "eq.posed", "graded_at": "is.null"},
        order="at.desc",
        limit=max(1, int(limit)) * 4,  # a re-posed item has more than one row
    ) or []
    seen: dict[str, datetime | None] = {}
    for row in rows:
        qh = row.get("question_hash")
        if not qh:
            continue
        at = _ts(row.get("at"))
        if qh not in seen:
            if len(seen) >= limit:
                break
            seen[qh] = at
        elif at is not None and (seen[qh] is None or at < seen[qh]):
            seen[qh] = at
    return list(seen.items())


def _ts(value) -> datetime | None:
    if value is None:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
