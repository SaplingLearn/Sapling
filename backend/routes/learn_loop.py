"""/api/learn/loop/* — the learning-loop tutor routes (PKG-07; spec §7, §9; A15–A20, A27).

Mounted at /api/learn/loop. Every endpoint is require_self + gate-404; every
model-calling endpoint also carries the A20 rate-limit dependency. The legacy
learn routes delegate here (routes/learn.py) when the gate is true; they are
byte-identical when it is false.

Routing is code: learning.policy.model_tier picks the tier slot after
services.ai_budget.check has read the student's budget — in the same function
as every model run (invariant 23); each tutor model run is counted with
ai_budget.count_tutor_call right before it (A39). Context comes from
learning.policy.context_policy, assembled with the legacy block builders.
The tutor's output is the STRUCTURED turn (`learning.turn_shape.LoopTurnOut`),
served as `render_turn(...)`; streaming rides
services.chat_stream.stream_structured_turn with a leak-strip transform, and
the loop stream events are yielded AROUND it. A tool run that ends without a
turn (#646: flash-lite answers empty after a tool call) is finished by the
tool-less continuation. Evidence is written ONLY by _grade_submission, from an
explicit answer submission (invariant 26). The reference answer of the active
check item lives only on the turn object — never in deps, the prefix, a log
line, or an event payload.

The gate (`learning.gate.learning_loop_for_request`) is read ONCE per request,
at route entry (A38 00); a delegating legacy route carries its own read in on
`request.state.learning_loop`, and the result rides on
`SaplingDeps.learning_loop`.

Loop state: PKG-06's `learning.loop_state_store` returns the typed `LoopState`;
this module reads its JSON document (`LoopState.to_json()`) and writes ONLY
through `update_loop_state` (compare-and-set, A38 06(q)) with a mutate closure
over that document, re-validated by `LoopState.from_json`. A closure expresses
this request's own change and has no side effects (it is re-applied on a
conflict); events and message rows follow the save. The
spec's `loop_state["active"]` is the document's `current`, and the spec's
per-item `loop_state[qh]` entry is `steps[qh]`: PKG-06 owns its `rung`,
`attempts` (failed genuine attempts while the step is open), `first_shown_at`,
`last_rung_at`, `attempted_at` (Unix seconds), `showed_work` and `exam_mode`;
every other per-item key is this package's (HANDOFF-07 Deviations). The
session is checked to be the requesting student's before any read or write.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from collections import Counter
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic_ai import capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import RunUsage
from sse_starlette.sse import EventSourceResponse

import config
from agents import CONTINUATION_LIMITS, LOOP_LIMITS
from agents.deps import SaplingDeps
from agents._run import run_agent_sync
from agents.session_close import run_session_close, shape_close
from agents.loop_tutor import (
    ITEM_WITHHELD,
    LOOP_TIER_SLOTS,
    assemble_turn_message,
    item_visible,
    loop_tutor_agent,
    new_nonce,
    phase_prefix,
    routable_tier,
    student_envelope,
    tier_run_kwargs,
)
from agents.tools.check import CHANNEL_FOR_FORMAT, CheckAnswer, grade_answer
from agents.usage import UnfinishedRun, record_agent_usage
from db.connection import table
from learning import answer_guard, gates, ladder, planner, policy, review, zpd_events
from learning import probe as probe_policy
from learning.bkt import band as bkt_band
from learning.checks import CheckItem, is_servable, posttest_reserve_hash, select_item
from learning.evidence import PREREQ_RELATIONSHIP_TYPE, flush_pending
from learning.fsrs import budget_select, order_due
from learning.gate import learning_loop_for_request
from learning.ladder import Rung
from learning.leak import detect_leak, leak_spans
from learning.learner_brief import course_concept_names, store_brief
from learning.learner_state import LearnerState, read_states
from learning.loop_state_store import (
    LoopStateConflict,
    load_loop_state,
    revealed_hashes,
    seen_hashes,
    update_loop_state,
)
from learning.params import (
    BAND_DEVELOP_MAX,
    BKT_L0,
    BKT_PROFICIENT,
    CHECK_ITEM_FORMATS,
    CHECK_REFUSALS_AS_IDK,
    CLOSE_PHASES,
    CLOSE_RUN_TIMEOUT_S,
    EDGE_PREREQ_SOURCE_IS_PREREQ,
    LOOP_CHECK_DIFFICULTY_BY_BAND,
    LOOP_CHECKS_PER_CONCEPT,
    LOOP_GRADING_CLAIM_STALE_S,
    LEARNER_BRIEF_CANDIDATE_NODES,
    LEARNER_BRIEF_RETRY_AFTER_S,
    LEARNER_BRIEF_TOP_STATES,
    LOOP_HISTORY_TRIM_BLOCK,
    LOOP_SESSION_MAX_DEEP_REQUESTS,
    LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE,
    LOOP_SOURCE_CHUNKS_MAX,
    LOOP_TEACH_TURNS_BEFORE_CHECK,
    PLAN_ORDER,
    PROBE_MAX_SKILLS,
    PROBE_PLAN_READS_PER_MIN,
    REVIEW_DAILY_BUDGET_MIN,
    REVIEW_SECONDS_PER_CHECK,
)
from learning.policy import LearnerView, LoopState, StepState
from learning.session_close import (
    CLOSE_FALLBACK_DETAILS,
    CloseRecord,
    build_close,
    fallback_close,
    store_close,
)
from learning.turn_shape import (
    FIELD_JOIN,
    clamp_model_ceiling,
    render_partial,
    render_turn,
    turn_limits,
)
from models import (
    ActionBody,
    ChatBody,
    CloseBody,
    EndSessionBody,
    LoopAttemptBody,
    LoopCheckAnswerBody,
    LoopCheckNextBody,
    LoopHintBody,
    PlanApproveBody,
    ProbeAnswerBody,
    ProbeNextBody,
    ReviewAnswerBody,
    StartSessionBody,
)
from routes.learn import (  # legacy helpers, reused verbatim — never copied
    PENDING_SESSIONS,
    _CONTINUATION_NUDGE,
    _CONTINUATION_RUN_KEYS,
    _agent_turn_or_http_error,
    _consume_pending,
    _get_catalog_chunk,
    _get_course_id_for_topic,
    _get_course_info,
    _load_message_history,
    save_message,
)
from services import ai_budget, events_service
from services.academics import (
    offering_course_id,
    resolve_offering,
    user_offering_ids_for_course,
)
from services.agent_events import SSE_CACHE_CONTROL, SaplingEvent, sapling_event_to_sse
from services.ai_budget import AIBudgetExceeded, enforce_rate_limit
from services.auth_guard import get_session_user_id, require_self
from services.encryption import decrypt_if_present, decrypt_json_column
from services.chat_stream import stream_structured_turn
from services.check_item_service import (
    course_has_items,
    get_check_item,
    items_for_concepts,
    list_items,
)
from services.graph_context import build_graph_context_block
from services.graph_service import _normalize_concept, _prerequisite_edges, get_graph
from services.prompt_safety import wrap_untrusted
from services.rag_service import chunks_for_ids, format_rag_context, retrieve_chunks
from services.request_context import current_request_id
from services.session_modes import NOT_REVIEW
from services.request_limits import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter()

_NOT_ENABLED = "learning loop not enabled"
_BUDGET_DETAIL = "ai budget reached"  # spec §3.5 hard-level body (A20)
_RATE_LIMITED = [Depends(enforce_rate_limit)]
#: The legacy catalog header (routes/learn.py::_prepare_chat_run), verbatim.
_CATALOG_HEADER = "COURSE CATALOG INFO (official BU course data):\n\n"
_SOURCE_HEADER = "CHECK ITEM SOURCE PASSAGES (the course text this item was written from):\n"
_SOURCE_LABEL = "student-document chunks"

_FEEDBACK_VERDICT_LINES = {
    "correct": "Correct.",
    "not_yet": "Not yet.",
    "idk": "No problem — here is the answer.",
}
_FEEDBACK_ANSWER_LEAD = "The answer: "
_FEEDBACK_NEXT_STEP = "When you're ready, try the next check."

_GRADE_UNAVAILABLE_REPLY = (
    "I couldn't check that answer just now, so nothing was recorded. "
    "Please submit it again in a moment."
)
#: A33: the guard refused the answer (it addressed the grader). Not an outage,
#: never a skip: the student is asked again; the CHECK_REFUSALS_AS_IDK-th
#: refusal of the same item is recorded as idk instead.
_ANSWER_REFUSED_REPLY = (
    "I can only check an answer written in your own words, so nothing was recorded. "
    "Please answer the question itself and submit again."
)
_IDK_RENDERED = "I don't know"
_SUBMISSION_KINDS = ("feedback", "hint_request", "unavailable", "refused")
#: A38 06(q): the 409 detail when the loop-state compare-and-set is exhausted.
_STATE_CONFLICT = "loop state changed, retry"
#: C2 (review round 3): the 409 detail for a submission on an item that is
#: graded, or being graded under another request's claim.
_ALREADY_GRADED = "already graded"
_DETERMINISTIC_RUNGS = (Rung.H2, Rung.H4, Rung.H6)
#: The session opener served at the hard budget level (A27): no model call, so
#: a capped student can still start a session and reach the probe (§3.5).
_LOOP_OPENER_TEMPLATE = "Let's start with a few quick questions to see where you are."

#: The three "[ACTION: ...]" texts, copied verbatim from routes/learn.py::_action_turn
#: (:1406–1411), where they are a local dict.
_ACTION_PROMPTS = {
    "hint": "The student asked for a hint. Give a small scaffold or clue without giving away the answer.",
    "confused": "The student said they are confused. Identify the likely point of confusion and re-explain with a different analogy.",
    "skip": "The student wants to skip this concept. Acknowledge and transition to the next recommended concept.",
}


def _gate(user_id: str, request: Request) -> bool:
    """require_self, then the learning-loop gate, read ONCE per request (A38 00):
    a delegating legacy route has already read it and carries the result on
    `request.state.learning_loop` (routes/learn.py), so a delegated request
    costs one `user_settings` read, not two. Returns the gate for
    `SaplingDeps.learning_loop`; False is the spec §7 404."""
    require_self(user_id, request)
    carried = getattr(request.state, "learning_loop", None)
    loop_on = carried if isinstance(carried, bool) else learning_loop_for_request(user_id)
    if not loop_on:
        raise HTTPException(status_code=404, detail=_NOT_ENABLED)
    return loop_on


def _now_s() -> float:
    return datetime.now(timezone.utc).timestamp()


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or current_request_id() or str(uuid.uuid4())


def _session_scope(session_id: str, user_id: str) -> tuple[str, str]:
    """(offering_id, abstract course_id) of a materialised session the requesting
    student owns. The loop-state store keys on the session id alone, so this
    ownership check is the route's (HANDOFF-06 Known gaps): 404 when no row
    exists, 403 when it is another student's. One `sessions` read. A daily
    review session (mode 'review', PKG-12) is never a loop session: its
    phase-less document would read as probing (`_loop_phase`), so it is a 404
    here and every probe/plan/teach/check route refuses it (A73)."""
    rows = table("sessions").select(
        "user_id,offering_id", filters={"id": f"eq.{session_id}", **NOT_REVIEW}, limit=1
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Session not found")
    if rows[0].get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Session user mismatch")
    offering_id = rows[0].get("offering_id") or ""
    return offering_id, (offering_course_id(offering_id) if offering_id else "")


class _BudgetPaused(HTTPException):
    """Hard budget level with nothing deterministic to serve. An HTTPException
    so routes.learn._agent_turn_or_http_error (which maps any other Exception
    to 502) passes it through; the route re-raises it as PKG-06b's
    AIBudgetExceeded, whose registered handler renders the spec §3.5 429."""

    def __init__(self, decision) -> None:
        super().__init__(status_code=429, detail=_BUDGET_DETAIL)
        self.decision = decision


def _budget_data(decision) -> dict:
    """The pause notice (JSON `budget`, SSE `budget` data): level and reset, plus
    the binding scope and `session_capped` for PKG-13's banner (A39, 06b(j)) —
    the same keys the 429 body carries."""
    reset = decision.reset_at
    return {
        "level": decision.level,
        "reset_at": reset.isoformat() if reset else None,
        "scope": decision.scope,
        "session_capped": bool(decision.session_capped),
    }


def _budget_event(decision) -> SaplingEvent:
    return SaplingEvent(
        type="budget", step="loop", message="Tutor chat paused.", data=_budget_data(decision)
    )


def _item_like(item):
    """PKG-05's grade_answer takes a learning.checks.CheckItem and PKG-06's
    deterministic_content an ItemLike (attribute access); the check-item
    service hands back decrypted CheckItem models. A dict is validated into
    CheckItem."""
    return CheckItem.model_validate(item) if isinstance(item, dict) else item


# ── Loop state: PKG-06's JSON document ─────────────────────────────────────


class _StateConflict(HTTPException):
    """update_loop_state lost the compare-and-set on every retry (A38 06(q)): a
    409 on a JSON route; inside a stream it is a terminal `error` event (the
    on_complete guard, or the deterministic path's). An HTTPException so
    routes.learn._agent_turn_or_http_error passes it through."""

    def __init__(self) -> None:
        super().__init__(status_code=409, detail=_STATE_CONFLICT)


def _load_loop_state(session_id: str) -> dict:
    """The session's loop state as PKG-06's JSON document (`LoopState.to_json()`).
    For reading only: every write is `_update_loop_state`."""
    return load_loop_state(session_id).state.to_json()


def _update_loop_state(session_id: str, mutate: Callable[[dict], None]) -> dict:
    """The ONE loop-state write (A38 06(q)): `update_loop_state` with `mutate`
    applied to the FRESH document (on a conflict it runs again on the newer
    one), re-validated by PKG-06's typed parser — a malformed PKG-06 field
    raises ValueError here instead of reaching the database. `mutate` changes
    the document in place and must have no side effects. Returns the document
    as mutated (saved, or — no sessions row, A11 — logged and not saved)."""
    last: dict = {}

    def apply(state: LoopState) -> LoopState:
        doc = state.to_json()
        mutate(doc)
        last["doc"] = doc
        return LoopState.from_json(doc)

    try:
        saved = update_loop_state(session_id, apply)
    except LoopStateConflict as exc:
        logger.warning("loop state for %s: compare-and-set exhausted", session_id)
        raise _StateConflict() from exc
    if saved is None:
        logger.warning("loop state for %s not saved: no sessions row", session_id)
        return last.get("doc", {})
    return saved.state.to_json()


def _steps(state: dict) -> dict:
    return state.setdefault("steps", {})


def _step_state(state: dict, question_hash: str | None) -> StepState:
    """PKG-06's typed view of one per-item entry (a fresh step when absent)."""
    entry = (state.get("steps") or {}).get(question_hash) if question_hash else None
    if not isinstance(entry, dict):
        return StepState(question_hash=question_hash or "")
    return LoopState.from_json({"steps": {question_hash: entry}}).steps[question_hash]


def _phase_for(state: dict) -> str:
    active = state.get("current")
    entry = (state.get("steps") or {}).get(active) if active else None
    if not isinstance(entry, dict):
        return "teach"
    if entry.get("graded_at") is not None:
        return "teach" if entry.get("feedback_given") else "feedback"
    return "check"


def _loop_phase(doc: dict) -> str:
    """The session's loop phase (PKG-08's top-level `phase`: probe → plan →
    teach). A document without the key is probing, unless its plan is already
    approved (a document /plan/approve wrote before the key existed)."""
    phase = doc.get("phase")
    if isinstance(phase, str) and phase:
        return phase
    plan = doc.get("plan") if isinstance(doc.get("plan"), dict) else {}
    return "teach" if plan.get("approved") else "probe"


_SESSION_CLOSED = "this session is closed"
#: PKG-08 reopen: the teaching routes' 409 while the probe or the plan is open.
#: A posed probe item lives under `probe.current`, not PKG-07's `current`, so a
#: teach turn then would run with no guarded item (it could hand out the answer).
_TEACHING_CLOSED = {
    "probe": "finish the probe first",
    "plan": "finish the plan first",
    # PKG-09 (spec §9): close is the last phase — no turn after the stored close.
    "close": _SESSION_CLOSED,
}


def _require_open(state: dict) -> None:
    """PKG-09: the answer routes (/check/answer, /step/attempt) of a closed or
    closing session — its close is stored (or being written); evidence after it
    would sit outside it."""
    _refuse_while_closing(state, _now_s())


def _require_teaching(state: dict) -> None:
    detail = _TEACHING_CLOSED.get(_loop_phase(state))
    if detail:
        raise HTTPException(status_code=409, detail=detail)
    _refuse_while_closing(state, _now_s())  # PKG-09: nor while a close is being written


def _teaching_open(session_id: str, user_id: str) -> None:
    """Ownership, then the phase: a teaching route runs only once the plan is
    approved (spec §9: probe → plan → teach). Reads only; writes nothing."""
    _session_scope(session_id, user_id)
    _require_teaching(_load_loop_state(session_id))


def _turn_phase(kind: str, state_phase: str) -> str:
    """The phase a turn of `kind` runs in, given the document's phase."""
    if kind == "feedback":
        return "feedback"
    if kind == "hint_request" or (kind == "action" and state_phase == "check"):
        return "hint"
    if kind in ("unavailable", "refused"):
        return "check"
    if kind == "opener":
        return "teach"
    return state_phase


@dataclass(repr=False)
class _BriefRequest(ModelRequest):
    """The learner brief as the loop history's synthetic first message (spec §13
    A19). A type, not a text marker: a student row can never pose as the brief.
    It is server-assembled with its own untrusted envelope (tags neutralised at
    build), so `_guard_history` never re-wraps it as the student's words — whose
    per-call nonce would change the stable prefix every turn."""


def _brief_message(brief: str) -> _BriefRequest:
    return _BriefRequest(parts=[UserPromptPart(content=brief)])


def _history_window(n: int) -> int:
    """How many of the last `n` history messages a loop turn keeps (spec §13 A19):
    all of them below LOOP_HISTORY_TRIM_BLOCK, else the block plus the remainder
    (10–19), so the window start moves only in whole blocks and consecutive
    turns share their prefix."""
    if n < LOOP_HISTORY_TRIM_BLOCK:
        return n
    return LOOP_HISTORY_TRIM_BLOCK + n % LOOP_HISTORY_TRIM_BLOCK


def _brief_node_ids(loop_state: dict, user_id: str, course_id: str | None) -> list[str]:
    """The concepts a brief built on a loop turn covers: the approved plan
    (PKG-08, A27) when there is one, else the course's weakest nodes. Runs only
    when a brief is being built — once per session."""
    plan = loop_state.get("plan") if isinstance(loop_state.get("plan"), dict) else {}
    approved = [n for n in plan.get("approved") or [] if isinstance(n, str) and n]
    if approved:
        return approved
    if not course_id:
        return []
    # Review round 2: only nodes that map to a course concept (a student-created
    # node at mastery 0 would otherwise rank first and carry its own name in)
    rows = table("graph_nodes").select(
        "id,concept_name",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        order="mastery_score.asc",
        limit=LEARNER_BRIEF_CANDIDATE_NODES,
    )
    names = {r["id"]: r.get("concept_name") or "" for r in rows or [] if r.get("id")}
    course = course_concept_names(course_id, names)
    return [n for n in names if n in course][:LEARNER_BRIEF_TOP_STATES]


#: Review M1: session id → when its brief build last failed (per process; a
#: failure is retried after LEARNER_BRIEF_RETRY_AFTER_S, not on every turn).
_BRIEF_FAILED: dict[str, float] = {}


def _load_loop_history(
    session_id: str,
    *,
    user_id: str | None = None,
    course_id: str | None = None,
    loop_state: dict | None = None,
) -> list:
    """The loop history (spec §13 A19): the session's learner brief as a
    synthetic first message, then a block-trimmed window of the legacy history
    (`_history_window`; ≤ LOOP_HISTORY_MAX_MESSAGES in all). The brief is read
    from `sessions.loop_brief` — never rebuilt once stored; when it is not
    built yet and `user_id` is given (a loop turn), it is built and stored here
    (a failure logs and the turn runs without it; the next turn retries). No
    row yet (a lazy session), or `user_id=None`, reads only. Leading assistant
    messages are kept: dropping them would move the window every turn."""
    rows = table("sessions").select(
        "id,loop_brief", filters={"id": f"eq.{session_id}", **NOT_REVIEW}, limit=1
    )
    brief = ""
    if rows:
        stored = rows[0].get("loop_brief")
        if stored is not None:
            brief = decrypt_if_present(stored) or ""
        elif user_id and _now_s() - _BRIEF_FAILED.get(session_id, float("-inf")) > (
            LEARNER_BRIEF_RETRY_AFTER_S
        ):
            try:
                brief = store_brief(
                    session_id,
                    user_id,
                    course_id or None,
                    _brief_node_ids(loop_state or {}, user_id, course_id),
                )
                _BRIEF_FAILED.pop(session_id, None)
            except Exception as exc:
                now = _now_s()
                for stale in [
                    k for k, at in _BRIEF_FAILED.items() if now - at > LEARNER_BRIEF_RETRY_AFTER_S
                ]:
                    _BRIEF_FAILED.pop(stale, None)  # bounded: only live windows are kept
                _BRIEF_FAILED[session_id] = now
                logger.warning(
                    "learner brief not built for this turn (%s); retried after %ss",
                    type(exc).__name__,
                    LEARNER_BRIEF_RETRY_AFTER_S,
                )
                brief = ""
    msgs = _load_message_history(session_id)
    window = msgs[len(msgs) - _history_window(len(msgs)) :]
    return ([_brief_message(brief)] if brief else []) + window


# ── Learner state, band, ceiling ───────────────────────────────────────────


def _node_for_item(user_id: str, item) -> str | None:
    """The student's graph node for a course-asset item (A2): the user's
    `graph_nodes` row in the item's course whose normalised concept name is the
    item's `concept_key`. None when the student has never met the concept."""
    rows = (
        table("graph_nodes").select(
            "id,concept_name",
            filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{item.course_id}"},
        )
        or []
    )
    for row in rows:
        if _normalize_concept(row.get("concept_name") or "") == item.concept_key:
            return row.get("id")
    return None


def _learner_state(user_id: str, node_id: str | None) -> LearnerState | None:
    if not node_id:
        return None
    return read_states(user_id, [node_id]).get(node_id)


def _band_of(state: LearnerState | None) -> tuple[str, float]:
    p = state.p_known if state is not None else BKT_L0
    return bkt_band(p), p


def _band_for(user_id: str, node_id: str | None) -> tuple[str, float]:
    """(band, p_known) of a node — BKT_L0 when there is no node or no row."""
    return _band_of(_learner_state(user_id, node_id))


def _prereq_proficient(user_id: str, node_id: str) -> bool:
    """Every prerequisite parent of the node has a decayed p_known ≥
    BAND_DEVELOP_MAX; True when it has none. Parents come from the read helper
    PKG-03's propagation uses (graph_service._prerequisite_edges), with the same
    EDGE_PREREQ_SOURCE_IS_PREREQ direction."""
    parents = []
    for src, tgt in _prerequisite_edges(user_id, node_id):
        prereq, dependent = (src, tgt) if EDGE_PREREQ_SOURCE_IS_PREREQ else (tgt, src)
        if dependent == node_id and prereq != node_id:
            parents.append(prereq)
    if not parents:
        return True
    states = read_states(user_id, parents)
    return all((states[p].p_known if p in states else BKT_L0) >= BAND_DEVELOP_MAX for p in parents)


def _learner_view(state: LearnerState | None, *, band: str, prereq_proficient: bool) -> LearnerView:
    """PKG-06's typed learner input; LearnerState's own defaults stand in for a
    node with no row (the BKT prior, no opportunities)."""
    st = state or LearnerState(user_id="", node_id="")
    return LearnerView(
        p_known=st.p_known,
        band=band,
        prereq_proficient=prereq_proficient,
        unassisted_next=st.unassisted_next,
        opps=st.opps,
        streak_unassisted=st.streak_unassisted,
    )


def _genuine(text: str, independent_s: float, band: str) -> bool:
    """Spec §3.3 genuine attempt, for hint unlocking and the shown-work floor
    only (never a grading gate, A16). `matched_non_attempt` is
    `has_non_attempt_phrase` — never `matches_non_attempt` (HANDOFF-06)."""
    return gates.is_genuine_attempt(
        len((text or "").strip()),
        False,
        gates.has_non_attempt_phrase(text or ""),
        independent_s,
        band,
        time_scale=config.LEARNING_GATE_TIME_SCALE,
    )


def _ceiling_for(
    *, step: StepState, learner: LearnerView, message: str, independent_s: float
) -> tuple[Rung, policy.CeilingReason]:
    """policy.ceiling_with_reason on typed state only (invariant 4). The shown-work
    floor applies when the step already records shown work or this message is a
    genuine attempt; exam mode is the step's own flag (False until PKG-08)."""
    showed = step.showed_work or _genuine(message, independent_s, learner.band)
    return policy.ceiling_with_reason(learner, dataclasses.replace(step, showed_work=showed))


def _failed_on_concept(state: dict, node_id: str | None) -> int:
    """Failed genuine attempts this session on the concept's items (PKG-06's
    per-step `attempts`), summed across its isomorphs."""
    if not node_id:
        return 0
    return sum(
        int(entry.get("attempts") or 0)
        for entry in (state.get("steps") or {}).values()
        if isinstance(entry, dict) and entry.get("node_id") == node_id
    )


def _seconds_since(t: float | None, now: float) -> float:
    return max(0.0, now - t) if t else 0.0


# ── Context and run assembly ───────────────────────────────────────────────


def _context_blocks(*, user_id: str, course_id: str, user_message: str, context, item) -> list[str]:
    """Only the blocks `context` (policy.context_policy) asks for, in the legacy
    order, with the legacy builders (routes/learn.py::_prepare_chat_run)."""
    blocks: list[str] = []
    bu_code = _get_course_info(course_id).get("course_code") if course_id else None
    if context.catalog and bu_code:
        catalog = _get_catalog_chunk(bu_code)
        if catalog:
            blocks.append(_CATALOG_HEADER + catalog)
    if context.rag_k and bu_code:
        rag = format_rag_context(
            retrieve_chunks(user_message, course_id=bu_code, k=context.rag_k, user_id=user_id)
        )
        if rag:
            blocks.append(rag)
    if context.source_chunks and item is not None:
        ids = list(item.source_chunk_ids or [])[: context.source_chunks]
        rows = chunks_for_ids(ids, user_id=user_id) if ids else []
        text = "\n\n".join(r["chunk_text"] for r in rows if r.get("chunk_text"))
        wrapped = wrap_untrusted(text, source=_SOURCE_LABEL)
        if wrapped:
            blocks.append(_SOURCE_HEADER + wrapped)
    if context.graph_block and course_id:
        graph = build_graph_context_block(user_id, course_id, user_message)
        if graph:
            blocks.append(graph)
    return blocks


def _prepare_loop_run(
    *,
    user_id: str,
    session_id: str,
    course_id: str,
    user_message: str,
    message_history: list,
    request_id: str,
    prefix: str,
    state: dict,
    tier: str,
    context,
    item,
    learning_loop: bool,
    loop_turn,
    trusted: bool = False,
    instruction: str | None = None,
    nonce: str | None = None,
) -> tuple:
    """One loop run's agent, user message, run kwargs and deps. `user_message`
    is the retrieval query and — unless `trusted` (server text: an [ACTION: ...]
    line) — the student's words, which reach the model only inside the nonce
    envelope (review round 3, C1(a)); `instruction` is server text placed
    verbatim before it. The history's user rows are the student's words too
    (enveloped by the caller, `_guard_history`)."""
    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id or None,
        supabase=None,
        request_id=request_id,
        session_id=session_id,
        feature="loop_tutor",
        learning_loop=learning_loop,
        loop_state=state,
        loop_turn=loop_turn,
    )
    blocks = _context_blocks(
        user_id=user_id, course_id=course_id, user_message=user_message, context=context, item=item
    )
    assembled = assemble_turn_message(
        prefix=prefix,
        blocks=blocks,
        nonce=nonce or new_nonce(),
        student_text=None if trusted else user_message,
        instruction=user_message if trusted else instruction,
    )
    run_kwargs = {
        "deps": deps,
        "message_history": message_history,
        "usage_limits": LOOP_LIMITS,
        **tier_run_kwargs(tier, tool_choice=context.tool_choice),
    }
    return loop_tutor_agent, assembled, run_kwargs, deps


def _template_feedback(verdict: str, reference: str | None) -> str:
    """The hard-level feedback turn (no model): the verdict line, the stored
    reference when the answer is released (H6 content, legal after a wrong
    attempt, spec §3.3), and the fixed next-step line."""
    parts = [_FEEDBACK_VERDICT_LINES[verdict]]
    if reference:
        parts.append(_FEEDBACK_ANSWER_LEAD + reference)
    parts.append(_FEEDBACK_NEXT_STEP)
    return " ".join(parts)


def _continuation_history(messages: list) -> list | None:
    """The failed tool run's messages up to and including its last tool
    results (#646: what follows them is the model's empty answer and any
    output-retry prompts). None when no tool ran — there is nothing to
    continue from, so the turn is re-run tool-less instead."""
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if isinstance(m, ModelRequest) and any(isinstance(p, ToolReturnPart) for p in m.parts):
            return list(messages[: i + 1])
    return None


@dataclass(frozen=True)
class ContinuationPlan:
    """What the tool-less continuation run is: its prompt, its `agent.run`
    kwargs (tools are removed by the caller's override) and its usage feature."""

    prompt: str
    run_kwargs: dict
    feature: str


def continuation_plan(*, assembled: str, run_kwargs: dict, messages: list) -> ContinuationPlan:
    """The #646 continuation of a loop run that ended without a structured turn,
    as data (the route runs it; tests/evals/loop_tutor.py replays through it).
    It continues from the failed run's last tool results with the nudge under
    CONTINUATION_LIMITS, or — no tool ran — re-runs the turn itself under the
    turn's own limits. Same slot, same settings, minus `tool_choice` (no tools,
    so a tool_config would have nothing to choose)."""
    carried = {k: run_kwargs[k] for k in _CONTINUATION_RUN_KEYS if k in run_kwargs}
    carried["model_settings"] = {
        k: v for k, v in (carried.get("model_settings") or {}).items() if k != "tool_choice"
    }
    history = _continuation_history(messages)
    if history is None:
        carried["message_history"] = list(run_kwargs.get("message_history") or [])
        carried["usage_limits"] = run_kwargs.get("usage_limits")
        return ContinuationPlan(prompt=assembled, run_kwargs=carried, feature="loop_tutor")
    carried["message_history"] = history
    carried["usage_limits"] = CONTINUATION_LIMITS
    return ContinuationPlan(
        prompt=_CONTINUATION_NUDGE, run_kwargs=carried, feature="loop_tutor_continuation"
    )


async def _loop_continuation_text(turn, messages: list) -> str | None:
    """The #646 twin of routes.learn._continuation_text for the STRUCTURED loop
    turn. Lane B's live finding: after a tool call gemini flash-lite answered
    with empty responses and never wrote the LoopTurnOut — Gemini only takes
    the structured (JSON) turn with no tools declared (the agent now declares
    no tools after a tool round, so this is the rescue for what is left). So: a
    budget check FIRST (invariant 23; None at the hard level), one counted
    tutor call (A39), then `continuation_plan` run on the SAME slot with every
    tool removed — the safety property, `override(tools=[], toolsets=[])`
    (pinned). Returns the rendered turn (the output validator still judges it
    against deps.loop_turn)."""
    decision = ai_budget.check(turn.user_id, "tutor", turn.band, **turn.budget_counters())
    if decision.level == "hard":
        return None
    plan = continuation_plan(
        assembled=turn.assembled, run_kwargs=turn.run_kwargs, messages=messages
    )
    ai_budget.count_tutor_call(turn.user_id)
    with turn.agent.override(tools=[], toolsets=[]):
        result = record_agent_usage(
            await turn.agent.run(plan.prompt, **plan.run_kwargs),
            feature=plan.feature,
            task=turn.slot,
            user_id=turn.user_id,
        )
    return turn.render(result.output)


# ── The served text (route + tests/evals/loop_tutor.py) ────────────────────


def loop_leak_rung(*, phase: str, rung: Rung, ceiling: Rung, answer_released: bool) -> Rung:
    """The rung model text is served at: H6 once the answer is released, the
    hint rung on a hint turn, else the ceiling — clamped below H6 while the
    answer is unreleased (clamp_model_ceiling: model text never writes H6)."""
    at = rung if phase == "hint" else ceiling
    if answer_released:
        at = Rung.H6
    return Rung(clamp_model_ceiling(at, answer_released))


def released_lead(reference: str) -> str:
    """m1 (review round 3): the stored reference, served FROM CODE above the
    model's released feedback turn — the model is never asked to state or
    compute it, and the turn still ends on its question."""
    return _FEEDBACK_ANSWER_LEAD + (reference or "").strip() + FIELD_JOIN


#: Fix round 2 (N1): what a turn whose model text still leaks after its one
#: retry is served — a fixed, student-facing line per rung (never the
#: model's text with the answer masked in place: the mask's position is itself
#: the signal). Rung by rung it adds no content above the rung's intent.
LADDER_FALLBACK_LINES: dict[int, str] = {
    0: "What will you do next on this item?",
    1: "What is the first thing you need to figure out here?",
    2: "What does your course material say about the idea behind this item?",
    3: "What is the very next step you would take on this item?",
    4: "Which step of the item would you try next?",
    5: "Which part of the item would you fill in next?",
}


#: Fix round 2: the served key idea of an item turn at H0/H1 — those rungs add
#: no content (RUNG_INTENT), so the key idea is the verdict (feedback) or the
#: focus of a hint, from code; recorded model key ideas there stated a
#: definition (judged H2).
LOW_RUNG_KEY_IDEAS: dict[str, str] = {
    "feedback_correct": "Your answer was graded correct.",
    "hint": "Start by pinning down what the item asks you to find.",
}


def _served_fields(out, *, phase: str, rung: Rung, verdict: str | None = None):
    """The structured turn as served (fix round 2). The ladder fixes what the
    lowest rungs may say, so code serves those fields: at an H2 hint the
    question is the ladder's (H2 is a concept pointer: reread the definition —
    recorded model questions named the item's own objects, judged H3); at
    H0/H1 the key idea of a hint or a correct-verdict feedback turn is
    LOW_RUNG_KEY_IDEAS'. The model writes everything else."""
    at = int(rung)
    served = dict(out)
    if phase == "hint" and at == int(Rung.H2) and "question" in out:
        served["question"] = LADDER_FALLBACK_LINES[at]
    if at <= int(Rung.H1) and "key_idea" in out:
        if phase == "hint":
            served["key_idea"] = LOW_RUNG_KEY_IDEAS["hint"]
        elif phase == "feedback" and verdict == "correct":
            served["key_idea"] = LOW_RUNG_KEY_IDEAS["feedback_correct"]
    return served


def served_render(out, *, phase: str, rung: Rung, verdict: str | None = None) -> str:
    """`render_turn` of the turn as served (`_served_fields`)."""
    return render_turn(_served_fields(out, phase=phase, rung=rung, verdict=verdict))


def _item_check_kwargs(
    *,
    reference: str,
    final_answer: str,
    canonical_answer: str | None,
    correct_option: str | None,
    option_text: str | None,
) -> dict:
    return {
        "reference": reference,
        "final_answer": final_answer,
        "canonical_answer": canonical_answer,
        "correct_option": correct_option,
        "option_text": option_text,
        "strict": True,
    }


def served_model_text(
    reply: str,
    *,
    leak_rung: Rung,
    reference: str,
    final_answer: str,
    canonical_answer: str | None = None,
    correct_option: str | None = None,
    option_text: str | None = None,
    answer_released: bool = False,
    given: str = "",
):
    """What the student is served for model-written `reply` against the active
    item. The check is STRICT and in SERVED MODE (`detect_leak(given=…)`,
    fix round 2): a copy of text the model was `given` this turn is no leak,
    and number words / standalone letters count only in answer position. A
    reply that still leaks is NEVER masked in place (N1): it is replaced by the
    rung's LADDER_FALLBACK_LINES line (the model already had its one leak
    retry, `deps.loop_leak`). The released answer's lead (`released_lead`)
    goes in front when the answer is released. Returns (text, LeakVerdict)."""
    item = _item_check_kwargs(
        reference=reference,
        final_answer=final_answer,
        canonical_answer=canonical_answer,
        correct_option=correct_option,
        option_text=option_text,
    )
    verdict = detect_leak(emitted=reply, rung=leak_rung, given=given, **item)
    text = LADDER_FALLBACK_LINES[int(Rung(leak_rung))] if verdict.leaked else reply
    return (released_lead(reference) + text if answer_released else text), verdict


# ── The served session close (PKG-09; spec §13 A25, A51) ─────────────────


def close_states_answer(text: str, item) -> bool:
    """Strict leak check of close text against one item the session posed but
    never released: in served mode (the item as posed is the provenance, as
    PKG-07's served_model_text reads it) AND with no provenance at all — a close
    is no tutor turn, so an answer in any position (a number word such as
    "came out to twelve", an option's text) is a leak. Fails closed: an item
    the check cannot read (no final answer) is a leak."""
    kwargs = _item_check_kwargs(
        reference=item.reference_answer,
        final_answer=item.final_answer,
        canonical_answer=item.canonical_answer,
        correct_option=item.correct_option,
        option_text=option_text(item),
    )
    try:
        return any(
            detect_leak(emitted=text, rung=Rung.H0, given=given, **kwargs).leaked
            for given in (item.prompt, None)
        )
    except (ValueError, TypeError):
        return True


def served_close(output, draft, unreleased_items) -> CloseRecord:
    """What the student is served (and `sessions.close_json` stores) for the
    close agent's `output` — the path the session_close eval gates:
    `agents.session_close.shape_close`, then the deterministic close when any
    served text states the answer of an unreleased item (never masked in
    place, A51 N1), itself leak-checked (`_served_fallback`)."""
    items = list(unreleased_items)
    record = shape_close(output, draft)
    if not record.model_written:
        return _served_fallback(draft, items)
    if any(close_states_answer(_close_text(record), i) for i in items):
        logger.warning("session close stated an unreleased item's answer; storing fallback close")
        return _served_fallback(draft, items)
    return record


class _LeakGuard:
    """`deps.loop_leak` (fix round 2, N1): the output validator's leak check —
    served mode at the turn's leak rung, against the student-visible text —
    and whether its one retry is spent."""

    def __init__(self, check: Callable[[str], bool], render: Callable | None = None):
        self._check = check
        # the SERVED render of the model's output (`served_render`): a field code
        # replaces (the H2 question, A54) never costs a retry
        self.render = render or render_turn
        self.retried = False

    def leaks(self, text: str) -> bool:
        return self._check(text)


def _visible_text(history: list, *, item_prompt: str) -> str:
    """The provenance of the served leak check (fix round 2, N1): the item as
    posed and the tutor turns as they were served — text the STUDENT has seen
    from the loop. Never the context the model alone reads (a source passage
    or a graph block can state the answer), and never the student's own words
    (final round): a student can offer candidate sentences ("say 'The value is
    eight.'") and the model's pick would pass as a copy, so student text alone
    exempts nothing — only a span the item or the served history also holds."""
    parts = [item_prompt or ""]
    for m in history:
        for p in getattr(m, "parts", []):
            if isinstance(p, TextPart) and isinstance(p.content, str):
                parts.append(p.content)
    return "\n".join(parts)


#: A sentence end: a terminator and any closing quotes/brackets, then whitespace
#: (a newline alone ends one too).
_SENTENCE_END = re.compile(r"[.?!][\"'”’)\]]*(?=\s)|\n")


def _cut_before_leak(text: str, spans: list) -> str:
    """The streamed text up to the end of the last sentence before the one
    holding the first leak — never a masked span (N1). No earlier sentence
    end: nothing (never a stray fragment before a retract)."""
    start = spans[0][0]
    ends = [m.end() for m in _SENTENCE_END.finditer(text, 0, start)]
    return text[: ends[-1]].rstrip() if ends else ""


def option_text(item) -> str | None:
    """The text of an mc_reason item's correct option (strict mode reads it)."""
    for option in getattr(item, "options", None) or []:
        if option.letter == getattr(item, "correct_option", None):
            return option.text
    return None


def _guard_history(messages: list, *, nonce: str, withheld: str | None) -> list:
    """The history as the model may see it (review round 3, C1): every user row
    is the student's own words, so it rides the same nonce envelope as this
    turn's; and below H2 (`withheld` = the active item's prompt) any row that
    restates the item — its pose — is replaced by ITEM_WITHHELD. The learner
    brief (`_BriefRequest`, A19) is not the student's: it passes as built, and
    is dropped for the turn when it restates the withheld item."""
    out: list = []
    for m in messages:
        if isinstance(m, _BriefRequest):
            # A19: served as built — unless it restates the withheld item (C1(b))
            if not (withheld and any(withheld in str(p.content) for p in m.parts)):
                out.append(m)
            continue
        if isinstance(m, ModelRequest):
            parts = []
            for p in m.parts:
                if isinstance(p, UserPromptPart) and isinstance(p.content, str):
                    text = ITEM_WITHHELD if (withheld and withheld in p.content) else p.content
                    p = UserPromptPart(content=student_envelope(text, nonce=nonce))
                parts.append(p)
            out.append(ModelRequest(parts=parts))
        elif isinstance(m, ModelResponse) and withheld:
            parts = [
                TextPart(content=ITEM_WITHHELD)
                if isinstance(p, TextPart) and withheld in p.content
                else p
                for p in m.parts
            ]
            out.append(ModelResponse(parts=parts))
        else:
            out.append(m)
    return out


# ── The turn ───────────────────────────────────────────────────────────────


class _LoopTurn:
    """One loop turn, shared by the JSON and streamed paths.

    Built BEFORE the budget is read (phase, band, ceiling); `plan(decision)`
    is called by the run site right after ai_budget.check (tier, context,
    prefix, or the deterministic text); `complete` runs AFTER the reply
    exists (leak check, feedback bookkeeping, counters, persist). The
    reference answer is an attribute of this object only.
    """

    def __init__(
        self,
        *,
        body: ChatBody,
        request: Request,
        message: str,
        kind: str = "chat",
        persist_user_row: bool = True,
        state: dict | None = None,
        verdict: str | None = None,
        scope: tuple[str, str] | None = None,
        loop_on: bool,
        refused: bool = False,
    ):
        self.user_id, self.session_id = body.user_id, body.session_id
        self.mode = body.mode
        self.message, self.kind, self.persist_user_row = message, kind, persist_user_row
        # an [ACTION: ...] turn's message is server text; every other is the student's
        self.trusted, self.instruction = kind == "action", None
        self.loop_on, self.refused = loop_on, refused
        self.request_id = _request_id(request)
        self.offering_id, self.course_id = scope or _session_scope(body.session_id, body.user_id)
        self.state = state if state is not None else _load_loop_state(body.session_id)
        self._derive(verdict)

    def _derive(self, verdict: str | None) -> None:
        """Everything the turn knows before the budget is read."""
        active = self.state.get("current")
        entry = (self.state.get("steps") or {}).get(active) if active else None
        self.item = None
        self.deps = None
        if isinstance(entry, dict) and entry.get("check_item_id"):
            self.item = get_check_item(entry["check_item_id"])
        # A23 withdrawal: the active item is gone — drop it; the entry stays.
        self.withdrawn = active if (active and self.item is None) else None
        self.active = None if self.withdrawn else active
        view = dict(self.state, current=self.active)
        self.phase = _turn_phase(self.kind, _phase_for(view))
        self.step = _step_state(self.state, self.active)
        self.entry = dict(entry) if (self.active and isinstance(entry, dict)) else {}
        self.node_id = _node_for_item(self.user_id, self.item) if self.item is not None else None
        # A27: teach turns take the current plan concept's band
        self.concept_node = self.node_id or self.state.get("concept")
        learner = _learner_state(self.user_id, self.concept_node)
        self.band, self.p_known = _band_of(learner)
        self.verdict = verdict or (
            self.entry.get("last_verdict") if self.phase == "feedback" else None
        )
        self.answer_released = self.phase == "feedback" and self.verdict != "correct"
        self.rung = self.step.rung if self.phase == "hint" else Rung.H0
        prereq = _prereq_proficient(self.user_id, self.concept_node) if self.concept_node else True
        self.ceiling, self.ceiling_reason = _ceiling_for(
            step=self.step,
            learner=_learner_view(learner, band=self.band, prereq_proficient=prereq),
            message=self.message,
            independent_s=_seconds_since(self.step.first_shown_at, _now_s()),
        )
        self.planned = None
        self.given = ""
        self.tier, self.text, self.paused = "none", None, False
        self.revealed_hash, self.served_as_h6 = None, False

    @property
    def slot(self) -> str:
        return LOOP_TIER_SLOTS[self.tier]

    def budget_counters(self) -> dict:
        return {
            "session_tutor_requests": int(self.state.get("tutor_requests") or 0),
            "session_deep_requests": int(self.state.get("deep_requests") or 0),
            "arm_session": False,  # loop_arm arrives with PKG-14a
        }

    def history(self) -> list:
        return _load_loop_history(
            self.session_id,
            user_id=self.user_id,
            course_id=self.course_id,
            loop_state=self.state,
        )

    def plan(self, decision) -> None:
        """Tier + run assembly for `decision`, the ai_budget verdict the calling
        run site just read (invariant 23). Idempotent for the same decision."""
        if self.planned is decision:
            return
        self.planned = decision
        self.tier, self.text, self.paused = "none", None, False
        self.revealed_hash, self.served_as_h6 = None, False
        if decision.pause_novice and self.band == "novice" and self.phase in ("check", "hint"):
            self.paused = True  # novice-band concepts pause at the hard level (§3.5)
            return
        self.text = self._deterministic_text(hard=decision.level == "hard")
        if self.phase != "check":  # the pose never reaches the model (A17)
            deep = self.budget_counters()["session_deep_requests"]
            self.tier = routable_tier(
                policy.model_tier(
                    self._tier_phase(),
                    self.band,
                    self.rung,
                    _failed_on_concept(self.state, self.concept_node),
                    False,  # misconception_active: PKG-10
                    deterministic_payload=self.text is not None,
                    budget_level=decision.level,
                    deep_cap_reached=deep >= LOOP_SESSION_MAX_DEEP_REQUESTS,
                    novice_deep_cap_reached=deep >= LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE,
                    arm_session=False,
                )
            )
        if self.tier == "none":
            self.paused = self.text is None
            return
        self.text = None  # the model writes this turn
        self.revealed_hash, self.served_as_h6 = None, False
        context = policy.context_policy(
            self.phase, opener=self.kind == "opener", budget_level=decision.level
        )
        item_phase = self.phase in ("hint", "feedback")
        # model text never writes H6 before the answer is released (clamp_model_ceiling)
        model_ceiling = Rung(
            clamp_model_ceiling(
                self.rung if self.phase == "hint" else self.ceiling, self.answer_released
            )
        )
        # C1(b): H0/H1 add no content — with an unreleased item in view the model
        # gets neither its text (the prefix withholds it) nor its source passages,
        # retrieval, tool calls, or a history row that restates it
        withhold = self.item is not None and not item_visible(model_ceiling, self.answer_released)
        if withhold:
            context = context._replace(rag_k=0, source_chunks=0, tool_choice="none")
        nonce = new_nonce()
        history = self.history()
        self.prefix = phase_prefix(
            phase=self.phase,
            band=self.band,
            ceiling=model_ceiling,
            item_prompt=self.item.prompt if (item_phase and self.item) else None,
            item_format=self.item.format if (item_phase and self.item) else None,
            answer_released=self.answer_released,
            verdict=self.verdict if self.phase == "feedback" else None,
        )
        self.agent, self.assembled, self.run_kwargs, self.deps = _prepare_loop_run(
            user_id=self.user_id,
            session_id=self.session_id,
            course_id=self.course_id,
            user_message=self.message,
            message_history=_guard_history(
                history, nonce=nonce, withheld=self.item.prompt if withhold else None
            ),
            request_id=self.request_id,
            prefix=self.prefix,
            state=self.state,
            tier=self.tier,
            context=context,
            item=self.item,
            learning_loop=self.loop_on,
            loop_turn=turn_limits(self.phase, model_ceiling, self.answer_released),
            trusted=self.trusted,
            instruction=self.instruction,
            nonce=nonce,
        )
        # N1: the provenance the served leak check reads, and the validator's guard
        self.given = _visible_text(
            history,
            item_prompt=self.item.prompt if self.item is not None else "",
        )
        self.deps.loop_leak = self._leak_guard()

    def _tier_phase(self) -> str:
        """PKG-06's TurnPhase: the feedback verdict rides the phase value."""
        if self.kind == "opener":
            return "opener"
        if self.phase == "feedback":
            return "feedback_correct" if self.verdict == "correct" else "feedback_wrong"
        return self.phase  # "teach" | "hint"

    def _deterministic_text(self, *, hard: bool) -> str | None:
        if self.kind == "unavailable":
            return _GRADE_UNAVAILABLE_REPLY
        if self.kind == "refused":
            return _ANSWER_REFUSED_REPLY
        if self.phase == "check" and self.item is not None:
            return ladder.check_pose(self.item.prompt)
        if self.phase == "hint" and self.item is not None and self.rung in _DETERMINISTIC_RUNGS:
            payload, leaked = _leak_checked_payload(
                user_id=self.user_id,
                item=self.item,
                rung=self.rung,
                reference=self.item.reference_answer,
            )
            if payload is None:
                return None
            if leaked:
                # Fall back to the LLM rung; only when no model may run (hard) is a
                # leaking payload served — and then only where H6 is allowed, and
                # recorded as H6 (no upward BKT credit, §3.3).
                if not (hard and _h6_ok(self.state, self.active, self.entry, self.item)):
                    return None
                self.served_as_h6 = True
            self.revealed_hash = payload.revealed_hash
            return payload.text
        if self.phase == "feedback" and hard and self.item is not None:
            reference = self.item.reference_answer if self.answer_released else None
            return _template_feedback(self.verdict, reference)
        return None

    def pre_events(self) -> list[SaplingEvent]:
        evs = [
            SaplingEvent(
                type="phase",
                step="loop",
                message=f"Phase: {self.phase}.",
                data={"phase": self.phase},
            )
        ]
        if self.item is not None and self.active and self.phase in ("check", "hint"):
            evs.append(
                SaplingEvent(
                    type="check",
                    step="loop",
                    message="Check item.",
                    data={
                        "question_hash": self.active,
                        "format": self.item.format,
                        "difficulty": self.item.difficulty,
                    },
                )
            )
        return evs

    def record_usage(self, run_result) -> None:
        record_agent_usage(run_result, feature="loop_tutor", task=self.slot, user_id=self.user_id)

    def _leak_rung(self) -> Rung:
        """`loop_leak_rung` for this turn."""
        return loop_leak_rung(
            phase=self.phase,
            rung=self.rung,
            ceiling=self.ceiling,
            answer_released=self.answer_released,
        )

    def _item_answer(self) -> dict:
        """The active item's answer forms (A34), for an mc_reason item its
        correct option letter (A38 06 gap) and text (strict mode, C1(c))."""
        return {
            "reference": self.item.reference_answer,
            "final_answer": self.item.final_answer,
            "canonical_answer": self.item.canonical_answer,
            "correct_option": self.item.correct_option,
            "option_text": option_text(self.item),
        }

    def _item_leak_kwargs(self) -> dict:
        """served_model_text's item keywords: the answer forms, whether the
        answer is released (its lead, m1) and the text the model was given."""
        return {**self._item_answer(), "answer_released": self.answer_released, "given": self.given}

    def _leak_guard(self) -> _LeakGuard | None:
        """deps.loop_leak for an unreleased active item (fix round 2, N1)."""
        if self.item is None or self.answer_released:
            return None
        rung, answer = self._leak_rung(), _item_check_kwargs(**self._item_answer())

        given = self.given

        def check(text: str) -> bool:
            return detect_leak(emitted=text, rung=rung, given=given, **answer).leaked

        return _LeakGuard(check, render=self.render)

    def redact(self, text: str) -> str:
        """stream_structured_turn's `transform` on the streamed (cumulative)
        text, BEFORE any token is sent: text that states the answer is never
        shown, and never masked in place (N1) — the stream stops before the
        sentence that holds it (the output validator's retry, or the final
        ladder line, replaces it). The released answer's lead goes in front."""
        if self.tier == "none" or self.item is None:
            return text
        if self.answer_released:
            return released_lead(self.item.reference_answer) + text
        spans = leak_spans(
            emitted=text, given=self.given, **_item_check_kwargs(**self._item_answer())
        )
        return _cut_before_leak(text, spans) if spans else text

    def render(self, out) -> str:
        """The served render of the model's structured turn (`served_render`)."""
        return served_render(out, phase=self.phase, rung=self._leak_rung(), verdict=self.verdict)

    def render_partial(self, partial) -> str:
        """The streamed partial as served (the same field override)."""
        return render_partial(
            _served_fields(partial, phase=self.phase, rung=self._leak_rung(), verdict=self.verdict)
        )

    def serve(self, text: str) -> str:
        """stream_structured_turn's `transform_final`: the served text of the
        final render (`served_model_text`)."""
        if self.tier == "none" or self.item is None:
            return text
        served, _ = served_model_text(text, leak_rung=self._leak_rung(), **self._item_leak_kwargs())
        return served

    def _leak_checked(self, reply: str) -> tuple[str, bool]:
        """Model-written text is leak-checked against the ACTIVE item at the rung
        it is served at (`_leak_rung`; A34: the item's structured final answer),
        through `served_model_text` (strict; the released lead in front)."""
        if self.tier == "none" or self.item is None:
            return reply, False
        served, verdict = served_model_text(
            reply, leak_rung=self._leak_rung(), **self._item_leak_kwargs()
        )
        if not verdict.leaked:
            return served, False
        zpd_events.emit_zpd_leak(
            user_id=self.user_id,
            request_id=self.request_id,
            rung_emitted=self._leak_rung(),
            ceiling=self.ceiling,
            detector=verdict.detector,
        )
        return served, True

    def _emit_step(self, entry: dict) -> None:
        """zpd.step for the ONE feedback turn (spec §6), from what
        _grade_submission recorded. Times derive from the stored timestamps;
        a key the route cannot answer (`r_before`) is null, never zero."""
        try:
            shown = float(entry.get("first_shown_at") or 0.0)
            graded = float(entry["graded_at"])
            log = [r for r in entry.get("rungs") or [] if isinstance(r, dict)]
            ats = [float(r["at"]) for r in log] + [graded]
            rungs = [
                {"rung": int(r["rung"]), "dwell_ms": _ms(ats[i + 1] - ats[i])}
                for i, r in enumerate(log)
            ]
            first_attempt = min([float(t) for t in entry.get("attempted_at") or []] + [graded])
            zpd_events.emit_zpd_step(
                user_id=self.user_id,
                request_id=self.request_id,
                concept_id=entry.get("node_id") or self.node_id,
                question_hash=self.active,
                phase="check",
                channel=entry["channel"],
                band=bkt_band(float(entry["p_before"])),
                ceiling=self.ceiling,
                ceiling_reason=self.ceiling_reason,
                first_attempt_correct=bool(entry.get("first_attempt_correct")),
                n_attempts=int(entry.get("graded") or 0),
                max_rung_used=Rung(int(entry.get("max_rung") or 0)),
                rungs=rungs,
                time_to_first_attempt_ms=_ms(first_attempt - shown) if shown else None,
                time_to_correct_ms=_ms(graded - shown)
                if (shown and entry.get("last_correct"))
                else None,
                independent_time_ms=_ms(ats[0] - shown) if shown else None,
                assisted=bool(entry.get("assisted")),
                confidence=entry.get("confidence"),
                fsrs_rating=int(entry["fsrs_rating"]),
                p_known_before=float(entry["p_before"]),
                p_known_after=self.p_known,
                r_before=None,
                item_difficulty=self.item.difficulty,
                tier=self.tier,
                grader_backend=entry.get("grader_backend"),
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("zpd.step not emitted for %s: incomplete step record", self.active)

    def complete(self, reply: str, merged: dict, mastery: list) -> dict:
        """Called exactly once per served turn: leak check, then this turn's
        changes applied to the FRESH document by ONE compare-and-set write
        (`_apply_turn`, re-run on a conflict), then — after the save — the
        zpd.step, the message rows and the usage event."""
        reply, redacted = self._leak_checked(reply)
        out: dict = {}
        self._now = _now_s()
        _update_loop_state(self.session_id, lambda state: self._apply_turn(state, out))
        if out.get("step") is not None:
            self._emit_step(out["step"])
        check = None
        if out.get("activated"):
            item = get_check_item(out["activated"])
            check = _pose_payload(item) if item is not None else None
        if self.persist_user_row:
            save_message(self.session_id, "user", self.message)
        save_message(self.session_id, "assistant", reply, merged or None)
        if check is not None:
            save_message(self.session_id, "assistant", check["prompt"])
        if self.persist_user_row:
            events_service.log_event(
                "chat.message_sent",
                category="usage",
                user_id=self.user_id,
                request_id=self.request_id,
                payload={"mode": self.mode, "session_id": self.session_id},
                content=self.message,
            )
        offer_rung = out.get("offer_rung")
        return {
            **self._submission_extra(),
            "reply": reply,
            "leak_redacted": redacted,
            "phase": self.phase,
            "tier": self.tier,
            "ceiling": int(self.ceiling),
            "learner_state": (
                [{"node_id": self.node_id, "p_known": self.p_known, "band": self.band}]
                if self.node_id
                else []
            ),
            "hint_offer": {"rung": offer_rung} if offer_rung is not None else None,
            "budget": _budget_data(self.planned) if self.planned.level == "hard" else None,
            "check": check,
        }

    def _apply_turn(self, state: dict, out: dict) -> None:
        """This turn's change to the loop document — the compare-and-set mutate,
        so it may run more than once (each time on a fresher document): it
        changes `state` in place, records what the caller emits after the save
        in `out`, and has no side effects."""
        out.clear()
        steps = _steps(state)
        if self.phase == "feedback" and self.active in steps:
            entry = steps[self.active]
            out["step"] = dict(entry)  # the zpd.step record, emitted after the save
            if gates.offer_allowed(self.band, self.verdict != "correct"):
                entry["offered"] = True
                out["offer_rung"] = min(int(self.ceiling), int(entry.get("rung") or 0) + 1)
            entry["feedback_given"] = True
            if state.get("current") == self.active:
                state["current"] = None
            # A27: one more graded check on the concept; the cursor advances at the cap
            state["concept_checks"] = int(state.get("concept_checks") or 0) + 1
            state["teach_turns"] = 0
            if state["concept_checks"] >= LOOP_CHECKS_PER_CONCEPT:
                _advance_cursor(state)
        state["phase_served"] = self.phase
        if self.tier != "none":
            state["tutor_requests"] = int(state.get("tutor_requests") or 0) + 1
            if self.tier == "deep":
                state["deep_requests"] = int(state.get("deep_requests") or 0) + 1
        if self.revealed_hash:  # an H4 sibling shown: never a future check (A23)
            revealed = list(state.get("revealed") or [])
            if self.revealed_hash not in revealed:
                state["revealed"] = [*revealed, self.revealed_hash]
        if self.served_as_h6 and self.active in steps:
            steps[self.active]["rung"] = int(Rung.H6)
        if self.withdrawn and state.get("current") == self.withdrawn:
            state["current"] = None
        if self.phase == "teach" and not state.get("current"):
            # A27 trigger 1: a served teach turn on the current concept; the
            # LOOP_TEACH_TURNS_BEFORE_CHECK-th activates its next check item
            state["teach_turns"] = int(state.get("teach_turns") or 0) + 1
            if state["teach_turns"] >= LOOP_TEACH_TURNS_BEFORE_CHECK:
                qh = _activate_next_item(self.user_id, self.course_id, state, now=self._now)
                if qh is not None:
                    out["activated"] = state["steps"][qh]["check_item_id"]

    def _submission_extra(self) -> dict:
        """The check-answer response keys (A16) — only on a submission's turn."""
        if self.kind not in _SUBMISSION_KINDS:
            return {}
        return {
            "graded": self.kind == "feedback",
            "verdict": self.verdict,
            "unavailable": self.kind == "unavailable",  # the outage flag only
            "refused": self.refused,  # A33: a refusal, or the idk it became
            "answer_released": self.answer_released,
        }


class _LoopOpener(_LoopTurn):
    """The session opener (spec Behaviour 15): a fresh session, `teach` with no
    item and the BKT_L0 band, the catalog context (the opener only), and the
    legacy lazy-session contract — `complete` stashes PENDING_SESSIONS and
    persists and counts nothing (no sessions row exists yet)."""

    def __init__(
        self,
        *,
        body: StartSessionBody,
        request: Request,
        loop_on: bool,
        session_id: str | None = None,
    ):
        self.start = body
        self.user_id, self.session_id = body.user_id, session_id or str(uuid.uuid4())
        self.mode = body.mode
        self.kind, self.persist_user_row = "opener", False
        self.loop_on, self.refused = loop_on, False
        self.request_id = _request_id(request)
        self.course_id = body.course_id or _get_course_id_for_topic(body.topic, body.user_id)
        self.offering_id = resolve_offering(self.course_id, create=True) if self.course_id else ""
        # routes/learn.py::_start_session_agent (:540–543)'s cue, as server text;
        # the topic is the student's and rides the envelope (review round 3, C1(a))
        self.message = body.topic or ""
        self.trusted = False
        self.instruction = (
            "The student opened a session; the topic they typed is below. Begin the "
            "session with a warm greeting and your first question or explanation."
        )
        self.state = {}
        self._derive(None)

    def history(self) -> list:
        return []

    def _deterministic_text(self, *, hard: bool) -> str | None:
        # the opener is never paused: at the hard level it is the template (A27)
        return _LOOP_OPENER_TEMPLATE if hard else None

    def complete(self, reply: str, merged: dict, mastery: list) -> dict:
        PENDING_SESSIONS[self.session_id] = {
            "user_id": self.user_id,
            "mode": self.mode,
            "topic": self.start.topic,
            "course_id": self.course_id,  # abstract — graph + shared-context key
            "offering_id": self.offering_id,  # term-scoped — the session-row key
            "use_shared_context": self.start.use_shared_context,
            "assistant_reply": reply,
            "graph_update": merged or {},
            "loop": True,
        }
        return {
            "reply": reply,
            "session_id": self.session_id,
            "graph_state": get_graph(self.user_id),
            "tier": self.tier,
            "phase": self.phase,
            "budget": _budget_data(self.planned) if self.planned.level == "hard" else None,
        }


def _h6_ok(state: dict, qh: str | None, item_state: dict, check) -> bool:
    """Spec §3.3 H6 item predicates (§13 A32), for the one gate PKG-06 owns:
    taught (recorded at activation), practice (the ACTIVE in-session check;
    activation never selects the post-test reserve), not graded coursework (a
    missing item fails closed). Ungraded alone never admits H6."""
    return gates.h6_allowed(
        _step_state(state, qh),
        item_taught=bool((item_state or {}).get("taught")),
        item_practice=qh is not None and state.get("current") == qh,
        item_graded=check is None or bool(check.graded),
    )


def _leak_checked_payload(*, user_id: str, item, rung: Rung, reference: str | None) -> tuple:
    """A17: the deterministic H2/H4/H6 payload for `rung`, leak-checked HERE,
    in the same function, before anything can emit it (invariant 27; A34: the
    active item's structured final answer). Returns (payload | None, leaked).
    H2 passages are resolved for the requesting student through the
    visibility-aware reader; H4 never shows the concept's post-test reserve
    (A23, HANDOFF-06), so the concept's items are read whole — the reserve is
    defined over all of them — and ladder.deterministic_content keeps the
    siblings of the item's format and difficulty."""
    passages: list[str] = []
    if rung == Rung.H2:
        ids = list(item.source_chunk_ids or [])[:LOOP_SOURCE_CHUNKS_MAX]
        passages = [r["chunk_text"] for r in chunks_for_ids(ids, user_id=user_id)] if ids else []
    siblings: list = []
    reserve = None
    if rung == Rung.H4:
        concept_items = list_items(item.course_id, item.concept_key)
        reserve = posttest_reserve_hash(concept_items)
        siblings = [s for s in concept_items if s.question_hash != item.question_hash]
    payload = ladder.deterministic_content(
        rung,
        _item_like(item),
        [_item_like(s) for s in siblings],
        passages,
        exclude_hashes={reserve} if reserve else (),
    )
    if payload is None:
        return None, False
    verdict = detect_leak(
        reference=reference or "",
        emitted=payload.text,
        rung=rung,
        final_answer=item.final_answer,
        canonical_answer=item.canonical_answer,
        correct_option=item.correct_option,
    )
    return payload, verdict.leaked


# ── Item activation and the current concept (spec §9, §13 A27) ─────────────


def _concept_key_for_node(user_id: str, node_id: str) -> str | None:
    """The A2 course key of the student's node — the inverse of _node_for_item.
    One `graph_nodes` read by id, scoped to the student."""
    rows = (
        table("graph_nodes").select(
            "concept_name", filters={"id": f"eq.{node_id}", "user_id": f"eq.{user_id}"}, limit=1
        )
        or []
    )
    return _normalize_concept(rows[0].get("concept_name") or "") if rows else None


def _advance_cursor(state: dict) -> bool:
    """Move the plan (PKG-08's `plan = {approved, cursor}`) to its next concept,
    resetting the concept's counters; past the end the plan is done and there is
    no current concept. False when there is no next concept (or no plan)."""
    plan = state.get("plan")
    if not isinstance(plan, dict):
        return False
    approved = list(plan.get("approved") or [])
    plan["cursor"] = int(plan.get("cursor") or 0) + 1
    if plan["cursor"] >= len(approved):
        plan["done"] = True
        state.pop("concept", None)
        return False
    state["concept"] = approved[plan["cursor"]]
    state["teach_turns"] = 0
    state["concept_checks"] = 0
    return True


def _activate_next_item(user_id: str, course_id: str, state: dict, *, now: float) -> str | None:
    """The ONLY code that SETS the document's `current` (the spec's `active`;
    feedback and withdrawal only clear it). For the current plan concept: its
    items, minus everything the student has seen or had revealed, every hash
    already keyed in this session and the concept's post-test reserve (A23);
    the band's target difficulty; the formats rotated by the concept's checks
    so far. A concept with nothing servable advances the cursor and tries the
    next (at most once per remaining concept). No plan → None (teaching only).
    Writes no evidence and runs no model."""
    concept = state.get("concept")
    if not concept:
        return None
    excluded = seen_hashes(user_id) | revealed_hashes(user_id) | set(state.get("steps") or {})
    while True:
        item = None
        key = _concept_key_for_node(user_id, concept)
        if key:
            items = list_items(course_id, key)
            reserve = posttest_reserve_hash(items)
            exclude = excluded | ({reserve} if reserve else set())
            band, _ = _band_for(user_id, concept)
            rotation = int(state.get("concept_checks") or 0) % len(CHECK_ITEM_FORMATS)
            formats = CHECK_ITEM_FORMATS[rotation:] + CHECK_ITEM_FORMATS[:rotation]
            for fmt in formats:
                item = select_item(
                    items,
                    format=fmt,
                    difficulty=LOOP_CHECK_DIFFICULTY_BY_BAND[band],
                    exclude_hashes=exclude,
                )
                if item is not None:
                    break
        if item is not None:
            qh = item.question_hash
            state["current"] = qh
            _steps(state)[qh] = {
                "rung": int(Rung.H0),
                "attempts": 0,
                "wrong": 0,
                "first_shown_at": now,
                "check_item_id": item.id,
                "node_id": concept,
                "feedback_given": False,
                # the H6 predicate (spec §3.3, A32): taught earlier in this session
                "taught": bool(state.get("teach_turns") or state.get("concept_checks")),
            }
            return qh
        if not _advance_cursor(state):
            return None
        concept = state["concept"]


def _pose_payload(item) -> dict:
    """The check pose the client renders (A17: the prompt verbatim; A22: an
    mc_reason item's stored options, never rebuilt, never marked correct, no
    wrong_key). Never the reference."""
    options = None
    if item.format == "mc_reason" and item.options:
        options = [{"letter": o.letter, "text": o.text} for o in item.options]
    return {
        "question_hash": item.question_hash,
        "format": item.format,
        "difficulty": item.difficulty,
        "prompt": ladder.check_pose(item.prompt),
        "options": options,
    }


def _ms(seconds: float) -> int:
    """Whole milliseconds, never negative (zpd.step's *_ms keys)."""
    return max(0, round(timedelta(seconds=seconds) / timedelta(milliseconds=1)))


# ── Run sites ──────────────────────────────────────────────────────────────


async def _run_turn_json(turn: _LoopTurn) -> dict:
    """The JSON run site (chat, action, check-answer turns, opener): budget →
    plan → deterministic text or ONE model run → complete. The run is
    counted (A39: once per model RUN; its tool round and output retries are
    uncharged but bounded by LOOP_LIMITS / LOOP_OUTPUT_RETRIES) right before
    it. A tool run that ends without a structured turn (#646; UnexpectedModelBehavior
    — the run is still billed) is finished by the tool-less continuation.
    Persist ordering mirrors routes.learn._chat_turn_json."""
    decision = ai_budget.check(turn.user_id, "tutor", turn.band, **turn.budget_counters())
    turn.plan(decision)
    if turn.paused:
        raise _BudgetPaused(decision)
    if turn.tier == "none":
        return {"graph_update": {}, "mastery_changes": [], **turn.complete(turn.text, {}, [])}
    reply = None
    usage = RunUsage()
    ai_budget.count_tutor_call(turn.user_id)
    with capture_run_messages() as messages:
        try:
            result = await turn.agent.run(turn.assembled, usage=usage, **turn.run_kwargs)
        except UnexpectedModelBehavior:
            logger.warning("Loop tool run ended without a structured turn", exc_info=True)
            turn.record_usage(UnfinishedRun(usage))
        else:
            turn.record_usage(result)
            reply = turn.render(result.output)
    if reply is None:
        reply = await _continue_turn(turn, list(messages))
    return {"graph_update": {}, "mastery_changes": [], **turn.complete(reply, {}, [])}


async def _continue_turn(turn: _LoopTurn, messages: list) -> str:
    """The #646 rescue of a planned turn whose run ended without a structured
    turn: `_loop_continuation_text` over the failed run's messages."""
    try:
        reply = await _loop_continuation_text(turn, messages)
    except UnexpectedModelBehavior:
        logger.warning("Tool-less loop continuation failed", exc_info=True)
        reply = None
    if not reply:
        raise UnexpectedModelBehavior("loop_tutor produced no structured turn")
    return reply


def _pre_done_events(data: dict) -> list[SaplingEvent]:
    evs = [
        SaplingEvent(type="learner_state", step="loop", message="Learner state.", data=ls)
        for ls in (data.get("learner_state") or [])
    ]
    if data.get("hint_offer"):
        evs.append(
            SaplingEvent(
                type="hint_offer", step="loop", message="Hint available.", data=data["hint_offer"]
            )
        )
    if data.get("check"):  # a check item activated by this turn (A27 trigger 1)
        pose = data["check"]
        evs.append(
            SaplingEvent(
                type="check",
                step="loop",
                message="Check item.",
                data={k: pose[k] for k in ("question_hash", "format", "difficulty")},
            )
        )
    return evs


async def _stream_turn(turn: _LoopTurn):
    """The SSE run site (chat, check-answer turns, opener). Loop events are
    yielded AROUND stream_structured_turn, never from inside it. The stream's
    `transform` is the turn's leak strip, applied to the cumulative text before
    any token is sent; `complete` gets the raw render and records the leak.
    Its Rung-1 fallback is the tool-less JSON turn (#646)."""
    decision = ai_budget.check(turn.user_id, "tutor", turn.band, **turn.budget_counters())
    try:
        turn.plan(decision)
    except Exception:
        # ADR 0024 honest degrade: nothing was shown or written — one terminal error
        logger.exception("Loop turn could not be planned")
        yield sapling_event_to_sse(_stream_error(turn, _STREAM_UNAVAILABLE))
        return
    for ev in turn.pre_events():
        yield sapling_event_to_sse(ev)
    if turn.paused:
        yield sapling_event_to_sse(_budget_event(decision))
        return
    if decision.level == "hard":
        # a deterministic turn served at the hard level carries the pause notice
        yield sapling_event_to_sse(_budget_event(decision))
    if turn.tier == "none":
        try:
            extra = turn.complete(turn.text, {}, [])
        except Exception:
            # Behaviour 19: stream_agent_turn's on_complete guard, for the template path
            logger.warning("Deterministic loop turn failed to persist", exc_info=True)
            yield sapling_event_to_sse(_stream_error(turn, _STREAM_INTERRUPTED))
            return
        data = {"graph_update": {}, "mastery_changes": [], **extra}
        for ev in _pre_done_events(data):
            yield sapling_event_to_sse(ev)
        yield sapling_event_to_sse(
            SaplingEvent(type="done", step="reply", message="Complete.", data=data)
        )
        return
    usage = RunUsage()

    async def fallback(messages: list) -> dict:
        """Rung 1 (m2): the SAME planned turn — no second plan(), no second
        retrieval — billed for the failed streamed run and continued from its
        messages (tool results) by the tool-less continuation."""
        turn.record_usage(UnfinishedRun(usage))
        reply = await _continue_turn(turn, messages)
        return {"graph_update": {}, "mastery_changes": [], **turn.complete(reply, {}, [])}

    ai_budget.count_tutor_call(turn.user_id)
    async for ev in stream_structured_turn(
        agent=turn.agent,
        user_message=turn.assembled,
        run_kwargs={**turn.run_kwargs, "usage": usage},
        deps=turn.deps,
        on_complete=turn.complete,
        nonstream_fallback=fallback,
        on_usage=turn.record_usage,
        request_id=turn.request_id,
        transform=turn.redact,
        transform_final=turn.serve,
        render_final=turn.render,
        render_partial=turn.render_partial,
    ):
        if ev.type == "done":
            for extra_ev in _pre_done_events(ev.data or {}):
                yield sapling_event_to_sse(extra_ev)
        yield sapling_event_to_sse(ev)


_STREAM_UNAVAILABLE = "The tutor is unavailable. Please retry."
_STREAM_INTERRUPTED = "The tutor was interrupted. Please retry."


def _stream_error(turn: _LoopTurn, message: str) -> SaplingEvent:
    """A terminal `error` event in services/chat_stream.py's shape; retryable, as
    a loop turn writes no graph or mastery rows before it completes."""
    return SaplingEvent(
        type="error",
        step="reply",
        message=message,
        data={"request_id": turn.request_id, "retryable": True},
    )


def _sse(turn: _LoopTurn) -> EventSourceResponse:
    return EventSourceResponse(
        _stream_turn(turn),
        headers={"X-Request-ID": turn.request_id, "Cache-Control": SSE_CACHE_CONTROL},
    )


async def _json_turn(make, what: str) -> dict:
    """Build the turn INSIDE the guardrail mapping (a read failure is a 502,
    like the legacy JSON routes) and run it; a paused turn becomes PKG-06b's
    429."""

    async def _turn() -> dict:
        return await _run_turn_json(make())

    try:
        return await _agent_turn_or_http_error(_turn(), what=what)
    except _BudgetPaused as paused:
        raise AIBudgetExceeded(paused.decision) from None


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/status")
def status(request: Request, user_id: str = Query(...), session_id: str = Query(...)) -> dict:
    _gate(user_id, request)
    pending = PENDING_SESSIONS.get(session_id)
    if pending is not None:
        if pending.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Session user mismatch")
        state: dict = {}
    else:
        try:
            _session_scope(session_id, user_id)
            state = _load_loop_state(session_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            state = {}  # no session yet: a fresh loop (never the gate's 404)
    active = state.get("current")
    entry = (state.get("steps") or {}).get(active) if active else None
    item = (
        get_check_item(entry["check_item_id"])
        if isinstance(entry, dict) and entry.get("check_item_id")
        else None
    )
    node_id = (_node_for_item(user_id, item) if item is not None else None) or state.get("concept")
    learner = _learner_state(user_id, node_id)
    band, p_known = _band_of(learner)
    step = _step_state(state, active if item is not None else None)
    prereq = _prereq_proficient(user_id, node_id) if node_id else True
    ceiling, _ = _ceiling_for(
        step=step,
        learner=_learner_view(learner, band=band, prereq_proficient=prereq),
        message="",
        independent_s=0.0,
    )
    return {
        "active": True,
        "session_id": session_id,
        "loop_phase": _loop_phase(state),  # PKG-08: probe | plan | teach (resume point)
        "phase": _phase_for(dict(state, current=active if item is not None else None)),
        "band": band,
        "ceiling": int(ceiling),
        "active_question_hash": active if item is not None else None,
        "items": len(state.get("steps") or {}),
        "rung": int(step.rung) if item is not None else None,
        "attempts": step.genuine_attempts if item is not None else 0,
    }


@router.post("/chat", dependencies=_RATE_LIMITED)
async def chat(body: ChatBody, request: Request):
    loop_on = _gate(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)
    _teaching_open(body.session_id, body.user_id)
    return await _json_turn(
        lambda: _LoopTurn(body=body, request=request, message=body.message, loop_on=loop_on),
        "loop chat agent",
    )


@router.post("/chat/stream", dependencies=_RATE_LIMITED)
async def chat_stream(body: ChatBody, request: Request):
    loop_on = _gate(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)
    _teaching_open(body.session_id, body.user_id)
    return _sse(_LoopTurn(body=body, request=request, message=body.message, loop_on=loop_on))


# ── The explicit-submission route (A16) ───────────────────────────────────


@dataclass
class _Submission:
    kind: str  # "feedback" | "hint_request" | "unavailable" | "refused"
    state: dict
    rendered: str  # the user row persisted for this submission
    scope: tuple[str, str]
    verdict: str | None = None
    refused: bool = False  # A33: refused, or the idk its CHECK_REFUSALS_AS_IDK-th refusal became


def _is_idk_phrase(text: str) -> bool:
    """A16's idk split, as HANDOFF-06 defines it: the submission routes to idk
    when gates.non_attempt_phrases (the A16 routing rule, which fails toward
    grading) returns a gates.IDK_PATTERNS phrase (A40 06(b): "idk", "i don't
    know", "no idea", "dunno") — so a hedged answer ("idk maybe 7") is graded,
    never turned into idk evidence."""
    return any(p in gates.IDK_PATTERNS for p in gates.non_attempt_phrases(text or ""))


def _render_submission(body: LoopCheckAnswerBody, *, idk: bool) -> str:
    if body.answer:
        return body.answer
    if body.option:
        return f"({body.option}) {body.reason}".strip()
    if idk:
        return _IDK_RENDERED
    return body.reason


def _record_attempt(entry: dict, now: float, *, failed: bool) -> None:
    """A genuine attempt: its time counts toward hint unlocking
    (`attempted_at`), and one that did not close the step correct is a failed
    genuine attempt (PKG-06's `attempts`, the ceiling's input)."""
    entry["attempted_at"] = [*(entry.get("attempted_at") or []), now]
    if failed:
        entry["attempts"] = int(entry.get("attempts") or 0) + 1


def _on_step(qh: str, change: Callable[[dict], None]) -> Callable[[dict], None]:
    """A compare-and-set mutate that applies `change` to the item's per-step
    entry in the FRESH document (nothing when the entry is gone)."""

    def mutate(state: dict) -> None:
        entry = _steps(state).get(qh)
        if isinstance(entry, dict):
            change(entry)

    return mutate


def _grading_open(entry: dict | None, now: float) -> bool:
    """The item still takes answers: never graded, and not left under a claim
    older than LOOP_GRADING_CLAIM_STALE_S (a crash mid-grade or a conflict
    after the flush — /check/next moves past it; it is never graded again)."""
    if not isinstance(entry, dict) or entry.get("graded_at") is not None:
        return False
    claimed_at = entry.get("grading_claim_at")
    return not (
        entry.get("grading_claim") and now - float(claimed_at or 0) > LOOP_GRADING_CLAIM_STALE_S
    )


def _claim_grading(session_id: str, qh: str, claim: str, now: float) -> None:
    """C2 (review round 3): grading is a CLAIM. One compare-and-set write sets
    `steps[qh].grading_claim` only when the item is ungraded and unclaimed;
    otherwise nothing is written and the submission is a 409. The claim is
    never re-taken: the grade, the ONE flush and its record all run under it,
    so a resubmission after the release, a double submit or a concurrent
    refusal can never grade (or flush) the item twice."""

    def take(state: dict) -> None:
        _refuse_while_closing(state, now)  # PKG-09: grading and closing exclude each other
        entry = _steps(state).get(qh)
        if not isinstance(entry, dict):
            raise HTTPException(status_code=404, detail="No such check item in this session")
        if entry.get("graded_at") is not None or entry.get("grading_claim"):
            raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
        entry["grading_claim"], entry["grading_claim_at"] = claim, now

    _update_loop_state(session_id, take)


def _under_claim(qh: str, claim: str, change: Callable[[dict], None], *, release: bool):
    """A mutate that applies `change` to the item's entry only while `claim`
    holds it, and — `release` — gives the claim up in the same write."""

    def mutate(state: dict) -> None:
        entry = _steps(state).get(qh)
        if not isinstance(entry, dict) or entry.get("grading_claim") != claim:
            return
        change(entry)
        if release:
            entry.pop("grading_claim", None)
            entry.pop("grading_claim_at", None)

    return mutate


async def _grade_submission(
    body: LoopCheckAnswerBody, request: Request, *, loop_on: bool
) -> _Submission:
    """The ONLY loop-chat evidence path (spec A16; invariant 26's allow-list):
    grade ONE explicit submission and persist its evidence with ONE
    flush_pending, before any feedback turn or stream starts — all under the
    item's grading claim (C2, `_claim_grading`): a graded item, or one another
    request is grading, is a 409 before anything is graded. A33: a guard
    refusal (checked BEFORE `unavailable`, which it also sets) is no credit, no
    evidence and never a genuine attempt; it is counted on the item under the
    claim, and the CHECK_REFUSALS_AS_IDK-th refusal of the same item is graded
    as idk. Every path that writes no evidence releases the claim; after the
    flush it is released only by the write that records the grade, so a lost
    record never admits a second flush."""
    scope = _session_scope(body.session_id, body.user_id)
    course_id = scope[1]
    state = _load_loop_state(body.session_id)
    _require_open(state)
    qh = body.question_hash
    entry = _steps(state).get(qh)
    if isinstance(entry, dict) and (
        entry.get("graded_at") is not None or entry.get("grading_claim")
    ):
        raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
    if not isinstance(entry, dict) or state.get("current") != qh:
        raise HTTPException(status_code=404, detail="No such check item in this session")
    item = get_check_item(entry["check_item_id"]) if entry.get("check_item_id") else None
    if item is None:  # A23 withdrawal: nothing is graded
        raise HTTPException(status_code=409, detail="check item withdrawn")
    text = body.answer or body.reason
    idk = body.idk or _is_idk_phrase(text)
    rendered = _render_submission(body, idk=idk)
    if not idk and gates.matches_non_attempt(text):
        return _Submission("hint_request", state, rendered, scope)  # never graded
    node_id = _node_for_item(body.user_id, item)
    if node_id is None:  # evidence needs the student's node for this concept (A2)
        raise HTTPException(status_code=409, detail="no graph node for this item")
    band, p_before = _band_for(body.user_id, node_id)
    now = _now_s()
    # hint-unlock bookkeeping only: the independent-time gate never blocks grading (A16)
    genuine = not idk and _genuine(text, _seconds_since(entry.get("first_shown_at"), now), band)
    deps = SaplingDeps(
        user_id=body.user_id,
        course_id=course_id or None,
        supabase=None,
        request_id=_request_id(request),
        session_id=body.session_id,
        feature="loop_check",
        learning_loop=loop_on,
    )
    rung = int(entry.get("rung") or 0)
    claim = str(uuid.uuid4())
    _claim_grading(body.session_id, qh, claim, now)
    flushed = False
    try:
        outcome = await grade_answer(
            _item_like(item),
            CheckAnswer(
                question_hash=qh,
                answer_text=body.answer,
                selected_option=body.option,
                reason=body.reason,
                idk=idk,
            ),
            deps=deps,
            node_id=node_id,
            max_rung=rung,
        )
        refused = bool(outcome.refused)
        if refused:  # A33, read BEFORE `unavailable`: not an outage, never a genuine attempt

            def count_refusal(e: dict) -> None:
                e["refusals"] = int(e.get("refusals") or 0) + 1
                if e["refusals"] < CHECK_REFUSALS_AS_IDK:
                    # nothing was graded: the claim goes with the count
                    e.pop("grading_claim", None)
                    e.pop("grading_claim_at", None)

            state = _update_loop_state(
                body.session_id, _under_claim(qh, claim, count_refusal, release=False)
            )
            if (_steps(state).get(qh) or {}).get("grading_claim") != claim:
                return _Submission("refused", state, rendered, scope, refused=True)
            # never a skip: the CHECK_REFUSALS_AS_IDK-th refusal is an idk observation (A1)
            idk, genuine = True, False
            outcome = await grade_answer(
                _item_like(item),
                CheckAnswer(question_hash=qh, idk=True),
                deps=deps,
                node_id=node_id,
                max_rung=rung,
            )
        if outcome.unavailable:  # invariant 28: nothing for either outcome; the item stays open

            def note_attempt(e: dict) -> None:
                if genuine:
                    _record_attempt(e, now, failed=True)

            state = _update_loop_state(
                body.session_id, _under_claim(qh, claim, note_attempt, release=True)
            )
            return _Submission("unavailable", state, rendered, scope, refused=refused)
        flushed = True
        flush_pending(deps, course_id or None)  # ONE call: the loop's only evidence write
    except BaseException:
        if not flushed:  # nothing was written: the student may submit again
            try:
                _update_loop_state(
                    body.session_id, _under_claim(qh, claim, lambda e: None, release=True)
                )
            except Exception:
                logger.warning("grading claim for %s not released", qh, exc_info=True)
        raise
    correct = bool(outcome.correct)
    verdict = "idk" if idk else ("correct" if correct else "not_yet")
    evidence = outcome.evidence or {}
    graded = {
        "graded_at": now,
        "last_correct": correct,
        "last_verdict": verdict,
        "max_rung": rung,
        "assisted": bool(evidence.get("assisted")),
        "node_id": node_id,
        "channel": evidence.get("channel"),
        "confidence": outcome.confidence,
        "grader_backend": outcome.grader_backend,
        "fsrs_rating": policy.evidence_for_rung(correct, Rung(rung)).fsrs_rating,
        "p_before": p_before,
        "feedback_given": False,
    }

    def record_grade(e: dict) -> None:
        if genuine:
            _record_attempt(e, now, failed=not correct)
        if e.get("graded_at") is None:
            e["first_attempt_correct"] = correct
        e["graded"] = int(e.get("graded") or 0) + 1
        e["wrong"] = int(e.get("wrong") or 0) + (0 if correct else 1)
        e.update(graded)

    # saved NOW: a failed feedback turn is recovered by _phase_for. An exhausted
    # conflict here is a 409 with the claim still held: the item is never
    # flushed again (it closes via /check/next once the claim is stale).
    state = _update_loop_state(body.session_id, _under_claim(qh, claim, record_grade, release=True))
    return _Submission("feedback", state, rendered, scope, verdict, refused=refused)


def _submission_turn(
    sub: _Submission, body: LoopCheckAnswerBody, request: Request, *, loop_on: bool
) -> _LoopTurn:
    chat_body = ChatBody(session_id=body.session_id, user_id=body.user_id, message=sub.rendered)
    return _LoopTurn(
        body=chat_body,
        request=request,
        message=sub.rendered,
        kind=sub.kind,
        state=sub.state,
        verdict=sub.verdict,
        scope=sub.scope,
        loop_on=loop_on,
        refused=sub.refused,
    )


@router.post("/check/answer", dependencies=_RATE_LIMITED)
async def check_answer(body: LoopCheckAnswerBody, request: Request):
    loop_on = _gate(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)
    sub = await _agent_turn_or_http_error(
        _grade_submission(body, request, loop_on=loop_on), what="loop grader"
    )
    return await _json_turn(
        lambda: _submission_turn(sub, body, request, loop_on=loop_on), "loop feedback agent"
    )


@router.post("/check/answer/stream", dependencies=_RATE_LIMITED)
async def check_answer_stream(body: LoopCheckAnswerBody, request: Request):
    loop_on = _gate(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)
    sub = await _agent_turn_or_http_error(
        _grade_submission(body, request, loop_on=loop_on), what="loop grader"
    )
    return _sse(_submission_turn(sub, body, request, loop_on=loop_on))


# ── Attempt / hint / action / openers / end-session ───────────────────────


def _addresses_grader(text: str, check) -> bool:
    """A33 / Behaviour 12: text the answer guard refuses is never an attempt.
    The screen reads the item's rubric ids and its own text (so "R1: yes" about
    the item's own resistor stays an attempt); the bare screen when the item
    is gone."""
    terms = answer_guard.item_terms(_item_like(check)) if check is not None else {}
    return answer_guard.screen(text, **terms).refusal is not None


def _attempt_hash(text: str) -> str:
    """A normalised digest of an attempt (lowercase alphanumeric words), so a
    repeat with other spacing or punctuation is the same attempt. The text
    itself is never stored."""
    words = " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))
    return hashlib.sha256(words.encode("utf-8")).hexdigest()[:16]


@router.post("/step/attempt", dependencies=_RATE_LIMITED)
def step_attempt(body: LoopAttemptBody, request: Request) -> dict:
    """Records a genuine attempt for hint unlocking only (spec §3.3). The text
    is judged by gates.is_genuine_attempt and the A33 screen, and never stored,
    never graded. M1 (review round 3): at most ONE attempt counts per rung
    anchor (since the last rung unlock, else the pose), and only one that
    differs from every earlier attempt on the item (`attempt_hashes`), so
    spamming the route cannot open the next rung; the route is rate-limited."""
    _gate(body.user_id, request)
    _session_scope(body.session_id, body.user_id)
    state = _load_loop_state(body.session_id)
    _require_open(state)
    qh = body.question_hash
    entry = _steps(state).get(qh)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail="No such check item in this session")
    check = get_check_item(entry["check_item_id"]) if entry.get("check_item_id") else None
    band, _ = _band_for(body.user_id, _node_for_item(body.user_id, check) if check else None)
    now = _now_s()
    independent_s = _seconds_since(entry.get("first_shown_at"), now)
    genuine = bool(_genuine(body.attempt_text, independent_s, band)) and not _addresses_grader(
        body.attempt_text, check
    )
    digest = _attempt_hash(body.attempt_text)
    counted: dict = {}

    def record(e: dict) -> None:
        counted.clear()
        anchor = (
            e.get("last_rung_at") if e.get("last_rung_at") is not None else e.get("first_shown_at")
        )
        if any(float(t) > float(anchor or 0) for t in e.get("attempted_at") or []):
            return  # this rung anchor already has its attempt
        if digest in (e.get("attempt_hashes") or []):
            return  # the same attempt again is no new work
        _record_attempt(e, now, failed=True)  # the step stays open: a failed genuine attempt
        e["attempt_hashes"] = [*(e.get("attempt_hashes") or []), digest]
        counted["yes"] = True

    if genuine:
        state = _update_loop_state(body.session_id, _on_step(qh, record))
        entry = _steps(state).get(qh) or entry
    return {
        "genuine": genuine,
        "counted": bool(counted),
        "attempts": len(entry.get("attempted_at") or []),
        "independent_s": independent_s,
    }


@router.post("/hint")
def hint(body: LoopHintBody, request: Request) -> dict:
    """Moves the active item's rung up one, behind the dwell / attempt gate, the
    ceiling and — at H6 — the item predicates (A32). The hint TEXT is the next
    `[ACTION: hint]` turn's (PKG-13), deterministic when a leak-clean payload
    exists. No model call."""
    _gate(body.user_id, request)
    _session_scope(body.session_id, body.user_id)
    state = _load_loop_state(body.session_id)
    _require_teaching(state)
    qh = body.question_hash
    entry = _steps(state).get(qh)
    if not isinstance(entry, dict) or state.get("current") != qh:
        return {"denied": "no_active_item"}
    step = _step_state(state, qh)
    now = _now_s()
    if not gates.rung_unlock(step, now, time_scale=config.LEARNING_GATE_TIME_SCALE):
        anchor = step.last_rung_at if step.last_rung_at is not None else step.first_shown_at
        attempted = any(t > anchor for t in step.attempted_at)
        return {"denied": "dwell" if attempted else "no_genuine_attempt"}
    check = get_check_item(entry["check_item_id"]) if entry.get("check_item_id") else None
    node_id = _node_for_item(body.user_id, check) if check else None
    learner = _learner_state(body.user_id, node_id)
    band, _ = _band_of(learner)
    prereq = _prereq_proficient(body.user_id, node_id) if node_id else True
    # an empty message: showed_work comes from the step alone — the floor-at-H3 rule
    # is applied by the turn that carried the work, never by a hint request
    ceiling, _ = _ceiling_for(
        step=step,
        learner=_learner_view(learner, band=band, prereq_proficient=prereq),
        message="",
        independent_s=0.0,
    )
    next_rung = int(step.rung) + 1
    if next_rung > int(ceiling):
        return {"denied": "ceiling"}
    if next_rung == int(Rung.H6) and not _h6_ok(state, qh, entry, check):
        return {"denied": "h6_gate"}
    accepted: dict = {}

    def unlock(e: dict) -> None:
        accepted.clear()
        if int(e.get("rung") or 0) >= next_rung:
            return  # a concurrent request already moved it this far
        e["rung"], e["last_rung_at"] = next_rung, now
        e["rungs"] = [*(e.get("rungs") or []), {"rung": next_rung, "at": now}]
        if e.get("offered"):
            e["offered"] = False
            accepted["offer"] = True

    _update_loop_state(body.session_id, _on_step(qh, unlock))
    if accepted.get("offer"):
        zpd_events.emit_zpd_offer(
            user_id=body.user_id, request_id=_request_id(request), accepted=True, band=band
        )
    return {"rung": next_rung, "intent": ladder.intent(Rung(next_rung))}


@router.post("/action", dependencies=_RATE_LIMITED)
async def action(body: ActionBody, request: Request):
    """An "[ACTION: ...]" turn: in the check phase a hint at the item's current
    rung, otherwise the current phase. Assistant-only persistence; never graded
    (invariant 26)."""
    loop_on = _gate(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)
    _teaching_open(body.session_id, body.user_id)
    message = f"[ACTION: {_ACTION_PROMPTS.get(body.action_type, '')}]"
    chat_body = ChatBody(
        session_id=body.session_id,
        user_id=body.user_id,
        message=message,
        mode=body.mode,
        use_shared_context=body.use_shared_context,
    )
    return await _json_turn(
        lambda: _LoopTurn(
            body=chat_body,
            request=request,
            message=message,
            kind="action",
            persist_user_row=False,
            loop_on=loop_on,
        ),
        "loop action agent",
    )


@router.post("/start-session", dependencies=_RATE_LIMITED)
async def start_session(body: StartSessionBody, request: Request):
    loop_on = _gate(body.user_id, request)
    result = await _json_turn(
        lambda: _LoopOpener(body=body, request=request, loop_on=loop_on),
        "loop start-session agent",
    )
    out = {
        "session_id": result["session_id"],
        "initial_message": result["reply"],
        "graph_state": result["graph_state"],
    }
    if result.get("budget"):
        out["budget"] = result["budget"]
    return out


@router.post("/start-session/stream", dependencies=_RATE_LIMITED)
async def start_session_stream(body: StartSessionBody, request: Request):
    loop_on = _gate(body.user_id, request)
    return _sse(_LoopOpener(body=body, request=request, loop_on=loop_on))


@router.post("/check/next")
def check_next(body: LoopCheckNextBody, request: Request) -> dict:
    """ "Check me" (spec §9, A27): the current concept's next check item and its
    pose. No model call, so no rate limit and no invariant-23 run site; the
    budget is read only for the novice pause (§3.5): a novice-band concept is
    not activated at the hard level. The activation is tried on a read copy
    first (the budget read is not a mutate's business), then applied to the
    fresh document by one compare-and-set write."""
    _gate(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)
    _, course_id = _session_scope(body.session_id, body.user_id)
    state = _load_loop_state(body.session_id)
    _require_teaching(state)
    active = state.get("current")
    entry = (state.get("steps") or {}).get(active) if active else None
    now = _now_s()
    if _grading_open(entry, now):
        item = get_check_item(entry["check_item_id"]) if entry.get("check_item_id") else None
        if item is not None:
            return {"phase": "check", "check": _pose_payload(item)}  # idempotent

    def activate(st: dict, out: dict) -> None:
        out.clear()
        cur = st.get("current")
        cur_entry = (st.get("steps") or {}).get(cur) if cur else None
        if _grading_open(cur_entry, now):
            if cur_entry.get("check_item_id") and get_check_item(cur_entry["check_item_id"]):
                out["qh"] = cur  # another request activated one meanwhile
                return
        if cur:
            # withdrawn (A23), graded, or left under a stale claim (C2): drop it; the entry stays
            st["current"] = None
        out["qh"] = _activate_next_item(body.user_id, course_id, st, now=now)

    trial: dict = {}
    activate(state, trial)
    if trial.get("qh") is not None:
        band, _ = _band_for(body.user_id, state["steps"][trial["qh"]]["node_id"])
        if band == "novice":
            decision = ai_budget.check(
                body.user_id,
                "tutor",
                "novice",
                session_tutor_requests=int(state.get("tutor_requests") or 0),
                session_deep_requests=int(state.get("deep_requests") or 0),
                arm_session=False,
            )
            if decision.pause_novice:
                raise AIBudgetExceeded(decision)  # nothing activated, nothing saved
    out: dict = {}
    saved = _update_loop_state(body.session_id, lambda st: activate(st, out))
    qh = out.get("qh")
    if qh is None:  # the cursor may have moved
        plan = saved.get("plan") if isinstance(saved.get("plan"), dict) else {}
        return {"phase": "teach", "plan_done": bool(plan.get("done")), "check": None}
    item = get_check_item(saved["steps"][qh]["check_item_id"])
    pose = _pose_payload(item)
    save_message(body.session_id, "assistant", pose["prompt"])
    return {"phase": "check", "check": pose}


# ── The session close (PKG-09; spec §4, §6, §9, §13 A11/A19/A20/A25) ────────
#
# One close per session, stored encrypted on `sessions.close_json` with the
# phase it stopped in (`close_phase`); `loop_state["phase"]` becomes "close".
# A close is claimed first (`close_claim` in loop_state, compare-and-set) so two
# concurrent closes never both run the model; a stored close is returned as is.

_CLOSE_IN_PROGRESS = "session close in progress"
_CLOSE_STORE_FAILED = "Could not store the session close."
_GRADING_IN_FLIGHT = "a check is being graded; close again in a moment"


def _live(entry: dict, key: str, now: float) -> bool:
    """`entry[key]` is a claim younger than LOOP_GRADING_CLAIM_STALE_S."""
    return bool(entry.get(key)) and now - float(entry.get(f"{key}_at") or 0) <= (
        LOOP_GRADING_CLAIM_STALE_S
    )


def _grading_in_flight(doc: dict, now: float) -> bool:
    """A check or probe item is being graded under a live claim (A52/A55c): its
    evidence is not written yet, so a close now would miss it."""
    entries = [e for e in (doc.get("steps") or {}).values() if isinstance(e, dict)]
    probe = doc.get("probe") if isinstance(doc.get("probe"), dict) else {}
    if isinstance(probe.get("current"), dict):
        entries.append(probe["current"])
    return any(_live(e, "grading_claim", now) for e in entries)


def _refuse_while_closing(doc: dict, now: float) -> None:
    """Grading and closing exclude each other on the session document: a
    grading claim is refused while the session is closed or a live close claim
    holds it (the close refuses a live grading claim, `_claim_close`)."""
    if _loop_phase(doc) == "close":
        raise HTTPException(status_code=409, detail=_SESSION_CLOSED)
    if _live(doc, "close_claim", now):
        raise HTTPException(status_code=409, detail=_CLOSE_IN_PROGRESS)


def _close_phase(doc: dict | None) -> str:
    """Where the session stopped (spec §9): PKG-08's probe/plan, or — once
    teaching — PKG-07's teach / check / feedback for the active item; a
    session with no loop state at all closes as `close`."""
    if not doc:
        return "close"
    phase = _loop_phase(doc)
    if phase == "teach":
        phase = _phase_for(doc)
    return phase if phase in CLOSE_PHASES else "close"


def _unreleased_items(doc: dict | None) -> list:
    """The items the session posed (PKG-07's steps) whose answer the student
    has not been shown: never graded and not revealed by a hint payload. The
    probe's items never reach the transcript, so the close cannot see them."""
    if not doc:
        return []
    revealed = set(doc.get("revealed") or [])
    out = []
    for qh, entry in (doc.get("steps") or {}).items():
        if not isinstance(entry, dict) or qh in revealed or entry.get("graded_at") is not None:
            continue
        if entry.get("check_item_id"):
            item = get_check_item(entry["check_item_id"])
            if item is not None:
                out.append(item)
    return out


def _close_misconception_keys(user_id: str, session_id: str) -> list[str]:
    """PKG-10 repoints this at the session's matched wrong keys. Empty until then."""
    return []


def _stored_close(row: dict) -> dict:
    record = decrypt_json_column(row.get("close_json")) or {}
    return {
        "close": record,
        "model_written": bool(record.get("model_written")),
        "close_phase": row.get("close_phase"),
    }


class _AlreadyClosed(Exception):
    """The document says `phase: close`: another close finished first."""


def _claim_close(session_id: str, claim: str, now: float) -> dict:
    """Take the session's close claim by compare-and-set (A38 06(q)); 409 while
    another close holds a live one, or while a check is being graded (its
    evidence is not written yet); `_AlreadyClosed` when a close already
    finished. Returns the document as claimed (claim keys stripped), so the
    phase and the unreleased items are read from the same state the claim saw."""
    out: dict = {}

    def take(doc: dict) -> None:
        if _loop_phase(doc) == "close":
            raise _AlreadyClosed()
        if doc.get("close_claim") != claim and _live(doc, "close_claim", now):
            raise HTTPException(status_code=409, detail=_CLOSE_IN_PROGRESS)
        if _grading_in_flight(doc, now):
            raise HTTPException(status_code=409, detail=_GRADING_IN_FLIGHT)
        out["doc"] = copy.deepcopy(
            {k: v for k, v in doc.items() if k not in ("close_claim", "close_claim_at")}
        )
        doc["close_claim"], doc["close_claim_at"] = claim, now

    _update_loop_state(session_id, take)
    return out.get("doc", {})


def _finish_close(session_id: str, claim: str, *, closed: bool) -> None:
    """Release the claim; a stored close also moves the phase to `close`.
    Best effort after the store: `close_json` is the record of truth."""

    def finish(doc: dict) -> None:
        if doc.get("close_claim") == claim:
            doc.pop("close_claim", None)
            doc.pop("close_claim_at", None)
        if closed:
            doc["phase"] = "close"

    try:
        _update_loop_state(session_id, finish)
    except Exception as exc:
        logger.warning("session close: loop state not updated (%s)", type(exc).__name__)


def _session_record(session_id: str) -> tuple[list[dict], list[dict]]:
    """The decrypted transcript and this session's evidence journal rows."""
    msgs = table("messages").select(
        "role,content", filters={"session_id": f"eq.{session_id}"}, order="created_at.asc"
    )
    transcript = [
        {"role": m.get("role"), "content": decrypt_if_present(m.get("content"))}
        for m in msgs or []
    ]
    evidence = table("node_mastery_events").select(
        "node_id,p_before,p_after,correct,channel",
        filters={"session_id": f"eq.{session_id}", "event_type": "eq.evidence"},
        order="created_at.asc,evidence_seq.asc",
    )
    return transcript, list(evidence or [])


def _concept_names(user_id: str, node_ids: list[str]) -> dict[str, str]:
    ids = list(dict.fromkeys(n for n in node_ids if n))
    if not ids:
        return {}
    rows = table("graph_nodes").select(
        "id,concept_name", filters={"user_id": f"eq.{user_id}", "id": f"in.({','.join(ids)})"}
    )
    return {r["id"]: r["concept_name"] for r in rows or [] if r.get("id") and r.get("concept_name")}


def _close_text(record: CloseRecord) -> str:
    return "\n".join((record.summary, record.self_eval, record.if_then))


def _served_fallback(draft, items: list) -> CloseRecord:
    """The deterministic close as served (review MINOR 3): it prints concept
    names and numbers, so it passes the same leak check as a model close —
    named, then with the names withheld, then with no names or numbers."""
    record = fallback_close(draft)
    named_ok = not any(
        _name_in_answer(draft.concept_names.get(c.node_id, ""), i)
        for c in draft.concepts
        for i in items
    )
    for detail in CLOSE_FALLBACK_DETAILS:
        record = fallback_close(draft, detail=detail)
        if detail == "named" and not named_ok:
            continue
        if not any(close_states_answer(_close_text(record), i) for i in items):
            return record
    return record


_WORD = re.compile(r"[^\W_]+")


def _name_in_answer(name: str, item) -> bool:
    """Review round 2: a concept name whose words all appear in an unreleased
    item's final (or canonical) answer states it ("Base Case" for "a base
    case") — the bare name is no sentence the text check reads as an answer."""
    words = set(_WORD.findall((name or "").casefold()))
    answer = " ".join(filter(None, (item.final_answer, item.canonical_answer))).casefold()
    return bool(words) and words <= set(_WORD.findall(answer))


async def _model_close(draft, *, user_id: str, request_id: str) -> object | None:
    """One close run under CLOSE_RUN_TIMEOUT_S (a timed-out run is the
    unavailable agent: the deterministic close is stored)."""
    try:
        return await asyncio.wait_for(
            run_session_close(draft, user_id=user_id, request_id=request_id),
            CLOSE_RUN_TIMEOUT_S,
        )
    except TimeoutError:
        logger.warning("session_close timed out; storing fallback close")
        return None


def _reread_close(session_id: str) -> dict:
    rows = table("sessions").select(
        "id,close_json,close_phase", filters={"id": f"eq.{session_id}", **NOT_REVIEW}, limit=1
    )
    if rows and rows[0].get("close_json") is not None:
        return _stored_close(rows[0])
    raise HTTPException(status_code=409, detail=_CLOSE_IN_PROGRESS)


async def close_session(
    session_id: str,
    user_id: str,
    *,
    request_id: str | None = None,
    rate_limit: str | None = None,
) -> dict:
    """Close a loop session (Behaviour 10). A pending (never-materialised)
    session has no transcript or evidence: its deterministic close is stored
    on the row the A11 helper creates, and its phase set to `close`. A
    materialised one is claimed, read, closed — the model only when it has
    evidence (A25; `run_session_close` itself returns None at the hard budget
    level), under CLOSE_RUN_TIMEOUT_S and past the inline A20 check
    (`rate_limit="raise"`: the 429; `"fallback"`: the deterministic close) —
    then stored ONCE (the write is conditional on `close_json IS NULL`), the
    phase moved to `close`, and `learn.session_closed` emitted. A close that
    finds the session already closed returns the stored close: no model call,
    no write, no event."""
    request_id = request_id or current_request_id() or str(uuid.uuid4())
    pending = PENDING_SESSIONS.get(session_id)
    claim = ""
    if pending is not None:
        if pending.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Session user mismatch")
        PENDING_SESSIONS.pop(session_id, None)
        phase = "close"
        record = fallback_close(build_close([], [], [], {}))
        row_defaults = {
            "mode": pending.get("mode"),
            "topic": pending.get("topic"),
            "offering_id": pending.get("offering_id"),
        }
    else:
        rows = table("sessions").select(
            "id,user_id,loop_state,close_json,close_phase",
            # PKG-12: a review session is not a tutor session — never closed (404)
            filters={"id": f"eq.{session_id}", **NOT_REVIEW},
            limit=1,
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Session not found")
        if rows[0].get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Session user mismatch")
        if rows[0].get("close_json") is not None:
            return _stored_close(rows[0])
        had_state = bool(rows[0].get("loop_state"))
        claim = uuid.uuid4().hex
        try:
            doc = _claim_close(session_id, claim, _now_s())
        except _AlreadyClosed:
            return _reread_close(session_id)
        phase = _close_phase(doc) if had_state else "close"
        row_defaults = None
        try:
            transcript, evidence = _session_record(session_id)
            draft = build_close(
                transcript,
                evidence,
                _close_misconception_keys(user_id, session_id),
                {},
                concept_names=_concept_names(user_id, [e.get("node_id") for e in evidence]),
            )
            items = _unreleased_items(doc)
            out = None
            if evidence:  # A25: no model without graded evidence
                limited = False
                if rate_limit:
                    try:
                        ai_budget.enforce_rate_limit_for(user_id)  # A20 inline: a model may run
                    except AIBudgetExceeded:
                        if rate_limit == "raise":
                            raise
                        limited = True
                if not limited:
                    out = await _model_close(draft, user_id=user_id, request_id=request_id)
            record = (
                served_close(out, draft, items)
                if out is not None
                else _served_fallback(draft, items)
            )
        except BaseException:
            _finish_close(session_id, claim, closed=False)
            raise
    try:
        stored = store_close(session_id, user_id, record, phase, row_defaults=row_defaults)
    except Exception as exc:
        if claim:
            _finish_close(session_id, claim, closed=False)
        logger.warning("session close not stored (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail=_CLOSE_STORE_FAILED) from None
    _finish_close(session_id, claim, closed=True)  # a pending session's phase too
    if not stored:  # another close's write landed first: serve it, emit nothing
        return _reread_close(session_id)
    events_service.log_event(
        "learn.session_closed",
        category="usage",
        user_id=user_id,
        request_id=request_id,
        payload={
            "session_id": session_id,
            "concepts": len(record.concepts),
            "misconceptions": len(record.misconceptions),
            "has_if_then": bool(record.if_then),
            "model_written": record.model_written,
        },
    )
    return {"close": record.model_dump(), "model_written": record.model_written, "close_phase": phase}


@router.post("/close")
async def close(body: CloseBody, request: Request) -> dict:
    """POST /api/learn/loop/close (spec §9): require_self + the gate's 404; the
    A20 rate limit is checked inline, only when this close would run the model
    (spec §9: "inline where only some bodies run one"), so a gate-off student
    gets the 404 and a zero-evidence close always works."""
    if not body.user_id:
        body.user_id = get_session_user_id(request)
    _gate(body.user_id, request)
    return await close_session(
        body.session_id, body.user_id, request_id=_request_id(request), rate_limit="raise"
    )


def end_session(body: EndSessionBody, request: Request) -> None:
    """The legacy end_session's loop delegate (PKG-07's pass-through, filled by
    PKG-09): a materialised session with loop state gets its real close first
    (A20 inline check: rate-limited, the deterministic close; the run bounded by
    CLOSE_RUN_TIMEOUT_S; a check still being graded → no close, WARNING);
    the legacy body then runs unchanged (ended_at, XP, the `summary_json`
    `flashcards._get_session_summary` reads, achievements). A pending session
    keeps the legacy early return. A close failure never fails the legacy end.
    The legacy handler is sync (a worker thread), so the async close runs
    through the sanctioned `run_agent_sync` seam. Always returns None."""
    if body.session_id in PENDING_SESSIONS:
        return None
    try:
        rows = table("sessions").select(
            "loop_state", filters={"id": f"eq.{body.session_id}", **NOT_REVIEW}, limit=1
        )
        if rows and rows[0].get("loop_state"):
            run_agent_sync(
                close_session(
                    body.session_id,
                    body.user_id,
                    request_id=_request_id(request),
                    rate_limit="fallback",  # A20 inline: rate-limited → the deterministic close
                )
            )
    except Exception as exc:
        # e.g. a check still being graded (409): the session ends without a close;
        # the student can still POST /close later (close_json stays null)
        logger.warning(
            "loop session ended without a close (%s); the legacy end continues",
            type(exc).__name__,
        )
    return None


# ── Probe and plan (PKG-08; spec §3.3 probe row, §3.4, §9; A16, A20, A23, A27, A33, A34) ──
#
# The session document's top-level `phase` is PKG-08's: `probe` → `plan` →
# `teach` (a missing key reads `probe`, unless the plan is already approved).
# The probe lives under `probe` = {skills, history, current, unavailable,
# refusals} and the plan under `plan` = {proposed, proposed_kinds, approved,
# cursor} plus PKG-07's `concept`/`teach_turns`/`concept_checks`. Nothing here
# writes PKG-07's top-level `current` or `steps` (only `_activate_next_item`
# sets `current`, A27). No handler here reads the tutor budget or counts a tutor
# call (A20: the probe runs at every budget level; the grader's own cap lives
# inside grade(), PKG-06b) — `/probe/answer`, the one route that can run a
# model, carries the rate limit.

#: A /probe/answer whose question_hash is not the posed item's (stale client,
#: or the item was answered or moved past meanwhile).
_PROBE_NOT_POSED = "not the posed probe item"


@dataclass(frozen=True)
class _BoundItem:
    """A course check item bound to the student's graph node (A2: stored items
    key on concept_key, never node_id). Satisfies `learning.probe.ProbeItem`;
    every other attribute is the item's own. `item` is what grade_answer takes."""

    item: CheckItem
    node_id: str

    def __getattr__(self, name: str):
        return getattr(self.item, name)


def _require_phase(doc: dict, phase: str) -> None:
    current = _loop_phase(doc)
    if current != phase:
        raise HTTPException(status_code=409, detail=f"phase is {current}")


def _probe_doc(doc: dict) -> dict:
    """The document's `probe` object with every list/map present (in place)."""
    pr = doc.get("probe")
    if not isinstance(pr, dict):
        pr = doc["probe"] = {}
    pr.setdefault("history", [])
    pr.setdefault("unavailable", [])
    pr.setdefault("refusals", {})
    pr.setdefault("current", None)
    return pr


def _plan_states(user_id: str, course_id: str) -> dict[str, float]:
    """Decayed p_known for every graph node of (user, course) — one
    `graph_nodes` read, one `learner_state` read (PKG-03); BKT_L0 for a node
    with no learner_state row."""
    rows = (
        table("graph_nodes").select(
            "id", filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"}
        )
        or []
    )
    ids = [r["id"] for r in rows if r.get("id")]
    states = read_states(user_id, ids)
    return {n: (states[n].p_known if n in states else BKT_L0) for n in ids}


def _plan_prereq_edges(user_id: str, node_ids: list[str]) -> list[tuple[str, str]]:
    """The user's prerequisite edges among `node_ids`, oriented (prerequisite,
    dependent) by EDGE_PREREQ_SOURCE_IS_PREREQ — the direction PKG-03's
    propagation and PKG-07's `_prereq_proficient` read. One `graph_edges` read."""
    rows = (
        table("graph_edges").select(
            "source_node_id,target_node_id",
            filters={
                "user_id": f"eq.{user_id}",
                "relationship_type": f"eq.{PREREQ_RELATIONSHIP_TYPE}",
            },
        )
        or []
    )
    keep = set(node_ids)
    out = []
    for e in rows:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src in keep and tgt in keep:
            out.append((src, tgt) if EDGE_PREREQ_SOURCE_IS_PREREQ else (tgt, src))
    return out


def _probe_course_has_items(course_id: str) -> bool:
    """A23: one `limit=1` read; False for a session with no course."""
    return bool(course_id) and course_has_items(course_id)


def _probe_items(user_id: str, course_id: str, node_ids: list[str]) -> list[_BoundItem]:
    """PKG-08's node → concept_key → items resolver (A2; the inverse of PKG-07's
    `_node_for_item`): one `graph_nodes` read for the nodes' names, one
    `check_items` read for their normalised keys, each item bound to the node.
    Unfiltered — the handlers drop the reserve, unavailable, revealed and
    unservable items (they must still COUNT an asked one)."""
    if not node_ids:
        return []
    rows = (
        table("graph_nodes").select(
            "id,concept_name",
            filters={
                "user_id": f"eq.{user_id}",
                "course_id": f"eq.{course_id}",
                "id": f"in.({','.join(sorted(set(node_ids)))})",
            },
        )
        or []
    )
    node_for_key: dict[str, str] = {}
    for row in sorted(rows, key=lambda r: r.get("id") or ""):
        key = _normalize_concept(row.get("concept_name") or "")
        if key and row.get("id"):
            node_for_key.setdefault(key, row["id"])  # one node per concept key
    by_key = items_for_concepts(course_id, list(node_for_key))
    return [
        _BoundItem(item, node_for_key[key])
        for key, items in by_key.items()
        if key in node_for_key
        for item in items
    ]


def _plan_node_names(user_id: str, node_ids: list[str]) -> dict[str, str]:
    """id → concept_name for the student's nodes (one `graph_nodes` read)."""
    if not node_ids:
        return {}
    rows = (
        table("graph_nodes").select(
            "id,concept_name",
            filters={"user_id": f"eq.{user_id}", "id": f"in.({','.join(sorted(set(node_ids)))})"},
        )
        or []
    )
    return {r["id"]: r.get("concept_name") or "" for r in rows if r.get("id")}


def _plan_due_reviews(
    user_id: str, node_ids: list[str], *, now: datetime | None = None
) -> list[str]:
    """The plan's review section: nodes whose FSRS review is due now
    (`fsrs_due_at ≤ now`; never reviewed = not due), in PKG-02's `order_due`
    order, capped by `budget_select` (REVIEW_DAILY_BUDGET_MIN /
    REVIEW_SECONDS_PER_CHECK). One `learner_state` read."""
    now = now or datetime.now(timezone.utc)
    due = [
        {"node_id": n, "fsrs_s": st.fsrs_s, "fsrs_last_review_at": st.fsrs_last_review_at}
        for n, st in read_states(user_id, node_ids, now=now).items()
        if st.fsrs_due_at is not None and st.fsrs_due_at <= now
    ]
    ordered = order_due(sorted(due, key=lambda r: r["node_id"]), now)
    return [
        r["node_id"]
        for r in budget_select(ordered, REVIEW_DAILY_BUDGET_MIN, REVIEW_SECONDS_PER_CHECK)
    ]


def _probe_done_payload(pr: dict) -> dict:
    """learn.probe_done (spec §6): ids and counts only."""
    history = list(pr.get("history") or [])
    return {
        "items": len(history),
        "misses": sum(1 for h in history if not h.get("correct")),
        "novice_floor": probe_policy.novice_floor(history),
        "skills": list(pr.get("skills") or []),
    }


def _emit_probe_done(saved: dict, user_id: str, request_id: str) -> None:
    events_service.log_event(
        "learn.probe_done",
        category="usage",
        user_id=user_id,
        request_id=request_id,
        payload=_probe_done_payload(_probe_doc(dict(saved))),
    )


def _probe_plan_read_limit(user_id: str) -> None:
    """A cheap per-user limit on the two no-model routes that write loop state
    (/probe/next, GET /plan): services/request_limits' in-process sliding
    window, PROBE_PLAN_READS_PER_MIN a minute. Runs after the gate. No model
    runs behind these routes, so this is not the A20 rate limit (llm_usage)."""
    retry = check_rate_limit(
        f"loop_probe_plan:{user_id}", limit=PROBE_PLAN_READS_PER_MIN, window_sec=60
    )
    if retry is not None:
        raise HTTPException(
            status_code=429, detail="too many requests", headers={"Retry-After": str(retry)}
        )


def _update_if_changed(session_id: str, doc: dict, mutate: Callable[[dict], None]) -> dict:
    """`_update_loop_state`, skipped when `mutate` leaves the document as read
    unchanged (a re-served item, a re-GET of the same plan): the mutate runs on a
    copy first; only a real change costs a compare-and-set write."""
    trial = copy.deepcopy(doc)
    mutate(trial)
    if trial == doc:
        return trial
    return _update_loop_state(session_id, mutate)


def _claim_live(current: dict, now: float) -> bool:
    claimed_at = current.get("grading_claim_at")
    return bool(current.get("grading_claim")) and (
        now - float(claimed_at or 0) <= LOOP_GRADING_CLAIM_STALE_S
    )


@router.post("/probe/next")
def probe_next(body: ProbeNextBody, request: Request) -> dict:
    """The next probe item (Behaviour 10): no model call (so no A20 rate limit;
    the cheap per-user read limit instead). The
    skill set is fixed on the first call — the outer fringe of the course graph,
    capped at PROBE_MAX_SKILLS — or, for a course with no check items, the probe
    ends at once (`no_check_items`, A23/A26). A posed item is served again until
    it is answered (never a skip); one left under a stale grading claim is
    moved past. Selection never serves a concept's post-test reserve (A23), an
    item whose answer this student has been shown (`revealed_hashes`), one the
    grader could not grade (`unavailable`), or one with no final answer (A34);
    an item the student already has evidence on (`seen_hashes`) only when no
    unseen one is left (review's A23 fallback). Asked items always count toward
    the per-skill cap, by the recorded observations."""
    _gate(body.user_id, request)
    _probe_plan_read_limit(body.user_id)
    _consume_pending(body.session_id, body.user_id)
    _, course_id = _session_scope(body.session_id, body.user_id)
    state = _load_loop_state(body.session_id)
    _require_phase(state, "probe")
    request_id = _request_id(request)
    fixed = (
        (state.get("probe") or {}).get("skills") if isinstance(state.get("probe"), dict) else None
    )
    if fixed is None and not _probe_course_has_items(course_id):

        def finish_empty(doc: dict) -> None:
            _require_phase(doc, "probe")
            pr = _probe_doc(doc)
            pr["skills"] = []
            pr["current"] = None
            doc["phase"] = "plan"

        saved = _update_loop_state(body.session_id, finish_empty)
        _emit_probe_done(saved, body.user_id, request_id)
        return {"done": True, "phase": "plan", "no_check_items": True}

    states = _plan_states(body.user_id, course_id)
    if fixed is None:
        edges = _plan_prereq_edges(body.user_id, list(states))
        skills = planner.outer_fringe(states, edges)[:PROBE_MAX_SKILLS]
    else:
        skills = [s for s in fixed if isinstance(s, str)]
    items = _probe_items(body.user_id, course_id, skills)
    revealed = revealed_hashes(body.user_id) if items else set()
    seen = seen_hashes(body.user_id) if items else set()
    reserves = {
        posttest_reserve_hash([it for it in items if it.node_id == n])
        for n in {it.node_id for it in items}
    } - {None}
    by_hash = {it.question_hash: it for it in items}
    now = _now_s()
    out: dict = {}

    def select(doc: dict) -> None:
        out.clear()
        _require_phase(doc, "probe")
        doc["phase"] = "probe"  # explicit from the first item on
        pr = _probe_doc(doc)
        if pr.get("skills") is None:
            pr["skills"] = list(skills)
        cur = pr.get("current")
        if isinstance(cur, dict) and cur.get("question_hash"):
            qh = cur["question_hash"]
            if (not cur.get("grading_claim") or _claim_live(cur, now)) and qh in by_hash:
                out["item"] = by_hash[qh]  # posed and not answered: the same item again
                return
            # withdrawn (A23) or left under a stale claim (C2): never asked again
            if qh not in pr["unavailable"]:
                pr["unavailable"].append(qh)
            pr["current"] = None
        asked = {h.get("question_hash") for h in pr["history"]}
        per_node = Counter(h.get("node_id") for h in pr["history"])
        skill_states = {n: states.get(n, BKT_L0) for n in pr["skills"]}

        def pick(extra_never: set[str]):
            never = (reserves | revealed | set(pr["unavailable"]) | extra_never) - asked
            candidates = [
                it
                for it in items
                if it.question_hash in asked or (it.question_hash not in never and is_servable(it))
            ]
            return probe_policy.next_probe_item(
                skill_states,
                candidates,
                asked,
                channel_for_format=CHANNEL_FOR_FORMAT,
                asked_per_node=per_node,
            )

        item = pick(seen) or pick(set())  # seen items only when nothing unseen is left
        if item is None:
            doc["phase"] = "plan"
            out["done"] = True
            return
        pr["current"] = {
            "check_item_id": item.id,
            "question_hash": item.question_hash,
            "node_id": item.node_id,
            "difficulty": item.difficulty,
            "channel": CHANNEL_FOR_FORMAT[item.format],
        }
        out["item"] = item

    saved = _update_if_changed(body.session_id, state, select)
    if out.get("done"):
        _emit_probe_done(saved, body.user_id, request_id)
        return {"done": True, "phase": "plan"}
    item = out["item"]
    pose = _pose_payload(item)  # prompt + letter/text options only (A22), never the key
    return {
        "done": False,
        "check_item_id": item.id,
        "question_hash": pose["question_hash"],
        "node_id": item.node_id,
        "format": pose["format"],
        "difficulty": pose["difficulty"],
        "prompt": pose["prompt"],
        "options": pose["options"],
    }


def _on_posed(qh: str, change: Callable[[dict, dict], None]) -> Callable[[dict], None]:
    """A compare-and-set mutate over the probe's posed item `qh`: `change(pr,
    current)` runs only while `qh` is still the posed item."""

    def mutate(doc: dict) -> None:
        pr = _probe_doc(doc)
        cur = pr.get("current")
        if isinstance(cur, dict) and cur.get("question_hash") == qh:
            change(pr, cur)

    return mutate


def _under_probe_claim(
    qh: str, claim: str, change: Callable[[dict, dict], None]
) -> Callable[[dict], None]:
    """`_on_posed`, applied only while `claim` holds the item (PKG-07's
    `_under_claim` for the probe's posed item)."""

    def guarded(pr: dict, cur: dict) -> None:
        if cur.get("grading_claim") == claim:
            change(pr, cur)

    return _on_posed(qh, guarded)


def _release(_pr: dict, cur: dict) -> None:
    cur.pop("grading_claim", None)
    cur.pop("grading_claim_at", None)


def _not_asked(pr: dict, cur: dict) -> None:
    """Invariant 28 / Behaviour 11: the item counts as not asked — excluded from
    selection, never counted toward a cap; the next /probe/next serves another."""
    if cur["question_hash"] not in pr["unavailable"]:
        pr["unavailable"].append(cur["question_hash"])
    pr["current"] = None


async def _probe_submission(body: ProbeAnswerBody, request: Request, *, loop_on: bool) -> dict:
    """Grade ONE explicit probe answer (A16) and persist its evidence with ONE
    flush_pending — invariant 26's probe writer. Grading is a CLAIM on the posed
    item (PKG-07's C2 discipline, A52): taken by compare-and-set before
    grade_answer, so a double submit, a resubmission or a concurrent refusal can
    never grade or write the item twice (409). A33: a refusal (read BEFORE
    `unavailable`, which it also sets) keeps the item posed, counts on
    `probe.refusals[qh]` and releases the claim; the CHECK_REFUSALS_AS_IDK-th
    refusal of the item in this probe is graded as idk. `unavailable` (an
    outage, a missing second opinion, the grader cap) and a withdrawn item count
    as not asked: no evidence for either outcome. After the flush the claim is
    released only by the write that records the observation, so a lost record
    never admits a second write (the item is moved past once the claim is
    stale)."""
    _, course_id = _session_scope(body.session_id, body.user_id)
    state = _load_loop_state(body.session_id)
    _require_phase(state, "probe")
    qh = body.question_hash
    posed = _probe_doc(state).get("current")
    if not isinstance(posed, dict) or posed.get("question_hash") != qh:
        raise HTTPException(status_code=409, detail=_PROBE_NOT_POSED)
    if posed.get("grading_claim"):
        raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
    skills = list(_probe_doc(state).get("skills") or [])
    node_id = posed["node_id"]
    item = next(
        (
            it
            for it in _probe_items(body.user_id, course_id, skills)
            if it.id == posed.get("check_item_id")
        ),
        None,
    )
    now = _now_s()
    claim = str(uuid.uuid4())

    def take(pr: dict, cur: dict) -> None:
        if cur.get("grading_claim"):
            raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
        cur["grading_claim"], cur["grading_claim_at"] = claim, now

    def take_posed(doc: dict) -> None:
        _require_phase(doc, "probe")
        _refuse_while_closing(doc, now)  # PKG-09: grading and closing exclude each other
        cur = _probe_doc(doc).get("current")
        if not isinstance(cur, dict) or cur.get("question_hash") != qh:
            raise HTTPException(status_code=409, detail=_PROBE_NOT_POSED)
        take(doc["probe"], cur)

    _update_loop_state(body.session_id, take_posed)
    if item is None:  # A23 withdrawal: nothing is graded
        _update_loop_state(body.session_id, _under_probe_claim(qh, claim, _not_asked))
        return {"graded": False, "unavailable": True}

    text = body.answer or body.reason
    idk = body.idk or _is_idk_phrase(text)
    deps = SaplingDeps(
        user_id=body.user_id,
        course_id=course_id or None,
        supabase=None,
        request_id=_request_id(request),
        session_id=body.session_id,
        feature="loop_probe",
        learning_loop=loop_on,
    )
    written = False
    try:
        outcome = await grade_answer(
            item.item,
            CheckAnswer(
                question_hash=qh,
                answer_text=body.answer,
                selected_option=body.option,
                reason=body.reason,
                idk=idk,
            ),
            deps=deps,
            node_id=node_id,
        )
        if outcome.refused:  # A33, read BEFORE `unavailable`: never a skip

            def count_refusal(pr: dict, cur: dict) -> None:
                pr["refusals"][qh] = int(pr["refusals"].get(qh) or 0) + 1
                if pr["refusals"][qh] < CHECK_REFUSALS_AS_IDK:
                    _release(pr, cur)  # nothing was graded: asked again

            state = _update_loop_state(
                body.session_id, _under_probe_claim(qh, claim, count_refusal)
            )
            if (_probe_doc(state).get("current") or {}).get("grading_claim") != claim:
                return {"graded": False, "refused": True}
            idk = True  # the CHECK_REFUSALS_AS_IDK-th refusal is an idk observation (A1)
            outcome = await grade_answer(
                item.item, CheckAnswer(question_hash=qh, idk=True), deps=deps, node_id=node_id
            )
        if outcome.unavailable:  # invariant 28: nothing for either outcome
            _update_loop_state(body.session_id, _under_probe_claim(qh, claim, _not_asked))
            return {"graded": False, "unavailable": True}

        # m1: re-take the claim (fresh stamp) right before the write — a grade
        # slower than LOOP_GRADING_CLAIM_STALE_S may have lost the item to
        # /probe/next meanwhile; a lost claim writes nothing.
        def renew(_pr: dict, cur: dict) -> None:
            cur["grading_claim_at"] = _now_s()

        renewed = _update_loop_state(body.session_id, _under_probe_claim(qh, claim, renew))
        if (_probe_doc(renewed).get("current") or {}).get("grading_claim") != claim:
            return {"graded": False, "recorded": False}
        written = True
        flush_pending(deps, course_id or None)  # ONE call: the probe's only evidence write
    except BaseException:
        if not written:  # nothing was written: the student may answer again
            try:
                _update_loop_state(body.session_id, _under_probe_claim(qh, claim, _release))
            except Exception:
                logger.warning("probe grading claim for %s not released", qh, exc_info=True)
        raise

    correct = bool(outcome.correct)
    evidence = outcome.evidence or {}
    _, p_after = _band_for(body.user_id, node_id)  # re-read after the write (decayed)
    observation = {
        "node_id": node_id,
        "question_hash": qh,
        "difficulty": int(posed["difficulty"]),
        "channel": posed["channel"],  # the item's channel (A1: no "idk" channel)
        "correct": correct,
        "idk": bool(evidence.get("idk", idk)),
        "p_after": p_after,
    }
    out: dict = {}

    def record(pr: dict, _cur: dict) -> None:
        pr["history"].append(observation)
        pr["current"] = None
        out["done"] = probe_policy.probe_done(pr["history"], skills=pr.get("skills") or [])
        out["novice_floor"] = probe_policy.novice_floor(pr["history"])

    def record_posed(doc: dict) -> None:
        out.clear()
        _under_probe_claim(qh, claim, record)(doc)
        if out.get("done"):
            doc["phase"] = "plan"

    saved = _update_loop_state(body.session_id, record_posed)
    if out.get("done"):
        _emit_probe_done(saved, body.user_id, deps.request_id)
    response = {
        "graded": True,
        "correct": correct,
        "p_known": p_after,
        "probe_done": bool(out.get("done")),
        "novice_floor": bool(out.get("novice_floor")),
    }
    if not correct:  # spec §3.3: a wrong answer or an idk gets the answer at once
        response["reference_answer"] = item.reference_answer
    return response


@router.post("/probe/answer")
async def probe_answer(body: ProbeAnswerBody, request: Request) -> dict:
    """Behaviour 11: grade_answer only (A16) — no tutor turn, no tutor budget
    (A20); the rate limit is the one model-cost guard here (spec §9), checked
    inline AFTER the gate (PKG-12's pattern) so a gate-off student gets the
    404, never a 429."""
    loop_on = _gate(body.user_id, request)
    ai_budget.enforce_rate_limit_for(body.user_id)
    _consume_pending(body.session_id, body.user_id)
    return await _agent_turn_or_http_error(
        _probe_submission(body, request, loop_on=loop_on), what="probe grader"
    )


@router.get("/plan")
def plan_get(request: Request, user_id: str = Query(...), session_id: str = Query(...)) -> dict:
    """Behaviour 13: the proposed plan — due reviews, then the outer fringe's new
    material (coupled cap), then interleaved proficient siblings, in PLAN_ORDER.
    The proposal is stored so /plan/approve can check the student's choice
    against it. No goal filter yet (Non-goals: nothing maps a syllabus week to
    concepts)."""
    _gate(user_id, request)
    _probe_plan_read_limit(user_id)
    _, course_id = _session_scope(session_id, user_id)
    state = _load_loop_state(session_id)
    _require_phase(state, "plan")
    states = _plan_states(user_id, course_id)
    edges = _plan_prereq_edges(user_id, list(states))
    parents: dict[str, set[str]] = {}
    for prereq, dependent in edges:
        if prereq != dependent:
            parents.setdefault(dependent, set()).add(prereq)

    def siblings(node_id: str) -> list[str]:
        mine = parents.get(node_id, set())
        return sorted(m for m, ps in parents.items() if m != node_id and ps & mine)

    proposal = planner.plan(
        planner.outer_fringe(states, edges),
        _plan_due_reviews(user_id, list(states)),
        siblings,
        None,
        proficient=frozenset(n for n, p in states.items() if p >= BKT_PROFICIENT),
    )
    ids = [c.node_id for c in proposal.concepts]
    kinds = {c.node_id: c.kind for c in proposal.concepts}

    def store(doc: dict) -> None:
        _require_phase(doc, "plan")
        plan_doc = doc.get("plan") if isinstance(doc.get("plan"), dict) else {}
        plan_doc["proposed"], plan_doc["proposed_kinds"] = list(ids), dict(kinds)
        doc["plan"] = plan_doc
        if not ids:
            # Nothing to plan (no fringe, no due review: a new student, all
            # proficient): the session is not left in `plan` — it teaches with
            # an empty approved plan (nothing to activate, A27).
            plan_doc["approved"], plan_doc["cursor"] = [], 0
            doc["phase"] = "teach"

    _update_if_changed(session_id, state, store)
    if not ids:
        return {"concepts": [], "order": list(PLAN_ORDER), "empty": True, "phase": "teach"}
    names = _plan_node_names(user_id, ids)
    return {
        "concepts": [
            {
                "node_id": n,
                "concept_name": names.get(n, ""),
                "kind": kinds[n],
                "p_known": states.get(n, BKT_L0),
            }
            for n in ids
        ],
        "order": list(PLAN_ORDER),
    }


@router.post("/plan/approve")
def plan_approve(body: PlanApproveBody, request: Request) -> dict:
    """Behaviour 14 / A27: store the approved concepts (a non-empty, duplicate-
    free subset of the proposal, in the student's order), point PKG-07's
    activation at the first one (`plan.cursor` 0, `concept`, counters 0), and
    move to `teach`. Activates nothing. PKG-09 post-hoc (spec §13 A19): after
    the plan is saved the learner brief is built and stored once for the
    session; a brief failure never changes the response."""
    _gate(body.user_id, request)
    _, course_id = _session_scope(body.session_id, body.user_id)
    chosen = list(body.concept_ids)
    out: dict = {}

    def approve(doc: dict) -> None:
        _require_phase(doc, "plan")
        plan_doc = doc.get("plan") if isinstance(doc.get("plan"), dict) else {}
        proposed = plan_doc.get("proposed") or []
        if len(set(chosen)) != len(chosen) or not set(chosen) <= set(proposed):
            raise HTTPException(
                status_code=422, detail="concept_ids must be distinct ids from the proposed plan"
            )
        kinds = plan_doc.get("proposed_kinds") or {}
        lead = 0
        while lead < len(chosen) and kinds.get(chosen[lead]) == "review":
            lead += 1
        out["n_reviews_first"] = lead
        plan_doc["approved"], plan_doc["cursor"] = list(chosen), 0
        plan_doc.pop("done", None)
        doc["plan"] = plan_doc
        doc["concept"] = chosen[0]
        doc["teach_turns"] = 0
        doc["concept_checks"] = 0
        doc["phase"] = "teach"

    _update_loop_state(body.session_id, approve)
    # PKG-09 post-hoc (spec §13 A19): the learner brief is built once per session, here.
    try:
        store_brief(body.session_id, body.user_id, course_id or None, chosen)
    except Exception as exc:
        logger.warning(
            "learner brief not stored at plan approval (%s); the first loop turn builds it",
            type(exc).__name__,
        )
    events_service.log_event(
        "learn.plan_approved",
        category="usage",
        user_id=body.user_id,
        request_id=_request_id(request),
        payload={"concept_ids": chosen, "n_reviews_first": out["n_reviews_first"]},
    )
    return {"phase": "teach", "concept_ids": chosen}


# ── PKG-12: the daily review queue (spec §3.2, §3.5, §5; A16, A20, A22, A23, A33, A52) ──
# Every review route is require_self + the gate (`_gate`, 404 when the loop is off,
# before any read). The review session (a `sessions` row with mode 'review', one per
# user, course and UTC day) is keyed on the requesting user, and a row of another
# student's is a 403. No review route gates on the tutor budget level: the only budget
# reads are `pause_novice` (A20 — novice concepts pause, flashcards and the rest keep
# working) and the rate limit on a CHECK answer, the one body that runs a model.


_REVIEW_NOT_FOUND = "review item not found"
_REVIEW_EXPIRED = "review session expired"
_REVIEW_CLAIM_DETAIL = {"not_served": "review item not served", "already_graded": _ALREADY_GRADED}


def _review_now() -> datetime:
    return datetime.now(timezone.utc)


def _pause_novice(user_id: str) -> bool:
    """A20: at the tutor hard level novice-band concepts are held back."""
    return bool(ai_budget.check(user_id, "tutor", "novice").pause_novice)


def _review_deps(
    user_id: str, course_id: str | None, session_id: str, request_id: str, loop_on: bool
) -> SaplingDeps:
    """The grader's deps, built as `_grade_submission` builds them, on the review
    session."""
    return SaplingDeps(
        user_id=user_id,
        course_id=course_id or None,
        supabase=None,
        request_id=request_id,
        session_id=session_id,
        feature="loop_review",
        learning_loop=loop_on,
    )


def _review_course(user_id: str, course_id: str | None) -> None:
    """A review scoped to a course is scoped to one the student is enrolled in
    (404 otherwise, before any review read)."""
    if course_id and not user_offering_ids_for_course(user_id, course_id):
        raise HTTPException(status_code=404, detail="Course not found")


def _review_session(user_id: str, course_id: str | None, now: datetime) -> tuple[str, dict]:
    try:
        return review.load_or_create_review_session(user_id, course_id, now)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Session user mismatch") from None


def _serve_review_item(user_id: str, item, loop_state: dict, session_id: str, now: datetime):
    """The client payload of `item`, re-loaded here (a check item withdrawn or a card
    deleted since the queue was built → None, and the next item is served). An
    item already open for its key is re-served without a write (review.serve)."""
    if item.kind == "check":
        check = get_check_item(item.id)
        if check is None:
            return None
        return review.serve(
            item, check_item=check, loop_state=loop_state, session_id=session_id, now=now
        )
    row = review.load_card(user_id, item.id)
    if row is None:
        return None
    return review.serve(item, card_row=row, loop_state=loop_state, session_id=session_id, now=now)


@router.get("/review/next")
def review_next(
    request: Request, user_id: str = Query(...), course_id: str | None = Query(None)
) -> dict:
    """The next item of today's review queue (or null). A served item stays the
    answerable one until it is answered: a refresh re-serves it (no write, no
    event) instead of choosing another — never item shopping. A new item is
    opened for answering and `review.served` follows the successful serve.
    `due_total` is everything due today; `in_budget` what the remaining budget
    covers (null item + due_total > 0 = the budget is spent, not caught up)."""
    _gate(user_id, request)
    _review_course(user_id, course_id)
    now = _review_now()
    sid, loop_state = _review_session(user_id, course_id, now)
    retention = review.review_retention(user_id, course_id)
    queue, stats = review.due_queue_with_stats(
        user_id,
        course_id,
        now,
        loop_state=loop_state,
        pause_novice=lambda: _pause_novice(user_id),
    )
    # the item already open for its key first: a refresh never moves on
    ordered = sorted(queue, key=lambda i: not review.is_open(loop_state, i, now))
    payload = None
    try:
        for item in ordered:
            fresh = not review.is_open(loop_state, item, now)
            payload = _serve_review_item(user_id, item, loop_state, sid, now)
            if payload is not None:
                if fresh:
                    review.log_served(
                        user_id, queue, retention=retention, request_id=_request_id(request)
                    )
                break
    except LoopStateConflict:
        raise _StateConflict() from None
    due = stats.get("due") or {}
    return {
        "item": payload,
        "remaining_budget_s": review.remaining_budget_s(loop_state),
        "session_id": sid,
        "retention_target": retention,
        "due_total": sum(due.values()),
        "in_budget": len(queue),
    }


@router.post("/review/answer")
async def review_answer(body: ReviewAnswerBody, request: Request) -> dict:
    """Grade one answer to the item today's session served for its key: a check
    through PKG-05's grade_answer (inside review.grade_review — its ONE evidence
    write), a flashcard through PKG-11's FSRS path. The item, its node (A2) and
    its reference are re-loaded here. Grading is a claim (A52): a second submit of
    the same served item is a 409 and is never graded or written twice."""
    loop_on = _gate(body.user_id, request)
    if body.kind == "check":  # the one review body that runs a model (the grader)
        ai_budget.enforce_rate_limit_for(body.user_id)
    _review_course(body.user_id, body.course_id)
    now = _review_now()
    if body.session_id != review.review_session_id(body.user_id, body.course_id, now):
        raise HTTPException(status_code=409, detail=_REVIEW_EXPIRED)  # a new UTC day began
    sid, loop_state = _review_session(body.user_id, body.course_id, now)
    check = card_row = deps = None
    if body.kind == "check":
        check = get_check_item(body.item_id)
        node_id = _node_for_item(body.user_id, check) if check is not None else None
        if node_id is None:
            raise HTTPException(status_code=404, detail=_REVIEW_NOT_FOUND)
        if check.format == "mc_reason" and not body.selected_option:
            raise HTTPException(status_code=422, detail="an mc_reason answer needs selected_option")
        if check.format != "mc_reason" and not body.answer:
            raise HTTPException(status_code=422, detail="a free answer needs answer")
        deps = _review_deps(body.user_id, body.course_id, sid, _request_id(request), loop_on)
    else:
        card_row = review.load_card(body.user_id, body.item_id)
        if card_row is None:
            raise HTTPException(status_code=404, detail=_REVIEW_NOT_FOUND)
    try:  # a stored fsrs_s that is not a finite positive number → 422 (InvalidStability)
        item = (
            review.item_for_check(body.user_id, check, node_id, now)
            if check is not None
            else review.item_for_card(card_row, body.course_id, now)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    retention = loop_state["review"].get("retention") or review.review_retention(
        body.user_id, body.course_id
    )
    claim = str(uuid.uuid4())
    try:
        review.claim_item(sid, review.sr_key(item), item.id, claim, now)
        outcome = await review.grade_review(
            body.user_id,
            item,
            answer=body.answer,
            rating=body.rating,
            session_id=sid,
            loop_state=loop_state,
            now=now,
            request_id=_request_id(request),
            retention=retention,
            check_item=_item_like(check) if check is not None else None,
            card_row=card_row,
            selected_option=body.selected_option,
            reason=body.reason,
            deps=deps,
            claim=claim,
        )
    except review.ReviewClaimRefused as exc:
        raise HTTPException(status_code=409, detail=_REVIEW_CLAIM_DETAIL[exc.reason]) from None
    except LoopStateConflict:
        raise _StateConflict() from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {
        "correct": outcome.correct,
        "hint": outcome.hint,
        "next_due_at": outcome.next_due_at,
        "rating": outcome.rating,
        "remaining_budget_s": review.remaining_budget_s(loop_state),
        "sr": outcome.sr,
        "unavailable": outcome.unavailable,
        "refused": outcome.refused,
    }


@router.get("/review/summary")
def review_summary(
    request: Request, user_id: str = Query(...), course_id: str | None = Query(None)
) -> dict:
    """Today's due counts, budget and retention target. Read-only: it never creates
    the review session."""
    _gate(user_id, request)
    _review_course(user_id, course_id)
    now = _review_now()
    try:
        loop_state = review.peek_review_session(user_id, course_id, now)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Session user mismatch") from None
    return review.summary(
        user_id,
        course_id,
        now,
        loop_state=loop_state,
        pause_novice=lambda: _pause_novice(user_id),
    )


@router.get("/review/active")
def review_active(request: Request, user_id: str = Query(...)) -> dict:
    """The frontend's cheap loop probe (`getLoopStatus`): 200 when the loop is on
    for the student, the gate's 404 when it is off. Builds nothing (PKG-07's
    GET /status needs a loop session id)."""
    _gate(user_id, request)
    return {"active": True}
