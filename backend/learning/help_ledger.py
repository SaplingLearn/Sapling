"""PKG-14 (review fix round, owner decision 1, spec §13 A93): the per-student
HELP LEDGER, on half A's `learning_reveals` table (migration
20261001010805_learning_help_ledger.sql).

What writes a 'help' row, keyed by (student, question_hash), AS THE HELP IS
SERVED — exactly these (corrected in the PKG-14 final fix round, spec §13 A102;
the first docstring and the migration's header comment listed more):

- a hint rung GRANTED by /api/learn/loop/hint (the rung, before its text);
- a planned loop hint turn's rung — H6 when a leaking deterministic payload is
  served as H6 (`_LoopTurn._record_planned_help`);
- an H4 sibling payload, on the SIBLING, at RUNG_NO_CREDIT_MIN;
- a quiz "Ask about this" session, on the quiz question, at RUNG_NO_CREDIT_MIN
  (spec §13 A99, services/quiz_ask.py).

A served-text reveal is a 'reveal' row (reveal_store), which `max_help` reads as
RUNG_NO_CREDIT_MIN. What writes NO help row, on purpose: a POST-GRADE release —
the feedback turn after a graded wrong answer states the answer, but the item
is already graded, and every later grade of it floors through the evidence
journal instead (a wrong attempt marks the item released in
`loop_state_store.revealed_hashes`, A23, which `_reveal_floor` reads as
RUNG_NO_CREDIT_MIN), so a help row would add nothing. Review, the post-test and
the probe serve no hints, so their rows are 'posed' rows only.

Every grade's floor is the MAX help ever recorded for that pair (`max_help`),
read by loop checks, review, the post-test, the probe and the quiz submit; the
loop grading routes re-read it inside their claim, right before the one
evidence write.

The ledger also records every item POSED to the student ('posed', with
`graded_at` set once graded): the served-text scan set is every posed item not
yet graded, newest first, bounded by LOOP_SCAN_POSED_MAX (`ungraded_posed_window`).

Hashes, ids, rungs and timestamps only — never item or tutor text. Every
reader and writer RAISES on a failed store call; the callers decide (a failed
floor read is RUNG_NO_CREDIT_MIN, a failed write follows the accepted DB-down
rule: the session-local record stands and an ERROR is logged; the quiz-ask
write refuses the session instead, as it has no session-local record)."""

from __future__ import annotations

from datetime import datetime, timezone

from db.connection import pg_quote_value, table
from learning.params import LADDER_MAX_RUNG, RUNG_NO_CREDIT_MIN

_LEDGER = "learning_reveals"

#: where a unit of help or a pose came from (`source`)
SOURCES = ("loop", "review", "posttest", "probe", "scan", "quiz")  # "quiz": A99 quiz-ask


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


def max_help_many(user_id: str, question_hashes) -> dict[str, int]:
    """`max_help` for several items in ONE `in.(...)` read (spec §13 A99: the quiz
    submit's help floor); every asked hash is a key (0 with no row). Raises."""
    hashes = sorted({h for h in question_hashes or [] if h})
    out = dict.fromkeys(hashes, 0)
    if not hashes:
        return out
    rows = table(_LEDGER).select(
        "kind,rung,question_hash",
        filters={
            "user_id": f"eq.{user_id}",
            "question_hash": f"in.({','.join(pg_quote_value(h) for h in hashes)})",
            "kind": "in.(help,reveal)",
        },
    ) or []
    for row in rows:
        qh = row.get("question_hash")
        if qh not in out:
            continue
        if row.get("kind") == "reveal":
            out[qh] = max(out[qh], RUNG_NO_CREDIT_MIN)
        elif row.get("rung") is not None:
            out[qh] = max(out[qh], min(int(row["rung"]), LADDER_MAX_RUNG))
    return out


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


#: rows read per distinct item `ungraded_posed_window` may return (a re-posed
#: item has more than one 'posed' row)
_ROWS_PER_ITEM = 4


def ungraded_posed_window(
    user_id: str, limit: int
) -> tuple[list[tuple[str, datetime | None]], datetime | None]:
    """(question_hash, first posed at) for the student's posed-and-ungraded
    items, newest first, at most `limit` DISTINCT items — and the EDGE: the
    posed time of the newest row left out, or None when nothing was. Rows are
    left out when the distinct limit is reached, AND (review minor 3) whenever
    the read itself hit its row limit — older rows may exist that were never
    fetched, so the edge is then the oldest fetched row's time (or now, if it
    has none): the caller's 'unscanned' marker there covers them. Raises."""
    fetch = max(1, int(limit)) * _ROWS_PER_ITEM
    rows = table(_LEDGER).select(
        "question_hash,at",
        filters={"user_id": f"eq.{user_id}", "kind": "eq.posed", "graded_at": "is.null"},
        order="at.desc",
        limit=fetch,
    ) or []
    seen: dict[str, datetime | None] = {}
    edge: datetime | None = None
    for row in rows:
        qh = row.get("question_hash")
        if not qh:
            continue
        at = _ts(row.get("at"))
        if qh not in seen:
            if len(seen) >= limit:
                edge = at or datetime.now(timezone.utc)
                break
            seen[qh] = at
        elif at is not None and (seen[qh] is None or at < seen[qh]):
            seen[qh] = at
    if len(rows) >= fetch:
        oldest = _ts(rows[-1].get("at")) or datetime.now(timezone.utc)
        edge = oldest if edge is None else max(edge, oldest)
    return list(seen.items()), edge


def ungraded_posed(user_id: str, limit: int) -> list[tuple[str, datetime | None]]:
    """`ungraded_posed_window`'s items only (raises)."""
    return ungraded_posed_window(user_id, limit)[0]


def _ts(value) -> datetime | None:
    if value is None:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
