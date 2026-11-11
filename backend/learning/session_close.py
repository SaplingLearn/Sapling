"""End-of-session close: draft assembly, deterministic fallback, normalisation
of the agent output, encrypted storage (spec §4/§9, §13 A11/A25/A117; research
report §Close). No LLM here — spec §12; the agent is `agents/session_close.py`.

`build_close` bounds what the close agent may see (the last
LOOP_HISTORY_MAX_MESSAGES user/assistant turns, each cut to
CLOSE_TRANSCRIPT_TURN_MAX_CHARS, each checked concept's change from an honest
baseline, the graded answers counted apart by phase and the misconception
keys). A117: the BKT prior is no measurement of the student, so a concept with
no evidence before this session starts at its FIRST measurement here (for a
probed concept, the check-in result), never at the prior; a concept with
evidence before the session starts at the estimate it had then. Check-in
(probe) answers came before any teaching and are counted apart from the
teaching-phase checks. `fallback_close` is the
deterministic close — stored when the session has no evidence (nothing was
graded), when the close budget is hard, or when the agent is unavailable
(ADR 0024 honest degrade, `model_written=False`). `normalise_close` bounds the
agent's output and never lets it invent a misconception key.

`ensure_session_row` is the A11 insert-if-missing helper for `sessions` (a
lazy session that closes before its first /chat has no row): select by id,
insert the `_consume_pending` shape when missing and defaults are given —
never `upsert`, which would overwrite an existing row's mode/topic.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from itertools import takewhile
from typing import Any, Literal, get_args

from pydantic import BaseModel

from db.connection import table
from learning.params import (
    CLOSE_IF_THEN_MAX_CHARS,
    CLOSE_PHASES,
    CLOSE_SELF_EVAL_MAX_CHARS,
    CLOSE_SUMMARY_MAX_CHARS,
    CLOSE_TRANSCRIPT_TURN_MAX_CHARS,
    LOOP_HISTORY_MAX_MESSAGES,
)
# A117: the probe's journal-row rule is the one the A112 pre/post report reads
# a pretest by (learning_gain.pretest_outcome) — one source, learning/probe.py
from learning.probe import is_probe_row, probe_history_hashes
from services.encryption import encrypt_json

logger = logging.getLogger("sapling.learning.session_close")

#: The deterministic self-evaluation prompt (a string, not a tunable).
FALLBACK_SELF_EVAL = "Which step were you least sure of this session?"
#: The fallback summary of a session with no graded check.
NO_EVIDENCE_SUMMARY = "No graded checks this session."
_ROLES = ("user", "assistant")


class Turn(BaseModel):
    role: str
    content: str


#: Where a concept's reported change starts — `ConceptDelta.p_before` (spec §13
#: A117). "pre_session": the concept had evidence before this session, so the
#: estimate right before this session's first evidence on it. "check_in" /
#: "teaching": it had none, so its FIRST measurement here — for a concept first
#: measured by check-in (probe) answers, the check-in result (where teaching on
#: it began, or after its last check-in answer when it was never taught: every
#: check-in answer came before any teaching, so none of them is a move);
#: otherwise the estimate right after its first teaching-phase evidence. The
#: BKT prior is never a start: it measures nothing about the student.
Baseline = Literal["pre_session", "check_in", "teaching"]
BASELINES: tuple[str, ...] = get_args(Baseline)


class ConceptDelta(BaseModel):
    """One checked concept's reported change: from `p_before`, where it starts
    (`baseline`), to `p_after`, the estimate after this session's last
    evidence on it. A close stored before A117 has no `baseline` key."""

    node_id: str
    p_before: float
    p_after: float
    baseline: Baseline = "pre_session"

    @property
    def first_measured(self) -> bool:
        return self.baseline != "pre_session"


def move(delta: ConceptDelta) -> str:
    """The reported change's direction, "up", "down" or "unchanged" (the close
    agent copies it instead of reading two numbers: a flash-lite close called
    a drop progress). For a first-measured concept it is the move AFTER the
    first measurement (for a probed one, after the check-in), never one from
    the prior."""
    if delta.p_after > delta.p_before:
        return "up"
    return "down" if delta.p_after < delta.p_before else "unchanged"


class CloseDraft(BaseModel):
    """The ONLY thing the close agent sees (plus its system prompt)."""

    turns: list[Turn]
    concepts: list[ConceptDelta]
    misconception_keys: list[str]
    # A117: this session's graded evidence rows (`correct` set), counted apart by
    # phase (`is_probe_row`) — the check-in came before any teaching, so its
    # answers locate where the student starts and are never a teaching score
    probe_answers: int = 0
    probe_correct: int = 0
    teach_checks: int = 0
    teach_correct: int = 0
    # node_id -> concept name (one graph_nodes read in the route); rendering
    # only — the stored record keeps node ids (the brief resolves names itself).
    concept_names: dict[str, str] = {}


class CloseRecord(BaseModel):
    """`sessions.close_json`, encrypted (spec §4). Nothing else is stored there:
    no message text, no timestamps, no self-eval answer."""

    summary: str
    self_eval: str
    if_then: str
    concepts: list[ConceptDelta]
    misconceptions: list[str]
    model_written: bool


def session_probe_hashes(loop_state: Mapping[str, Any] | None) -> frozenset[str]:
    """The question hashes of the session's recorded check-in answers:
    `probe.probe_history_hashes` of `loop_state.probe.history`."""
    probe = loop_state.get("probe") if isinstance(loop_state, Mapping) else None
    return probe_history_hashes(probe.get("history") if isinstance(probe, Mapping) else None)


def _node_rows(evidence_rows: list[dict]) -> dict[str, list[dict]]:
    """Per node, in apply order, its rows carrying both probabilities (a row
    missing either is skipped)."""
    out: dict[str, list[dict]] = {}
    for row in evidence_rows or []:
        node = row.get("node_id")
        if not node or row.get("p_before") is None or row.get("p_after") is None:
            continue
        out.setdefault(node, []).append(row)
    return out


def _start(
    rows: list[dict], *, measured_before: bool, probe_hashes: Collection[str]
) -> tuple[str, float]:
    """(baseline, p) where one concept's reported change starts (A117):

    - evidence before the session: its first row's p_before;
    - first measured by check-in answers: the check-in result — the p_before
      of its first teaching-phase row (where teaching on it began: after all
      of its check-in answers AND whatever the other check-in answers inferred
      about it, since prerequisite propagation is never journaled), or, never
      taught, the p_after of its last check-in answer. No check-in answer, its
      own or another concept's, ever reads as this concept's move;
    - first measured in teaching: its first row's p_after."""
    if measured_before:
        return "pre_session", rows[0]["p_before"]
    check_in = list(takewhile(lambda r: is_probe_row(r, probe_hashes), rows))
    if not check_in:
        return "teaching", rows[0]["p_after"]
    taught = rows[len(check_in) :]
    return "check_in", taught[0]["p_before"] if taught else check_in[-1]["p_after"]


def build_close(
    session_messages: list[dict],
    evidence_rows: list[dict],
    misconception_keys: list[str],
    *,
    measured_before: Collection[str],
    probe_hashes: Collection[str] = (),
    concept_names: dict[str, str] | None = None,
) -> CloseDraft:
    """Pure: the bounded draft. `session_messages` are decrypted `{role,
    content}` dicts in order; `evidence_rows` this session's `evidence` journal
    rows in apply order; `measured_before` the node ids the journal measured
    before this session first did; `probe_hashes` this session's check-in
    question hashes (`session_probe_hashes`).

    A117: a node in `measured_before` reports from its first row's p_before
    (the estimate before the session); any other node from its first
    measurement here (`_start`: the check-in result, or its first teaching-phase
    row's p_after), so the BKT prior never stands as a level the student had
    and no check-in answer reads as a move. Every node reports to its last
    row's p_after."""
    kept = [
        Turn(role=m["role"], content=str(m["content"])[:CLOSE_TRANSCRIPT_TURN_MAX_CHARS])
        for m in session_messages or []
        if m.get("role") in _ROLES and m.get("content")
    ]
    before = set(measured_before)
    concepts = []
    for node, rows in _node_rows(evidence_rows).items():
        baseline, start = _start(rows, measured_before=node in before, probe_hashes=probe_hashes)
        concepts.append(
            ConceptDelta(
                node_id=node,
                p_before=float(start),
                p_after=float(rows[-1]["p_after"]),
                baseline=baseline,
            )
        )
    graded = [r for r in evidence_rows or [] if r.get("correct") is not None]
    probe = [r for r in graded if is_probe_row(r, probe_hashes)]
    teach = [r for r in graded if not is_probe_row(r, probe_hashes)]
    return CloseDraft(
        turns=kept[-LOOP_HISTORY_MAX_MESSAGES:],
        concepts=concepts,
        misconception_keys=list(dict.fromkeys(k for k in misconception_keys or [] if k)),
        probe_answers=len(probe),
        probe_correct=sum(1 for r in probe if r.get("correct")),
        teach_checks=len(teach),
        teach_correct=sum(1 for r in teach if r.get("correct")),
        concept_names={k: v for k, v in (concept_names or {}).items() if k and v},
    )


def concept_label(draft: CloseDraft, node_id: str) -> str:
    """The concept's name when the draft knows it, else its node id."""
    return draft.concept_names.get(node_id) or node_id


#: What the deterministic close may print, most to least (review MINOR 3): the
#: route serves the first whose text states no unreleased item's answer.
CLOSE_FALLBACK_DETAILS = ("named", "unnamed", "bare")
#: The `bare` fallback summary: no concept name, no number.
BARE_SUMMARY = "Your checks this session were recorded."


#: Where the deterministic close says a first measurement was taken (A117).
_FIRST_MEASURED_AT = {"check_in": "at the check-in", "teaching": "this session"}


def _fallback_change(c: ConceptDelta) -> str:
    """One concept in the deterministic summary (A117): a change from the
    pre-session estimate ("p a → b"); a first measurement with no move after
    it ("first measured at the check-in, p a"); or the move after it ("since
    the check-in, p a → b", "first measured this session, p a → b") — never a
    move from the prior."""
    if not c.first_measured:
        return f"p {c.p_before:.2f} → {c.p_after:.2f}"
    if move(c) == "unchanged":
        return f"first measured {_FIRST_MEASURED_AT[c.baseline]}, p {c.p_before:.2f}"
    if c.baseline == "check_in":  # the start is where teaching on it began
        return f"since the check-in, p {c.p_before:.2f} → {c.p_after:.2f}"
    return f"first measured this session, p {c.p_before:.2f} → {c.p_after:.2f}"


def fallback_close(draft: CloseDraft, *, detail: str = "named") -> CloseRecord:
    """The deterministic close (no LLM): the concept changes as the summary
    (`named`: "<name>: p a → b", or for a concept first measured this session
    "<name>: first measured at the check-in, p a" / "<name>: since the
    check-in, p a → b", A117 — `_fallback_change`; `unnamed`: the name
    withheld; `bare`: no name and no number), the fixed self-evaluation
    question, no if-then plan, `model_written=False`."""
    if detail not in CLOSE_FALLBACK_DETAILS:
        raise ValueError(f"fallback_close: unknown detail {detail!r}")
    summary = "; ".join(
        (f"{concept_label(draft, c.node_id)}: " if detail == "named" else "a checked concept: ")
        + _fallback_change(c)
        for c in draft.concepts
    )
    if detail == "bare" and draft.concepts:
        summary = BARE_SUMMARY
    return CloseRecord(
        summary=summary or NO_EVIDENCE_SUMMARY,
        self_eval=FALLBACK_SELF_EVAL,
        if_then="",
        concepts=list(draft.concepts),
        misconceptions=list(draft.misconception_keys),
        model_written=False,
    )


def normalise_close(output, draft: CloseDraft) -> CloseRecord:
    """The agent's flat output, bounded: each string cut to its cap, the open
    misconception keys intersected with the draft's (the model may drop keys,
    never invent them), the concepts copied from the draft."""
    allowed = set(draft.misconception_keys)
    keys = [k for k in dict.fromkeys(output.open_misconception_keys or []) if k in allowed]
    return CloseRecord(
        summary=(output.summary or "")[:CLOSE_SUMMARY_MAX_CHARS],
        self_eval=(output.self_eval_prompt or "")[:CLOSE_SELF_EVAL_MAX_CHARS],
        if_then=(output.if_then_plan or "")[:CLOSE_IF_THEN_MAX_CHARS],
        concepts=list(draft.concepts),
        misconceptions=keys,
        model_written=True,
    )


def ensure_session_row(session_id: str, user_id: str, row_defaults: dict | None) -> bool:
    """A11 insert-if-missing: True when the `sessions` row exists or was just
    inserted from `row_defaults` (`mode`/`topic` are NOT NULL; `offering_id`
    only when present, as `_consume_pending` inserts it; ON CONFLICT DO
    NOTHING, then re-read, so a concurrent insert is no error); False when it
    is missing and no defaults were given (nothing inserted). Never `upsert`."""
    if table("sessions").select("id", filters={"id": f"eq.{session_id}"}):
        return True
    if not row_defaults:
        return False
    row = {
        "id": session_id,
        "user_id": user_id,
        "mode": row_defaults.get("mode"),
        "topic": row_defaults.get("topic"),
    }
    if row_defaults.get("offering_id"):
        row["offering_id"] = row_defaults["offering_id"]
    # Review M5: a concurrent writer may insert the row between the select and
    # here — ON CONFLICT DO NOTHING (never an upsert: it would overwrite
    # mode/topic, A11), then re-read.
    table("sessions").insert_ignore_duplicates(row, on_conflict="id")
    return bool(table("sessions").select("id", filters={"id": f"eq.{session_id}"}))


def store_close(
    session_id: str,
    user_id: str,
    record: CloseRecord,
    phase: str,
    *,
    row_defaults: dict | None,
) -> bool:
    """Encrypt and store the close with the phase the session stopped in, once:
    True when this write stored it, False when a close was already stored.
    ValueError on a phase outside CLOSE_PHASES (the CHECK enum); LookupError
    when the row is missing and cannot be created (no defaults) — a close is
    never silently dropped. DB errors propagate."""
    if phase not in CLOSE_PHASES:
        raise ValueError(f"store_close: phase {phase!r} not in CLOSE_PHASES")
    if not ensure_session_row(session_id, user_id, row_defaults):
        raise LookupError(f"store_close: sessions row {session_id} missing")
    # Review MAJOR 2: written once — the update matches only while close_json is
    # still null (`is.null`, never an equality filter on the ciphertext, inv 9).
    rows = table("sessions").update(
        {"close_json": encrypt_json(record.model_dump()), "close_phase": phase},
        filters={"id": f"eq.{session_id}", "close_json": "is.null"},
    )
    return bool(rows)
