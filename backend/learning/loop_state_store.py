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
from datetime import datetime, timezone
from typing import NamedTuple

from db.connection import page_all, pg_quote_value, table
from learning import params, void_store
from learning.policy import WINDOW_KEEP, LoopState, Opportunity

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


class LoopSessionClosed(RuntimeError):
    """A conditional write cannot reopen an ended or durably closed session."""


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


def save_loop_state(
    session_id: str, state: LoopState, *, expected_rev: int, require_open: bool = False
) -> SaveOutcome:
    doc = state.to_json()
    filters = {"id": f"eq.{session_id}", "loop_state_rev": f"eq.{expected_rev}"}
    if require_open:
        filters.update({"ended_at": "is.null", "close_json": "is.null"})
    rows = table("sessions").update(
        {"loop_state": doc, "loop_state_rev": expected_rev + 1},
        filters=filters,
    )
    if rows:
        return SaveOutcome.SAVED
    existing = table("sessions").select(
        "id,ended_at,close_json" if require_open else "id",
        filters={"id": f"eq.{session_id}"},
        limit=1,
    )
    if existing:
        if require_open and (
            existing[0].get("ended_at") is not None or existing[0].get("close_json") is not None
        ):
            raise LoopSessionClosed(session_id)
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
    session_id: str, mutate: Callable[[LoopState], LoopState | None], *, require_open: bool = False
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
        extra = {"require_open": True} if require_open else {}
        outcome = save_loop_state(session_id, state, expected_rev=rev, **extra)
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


def _released(row: dict) -> bool:
    """revealed_hashes' rule on one evidence row: a wrong/idk answer, or a
    worked answer shown on the way (max_rung >= RUNG_NO_CREDIT_MIN)."""
    return row.get("correct") is False or (row.get("max_rung") or 0) >= params.RUNG_NO_CREDIT_MIN


def recent_evidence(user_id: str, node_id: str, *, since: str) -> list[dict] | None:
    """PKG-10 (spec §13 A76): the student's evidence rows on this node
    journaled since `since`, oldest first, each as {question_hash, released,
    shape} — `released` by revealed_hashes' rule, `shape` the item's isomorph
    class (format, difficulty; None when the item cannot be read). Two
    owner-scoped reads (the node's rows like _evidence_rows, then the rows'
    items' plaintext format/difficulty in one `in.(...)` select); None when a
    read failed (never raises)."""
    try:
        rows = table("node_mastery_events").select(
            "check_item_id,question_hash,correct,max_rung,graph_nodes!inner(user_id)",
            filters={
                "graph_nodes.user_id": f"eq.{user_id}",
                "node_id": f"eq.{node_id}",
                "event_type": "eq.evidence",
                "created_at": f"gte.{since}",
            },
            order="created_at.asc,evidence_seq.asc",
        )
        ids = sorted({r["check_item_id"] for r in rows or [] if r.get("check_item_id")})
        shapes: dict[str, tuple] = {}
        if ids:
            for item in table("check_items").select(
                "id,format,difficulty",
                filters={"id": f"in.({','.join(pg_quote_value(i) for i in ids)})"},
            ):
                shapes[item["id"]] = (item.get("format"), item.get("difficulty"))
    except Exception as exc:
        logger.warning("recent_evidence read failed: %s", type(exc).__name__)
        return None
    return [
        {
            "question_hash": row.get("question_hash"),
            "released": _released(row),
            "shape": shapes.get(row.get("check_item_id")),
        }
        for row in rows or []
    ]


def _number_or_none(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def opportunity_window(user_id: str, node_id: str) -> list[Opportunity] | None:
    """Spec §13 A122: the concept's band-control window — its newest
    WINDOW_KEEP graded opportunities (evidence rows that name their item, the
    rows scripts/derive_zpd_metrics.py reads), newest LAST, across sessions
    and surfaces, as policy.Opportunity. Read in the journal's order
    (created_at, evidence_seq, id) and owner-scoped through the
    graph_nodes!inner embed. Propagation is never journaled, so it is never an
    opportunity. None when the read failed (never raises): the caller then
    has no verdict to apply, never an invented one."""
    try:
        rows = table("node_mastery_events").select(
            "correct,assisted,max_rung,p_before,p_after,graph_nodes!inner(user_id)",
            filters={
                "graph_nodes.user_id": f"eq.{user_id}",
                "node_id": f"eq.{node_id}",
                "event_type": "eq.evidence",
                "question_hash": "not.is.null",
            },
            order="created_at.desc,evidence_seq.desc.nullslast,id.desc",
            limit=WINDOW_KEEP,
        )
    except Exception as exc:
        logger.warning("opportunity_window read failed: %s", type(exc).__name__)
        return None
    return [
        Opportunity(
            correct=row.get("correct") is True,
            assisted=row.get("assisted") is not False,  # unknown help is never unassisted
            max_rung=int(row.get("max_rung") or 0),
            p_before=_number_or_none(row.get("p_before")),
            p_after=_number_or_none(row.get("p_after")),
        )
        for row in reversed(rows or [])
    ]


class EvidenceSpan(NamedTuple):
    """One concept's journaled evidence span (spec §13 A112)."""

    first_id: str  # node_mastery_events.id of the FIRST evidence row: the post-test anchor
    first_at: datetime  # its time; the journal is append-only, so practice never moves it
    last_at: datetime  # the latest evidence time (what a pose's delay is measured from)


def _journal_time(raw) -> datetime:
    """A journal created_at as an aware datetime; an unreadable one raises
    (a timestamp the database wrote has no honest default)."""
    ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def evidence_spans(user_id: str, course_id: str) -> dict[str, EvidenceSpan]:
    """A112: node id → its EvidenceSpan, for every node of the student's course
    that has evidence rows (event_type='evidence'), read in the journal's total
    order (created_at, evidence_seq, id — read_planning_history's), paged and
    owner- and course-scoped through the graph_nodes!inner embed. Propagation is
    never journaled, so it neither anchors a concept nor refreshes its last
    evidence (learner_state.last_evidence_at is the DECAY anchor, which a
    propagation can set — HANDOFF-03). Spec §13 A123: a VOID row (graded
    against an item staff retired) is no evidence — it neither anchors the
    concept nor counts as its last evidence; a concept whose every row is void
    has no span (no valid graded evidence to measure a delay from). A failed
    read raises."""
    voided = void_store.voided_event_ids(user_id=user_id)
    spans: dict[str, EvidenceSpan] = {}
    for row in page_all(
        _MasteryEventsRead(),
        "id,node_id,created_at,evidence_seq,graph_nodes!inner(user_id,course_id)",
        filters={
            "graph_nodes.user_id": f"eq.{user_id}",
            "graph_nodes.course_id": f"eq.{course_id}",
            "event_type": "eq.evidence",
        },
        order="created_at.asc,evidence_seq.asc.nullslast,id.asc",
    ):
        node = row.get("node_id")
        if not node or not row.get("id") or row["id"] in voided:
            continue
        at = _journal_time(row.get("created_at"))
        span = spans.get(node)
        if span is None:
            spans[node] = EvidenceSpan(str(row["id"]), at, at)
        elif at > span.last_at:
            spans[node] = span._replace(last_at=at)
    return spans


def seen_hashes(user_id: str) -> set[str]:
    """Every question_hash the user has evidence on (A23) — void rows included
    (spec §13 A123): seen is exposure, and a voided grade was still seen."""
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
    # PKG-14 (spec §13 A88): the open posed items a served tutor turn stated
    for row in page_all(
        table(_REVEALS),
        "id,question_hash",
        filters={"user_id": f"eq.{user_id}", "kind": "eq.reveal"},
        order="id",
    ):
        if row.get("question_hash"):
            revealed.add(row["question_hash"])
    return revealed


def reported_hashes(user_id: str) -> set[str]:
    """Items the user reported ("Report this question", spec §13 A113): never
    served to them again — every selection that excludes seen_hashes and
    revealed_hashes excludes these too (in-session checks, the goal preflight,
    the probe, review and the post-test). One owner-scoped read of the
    reports table (its writer is learning/item_reports.py; this module never
    inserts). Raises on a failed read, like the two sets above."""
    return {
        row["question_hash"]
        for row in page_all(
            table(_REPORTS),
            "question_hash",
            filters={"user_id": f"eq.{user_id}"},
            order="question_hash",
        )
        if row.get("question_hash")
    }


# PKG-14 (spec §13 A88): the learning_reveals table (its writers and the
# marker reader live in learning/reveal_store.py; this module never inserts)
_REVEALS = "learning_reveals"
# A113: the check_item_reports table (written by learning/item_reports.py)
_REPORTS = "check_item_reports"
