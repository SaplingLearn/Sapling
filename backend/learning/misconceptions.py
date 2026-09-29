"""Per-student misconception store and the slip / misconception / novice rule
(spec §3.3), plus the class rollup (spec §4 PKG-10, n >=
MISCONCEPTION_ROLLUP_MIN_USERS enforced in SQL).

The rule is pure: typed attempts in, one verdict out. A wrong_key reaches it
only when the student's reason matched that key through the decision seam
(spec §13 A22/A24; agents/tools/check.py::match_wrong_key), and only a key the
item lists and that is identifier-shaped is ever stored. The store fails
closed: a DB error is a WARNING and an empty result, never an error on the
student's turn (it is a diagnosis input, never a gate). The rollup is a
backend function — never a tutor tool (ADR 0023 §5;
tests/test_learning_loop_invariants.py::test_inv_17).

The session attempt log and the confrontation marker live in the
`sessions.loop_state` document as the top-level keys `attempts` and
`confront` (ids, enums, bools, numbers and the plaintext key only — spec §4
"no free text"). Every reader and writer goes through the accessors below,
so the shape lives in one file.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from db.connection import pg_quote_value, rpc, table
from learning.evidence import MisconceptionVerdict
from learning.params import (
    GAP_CONFIDENCE_MAX,
    MISCONCEPTION_CONFIDENCE,
    MISCONCEPTION_KEY_MAX_CHARS,
    MISCONCEPTION_MIN_ISOMORPHS,
    MISCONCEPTION_RECENT_DAYS,
    NOVICE_FLOOR_IDK,
    NOVICE_FLOOR_MISSES,
)
from services.encryption import encrypt_if_present

logger = logging.getLogger("sapling.learning.misconceptions")

#: The rule's verdict: the six spec §3.3 verdicts plus "none" (a plain correct
#: attempt with nothing to diagnose). One type with Evidence.verdict.
Verdict = MisconceptionVerdict

#: A wrong_key as check items state it (checks.wrong_key_form: snake_case). Only
#: such a key is stored, rendered in the learner brief or named to the tutor.
KEY_PATTERN = re.compile(rf"[a-z0-9][a-z0-9_]{{0,{MISCONCEPTION_KEY_MAX_CHARS - 1}}}")

_ATTEMPTS = "attempts"
_CONFRONT = "confront"
_CONFRONT_KEYS = ("node_id", "wrong_key", "check_item_id")
_OPEN_COLS = "node_id,wrong_key,count"


def is_key(key: object) -> bool:
    """True for an identifier-shaped wrong_key (KEY_PATTERN, full match)."""
    return isinstance(key, str) and KEY_PATTERN.fullmatch(key) is not None


class Attempt(BaseModel):
    """One graded attempt, as the session attempt log stores it (ids, enums,
    bools, numbers — no free text, so it may live in sessions.loop_state)."""

    model_config = ConfigDict(extra="forbid")

    question_hash: str
    node_id: str  # the student's graph_nodes.id (items key on concept_key, A2)
    correct: bool
    wrong_key: str | None = None  # only a key the student's reason matched (A22)
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0
    )  # STUDENT-stated; never the grader's
    difficulty: int
    idk: bool = False
    isomorph_of: str | None = None  # the question_hash this attempt re-asks
    # the reference was released after this attempt (a wrong or idk grade, A16)
    released: bool = False
    # graded as a same-session re-check: served after a released answer on
    # this concept (fix round F1: never a full-weight unassisted first attempt)
    after_release: bool = False


# ── the rule (pure) ─────────────────────────────────────────────────────────


def slip_or_misconception(history: list[Attempt]) -> Verdict:
    """Spec §3.3. `history` = this session's attempts on ONE node, oldest
    first; the verdict is about the last one. First matching rule wins:
    right-with-a-matched-wrong-reason → not_known; right on an isomorph of an
    earlier wrong → slip; right → none; wrong with stated confidence >=
    MISCONCEPTION_CONFIDENCE, or the same matched key on
    MISCONCEPTION_MIN_ISOMORPHS distinct items → misconception (it outranks
    novice: PKG-08's probe.novice_floor owns probe exit on its own); misses
    at difficulty 1 >= NOVICE_FLOOR_MISSES or idks >= NOVICE_FLOOR_IDK →
    novice; stated confidence <= GAP_CONFIDENCE_MAX → gap; else unknown
    (re-ask an isomorph). The grader's confidence never enters."""
    if not history:
        return "none"
    nodes = {a.node_id for a in history}
    if len(nodes) != 1:
        raise ValueError(f"slip_or_misconception takes one node's history, got {sorted(nodes)}")
    last = history[-1]
    if last.correct:
        if last.wrong_key:
            return "not_known"  # right answer, wrong reason: treat as a miss (§3.3)
        earlier = {a.question_hash: a for a in history[:-1]}
        prior = earlier.get(last.isomorph_of or "")
        if prior is not None and not prior.correct:
            return "slip"
        return "none"
    if last.confidence is not None and last.confidence >= MISCONCEPTION_CONFIDENCE:
        return "misconception"
    if last.wrong_key:
        hashes = {
            a.question_hash for a in history if not a.correct and a.wrong_key == last.wrong_key
        }
        if len(hashes) >= MISCONCEPTION_MIN_ISOMORPHS:
            return "misconception"
    floor_misses = sum(1 for a in history if not a.correct and a.difficulty == 1)
    idks = sum(1 for a in history if a.idk)
    if floor_misses >= NOVICE_FLOOR_MISSES or idks >= NOVICE_FLOOR_IDK:
        return "novice"
    if last.confidence is not None and last.confidence <= GAP_CONFIDENCE_MAX:
        return "gap"
    return "unknown"


# ── the session attempt log and the marker (sessions.loop_state) ────────────


def attempts_of(loop_state: dict) -> list:
    """The session attempt log (`loop_state["attempts"]`), created on first
    use; a malformed stored value is replaced by an empty log (fail closed: a
    lost diagnosis, never an error). Returns the live list: callers append."""
    log = loop_state.get(_ATTEMPTS)
    if not isinstance(log, list):
        log = []
        loop_state[_ATTEMPTS] = log
    return log


def released_on_node(loop_state: dict, node_id: str) -> bool:
    """True when an earlier attempt on this concept in this session had its
    reference released (a wrong or idk grade). An item graded after it is a
    same-session re-check: the student has just read a worked answer of the
    concept, so its correct answer is neither full-weight nor a streak (the
    check route passes `same_session_recheck=True`, graph_service's rule)."""
    return any(a.released for a in attempts_for_node(attempts_of(loop_state), node_id))


def attempts_for_node(log: list, node_id: str) -> list[Attempt]:
    """The session attempt log filtered to one concept, order preserved. An
    entry that does not validate as an Attempt is skipped."""
    out: list[Attempt] = []
    for entry in log:
        if not isinstance(entry, dict) or entry.get("node_id") != node_id:
            continue
        try:
            out.append(Attempt.model_validate(entry))
        except ValidationError:
            continue
    return out


def confront_of(loop_state: dict) -> dict | None:
    """The pending confrontation marker {node_id, wrong_key, check_item_id},
    or None — also for a malformed stored value (an incomplete marker, or a
    key that is not identifier-shaped, is never used)."""
    marker = loop_state.get(_CONFRONT)
    if not isinstance(marker, dict):
        return None
    if not all(isinstance(marker.get(k), str) and marker.get(k) for k in _CONFRONT_KEYS):
        return None
    if not is_key(marker["wrong_key"]):
        return None
    return {k: marker[k] for k in _CONFRONT_KEYS}


def set_confront(loop_state: dict, marker: dict | None) -> None:
    """Set (the hook) or clear (the route, after a model turn used it) the marker."""
    loop_state[_CONFRONT] = {k: marker[k] for k in _CONFRONT_KEYS} if marker else None


def carry(loop_state: dict, diagnosis: dict | None) -> None:
    """Apply the hook's change to a loop-state document: append its attempt;
    set its marker when it set one, or clear the one it cleared. The route's
    compare-and-set mutate calls this on the FRESH document (A38 06(q)), so
    the change is re-applied, never a copy of an older state. None changes
    nothing."""
    if not diagnosis:
        return
    attempt = diagnosis.get("attempt")
    if isinstance(attempt, dict):
        attempts_of(loop_state).append(dict(attempt))
    if diagnosis.get("confront"):
        set_confront(loop_state, diagnosis["confront"])
    elif diagnosis.get("cleared") and confront_of(loop_state) == diagnosis["cleared"]:
        set_confront(loop_state, None)  # only that marker: a newer one is never lost


# ── the store (fails closed) ────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _utcnow().isoformat()


def _open_filters(user_id: str, node_id: str, wrong_key: str) -> dict:
    return {
        "user_id": f"eq.{user_id}",
        "node_id": f"eq.{node_id}",
        "wrong_key": f"eq.{wrong_key}",
        "resolved_at": "is.null",
    }


def record(
    user_id: str,
    node_id: str,
    check_item_id: str | None,
    wrong_key: str,
    evidence_text: str | None,
) -> dict:
    """Insert-or-increment on (user_id, node_id, wrong_key) among OPEN rows —
    ONE atomic statement, the `misconception_record` SQL function (INSERT …
    ON CONFLICT on the open-row partial unique index; PKG-10 fix round F5: a
    read-then-write from here lost increments and opened duplicate rows under
    concurrency). `evidence_text` (the student's answer) is encrypted here, at
    the write boundary, and never read back. A key that is not
    identifier-shaped is refused with nothing written. Returns {id, count};
    {} on a refusal or a DB error. Never raises."""
    if not is_key(wrong_key):
        logger.warning("misconceptions.record: refused a key that is not identifier-shaped")
        return {}
    try:
        rows = rpc(
            "misconception_record",
            {
                "p_id": str(uuid.uuid4()),
                "p_user_id": user_id,
                "p_node_id": node_id,
                "p_check_item_id": check_item_id,
                "p_wrong_key": wrong_key,
                "p_evidence_text": encrypt_if_present(evidence_text),
            },
        )
        return dict(rows[0]) if rows else {}
    except Exception as exc:  # fail closed: a diagnosis input, never a gate
        logger.warning(
            "misconceptions.record failed for %s/%s/%s: %s",
            user_id,
            node_id,
            wrong_key,
            type(exc).__name__,
        )
        return {}


def resolve(user_id: str, node_id: str, wrong_key: str) -> int:
    """Mark the open row(s) for the key resolved. Returns rows touched; 0 on
    a DB error. Never raises. (No caller yet: PKG-12's review is the natural one.)"""
    try:
        t = table("misconceptions")
        filters = _open_filters(user_id, node_id, wrong_key)
        rows = t.select("id", filters=filters) or []
        if rows:
            t.update({"resolved_at": _now()}, filters=filters)
        return len(rows)
    except Exception as exc:
        logger.warning(
            "misconceptions.resolve failed for %s/%s/%s: %s",
            user_id,
            node_id,
            wrong_key,
            type(exc).__name__,
        )
        return 0


def open_for(user_id: str, node_ids: list[str]) -> list[dict]:
    """Open misconceptions for the student on the given nodes, seen within
    MISCONCEPTION_RECENT_DAYS (F6: resolve() has no caller yet, so an old row
    would otherwise re-list forever): [{node_id, wrong_key, count}], count
    descending; only identifier-shaped keys. No read for an empty id list.
    Never reads evidence_text; [] on a DB error (never raises)."""
    ids = list(dict.fromkeys(n for n in node_ids or [] if n))
    if not ids:
        return []
    since = (_utcnow() - timedelta(days=MISCONCEPTION_RECENT_DAYS)).isoformat()
    try:
        rows = (
            table("misconceptions").select(
                _OPEN_COLS,
                filters={
                    "user_id": f"eq.{user_id}",
                    "node_id": f"in.({','.join(pg_quote_value(n) for n in ids)})",
                    "resolved_at": "is.null",
                    "last_seen_at": f"gte.{since}",
                },
            )
            or []
        )
    except Exception as exc:
        logger.warning("misconceptions.open_for failed for %s: %s", user_id, type(exc).__name__)
        return []
    out = [
        {"node_id": r["node_id"], "wrong_key": r["wrong_key"], "count": int(r.get("count") or 0)}
        for r in rows
        if is_key(r.get("wrong_key"))
    ]
    return sorted(out, key=lambda r: -r["count"])


def rollup(course_id: str) -> list[dict]:
    """Class rollup via the SECURITY DEFINER SQL function: rows
    {concept_key, wrong_key, users}, keyed on the course concept (spec §13
    A29; concept_key == check_items.concept_key), and only at or above
    MISCONCEPTION_ROLLUP_MIN_USERS distinct students (enforced in SQL, never
    here). Backend-only. NOT a tutor tool (ADR 0023 §5, inv 17). [] on a DB
    error."""
    try:
        return rpc("misconception_rollup", {"p_course_id": course_id}) or []
    except Exception as exc:
        logger.warning(
            "misconceptions.rollup failed for course %s: %s", course_id, type(exc).__name__
        )
        return []
