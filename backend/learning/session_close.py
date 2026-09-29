"""End-of-session close: draft assembly, deterministic fallback, normalisation
of the agent output, encrypted storage (spec §4/§9, §13 A11/A25; research
report §Close). No LLM here — spec §12; the agent is `agents/session_close.py`.

`build_close` bounds what the close agent may see (the last
LOOP_HISTORY_MAX_MESSAGES user/assistant turns, each cut to
CLOSE_TRANSCRIPT_TURN_MAX_CHARS, the per-concept probability deltas of this
session's evidence rows and the misconception keys). `fallback_close` is the
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


class ConceptDelta(BaseModel):
    node_id: str
    p_before: float
    p_after: float


class CloseDraft(BaseModel):
    """The ONLY thing the close agent sees (plus its system prompt)."""

    turns: list[Turn]
    concepts: list[ConceptDelta]
    misconception_keys: list[str]
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


def _deltas_from_evidence(evidence_rows: list[dict]) -> dict[str, tuple[float, float]]:
    """The first p_before and the last p_after per node, in row order; a row
    missing either probability is skipped."""
    out: dict[str, tuple[float, float]] = {}
    for row in evidence_rows or []:
        node, before, after = row.get("node_id"), row.get("p_before"), row.get("p_after")
        if not node or before is None or after is None:
            continue
        first = out[node][0] if node in out else float(before)
        out[node] = (first, float(after))
    return out


def build_close(
    session_messages: list[dict],
    evidence_rows: list[dict],
    misconception_keys: list[str],
    learner_deltas: dict[str, tuple[float, float]],
    *,
    concept_names: dict[str, str] | None = None,
) -> CloseDraft:
    """Pure: the bounded draft. `session_messages` are decrypted `{role,
    content}` dicts in order; `evidence_rows` this session's `evidence` journal
    rows in apply order; `learner_deltas` `{node_id: (p_before, p_after)}`
    (derived from `evidence_rows` when empty)."""
    kept = [
        Turn(role=m["role"], content=str(m["content"])[:CLOSE_TRANSCRIPT_TURN_MAX_CHARS])
        for m in session_messages or []
        if m.get("role") in _ROLES and m.get("content")
    ]
    deltas = learner_deltas or _deltas_from_evidence(evidence_rows)
    return CloseDraft(
        turns=kept[-LOOP_HISTORY_MAX_MESSAGES:],
        concepts=[ConceptDelta(node_id=n, p_before=b, p_after=a) for n, (b, a) in deltas.items()],
        misconception_keys=list(dict.fromkeys(k for k in misconception_keys or [] if k)),
        concept_names={k: v for k, v in (concept_names or {}).items() if k and v},
    )


def concept_label(draft: CloseDraft, node_id: str) -> str:
    """The concept's name when the draft knows it, else its node id."""
    return draft.concept_names.get(node_id) or node_id


def fallback_close(draft: CloseDraft) -> CloseRecord:
    """The deterministic close (no LLM): the concept deltas as the summary, the
    fixed self-evaluation question, no if-then plan, `model_written=False`."""
    summary = "; ".join(
        f"{concept_label(draft, c.node_id)}: p {c.p_before:.2f} → {c.p_after:.2f}"
        for c in draft.concepts
    )
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
    only when present, as `_consume_pending` inserts it); False when it is
    missing and no defaults were given (nothing inserted). Never `upsert`."""
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
    table("sessions").insert(row)
    return True


def store_close(
    session_id: str,
    user_id: str,
    record: CloseRecord,
    phase: str,
    *,
    row_defaults: dict | None,
) -> None:
    """Encrypt and store the close with the phase the session stopped in.
    ValueError on a phase outside CLOSE_PHASES (the CHECK enum); LookupError
    when the row is missing and cannot be created (no defaults) — a close is
    never silently dropped. DB errors propagate."""
    if phase not in CLOSE_PHASES:
        raise ValueError(f"store_close: phase {phase!r} not in CLOSE_PHASES")
    if not ensure_session_row(session_id, user_id, row_defaults):
        raise LookupError(f"store_close: sessions row {session_id} missing")
    table("sessions").update(
        {"close_json": encrypt_json(record.model_dump()), "close_phase": phase},
        filters={"id": f"eq.{session_id}"},
    )
