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

Spec §13 A127 closes a misconception: a correct, unassisted first attempt
(`resolves`) on an isomorph — another question on the same concept — whose
item lists the key (`resolvable_keys`) resolves the student's open row
(`resolve`, one conditional UPDATE), after the grading route's flush and
claimed save, with one `learn.misconception_resolved` event per row
(`resolve_after_grade`). A resolved row leaves every reader (`open_for`,
`open_keys`): the learner brief, the session close and the review interleave.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from db.connection import pg_quote_value, rpc, table
from learning.evidence import MisconceptionVerdict
from learning.loop_state_store import recent_evidence  # A76's journal half
from learning.multi_concept import isomorph_class
from learning.params import (
    GAP_CONFIDENCE_MAX,
    MISCONCEPTION_CONFIDENCE,
    MISCONCEPTION_KEY_MAX_CHARS,
    MISCONCEPTION_MIN_ISOMORPHS,
    MISCONCEPTION_RECENT_DAYS,
    NOVICE_FLOOR_IDK,
    NOVICE_FLOOR_MISSES,
    RECHECK_RELEASE_WINDOW_HOURS,
)
from services.encryption import encrypt_if_present
from services.events_service import log_event

logger = logging.getLogger("sapling.learning.misconceptions")

#: Spec §13 A127: one closed misconception (the event names the surface that
#: closed it: the check route, the probe or the review).
RESOLVED_EVENT = "learn.misconception_resolved"
RESOLVE_SURFACES = ("check", "probe", "review")

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
    # STUDENT-stated (A127: evidence.stated_confidence of the answer's label);
    # never the grader's. None = none stated.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    difficulty: int
    idk: bool = False
    isomorph_of: str | None = None  # the question_hash this attempt re-asks
    # the reference was released after this attempt: a wrong or idk grade (A16),
    # or a worked answer shown on the way (max_rung >= RUNG_NO_CREDIT_MIN) — the
    # loop_state_store.revealed_hashes rule (A76)
    released: bool = False
    # graded as a re-check: the next item on this concept after a release
    # (A76: never a full-weight unassisted first attempt)
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


# ── resolution (spec §13 A127; pure) ────────────────────────────────────────


def resolves(attempt: Mapping) -> bool:
    """Spec §13 A127, the attempt half of the resolution rule: a correct,
    unassisted first attempt — correct, not an idk, rung 0 (no hint and no
    reveal: the grading route's help floor already raised the rung of an item
    with recorded help or a released answer, A88/A93), not assisted, and not a
    re-check after a release (§13 A76: never an unassisted first attempt).
    Reads the FINAL evidence of the grade (or the single writer's committed
    observation of it) — never the grader's or the student's confidence."""
    if not isinstance(attempt, Mapping):
        return False
    rung = attempt.get("max_rung")
    return (
        attempt.get("correct") is True
        and not attempt.get("idk")
        and isinstance(rung, int)
        and not isinstance(rung, bool)
        and rung == 0
        and not attempt.get("assisted")
        and not attempt.get("same_session_recheck")
    )


def resolvable_keys(
    item, *, correct: bool, idk: bool = False, matched_wrong_key: str | None = None
) -> list[str]:
    """Spec §13 A127: the misconceptions a graded answer to `item` can close —
    every identifier-shaped key the item lists among its common wrong reasons
    (what the item tests), and only for a correct answer that is no idk. The
    key the student's reason matched stays open: a right answer for a reason
    the grader matched to that misconception (§3.3 "right answer, wrong reason")
    shows it held, never gone. Sorted, deduplicated; [] otherwise."""
    if not correct or idk:
        return []
    listed = {getattr(w, "key", None) for w in getattr(item, "common_wrong", None) or []}
    return sorted(k for k in listed if is_key(k) and k != matched_wrong_key)


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


def last_release_on_node(loop_state: dict, node_id: str) -> bool | None:
    """Spec §13 A76: whether the concept's LATEST attempt in this session had
    its reference released (True / False), or None when the session has no
    attempt on the concept. Only the next graded item on a concept after a
    release is a re-check — the copy risk — so an older release no longer
    counts once another item on the concept was graded. None: the check route
    reads the evidence journal (a release in another session, R2-2)."""
    log = loop_state.get(_ATTEMPTS) if isinstance(loop_state, dict) else None
    tail = attempts_for_node(log if isinstance(log, list) else [], node_id)
    return tail[-1].released if tail else None


def owed_isomorph(rows: list[dict], shape: tuple) -> bool:
    """Spec §13 A76 (fix rounds 4–5): whether an item of isomorph class `shape`
    (format, difficulty on this node, A27/next_isomorph) is a re-check given the
    node's journal rows in the window (loop_state_store.recent_evidence). A
    release makes EVERY item of the released item's class a re-check for the
    window — no item "pays" the debt (R5-2: every class-mate carries the copy
    risk; the cost is slower credit on that class alone for
    RECHECK_RELEASE_WINDOW_HOURS). Fail closed (R5-3): a released row whose
    item cannot be read (withdrawn, deleted) owes on EVERY class of the node,
    and so does any release when the graded item's own class is unknown. Pure."""
    released = [row for row in rows if row.get("released")]
    if not released:
        return False
    if None in shape or any(row.get("shape") is None for row in released):
        return True
    return shape in {row["shape"] for row in released}


def recheck_after_release(
    user_id: str, node_id: str, loop_state: dict | None, *, now: datetime, item
) -> bool:
    """Spec §13 A76 — the ONE re-check decision every grading caller passes to
    grade_answer as `same_session_recheck` (the check route, the probe and the
    review). `item` is the item being graded (question_hash, format,
    difficulty). A re-check when EITHER
      • it is the next graded item on the concept after a release: the
        concept's latest attempt in THIS session's log when there is one, else
        the node's newest journal row within RECHECK_RELEASE_WINDOW_HOURS of
        `now` (a session hop never bypasses it; R2-2/R2-3); or
      • an item of its isomorph class (same format and difficulty on the
        node) was released within the window — every class-mate, whatever was
        graded since (R4-1/R5-2), and every class when the released item cannot
        be read (R5-3; owed_isomorph).
    A failed journal read decides nothing (False). Reads only: `loop_state` is
    never changed.

    Spec §13 A138: an ANSWERED segment prequestion is a release too — its
    item's worked answer was shown before any teaching — so it joins both
    rules (`_prequestion_owes`): the next graded item on the concept after it
    is a re-check, and so is every class-mate of its item for the window. It
    writes no evidence, so it is read from this session's loop state and,
    across sessions, from `learning_prequestions`."""
    last = last_release_on_node(loop_state or {}, node_id)
    if last:
        return True
    since = now - timedelta(hours=RECHECK_RELEASE_WINDOW_HOURS)
    # spec §13 A141: a multi-concept item's class names its combination
    shape = isomorph_class(
        getattr(item, "format", None), getattr(item, "difficulty", None), getattr(item, "concept_key", None)
    )
    if _prequestion_owes(user_id, node_id, loop_state, since=since, shape=shape):
        return True
    rows = recent_evidence(user_id, node_id, since=since.isoformat())
    if not rows:
        return False
    if last is None and rows[-1]["released"]:
        return True
    return owed_isomorph(rows, shape)


def _prequestion_owes(
    user_id: str, node_id: str, loop_state: dict | None, *, since: datetime, shape: tuple
) -> bool:
    """Spec §13 A138 × A76: whether an answered prequestion on the concept
    makes this grade a re-check.
      • Every answered prequestion in the window (this session's, and
        `learning_prequestions` across sessions) owes its item's isomorph class,
        as owed_isomorph does for a journal release; an unknown class of the
        graded item owes on any release (R5-3).
      • The NEXT graded item on the concept after the newest such release is a
        re-check, whatever class it is: nothing on the concept was graded after
        the release — no step of this session (`graded_at`) and no evidence row
        in the journal, any surface. Decided by time, never by the session's
        attempt log: an answer before the release (the probe's, A120, which
        logs an unreleased attempt) must not hide it.
    A failed journal read leaves this session's own record to decide (the
    session's release with no later step owes, as `last` does for an attempt);
    a release from another session then decides nothing (A76's rule for its
    own journal)."""
    from learning.prequestion import released_on_node
    from learning.prequestion_store import evidence_since, releases

    cutoff = since.timestamp()
    session = [r for r in released_on_node(loop_state, node_id) if r["at"] >= cutoff]
    durable = releases(user_id, node_id, since=since) or []
    shapes = {r["shape"] for r in session} | {r["shape"] for r in durable}
    if not shapes:
        return False
    if None in shape or shape in shapes:
        return True
    newest = max([r["at"] for r in session] + [r["at"].timestamp() for r in durable])
    if _graded_on_node_after(loop_state, node_id, newest):
        return False
    later = evidence_since(user_id, node_id, datetime.fromtimestamp(newest, tz=timezone.utc))
    if later is None:
        return bool(session) and not _graded_on_node_after(loop_state, node_id, max(r["at"] for r in session))
    return later is False


def _graded_on_node_after(loop_state: dict | None, node_id: str, at: float) -> bool:
    """Whether a step of this session on `node_id` was graded after `at` (epoch
    seconds). Pure."""
    steps = loop_state.get("steps") if isinstance(loop_state, dict) else None
    for entry in steps.values() if isinstance(steps, dict) else ():
        if not isinstance(entry, dict):
            continue
        graded = entry.get("graded_at")
        if (
            entry.get("node_id") == node_id
            and isinstance(graded, (int, float))
            and not isinstance(graded, bool)
            and graded > at
        ):
            return True
    return False


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


def record(
    user_id: str,
    node_id: str,
    check_item_id: str | None,
    wrong_key: str,
    evidence_text: str | None,
    *,
    question_hash: str | None = None,
) -> dict:
    """Insert-or-increment on (user_id, node_id, wrong_key) among OPEN rows —
    ONE atomic statement, the `misconception_record` SQL function (INSERT …
    ON CONFLICT on the open-row partial unique index; PKG-10 fix round F5: a
    read-then-write from here lost increments and opened duplicate rows under
    concurrency). `evidence_text` (the student's answer) is encrypted here, at
    the write boundary, and never read back. A key that is not
    identifier-shaped is refused with nothing written. Spec §13 A123: the
    attempt's `question_hash` (its check item) is recorded as the row's
    supporting attempt, so a misconception every attempt of which was graded
    against a retired item is closed when that evidence is voided — and an
    attempt on an item staff already retired records nothing (the function
    checks under the item's lock). Returns {id, count}; {} on a refusal, an
    attempt on a retired item, or a DB error. Never raises."""
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
                "p_question_hash": question_hash,
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


_RESOLVED_COLS = "id,node_id,wrong_key,check_item_id,count"
#: misconceptions.resolved_reason of a misconception resolve() closes (spec §13
#: A127): the student answered an ISOMORPH (the same concept, another question
#: than the one it was recorded on) correctly and unassisted. A123's void
#: closure writes learning.evidence_void.MISCONCEPTION_VOID_REASON instead. The
#: column's CHECK admits exactly these two
#: (20261108110805_learning_misconception_resolved_reason.sql).
RESOLVED_BY_ISOMORPH = "correct_unassisted_isomorph"


def _in_list(values: Iterable[str]) -> str:
    return f"in.({','.join(pg_quote_value(v) for v in values)})"


def resolve(user_id: str, node_id: str, wrong_keys: Iterable[str], *, by_item: str) -> list[dict]:
    """Spec §13 A127: close the student's OPEN misconceptions on `node_id` among
    `wrong_keys` that were recorded on an item other than `by_item` — the item
    whose correct, unassisted answer closes them must be an isomorph (same
    concept, another question), never the question the misconception was
    recorded on. ONE conditional UPDATE … RETURNING (`resolved_at IS NULL` in
    the filter), so a row another request closed first is never closed — or
    reported — twice. The row records why it closed: `resolved_reason` is
    RESOLVED_BY_ISOMORPH. A later record of the same key opens a fresh row (the
    open-row unique index, A75 (f)): a relapse is a new misconception.
    Returns the closed rows [{id, node_id, wrong_key, check_item_id, count}],
    identifier-shaped keys only; [] when nothing is asked (no key, no item) or
    on a DB error. Never raises, never reads evidence_text."""
    keys = sorted({k for k in wrong_keys or [] if is_key(k)})
    if not keys or not by_item or not node_id:
        return []
    try:
        rows = (
            table("misconceptions").update(
                {"resolved_at": _now(), "resolved_reason": RESOLVED_BY_ISOMORPH},
                filters={
                    "user_id": f"eq.{user_id}",
                    "node_id": f"eq.{node_id}",
                    "wrong_key": _in_list(keys),
                    "resolved_at": "is.null",
                    # an isomorph: recorded on another question (or on none)
                    "or": f"(check_item_id.is.null,check_item_id.neq.{pg_quote_value(by_item)})",
                    "select": _RESOLVED_COLS,  # never the encrypted evidence_text
                },
            )
            or []
        )
    except Exception as exc:  # fail closed: a diagnosis, never a gate
        logger.warning(
            "misconceptions.resolve failed for %s/%s: %s", user_id, node_id, type(exc).__name__
        )
        return []
    return [dict(r) for r in rows if isinstance(r, dict) and is_key(r.get("wrong_key"))]


def resolve_after_grade(
    user_id: str,
    node_id: str,
    *,
    keys: Iterable[str],
    item_id: str | None,
    attempt: Mapping,
    surface: str,
    session_id: str | None = None,
    request_id: str | None = None,
) -> list[str]:
    """Spec §13 A127: the resolution rule, applied by a grading route AFTER its
    one flush and the claimed save that recorded the grade (A75 (a)'s order: a
    failed flush closes nothing). `attempt` is the grade's final evidence (or
    the writer's committed observation of it), `keys` what the answered item
    can close (`resolvable_keys`), `item_id` the answered item. When the
    attempt `resolves`, the open rows recorded on another item are closed
    (`resolve`) and one `learn.misconception_resolved` event (ids, the key,
    counts, the surface) is logged per closed row. Returns the closed keys. A
    store failure closes nothing and never raises; an unknown `surface` is a
    caller bug (ValueError), raised before any read."""
    if surface not in RESOLVE_SURFACES:
        raise ValueError(f"unknown resolution surface {surface!r}")
    if not resolves(attempt) or not item_id:
        return []
    closed = resolve(user_id, node_id, keys, by_item=item_id)
    for row in closed:
        log_event(
            RESOLVED_EVENT,
            category="usage",
            user_id=user_id,
            request_id=request_id,
            payload={
                "node_id": node_id,
                "wrong_key": row["wrong_key"],
                "check_item_id": item_id,
                "recorded_on": row.get("check_item_id"),
                "count": int(row.get("count") or 0),
                "surface": surface,
                **({"session_id": session_id} if session_id else {}),
            },
        )
    return [row["wrong_key"] for row in closed]


def open_keys(user_id: str, keys: Iterable[str]) -> set[str]:
    """Spec §13 A127: which of `keys` the student still holds — an OPEN row on
    any node, seen within MISCONCEPTION_RECENT_DAYS (open_for's window). The
    learner brief lists a recent close's key only when it is still open, so a
    misconception resolved since that close drops out. One read; no read for an
    empty list; set() on a DB error (never raises: the brief then lists none of
    them rather than a closed one)."""
    wanted = sorted({k for k in keys or [] if is_key(k)})
    if not wanted:
        return set()
    since = (_utcnow() - timedelta(days=MISCONCEPTION_RECENT_DAYS)).isoformat()
    try:
        rows = (
            table("misconceptions").select(
                "wrong_key",
                filters={
                    "user_id": f"eq.{user_id}",
                    "wrong_key": _in_list(wanted),
                    "resolved_at": "is.null",
                    "last_seen_at": f"gte.{since}",
                },
            )
            or []
        )
    except Exception as exc:
        logger.warning("misconceptions.open_keys failed for %s: %s", user_id, type(exc).__name__)
        return set()
    return {r["wrong_key"] for r in rows if isinstance(r, dict) and r.get("wrong_key") in wanted}


def open_for(user_id: str, node_ids: list[str]) -> list[dict]:
    """Open misconceptions for the student on the given nodes, seen within
    MISCONCEPTION_RECENT_DAYS (F6: one the student never meets again stops
    re-listing; a resolved one — spec §13 A127 — never lists):
    [{node_id, wrong_key, count}], count descending; only identifier-shaped
    keys. No read for an empty id list. Never reads evidence_text; [] on a DB
    error (never raises)."""
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
