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
import hmac
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from typing import NamedTuple, get_args

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
    plan_focus_block,
    prequestion_answer_block,
    prequestion_item_block,
    routable_tier,
    student_envelope,
    tier_run_kwargs,
    variant_run_args,
)
from agents.tools.check import CHANNEL_FOR_FORMAT, CheckAnswer, GradeOutcome, grade_answer, grader_answer_text
from agents.usage import UnfinishedRun, record_agent_usage, served_model_name
from db.connection import page_all, pg_quote_value, table
from learning import answer_guard, arms, gates, ladder, planner, policy, review, turn_activity, zpd_events
from learning import grade_checkpoint, item_reports
from learning import prequestion as prequestion_rules
from learning import self_explain
from learning.prequestion_store import store_answer as store_prequestion_answer
from learning.self_explain_store import close_prompt as close_self_explain_prompt
from learning.self_explain_store import record_prompt as record_self_explain_prompt
from learning import probe as probe_policy
from learning.bkt import band as bkt_band
from learning.checks import (
    CheckItem,
    PosttestChoice,
    choose_posttest_item,
    is_servable,
    posttest_reserves,
    posttest_skip_reason,
    pretest_form,
    pretest_match,
    select_item,
    serve_quality,
)
from learning.checks import unsourced as item_unsourced
from learning.evidence import (
    PREREQ_RELATIONSHIP_TYPE, PlanningObservation, PlanningPersistenceUnavailable, PlanningProvenance, flush_pending,
)
from learning.evidence_transaction import (
    EvidenceItemRetired,
    EvidenceObservationSuperseded,
    read_receipt as read_evidence_receipt,
)
from learning.void_store import voided_by_node, voided_event_ids
from learning.planning_history import read_planning_history
from learning.fsrs import budget_select, order_due
from learning.gate import learning_loop_active, learning_loop_for_request
from learning.goals import (
    encode_goal, public_goal, goal_version, attempted_nodes, planning_observations,
    scope_signature, progress as goal_progress,
)
from learning.ladder import Rung
from learning.leak import confront_text_states_answer, detect_leak, leak_spans
from learning.served_scan import ScanSet
from learning.learning_gain import answer_latency_s, clamp_visibility, window_at
from learning.posttest_store import posttest_anchors
from learning.learner_brief import course_concept_names, store_brief
from learning.learner_state import LearnerState, read_states
from learning.misconceptions import (
    attempts_for_node,
    attempts_of,
    carry,
    confront_of,
    is_key,
    open_for,
    record,
    recheck_after_release,
    resolve_after_grade,
    set_confront,
    slip_or_misconception,
)
from learning.loop_state_store import (
    LoopStateConflict,
    LoopSessionClosed,
    evidence_spans,
    load_loop_state,
    opportunity_window,
    recent_evidence,
    reported_hashes,
    revealed_hashes,
    seen_hashes,
    update_loop_state,
)
from learning.reveal_store import record_reveals, record_unscanned, unscanned_since
from learning.help_ledger import (
    earliest_open_pose,
    mark_graded,
    max_help,
    record_help,
    record_posed,
    ungraded_posed_window,
)
from learning.params import (
    LOOP_SCAN_POSED_MAX,
    BAND_CONTROL_CEILING_STEP,
    BKT_L0,
    BKT_PROFICIENT,
    MISCONCEPTION_CONFRONT_MIN_RUNG,
    CHECK_ITEM_DIFFICULTIES,  # A122's band difficulty targets (A126 dropped its own use)
    CHECK_ITEM_FORMATS,
    CHECK_REFUSALS_AS_IDK,
    CLOSE_PHASES,
    CLOSE_RUN_TIMEOUT_S,
    EDGE_PREREQ_SOURCE_IS_PREREQ,
    HELP_NOVELTY_DIGESTS_MAX,
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
    LOOP_FAILED_ANCHORS_MAX,
    PLAN_ORDER,
    POSTTEST_DUE_CACHE_S,
    POSTTEST_MAX_ITEMS,
    POSTTEST_POSE_TTL_HOURS,
    POSTTEST_WINDOWS_DAYS,
    PROBE_MAX_SKILLS,
    PROBE_SESSION_CAP,
    REVIEW_DAILY_BUDGET_MIN,
    REVIEW_SECONDS_PER_CHECK,
    RUNG_ASSISTED_MIN,
    RUNG_NO_CREDIT_MIN,
    ZPD_RATING_EVERY_N_CHECKS,
)
from learning.policy import LearnerView, LoopState, StepState
from learning.session_close import (
    CLOSE_FALLBACK_DETAILS,
    CloseRecord,
    build_close,
    fallback_close,
    session_probe_hashes,
    store_close,
)
from learning.turn_shape import (
    FIELD_JOIN,
    LOOP_PLAN_OPENER,
    LOOP_PROBE_OPENER,
    LOOP_QUIZ_ASK_OPENER,
    TurnTemplate,
    clamp_model_ceiling,
    labels_new_content,
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
    LoopRatingBody,
    LoopReportBody,
    LoopGoalBody,
    PlanApproveBody,
    PosttestAnswerBody,
    PosttestShownBody,
    PosttestStartBody,
    PrequestionAnswerBody,
    ProbeAnswerBody,
    ProbeNextBody,
    ReviewAnswerBody,
    SelfExplainBody,
    StartSessionBody,
)
from routes.learn import (  # legacy helpers, reused verbatim — never copied
    PENDING_SESSIONS,
    _CONTINUATION_NUDGE,
    _CONTINUATION_RUN_KEYS,
    _agent_turn_or_http_error,
    _consume_pending,
    _consume_pending_off_loop,
    _get_catalog_chunk,
    _get_course_id_for_topic,
    _get_course_info,
    _load_message_history,
    _observe_persisted_turn,
    save_message,
)
from services import ai_budget, crisis_support, events_service
from services.academics import (
    course_offering_ids,
    offering_course_id,
    resolve_offering,
    user_offering_ids_for_course,
)
from services.agent_events import SSE_CACHE_CONTROL, SaplingEvent, sapling_event_to_sse
from services.ai_budget import AIBudgetExceeded, enforce_rate_limit
from services.auth_guard import get_session_user_id, guard_off_loop, require_self
from services.encryption import decrypt_if_present, decrypt_json_column, derive_key
from services.chat_stream import stream_structured_turn
from services.check_item_service import (
    course_has_items,
    drafting_pending,
    get_check_item,
    items_by_hash,
    items_by_ids,
    items_for_concepts,
    list_items,
)
from services.feature_flags import flag_on
from services.graph_context import build_graph_context_block
from services.graph_service import _normalize_concept, _prerequisite_edges, get_graph
from services.prompt_safety import neutralise_control_tags, wrap_untrusted
from services.quiz_ask import QUIZ_ASK_ORIGIN, open_quiz_ask
from services.rag_service import chunks_for_ids, format_rag_context, retrieve_chunks_detailed
from services.request_context import current_request_id
from services.session_modes import NOT_REVIEW
from services.request_limits import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter()

_NOT_ENABLED = "learning loop not enabled"
_BUDGET_DETAIL = "ai budget reached"  # spec §3.5 hard-level body (A20)


def _kill_switch_first(request: Request) -> None:
    """The kill switch BEFORE the rate limit (spec §7: every loop route 404s when the
    loop is off). Route dependencies run in order and before the handler's `_gate`,
    so a bare `enforce_rate_limit` dependency answered a thrown kill switch with 401
    (no session) or 429 instead of the 404. The gate is env-only after PKG-14b, so no
    user is needed to read it, and it costs no read of any kind — the handler's
    `_gate` still makes the one route-entry read (A38 00) and runs require_self."""
    if not learning_loop_active(""):
        raise HTTPException(status_code=404, detail=_NOT_ENABLED)


_RATE_LIMITED = [Depends(_kill_switch_first), Depends(enforce_rate_limit)]


def _screened(surface: str, *fields: str, respond) -> list:
    """`_RATE_LIMITED` for a route that takes student-written text: the crisis
    screen sits between the kill switch and the rate limit
    (docs/safety/crisis-support.md). A crisis turn is answered with the card
    before the limiter is even read, so it never meets a 429 and consumes no
    unit; any other request meets the same two dependencies as before."""
    return [
        Depends(_kill_switch_first),
        crisis_support.screened(surface, *fields, respond=respond),
        Depends(enforce_rate_limit),
    ]
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
_FEEDBACK_PENDING = "feedback pending; retry feedback before another check"
_WITHDRAWN_FEEDBACK = (
    "This check has been withdrawn. {result} The question and solution are no longer "
    "available. You can continue with another check or end this session."
)
_DETERMINISTIC_RUNGS = (Rung.H2, Rung.H4, Rung.H6)
#: The session opener served without a model (A27, A121): ALWAYS while the new
#: session is in the probe phase — a neutral welcome and the check-in's intro,
#: no teaching and no question (the check-in is a pretest; teaching first skews
#: it, and a question would compete with its first item) — and at the hard
#: budget level, so a capped student can still start a session and reach the
#: probe (§3.5).
_LOOP_OPENER_TEMPLATE = LOOP_PROBE_OPENER
#: Spec §13 A121: loop_state key — True when the last SERVED turn ended with the
#: tutor's own open question (a model teach or feedback turn that rendered its
#: question; never a hint, a pose, a template or a turn that posed a check).
#: With the v2 variant on, the next teach-phase chat message is
#: then the student's reply to it, and that turn opens with the verdict
#: (`_LoopTurn._answer_check_due`). Kept with the flag off too, so a student
#: turned on mid-session is judged from the right turn. A flag only: the
#: question's text lives in the (encrypted) message history, never here.
OPEN_QUESTION_KEY = "open_question"
#: Spec §13 A121: the v2 tutor variant's flag (services/feature_flags.py) —
#: every tutor-prompt change that needs a live eval re-record sits behind it.
TUTOR_V2_FLAG = "loop_tutor_v2"


def _tutor_v2_on(user_id: str | None) -> bool:
    """The `loop_tutor_v2` flag for this student (spec §13 A121),
    resolved ONCE per turn by `_LoopTurn._derive` and carried on the turn: it
    picks the prompt and schema variant (`variant_run_args`), the answer check,
    the verdict lines, the label rules and the plan focus, so one turn never
    sees two answers. No student means off; the resolver fails closed
    (feature_flags)."""
    return bool(user_id) and flag_on(TUTOR_V2_FLAG, user_id)


#: Spec §13 A134: the strict genuine-attempt rule's flag (services/feature_flags.py).
HELP_GATE_STRICT_FLAG = "help_gate_strict"


def _help_gate_strict_on(user_id: str | None) -> bool:
    """The `help_gate_strict` flag for this student (spec §13 A134), read once
    per request where it matters: POST /step/attempt counts an attempt by the
    strict rule when on, and POST /hint words its time-alone denial by it. No
    student means off; the resolver fails closed (feature_flags)."""
    return bool(user_id) and flag_on(HELP_GATE_STRICT_FLAG, user_id)


#: Spec §13 A138: the segment prequestion's flag (services/feature_flags.py).
PREQUESTION_FLAG = "segment_prequestion"
#: Spec §13 A139: the self-explanation prompts' flag.
SELF_EXPLAIN_FLAG = "self_explanation_prompts"


def _prequestion_on(user_id: str | None) -> bool:
    """The `segment_prequestion` flag for this student (spec §13 A138), read
    once per request where a segment can start or a prequestion be answered.
    Off: nothing is posed, explained or read. No student means off; the
    resolver fails closed (feature_flags)."""
    return bool(user_id) and flag_on(PREQUESTION_FLAG, user_id)


def _self_explain_on(user_id: str | None) -> bool:
    """The `self_explanation_prompts` flag for this student (spec §13 A139),
    read once per turn. Off: no juncture is ever a prompt and no
    acknowledgement line is sent."""
    return bool(user_id) and flag_on(SELF_EXPLAIN_FLAG, user_id)


#: Spec §13 A138: the server cue of the turn that explains an answered
#: prequestion (trusted route text, like an [ACTION: …] turn's).
_PREQUESTION_CUE = "[ACTION: The student has just answered the prequestion; explain its answer now.]"
_NO_OPEN_PREQUESTION = "no open prequestion"
_NO_OPEN_SELF_EXPLAIN = "no open self-explanation prompt"

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
    loop_on = _gate_value(user_id, request)
    if not loop_on:
        raise HTTPException(status_code=404, detail=_NOT_ENABLED)
    return loop_on


def _gate_value(user_id: str, request: Request) -> bool:
    """require_self, then the gate's value (read once per request, A38 00)."""
    require_self(user_id, request)
    carried = getattr(request.state, "learning_loop", None)
    return carried if isinstance(carried, bool) else learning_loop_for_request(user_id)


def _now_s() -> float:
    return datetime.now(timezone.utc).timestamp()


def _loop_arm(user_id: str) -> str | None:
    """The student's within-student arm label (`user_settings.loop_arm`, PKG-14;
    set by the series owner in SQL, in no settings API field — A31's reason).
    Only a non-empty string is an arm; a missing row, a non-string value or a
    read error is no arm (variant A everywhere, no budget exemption), so the
    plumbing can never turn a student into an arm session by accident."""
    try:
        rows = table("user_settings").select("loop_arm", filters={"user_id": f"eq.{user_id}"})
    except Exception as exc:  # the arm is plumbing: a failed read is "no experiment"
        logger.warning("loop_arm read failed for %s: %s", user_id, type(exc).__name__)
        return None
    raw = rows[0].get("loop_arm") if rows and isinstance(rows[0], dict) else None
    return raw if isinstance(raw, str) and raw else None


def _arm_for(user_id: str, request: Request) -> str | None:
    """`_loop_arm`, read ONCE per request (carried on `request.state`)."""
    cache = getattr(request.state, "loop_arm", None)
    if isinstance(cache, tuple) and len(cache) == 2 and cache[0] == user_id:
        return cache[1]
    arm = _loop_arm(user_id)
    request.state.loop_arm = (user_id, arm)
    return arm


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
        raise HTTPException(status_code=404, detail="Session not found")
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


def _update_loop_state(session_id: str, mutate: Callable[[dict], None], *, require_open: bool = False, require_existing: bool = False) -> dict:
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
        extra = {"require_open": True} if require_open else {}
        saved = update_loop_state(session_id, apply, **extra)
    except LoopSessionClosed as exc:
        raise HTTPException(status_code=409, detail=_SESSION_CLOSED) from exc
    except LoopStateConflict as exc:
        logger.warning("loop state for %s: compare-and-set exhausted", session_id)
        raise _StateConflict() from exc
    if saved is None:
        if require_existing:
            raise HTTPException(status_code=409, detail="Session unavailable; reload before retrying")
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
        return "teach" if entry.get("feedback_given") is True else "feedback"
    return "check"


def _pending_grade(state: dict) -> dict | None:
    """Public recovery identity only; encrypted answer/outcome never leaves storage."""
    if _loop_phase(state) == "probe":
        current = (state.get("probe") or {}).get("current")
        if isinstance(current, dict) and grade_checkpoint.KEY in current:
            return {"kind": "probe", "question_hash": current["question_hash"]}
    active = state.get("current")
    entry = (state.get("steps") or {}).get(active) if active else None
    if isinstance(entry, dict) and grade_checkpoint.KEY in entry:
        return {"kind": "check", "question_hash": active}
    return None


def _require_no_pending_feedback(state: dict) -> None:
    """A committed grade stays current until its feedback is actually served.

    Ordinary chat retries that feedback from its saved verdict; activating a
    new check must not abandon it or count it as delivered. Ending the session
    remains a separate, explicit early end.
    """
    active = state.get("current")
    entry = (state.get("steps") or {}).get(active) if active else None
    if (
        isinstance(entry, dict)
        and entry.get("graded_at") is not None
        and entry.get("feedback_given") is not True
    ):
        raise HTTPException(status_code=409, detail=_FEEDBACK_PENDING)


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
    state = _load_loop_state(session_id)
    _require_teaching(state)
    if _pending_grade(state):
        raise HTTPException(status_code=409, detail="Finish checking the saved answer before continuing")


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


def _prerequisites(user_id: str, node_id: str) -> list[policy.Prerequisite]:
    """The node's prerequisite parents with their decayed p_known (BKT_L0 for a
    parent with no learner_state row); [] when it has none. Parents come from
    the read helper PKG-03's propagation uses (graph_service._prerequisite_edges),
    with the same EDGE_PREREQ_SOURCE_IS_PREREQ direction."""
    parents: list[str] = []
    for src, tgt in _prerequisite_edges(user_id, node_id):
        prereq, dependent = (src, tgt) if EDGE_PREREQ_SOURCE_IS_PREREQ else (tgt, src)
        if dependent == node_id and prereq != node_id and prereq not in parents:
            parents.append(prereq)
    if not parents:
        return []
    states = read_states(user_id, parents)
    return [
        policy.Prerequisite(p, states[p].p_known if p in states else BKT_L0) for p in parents
    ]


def _prereq_proficient(user_id: str, node_id: str) -> bool:
    """The ceiling's prerequisite input (spec §3.3): True only when the status is
    PROFICIENT — every prerequisite parent in the profic band (p_known ≥
    BAND_DEVELOP_MAX). A node with NO prerequisite edge is UNKNOWN, never
    proficient (spec §13 A122): it takes the "prerequisite not known" row, so a
    novice there gets the worked example first."""
    status = policy.prerequisite_status(_prerequisites(user_id, node_id))
    return status is policy.PrerequisiteStatus.PROFICIENT


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
        n_strong_unassisted=st.n_strong_unassisted,
    )


def _genuine(text: str, independent_s: float, band: str, variant: str = "A") -> bool:
    """Spec §3.3 genuine attempt, for hint unlocking and the shown-work floor
    only (never a grading gate, A16). `matched_non_attempt` is
    `vetoes_attempt` — never `matches_non_attempt` (HANDOFF-06; spec §13 A120:
    a phrase or plea vetoes only a message with nothing else in it)."""
    return gates.is_genuine_attempt(
        len((text or "").strip()),
        False,
        gates.vetoes_attempt(text or ""),
        independent_s,
        band,
        time_scale=config.LEARNING_GATE_TIME_SCALE,
        variant=variant,  # PKG-14: the concept's within-student arm (learning.arms.variant_for)
    )


def _ceiling_for(
    *,
    step: StepState,
    learner: LearnerView,
    message: str,
    independent_s: float,
    variant: str = "A",
    teach_attempt: bool = False,
    band_delta: int = 0,
) -> tuple[Rung, policy.CeilingReason]:
    """policy.ceiling_with_reason on typed state only (invariant 4). The shown-work
    floor applies when the step already records shown work or this message is a
    genuine attempt; exam mode is the step's own flag (False until PKG-08).
    `band_delta`: band control's ceiling clause for the concept (spec §13 A122,
    `_band_ceiling_delta`)."""
    showed = step.showed_work or _genuine(message, independent_s, learner.band, variant)
    raise_ = {"teach_attempt": True} if teach_attempt else {}  # A85; typed state only
    if band_delta:
        raise_["band_delta"] = band_delta
    return policy.ceiling_with_reason(learner, dataclasses.replace(step, showed_work=showed), **raise_)


#: loop_state key (spec §13 A122): node id → band control's ceiling delta for
#: that concept this session (−1 after HARDER, +1 after EASIER_CHECK_PREREQS;
#: set when a verdict's feedback turn is served, held through HOLD)
_BAND_CEILING = "band_ceiling"


def _band_ceiling_delta(state: dict, node_id: str | None) -> int:
    """The concept's band-control ceiling delta in this session (0 when none,
    or for a malformed stored value: no adjustment is ever invented)."""
    deltas = state.get(_BAND_CEILING) if node_id else None
    delta = deltas.get(node_id) if isinstance(deltas, dict) else None
    if type(delta) is int and delta in (
        -BAND_CONTROL_CEILING_STEP,
        BAND_CONTROL_CEILING_STEP,
    ):
        return delta
    return 0


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


def _context_blocks(
    *, user_id: str, course_id: str, user_message: str, context, item, out: dict | None = None
) -> list[str]:
    """Only the blocks `context` (policy.context_policy) asks for, in the legacy
    order, with the legacy builders (routes/learn.py::_prepare_chat_run).

    Spec §13 A128: the course-material retrieval tells a FAILURE from an empty
    result (`retrieve_chunks_detailed`); a failed one sets `out["retrieval"] =
    "failed"` for the turn, and the turn still runs (with no RAG block, as an
    empty result would) — the outage is reported, never blocking."""
    blocks: list[str] = []
    bu_code = _get_course_info(course_id).get("course_code") if course_id else None
    if context.catalog and bu_code:
        catalog = _get_catalog_chunk(bu_code)
        if catalog:
            blocks.append(_CATALOG_HEADER + catalog)
    if context.rag_k and bu_code:
        got = retrieve_chunks_detailed(
            user_message, course_id=bu_code, k=context.rag_k, user_id=user_id
        )
        if got.failed and out is not None:
            out["retrieval"] = "failed"
        rag = format_rag_context(got.chunks)
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


# ── A failed course-material retrieval (spec §13 A128) ─────────────────────
#
# Two loop_state keys. `materials_notice`: the session's ONE calm note that
# its course materials are unavailable has been served (`materials_unavailable`
# in the turn's response; the UI renders it — never a prompt change).
# `retrieval_failed`: the concept nodes whose teach turns ran with a failed
# retrieval since their last check activation; `_activate_next_item` moves a
# concept's mark onto the step it opens (`retrieval: "failed"`), so that
# step's zpd.step says its teaching lacked the course's material.
_MATERIALS_NOTICE = "materials_notice"
_RETRIEVAL_FAILED = "retrieval_failed"
#: The step entry's key (and zpd.step's payload value) for such a step.
_RETRIEVAL_KEY, _RETRIEVAL_FAILED_VALUE = "retrieval", "failed"


def _note_retrieval_failure(state: dict, concept_node: str | None) -> bool:
    """Record a turn whose course-material retrieval failed, on the loop
    document (a compare-and-set mutate's business: no side effects): the
    concept's mark, and the session's note. True when THIS turn serves the
    note — the first failure of the session, never again after it."""
    if concept_node:
        marked = [n for n in state.get(_RETRIEVAL_FAILED) or [] if isinstance(n, str)]
        if concept_node not in marked:
            state[_RETRIEVAL_FAILED] = [*marked, concept_node]
    if state.get(_MATERIALS_NOTICE) is True:
        return False
    state[_MATERIALS_NOTICE] = True
    return True


def _materials_notice(out: dict) -> dict:
    """The turn response's A128 key: `materials_unavailable: true` on the ONE
    turn that serves the session's note, absent on every other (never false)."""
    return {"materials_unavailable": True} if out.get("materials_notice") else {}


def _take_retrieval_mark(state: dict, concept_node: str) -> bool:
    """Whether the concept's teaching since its last check ran with a failed
    retrieval — the mark is consumed, so the NEXT check of the concept starts
    clean (its own teach turns decide it)."""
    marked = [n for n in state.get(_RETRIEVAL_FAILED) or [] if isinstance(n, str)]
    if concept_node not in marked:
        return False
    rest = [n for n in marked if n != concept_node]
    if rest:
        state[_RETRIEVAL_FAILED] = rest
    else:
        state.pop(_RETRIEVAL_FAILED, None)
    return True


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
    v2: bool = False,
    focus_block: str | None = None,
    extra_blocks: list[str] | None = None,
    out: dict | None = None,
) -> tuple:
    """One loop run's agent, user message, run kwargs and deps. `user_message`
    is the retrieval query and — unless `trusted` (server text: an [ACTION: ...]
    line) — the student's words, which reach the model only inside the nonce
    envelope (review round 3, C1(a)); `instruction` is server text placed
    verbatim before it. The history's user rows are the student's words too
    (enveloped by the caller, `_guard_history`). `v2` adds the
    v2 variant's run arguments (spec §13 A121, `variant_run_args`):
    none when off. `focus_block` (v2 teach turns only) is the plan concept's
    untrusted block (`plan_focus_block`), first among the context blocks.
    `extra_blocks` (spec §13 A138: the prequestion's answer block) follow the
    context blocks. `out` receives what the context assembly found (A128:
    `retrieval: "failed"`)."""
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
        user_id=user_id,
        course_id=course_id,
        user_message=user_message,
        context=context,
        item=item,
        out=out,
    )
    if focus_block:
        blocks = [focus_block, *blocks]
    if extra_blocks:
        # spec §13 A138: the prequestion's answer, as data, after the context
        blocks = [*blocks, *extra_blocks]
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
        **variant_run_args(v2),
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


#: Spec §13 A121: the v2 variant's run arguments
#: (`variant_run_args`) — a continuation finishes the turn in the same variant.
#: A flag-off run carries none of them.
_VARIANT_RUN_KEYS = ("output_type", "instructions", "metadata")


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
    carried = {
        k: run_kwargs[k]
        for k in (*_CONTINUATION_RUN_KEYS, *_VARIANT_RUN_KEYS)
        if k in run_kwargs
    }
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
    budget check FIRST (invariant 23; None at the hard level or when the
    existing slot exceeds the refreshed tier ceiling), one counted
    tutor call (A39), then `continuation_plan` run on the SAME slot with every
    tool removed — the safety property, `override(tools=[], toolsets=[])`
    (pinned). Returns the rendered turn (the output validator still judges it
    against deps.loop_turn)."""
    decision = ai_budget.check(
        turn.user_id, "tutor", turn.band, **turn.budget_counters(include_current_run=True)
    )
    if decision.level == "hard" or (turn.tier == "deep" and decision.tier_ceiling != "deep"):
        # Never rescue on the old deep slot after the known primary work has
        # lowered its allowance. Replanning/rerouting would be a different turn.
        return None
    plan = continuation_plan(
        assembled=turn.assembled, run_kwargs=turn.run_kwargs, messages=messages
    )
    ai_budget.count_tutor_call(turn.user_id)
    usage = RunUsage()
    result = None
    try:
        with turn.agent.override(tools=[], toolsets=[]):
            result = await turn.agent.run(plan.prompt, usage=usage, **plan.run_kwargs)
    finally:
        # A failed continuation still consumed its bounded model requests.
        # Keep an incomplete bill explicitly partial; never invent missing tokens.
        if result is None:
            logger.warning(
                "Loop continuation ended without final output; usage is incomplete "
                "(known model requests=%s); in-flight token usage may be missing",
                usage.requests,
            )
        if result is not None or usage.requests:
            billed = result if result is not None else UnfinishedRun(usage)
            turn.run_requests += _requests_of(billed)
            try:
                record_agent_usage(
                    billed,
                    feature=plan.feature,
                    task=turn.slot,
                    user_id=turn.user_id,
                    session_id=turn.session_id,
                )
            except Exception as exc:
                # The canonical helper never raises. Keep instrumentation from
                # replacing a provider error or cancellation if that changes.
                logger.warning("Usage accounting hook failed (stage=loop_continuation_usage, error_type=%s)", type(exc).__name__)
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
#: definition (judged H2). Spec §13 A121, v2 variant on: a
#: correct-verdict feedback turn serves NO key idea there — the grader's
#: verdict line, served first, says it.
LOW_RUNG_KEY_IDEAS: dict[str, str] = {
    "feedback_correct": "Your answer was graded correct.",
    "hint": "Start by pinning down what the item asks you to find.",
}


def _served_fields(
    out, *, phase: str, rung: Rung, verdict: str | None = None, v2: bool = False
):
    """The structured turn as served (fix round 2). The ladder fixes what the
    lowest rungs may say, so code serves those fields: at an H2 hint the
    question is the ladder's (H2 is a concept pointer: reread the definition —
    recorded model questions named the item's own objects, judged H3); at
    H0/H1 the key idea of a hint or a correct-verdict feedback turn is
    LOW_RUNG_KEY_IDEAS' — or, the v2 variant on (A121), the
    feedback turn's is left out: its verdict line leads the turn. The model
    writes everything else."""
    at = int(rung)
    served = dict(out)
    if phase == "hint" and at == int(Rung.H2) and "question" in out:
        served["question"] = LADDER_FALLBACK_LINES[at]
    if at <= int(Rung.H1) and "key_idea" in out:
        if phase == "hint":
            served["key_idea"] = LOW_RUNG_KEY_IDEAS["hint"]
        elif phase == "feedback" and verdict == "correct":
            served["key_idea"] = "" if v2 else LOW_RUNG_KEY_IDEAS["feedback_correct"]
    return served


def served_template(
    *,
    phase: str,
    rung: Rung,
    poses_check: bool = False,
    answer_check: bool = False,
    v2: bool = False,
    question_text: str | None = None,
) -> TurnTemplate:
    """Spec §13 A121: how this turn is served. Always: no question of its own
    when it poses a check (the card is the one open prompt). With the
    v2 variant on: the "Key idea:" label only on a turn with new
    content (`labels_new_content`: teach or hint at H2+, never feedback), and
    the verdict line first when it answers the reply to the tutor's own
    question. Off, the label is on every turn, exactly as at 7fa9cd0e — the
    rendering every recorded rung judgement was made of. Spec §13 A139:
    `question_text`, a self-explanation prompt code serves in place of the
    model's question (None: the model's, as before)."""
    return TurnTemplate(
        label=labels_new_content(phase, int(rung)) if v2 else True,
        question=not poses_check,
        answer_check=answer_check,
        question_text=question_text,
    )


def served_render(
    out,
    *,
    phase: str,
    rung: Rung,
    verdict: str | None = None,
    poses_check: bool = False,
    answer_check: bool = False,
    v2: bool = False,
    question_text: str | None = None,
) -> str:
    """`render_turn` of the turn as served (`_served_fields`, `served_template`)."""
    return render_turn(
        _served_fields(out, phase=phase, rung=rung, verdict=verdict, v2=v2),
        served_template(
            phase=phase,
            rung=rung,
            poses_check=poses_check,
            answer_check=answer_check,
            v2=v2,
            question_text=question_text,
        ),
    )


def served_partial(
    partial,
    *,
    phase: str,
    rung: Rung,
    verdict: str | None = None,
    poses_check: bool = False,
    answer_check: bool = False,
    v2: bool = False,
    question_text: str | None = None,
) -> str:
    """`render_partial` of a streamed partial as served — the same fields and
    template as `served_render`, so the stream is a prefix of the final text."""
    return render_partial(
        _served_fields(partial, phase=phase, rung=rung, verdict=verdict, v2=v2),
        served_template(
            phase=phase,
            rung=rung,
            poses_check=poses_check,
            answer_check=answer_check,
            v2=v2,
            question_text=question_text,
        ),
    )


def served_lead(*, reference: str, answer_released: bool, verdict: str | None = None) -> str:
    """What code serves ABOVE an item turn's model text: with the answer-verdict
    variant on, a feedback turn's grader verdict as a plain line first (spec
    §13 A121: the turn opens with whether the answer was right, before
    anything else — the hard-level template's own words,
    `_FEEDBACK_VERDICT_LINES`; callers pass `verdict` only then), then the
    released answer (m1, `released_lead`)."""
    lead = _FEEDBACK_VERDICT_LINES[verdict] + FIELD_JOIN if verdict else ""
    return lead + (released_lead(reference) if answer_released else "")


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
    verdict: str | None = None,
):
    """What the student is served for model-written `reply` against the active
    item. The check is STRICT and in SERVED MODE (`detect_leak(given=…)`,
    fix round 2): a copy of text the model was `given` this turn is no leak,
    and number words / standalone letters count only in answer position. A
    reply that still leaks is NEVER masked in place (N1): it is replaced by the
    rung's LADDER_FALLBACK_LINES line (the model already had its one leak
    retry, `deps.loop_leak`). Code's lead goes in front (`served_lead`): a
    feedback turn's `verdict` line (A121), then the released answer (m1).
    Returns (text, LeakVerdict)."""
    item = _item_check_kwargs(
        reference=reference,
        final_answer=final_answer,
        canonical_answer=canonical_answer,
        correct_option=correct_option,
        option_text=option_text,
    )
    leak_verdict = detect_leak(emitted=reply, rung=leak_rung, given=given, **item)
    text = LADDER_FALLBACK_LINES[int(Rung(leak_rung))] if leak_verdict.leaked else reply
    lead = served_lead(reference=reference, answer_released=answer_released, verdict=verdict)
    return lead + text, leak_verdict


_POSES = "posttest_poses"  # spec §13 A87: the post-test commits when it is opened


# ── Served reveals of OPEN, POSED items (PKG-14, spec §13 A88; A86's scope) ──
# A served tutor turn is never withheld on account of item answers. Its served
# text is scanned (strict served mode) against the items the student has SEEN
# the prompt of and that are still OPEN — the active check item of any open
# loop session, an open review item, an open post-test pose (an item turn's own
# active item excluded: its leak check is the item turn's). Each stated item is
# recorded in learning_reveals (keyed by the student, durable the moment it is
# served — the opener has no session row), so it is never selected again and
# grades with no unassisted credit (`_reveal_floor`). Open items that cannot be
# read leave an 'unscanned' marker: every item posed at or before it grades as
# assisted. A failed write falls back to the session's loop_state.

#: Conservative cache if a failure's durable update is unavailable. Materialised
#: sessions also store turn_activity before any work; the cache grants no credit.
_FAILED_TURN_ANCHORS: dict[str, float] = {}
ANCHORS_MAX = LOOP_FAILED_ANCHORS_MAX


def stated_items(text: str, items, *, rung: Rung, given: str) -> list[str]:
    """The sorted question hashes of the servable `items` whose answer `text`
    states (strict served mode). An item the check raises on counts as stated
    (fail closed on the evidence side); a non-servable one is skipped. One
    compiled scan (learning.served_scan, spec §13 A101); nothing is a leak at H6."""
    if Rung(rung) >= Rung.H6:
        return []
    return ScanSet.build(items, given=given).stated(text)


def _ts(value) -> datetime | None:
    """A posed-at time from Unix seconds or an ISO string (None if unreadable)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), timezone.utc)
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def posed_items(user_id: str, *, now: datetime) -> tuple[list[tuple], datetime | None] | None:
    """A93 (owner decision 1, M2): (item, first posed at) for every item POSED to
    the student and not yet graded — every session's ungraded steps (ended or
    closed sessions too) and its probe item, each ungraded review item, every
    unanswered post-test pose (expired too), and the help ledger's 'posed' rows.

    Spec §13 A101 (focused review M1): an item that is CURRENTLY OPEN — an
    ungraded step, an open review entry, a probe's current item, an unanswered
    pose — is always in the set, whether or not the student has evidence on it
    (review serves previously-seen items; dropping them reopened laundering).
    The seen filter (`seen_hashes`) applies only to the ledger's historical
    'posed' rows. (M2 (a)/(d)): the candidates are ranked by posed time and cut
    to the newest LOOP_SCAN_POSED_MAX BEFORE any item is loaded, then loaded in
    batched reads (`items_by_ids`, `items_by_hash`). The second element is the
    edge of what was left out — the newest candidate beyond the window, or
    (minor 3) the oldest ledger row read when that read hit its row limit —
    at which the caller records an 'unscanned' marker, so every older ungraded
    item grades as assisted. None when any of it cannot be read."""
    try:
        open_ids: dict[str, datetime | None] = {}  # check item id → first posed
        open_hashes: dict[str, datetime | None] = {}  # question hash → first posed

        def keep(store: dict, key, at) -> None:
            if not key:
                return
            if key not in store or (at is not None and (store[key] is None or at < store[key])):
                store[key] = at

        for row in page_all(
            table("sessions"),
            "id,steps:loop_state->steps,probe:loop_state->probe",
            filters={"user_id": f"eq.{user_id}", **NOT_REVIEW},
            order="id",
        ):
            for entry in (row.get("steps") or {}).values():
                if isinstance(entry, dict) and entry.get("graded_at") is None:
                    keep(open_ids, entry.get("check_item_id"), _ts(entry.get("first_shown_at")))
            cur = (row.get("probe") or {}).get("current") if isinstance(row.get("probe"), dict) else None
            if isinstance(cur, dict):
                keep(open_hashes, cur.get("question_hash"), None)
        for row in page_all(
            table("sessions"),
            "id,open:loop_state->open",
            filters={"user_id": f"eq.{user_id}", "mode": "eq.review", "loop_state->open": "not.is.null"},
            order="id",
        ):
            for key, entry in (row.get("open") or {}).items():
                if (
                    isinstance(entry, dict)
                    and not str(key).startswith("fc:")
                    and entry.get("graded_at") is None
                ):
                    keep(open_ids, entry.get("item_id"), _ts(entry.get("served_at")))
        pose_course: dict[str, str] = {}  # a pose names its course: matched on load
        for pose in table(_POSES).select(
            "course_id,question_hash,posed_at",
            filters={"user_id": f"eq.{user_id}", "answered_at": "is.null"},
        ) or []:
            keep(open_hashes, pose.get("question_hash"), _ts(pose.get("posed_at")))
            if pose.get("question_hash"):
                pose_course[pose["question_hash"]] = pose.get("course_id")
        ledger, edge = ungraded_posed_window(user_id, LOOP_SCAN_POSED_MAX)
        ledger_hashes = {qh for qh, _ in ledger}
        historical: dict[str, datetime | None] = {}
        for qh, at in ledger:
            if qh in open_hashes:
                keep(open_hashes, qh, at)  # open: always scanned; the earliest pose counts
            else:
                keep(historical, qh, at)
        if historical:  # M1: the seen filter reads the historical rows only
            seen = seen_hashes(user_id)
            historical = {qh: at for qh, at in historical.items() if qh not in seen}
        oldest = datetime.min.replace(tzinfo=timezone.utc)
        candidates = sorted(
            [("id", k, at) for k, at in open_ids.items()]
            + [("hash", k, at) for k, at in open_hashes.items()]
            + [("ledger", k, at) for k, at in historical.items()],
            key=lambda c: c[2] or oldest,
            reverse=True,
        )
        kept, left = candidates[:LOOP_SCAN_POSED_MAX], candidates[LOOP_SCAN_POSED_MAX:]
        overflow = (left[0][2] or now) if left else None
        if edge is not None:
            overflow = edge if overflow is None else max(overflow, edge)
        found: dict[str, tuple] = {}
        ids = sorted(k for kind, k, _ in kept if kind == "id")
        for item in items_by_ids(ids) if ids else []:
            found.setdefault(item.question_hash, (item, open_ids.get(item.id)))
        hashes = sorted(k for kind, k, _ in kept if kind != "id" and k not in found)
        for item in items_by_hash(hashes) if hashes else []:
            qh = item.question_hash
            if qh in pose_course and qh not in ledger_hashes and pose_course[qh] != item.course_id:
                continue  # a pose's hash names an item of ITS course only
            found.setdefault(qh, (item, open_hashes.get(qh, historical.get(qh))))
        ranked = sorted(found.values(), key=lambda pair: pair[1] or oldest, reverse=True)
        return ranked, overflow
    except Exception as exc:
        logger.warning("posed items could not be read (%s)", type(exc).__name__)
        return None


def _mark_revealed(state: dict, hashes, mark: dict | None) -> None:
    """The loop_state fallback of a failed learning_reveals write: hashes join
    loop_state["revealed"] (A23); a marker joins loop_state["reveal_unscanned"]."""
    if hashes:
        revealed = list(state.get("revealed") or [])
        state["revealed"] = revealed + [h for h in hashes if h not in revealed]
    if mark is not None:
        state["reveal_unscanned"] = [*(state.get("reveal_unscanned") or []), mark]


def _persist_reveals(
    user_id: str, session_id: str | None, hashes, *, unscanned: bool, source: str, at: datetime
) -> None:
    """Record the reveals (or the marker) in learning_reveals; on a failed write
    fall back to the session's loop_state; if that fails too, log an ERROR."""
    try:
        if unscanned:
            record_unscanned(user_id, session_id=session_id, source=source, at=at)
        elif hashes:
            record_reveals(user_id, hashes, session_id=session_id, source=source)
        return
    except Exception:
        logger.warning("learning_reveals write failed; falling back to loop_state", exc_info=True)
    mark = {"at": at.timestamp(), "source": source} if unscanned else None
    try:
        if not session_id:
            raise RuntimeError("no session row to fall back to")
        _update_loop_state(session_id, lambda st: _mark_revealed(st, hashes, mark))
    except Exception:
        logger.error("served reveals of %s LOST (both stores failed)", user_id, exc_info=True)


def _reveal_floor(user_id: str, item, posed_at: datetime | None = None) -> int:
    """The lowest rung a grade of `item` may claim — A93's help floor (owner
    decision 1): the MAX help ever recorded for (student, item) in the help
    ledger, across every session and surface (a served reveal counts as
    RUNG_NO_CREDIT_MIN); RUNG_NO_CREDIT_MIN when the item is revealed by the
    evidence journal or a session's revealed list (A23); RUNG_ASSISTED_MIN while
    an 'unscanned' marker lands at or after the item's FIRST ungraded pose (or
    `posed_at`; None: any marker). A failed read is RUNG_NO_CREDIT_MIN (fail
    closed, minor 8)."""
    try:
        floor = max_help(user_id, item.question_hash)
        if item.question_hash in revealed_hashes(user_id):
            floor = max(floor, RUNG_NO_CREDIT_MIN)
        first = earliest_open_pose(user_id, item.question_hash)
        anchor = min((t for t in (first, posed_at) if t is not None), default=None)
        if floor < RUNG_ASSISTED_MIN and unscanned_since(user_id, anchor):
            floor = RUNG_ASSISTED_MIN
    except Exception:
        logger.warning("help ledger reads failed; the grade carries no credit", exc_info=True)
        return RUNG_NO_CREDIT_MIN
    return floor


def _refloor(evidence: list, user_id: str, item, posed_at: datetime | None, used: int) -> int:
    """A93: the help floor re-read INSIDE the grading claim, right before the one
    evidence write — so help served while the grade ran (a hint in another
    session, a reveal streaming meanwhile) is seen. Raises the pending Evidence
    rows of `item` to the new floor (apply_graph_update re-derives the weight);
    returns the rung the grade carries."""
    floor = _reveal_floor(user_id, item, posed_at)
    if floor > int(used):
        for row in evidence:
            if row.get("question_hash") == item.question_hash and int(row.get("max_rung") or 0) < floor:
                row["max_rung"] = floor
                if floor >= RUNG_ASSISTED_MIN:
                    row["assisted"] = True
    return max(floor, int(used))


def _tag_planning_evidence(pending: list, item, *, synthetic_idk: bool, previously_seen: bool,
                           operation_id: str | None = None, observed_at: float | None = None) -> None:
    """Actual probe/check grades, goal or not; never answers or inferred history."""
    provenance = PlanningProvenance(
        check_item_id=item.id, difficulty=item.difficulty,
        synthetic_idk=synthetic_idk, previously_seen=previously_seen,
    ).model_dump()
    for row in pending:
        if row.get("question_hash") == item.question_hash and row.get("check_item_id") == item.id:
            row["planning_provenance"] = provenance
            if operation_id is not None:
                row["operation_id"] = operation_id
                row["observed_at"] = datetime.fromtimestamp(observed_at, tz=timezone.utc).isoformat()


def _ledger(write, *args, **kwargs) -> None:
    """A help-ledger write under the accepted DB-down rule: the session-local
    record (the step's rung, loop_state["revealed"]) stands and an ERROR is
    logged; never raises."""
    try:
        write(*args, **kwargs)
    except Exception:
        logger.error("help ledger write %s failed", getattr(write, "__name__", "?"), exc_info=True)


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


# ── PKG-10: the misconception confrontation line (spec §3.3, §13 A15) ─────

#: Spec §13 A75: the tiers a confrontation line is served on — exactly the slots
#: whose misconception_confront eval scores 1.0 on every served gate (pinned to
#: baselines.json by tests/test_learning_misconceptions.py). A turn model_tier
#: routes elsewhere (the §3.5 soft-level / deep-cap downgrade) carries no line,
#: and the marker waits for one that does.
CONFRONT_TIERS: frozenset[str] = frozenset({"deep"})

#: Spec §13 A75: the confrontation mapped onto the structured turn's fields (A46).
_CONFRONT_LINE = (
    'The student holds misconception "{text}". This turn, confront it instead of '
    "correcting it: the key idea names what to test, never the correct rule; the body sets "
    "up ONE concrete case of this concept where the belief predicts something the student "
    "can check, without working the case out or saying which result is right; the question "
    "asks the student to work that case out and compare it with their belief."
)


def _confrontation_line(loop_state: dict) -> str | None:
    """PKG-10: the line for the misconception grade_answer recorded (the
    loop state's `confront` marker), or None. The text is the marked item's
    decrypted `common_wrong` entry for the marker's key, collapsed to one line
    with its control tags neutralised (item-drafted text may never forge a
    [VERDICT: …] or [STUDENT MESSAGE] block). No marker, a missing item, a
    failed read or an unknown key → None, no error. Reads only: the turn that
    serves the line clears the marker in its compare-and-set save."""
    text = _confrontation_text(loop_state)
    return confront_line_for(text) if text else None


def _confrontation_text(loop_state: dict) -> str | None:
    """The marked item's stored wrong-reason text for the marker's key, or
    None (no marker, a missing item, a failed read, an unknown key)."""
    confront = confront_of(loop_state)
    if confront is None:
        return None
    try:
        item = get_check_item(confront["check_item_id"])
    except Exception as exc:
        logger.warning("confrontation: check item read failed (%s)", type(exc).__name__)
        return None
    if item is None:
        return None
    for entry in item.common_wrong or []:
        if entry.key == confront["wrong_key"] and entry.text:
            return entry.text
    return None


def confront_line_for(text: str) -> str | None:
    """The confrontation line for one wrong-reason text: collapsed to one line,
    its control tags neutralised, its double quotes made single (it stays inside
    the line's quoted span); None for a text with nothing left. Shared
    with the eval (tests/evals/misconception_confront.py) so it scores the
    line production sends."""
    # one line, no control tag, and never a double quote: the text stays inside
    # the line's one quoted span (it can never close it and write an instruction)
    text = " ".join(neutralise_control_tags(text or "").replace('"', "'").split())
    return _CONFRONT_LINE.format(text=text) if text else None


def with_confrontation(prefix: str, line: str | None) -> str:
    """The turn prefix with the confrontation line right after the phase
    instruction (before the context blocks and the student's words)."""
    return f"{prefix}\n{line}" if line else prefix


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
        self.observer_body = body
        self.observer_history: list = []
        self.served_model: str | None = None
        self.mode = body.mode
        self.message, self.kind, self.persist_user_row = message, kind, persist_user_row
        # an [ACTION: ...] turn's message is server text (so is the prequestion
        # cue, spec §13 A138); every other is the student's
        self.trusted, self.instruction = kind in ("action", "prequestion"), None
        self.loop_on, self.refused = loop_on, refused
        self.request_id = _request_id(request)
        # PKG-14 (A20): an arm session is never downgraded; it pauses at hard
        self.arm = _arm_for(body.user_id, request)
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
        # A committed grade still needs a delivered result, even if its source
        # item was withdrawn before feedback/recovery. Keep only its recorded
        # metadata; never reconstruct a prompt, reference or model context.
        self.withdrawn_feedback = bool(
            self.withdrawn and isinstance(entry, dict)
            and entry.get("graded_at") is not None and entry.get("feedback_given") is not True
        )
        self.active = active if self.withdrawn_feedback else (None if self.withdrawn else active)
        view = dict(self.state, current=self.active)
        self.phase = _turn_phase(self.kind, _phase_for(view))
        self.step = _step_state(self.state, self.active)
        self.entry = dict(entry) if (self.active and isinstance(entry, dict)) else {}
        self.node_id = (_node_for_item(self.user_id, self.item) if self.item is not None
                        else self.entry.get("node_id") if self.withdrawn_feedback else None)
        # A27: teach turns take the current plan concept's band
        self.concept_node = self.node_id or self.state.get("concept")
        learner = _learner_state(self.user_id, self.concept_node)
        self.band, self.p_known = _band_of(learner)
        self.variant = arms.variant_for(self.user_id, self.concept_node or "", self.arm)
        self.verdict = verdict or (
            self.entry.get("last_verdict") if self.phase == "feedback" else None
        )
        self.answer_released = self.item is not None and self.phase == "feedback" and self.verdict != "correct"
        self.rung = self.step.rung if self.phase == "hint" else Rung.H0
        prereq = _prereq_proficient(self.user_id, self.concept_node) if self.concept_node else True
        # spec §13 A122: the band format reads policy.attempt_first off this view
        self.learner_view = _learner_view(learner, band=self.band, prereq_proficient=prereq)
        self.ceiling, self.ceiling_reason = _ceiling_for(
            step=self.step,
            learner=self.learner_view,
            message=self.message,
            independent_s=_seconds_since(self.step.first_shown_at, _now_s()),
            variant=self.variant,
            teach_attempt=self._teach_attempt(),
            # spec §13 A122: band control's ceiling clause for this concept
            band_delta=_band_ceiling_delta(self.state, self.concept_node),
        )
        self.planned = None
        self.given = ""
        self.confront_line, self.confront_used = None, None
        self.run_requests = 0
        self.tier, self.text, self.paused = "none", None, False
        self.revealed_hash, self.served_as_h6 = None, False
        self.reveal_hashes: list[str] = []  # A88: the open posed items this turn stated
        self.reveal_unscanned = False  # A88: its open items could not be read
        self.reveal_overflow = None  # A93: posed items beyond the scan window
        self.reveal_fallback: tuple | None = None  # a failed learning_reveals write
        self.retrieval_failed = False  # A128: this turn's course-material retrieval failed
        # Spec §13 A121, both settled in _plan before the model runs: the turn
        # poses the concept's next check (so it ends without its own question),
        # and the turn opens with the verdict on the reply to the tutor's question
        self.poses_check = False
        self.answer_check = False
        # Spec §13 A121 (v2): a teach turn's (concept name, cursor reason), set in _plan
        self.focus: tuple[str, str] | None = None
        # Spec §13 A121: the v2 variant, resolved ONCE for the turn
        self.v2 = _tutor_v2_on(self.user_id)
        # Spec §13 A138 / A139: their flags, each resolved ONCE for the turn
        self.pq_on = _prequestion_on(self.user_id)
        self.se_on = _self_explain_on(self.user_id)
        # A138: the plan concept's answered prequestion this teach turn explains
        self.pq_record, self.pq_item = self._prequestion_to_explain()
        # A138: this feedback turn hands the student to the next segment's
        # prequestion card, so it is served without its own question (set in _plan)
        self.pq_follows = False
        # A139: the self-explanation prompt this turn's question becomes (set in _plan)
        self.se_prompt: dict | None = None
        # A139: the student replied to the last prompt; this turn acknowledges it
        self.se_ack = self_explain.ack_due(self.state) if self.se_on else None

    def _prequestion_to_explain(self) -> tuple[dict | None, object | None]:
        """Spec §13 A138: (record, item) of the plan concept's ANSWERED
        prequestion when this turn explains it — a teach turn with no active
        item (a chat or action turn, or the answer route's own), flag on. The
        explanation is owed until a turn serves it, so a failed explaining turn
        is retried by the next one. A withdrawn item (A23) has nothing left to
        explain: (record, None), and the turn closes the record."""
        if not getattr(self, "pq_on", False) or self.phase != "teach" or self.item is not None:
            return None, None
        if self.withdrawn_feedback or self.kind not in ("chat", "action", "prequestion"):
            return None, None
        rec = prequestion_rules.answered(self.state, self.state.get("concept"))
        if rec is None:
            return None, None
        try:
            item = get_check_item(rec["check_item_id"]) if rec.get("check_item_id") else None
        except Exception:
            logger.warning("prequestion item unreadable; this turn does not explain it", exc_info=True)
            return None, None
        return rec, item

    def _self_explain_juncture(self) -> dict | None:
        """Spec §13 A139: the self-explanation prompt this turn carries, or None.
        Decided in code, flag on: a hint turn at H4 (the worked example) or H5/H6
        (a shown solution — a leaking payload served as H6 counts as H6), or a
        feedback turn that released the answer, or the feedback turn of the
        session's first check on the concept answered correctly with no help.
        Never twice on a concept in a session (SELF_EXPLAIN_MAX_PER_CONCEPT, the
        first juncture takes it), never in a quiz-ask session (its sheet shows
        no reply box), and never on a confronting turn (PKG-10): a recorded
        misconception's contradiction needs the turn's question, and the
        prompt then waits for the concept's next juncture."""
        if not self.se_on or self.item is None or self.withdrawn_feedback or self.paused:
            return None
        if self.phase not in ("hint", "feedback") or not _auto_poses_checks(self.state):
            return None
        if self.tier != "none" and self.confront_line is not None:
            return None  # a template turn serves no confrontation line
        node = self.node_id or self.concept_node
        if not self_explain.may_prompt(self.state, node):
            return None
        rung = int(Rung.H6) if self.served_as_h6 else int(self.rung)
        first = (
            self.phase == "feedback"
            and self.verdict == "correct"
            and self_explain.first_unhelped_on_concept(self.state.get("steps") or {}, node, self.active)
        )
        found = self_explain.juncture(
            phase=self.phase, rung=rung, answer_released=self.answer_released, first_correct=first
        )
        if found is None:
            return None
        juncture, prompt_key = found
        return {
            "id": uuid.uuid4().hex,
            "node_id": node,
            "juncture": juncture,
            "prompt_key": prompt_key,
            "question_hash": self.active,
            "rung": rung if self.phase == "hint" else int(self.entry.get("max_rung") or 0),
            "prompted_at": _now_s(),
        }

    def _prequestion_follows(self) -> bool:
        """Spec §13 A138 × A121: whether this FEEDBACK turn's completion starts a
        new segment whose prequestion is then posed — settled before the model
        runs, so the turn is served without its own question (the card is the
        one open prompt). A read-only trial of `_apply_turn`'s cursor move and of
        the pose on a copy of the loop state. A turn that carries a
        self-explanation prompt never hands over: the prompt is about the
        concept just finished and comes first; the next segment's prequestion is
        posed when the prompt closes. A failed read plans the turn with its
        question."""
        if not self.pq_on or self.phase != "feedback" or self.withdrawn_feedback or self.se_prompt:
            return False
        entry = (self.state.get("steps") or {}).get(self.active)
        if not isinstance(entry, dict):
            return False
        trial = copy.deepcopy(self.state)
        try:
            if trial.get("current") == self.active:
                trial["current"] = None
            _count_feedback_and_move(trial, trial["steps"][self.active])
            return _pose_prequestion(self.user_id, self.course_id, trial, now=_now_s()).item is not None
        except Exception:
            logger.warning("prequestion trial failed; the turn keeps its question", exc_info=True)
            return False

    def _answer_check_due(self) -> bool:
        """Spec §13 A121: this turn answers the student's reply to the tutor's
        own question — with the v2 variant on, a student chat
        message in the teach phase (no active item: a check item is graded only
        by the grader, A16) right after a served turn that ended with the
        tutor's open question (OPEN_QUESTION_KEY). Read from loop state, never
        from the text."""
        return (
            self.v2
            and self.kind == "chat"
            and not self.trusted
            and self.phase == "teach"
            and self.item is None
            and not self.withdrawn_feedback
            and self.state.get(OPEN_QUESTION_KEY) is True
        )

    def _check_follows(self) -> bool:
        """Spec §13 A121: whether this teach turn's completion poses the concept's
        next check (A27 trigger 1: it brings `teach_turns` to
        LOOP_TEACH_TURNS_BEFORE_CHECK) — settled BEFORE the model runs, so the
        turn is planned and served without a question of its own (the check card
        is the one open prompt). A read-only trial of `_activate_next_item` on a
        copy of the loop state: the same selection `_apply_turn` then makes for
        real (which never poses a check on a turn planned with its question). A
        failed read plans the turn with its question."""
        if (
            self.kind not in ("chat", "action")
            or self.phase != "teach"
            or self.withdrawn_feedback
            or not _auto_poses_checks(self.state)
        ):
            return False
        trial = copy.deepcopy(self.state)
        if self.withdrawn and trial.get("current") == self.withdrawn:
            trial["current"] = None
        if (
            trial.get("current")
            or not trial.get("concept")
            or int(trial.get("teach_turns") or 0) + 1 < LOOP_TEACH_TURNS_BEFORE_CHECK
        ):
            return False
        try:
            return _activate_next_item(self.user_id, self.course_id, trial, now=_now_s()) is not None
        except Exception:
            logger.warning("check activation trial failed; the turn keeps its question", exc_info=True)
            return False

    def _reply_states_posed_answer(self) -> bool:
        """Spec §13 A121 (no reveal): a verdict on the student's reply must never
        confirm a check item's answer. True when the reply states the answer of
        an item posed to this student and not yet graded (A93's scan set, read
        strictly as served text), or when that cannot be checked — the set is
        unreadable or the scan raises (fail closed). The turn then asks for no
        verdict at all. Items beyond the scan window are A93's: the turn's own
        served-text scan records the 'unscanned' marker at the window's edge,
        so each grades with no unassisted credit."""
        got = self._scan_set()
        if got is None:
            return True
        scan, _overflow = got
        try:
            return bool(scan.stated(self.message))
        except Exception:
            logger.warning("the reply could not be scanned; no verdict this turn", exc_info=True)
            return True

    def _plan_focus(self) -> tuple[str, str] | None:
        """Spec §13 A121 (`loop_tutor_v2`): (the plan's current concept NAME, why
        the cursor is on it) for a teach turn — concept and reason from loop
        state (`plan_focus`), the name from the student's graph. None off the
        variant, outside the teach phase, with no plan concept, or when the
        name cannot be read (the turn is then served without it, never failed)."""
        if not self.v2 or self.phase != "teach":
            return None
        focus = plan_focus(self.state)
        if focus is None:
            return None
        node_id, reason = focus
        try:
            name = (_plan_node_names(self.user_id, [node_id]).get(node_id) or "").strip()
        except Exception:
            logger.warning("plan focus: the concept name could not be read; the turn goes without it", exc_info=True)
            return None
        return (name, reason) if name else None

    def _teach_attempt(self) -> bool:
        """PKG-14 (A85): the student's teach-phase message is a genuine attempt
        for THIS turn's ceiling when the existing rule says so, timed from the
        loop's previous served turn (`loop_state.served_at`). Only a student chat
        message on a teach turn with no active item; no anchor → no raise. It
        moves no evidence and no state (spec §1)."""
        if self.phase != "teach" or self.item is not None or self.kind != "chat" or self.trusted:
            return False
        anchor = self.state.get("served_at")
        if isinstance(anchor, bool) or not isinstance(anchor, (int, float)):
            anchor = None
        activity_at, unresolved = turn_activity.timing(self.state)
        if unresolved:
            return False  # A crashed/unknown turn is not independent work time.
        if activity_at is not None:
            anchor = activity_at if anchor is None else max(float(anchor), activity_at)
        failed = _FAILED_TURN_ANCHORS.get(self.session_id)
        if failed is not None:
            anchor = failed if anchor is None else max(float(anchor), failed)
        if anchor is None:
            return False
        return gates.teach_attempt(
            self.message,
            max(0.0, _now_s() - float(anchor)),
            self.band,
            time_scale=config.LEARNING_GATE_TIME_SCALE,
            variant=self.variant,
        )

    @property
    def slot(self) -> str:
        return LOOP_TIER_SLOTS[self.tier]

    def budget_counters(self, *, include_current_run: bool = False) -> dict:
        tutor = int(self.state.get("tutor_requests") or 0)
        deep = int(self.state.get("deep_requests") or 0)
        if include_current_run and self.run_requests:
            # The current turn has not completed/saved yet. Mirror _apply_turn's
            # existing units without mutating its counters: ordinary turns add
            # one, while confronting deep turns count every known model request.
            tutor += 1
            if self.tier == "deep":
                deep += self.run_requests if self.confront_used is not None else 1
        return {
            "session_tutor_requests": tutor,
            "session_deep_requests": deep,
            "arm_session": bool(self.arm),  # PKG-14 (A20): both variants of an arm alike
        }

    def history(self) -> list:
        history = _load_loop_history(
            self.session_id,
            user_id=self.user_id,
            course_id=self.course_id,
            loop_state=self.state,
        )
        return _with_goal_context(history, self.state, self.user_id)

    def plan(self, decision) -> None:
        """Tier + run assembly for `decision`, the ai_budget verdict the calling
        run site just read (invariant 23). Idempotent for the same decision.
        A93: the help this turn will serve is recorded in the help ledger HERE —
        before a token or the deterministic payload goes out."""
        if self.planned is decision:
            return
        self._plan(decision)
        self._record_planned_help()

    def _record_planned_help(self) -> None:
        """A93 (owner decision 1): a hint turn's rung on its item (H6 when a
        leaking deterministic payload is served as H6), and an H4 sibling payload
        on the SIBLING (its worked answer is shown: RUNG_NO_CREDIT_MIN)."""
        if self.paused or self.phase != "hint" or self.item is None:
            return
        if self.text is None and self.tier == "none":
            return  # nothing is served
        rung = int(Rung.H6) if self.served_as_h6 else int(self.rung)
        _ledger(record_help, self.user_id, self.item.question_hash, rung, source="loop", session_id=self.session_id)
        if self.revealed_hash:
            _ledger(
                record_help,
                self.user_id,
                self.revealed_hash,
                RUNG_NO_CREDIT_MIN,
                source="loop",
                session_id=self.session_id,
            )

    def _template_only(self) -> bool:
        """A turn served from a template at every budget level (no model run):
        the probe-phase opener (spec §13 A121, `_LoopOpener`)."""
        return False

    def _plan(self, decision) -> None:
        if self.planned is decision:
            return
        self.planned = decision
        self.tier, self.text, self.paused = "none", None, False
        self.revealed_hash, self.served_as_h6 = None, False
        self.poses_check, self.answer_check, self.focus = False, False, None
        self.pq_follows, self.se_prompt = False, None
        self.retrieval_failed = False
        if decision.pause_novice and self.band == "novice" and self.phase in ("check", "hint"):
            self.paused = True  # novice-band concepts pause at the hard level (§3.5)
            return
        self.text = self._deterministic_text(hard=decision.level == "hard")
        if self.withdrawn_feedback:
            # This is an explicit recorded-result/withdrawal notice, not a
            # substitute model lesson. No assessment content remains servable.
            return
        if self._template_only():
            return  # tier "none": the template is served, nothing else is planned
        # PKG-10 (A15): a recorded misconception makes this a confronting turn
        self.confront_line = self._confront_line()
        if self.phase != "check":  # the pose never reaches the model (A17)
            deep = self.budget_counters()["session_deep_requests"]
            self.tier = routable_tier(
                policy.model_tier(
                    self._tier_phase(),
                    self.band,
                    self.rung,
                    _failed_on_concept(self.state, self.concept_node),
                    self.confront_line is not None,  # misconception_active (PKG-10)
                    deterministic_payload=self.text is not None,
                    budget_level=decision.level,
                    deep_cap_reached=deep >= LOOP_SESSION_MAX_DEEP_REQUESTS,
                    novice_deep_cap_reached=deep >= LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE,
                    arm_session=bool(self.arm),
                )
            )
        if self.tier == "none":
            self.paused = self.text is None
            if not self.paused:
                # spec §13 A139: a template hint or feedback turn at a juncture
                # (an H4 sibling, an H6 answer, the hard-level feedback) closes
                # on the prompt, its one question; no model, so no tier cost
                self.se_prompt = self._self_explain_juncture()
                if self.se_prompt is not None:
                    self.text = self.text + FIELD_JOIN + self_explain.prompt_text(self.se_prompt)
                self.pq_follows = self._prequestion_follows()
            return
        if self.tier not in CONFRONT_TIERS:
            self.confront_line = None  # A75: served only where its eval passes; the marker waits
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
        self.observer_history = history
        # N1: the provenance the served leak check reads (and the scan set's)
        self.given = _visible_text(
            history,
            item_prompt=self.item.prompt if self.item is not None else "",
        )
        # Spec §13 A121: the turn template's two directives, from loop state
        self.poses_check = self._check_follows()
        self.answer_check = self._answer_check_due() and not self._reply_states_posed_answer()
        # Spec §13 A121 (v2): a teach turn names the plan's concept and why it is there
        self.focus = self._plan_focus()
        # Spec §13 A139: a juncture's prompt replaces the model's question in the
        # served render (the request is unchanged); A138: a feedback turn that
        # hands over to the next segment's prequestion is served without one
        self.se_prompt = self._self_explain_juncture()
        self.pq_follows = self._prequestion_follows()
        explaining = self.pq_item is not None  # A138: this teach turn explains a prequestion
        self.prefix = phase_prefix(
            phase=self.phase,
            band=self.band,
            ceiling=model_ceiling,
            item_prompt=self.item.prompt if (item_phase and self.item) else None,
            item_format=self.item.format if (item_phase and self.item) else None,
            answer_released=self.answer_released,
            verdict=self.verdict if self.phase == "feedback" else None,
            # §3.3 novice rows (spec §13 A122): worked example first when the
            # prerequisite is not known — policy.attempt_first decides
            attempt_first=policy.attempt_first(self.learner_view),
            v2=self.v2,
            poses_check=self.poses_check,
            answer_check=self.answer_check,
            plan_reason=self.focus[1] if self.focus else None,
            prequestion_block=(
                prequestion_item_block(
                    self.pq_item.prompt, self.pq_item.format, prequestion_rules.option_lines(self.pq_item)
                )
                if explaining
                else None
            ),
            self_explain_ack=self.se_ack is not None,
        )
        if self.confront_line:
            # PKG-10: right after the phase instruction, before the context blocks
            # and the student's words — trusted route text for THIS turn only
            # (never the stored brief, the history or the system prompt, A19)
            self.prefix = with_confrontation(self.prefix, self.confront_line)
            self.confront_used = confront_of(self.state)
        assembly: dict = {}  # A128: what the context assembly found
        context_item = self.item
        extra_blocks: list[str] = []
        if explaining:
            # spec §13 A138: the explanation draws on the prequestion item's own
            # source passages (resolved for this student, A17/A18) instead of a
            # retrieval keyed on the route's cue, and gets the released answer as
            # data — the model never states it (the lead is code's, A51 m1)
            context = context._replace(rag_k=0, source_chunks=LOOP_SOURCE_CHUNKS_MAX)
            context_item = self.pq_item
            extra_blocks.append(prequestion_answer_block(self.pq_item.reference_answer))
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
            item=context_item,
            learning_loop=self.loop_on,
            loop_turn=turn_limits(
                self.phase,
                model_ceiling,
                self.answer_released,
                question=not self.poses_check,
                answer_check=self.answer_check,
                v2=self.v2,
            ),
            trusted=self.trusted,
            instruction=self.instruction,
            nonce=nonce,
            v2=self.v2,
            focus_block=plan_focus_block(self.focus[0]) if self.focus else None,
            extra_blocks=extra_blocks,
            out=assembly,
        )
        self.retrieval_failed = assembly.get("retrieval") == "failed"
        self.deps.loop_leak = self._leak_guard()  # N1: the validator's guard

    def _confront_line(self) -> str | None:
        """The confrontation line this turn may carry (PKG-10), or None. Not on
        a check pose (no model), a correct-answer feedback turn, a turn on
        another concept than the marker's (fix round F2), or — the answer
        unreleased — a model ceiling below MISCONCEPTION_CONFRONT_MIN_RUNG. The
        text is model-written (item drafting), so while the active item's answer
        is unreleased it must not state it — leak.confront_text_states_answer,
        the strict check drafting also refuses with (F3, spec §13 A77: number
        words anywhere, no provenance — fix round 5); a text that states it is
        withheld and its marker waits."""
        if self.phase == "check" or (self.phase == "feedback" and self.verdict == "correct"):
            return None
        marker = confront_of(self.state)
        if marker is None or marker["node_id"] != self.concept_node:
            return None
        ceiling = clamp_model_ceiling(
            self.rung if self.phase == "hint" else self.ceiling, self.answer_released
        )
        if not self.answer_released and ceiling < MISCONCEPTION_CONFRONT_MIN_RUNG:
            return None  # the ceiling wins: a contradiction names specifics (H3+)
        text = _confrontation_text(self.state)
        line = confront_line_for(text) if text else None
        if line is None or self.item is None or self.answer_released:
            return line
        # the item-drafted text is checked, not the route's own wording around it —
        # by the one function drafting also refuses with (spec §13 A77): stored ==
        # servable. Answer unreleased here, so the rung is below H6.
        answer = self._item_answer()
        answer.pop("reference")
        leaked = confront_text_states_answer(text, **answer)
        return None if leaked else line

    def _tier_phase(self) -> str:
        """PKG-06's TurnPhase: the feedback verdict rides the phase value."""
        if self.kind == "opener":
            return "opener"
        if self.phase == "feedback":
            return "feedback_correct" if self.verdict == "correct" else "feedback_wrong"
        return self.phase  # "teach" | "hint"

    def _deterministic_text(self, *, hard: bool) -> str | None:
        if self.withdrawn_feedback:
            result = {
                "correct": "Your answer was recorded as correct.",
                "not_yet": "Your answer was recorded as not yet correct.",
                "idk": "Your 'I don't know' response was recorded.",
            }.get(self.verdict, "Your earlier result remains recorded.")
            return _WITHDRAWN_FEEDBACK.format(result=result)
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
        if self.phase == "teach" and hard and self.pq_item is not None:
            # spec §13 A138: the answer follows promptly whatever the budget —
            # at the hard level as a template (no model): the answer, one line
            return prequestion_rules.answer_lead(self.pq_item) + FIELD_JOIN + prequestion_rules.HARD_LEVEL_LINE
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
        # PKG-10 (fix round F4): the model requests this turn cost (a run, its
        # output/leak retries, a continuation) — a confronting turn counts them all
        self.run_requests += _requests_of(run_result)
        self.served_model = served_model_name(run_result, self.slot)
        record_agent_usage(
            run_result,
            feature="loop_tutor",
            task=self.slot,
            user_id=self.user_id,
            session_id=self.session_id,
        )

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
        answer is released (its lead, m1), the text the model was given and —
        on a feedback turn — the grader's verdict, whose line leads it (A121)."""
        return {
            **self._item_answer(),
            "answer_released": self.answer_released,
            "given": self.given,
            "verdict": self._lead_verdict(),
        }

    def _prequestion_lead(self) -> str:
        """Spec §13 A138: what code serves above the model text of a turn that
        explains an answered prequestion — the correct answer (A51 m1: the
        model never states it); "" on every other turn and on a template turn
        (whose text already carries it)."""
        if self.tier == "none" or self.pq_item is None:
            return ""
        return prequestion_rules.answer_lead(self.pq_item) + FIELD_JOIN

    def _lead_verdict(self) -> str | None:
        """The grader verdict whose plain line code serves first: a feedback
        turn's, with the v2 variant on (spec §13 A121)."""
        return self.verdict if self.phase == "feedback" and self.v2 else None

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
        ladder line, replaces it). Code's lead goes in front (`served_lead`: a
        feedback turn's verdict line, A121, then the released answer, m1), so
        the verdict is the first thing the stream shows."""
        if self.tier == "none" or self.item is None:
            return self._prequestion_lead() + text
        lead = served_lead(
            reference=self.item.reference_answer,
            answer_released=self.answer_released,
            verdict=self._lead_verdict(),
        )
        if self.answer_released:
            return lead + text
        spans = leak_spans(
            emitted=text, given=self.given, **_item_check_kwargs(**self._item_answer())
        )
        return lead + (_cut_before_leak(text, spans) if spans else text)

    def _render_kwargs(self) -> dict:
        """`served_render` / `served_partial` keywords for this turn (A121; A138:
        a turn that hands over to a prequestion card asks nothing itself; A139:
        a juncture's prompt is the turn's question)."""
        kwargs = {
            "phase": self.phase,
            "rung": self._leak_rung(),
            "verdict": self.verdict,
            "poses_check": self.poses_check or self.pq_follows,
            "answer_check": self.answer_check,
            "v2": self.v2,
        }
        if self.se_prompt is not None:
            kwargs["question_text"] = self_explain.prompt_text(self.se_prompt)
        return kwargs

    def render(self, out) -> str:
        """The served render of the model's structured turn (`served_render`)."""
        return served_render(out, **self._render_kwargs())

    def render_partial(self, partial) -> str:
        """The streamed partial as served (the same fields and template)."""
        return served_partial(partial, **self._render_kwargs())

    def serve(self, text: str) -> str:
        """stream_structured_turn's `transform_final`: the served text of the
        final render (`served_model_text`)."""
        if self.tier == "none" or self.item is None:
            return self._prequestion_lead() + text
        served, _ = served_model_text(text, leak_rung=self._leak_rung(), **self._item_leak_kwargs())
        return served

    def _leak_checked(self, reply: str) -> tuple[str, bool]:
        """Model-written text is leak-checked against the ACTIVE item at the rung
        it is served at (`_leak_rung`; A34: the item's structured final answer),
        through `served_model_text` (strict; the released lead in front)."""
        if self.tier == "none" or self.item is None:
            return self._prequestion_lead() + reply, False
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
                variant=arms.variant_for(
                    self.user_id, entry.get("node_id") or self.node_id or "", self.arm
                ),
                session_id=self.session_id,  # A82: per-session cost attribution
                earnest_blocked=entry.get("earnest_blocked") is True,  # A109
                # A128: the step's teaching ran with a failed retrieval
                retrieval=(
                    _RETRIEVAL_FAILED_VALUE
                    if entry.get(_RETRIEVAL_KEY) == _RETRIEVAL_FAILED_VALUE
                    else None
                ),
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
        with self.__dict__.setdefault("_scan_lock", threading.Lock()):
            self._scan_served(reply, whole=True)  # A105: the final text, whole
            self._record_served()
        activity_write = {"require_open": True, "require_existing": True} if getattr(self, "activity_id", None) else {}
        saved = _update_loop_state(
            self.session_id, lambda state: self._apply_turn(state, out), **activity_write
        )
        self._emit_reveal()
        if out.get("step") is not None:
            self._emit_step(out["step"])
        check = None
        if out.get("activated"):
            item = get_check_item(out["activated"])
            # A122: an item that opens on the worked example says so — the client asks for it now
            owed = _worked_example_owed(self.user_id, saved, out.get("activated_qh"))
            check = _pose_payload(item, worked_first=owed) if item is not None else None
            if item is not None:  # A93: posed — in the scan set until graded
                _ledger(record_posed, self.user_id, item.question_hash, source="loop", session_id=self.session_id)
        if self.persist_user_row:
            save_message(self.session_id, "user", self.message)
        save_message(self.session_id, "assistant", reply, merged or None)
        if check is not None:
            save_message(self.session_id, "assistant", check["prompt"])
        teach_prompts = self._after_teach_prompts(out)
        if self.persist_user_row:
            events_service.log_event(
                "chat.message_sent",
                category="usage",
                user_id=self.user_id,
                request_id=self.request_id,
                payload={"mode": self.mode, "session_id": self.session_id},
                content=self.message,
            )
        if self.kind == "chat" and self.persist_user_row:
            # Observe only after both message rows persist. The shared helper
            # catches scheduling failures; no router answer controls teaching.
            _observe_persisted_turn(
                self.observer_body,
                history=self.observer_history,
                ran_on=(self.tier, self.served_model),
                request_id=self.request_id,
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
            **_materials_notice(out),
            **teach_prompts,
            # spec §13 A138: the answer route's turn (present only there)
            **({"prequestion_answered": True} if self.kind == "prequestion" else {}),
        }

    def _after_teach_prompts(self, out: dict) -> dict:
        """Spec §13 A138 / A139, after the save that recorded this turn: the
        prompts' rows and events, and the response keys — `prequestion` (the
        card this turn posed) and `self_explain` (the prompt this turn's
        question is), each present only when there is one (never null), so a
        flag-off response is the one it was. Never raises into the turn."""
        keys: dict = {}
        try:
            if out.get("pq_superseded"):
                node, rec = out["pq_superseded"]
                _emit_prequestion(
                    self.user_id, self.request_id, self.session_id, node, "superseded",
                    question_hash=rec.get("question_hash"),
                )
            if out.get("pq_resolved"):
                _emit_prequestion(
                    self.user_id, self.request_id, self.session_id, out["pq_resolved"], "resolved",
                    question_hash=(self.pq_record or {}).get("question_hash"),
                )
            pose = out.get("pq_pose")
            if pose is not None:
                payload = _posed_prequestion(self.user_id, self.session_id, self.request_id, pose)
                if payload is not None:
                    keys["prequestion"] = payload
            prompt = out.get("se_prompt")
            if prompt is not None:
                record_self_explain_prompt(
                    prompt, user_id=self.user_id, session_id=self.session_id, course_id=self.course_id
                )
                _emit_self_explanation(self.user_id, self.request_id, self.session_id, prompt, "shown")
                keys["self_explain"] = _self_explain_payload(prompt)
        except Exception:
            logger.warning("teach-prompt bookkeeping failed after the turn was saved", exc_info=True)
        return keys

    def _apply_teach_prompts(self, state: dict, out: dict) -> None:
        """Spec §13 A138 / A139, inside this turn's compare-and-set mutate (no
        side effects; `out` carries what `_after_teach_prompts` does after the
        save).
          • A139: any served turn closes the open self-explanation prompt (the
            student moved on; its row stays 'open': never replied), then opens
            its own; a pending acknowledgement is consumed by this turn.
          • A138: a teach turn served while the concept's card is still open
            supersedes it (the student went on without guessing; nothing was
            revealed, and its item stays out of this session's checks); the
            turn that explained an answered prequestion resolves it; a feedback
            turn that started a new segment poses (or skips) its prequestion —
            unless this turn carries a self-explanation prompt, which comes
            first (the prequestion waits for the prompt to close), or the turn
            was planned with its own question (`_undo_pose`, A121).
        The cleanup halves run whatever the flags say, so a flag turned off
        mid-session leaves nothing open; with both flags off they find nothing."""
        self_explain.close_open(state)
        if self.se_prompt is not None:
            self_explain.record_prompt(state, self.se_prompt)
            out["se_prompt"] = self.se_prompt
        if self_explain.ack_due(state):
            self_explain.set_ack(state, None)
        if self.phase == "teach" and self.kind in ("chat", "action"):
            rec = prequestion_rules.open_record(state, self.concept_node)
            if rec is not None:
                records = dict(prequestion_rules.records(state))
                records[self.concept_node] = {**rec, "status": prequestion_rules.SUPERSEDED}
                state[prequestion_rules.KEY] = records
                out["pq_superseded"] = (self.concept_node, rec)
        if self.pq_record is not None:
            node = self.concept_node
            rec = prequestion_rules.answered(state, node)
            if rec is not None:
                records = dict(prequestion_rules.records(state))
                records[node] = {**rec, "status": prequestion_rules.RESOLVED, "resolved_at": self._now}
                state[prequestion_rules.KEY] = records
                out["pq_resolved"] = node
        if self.phase == "feedback" and self.pq_on and self.se_prompt is None and not self.withdrawn_feedback:
            pose = _pose_prequestion(self.user_id, self.course_id, state, now=self._now)
            if pose.item is not None and not self.pq_follows:
                _undo_pose(state, pose)
                pose = _NO_POSE
            out["pq_pose"] = pose

    def begin_activity(self) -> None:
        """Persist pending timing before planning/model work, including a crash.

        The legacy lazy opener has no session row and earns no teach-attempt
        credit. It keeps its existing no-row contract. All materialised turn
        paths require an acknowledged open-session CAS before dispatch.
        """
        if self.kind == "opener":
            return
        self.activity_id = str(uuid.uuid4())
        now = _now_s()

        def begin(doc: dict) -> None:
            _refuse_while_closing(doc, now)
            turn_activity.begin(doc, self.activity_id, now)

        _update_loop_state(
            self.session_id, begin, require_open=True, require_existing=True
        )

    def touch_served_at(self) -> None:
        """Move failure timing without changing history, verdicts or evidence.

        If a worker dies before this final update, its durable pending marker
        still denies independent-time credit after restart. A superseded
        request cannot overwrite a newer operation's activity.
        """
        now = _now_s()
        _FAILED_TURN_ANCHORS.pop(self.session_id, None)
        _FAILED_TURN_ANCHORS[self.session_id] = now
        while len(_FAILED_TURN_ANCHORS) > ANCHORS_MAX:
            _FAILED_TURN_ANCHORS.pop(next(iter(_FAILED_TURN_ANCHORS)))
        operation_id = getattr(self, "activity_id", None)
        if operation_id is not None:
            try:
                _update_loop_state(
                    self.session_id,
                    lambda doc: turn_activity.interrupt(doc, operation_id, now),
                    require_open=True,
                    require_existing=True,
                )
            except Exception as exc:
                if (isinstance(exc, HTTPException) and exc.status_code == 409
                        and exc.detail == _SESSION_CLOSED):
                    logger.info("Tutor interruption timing skipped: session already closed")
                else:
                    logger.warning("Tutor interruption timing could not be stored", exc_info=True)

    def _scan_set(self):
        """A93: the posed-and-ungraded items (`posed_items`), read ONCE per turn
        (a stream is scanned on every relayed delta) and compiled once
        (learning.served_scan.ScanSet, spec §13 A101): (ScanSet, overflow), or
        None when they cannot be read. The turn's own active item is excluded:
        its leak check is `_leak_checked`'s."""
        if not hasattr(self, "_scan_cache"):
            got = posed_items(self.user_id, now=datetime.now(timezone.utc))
            if got is None:
                self._scan_cache = None
            else:
                active = self.item.question_hash if self.item is not None else None
                items, overflow = got
                scan = ScanSet.build(
                    [item for item, _at in items if item.question_hash != active], given=self.given
                )
                self._scan_cache = (scan, overflow)
        return self._scan_cache

    def _scan_served(self, reply: str, *, whole: bool = False) -> None:
        """A88/A93: the posed-and-ungraded items this served, model-written text
        states. Scanned strictly (H0). Unreadable → `reveal_unscanned`; items
        beyond the scan window → an 'unscanned' marker at the window's edge.

        Spec §13 A101 (review M2): `reveal_hashes` accumulates over the turn's
        scans, and a text that EXTENDS the one scanned last (the stream relaying
        its next delta, the final text of a streamed turn) is scanned from
        `ScanSet.window_start` — the new suffix plus the overlap — never from the
        start again; any other text (a retracted attempt, a fresh JSON reply) is
        scanned whole. An item already stated this turn is not scanned again.

        Spec §13 A105 (PKG-14/15 review m1, m4): `whole=True` — complete()'s
        scan of the turn's final text — is a whole-text scan, so no windowing
        gap survives the turn. A scan that raises leaves `reveal_unscanned`
        (the 'unscanned' marker: every posed item's grade floors to assisted,
        A88/A93 — fail closed) and does NOT mark its text scanned, so the next
        scan reads that window again."""
        self.reveal_unscanned, self.reveal_overflow = False, None
        if self.tier == "none" or not reply:
            return
        got = self._scan_set()
        if got is None:
            self.reveal_unscanned = True
            return
        scan, self.reveal_overflow = got
        last = self.__dict__.get("_scanned_text")
        try:
            start = (
                scan.window_start(reply, len(last))
                if not whole and last and reply.startswith(last)
                else 0
            )
            already = set(self.reveal_hashes)
            found = scan.stated(reply, start=start, skip=already)
        except Exception:
            logger.error("served text of %s could not be scanned", self.session_id, exc_info=True)
            self.reveal_unscanned = True
            return
        self._scanned_text = reply  # only after the scan succeeded (A105)
        if found:
            self.reveal_hashes = sorted(already | set(found))

    def _record_served(self) -> None:
        """A88 (M2) / A93: durable at serve time — learning_reveals, keyed by the
        student; a hash this turn already recorded (it was scanned while
        streaming) is not written twice. A failed write leaves `reveal_fallback`
        for `_apply_turn` (the same compare-and-set write as the turn)."""
        self.reveal_fallback = None
        recorded = self.__dict__.setdefault("_recorded", set())
        fresh = [h for h in self.reveal_hashes if h not in recorded]
        marker_at = None
        # spec §13 A101 (review minor 2): ONE marker per turn, however often the
        # unreadable scan set is met (a stream meets it on every delta)
        if self.reveal_unscanned and not self.__dict__.get("_unscanned_marked"):
            marker_at = datetime.fromtimestamp(self._now, timezone.utc)
            self._unscanned_marked = True
        elif (
            not self.reveal_unscanned
            and self.reveal_overflow is not None
            and not self.__dict__.get("_overflow_marked")
        ):
            marker_at = self.reveal_overflow
        if not (fresh or marker_at is not None):
            return
        try:
            if fresh:
                record_reveals(self.user_id, fresh, session_id=self.session_id, source=self.phase)
                recorded.update(fresh)
            if marker_at is not None:
                record_unscanned(self.user_id, session_id=self.session_id, source=self.phase, at=marker_at)
                self._overflow_marked = True
        except Exception:
            logger.warning("learning_reveals write failed; falling back to loop_state", exc_info=True)
            mark = (
                {"at": marker_at.timestamp(), "source": self.phase} if marker_at is not None else None
            )
            self.reveal_fallback = ([h for h in fresh if h not in recorded], mark)
            # handed to the fallback store: not written again by a later scan of the turn
            recorded.update(self.reveal_fallback[0])

    def _emit_reveal(self) -> None:
        """zpd.reveal for what this turn stated that no earlier scan of the same
        turn already reported (A93: a stream is scanned many times)."""
        emitted = self.__dict__.setdefault("_emitted", set())
        fresh = [h for h in self.reveal_hashes if h not in emitted]
        # spec §13 A101 (review minor 2): the unscanned zpd.reveal once per turn
        unscanned = self.reveal_unscanned and not self.__dict__.get("_unscanned_emitted")
        if fresh or unscanned:
            emitted.update(fresh)
            if unscanned:
                self._unscanned_emitted = True
            zpd_events.emit_zpd_reveal(
                user_id=self.user_id,
                request_id=self.request_id,
                session_id=self.session_id,
                question_hashes=fresh,
                unscanned=unscanned,
                phase=self.phase,
            )

    def record_relayed(self, text: str) -> None:
        """A88 (M1) / A93 (M3, M4): text the student has been SHOWN — while it
        streams (every relayed delta, spec §13 A101), a retracted attempt, or
        what a stream that ended without `done` relayed — is scanned and its
        reveals persisted (learning_reveals, then loop_state). The stream runs
        it in a worker thread (`asyncio.to_thread`) and awaits it before the
        chunk goes out; the turn's lock serialises it with the synchronous call
        a cancelled stream makes in its `finally` (which then waits for an
        in-flight scan instead of racing it). Never raises."""
        with self.__dict__.setdefault("_scan_lock", threading.Lock()):
            self._record_relayed(text)

    def _record_relayed(self, text: str) -> None:
        try:
            self._now = _now_s()
            self._scan_served(text)
            self._record_served()
            if self.reveal_fallback is not None:
                hashes, mark = self.reveal_fallback
                self.reveal_fallback = None
                if hashes or mark is not None:
                    _persist_reveals(
                        self.user_id,
                        None if self.session_id in PENDING_SESSIONS else self.session_id,
                        hashes,
                        unscanned=mark is not None,
                        source=f"{self.phase}:relayed",
                        at=datetime.fromtimestamp(self._now, timezone.utc),
                    )
            if self.reveal_hashes or self.reveal_unscanned:
                self._emit_reveal()
        except Exception:
            logger.error("relayed text of %s could not be scanned", self.session_id, exc_info=True)

    def _apply_turn(self, state: dict, out: dict) -> None:
        """This turn's change to the loop document — the compare-and-set mutate,
        so it may run more than once (each time on a fresher document): it
        changes `state` in place, records what the caller emits after the save
        in `out`, and has no side effects."""
        out.clear()
        if _pending_grade(state):
            raise HTTPException(status_code=409, detail="Finish checking the saved answer before continuing")
        if getattr(self, "activity_id", None) is not None:
            _refuse_while_closing(state, self._now)
            try:
                turn_activity.complete(state, self.activity_id, self._now)
            except turn_activity.StaleTurnActivity as exc:
                raise _StateConflict() from exc
        steps = _steps(state)
        if self.withdrawn_feedback and (
            state.get("current") != self.active
            or (steps.get(self.active) or {}).get("feedback_given") is True
        ):
            raise _StateConflict()
        if self.phase == "feedback" and self.active in steps:
            entry = steps[self.active]
            if self.withdrawn_feedback:
                entry["feedback_withdrawn"] = True
            else:
                out["step"] = dict(entry)  # item-dependent zpd.step, after the save
            if not self.withdrawn_feedback and gates.offer_allowed(self.band, self.verdict != "correct"):
                entry["offered"] = True
                out["offer_rung"] = min(int(self.ceiling), int(entry.get("rung") or 0) + 1)
            entry["feedback_given"] = True
            if state.get("current") == self.active:
                state["current"] = None
            # A27: one more graded check on the concept; the cursor advances at the
            # cap — unless the band controller's verdict on this grade (spec §13
            # A122) already moved it: stop practice, wheel-spin, prerequisite repair
            _count_feedback_and_move(state, entry)
        if self.retrieval_failed and _note_retrieval_failure(state, self.concept_node):
            out["materials_notice"] = True  # A128: once per session (the stored key)
        state["phase_served"] = self.phase
        if self.reveal_fallback is not None:  # A88: a failed learning_reveals write
            _mark_revealed(state, *self.reveal_fallback)
        state["served_at"] = self._now  # A85: the next teach message's independent-time anchor
        if self.confront_used is not None and confront_of(state) == self.confront_used:
            set_confront(state, None)  # PKG-10: used once (a newer marker is kept)
        if self.tier != "none":
            state["tutor_requests"] = int(state.get("tutor_requests") or 0) + 1
            if self.tier == "deep":
                # A39: one per run; PKG-10 (F4): a confronting run counts every request
                spent = max(1, self.run_requests) if self.confront_used is not None else 1
                state["deep_requests"] = int(state.get("deep_requests") or 0) + spent
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
            if state["teach_turns"] >= LOOP_TEACH_TURNS_BEFORE_CHECK and _auto_poses_checks(state):
                qh = _activate_next_item(self.user_id, self.course_id, state, now=self._now)
                if qh is not None and not self.poses_check:
                    # Spec §13 A121: this turn was planned and served WITH its own
                    # question (its trial found nothing to pose), so it poses no
                    # check — never two open prompts at once. The item stays
                    # unposed for a later teach turn or "Check me"; a cursor move
                    # the activation made on the way is kept.
                    state["current"] = None
                    _steps(state).pop(qh, None)
                    qh = None
                if qh is not None:
                    out["activated"] = state["steps"][qh]["check_item_id"]
                    out["activated_qh"] = qh
        # Spec §13 A138 / A139: the teach-phase prompts' part of this write
        self._apply_teach_prompts(state, out)
        # Spec §13 A121: whether the next teach-phase chat message replies to the
        # tutor's own open question (its turn then opens with the verdict). A139:
        # a self-explanation prompt is answered on its own card, never in chat;
        # A138: a turn that handed over to a prequestion card asked nothing
        state[OPEN_QUESTION_KEY] = (
            self.tier != "none"
            and self.phase in ("teach", "feedback")
            and not self.poses_check
            and not self.pq_follows
            and self.se_prompt is None
        )

    def _submission_extra(self) -> dict:
        """The check-answer response keys (A16) — only on a submission's turn."""
        if self.kind not in _SUBMISSION_KINDS:
            return {}
        extra = {
            "graded": self.kind == "feedback",
            "verdict": self.verdict,
            "unavailable": self.kind == "unavailable",  # the outage flag only
            "refused": self.refused,  # A33: a refusal, or the idk it became
            "answer_released": self.answer_released,
        }
        if getattr(self, "ask_rating", False):  # PKG-14: present only when true, never false
            extra["ask_rating"] = True
        return extra


def _auto_poses_checks(state: dict) -> bool:
    """Spec §13 A121: whether a teach turn may pose the concept's next check
    itself (A27 trigger 1). Not in a quiz-ask session (A99): its surface, the
    quiz's "Ask about this" sheet, shows no check card, so a check posed there
    would be an invisible second prompt that answers the student's next
    message with its pose. "Check me" still poses one wherever a card shows."""
    return state.get("origin") != QUIZ_ASK_ORIGIN


def quiz_ask_state(node_id: str) -> dict:
    """PKG-14 final fix round (spec §13 A99): the loop document a quiz-ask session
    starts with — `teach` on the quiz's concept node, as /plan/approve leaves a
    one-concept plan (cursor 0, counters 0), marked with its origin."""
    return {
        "phase": "teach",
        "origin": QUIZ_ASK_ORIGIN,
        "plan": {"approved": [node_id], "cursor": 0},
        "concept": node_id,
        "teach_turns": 0,
        "concept_checks": 0,
    }


def _probe_opener(course_id: str | None) -> str:
    """Spec §13 A121: the probe-phase opener — the check-in intro, or, for a
    course with no check items (its probe ends at once, `no_check_items`), the
    plan intro. One `limit=1` read; an unreadable bank gets the check-in intro."""
    try:
        has_items = _probe_course_has_items(course_id or "")
    except Exception:
        logger.warning("opener: check-item bank unreadable; serving the check-in intro", exc_info=True)
        return LOOP_PROBE_OPENER
    return LOOP_PROBE_OPENER if has_items else LOOP_PLAN_OPENER


class _LoopOpener(_LoopTurn):
    """The session opener (spec Behaviour 15): a fresh session, `teach` with no
    item and the BKT_L0 band, the catalog context (the opener only), and the
    legacy lazy-session contract — `complete` stashes PENDING_SESSIONS and
    persists and counts nothing (no sessions row exists yet). Spec §13 A121:
    while the session is in the probe phase (every session but a quiz-ask one)
    the opener is a template — a neutral welcome and the check-in's intro, no
    model run, no teaching, no question — at every budget level."""

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
        self.arm = _arm_for(body.user_id, request)  # PKG-14 (A20), as _LoopTurn
        # A99: a quiz-ask session names its quiz question; the help row is written
        # here, before any tutor text exists (a failed write is a 503)
        if body.goal is not None and body.origin == "quiz_ask":
            raise HTTPException(status_code=422, detail="Choose a goal in a course learning session")
        self.quiz_ask = open_quiz_ask(body, session_id=self.session_id)
        # A106 (review m2): a quiz-ask session runs on the quiz node's course only
        # (resolve_quiz_ask 422s when it has none) — never the client's course_id
        self.course_id = (
            self.quiz_ask.course_id
            if self.quiz_ask is not None
            else body.course_id or _get_course_id_for_topic(body.topic, body.user_id)
        )
        if body.goal is not None:
            _validate_goal(body.goal, _plan_states(self.user_id, self.course_id or ""))
        self.offering_id = resolve_offering(self.course_id, create=True) if self.course_id else ""
        # routes/learn.py::_start_session_agent (:540–543)'s cue, as server text;
        # the topic is the student's and rides the envelope (review round 3, C1(a))
        self.message = body.topic or ""
        self.trusted = False
        self.instruction = (
            "The student opened a session; the topic they typed is below. Begin the "
            "session with a warm greeting and your first question or explanation."
        )
        # A99: a quiz-ask session skips the probe and the plan — it teaches the
        # quiz's concept from the first turn (the materialised row keeps this doc)
        self.state = quiz_ask_state(self.quiz_ask.node_id) if self.quiz_ask is not None else {}
        if body.goal is not None:
            self.state["goal"] = encode_goal(body.goal)
            self.state["goal_version"] = 1
        self._derive(None)

    def history(self) -> list:
        return _with_goal_context([], self.state, self.user_id)

    def _probing(self) -> bool:
        """The new session opens in the probe phase (every session but a quiz-ask
        one, which teaches from its first turn, A99)."""
        return _loop_phase(self.state) == "probe"

    def _template_only(self) -> bool:
        # Spec §13 A121: the probe-phase opener is a template at every budget
        # level — the check-in is a pretest, so nothing may be taught before it
        return self._probing()

    def _deterministic_text(self, *, hard: bool) -> str | None:
        if self._probing():
            return _probe_opener(self.course_id)
        if not hard:
            return None
        # the opener is never paused: at the hard level it is a template (A27). A
        # quiz-ask session has no check-in, so its template never promises one
        return LOOP_QUIZ_ASK_OPENER if self.quiz_ask is not None else _LOOP_OPENER_TEMPLATE

    def complete(self, reply: str, merged: dict, mastery: list) -> dict:
        self._now = _now_s()
        with self.__dict__.setdefault("_scan_lock", threading.Lock()):
            # A88 (M2): no session row — durable in learning_reveals now; A105: whole
            self._scan_served(reply, whole=True)
            self._record_served()
        if self.reveal_fallback is not None:
            raise RuntimeError("the opener's reveals could not be recorded")  # never served unrecorded
        self._emit_reveal()
        if self.tier != "none" and not self._probing():
            # Spec §13 A121: a model opener (a quiz-ask session's first teach
            # turn, A99) ends with the tutor's own question, as any served teach
            # turn does, so the student's reply to it is judged like any other.
            # A template opener asks nothing and leaves the key unset.
            self.state[OPEN_QUESTION_KEY] = True
        notice: dict = {}
        # A128: no session row yet — the lazy document carries the note's key
        # and the concept's mark into the row the first turn materialises
        if self.retrieval_failed and _note_retrieval_failure(self.state, self.concept_node):
            notice["materials_notice"] = True
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
        if self.state:  # Preserve a private goal while the session is still lazy.
            PENDING_SESSIONS[self.session_id]["loop_state"] = dict(self.state)
        return {
            "reply": reply,
            "session_id": self.session_id,
            "graph_state": get_graph(self.user_id),
            "tier": self.tier,
            "phase": self.phase,
            "budget": _budget_data(self.planned) if self.planned.level == "hard" else None,
            **_materials_notice(notice),
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
    reserves: frozenset[str] = frozenset()
    if rung == Rung.H4:
        concept_items = list_items(item.course_id, item.concept_key)
        reserves = posttest_reserves(concept_items)  # A23, A126: both protected items
        # spec §13 A129: deterministic_content shows the FIRST isomorph left, so
        # the siblings go best-first — a confirmed key (the worked example IS
        # its solution), then clean, never-linted, flagged; ties keep the
        # bank's (created_at, id) order (a stable sort)
        siblings = sorted(
            (s for s in concept_items if s.question_hash != item.question_hash),
            key=serve_quality,
        )
    payload = ladder.deterministic_content(
        rung,
        _item_like(item),
        [_item_like(s) for s in siblings],
        passages,
        exclude_hashes=reserves,
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


#: Spec §13 A121 (`loop_tutor_v2`): why the plan's cursor is on its current
#: concept, as a v2 teach turn tells the tutor (agents.loop_tutor
#: .PLAN_FOCUS_REASONS words each one). Read off loop state, never off text.
CURSOR_REASONS = ("plan_order", "prerequisite_repair", "wheelspin_moved", "isomorph_reask")
#: The two reasons a cursor MOVE records (`mark_cursor_reason`); "plan_order"
#: is the default and "isomorph_reask" is read off the attempt log.
_MOVE_REASONS = ("prerequisite_repair", "wheelspin_moved")
#: The `plan` key that records why a move that is not plan order put the
#: cursor where it is; `_advance_cursor` (plan order) clears it.
CURSOR_REASON_KEY = "cursor_reason"


def _advance_cursor(state: dict, *, no_items: bool = False) -> bool:
    """Move the plan (PKG-08's `plan = {approved, cursor}`) to its next concept,
    resetting the concept's counters; past the end the plan is done and there is
    no current concept. False when there is no next concept (or no plan)."""
    plan = state.get("plan")
    if not isinstance(plan, dict):
        return False
    plan.pop(CURSOR_REASON_KEY, None)  # spec §13 A121: a plan-order move
    set_confront(state, None)  # PKG-10 (F2): a marker never outlives its concept
    approved = list(plan.get("approved") or [])
    if state.get("goal") and state.get("concept"):
        # A finite session frontier is an attempt, not proof of proficiency.
        plan["attempted"] = list(dict.fromkeys([*attempted_nodes(state), state["concept"]]))
        if not no_items:
            plan["checked_nodes"] = list(dict.fromkeys([*(plan.get("checked_nodes") or []), state["concept"]]))
        else:
            plan["practice_unavailable_node_ids"] = list(dict.fromkeys([
                *(plan.get("practice_unavailable_node_ids") or []), state["concept"],
            ]))
    plan["cursor"] = int(plan.get("cursor") or 0) + 1
    if plan["cursor"] >= len(approved):
        plan["done"] = True
        state.pop("concept", None)
        return False
    state["concept"] = approved[plan["cursor"]]
    state["teach_turns"] = 0
    state["concept_checks"] = 0
    return True


def _count_feedback_and_move(state: dict, entry: dict) -> None:
    """A27: one more graded check on the concept; the cursor advances at the
    cap — unless the band controller's verdict on this grade (spec §13 A122)
    already moved it: stop practice, wheel-spin, prerequisite repair. The
    feedback turn's own compare-and-set mutate (and, read-only on a copy,
    spec §13 A138's prequestion trial) runs it."""
    state["concept_checks"] = int(state.get("concept_checks") or 0) + 1
    state["teach_turns"] = 0
    moved = _apply_band_control(state, entry)
    if not moved and state["concept_checks"] >= LOOP_CHECKS_PER_CONCEPT:
        _advance_cursor(state)


# ── The segment prequestion (spec §13 A138) ────────────────────────────────


class _Pose(NamedTuple):
    """What a segment start decided: the concept, the item posed (None: a skip,
    with its reason — or no segment start at all, when `node` is None too)."""

    node: str | None
    item: object | None
    reason: str | None


_NO_POSE = _Pose(None, None, None)


def _pose_prequestion(user_id: str, course_id: str, state: dict, *, now: float) -> _Pose:
    """Spec §13 A138: at a segment start (`learning.prequestion.segment_open`;
    the caller has read the flag), decide the concept's prequestion and record
    it in `state` — a compare-and-set mutate's document, so no side effects
    beyond reads (as `_activate_next_item`): a pose (and the card becomes the
    one open prompt, A121) or a skip with its reason. Excluded like every
    selection (A23, A113): seen, revealed and reported items, this session's
    steps and earlier prequestions, the concept's post-test reserves (inside
    `choose`). A failed read poses nothing and records nothing: the segment
    simply opens without one (a learning activity, never a gate)."""
    node = prequestion_rules.segment_open(state)
    if node is None:
        return _NO_POSE
    try:
        _, p_known = _band_for(user_id, node)
        reason = prequestion_rules.skip_reason(state, node, p_known=p_known)
        item = None
        if reason is None:
            excluded = (
                seen_hashes(user_id)
                | revealed_hashes(user_id)
                | reported_hashes(user_id)
                | set(state.get("steps") or {})
                | prequestion_rules.session_hashes(state)
            )
            key = _concept_key_for_node(user_id, node)
            bank = list_items(course_id, key) if key and course_id else []
            item, reason = prequestion_rules.choose(bank, excluded)
    except Exception:
        logger.warning("prequestion: the concept could not be read; the segment opens without one", exc_info=True)
        return _NO_POSE
    records = dict(prequestion_rules.records(state))
    if item is None:
        records[node] = prequestion_rules.skip_record(reason)
        state[prequestion_rules.KEY] = records
        return _Pose(node, None, reason)
    records[node] = prequestion_rules.pose_record(item, node, now)
    state[prequestion_rules.KEY] = records
    state[OPEN_QUESTION_KEY] = False  # A121: the card is the one open prompt
    return _Pose(node, item, None)


def _undo_pose(state: dict, pose: _Pose) -> None:
    """Spec §13 A138 × A121: a pose the turn was not planned for (its trial
    found none, so the turn kept its own question) is dropped in the same
    compare-and-set: never two open prompts. The segment then opens without
    a prequestion, as when a planned check cannot be posed (A121 (b))."""
    if pose.item is None or pose.node is None:
        return
    records = dict(prequestion_rules.records(state))
    records.pop(pose.node, None)
    state[prequestion_rules.KEY] = records


def _emit_prequestion(user_id: str, request_id: str, session_id: str, node_id: str, status: str, **extra) -> None:
    """`learn.prequestion` (spec §6, §13 A138): ids, enums and counts only —
    never the question or the guess. One per lifecycle step of a segment's
    prequestion: posed, skipped (with its reason), answered (no_idea), superseded."""
    events_service.log_event(
        "learn.prequestion",
        category="usage",
        user_id=user_id,
        request_id=request_id,
        payload={"session_id": session_id, "node_id": node_id, "status": status, **extra},
    )


def _posed_prequestion(user_id: str, session_id: str, request_id: str, pose: _Pose) -> dict | None:
    """After the write that recorded `pose`: a posed item's assistant row (the
    transcript shows what was asked; the card hides it while open) and its
    event, and the payload for the response; a skip's event only."""
    if pose.node is None:
        return None
    if pose.item is None:
        _emit_prequestion(user_id, request_id, session_id, pose.node, "skipped", reason=pose.reason)
        return None
    try:
        save_message(session_id, "assistant", prequestion_rules.pose_text(pose.item))
    except Exception:
        # the card is posed (the write above): only the transcript row is lost;
        # the explaining turn carries the question in its own prefix block
        logger.warning("prequestion pose row not saved", exc_info=True)
    _emit_prequestion(
        user_id,
        request_id,
        session_id,
        pose.node,
        "posed",
        question_hash=pose.item.question_hash,
        format=pose.item.format,
        difficulty=int(pose.item.difficulty),
    )
    return prequestion_rules.pose_payload(pose.item)


def _emit_self_explanation(user_id: str, request_id: str, session_id: str, prompt: dict, status: str, **extra) -> None:
    """`learn.self_explanation` (spec §6, §13 A139): ids, enums and counts only
    — never the prompt's reply. shown (the turn carrying it was served),
    replied (with reply_chars) or skipped."""
    events_service.log_event(
        "learn.self_explanation",
        category="usage",
        user_id=user_id,
        request_id=request_id,
        payload={
            "session_id": session_id,
            "node_id": prompt.get("node_id"),
            "juncture": prompt.get("juncture"),
            "status": status,
            **extra,
        },
    )


def _self_explain_payload(prompt: dict) -> dict:
    """The client's view of an open prompt: its id (echoed by the reply), juncture and text."""
    return {"prompt_id": prompt["id"], "juncture": prompt["juncture"], "prompt": self_explain.prompt_text(prompt)}


def _open_teach_prompts(user_id: str, state: dict) -> dict:
    """GET /status's spec §13 A138 / A139 keys: the plan concept's prequestion
    card while it is open (posed, or answered with its explanation owed —
    `answered: true`) and the open self-explanation prompt, each behind its
    flag and present only when there is one. Reads one item at most."""
    keys: dict = {}
    rec = prequestion_rules.record_for(state, state.get("concept"))
    if (
        rec is not None
        and rec.get("status") in (prequestion_rules.POSED, prequestion_rules.ANSWERED)
        and not state.get("current")
        and _prequestion_on(user_id)
    ):
        item = get_check_item(rec["check_item_id"]) if rec.get("check_item_id") else None
        if item is not None:
            keys["prequestion"] = prequestion_rules.pose_payload(
                item, answered=rec.get("status") == prequestion_rules.ANSWERED
            )
    prompt = self_explain.open_prompt(state)
    if prompt is not None and _self_explain_on(user_id):
        keys["self_explain"] = _self_explain_payload(prompt)
    return keys


# ── Band control on the plan (spec §3.3, §13 A122) ──────────────────────────
#: loop_state key: node id → the target difficulty band control set for that
#: concept's next item this session (ids → ints only; read by activation)
_BAND_DIFFICULTY = "band_difficulty"
#: the graded step's key holding the verdict _finish_check_checkpoint stored
_BAND_CONTROL = "band_control"


def _repaired(plan: dict, concept: str, prereq: str) -> bool:
    """This concept already sent the student to this prerequisite in the
    session (`plan["repairs"]`): each (concept, prerequisite) repair runs at
    most once a session, so repairs never cycle."""
    return any(
        isinstance(r, dict) and r.get("for") == concept and r.get("node_id") == prereq
        for r in plan.get("repairs") or []
    )


def _repair_cursor(
    state: dict, prereq: str, action: policy.BandAction, *, replace: bool
) -> None:
    """Prerequisite repair (§3.3): teaching moves to `prereq` NOW — it takes the
    plan slot at the cursor, so activation, the band and the ceiling follow it.
    REPAIR_RETURN (`replace` False) puts the concept right after it, to be
    practised again once the prerequisite's checks are done; REPAIR_REPLACE
    (wheel-spin: stop more-of-the-same) drops the concept from the rest of the
    session, and a goal session records it attempted, as _advance_cursor would.
    A later occurrence of `prereq` in the plan moves up to here. Recorded in
    `plan["repairs"]` (ids and the enum only)."""
    plan = state["plan"]
    approved = [n for n in plan.get("approved") or [] if isinstance(n, str)]
    cursor = int(plan.get("cursor") or 0)
    concept = state["concept"]
    ahead = [n for n in approved[cursor + 1 :] if n != prereq]
    plan["approved"] = approved[:cursor] + [prereq] + ([] if replace else [concept]) + ahead
    plan["repairs"] = [
        *(plan.get("repairs") or []),
        {"node_id": prereq, "for": concept, "action": action.value},
    ]
    if replace and state.get("goal"):
        # an exhausted session frontier is an attempt, never a claim of proficiency
        plan["attempted"] = list(dict.fromkeys([*attempted_nodes(state), concept]))
        plan["checked_nodes"] = list(
            dict.fromkeys([*(plan.get("checked_nodes") or []), concept])
        )
    set_confront(state, None)  # PKG-10 (F2): a marker never outlives its concept
    state["concept"] = prereq
    state["teach_turns"] = 0
    state["concept_checks"] = 0


def _apply_band_control(state: dict, entry: dict) -> bool:
    """Apply the band controller's verdict on the graded step `entry` (spec §3.3,
    §13 A122) as its feedback turn is served — inside that turn's
    compare-and-set mutate, from the stored verdict alone (no reads). The next
    item's difficulty: `state["band_difficulty"][node]` (activation reads it).
    The concept's ceiling clause: `state["band_ceiling"][node]` (−1 / +1 rung,
    `policy.ceiling_delta`; every ceiling on the concept reads it through
    `_band_ceiling_delta`, gates unchanged; HOLD keeps the last one).
    The cursor: policy.cursor_move — STOP_PRACTICE leaves the concept,
    WHEELSPIN stops more-of-the-same (repairing the weakest unproficient
    prerequisite in its place when there is one), EASIER_CHECK_PREREQS repairs
    a weak prerequisite first and comes back. True when the cursor moved, so
    the per-concept check count does not move it again. A verdict on a concept
    the cursor has left, or a session without a plan, moves nothing."""
    verdict = entry.get(_BAND_CONTROL)
    if not isinstance(verdict, dict):
        return False
    try:
        action = policy.BandAction(verdict.get("action"))
    except ValueError:
        return False
    node = entry.get("node_id")
    if not isinstance(node, str) or not node:
        return False
    target = verdict.get("difficulty")
    if type(target) is int and target in CHECK_ITEM_DIFFICULTIES:
        targets = state.get(_BAND_DIFFICULTY)
        state[_BAND_DIFFICULTY] = {**(targets if isinstance(targets, dict) else {}), node: target}
    # §3.3's ceiling clause, from the action itself (never a stored number):
    # HARDER −1 rung, EASIER_CHECK_PREREQS +1; the band's ceiling only
    delta = policy.ceiling_delta(action)
    if delta:
        deltas = state.get(_BAND_CEILING)
        state[_BAND_CEILING] = {**(deltas if isinstance(deltas, dict) else {}), node: delta}
    plan = state.get("plan")
    if node != state.get("concept") or not isinstance(plan, dict):
        return False
    prereq = verdict.get("repair")
    available = (
        isinstance(prereq, str) and bool(prereq) and prereq != node
        and not _repaired(plan, node, prereq)
    )
    move = policy.cursor_move(action, repair_available=available)
    if move is policy.CursorMove.STAY:
        return False
    # spec §13 A121 × A122: every move records why the cursor moved
    # (mark_cursor_reason, read by plan_focus); a plan-order advance clears it
    wheelspin = action is policy.BandAction.WHEELSPIN
    if move is policy.CursorMove.ADVANCE:
        if _advance_cursor(state) and wheelspin:
            mark_cursor_reason(state, "wheelspin_moved")  # moved on, no prerequisite to repair
    else:
        _repair_cursor(state, prereq, action, replace=move is policy.CursorMove.REPAIR_REPLACE)
        mark_cursor_reason(state, "wheelspin_moved" if wheelspin else "prerequisite_repair")
    return True


def _target_difficulty(state: dict, node_id: str, band: str) -> int:
    """The difficulty an activated item on the concept targets (select_item falls
    back to the nearest): the band controller's target for the concept this
    session when a verdict set one (spec §13 A122: HARDER one step up,
    EASIER_CHECK_PREREQS one step down from the graded item's), else the band's
    LOOP_CHECK_DIFFICULTY_BY_BAND."""
    targets = state.get(_BAND_DIFFICULTY)
    target = targets.get(node_id) if isinstance(targets, dict) else None
    if type(target) is int and target in CHECK_ITEM_DIFFICULTIES:
        return target
    return LOOP_CHECK_DIFFICULTY_BY_BAND[band]


def _worked_example_shown(state: dict, node_id: str) -> bool:
    """A worked example was already shown on this concept this session: one of
    its steps opened on the worked example AND reached H4 (spec §13 A122's
    near-transfer rule — the next item is attempted, not shown worked)."""
    return any(
        isinstance(e, dict)
        and e.get("node_id") == node_id
        and e.get("worked_first") is True
        and int(e.get("rung") or 0) >= int(Rung.H4)
        for e in (state.get("steps") or {}).values()
    )


def mark_cursor_reason(state: dict, reason: str) -> None:
    """THE HOOK for a cursor move that is not plan order (spec §13 A121 × A122).
    A122's band control calls it right after it moves `plan.cursor` / `concept`
    (`_apply_band_control`): "prerequisite_repair" after a repair that comes
    back (EASIER_CHECK_PREREQS), "wheelspin_moved" after wheel-spin's move — a
    repair in the concept's place, or moving on when there is none — so the v2
    tutor's teach turns say why the plan is on the new concept (`plan_focus`).
    The next plan-order advance (`_advance_cursor`) clears it. PKG-10's isomorph
    re-ask moves no cursor: plan_focus reads it off the attempt log, exactly
    while the re-ask is pending."""
    if reason not in _MOVE_REASONS:
        raise ValueError(f"not a cursor move reason: {reason!r} (expected one of {_MOVE_REASONS})")
    plan = state.get("plan")
    if isinstance(plan, dict):
        plan[CURSOR_REASON_KEY] = reason


def plan_focus(state: dict) -> tuple[str, str] | None:
    """Spec §13 A121 (`loop_tutor_v2`): (the plan's current concept node, why
    the cursor is there), from loop state only — never from text. The reason
    is "isomorph_reask" when the session's last attempt on the concept was
    `unknown` (its next check re-asks an isomorph, `_isomorph_after_unknown`),
    else the reason a non-plan-order move recorded (`mark_cursor_reason`),
    else "plan_order". None with no plan, a finished plan or no concept. Pure:
    `state` is never changed."""
    plan = state.get("plan")
    concept = state.get("concept")
    if not isinstance(plan, dict) or plan.get("done") or not isinstance(concept, str) or not concept:
        return None
    tail = attempts_for_node(attempts_of(dict(state)), concept)  # a copy: attempts_of may add the log
    if tail and slip_or_misconception(tail) == "unknown":
        return concept, "isomorph_reask"
    moved = plan.get(CURSOR_REASON_KEY)
    return concept, moved if moved in _MOVE_REASONS else "plan_order"


def _isomorph_after_unknown(state: dict, node_id: str, items: list, exclude: set):
    """PKG-10 (spec §3.3 "unknown → re-ask an isomorph"; §13 A27): when the
    session's last attempt on this concept was `unknown`, the isomorph of that
    attempt's item (policy.next_isomorph) among the site's own candidates —
    everything `exclude` leaves (seen, revealed, session hashes, the post-test
    reserve; A23), servable only (A34) — else None (the normal pick)."""
    tail = attempts_for_node(attempts_of(state), node_id)
    if not tail or slip_or_misconception(tail) != "unknown":
        return None
    last = next((i for i in items if i.question_hash == tail[-1].question_hash), None)
    if last is None:
        return None
    # spec §13 A129: next_isomorph takes the FIRST isomorph in the given
    # order — every isomorph is equal under its rule (same concept, format and
    # difficulty) — so the candidates go best-first by serve_quality; ties keep
    # the bank's (created_at, id) order (a stable sort)
    candidates = sorted(
        (i for i in items if i.question_hash not in exclude and is_servable(i)), key=serve_quality
    )
    return policy.next_isomorph(last, candidates)


def _activate_next_item(user_id: str, course_id: str, state: dict, *, now: float) -> str | None:
    """The ONLY code that SETS the document's `current` (the spec's `active`;
    feedback and withdrawal only clear it). For the current plan concept: its
    items, minus everything the student has seen or had revealed, every hash
    already keyed in this session and the concept's post-test reserve (A23);
    the band's target difficulty; the formats rotated by the concept's checks
    so far. A concept with nothing servable advances the cursor and tries the
    next (at most once per remaining concept). No plan → None (teaching only).
    Writes no evidence and runs no model. An item the student reported (A113)
    is excluded like a seen or revealed one."""
    concept = state.get("concept")
    if not concept:
        return None
    try:
        excluded = (
            seen_hashes(user_id)
            | revealed_hashes(user_id)
            | reported_hashes(user_id)
            | set(state.get("steps") or {})
            # spec §13 A138: an item this session posed as a prequestion (empty
            # with the flag off) — its answer is shown, or its stem was seen
            | prequestion_rules.session_hashes(state)
        )
    except Exception as exc:
        if state.get("goal"):
            raise HTTPException(status_code=503, detail="Practice availability unavailable; retry") from exc
        raise
    while True:
        item = None
        try:
            items, exclude = _practice_pool(user_id, course_id, concept, excluded)
        except Exception as exc:
            if state.get("goal"):
                raise HTTPException(status_code=503, detail="Practice availability unavailable; retry") from exc
            raise
        learner = None
        if items:
            item = _isomorph_after_unknown(state, concept, items, exclude)
            learner = _learner_state(user_id, concept)
            band, _ = _band_of(learner)
            rotation = int(state.get("concept_checks") or 0) % len(CHECK_ITEM_FORMATS)
            formats = CHECK_ITEM_FORMATS[rotation:] + CHECK_ITEM_FORMATS[:rotation]
            for fmt in formats if item is None else ():
                item = select_item(
                    items,
                    format=fmt,
                    difficulty=_target_difficulty(state, concept, band),
                    exclude_hashes=exclude,
                )
                if item is not None:
                    break
        if item is not None:
            qh = item.question_hash
            state["current"] = qh
            step = {
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
            # spec §13 A122: a novice without the prerequisite (policy.attempt_first
            # says no) gets the worked example FIRST on the concept's first item of
            # the session; the item after it is the near-transfer, attempted
            view = _learner_view(
                learner, band=band, prereq_proficient=_prereq_proficient(user_id, concept)
            )
            if policy.opens_on_worked_example(
                view, shown_on_concept=_worked_example_shown(state, concept)
            ):
                step["worked_first"] = True
            if _take_retrieval_mark(state, concept):
                # A128: this step's teaching ran without its course material
                step[_RETRIEVAL_KEY] = _RETRIEVAL_FAILED_VALUE
            _steps(state)[qh] = step
            return qh
        if not _advance_cursor(state, no_items=True):
            return None
        concept = state["concept"]


def _practice_pool(user_id: str, course_id: str, node_id: str, excluded: set[str]) -> tuple[list, set[str]]:
    """The same eligible bank for planning and actual check activation.

    A probe's practice reserve is eligible here; the delayed post-test
    reserves (both, A126) are not. Difficulty is not an availability filter:
    selection uses the nearest difficulty and rotates through all supported
    check formats. Failed reads propagate, never masquerade as an empty bank.
    """
    key = _concept_key_for_node(user_id, node_id)
    if not key:
        return [], excluded
    items = list_items(course_id, key)
    return items, excluded | posttest_reserves(items)


def _goal_practice_unavailable(user_id: str, course_id: str, state: dict, node_ids) -> set[str]:
    """Read-only, owner-scoped goal preflight. A read outage is not depletion."""
    if not node_ids:
        return set()
    try:
        excluded = (
            seen_hashes(user_id)
            | revealed_hashes(user_id)
            | reported_hashes(user_id)
            | set(state.get("steps") or {})
            | prequestion_rules.session_hashes(state)  # spec §13 A138, as activation
        )
        unavailable = set()
        for node in node_ids:
            items, excluded_for_node = _practice_pool(user_id, course_id, node, excluded)
            if not any(item.question_hash not in excluded_for_node and item.format in CHECK_ITEM_FORMATS
                       and is_servable(item) for item in items):
                unavailable.add(node)
        return unavailable
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Practice availability unavailable; retry") from exc


def _pose_payload(item, *, worked_first: bool = False) -> dict:
    """The check pose the client renders (A17: the prompt verbatim; A22: an
    mc_reason item's stored options, never rebuilt, never marked correct, no
    wrong_key). Never the reference. `worked_first` (spec §13 A122): the item
    opens on the worked example and it has not been unlocked yet — the client
    asks for it at once (/hint grants H4 with no attempt before it, the hint
    turn serves it); the key is present only when true."""
    options = None
    if item.format == "mc_reason" and item.options:
        options = [{"letter": o.letter, "text": o.text} for o in item.options]
    pose = {
        "question_hash": item.question_hash,
        "format": item.format,
        "difficulty": item.difficulty,
        "prompt": ladder.check_pose(item.prompt),
        "options": options,
    }
    if worked_first:
        pose["worked_first"] = True
    return pose


def _worked_example_owed(user_id: str, state: dict, qh: str | None) -> bool:
    """Whether item `qh`'s next hint is its worked example (spec §13 A122): its
    step opened on it, is still below H4, and policy.worked_example_rung —
    re-read on the learner's state NOW — still grants it. Reads only for such a
    step (the common pose reads nothing more)."""
    entry = (state.get("steps") or {}).get(qh) if qh else None
    if not isinstance(entry, dict) or entry.get("worked_first") is not True:
        return False
    node_id = entry.get("node_id")
    if not node_id or int(entry.get("rung") or 0) >= int(Rung.H4):
        return False
    learner = _learner_state(user_id, node_id)
    band, _ = _band_of(learner)
    view = _learner_view(learner, band=band, prereq_proficient=_prereq_proficient(user_id, node_id))
    step = _step_state(state, qh)
    delta = _band_ceiling_delta(state, node_id)
    return policy.worked_example_rung(view, step, worked_first=True, band_delta=delta) is not None


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
    await asyncio.to_thread(turn.begin_activity)
    decision = ai_budget.check(turn.user_id, "tutor", turn.band, **turn.budget_counters())
    try:
        turn.plan(decision)
    except BaseException:
        await asyncio.shield(asyncio.to_thread(turn.touch_served_at))
        raise
    if turn.paused:
        await asyncio.shield(asyncio.to_thread(turn.touch_served_at))
        raise _BudgetPaused(decision)
    if turn.tier == "none":
        return {"graph_update": {}, "mastery_changes": [], **turn.complete(turn.text, {}, [])}
    try:
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
    except BaseException:
        await asyncio.shield(asyncio.to_thread(turn.touch_served_at))
        raise


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
    try:
        await asyncio.to_thread(turn.begin_activity)
        decision = ai_budget.check(turn.user_id, "tutor", turn.band, **turn.budget_counters())
        turn.plan(decision)
    except Exception:
        # ADR 0024 honest degrade: nothing was shown or written — one terminal error
        logger.exception("Loop turn could not be planned")
        await asyncio.shield(asyncio.to_thread(turn.touch_served_at))
        yield sapling_event_to_sse(_stream_error(turn, _STREAM_UNAVAILABLE))
        return
    for ev in turn.pre_events():
        yield sapling_event_to_sse(ev)
    if turn.paused:
        await asyncio.shield(asyncio.to_thread(turn.touch_served_at))
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

    def record_incomplete_usage(known_usage) -> None:
        # Completed responses from an exhausted/cancelled stream still cost.
        # An in-flight response may report nothing; never invent its token bill.
        if known_usage is not None and _requests_of(UnfinishedRun(known_usage)):
            turn.record_usage(UnfinishedRun(known_usage))

    async def fallback(messages: list) -> dict:
        """Rung 1 (m2): the SAME planned turn — no second plan(), no second
        retrieval — billed for the failed streamed run and continued from its
        messages (tool results) by the tool-less continuation."""
        reply = await _continue_turn(turn, messages)
        return {"graph_update": {}, "mastery_changes": [], **turn.complete(reply, {}, [])}

    ai_budget.count_tutor_call(turn.user_id)
    shown = ""  # A88 (M1): the text the student has been shown
    scanned = ""  # the last `shown` whose scan returned (A105, review m3)
    attempts: list[str] = []  # A93 (M4): retracted attempts relayed but never scanned
    finished = False
    try:
        async for ev in stream_structured_turn(
            agent=turn.agent,
            user_message=turn.assembled,
            run_kwargs={**turn.run_kwargs, "usage": usage},
            deps=turn.deps,
            on_complete=turn.complete,
            nonstream_fallback=fallback,
            on_usage=turn.record_usage,
            on_incomplete_usage=record_incomplete_usage,
            request_id=turn.request_id,
            transform=turn.redact,
            transform_final=turn.serve,
            render_final=turn.render,
            render_partial=turn.render_partial,
        ):
            if ev.type == "token":
                delta = str((ev.data or {}).get("delta") or "")
                if delta:
                    shown += delta
                    # A93 (M3) / A101: EVERY delta is scanned (the suffix + the
                    # overlap) and recorded before this chunk goes out — off the
                    # event loop, awaited, so the ordering holds
                    await asyncio.to_thread(turn.record_relayed, shown)
                    scanned = shown
            elif ev.type == "retract":
                # A105 (review m3): every delta of the attempt was already scanned
                # before it went out; only text relayed and never scanned is kept
                if shown and shown != scanned:
                    attempts.append(shown)
                shown = scanned = ""
            elif ev.type == "done":
                finished = True
                for extra_ev in _pre_done_events(ev.data or {}):
                    yield sapling_event_to_sse(extra_ev)
            yield sapling_event_to_sse(ev)
    finally:
        # A85: an errored, disconnected or cancelled stream moves the anchor
        if not finished:
            await asyncio.shield(asyncio.to_thread(turn.touch_served_at))
        # A93 (M4) / A88 (M1): a retracted attempt, or what an unfinished stream
        # relayed, that no scan has covered is scanned and recorded. A105 (review
        # m3): in a worker thread — the turn's lock may be held by a scan still in
        # flight, and waiting for it must not block the event loop — and SHIELDED,
        # so a second cancellation cannot stop the write: the thread finishes it.
        pending = [text for text in attempts if text]
        if not finished and shown and shown != scanned:
            pending.append(shown)
        if pending:

            def _scan_pending() -> None:
                for text in pending:
                    turn.record_relayed(text)

            await asyncio.shield(asyncio.to_thread(_scan_pending))


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
            raise HTTPException(status_code=404, detail="Session not found")
        state: dict = copy.deepcopy(pending.get("loop_state") or {})
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
    pending_grade = _pending_grade(state)
    item = (
        get_check_item(entry["check_item_id"])
        if isinstance(entry, dict) and entry.get("check_item_id") and not pending_grade
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
        band_delta=_band_ceiling_delta(state, node_id),  # spec §13 A122
    )
    pending_withdrawn_feedback = item is None and _phase_for(state) == "feedback"
    phase = ("check" if pending_grade and pending_grade["kind"] == "check"
             else "feedback" if pending_withdrawn_feedback
             else _phase_for(dict(state, current=active if item is not None else None)))
    # spec §13 A138 / A139: an open card is restored READ-ONLY on resume — each
    # key present only when there is one (never null), behind its flag
    teach_prompts = _open_teach_prompts(user_id, state) if not pending_grade else {}
    return {
        **teach_prompts,
        "active": True,
        "session_id": session_id,
        "loop_phase": _loop_phase(state),  # PKG-08: probe | plan | teach (resume point)
        **_learning_scope_payload(state),
        "phase": phase,
        "pending_grade": pending_grade,
        # PKG-13 reopen: the open item's pose, so a resuming client restores the
        # check READ-ONLY (POST /check/next may activate — write — another item).
        # Only while the item takes answers; never the reference (A17/A22). A122:
        # it still says so when its worked example is owed (the client asks for it).
        "check": (
            _pose_payload(item, worked_first=_worked_example_owed(user_id, state, active))
            if item is not None and phase == "check"
            else None
        ),
        "band": band,
        "ceiling": int(ceiling),
        "active_question_hash": active if item is not None else None,
        "items": len(state.get("steps") or {}),
        "rung": int(step.rung) if item is not None else None,
        "attempts": step.genuine_attempts if item is not None else 0,
    }


# ── Open loop sessions (PKG-13; spec §9, §11.3, §13 A26) ────────────────────
# What LoopLearn resumes instead of starting a new probe: the student's loop
# sessions for the course that have loop_state, no close record and no end.
# Read-only — no write, no model, no event — and never rate-limited (A20: a
# failure here must not push a student off the loop UI). The offerings are the
# COURSE's (`course_offering_ids`): a loop session is stamped with
# `resolve_offering(course, create=True)` — the current term — which is not the
# enrollment's offering once a term rolls over (#553/#529); ownership is the
# `user_id` filter. Offerings the store cannot vouch for are a 503 (the
# client's retry state), never an empty list — that would start a new probe.
# `loop_state=neq.{}` keeps legacy tutor sessions (the column default '{}') out
# BEFORE the limit; mode='review' rows are PKG-12's daily review sessions
# (NOT_REVIEW). A lazy session (spec §9) has no row until its first loop write,
# so it is not listed. `phase` is the phase GET /status reports for the same
# document: `_loop_phase` (probe | plan | teach), refined in teach by
# `_phase_for` (teach | check | feedback); a document whose close is being
# stored (`phase: close`) is not open. (`close_phase` is written together with
# `close_json`, so an open row never has one.)
LOOP_OPEN_SESSIONS_LIMIT = 10  # † picker length; mirrors the legacy getSessions(limit=10)
_OFFERINGS_UNKNOWN = "course offerings unavailable, retry"


def _open_loop_filters(user_id: str) -> dict:
    """An open loop session of this student: no close record, no end, loop state,
    not a review session."""
    return {
        "user_id": f"eq.{user_id}",
        "close_json": "is.null",  # never an equality on the ciphertext (invariant 9)
        "ended_at": "is.null",
        "loop_state": "neq.{}",
        **NOT_REVIEW,
    }


def _open_session_entry(row: dict) -> dict | None:
    """The listed shape of one open row, or None when it is not resumable."""
    state = row.get("loop_state")
    if not isinstance(state, dict) or not state:
        return None
    loop_phase = _loop_phase(state)
    if loop_phase == "close":
        return None
    return {
        "session_id": row["id"],
        "topic": row.get("topic") or "",
        "started_at": row.get("started_at"),
        "phase": _phase_for(state) if loop_phase == "teach" else loop_phase,
    }


def _resume_entry(user_id: str, session_id: str) -> dict | None:
    """`?resume=<id>` outside the list (another course, or past the limit): ONE
    read of that row under the same open-loop filters, its course from the
    offering. None when it is not this student's open loop session — the client
    then shows it read-only (a legacy chat) — or its course cannot be told."""
    rows = (
        table("sessions").select(
            "id,topic,started_at,loop_state,offering_id",
            filters={"id": f"eq.{session_id}", **_open_loop_filters(user_id)},
            limit=1,
        )
        or []
    )
    entry = _open_session_entry(rows[0]) if rows else None
    course = offering_course_id(rows[0].get("offering_id") or "") if entry else None
    return {**entry, "course_id": course} if entry and course else None


@router.get("/sessions")
def list_open_sessions(
    request: Request,
    user_id: str = Query(...),
    course_id: str = Query(...),
    resume: str | None = Query(None),
) -> dict:
    """PKG-13 fix round: `resume` (the `/learn?resume=<id>` deep link) adds
    `"resume": {…, course_id} | null` — the named session when it is the
    student's open loop session in ANY course, even past the list limit."""
    _gate(user_id, request)  # require_self, then the spec §7 404
    offering_ids = course_offering_ids(course_id)
    if offering_ids is None:
        raise HTTPException(status_code=503, detail=_OFFERINGS_UNKNOWN)
    rows = (
        table("sessions").select(
            "id,topic,started_at,loop_state",
            filters={
                **_open_loop_filters(user_id),
                "offering_id": f"in.({','.join(offering_ids)})",
            },
            order="started_at.desc",
            limit=LOOP_OPEN_SESSIONS_LIMIT,
        )
        if offering_ids
        else []
    ) or []
    sessions = [e for e in map(_open_session_entry, rows) if e is not None]
    if resume is None:
        return {"sessions": sessions}
    listed = next((s for s in sessions if s["session_id"] == resume), None)
    found = {**listed, "course_id": course_id} if listed else _resume_entry(user_id, resume)
    return {"sessions": sessions, "resume": found}


@router.post("/chat", dependencies=_screened("loop_chat", "message", respond=crisis_support.turn_response))
async def chat(body: ChatBody, request: Request):
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    await _consume_pending_off_loop(body.session_id, body.user_id)
    _teaching_open(body.session_id, body.user_id)
    return await _json_turn(
        lambda: _LoopTurn(body=body, request=request, message=body.message, loop_on=loop_on),
        "loop chat agent",
    )


@router.post("/chat/stream", dependencies=_screened("loop_chat", "message", respond=crisis_support.turn_stream))
async def chat_stream(body: ChatBody, request: Request):
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    await _consume_pending_off_loop(body.session_id, body.user_id)
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
    ask_rating: bool = False  # PKG-14: this graded check brought the counter to the rating cadence


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
    if not isinstance(entry, dict) or entry.get("graded_at") is not None or entry.get("grading_superseded"):
        return False
    if grade_checkpoint.KEY in entry:
        return True  # a saved result must be recovered, never abandoned as stale
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
            entry.pop(grade_checkpoint.KEY, None)

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
    if isinstance(entry, dict) and grade_checkpoint.KEY in entry:
        checkpoint = _open_grade_checkpoint(entry, body, course_id, kind="check")
        return _finish_check_checkpoint(checkpoint, scope, request, loop_on=loop_on)
    if isinstance(entry, dict) and (
        entry.get("graded_at") is not None or entry.get("grading_claim") or entry.get("grading_superseded")
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
    variant = arms.variant_for(body.user_id, node_id, _arm_for(body.user_id, request))
    genuine = not idk and _genuine(
        text, _seconds_since(entry.get("first_shown_at"), now), band, variant
    )
    deps = SaplingDeps(
        user_id=body.user_id,
        course_id=course_id or None,
        supabase=None,
        request_id=_request_id(request),
        session_id=body.session_id,
        feature="loop_check",
        learning_loop=loop_on,
        # PKG-10: the hook's attempt log + marker; its change rides
        # outcome.diagnosis into the grade's compare-and-set save below
        loop_state=copy.deepcopy(state),
    )
    # A88: a posed item a served turn revealed grades with no unassisted credit
    rung = max(
        int(entry.get("rung") or 0),
        _reveal_floor(body.user_id, item, _ts(entry.get("first_shown_at"))),
    )
    # PKG-10 (spec §13 A76): the next graded item on a concept after a release
    # is a re-check, never a full-weight unassisted first attempt
    recheck = recheck_after_release(
        body.user_id,
        node_id,
        state,
        now=datetime.fromtimestamp(now, tz=timezone.utc),
        item=item,
    )
    claim = str(uuid.uuid4())
    _claim_grading(body.session_id, qh, claim, now)
    checkpointed = False
    answer = CheckAnswer(
        question_hash=qh,
        answer_text=body.answer,
        selected_option=body.option,
        reason=body.reason,
        idk=idk,
        # spec §13 A127: the stated confidence; an idk (a box or a phrase) states none
        confidence=None if idk else body.confidence,
    )
    try:
        outcome = await grade_answer(
            _item_like(item),
            answer,
            deps=deps,
            node_id=node_id,
            max_rung=rung,
            same_session_recheck=recheck,
        )
        refused = bool(outcome.refused)
        if refused:  # A33, read BEFORE `unavailable`: not an outage, never a genuine attempt

            # A97: a disowned answer is never escalated to idk — the student may
            # have been right; they are only asked to state their own answer
            disowned = outcome.refused == "disowned_answer"

            def count_refusal(e: dict) -> None:
                if not disowned:
                    e["refusals"] = int(e.get("refusals") or 0) + 1
                if disowned or e["refusals"] < CHECK_REFUSALS_AS_IDK:
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
            answer = CheckAnswer(question_hash=qh, idk=True)
            outcome = await grade_answer(
                _item_like(item),
                answer,
                deps=deps,
                node_id=node_id,
                max_rung=rung,
                same_session_recheck=recheck,
            )
        if outcome.unavailable:  # invariant 28: nothing for either outcome; the item stays open

            def note_attempt(e: dict) -> None:
                if genuine:
                    _record_attempt(e, now, failed=True)

            state = _update_loop_state(
                body.session_id, _under_claim(qh, claim, note_attempt, release=True)
            )
            return _Submission("unavailable", state, rendered, scope, refused=refused)
        # A93: the help floor re-read inside the claim, right before the write
        rung = _refloor(
            deps.pending_evidence, body.user_id, item, _ts(entry.get("first_shown_at")), rung
        )
        previously_seen = qh in seen_hashes(body.user_id)
        _tag_planning_evidence(deps.pending_evidence, item, synthetic_idk=bool(refused),
                               previously_seen=previously_seen, operation_id=claim, observed_at=now)
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

        if state.get("goal"):
            effective_rung = max(rung, int(evidence.get("max_rung") or 0))
            rechecked = bool(recheck or evidence.get("same_session_recheck"))
            graded["goal_observation"] = {
                "node_id": node_id, "question_hash": qh, "difficulty": item.difficulty,
                "channel": CHANNEL_FOR_FORMAT[item.format], "correct": correct, "idk": bool(idk),
                "max_rung": effective_rung, "same_session_recheck": rechecked,
                "previously_seen": previously_seen, "synthetic_idk": bool(refused),
                "independent": effective_rung == 0 and not rechecked and not refused
                and not previously_seen and not evidence.get("assisted", False),
            }

        checkpoint = grade_checkpoint.GradeCheckpoint(
            kind="check", operation_id=claim, user_id=body.user_id,
            session_id=body.session_id, course_id=course_id or None, question_hash=qh,
            goal_version=goal_version(state), evidence=copy.deepcopy(deps.pending_evidence),
            continuation={"graded": graded, "correct": correct, "genuine": genuine,
                          "diagnosis": getattr(outcome, "diagnosis", None), "rendered": rendered,
                          "answer": answer.model_dump(mode="json"), "verdict": verdict, "refused": refused},
        )
        # Treat a lost checkpoint acknowledgment as potentially saved. Never release
        # its claim or call the grader again while that uncertainty exists.
        checkpointed = True
        _save_grade_checkpoint(checkpoint)
        return _finish_check_checkpoint(
            checkpoint, scope, request, loop_on=loop_on, deps=deps, difficulty=item.difficulty
        )
    except BaseException as exc:
        if not checkpointed:
            try:
                _update_loop_state(
                    body.session_id, _under_claim(qh, claim, lambda e: None, release=True)
                )
            except Exception:
                logger.warning("grading claim could not be released")
        if isinstance(exc, PlanningPersistenceUnavailable):
            raise HTTPException(status_code=503, detail="Learning evidence unavailable; retry the same answer") from None
        raise


def _open_grade_checkpoint(entry, body, course_id, *, kind):
    try:
        return grade_checkpoint.open_checkpoint(
            entry.get(grade_checkpoint.KEY), kind=kind, operation_id=entry.get("grading_claim"),
            user_id=body.user_id, session_id=body.session_id, course_id=course_id or None,
            question_hash=body.question_hash,
        )
    except PlanningPersistenceUnavailable:
        raise HTTPException(status_code=503, detail="Saved grade recovery unavailable; retry later") from None


def _save_grade_checkpoint(checkpoint):
    encrypted = grade_checkpoint.seal(checkpoint)  # constant across CAS retries

    def save(doc):
        _refuse_while_closing(doc, _now_s())
        _check_goal_version(doc, checkpoint.goal_version)
        entry = (_steps(doc).get(checkpoint.question_hash) if checkpoint.kind == "check"
                 else _probe_doc(doc).get("current"))
        if (not isinstance(entry, dict) or entry.get("grading_claim") != checkpoint.operation_id
                or (checkpoint.kind == "probe" and entry.get("question_hash") != checkpoint.question_hash)):
            raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
        entry[grade_checkpoint.KEY] = encrypted
        entry["grading_claim_at"] = _now_s()

    _update_loop_state(checkpoint.session_id, save, require_open=True, require_existing=True)


#: spec §13 A123: _flush_grade_checkpoint's answer when the commit refused the
#: grade because staff retired its item meanwhile (EvidenceItemRetired)
_ITEM_RETIRED = object()
_RETIRED_DETAIL = "This question was withdrawn. Select another check to continue."


def _flush_grade_checkpoint(checkpoint, request, *, loop_on, deps=None):
    def guard(doc):
        _refuse_while_closing(doc, _now_s())
        _check_goal_version(doc, checkpoint.goal_version)
        if checkpoint.kind == "probe":
            _require_phase(doc, "probe")
            entry = _probe_doc(doc).get("current")
        else:
            _require_teaching(doc)
            entry = _steps(doc).get(checkpoint.question_hash)
            if doc.get("current") != checkpoint.question_hash:
                raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
        if (not isinstance(entry, dict) or entry.get("grading_claim") != checkpoint.operation_id
                or grade_checkpoint.KEY not in entry):
            raise HTTPException(status_code=409, detail=_ALREADY_GRADED)

    # The durable claim excludes goal changes and close. A conditional write
    # also checks ended_at/close_json before any replay can write evidence.
    _update_loop_state(checkpoint.session_id, guard, require_open=True, require_existing=True)
    deps = deps or SaplingDeps(
        user_id=checkpoint.user_id, course_id=checkpoint.course_id, supabase=None,
        request_id=_request_id(request), session_id=checkpoint.session_id,
        feature="loop_check" if checkpoint.kind == "check" else "loop_probe", learning_loop=loop_on,
    )
    deps.pending_evidence = copy.deepcopy(checkpoint.evidence)
    try:
        flush_pending(deps, checkpoint.course_id)
    except EvidenceObservationSuperseded as exc:
        # The original answer has no committed receipt, and a newer observation
        # is already authoritative — or (A123, EvidenceItemRetired) staff retired
        # the item while it was graded, so the grade is void by definition and
        # nothing was written. Never apply the old answer out of order or
        # invent a diagnosis; retire its pose and ask for fresh evidence.
        def supersede(doc):
            if checkpoint.kind == "check":
                def retire(entry):
                    entry["grading_superseded"] = True
                    entry["discarded_grade_operation_id"] = checkpoint.operation_id
                _under_claim(checkpoint.question_hash, checkpoint.operation_id, retire, release=True)(doc)
                if doc.get("current") == checkpoint.question_hash:
                    doc["current"] = None
            else:
                _under_probe_claim(checkpoint.question_hash, checkpoint.operation_id, _not_asked)(doc)

        _update_loop_state(checkpoint.session_id, supersede, require_open=True, require_existing=True)
        return _ITEM_RETIRED if isinstance(exc, EvidenceItemRetired) else False
    except PlanningPersistenceUnavailable:
        raise HTTPException(status_code=503, detail="Learning evidence unavailable; retry the same answer") from None
    try:
        receipt = read_evidence_receipt(checkpoint.user_id, checkpoint.operation_id)
        if receipt is None or receipt.get("course_id") != checkpoint.course_id:
            raise PlanningPersistenceUnavailable("Saved grade receipt unavailable")
    except PlanningPersistenceUnavailable:
        raise HTTPException(status_code=503, detail="Saved grade recovery unavailable; retry the same answer") from None
    _ledger(mark_graded, checkpoint.user_id, checkpoint.question_hash)
    return receipt


def _committed_grade_observation(checkpoint, receipt, node_id):
    """Use the final serialized writer's exposure provenance, never a stale guess.

    Another session may have answered this question after the grader began.
    The original grade stays frozen, but only the committed receipt can attest
    that this particular exposure was fresh and independently useful.
    """
    try:
        matches = [PlanningObservation.model_validate(row) for row in receipt["observations"]
                   if row.get("node_id") == node_id and row.get("question_hash") == checkpoint.question_hash]
        original = next(row for row in checkpoint.evidence if row["node_id"] == node_id)
        if len(matches) != 1:
            raise ValueError("Saved grade observation unavailable")
        final = matches[0].model_dump(mode="json")
        for key in ("check_item_id", "channel", "correct", "idk", "max_rung"):
            if final[key] != original[key]:
                raise ValueError("Saved grade observation disagrees")
        for key in ("difficulty", "synthetic_idk"):
            if final[key] != original["planning_provenance"][key]:
                raise ValueError("Saved grade immutable provenance disagrees")
        if original.get("same_session_recheck") and not final["same_session_recheck"]:
            raise ValueError("Saved grade recheck provenance weakened")
        if original["planning_provenance"]["previously_seen"] and not final["previously_seen"]:
            raise ValueError("Saved grade exposure provenance weakened")
        return final
    except Exception:
        raise HTTPException(status_code=503, detail="Saved grade recovery unavailable; retry the same answer") from None


class _BandOutcome(NamedTuple):
    """One graded check's band-control verdict (spec §13 A122). `stored` is
    what the graded step keeps for its feedback turn to apply (ids, the enum,
    an int) — None for HOLD, which adjusts nothing; the rest feeds the events."""

    stored: dict | None
    verdict: policy.BandVerdict
    p_known: float
    opps: int
    difficulty: int | None
    prerequisite_ids: list[str]


def _graded_difficulty(difficulty: int | None, checkpoint) -> int | None:
    """The graded item's difficulty: the grading request's (it holds the item),
    else — a saved grade recovered by a later request — the item's, read once
    by its id in the checkpoint's evidence; None when it cannot be read."""
    if type(difficulty) is int:
        return difficulty
    ids = [
        row.get("check_item_id")
        for row in checkpoint.evidence
        if row.get("question_hash") == checkpoint.question_hash and row.get("check_item_id")
    ]
    try:
        item = get_check_item(ids[0]) if ids else None
    except Exception:
        logger.warning("graded item unreadable; band control takes no difficulty step")
        return None
    return item.difficulty if item is not None else None


def _band_verdict(user_id: str, node_id: str, difficulty: int | None) -> _BandOutcome | None:
    """Spec §3.3 band control after ONE graded check (§13 A122), read after its
    evidence is flushed so the window holds it: the concept's opportunity window
    (loop_state_store.opportunity_window: unassisted first-attempt outcomes,
    newest last, across sessions), its decayed learner_state (p_known, opps, the
    A3 max streak) and — for a verdict that checks prerequisites
    (EASIER_CHECK_PREREQS, WHEELSPIN) — its prerequisite parents, from which
    policy.repair_target picks the weakest unproficient one. Typed state in
    (policy.band_verdict, invariant 4); never the student's text. None when a
    read failed: the grade stands, no verdict is applied — never an invented
    one — and the next graded check decides again from the durable journal."""
    window = opportunity_window(user_id, node_id)
    if window is None:
        return None
    try:
        state = read_states(user_id, [node_id]).get(node_id) or LearnerState(
            user_id=user_id, node_id=node_id
        )
        verdict = policy.band_verdict(
            window,
            p_known=state.p_known,
            opps=state.opps,
            max_streak_unassisted=state.max_streak_unassisted,
        )
        band, _ = _band_of(state)
        adjusts = verdict.action is not policy.BandAction.HOLD
        # prerequisites: the repair target (EASIER_CHECK_PREREQS, WHEELSPIN), and
        # the novice rows of the effective ceiling (prerequisite known or not)
        checks_prereqs = verdict.action in (
            policy.BandAction.EASIER_CHECK_PREREQS,
            policy.BandAction.WHEELSPIN,
        ) or (adjusts and band == "novice")
        prerequisites = _prerequisites(user_id, node_id) if checks_prereqs else []
    except Exception as exc:
        logger.warning("band control skipped for this grade: %s", type(exc).__name__)
        return None
    target = policy.repair_target(prerequisites)
    delta = policy.ceiling_delta(verdict.action)
    stored = None
    if adjusts:
        proficient = policy.prerequisite_status(prerequisites) is policy.PrerequisiteStatus.PROFICIENT
        view = _learner_view(state, band=band, prereq_proficient=proficient)
        stored = {
            "action": verdict.action.value,
            "difficulty": (
                policy.next_difficulty(verdict.action, difficulty)
                if difficulty is not None
                else None
            ),
            "repair": target.node_id if target is not None else None,
            # §3.3's ceiling clause and the ceiling it leaves a fresh item on the
            # concept (0 failed attempts, outside exam mode): the band's row moved
            # by the delta, clamped — gates still apply turn by turn
            "ceiling_delta": delta,
            "ceiling": int(
                policy.ceiling(view, StepState(question_hash=""), band_delta=delta)
            ),
        }
    return _BandOutcome(
        stored=stored,
        verdict=verdict,
        p_known=state.p_known,
        opps=state.opps,
        difficulty=difficulty,
        prerequisite_ids=sorted(p.node_id for p in prerequisites),
    )


def _emit_band_verdict(user_id: str, request_id: str, node_id: str, band: _BandOutcome) -> None:
    """Spec §6 (§13 A122): zpd.band_adjust for every verdict that adjusts
    something (HOLD adjusts nothing), with direction, trigger and window_stats
    (numbers and bools only); and on WHEELSPIN zpd.wheelspin (category error) —
    the spec's "flag instructor": Sapling has no instructor role, so this error
    event IS the flag. The emitters never raise into the request."""
    verdict = band.verdict
    trigger = policy.BAND_TRIGGERS.get(verdict.action)
    if trigger is None:
        return
    stored = band.stored or {}
    zpd_events.emit_zpd_band_adjust(
        user_id=user_id,
        request_id=request_id,
        direction=verdict.action,
        trigger=trigger,
        window_stats={
            "rate": verdict.rate,
            "n": verdict.n,
            "full_windows": verdict.full_windows,
            "stable": verdict.stable,
            "p_known": band.p_known,
            "opps": band.opps,
            "difficulty": band.difficulty,
            "next_difficulty": stored.get("difficulty"),
            "repair": stored.get("repair") is not None,
        },
        ceiling_delta=policy.ceiling_delta(verdict.action),  # spec §13 A122
    )
    if verdict.action is policy.BandAction.WHEELSPIN:
        zpd_events.emit_zpd_wheelspin(
            user_id=user_id,
            request_id=request_id,
            concept_id=node_id,
            opps=band.opps,
            unassisted_next=verdict.rate,
            htc_k=verdict.htc_k,
            prerequisite_ids=list(band.prerequisite_ids),
        )


def _finish_check_checkpoint(checkpoint, scope, request, *, loop_on, deps=None, difficulty=None):
    receipt = _flush_grade_checkpoint(checkpoint, request, loop_on=loop_on, deps=deps)
    if receipt is _ITEM_RETIRED:
        raise HTTPException(status_code=409, detail=_RETIRED_DETAIL)
    if receipt is False:
        raise HTTPException(status_code=409, detail="Newer learning activity was recorded. Select another check to continue.")
    qh, claim = checkpoint.question_hash, checkpoint.operation_id
    c = checkpoint.continuation
    graded, correct, genuine = copy.deepcopy(c["graded"]), c["correct"], c["genuine"]
    committed = _committed_grade_observation(checkpoint, receipt, graded["node_id"])
    if graded.get("goal_observation") is not None:
        graded["goal_observation"].update(committed)
    now = graded["graded_at"]
    # spec §13 A122: the band controller's verdict on the concept, read now that
    # the journal holds this grade; stored on the step under the claim below and
    # applied when its feedback turn is served
    band = _band_verdict(
        checkpoint.user_id, graded["node_id"], _graded_difficulty(difficulty, checkpoint)
    )
    def record_grade(e: dict) -> None:
        if genuine:
            _record_attempt(e, now, failed=not correct)
        if e.get("graded_at") is None:
            e["first_attempt_correct"] = correct
        e["graded"] = int(e.get("graded") or 0) + 1
        e["wrong"] = int(e.get("wrong") or 0) + (0 if correct else 1)
        e.update(graded)

    under = _under_claim(qh, claim, record_grade, release=True)
    diagnosis = c["diagnosis"]

    held = {"last": False}

    def record_grade_and_diagnosis(doc: dict) -> None:
        _refuse_while_closing(doc, _now_s())
        _check_goal_version(doc, checkpoint.goal_version)
        entry = _steps(doc).get(qh)
        held["last"] = isinstance(entry, dict) and entry.get("grading_claim") == claim
        under(doc)
        if held["last"]:
            _steps(doc)[qh]["graded_operation_id"] = claim
            if band is not None and band.stored is not None:
                _steps(doc)[qh][_BAND_CONTROL] = dict(band.stored)
        if held["last"]:  # PKG-10: the attempt log + marker change, on the FRESH document
            carry(doc, diagnosis)
            # PKG-14 (spec §3.4): one more flushed check toward the zpd.rating prompt,
            # in this same write — only an evidence flush counts (A16, invariant 26)
            doc["checks_since_rating"] = int(doc.get("checks_since_rating") or 0) + 1
            held["checks"] = doc["checks_since_rating"]

    # saved NOW: a failed feedback turn is recovered by _phase_for. An exhausted
    # conflict retains the encrypted checkpoint; retry replays the same atomic
    # operation and then materializes this session continuation exactly once.
    state = _update_loop_state(checkpoint.session_id, record_grade_and_diagnosis, require_open=True, require_existing=True)
    if not held["last"]:
        raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
    if band is not None:  # after the save that recorded it under OUR claim: once per grade
        _emit_band_verdict(checkpoint.user_id, _request_id(request), graded["node_id"], band)
    if held["last"]:
        # PKG-10 (spec §13 A75): the row grade_answer marked, written only now —
        # after the ONE flush and the save that recorded the grade under OUR
        # claim (a claim lost to another request writes nothing; never raises)
        if (diagnosis or {}).get("record"):
            try:
                item = get_check_item((_steps(state).get(qh) or {}).get("check_item_id"))
                if item is not None:
                    _write_misconception(checkpoint.user_id, GradeOutcome(diagnosis=diagnosis),
                                         _item_like(item), CheckAnswer.model_validate(c["answer"]))
            except Exception:
                logger.warning("optional misconception rollup unavailable after saved grade")
        # spec §13 A127: a correct, unassisted answer on an isomorph closes the
        # misconceptions its item tests — after the flush and the claimed save
        _resolve_misconceptions(checkpoint, diagnosis, committed, surface="check", request=request)
    ask = held.get("checks", 0) >= ZPD_RATING_EVERY_N_CHECKS
    return _Submission("feedback", state, c["rendered"], scope, c["verdict"], refused=c["refused"], ask_rating=ask)


def _requests_of(run_result) -> int:
    """Model requests a run reports (RunResult.usage / UnfinishedRun.usage()); 0 unknown."""
    usage = getattr(run_result, "usage", None)
    if not hasattr(usage, "requests") and callable(usage):  # UnfinishedRun.usage()
        usage = usage()
    try:
        return int(getattr(usage, "requests", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _write_misconception(user_id: str, outcome, item, answer: CheckAnswer) -> None:
    """PKG-10: write the misconceptions row the grade marked
    (`outcome.diagnosis["record"]`), its evidence_text the text the grader saw
    (encrypted by learning.misconceptions.record). Nothing marked, nothing
    written; the store never raises."""
    mark = (getattr(outcome, "diagnosis", None) or {}).get("record")
    if not mark:
        return
    record(
        user_id,
        mark["node_id"],
        mark["check_item_id"],
        mark["wrong_key"],
        grader_answer_text(item, answer),
        question_hash=getattr(item, "question_hash", None),  # A123: the supporting attempt's item
    )


def _resolve_misconceptions(
    checkpoint, diagnosis: dict | None, committed: dict, *, surface: str, request: Request
) -> list[str]:
    """Spec §13 A127: close what a correct, unassisted answer on an isomorph
    closes — the keys the hook listed for this answer (`diagnosis["resolve"]`:
    the item's keys but one the student's reason matched), judged on the
    grade's FINAL observation (`committed`: the single writer's, with the help
    floor's rung and any re-check it forced). Called by the check route and
    the probe after their one flush and the claimed save that recorded the
    grade (A75 (a)'s order), so a failed flush closes nothing. It never changes
    the response, the phase or the next item (the probe stays a diagnostic,
    A120 (e)). A checkpoint saved before A127 lists no keys: nothing to close.
    Never raises."""
    keys = (diagnosis or {}).get("resolve") or []
    if not keys:
        return []
    try:
        return resolve_after_grade(
            checkpoint.user_id,
            committed["node_id"],
            keys=keys,
            item_id=committed.get("check_item_id"),
            attempt=committed,
            surface=surface,
            session_id=checkpoint.session_id,
            request_id=_request_id(request),
        )
    except Exception:
        logger.warning("misconception resolution unavailable after saved grade")
        return []


def _submission_turn(
    sub: _Submission, body: LoopCheckAnswerBody, request: Request, *, loop_on: bool
) -> _LoopTurn:
    chat_body = ChatBody(session_id=body.session_id, user_id=body.user_id, message=sub.rendered)
    turn = _LoopTurn(
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
    turn.ask_rating = sub.ask_rating
    return turn


# crisis support: a crisis answer leaves the item posed and ungraded (no claim, no evidence)
@router.post(
    "/check/answer",
    dependencies=_screened("loop_check_answer", "answer", "reason", respond=crisis_support.turn_response),
)
async def check_answer(body: LoopCheckAnswerBody, request: Request):
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    await _consume_pending_off_loop(body.session_id, body.user_id)
    sub = await _agent_turn_or_http_error(
        _grade_submission(body, request, loop_on=loop_on), what="loop grader"
    )
    return await _json_turn(
        lambda: _submission_turn(sub, body, request, loop_on=loop_on), "loop feedback agent"
    )


@router.post(
    "/check/answer/stream",
    dependencies=_screened("loop_check_answer", "answer", "reason", respond=crisis_support.turn_stream),
)
async def check_answer_stream(body: LoopCheckAnswerBody, request: Request):
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    await _consume_pending_off_loop(body.session_id, body.user_id)
    sub = await _agent_turn_or_http_error(
        _grade_submission(body, request, loop_on=loop_on), what="loop grader"
    )
    return _sse(_submission_turn(sub, body, request, loop_on=loop_on))


_NO_RATING_ASKED = "no rating was asked for"


@router.post("/rating", dependencies=_RATE_LIMITED)
def rating(body: LoopRatingBody, request: Request) -> dict:
    """POST /api/learn/loop/rating (PKG-14; spec §3.4, §6): the student's
    perceived difficulty, asked every ZPD_RATING_EVERY_N_CHECKS checks. Emits
    zpd.rating {rating, checks_since_last} and resets the session's counter in
    ONE compare-and-set write; the rating is stored nowhere else. Accepted only
    on an open session whose counter reached ZPD_RATING_EVERY_N_CHECKS (else a
    409, nothing written). Runs no model but is rate-limited (A20); require_self,
    the gate's 404 and the session owner check run first."""
    if not body.user_id:
        body.user_id = get_session_user_id(request)
    _gate(body.user_id, request)
    _session_scope(body.session_id, body.user_id)
    seen: dict = {}

    def reset(state: dict) -> None:
        # review fix round: only an open session, and only when a rating was
        # actually asked for (the counter reached the cadence) — else 409
        _require_open(state)
        count = int(state.get("checks_since_rating") or 0)
        if count < ZPD_RATING_EVERY_N_CHECKS:
            raise HTTPException(status_code=409, detail=_NO_RATING_ASKED)
        seen["count"] = count
        state["checks_since_rating"] = 0

    _update_loop_state(body.session_id, reset)
    zpd_events.emit_zpd_rating(
        user_id=body.user_id,
        request_id=_request_id(request),
        rating=body.rating,
        checks_since_last=seen.get("count", 0),
    )
    return {"ok": True}


# ── "Report this question" (spec §13 A113, A123; GitHub #695) ──────────────
#
# A check item's key comes from a classmate's upload and no instructor reviews
# it, so a student can report a question they were posed: wrong answer, unclear
# or not from my course (enums only). The report is recorded first (the
# database decides, under the item's lock, whether it is the
# ITEM_REPORT_QUARANTINE_MIN_REPORTERS-th distinct reporter); then the item stops
# being served to the reporter: every selection excludes
# loop_state_store.reported_hashes, and the item is taken off the surface it was
# reported from (the loop session's current check; the review session's open
# entry). The report that reaches the threshold QUARANTINES the item
# course-wide (A123): the database holds every row of it (`reports_threshold`,
# A124's hold — every student read drops a held item), nothing is deleted and
# no evidence changes, until staff approve it (restored) or retire it (deleted,
# evidence voided) in the admin queue. A report never deletes anything.

_REPORTED = "learn.check_item_reported"
_QUARANTINED = "learn.check_item_quarantined"
_WITHDRAWN_ITEM = "check item withdrawn"


def _report_flag(user_id: str) -> None:
    """The `item_reports` flag (spec §13 A113): off → the route's 404."""
    if not flag_on(item_reports.ITEM_REPORTS_FLAG, user_id):
        raise HTTPException(status_code=404, detail="Not found")


def _posed_loop_item(body: LoopReportBody) -> CheckItem:
    """The loop surface: an item this session posed (a step keyed by its
    hash, the session the student's own). A withdrawn item is a 409."""
    _session_scope(body.session_id, body.user_id)
    entry = (_load_loop_state(body.session_id).get("steps") or {}).get(body.question_hash)
    if not isinstance(entry, dict) or not entry.get("check_item_id"):
        raise HTTPException(status_code=404, detail="No such check item in this session")
    item = get_check_item(entry["check_item_id"])
    if item is None:
        raise HTTPException(status_code=409, detail=_WITHDRAWN_ITEM)
    return item


def _served_review_item(body: LoopReportBody, now: datetime) -> CheckItem:
    """The review surface: today's review session (the student's, its course
    one they are enrolled in) served this item."""
    _review_course(body.user_id, body.course_id)
    if body.session_id != review.review_session_id(body.user_id, body.course_id, now):
        raise HTTPException(status_code=409, detail=_REVIEW_EXPIRED)  # a new UTC day began
    try:
        view = review.peek_review_session(body.user_id, body.course_id, now)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Session user mismatch") from None
    item = get_check_item(body.item_id)
    if item is None:
        raise HTTPException(status_code=409, detail=_WITHDRAWN_ITEM)
    if item.question_hash not in ((view.get("review") or {}).get("served_hashes") or []):
        raise HTTPException(status_code=404, detail=_REVIEW_CLAIM_DETAIL["not_served"])
    return item


def _clear_reported_current(session_id: str, question_hash: str, now: float) -> None:
    """Take the reported check off the loop session: its step is marked
    reported (a session never re-activates a hash it keyed), and it stops
    being current while it still awaits an answer. A graded step (its feedback
    must still be served) or one being graded is left as it is."""

    def withdraw(state: dict) -> None:
        entry = _steps(state).get(question_hash)
        if not isinstance(entry, dict):
            return
        entry["reported"] = True
        claimed = entry.get("grading_claim") and not (
            now - float(entry.get("grading_claim_at") or 0) > LOOP_GRADING_CLAIM_STALE_S
        )
        if (
            state.get("current") == question_hash
            and entry.get("graded_at") is None
            and grade_checkpoint.KEY not in entry
            and not claimed
        ):
            state["current"] = None

    _update_loop_state(session_id, withdraw)


@router.post("/report", dependencies=_RATE_LIMITED)
def report_item(body: LoopReportBody, request: Request) -> dict:
    """POST /api/learn/loop/report (spec §13 A113; GitHub #695): the student
    reports a check item they were posed — on the loop's check card
    (`surface: loop`, the session's step by `question_hash`) or on Study's
    review queue (`surface: review`, today's review session's item by
    `item_id`). The reason is an enum; nothing else the student writes is
    stored. Idempotent: a repeat records nothing new. The report that reaches
    ITEM_REPORT_QUARANTINE_MIN_REPORTERS quarantines the course item (A123:
    `quarantined` — held from every student until staff decide; nothing is
    deleted). Runs no model but is rate-limited (A20); require_self, the gate's
    404, the `item_reports` flag's 404 and the owner checks run first. 503
    when the report could not be recorded (nothing changed; retry)."""
    if not body.user_id:
        body.user_id = get_session_user_id(request)
    _gate(body.user_id, request)
    _report_flag(body.user_id)
    loop = body.surface == "loop"
    review_now = None if loop else _review_now()
    item = _posed_loop_item(body) if loop else _served_review_item(body, review_now)
    request_id = _request_id(request)
    try:
        outcome = item_reports.record_report(
            body.user_id,
            item.course_id,
            item.question_hash,
            reason=body.reason,
            surface=body.surface,
        )
    except Exception:
        logger.warning("check item report not recorded (course=%s)", item.course_id, exc_info=True)
        raise HTTPException(status_code=503, detail="report not recorded; retry") from None
    # stop serving it to the reporter on the surface it came from (a refresh,
    # /check/next or /review/next then moves on; every selection excludes it)
    if loop:
        _clear_reported_current(body.session_id, item.question_hash, _now_s())
    else:
        try:
            review.drop_reported(body.session_id, item.id, review_now)
        except LoopStateConflict:
            raise _StateConflict() from None
    events_service.log_event(
        _REPORTED,
        category="usage",
        user_id=body.user_id,
        request_id=request_id,
        payload={
            "course_id": item.course_id,
            "question_hash": item.question_hash,
            "reason": body.reason,
            "surface": body.surface,
            "first": outcome.first,
            "reporters": outcome.reporters,
        },
    )
    if outcome.quarantine:
        events_service.log_event(
            _QUARANTINED,
            category="audit",
            user_id=body.user_id,
            request_id=request_id,
            payload={
                "course_id": item.course_id,
                "question_hash": item.question_hash,
                "reporters": outcome.reporters,
            },
        )
    return {"reported": True, "first": outcome.first, "quarantined": outcome.quarantine}


# ── Tool-removed post-test (PKG-14; spec §10 rung 3, A16, A23, A112, A113) ─

#: Every value `zpd.step.phase` may carry (PKG-06's Phase; spec §13 A8 adds
#: "posttest"). The `sessions.close_phase` CHECK is NOT widened: posttest is a
#: step phase only.
STEP_PHASES: tuple[str, ...] = get_args(zpd_events.Phase)
_NOT_A_POSTTEST_ITEM = "not a post-test item"
_ONE_DAY = timedelta(days=1)


def _posttest_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(ts: datetime) -> str:
    """A UTC ISO timestamp with no '+' (safe inside a PostgREST or=(…) filter)."""
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _posttest_window(anchor: datetime, now: datetime) -> int | None:
    """A112/A126: the fixed follow-up window `now` falls in, counted from
    `anchor`, the concept's FIRST graded evidence (practice cannot move it) —
    learning_gain.window_at, the one rule the funnel reads too. A window runs
    until the next one opens and the last closes POSTTEST_LAST_WINDOW_CLOSE_DAYS
    after the anchor, so a window the student was away for is skipped, never
    posed late under its label. None before the first window opens and after
    the last one closes."""
    return window_at(anchor, now)


def _posttest_exposed(user_id: str) -> set[str]:
    """seen ∪ revealed (A23): what a post-test never poses because the student
    has answered it or been shown its answer."""
    return set(seen_hashes(user_id)) | set(revealed_hashes(user_id))


def _posttest_excluded(user_id: str, reported: set[str] | None = None) -> set[str]:
    """seen ∪ revealed (A23) ∪ reported (A113), read once per request (the
    reported set is the caller's when it has read it already)."""
    if reported is None:
        reported = set(reported_hashes(user_id))
    return _posttest_exposed(user_id) | reported


class _CourseNodesRead:
    """A read-only page_all handle over graph_nodes (invariant 1's ast half
    allows the table only as a direct read — check_item_service's pattern)."""

    def select_with_count(self, *args, **kwargs):
        return table("graph_nodes").select_with_count(*args, **kwargs)


def _course_nodes(user_id: str, course_id: str) -> dict[str, str]:
    """node id → concept key of the student's nodes in the course (paged)."""
    return {
        row["id"]: _normalize_concept(row.get("concept_name") or "")
        for row in page_all(
            _CourseNodesRead(),
            "id,concept_name",
            filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
            order="id",
        )
        if row.get("id")
    }


def _read_poses(user_id: str, course_id: str) -> dict[str, dict[int, dict]]:
    """node id → window → the student's post-test pose rows in the course (A87;
    one row per (student, node, window) since A112)."""
    rows = table(_POSES).select(
        "node_id,window_days,question_hash,posed_at,answered_at,claim,claimed_at",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    )
    poses: dict[str, dict[int, dict]] = {}
    for r in rows or []:
        if r.get("node_id"):
            poses.setdefault(r["node_id"], {})[int(r["window_days"])] = r
    return poses


def _pose_open(pose: dict | None, now: datetime) -> bool:
    """Unanswered and younger than POSTTEST_POSE_TTL_HOURS (A89): an expired
    pose is void — it may be re-posed. An unreadable posed_at is void too."""
    if not pose or pose.get("answered_at"):
        return False
    posed = _ts(pose.get("posed_at"))
    return posed is not None and posed >= now - timedelta(hours=POSTTEST_POSE_TTL_HOURS)


def _posed_order(pose: dict) -> tuple:
    """Earliest posed first; an unreadable posed_at sorts first; then the window."""
    return (_ts(pose.get("posed_at")) or datetime.min.replace(tzinfo=timezone.utc), int(pose["window_days"]))


def _open_posed_item(node_poses: dict[int, dict], items: list, now: datetime, reported: set[str]):
    """(pose, item) of the node's OPEN pose whose item is still in the bank — the
    earliest posed, should a race have left two (A87: returned as posed, never
    re-chosen); None when there is none. An open pose whose item was withdrawn
    counts as no pose, as it did before A112, and so does one whose item is in
    `reported` (A113: an item the student reported is never posed again — in
    any window)."""
    by_hash = {i.question_hash: i for i in items if i.question_hash not in reported}
    posed = [
        (p, by_hash[p.get("question_hash")])
        for p in node_poses.values()
        if _pose_open(p, now) and p.get("question_hash") in by_hash
    ]
    return min(posed, key=lambda pi: _posed_order(pi[0]), default=None)


def _bound_item(items: list, node_poses: dict[int, dict], excluded: set[str]):
    """A93 (minor 6), across windows since A112: the node's newest UNANSWERED
    pose (expired, or open with a withdrawn or reported item) keeps its item
    bound to the node — the next pose, a renewal in its window or a later
    window's, is that SAME item, never a fresh one to dodge it — while the item
    is still fresh (A23: neither seen nor revealed since; a stale item would
    grade practice as a delayed outcome) and not reported (A113: `excluded`
    holds the student's reported items, never posed again). None → the
    window's choice (`_window_choice`, A126)."""
    unanswered = [p for p in node_poses.values() if not p.get("answered_at")]
    if not unanswered:
        return None
    qh = max(unanswered, key=_posed_order).get("question_hash")
    if qh in excluded:
        return None
    return next((i for i in items if i.question_hash == qh), None)


def _new_pose(user_id: str, course_id: str, node: str, window: int, choice, span, now: datetime) -> dict:
    """A112: a pose row — its window, the window's fixed anchor (the concept's
    first graded evidence: journal row id and time), and the concept's last
    evidence before the pose with the days since it, the delay an analysis
    stratifies on (truly delayed vs recently practised — practice no longer
    postpones a window). A126: how its item was chosen (`choice`, a
    checks.PosttestChoice: `item_match` against the student's pretest item,
    `item_source` reserve or fallback). The outcome (`correct`, `max_rung`) and
    what the answer reports (`served_at` once the client shows the item; the
    latency and the page-hidden telemetry once it is answered) stay NULL — a
    renewal (A89/A93) resets them all. Hashes, ids, codes, times and numbers
    only."""
    return {
        "user_id": user_id,
        "node_id": node,
        "course_id": course_id,
        "window_days": window,
        "question_hash": choice.item.question_hash,
        "posed_at": now.isoformat(),
        "answered_at": None,
        "claim": None,
        "claimed_at": None,
        "anchor_event_id": span.first_id,
        "anchor_at": span.first_at.isoformat(),
        "last_evidence_at": span.last_at.isoformat(),
        "days_since_evidence": max(0.0, (now - span.last_at) / _ONE_DAY),
        "correct": None,
        "max_rung": None,
        "item_match": choice.match,
        "item_source": choice.source,
        "served_at": None,
        "answer_latency_s": None,
        "hidden_count": None,
        "hidden_s": None,
    }


def _record_poses(rows: list[dict]) -> None:
    """Open (or renew, A89/A93) the poses — one upsert, one row per (student,
    node, window) (A112)."""
    if rows:
        table(_POSES).upsert(rows, on_conflict="user_id,node_id,window_days")


#: spec §13 A126: a due window with nothing fresh to pose, and why — one row
#: per (student, node, window), the latest reason (written by /posttest/start)
_SKIPS = "posttest_skips"


def _skip_row(user_id: str, course_id: str, node: str, window: int, reason: str, now: datetime) -> dict:
    return {
        "user_id": user_id,
        "node_id": node,
        "course_id": course_id,
        "window_days": window,
        "reason": reason,
        "skipped_at": now.isoformat(),
    }


def _record_skips(rows: list[dict]) -> None:
    """A126: record the due windows /posttest/start had to skip, so the funnel
    can count them. One upsert. A measurement record, not the pose: a failed
    write logs and the start still answers (its poses are already committed)."""
    if not rows:
        return
    try:
        table(_SKIPS).upsert(rows, on_conflict="user_id,node_id,window_days")
    except Exception:
        logger.warning("post-test skips not recorded (%d)", len(rows), exc_info=True)


def _stamp_served(user_id: str, node_id: str, question_hash: str, now: datetime) -> bool:
    """A126: the first time the client SHOWS an open pose's item — one
    conditional UPDATE of the open pose (unanswered, within its TTL) whose
    served_at is still NULL, so a reload or a repeat call keeps the first
    display. The server's clock: a latency is answered_at − served_at, both
    stamped here. True when this call stamped it."""
    rows = table(_POSES).update(
        {"served_at": now.isoformat()},
        filters={
            "user_id": f"eq.{user_id}",
            "node_id": f"eq.{node_id}",
            "question_hash": f"eq.{question_hash}",
            "answered_at": "is.null",
            "served_at": "is.null",
            "posed_at": f"gte.{_iso_z(now - timedelta(hours=POSTTEST_POSE_TTL_HOURS))}",
        },
    )
    return bool(rows)


def _claim_pose(
    user_id: str, node_id: str, question_hash: str, claim: str, now: datetime
) -> dict | None:
    """The DB claim (A87): one conditional UPDATE — the OPEN pose of this item
    (unanswered, posed within POSTTEST_POSE_TTL_HOURS, A89), unclaimed, with no
    claim time (m10) or under a claim older than LOOP_GRADING_CLAIM_STALE_S — so
    only one submission grades it, whatever the number of backend processes.
    A112: a node has one row per window, so the open pose's window is read first
    (the earliest posed, should a race have left two) and the UPDATE names it:
    one answer never closes two windows. Returns the claimed row (its posed_at
    and window_days), or None."""
    open_pose = {
        "user_id": f"eq.{user_id}",
        "node_id": f"eq.{node_id}",
        "question_hash": f"eq.{question_hash}",
        "answered_at": "is.null",
        "posed_at": f"gte.{_iso_z(now - timedelta(hours=POSTTEST_POSE_TTL_HOURS))}",
    }
    posed = table(_POSES).select("window_days,posed_at", filters=open_pose) or []
    if not posed:
        return None
    window = int(min(posed, key=_posed_order)["window_days"])
    stale = _iso_z(now - timedelta(seconds=LOOP_GRADING_CLAIM_STALE_S))
    rows = table(_POSES).update(
        {"claim": claim, "claimed_at": now.isoformat()},
        filters={
            **open_pose,
            "window_days": f"eq.{window}",
            "or": f"(claim.is.null,claimed_at.is.null,claimed_at.lt.{stale})",
        },
    )
    return rows[0] if rows else None


def _answer_pose(
    user_id: str,
    node_id: str,
    claim: str,
    now: datetime,
    *,
    correct: bool,
    max_rung: int,
    latency_s: float | None = None,
    hidden_count: int | None = None,
    hidden_s: float | None = None,
) -> bool:
    """m1/m2: re-validate the claim and CLOSE the pose before the one flush —
    a conditional UPDATE on this claim, still unanswered. The same write records
    the post-test OUTCOME (A112): `correct` and the rung the grade carries
    (`max_rung`, the floor after the in-claim re-read; above 0 it is no clean
    delayed outcome) — and, A126, what the answer reports beside it: the
    latency (answered_at − served_at, None when the item's display was never
    stamped) and the page-hidden telemetry, already clamped
    (learning_gain.clamp_visibility). None of it reaches the grade. True → the
    pose is answered for good (a later failure never reopens it: fail closed);
    False → the claim was taken over, and nothing may be written."""
    rows = table(_POSES).update(
        {
            "answered_at": now.isoformat(),
            "claim": None,
            "claimed_at": None,
            "correct": bool(correct),
            "max_rung": int(max_rung),
            "answer_latency_s": latency_s,
            "hidden_count": hidden_count,
            "hidden_s": hidden_s,
        },
        filters={
            "user_id": f"eq.{user_id}",
            "node_id": f"eq.{node_id}",
            "claim": f"eq.{claim}",
            "answered_at": "is.null",
        },
    )
    return bool(rows)


def _release_pose(user_id: str, node_id: str, claim: str) -> None:
    """Nothing was graded: release this claim (an unanswered pose only)."""
    table(_POSES).update(
        {"claim": None, "claimed_at": None},
        filters={
            "user_id": f"eq.{user_id}",
            "node_id": f"eq.{node_id}",
            "claim": f"eq.{claim}",
            "answered_at": "is.null",
        },
    )


def _due_nodes(
    nodes: Iterable[str], poses: Mapping[str, dict[int, dict]], anchors: Mapping[str, datetime], now: datetime
) -> dict[str, int | None]:
    """A112: candidate node → its due, unanswered window, or None when only an
    open pose keeps it a candidate (an open pose stays posed until answered or
    expired, even when no window is due). `anchors`: node → its FIRST graded
    evidence time. Shared by /posttest/start and GET /posttest/due."""
    due: dict[str, int | None] = {}
    for node in nodes:
        node_poses = poses.get(node) or {}
        anchor = anchors.get(node)
        window = _posttest_window(anchor, now) if anchor is not None else None
        if window is not None and (node_poses.get(window) or {}).get("answered_at"):
            window = None  # answered: a window is posed at most once
        if window is not None or any(_pose_open(p, now) for p in node_poses.values()):
            due[node] = window
    return due


def _posttest_plans(
    due: Mapping[str, int | None],
    poses: Mapping[str, dict[int, dict]],
    anchors: Mapping[str, datetime],
    items_of: Callable[[str], list],
    now: datetime,
    reported: set[str],
) -> list[tuple]:
    """(order, node, the open pose's item or None, the window to pose or None),
    sorted: open poses first (A87: returned as posed), then the
    earliest-opened windows. An open pose of a withdrawn or reported item
    counts as no pose (A113), so its due window is posed afresh."""
    plans = []
    for node, window in due.items():
        current = _open_posed_item(poses.get(node) or {}, items_of(node), now, reported)
        if current is not None:
            plans.append(((0, _posed_order(current[0])[0], node), node, current[1], None))
        elif window is not None:
            opened = anchors[node] + timedelta(days=window)
            plans.append(((1, opened, node), node, None, window))
    return sorted(plans, key=lambda p: p[0])


def _window_choice(items: list, node_poses: dict[int, dict], excluded: set[str], window: int, pretest):
    """The item a due window poses (A23, A93, A113, A126) — a
    checks.PosttestChoice, or None (nothing fresh: the window is skipped). The
    newest unanswered pose's item first while it is fresh (A93: bound across
    windows, never shopped away); else checks.choose_posttest_item: a fresh
    protected reserve matched to the student's pretest item, else a fallback."""
    bound = _bound_item(items, node_poses, excluded)
    if bound is not None:
        source = "reserve" if bound.question_hash in posttest_reserves(items) else "fallback"
        return PosttestChoice(bound, pretest_match(bound, pretest), source)
    return choose_posttest_item(
        items, excluded, window_index=POSTTEST_WINDOWS_DAYS.index(window), pretest=pretest
    )


@router.post("/posttest/start", dependencies=_RATE_LIMITED)
def posttest_start(body: PosttestStartBody, request: Request) -> dict:
    """Rung 3 (spec §10) at FIXED follow-up windows (A112): this student's
    post-test items for one course. A concept is due when `now` falls in one of
    POSTTEST_WINDOWS_DAYS counted from its FIRST graded evidence (the journal's
    earliest evidence row: practice cannot postpone it) and that window is not
    answered yet — each window is posed at most once per student, concept and
    window, a window the student was away for is skipped, and the last one
    closes POSTTEST_LAST_WINDOW_CLOSE_DAYS after the anchor (A126). The item is
    a fresh protected reserve matched to the student's pretest item, else a
    fresh fallback (A126, `_window_choice`; a confirmed key, then the lint
    tier, A124/A113, so an `unsourced` item comes after one with its sources,
    A128) — never one seen or revealed (A23), reported (A113), or held or
    retired (A124, A123: a held item is not in the course's items); an
    unanswered pose's item stays bound to the node while it is fresh (A93) —
    never once reported (an open pose of a reported item counts as no pose,
    like a withdrawn one). A due window with nothing fresh is skipped and the
    skip recorded with its reason (`posttest_skips`, A126). Open poses first,
    then the earliest-opened
    windows, at most POSTTEST_MAX_ITEMS. It COMMITS when opened (A87): the pose
    records its window, its anchor, the days since the concept's last evidence
    and how its item was chosen, and a repeat start returns the same item for a
    node with an open pose — never a fresh one. The pose only: the prompt
    verbatim and an mc_reason item's options, never a key or a reference. No
    brief, no RAG, no tutor, no session row, no model call. Rate-limited (A20)."""
    if not body.user_id:
        body.user_id = get_session_user_id(request)
    _gate(body.user_id, request)
    now = _posttest_now()
    nodes = _course_nodes(body.user_id, body.course_id)
    poses = _read_poses(body.user_id, body.course_id)
    spans = evidence_spans(body.user_id, body.course_id)
    anchors = {node: span.first_at for node, span in spans.items()}
    due = _due_nodes(nodes, poses, anchors, now)
    if not due:
        return {"items": []}
    by_key = items_for_concepts(body.course_id, sorted({nodes[n] for n in due}))
    # A113: read once — an item the student reported is never posed again: an
    # open pose of it counts as no pose, a bound one is excluded (the choice
    # excludes it too; a held or retired item is gone from the course's items)
    reported = set(reported_hashes(body.user_id))
    plans = _posttest_plans(
        due, poses, anchors, lambda node: by_key.get(nodes[node]) or [], now, reported
    )
    exposed = _posttest_exposed(body.user_id) if any(p[2] is None for p in plans) else set()
    excluded = exposed | reported
    out: list[dict] = []
    new: list[dict] = []
    skips: list[dict] = []
    for _, node, item, window in plans:
        if item is None:
            items = by_key.get(nodes[node]) or []
            span = spans[node]
            # A126: the student's pretest item — the concept's first graded item
            pretest = next((i for i in items if i.question_hash == span.first_hash), None)
            choice = _window_choice(items, poses.get(node) or {}, excluded, window, pretest)
            if choice is None:  # nothing fresh left for this concept: skipped, and why
                reason = posttest_skip_reason(items, exposed=exposed)
                skips.append(_skip_row(body.user_id, body.course_id, node, window, reason, now))
                continue
            new.append(_new_pose(body.user_id, body.course_id, node, window, choice, span, now))
            item = choice.item
        out.append({"node_id": node, **_pose_payload(item)})
        if len(out) >= POSTTEST_MAX_ITEMS:
            break
    _record_poses(new)
    _record_skips(skips)
    for row in new:  # A93: posed — in the scan set until graded
        _ledger(record_posed, body.user_id, row["question_hash"], source="posttest")
    clear_posttest_due_cache(body.user_id)
    return {"items": out}


def _posttest_node(user_id: str, node_id: str) -> dict:
    rows = (
        table("graph_nodes").select(
            "id,course_id,concept_name",
            filters={"id": f"eq.{node_id}", "user_id": f"eq.{user_id}"},
            limit=1,
        )
        or []
    )
    if not rows or not rows[0].get("course_id"):
        raise HTTPException(status_code=404, detail="Node not found")
    return rows[0]


def _posttest_reported(user_id: str, question_hash: str) -> bool:
    """A113 across A112's windows: an item the student reported is never posed
    again, so an open pose of it is not answerable either — /posttest/start
    replaces such a pose in its own window, but one left open in an EARLIER
    window (the next window was posed with a fresh item) would otherwise still
    be claimable. Read before the claim: a refusal claims and records nothing.
    An unreadable reported set refuses too (503, fail closed)."""
    try:
        return question_hash in reported_hashes(user_id)
    except Exception:
        logger.warning("post-test: reported items unread; the answer is refused", exc_info=True)
        raise HTTPException(status_code=503, detail="post-test unavailable; retry") from None


def _posttest_floor(user_id: str, node_id: str, item, posed_at: datetime | None) -> int:
    """A88/A89: the open post-test item's grading floor — `_reveal_floor`
    (revealed → no credit; an unscanned marker since the pose → assisted), and
    RUNG_NO_CREDIT_MIN when the node has ANY evidence journaled after the pose
    (the student worked the concept in between; owner 2). An unreadable pose
    time or evidence read is assisted at least (fail closed)."""
    floor = _reveal_floor(user_id, item, posed_at)
    if posed_at is None:
        return max(floor, RUNG_ASSISTED_MIN)
    since = recent_evidence(user_id, node_id, since=_iso_z(posed_at))
    if since is None:
        logger.warning("post-test evidence read failed; the grade is assisted")
        return max(floor, RUNG_ASSISTED_MIN)
    if since:
        return max(floor, RUNG_NO_CREDIT_MIN)
    return floor


# crisis support: a crisis answer leaves the pose open and unclaimed, nothing graded
@router.post(
    "/posttest/answer",
    dependencies=_screened(
        "loop_posttest_answer", "answer", "reason", respond=crisis_support.plain_response(graded=False)
    ),
)
async def posttest_answer(body: PosttestAnswerBody, request: Request):
    """Grade the node's OPEN post-test pose (A87) through grade_answer (A16):
    ceiling H0, max_rung 0, no session — unless the item was revealed or seen
    since it was posed, when the grade carries no unassisted credit (A86). An
    item the student reported is never graded here (A113, any window: 409
    before the claim, `_posttest_reported`).
    The pose is claimed by one conditional UPDATE, so it is graded once; a
    refusal (A33) releases the claim and asks again (never an idk here); an
    outage or the grade cap releases it too and is a 503 with nothing recorded
    for either outcome (invariant 28). A126: the pose also records the answer
    latency (answered_at − the served_at /posttest/shown stamped) and the
    page-hidden telemetry the client sends — untrusted, clamped
    (learning_gain.clamp_visibility), and never read by the grade."""
    if not body.user_id:
        body.user_id = await guard_off_loop(get_session_user_id, request)
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    node = _posttest_node(body.user_id, body.node_id)
    course_id, key = node["course_id"], _normalize_concept(node.get("concept_name") or "")
    items = items_for_concepts(course_id, [key]).get(key) or []
    item = next((i for i in items if i.question_hash == body.question_hash), None)
    if item is None:
        raise HTTPException(status_code=404, detail="check item not found")
    if not body.idk:
        if item.format == "mc_reason" and not body.selected_option:
            raise HTTPException(status_code=422, detail="an mc_reason answer needs selected_option")
        if item.format != "mc_reason" and not body.answer:
            raise HTTPException(status_code=422, detail="a free answer needs answer")
    if _posttest_reported(body.user_id, item.question_hash):
        raise HTTPException(status_code=409, detail=_NOT_A_POSTTEST_ITEM)
    now = _posttest_now()
    claim = str(uuid.uuid4())
    pose = _claim_pose(body.user_id, body.node_id, item.question_hash, claim, now)
    if pose is None:  # not posed, answered, claimed, or expired (A89) → 409
        raise HTTPException(status_code=409, detail=_NOT_A_POSTTEST_ITEM)
    answered = False
    try:
        floor = Rung(_posttest_floor(body.user_id, body.node_id, item, _ts(pose.get("posed_at"))))
        band, p_before = _band_for(body.user_id, body.node_id)
        deps = SaplingDeps(
            user_id=body.user_id,
            course_id=course_id,
            supabase=None,
            request_id=_request_id(request),
            session_id=None,
            feature="loop_posttest",
            learning_loop=loop_on,
        )
        answer = CheckAnswer(
            question_hash=item.question_hash,
            answer_text=body.answer,
            selected_option=body.selected_option,
            reason=body.reason,
            idk=body.idk,
        )
        # A76: every grading caller decides the re-check through the one helper
        # (no session log here: the node's journal decides)
        recheck = recheck_after_release(body.user_id, body.node_id, None, now=now, item=item)
        outcome = await grade_answer(
            _item_like(item),
            answer,
            deps=deps,
            node_id=body.node_id,
            max_rung=int(floor),
            same_session_recheck=recheck,
        )
        if outcome.refused:  # A33: checked first — a refused outcome is also unavailable
            return {"graded": False, "refused": True}
        if outcome.unavailable:
            raise HTTPException(status_code=503, detail="grader unavailable")
        # m1/m2: the claim is re-validated and the pose CLOSED before the flush —
        # a taken-over claim writes nothing; a failed flush never reopens the pose
        # A93: the help floor re-read inside the claim, right before the write
        floor = Rung(
            _refloor(deps.pending_evidence, body.user_id, item, _ts(pose.get("posed_at")), int(floor))
        )
        answered_at = _posttest_now()
        # A126: telemetry beside the outcome, bounded by the server's own clock:
        # the item cannot have been hidden for longer than it was on screen
        served = _ts(pose.get("served_at"))
        shown_from = served or _ts(pose.get("posed_at"))
        hidden_count, hidden_s = clamp_visibility(
            body.hidden_count,
            body.hidden_s,
            (answered_at - shown_from).total_seconds() if shown_from else None,
        )
        answered = _answer_pose(
            body.user_id,
            body.node_id,
            claim,
            answered_at,
            correct=bool(outcome.correct),
            max_rung=int(floor),
            latency_s=answer_latency_s(served, answered_at),
            hidden_count=hidden_count,
            hidden_s=hidden_s,
        )
        if not answered:
            raise HTTPException(status_code=409, detail=_NOT_A_POSTTEST_ITEM)
        try:
            changes = flush_pending(deps, course_id)  # ONE call: the post-test's only evidence write
        except EvidenceItemRetired:
            # A123: staff retired the item while it was graded — nothing was
            # written (the grade is void); the pose stays answered, and its
            # outcome is left out of the learning gain by the void rule
            raise HTTPException(status_code=409, detail=_RETIRED_DETAIL) from None
        _ledger(mark_graded, body.user_id, item.question_hash)
    finally:
        if not answered:
            try:
                _release_pose(body.user_id, body.node_id, claim)
            except Exception:
                logger.warning("post-test claim on %s not released", body.node_id, exc_info=True)
        clear_posttest_due_cache(body.user_id)
    _emit_posttest_step(body, request, item, outcome, band, p_before, changes, floor)
    return {"correct": bool(outcome.correct), "confidence": outcome.confidence}


def _posttest_light_limit(user_id: str) -> None:
    """A126: the cheap per-user limit (services/request_limits' in-process
    sliding window) on the two no-model post-test routes — the display stamp
    and the "due" read. Not the A20 rate limit: no model runs behind them."""
    retry = check_rate_limit(
        f"loop_posttest_light:{user_id}", limit=config.LOOP_PROBE_PLAN_READS_PER_MIN, window_sec=60
    )
    if retry is not None:
        raise HTTPException(
            status_code=429, detail="too many requests", headers={"Retry-After": str(retry)}
        )


@router.post("/posttest/shown")
def posttest_shown(body: PosttestShownBody, request: Request) -> dict:
    """A126: the client shows an open pose's item — stamp its `served_at` (the
    first display only; the server's clock), so the answer's latency is
    answered_at − served_at. Writes nothing else: no evidence, no ledger, no
    model. An item with no open pose stamps nothing (`served: false`); a failed
    stamp logs and leaves the latency unknown, never an error the student sees."""
    if not body.user_id:
        body.user_id = get_session_user_id(request)
    _gate(body.user_id, request)
    _posttest_light_limit(body.user_id)
    try:
        stamped = _stamp_served(body.user_id, body.node_id, body.question_hash, _posttest_now())
    except Exception:
        logger.warning("post-test display not stamped", exc_info=True)
        stamped = False
    return {"served": stamped}


# ── "A retention check is due" (spec §13 A126) ───────────────────────────────

#: Client-visible flag (services/feature_flags.py): off → GET /posttest/due
#: 404s and the app shows no badge. Pushing students toward the retention check
#: changes the measurement protocol (pull → push), so it is switched on
#: deliberately — at a trial boundary — not by a deploy.
RETENTION_DUE_FLAG = "retention_due_badge"
#: user id → (monotonic expiry, payload): a per-process TTL cache (CLAUDE.md
#: #98): POSTTEST_DUE_CACHE_S, cleared for the student by /posttest/start and
#: /posttest/answer (the routes that change what is due); other workers and
#: evidence written elsewhere converge within the TTL.
_DUE_CACHE: dict[str, tuple[float, dict]] = {}
_DUE_CACHE_MAX = 10_000
_DUE_LOCK = threading.Lock()


def clear_posttest_due_cache(user_id: str | None = None) -> None:
    """Drop one student's cached "due" answer (every student's with None)."""
    with _DUE_LOCK:
        if user_id is None:
            _DUE_CACHE.clear()
        else:
            _DUE_CACHE.pop(user_id, None)


def _due_cache_get(user_id: str) -> dict | None:
    with _DUE_LOCK:
        hit = _DUE_CACHE.get(user_id)
        if hit is None or hit[0] <= time.monotonic():
            return None
        return copy.deepcopy(hit[1])


def _due_cache_put(user_id: str, payload: dict) -> None:
    with _DUE_LOCK:
        if len(_DUE_CACHE) >= _DUE_CACHE_MAX and user_id not in _DUE_CACHE:
            _DUE_CACHE.pop(min(_DUE_CACHE, key=lambda k: _DUE_CACHE[k][0]))
        _DUE_CACHE[user_id] = (time.monotonic() + POSTTEST_DUE_CACHE_S, copy.deepcopy(payload))


def _read_student_poses(user_id: str) -> dict[str, dict[int, dict]]:
    """node id → window → the student's pose rows, every course (one read)."""
    rows = table(_POSES).select(
        "node_id,course_id,window_days,question_hash,posed_at,answered_at",
        filters={"user_id": f"eq.{user_id}"},
    )
    poses: dict[str, dict[int, dict]] = {}
    for r in rows or []:
        if r.get("node_id"):
            poses.setdefault(r["node_id"], {})[int(r["window_days"])] = r
    return poses


def _retention_due(user_id: str, now: datetime) -> dict:
    """Does the student have a retention check to take now — an open pose
    whose item can still be answered, or a due, unanswered window with an item
    /posttest/start would pose? The same rules as /posttest/start
    (`_due_nodes`, `_open_posed_item`, `_window_choice`), never a pose: nothing
    is written. Cheap first: one anchors read and one poses read; only when
    some node is a candidate, its courses' items and the exclusion sets."""
    rows, _ = posttest_anchors(user_id=user_id)
    anchors: dict[str, dict] = {}
    anchor_at: dict[str, datetime] = {}
    for row in rows:
        at = _ts(row.get("anchor_at"))
        if row.get("node_id") and row.get("course_id") and at is not None:
            anchors[row["node_id"]] = row
            anchor_at[row["node_id"]] = at
    poses = _read_student_poses(user_id)
    due = _due_nodes(anchors, poses, anchor_at, now)
    if not due:
        return {"due": False, "course_ids": []}
    by_course: dict[str, list[str]] = {}
    for node in due:
        by_course.setdefault(anchors[node]["course_id"], []).append(node)
    reported = set(reported_hashes(user_id))
    excluded: set[str] | None = None
    courses = []
    for course_id, course_nodes in sorted(by_course.items()):
        keys = {n: _normalize_concept(anchors[n].get("concept_name") or "") for n in course_nodes}
        by_key = items_for_concepts(course_id, sorted(set(keys.values())))
        for node in course_nodes:
            items = by_key.get(keys[node]) or []
            node_poses = poses.get(node) or {}
            if _open_posed_item(node_poses, items, now, reported) is not None:
                courses.append(course_id)
                break
            if due[node] is None:
                continue
            if excluded is None:
                excluded = _posttest_exposed(user_id) | reported
            if _window_choice(items, node_poses, excluded, due[node], None) is not None:
                courses.append(course_id)
                break
    return {"due": bool(courses), "course_ids": courses}


@router.get("/posttest/due")
def posttest_due(request: Request, user_id: str = Query("")) -> dict:
    """A126: {due, course_ids} — whether the student has a retention check to
    take now (`_retention_due`), for the app's "retention check due" badge on
    Study and the Dashboard. Behind the `retention_due_badge` flag (off → 404)
    and the loop gate; cached per student for POSTTEST_DUE_CACHE_S. Read-only:
    it never opens a pose. A failed read is a 503 (the badge stays hidden),
    never a "nothing due" it cannot vouch for."""
    if not user_id:
        user_id = get_session_user_id(request)
    _gate(user_id, request)
    if not flag_on(RETENTION_DUE_FLAG, user_id):
        raise HTTPException(status_code=404, detail="Not found")
    cached = _due_cache_get(user_id)
    if cached is not None:
        return cached
    _posttest_light_limit(user_id)
    try:
        payload = _retention_due(user_id, _posttest_now())
    except Exception:
        logger.warning("retention-due read failed", exc_info=True)
        raise HTTPException(status_code=503, detail="retention status unavailable") from None
    _due_cache_put(user_id, payload)
    return payload


def _emit_posttest_step(body, request, item, outcome, band, p_before, changes, floor: Rung) -> None:
    """zpd.step for one graded post-test answer. p_known_after is read honestly
    (m8): the flush's result, else the node's stored state now — never a prior
    for a node with no row; when neither exists the step is not emitted (fail
    closed, as _emit_step does)."""
    correct = bool(outcome.correct)
    after = next(
        (c.get("after") for c in changes or [] if isinstance(c, dict) and c.get("after") is not None),
        None,
    )
    try:
        if after is None:
            state = _learner_state(body.user_id, body.node_id)
            if state is None:
                raise LookupError("no learner-state row")
            after = state.p_known
        after = float(after)
    except Exception:
        logger.warning("zpd.step not emitted for post-test %s: no p_known_after", item.question_hash)
        return
    evidence = outcome.evidence or {}
    zpd_events.emit_zpd_step(
        user_id=body.user_id,
        request_id=_request_id(request),
        concept_id=body.node_id,
        question_hash=item.question_hash,
        phase="posttest",
        channel=evidence.get("channel") or CHANNEL_FOR_FORMAT[item.format],
        band=band,
        # H0 — or, for an item a teach turn revealed, the rung it was graded at (A86)
        ceiling=floor,
        ceiling_reason=policy.CeilingReason.POSTTEST,
        first_attempt_correct=correct,
        n_attempts=1,
        max_rung_used=floor,
        rungs=[],
        time_to_first_attempt_ms=None,
        time_to_correct_ms=None,
        independent_time_ms=None,
        assisted=int(floor) >= RUNG_ASSISTED_MIN,
        confidence=outcome.confidence,
        fsrs_rating=policy.evidence_for_rung(correct, floor).fsrs_rating,
        p_known_before=p_before,
        p_known_after=after,
        r_before=None,
        item_difficulty=item.difficulty,
        grader_backend=outcome.grader_backend,
        variant=arms.variant_for(body.user_id, body.node_id, _arm_for(body.user_id, request)),
    )  # no tier: no tutor turn ran (omitted, never zeroed)


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


# ── Spec §13 A133/A134: one attempt's structured signals ────────────────────

#: steps[qh] key (spec §13 A134): keyed digests of the answer tokens the
#: student's COUNTED attempts on the item held — the strict rule's novelty
#: memory, kept whichever rule is in force so the zpd.attempt measurement
#: (A133) sees repeats under either. A digest is HMAC-SHA256 under a key
#: derived from ENCRYPTION_KEY, over the item's hash and the token: neither a
#: token nor the attempt text is stored, and the same word on two items does
#: not match.
_ATTEMPT_TOKENS = "attempt_tokens"
_ATTEMPT_TOKEN_KEY = derive_key("learning/attempt-tokens")
#: hex characters kept per digest (48 bits: a new token's chance of matching
#: one of a step's HELP_NOVELTY_DIGESTS_MAX digests is about 1 in 10^12)
_ATTEMPT_TOKEN_HEX = 12


def _token_digest(question_hash: str, value: str) -> str:
    mac = hmac.new(_ATTEMPT_TOKEN_KEY, f"{question_hash}\x1f{value}".encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:_ATTEMPT_TOKEN_HEX]


def _help_anchor(entry: dict) -> float | None:
    """When the student last got help on the item: the last rung shown, else
    the pose (the M1 rung anchor; spec §13 A134 measures time alone from it)."""
    return entry.get("last_rung_at") if entry.get("last_rung_at") is not None else entry.get("first_shown_at")


@dataclass(frozen=True)
class _AttemptSignals:
    """Spec §13 A134: what one attempt shows, measured on the attempt — never
    its length, never the item's key. `standard` is the §3.3 rule's verdict
    (A120's hedge tolerance included), `strict` the strict rule's."""

    alone_s: float  # since the latest help on the item (the last rung shown, else the pose)
    required_s: float  # the band's independent-time gate (variant, A5 time scale)
    novel: bool
    digests: frozenset[str]
    standard: bool
    strict: bool


def _attempt_signals(
    text: str, qh: str, entry: dict, check, *, standard: bool, band: str, variant: str, now: float
) -> _AttemptSignals:
    """The strict rule's inputs and verdict for one attempt on the step
    `entry` (gates.attempt_novelty and gates.strict_genuine_attempt): time
    alone since the latest help, novelty against the earlier counted attempts
    and the item's stem. Computed whichever rule is in force."""
    alone_s = _seconds_since(_help_anchor(entry), now)
    novel, digests = gates.attempt_novelty(
        text,
        stem=getattr(check, "prompt", None),
        seen=entry.get(_ATTEMPT_TOKENS) or (),
        digest=lambda value: _token_digest(qh, value),
    )
    scale = config.LEARNING_GATE_TIME_SCALE
    return _AttemptSignals(
        alone_s=alone_s,
        required_s=gates.independent_time_required(band, time_scale=scale, variant=variant),
        novel=novel,
        digests=digests,
        standard=standard,
        strict=gates.strict_genuine_attempt(
            standard, alone_s, novel, band, time_scale=scale, variant=variant
        ),
    )


def _remember_attempt_tokens(entry: dict, digests: frozenset[str]) -> None:
    """Add a counted attempt's token digests to the step's novelty memory,
    oldest kept first, at most HELP_NOVELTY_DIGESTS_MAX (past it a later
    attempt is compared with what is kept: the check errs toward counting)."""
    kept = list(entry.get(_ATTEMPT_TOKENS) or [])
    have = set(kept)
    for d in sorted(digests - have):
        if len(kept) >= HELP_NOVELTY_DIGESTS_MAX:
            break
        kept.append(d)
    entry[_ATTEMPT_TOKENS] = kept


def _ms_of(seconds: float) -> int:
    return int(round(max(0.0, seconds) * 1000))


# crisis support: a crisis attempt stops the hint flow — nothing counts toward a hint
@router.post(
    "/step/attempt",
    dependencies=_screened(
        "loop_step_attempt",
        "attempt_text",
        respond=crisis_support.plain_response(genuine=False, counted=False),
    ),
)
def step_attempt(body: LoopAttemptBody, request: Request) -> dict:
    """Records a genuine attempt for hint unlocking only (spec §3.3). The text
    is judged by gates.is_genuine_attempt and the A33 screen, and never stored,
    never graded. M1 (review round 3): at most ONE attempt counts per rung
    anchor (since the last rung unlock, else the pose), and only one that
    differs from every earlier attempt on the item (`attempt_hashes`), so
    spamming the route cannot open the next rung; the route is rate-limited.

    Spec §13 A134: with the `help_gate_strict` flag on, an attempt counts only
    by the strict rule (gates.strict_genuine_attempt: the band's independent
    time alone since the latest help, and something no counted attempt on the
    item said, not a paste of the stem). Off, the response and every step key
    the §3.3 rule writes are exactly as before A134. Either way the step keeps
    the counted attempts' token digests (`attempt_tokens`) and one zpd.attempt
    records the attempt's signals (spec §13 A133)."""
    _gate(body.user_id, request)
    _session_scope(body.session_id, body.user_id)
    state = _load_loop_state(body.session_id)
    _require_open(state)
    qh = body.question_hash
    entry = _steps(state).get(qh)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail="No such check item in this session")
    check = get_check_item(entry["check_item_id"]) if entry.get("check_item_id") else None
    node_id = _node_for_item(body.user_id, check) if check else None
    band, _ = _band_for(body.user_id, node_id)
    variant = arms.variant_for(body.user_id, node_id or "", _arm_for(body.user_id, request))
    now = _now_s()
    independent_s = _seconds_since(entry.get("first_shown_at"), now)
    standard = bool(
        _genuine(body.attempt_text, independent_s, band, variant)
    ) and not _addresses_grader(body.attempt_text, check)
    strict_on = _help_gate_strict_on(body.user_id)

    def signals_of(e: dict) -> _AttemptSignals:
        return _attempt_signals(
            body.attempt_text, qh, e, check, standard=standard, band=band, variant=variant, now=now
        )

    signals = signals_of(entry)
    genuine = signals.strict if strict_on else standard
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
        fresh = signals_of(e)
        if strict_on and not fresh.strict:
            return  # A134: re-judged on the fresh document (a rung granted, an attempt counted meanwhile)
        _record_attempt(e, now, failed=True)  # the step stays open: a failed genuine attempt
        e["attempt_hashes"] = [*(e.get("attempt_hashes") or []), digest]
        _remember_attempt_tokens(e, fresh.digests)  # A134's novelty memory (either rule)
        counted["yes"] = True

    rung = int(entry.get("rung") or 0)
    if genuine:
        state = _update_loop_state(body.session_id, _on_step(qh, record))
        entry = _steps(state).get(qh) or entry
    zpd_events.emit_zpd_attempt(
        user_id=body.user_id,
        request_id=_request_id(request),
        session_id=body.session_id,
        question_hash=qh,
        concept_id=node_id,
        band=band,
        gate="strict" if strict_on else "standard",
        rung=Rung(min(max(rung, int(Rung.H0)), int(Rung.H6))),
        since_pose_ms=_ms_of(independent_s),
        alone_ms=_ms_of(signals.alone_s),
        gate_ms=_ms_of(signals.required_s),
        novel=signals.novel,
        standard=standard,
        strict=signals.strict,
        counted=bool(counted),
    )
    return {
        "genuine": genuine,
        "counted": bool(counted),
        "attempts": len(entry.get("attempted_at") or []),
        "independent_s": independent_s,
    }


def _mark_earnest_blocked(session_id: str, qh: str, step: StepState, entry: dict) -> None:
    """Spec §10's earnest-revise signal (spec §13 A109): /hint denied a rung
    because the ceiling (or the H6 gate) held, on a step with a genuine attempt
    (`attempted_at` holds genuine attempts only). Never for `no_genuine_attempt`
    or `dwell` — the dwell clock lifts with the same attempt, so it is not the
    ceiling holding. Stored on the step's loop_state entry (a StepState.extra
    key) by the compare-and-set write, so the feedback turn's zpd.step carries
    it. Written once per step. A measurement: a failed write is logged and the
    deny is served unchanged."""
    if not step.attempted_at or entry.get("earnest_blocked") is True:
        return

    def mark(e: dict) -> None:
        if e.get("graded_at") is None and e.get("attempted_at"):
            e["earnest_blocked"] = True

    try:
        _update_loop_state(session_id, _on_step(qh, mark))
    except Exception:
        logger.warning("earnest_blocked not recorded for %s", qh, exc_info=True)


def _rung_gate_denial(step: StepState, now: float) -> dict | None:
    """gates.rung_unlock's denial for /hint — "dwell" when a genuine attempt
    came since the rung anchor, else "no_genuine_attempt" — or None (open)."""
    if gates.rung_unlock(step, now, time_scale=config.LEARNING_GATE_TIME_SCALE):
        return None
    anchor = step.last_rung_at if step.last_rung_at is not None else step.first_shown_at
    attempted = any(t > anchor for t in step.attempted_at)
    return {"denied": "dwell" if attempted else "no_genuine_attempt"}


def _hint_gate_denial(
    body: LoopHintBody, request: Request, entry: dict, step: StepState, now: float
) -> dict | None:
    """`_rung_gate_denial`, worded for the strict rule (spec §13 A134). With
    the `help_gate_strict` flag on, a step with no counted attempt since the
    rung anchor whose time alone with that help is still short of the band's
    independent-time gate answers "dwell" (LoopLearn: "Stay with this step a
    little longer before the next hint.") — the time is what is missing, not
    the attempt. Flag off: exactly `_rung_gate_denial`, and nothing more is read."""
    denied = _rung_gate_denial(step, now)
    if denied != {"denied": "no_genuine_attempt"} or not _help_gate_strict_on(body.user_id):
        return denied
    check = get_check_item(entry["check_item_id"]) if entry.get("check_item_id") else None
    node_id = _node_for_item(body.user_id, check) if check else None
    band, _ = _band_for(body.user_id, node_id)
    variant = arms.variant_for(body.user_id, node_id or "", _arm_for(body.user_id, request))
    required = gates.independent_time_required(
        band, time_scale=config.LEARNING_GATE_TIME_SCALE, variant=variant
    )
    if _seconds_since(_help_anchor(entry), now) < required:
        return {"denied": "dwell"}
    return denied


@router.post("/hint")
def hint(body: LoopHintBody, request: Request) -> dict:
    """Moves the active item's rung up one, behind the dwell / attempt gate, the
    ceiling and — at H6 — the item predicates (A32). The hint TEXT is the next
    `[ACTION: hint]` turn's (PKG-13), deterministic when a leak-clean payload
    exists. No model call. Spec §13 A122: on an item that opens on the worked
    example (`worked_first`, set at activation), the first hint unlocks H4
    with no attempt and no dwell before it while policy.worked_example_rung
    grants it — the example comes FIRST; every later rung keeps the gate."""
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
    may_jump = entry.get("worked_first") is True and step.rung < Rung.H4
    if not may_jump and (denied := _hint_gate_denial(body, request, entry, step, now)):
        return denied
    check = get_check_item(entry["check_item_id"]) if entry.get("check_item_id") else None
    node_id = _node_for_item(body.user_id, check) if check else None
    learner = _learner_state(body.user_id, node_id)
    band, _ = _band_of(learner)
    prereq = _prereq_proficient(body.user_id, node_id) if node_id else True
    view = _learner_view(learner, band=band, prereq_proficient=prereq)
    delta = _band_ceiling_delta(state, node_id)  # spec §13 A122: the band's ceiling only
    jump = policy.worked_example_rung(view, step, worked_first=may_jump, band_delta=delta)
    if jump is None and may_jump and (denied := _hint_gate_denial(body, request, entry, step, now)):
        return denied  # the learner left the worked-example row: the ordinary gate
    # an empty message: showed_work comes from the step alone — the floor-at-H3 rule
    # is applied by the turn that carried the work, never by a hint request
    ceiling, _ = _ceiling_for(
        step=step, learner=view, message="", independent_s=0.0, band_delta=delta
    )
    next_rung = int(jump) if jump is not None else int(step.rung) + 1
    if next_rung > int(ceiling):
        _mark_earnest_blocked(body.session_id, qh, step, entry)
        return {"denied": "ceiling"}
    if next_rung == int(Rung.H6) and not _h6_ok(state, qh, entry, check):
        _mark_earnest_blocked(body.session_id, qh, step, entry)
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
    # A93: the rung is granted now — recorded in the help ledger before its text is served
    _ledger(record_help, body.user_id, qh, next_rung, source="loop", session_id=body.session_id)
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
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    await _consume_pending_off_loop(body.session_id, body.user_id)
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


# crisis support: a crisis topic or goal opens no session (nothing is stashed or
# written). The legacy /api/learn routes that delegate here screen first themselves.
@router.post(
    "/start-session",
    dependencies=_screened("loop_start", "topic", "goal.text", respond=crisis_support.start_response),
)
async def start_session(body: StartSessionBody, request: Request):
    loop_on = await guard_off_loop(_gate, body.user_id, request)
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
    if result.get("materials_unavailable"):
        out["materials_unavailable"] = True  # A128: present only when true
    return out


@router.post(
    "/start-session/stream",
    dependencies=_screened("loop_start", "topic", "goal.text", respond=crisis_support.start_stream),
)
async def start_session_stream(body: StartSessionBody, request: Request):
    loop_on = await guard_off_loop(_gate, body.user_id, request)
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
    _require_no_pending_feedback(state)
    active = state.get("current")
    entry = (state.get("steps") or {}).get(active) if active else None
    now = _now_s()
    if isinstance(entry, dict) and grade_checkpoint.KEY in entry:
        return {"phase": "check", "pending_grade": _pending_grade(state)}
    if _grading_open(entry, now):
        item = get_check_item(entry["check_item_id"]) if entry.get("check_item_id") else None
        if item is not None:  # idempotent (A122: a worked example still owed says so)
            pose = _pose_payload(item, worked_first=_worked_example_owed(body.user_id, state, active))
            return {"phase": "check", "check": pose}

    def activate(st: dict, out: dict) -> None:
        out.clear()
        _require_teaching(st)
        _require_no_pending_feedback(st)  # recheck on the fresh CAS document too
        cur = st.get("current")
        cur_entry = (st.get("steps") or {}).get(cur) if cur else None
        if isinstance(cur_entry, dict) and grade_checkpoint.KEY in cur_entry:
            out["pending_grade"] = _pending_grade(st)
            return
        if _grading_open(cur_entry, now):
            if cur_entry.get("check_item_id") and get_check_item(cur_entry["check_item_id"]):
                out["qh"] = cur  # another request activated one meanwhile
                return
        if cur:
            # withdrawn (A23) or held (A124, A123), graded, or left under a
            # stale claim (C2): drop it; the entry stays
            st["current"] = None
        out["qh"] = _activate_next_item(body.user_id, course_id, st, now=now)
        if out["qh"] is not None:
            # Spec §13 A121: the student chose the check over the tutor's last
            # question; the card is now the one open prompt, so a later chat
            # message is no reply to that question
            st[OPEN_QUESTION_KEY] = False
            # Spec §13 A139 / A138: so is it over an open self-explanation prompt
            # (its row stays 'open': never replied) and over a prequestion card
            # on the concept the check opens (the segment started on a check)
            self_explain.close_open(st)
            node = (st.get("steps") or {}).get(out["qh"], {}).get("node_id")
            rec = prequestion_rules.open_record(st, node)
            if rec is not None:
                records = dict(prequestion_rules.records(st))
                records[node] = {**rec, "status": prequestion_rules.SUPERSEDED}
                st[prequestion_rules.KEY] = records
                out["pq_superseded"] = (node, rec)

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
                arm_session=bool(_arm_for(body.user_id, request)),
            )
            if decision.pause_novice:
                raise AIBudgetExceeded(decision)  # nothing activated, nothing saved
    out: dict = {}
    saved = _update_loop_state(body.session_id, lambda st: activate(st, out))
    if out.get("pending_grade"):
        return {"phase": "check", "pending_grade": out["pending_grade"]}
    qh = out.get("qh")
    if qh is None:  # the cursor may have moved
        saved = _continue_goal(body.session_id, body.user_id, course_id, saved)
        plan = saved.get("plan") if isinstance(saved.get("plan"), dict) else {}
        out = {"phase": _loop_phase(saved), "plan_done": bool(plan.get("done")) and _loop_phase(saved) != "plan", "check": None}
        if saved.get("goal") and isinstance(plan.get("goal_progress"), dict):
            out["goal_progress"] = plan["goal_progress"]
        if saved.get("goal"):
            out["practice_unavailable_node_ids"] = list(plan.get("practice_unavailable_node_ids") or [])
        out.update(_preparing(body.user_id, course_id))  # A128
        return out
    item = get_check_item(saved["steps"][qh]["check_item_id"])
    # A122: an item that opens on the worked example says so (the client asks for it)
    pose = _pose_payload(item, worked_first=_worked_example_owed(body.user_id, saved, qh))
    _ledger(record_posed, body.user_id, qh, source="loop", session_id=body.session_id)  # A93
    save_message(body.session_id, "assistant", pose["prompt"])
    if out.get("pq_superseded"):  # spec §13 A138
        node, rec = out["pq_superseded"]
        _emit_prequestion(
            body.user_id, _request_id(request), body.session_id, node, "superseded",
            question_hash=rec.get("question_hash"),
        )
    return {"phase": "check", "check": pose}


# ── The segment prequestion's answer (spec §13 A138) ───────────────────────
#
# One request records the guess and serves its explanation: the guess is
# stored encrypted (learning_prequestions), the item is revealed for the
# student at once (learning_reveals, A88 — before any text goes out), the
# card's record moves to `answered`, the guess is saved as the student's
# message, and the turn that explains it runs (its lead, from code, is the
# answer; A51 m1). Nothing is graded: no grade_answer, no evidence (invariant
# 26: this route is not an evidence writer), no misconception, no help-ledger
# rung, no band-control input. A retry after a failed explanation (a stored
# guess) ignores the guess fields and serves the explanation again; so does
# the next teach turn, whatever it is.


def _validated_guess(body: PrequestionAnswerBody, item) -> tuple[bool, dict | None]:
    """(no_idea, guess) for a posed prequestion: "no idea"; a choice among the
    item's own letters, with an optional reason (multiple choice); or a
    non-empty answer (free). Anything else is a 422 and nothing is stored."""
    if body.no_idea:
        return True, None
    if item.format == "mc_reason":
        option = (body.option or "").strip()
        if option not in {o.letter for o in item.options or []}:
            raise HTTPException(status_code=422, detail="Choose one of the options, or say you have no idea.")
        return False, {"option": option, "reason": body.reason.strip()}
    answer = body.answer.strip()
    if not answer:
        raise HTTPException(status_code=422, detail="Write a guess, or say you have no idea.")
    return False, {"answer": answer}


async def _prequestion_answer(body: PrequestionAnswerBody, request: Request) -> tuple[dict, tuple[str, str]]:
    """Record the guess (a stored one stands) and return (loop state, scope)
    for the explaining turn. 409 when no prequestion with this hash is open on
    the plan's current concept — or the flag is off for the student."""
    scope = _session_scope(body.session_id, body.user_id)
    course_id = scope[1]
    if not _prequestion_on(body.user_id):
        raise HTTPException(status_code=409, detail=_NO_OPEN_PREQUESTION)
    state = _load_loop_state(body.session_id)
    _require_teaching(state)
    if _pending_grade(state):
        raise HTTPException(status_code=409, detail="Finish checking the saved answer before continuing")
    node = state.get("concept")
    rec = prequestion_rules.record_for(state, node)
    if (
        rec is None
        or state.get("current")
        or rec.get("question_hash") != body.question_hash
        or rec.get("status") not in (prequestion_rules.POSED, prequestion_rules.ANSWERED)
    ):
        raise HTTPException(status_code=409, detail=_NO_OPEN_PREQUESTION)
    item = get_check_item(rec["check_item_id"]) if rec.get("check_item_id") else None
    if item is None:  # A23 withdrawal / A124, A123 holds: nothing left to explain
        raise HTTPException(status_code=409, detail=_NO_OPEN_PREQUESTION)
    if rec.get("status") == prequestion_rules.ANSWERED:
        return state, scope  # a retry: the stored guess stands
    no_idea, guess = _validated_guess(body, item)
    now = _now_s()
    posed = rec.get("posed_at")
    posed_at = datetime.fromtimestamp(
        float(posed) if isinstance(posed, (int, float)) and not isinstance(posed, bool) else now, tz=timezone.utc
    )
    try:
        await asyncio.to_thread(
            store_prequestion_answer,
            user_id=body.user_id,
            session_id=body.session_id,
            course_id=course_id or None,
            node_id=node,
            item=item,
            no_idea=no_idea,
            guess=guess,
            posed_at=posed_at,
        )
    except Exception as exc:
        logger.warning("prequestion guess not stored", exc_info=True)
        raise HTTPException(status_code=503, detail="Your guess could not be saved; try again") from exc
    # its answer is about to be shown: durable now (A88), so the item never
    # serves this student again — a check, a review item or a post-test item
    await asyncio.to_thread(
        _persist_reveals,
        body.user_id,
        body.session_id,
        [item.question_hash],
        unscanned=False,
        source="prequestion",
        at=datetime.fromtimestamp(now, tz=timezone.utc),
    )
    won: dict = {}

    def mark(doc: dict) -> None:
        won.clear()
        _refuse_while_closing(doc, now)
        cur = prequestion_rules.record_for(doc, node)
        if cur is None or cur.get("question_hash") != item.question_hash or doc.get("current"):
            raise HTTPException(status_code=409, detail=_NO_OPEN_PREQUESTION)
        if cur.get("status") == prequestion_rules.POSED:
            records = dict(prequestion_rules.records(doc))
            records[node] = {**cur, "status": prequestion_rules.ANSWERED, "answered_at": now, "no_idea": no_idea}
            doc[prequestion_rules.KEY] = records
            won["first"] = True

    state = _update_loop_state(body.session_id, mark, require_open=True, require_existing=True)
    if won.get("first"):  # a concurrent duplicate records nothing twice
        save_message(
            body.session_id,
            "user",
            prequestion_rules.render_guess(
                no_idea=no_idea,
                answer=body.answer,
                option=(guess or {}).get("option"),
                reason=body.reason,
            ),
        )
        _emit_prequestion(
            body.user_id,
            _request_id(request),
            body.session_id,
            node,
            "answered",
            question_hash=item.question_hash,
            no_idea=no_idea,
            format=item.format,
            difficulty=int(item.difficulty),
        )
    return state, scope


def _prequestion_turn(
    state: dict, scope: tuple[str, str], body: PrequestionAnswerBody, request: Request, *, loop_on: bool
) -> _LoopTurn:
    """The turn that explains the answered prequestion: a teach turn on the
    plan's concept, its message the route's cue (trusted server text; the
    guess is the student's saved message, enveloped in the history, A51)."""
    chat_body = ChatBody(session_id=body.session_id, user_id=body.user_id, message=_PREQUESTION_CUE)
    return _LoopTurn(
        body=chat_body,
        request=request,
        message=_PREQUESTION_CUE,
        kind="prequestion",
        persist_user_row=False,
        state=state,
        scope=scope,
        loop_on=loop_on,
    )


@router.post(
    "/prequestion/answer",
    dependencies=_screened("loop_prequestion_answer", "answer", "reason", respond=crisis_support.turn_response),
)
async def prequestion_answer(body: PrequestionAnswerBody, request: Request):
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    await _consume_pending_off_loop(body.session_id, body.user_id)
    state, scope = await _agent_turn_or_http_error(_prequestion_answer(body, request), what="loop prequestion")
    return await _json_turn(
        lambda: _prequestion_turn(state, scope, body, request, loop_on=loop_on), "loop prequestion agent"
    )


@router.post(
    "/prequestion/answer/stream",
    dependencies=_screened("loop_prequestion_answer", "answer", "reason", respond=crisis_support.turn_stream),
)
async def prequestion_answer_stream(body: PrequestionAnswerBody, request: Request):
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    await _consume_pending_off_loop(body.session_id, body.user_id)
    state, scope = await _agent_turn_or_http_error(_prequestion_answer(body, request), what="loop prequestion")
    return _sse(_prequestion_turn(state, scope, body, request, loop_on=loop_on))


# ── The self-explanation reply (spec §13 A139) ─────────────────────────────


@router.post(
    "/self-explain",
    dependencies=_screened("loop_self_explain", "reply", respond=crisis_support.plain_response(recorded=False)),
)
def self_explain_reply(body: SelfExplainBody, request: Request) -> dict:
    """The student's reply to the open self-explanation prompt, or a skip (an
    empty reply is a skip). Stored encrypted with its juncture
    (learning_self_explanations) and saved as the student's message; never
    graded, never evidence, never a misconception — no model reads it here (the
    next tutor turn may acknowledge it, flag-on prompt only). Then, when the
    prompt closed a segment, the next segment's prequestion is posed (A138:
    the self-explanation comes first, one open prompt at a time)."""
    _gate(body.user_id, request)
    _, course_id = _session_scope(body.session_id, body.user_id)
    if not _self_explain_on(body.user_id):
        raise HTTPException(status_code=409, detail=_NO_OPEN_SELF_EXPLAIN)
    state = _load_loop_state(body.session_id)
    _require_teaching(state)
    prompt = self_explain.open_prompt(state)
    if prompt is None or prompt.get("id") != body.prompt_id:
        raise HTTPException(status_code=409, detail=_NO_OPEN_SELF_EXPLAIN)
    reply = "" if body.skip else body.reply.strip()
    now = _now_s()
    try:
        close_self_explain_prompt(
            prompt,
            user_id=body.user_id,
            session_id=body.session_id,
            course_id=course_id,
            reply=reply or None,
            closed_at=datetime.fromtimestamp(now, tz=timezone.utc),
        )
    except Exception as exc:
        logger.warning("self-explanation reply not stored", exc_info=True)
        raise HTTPException(status_code=503, detail="Your explanation could not be saved; try again") from exc
    pq_on = _prequestion_on(body.user_id)
    out: dict = {}

    def close(doc: dict) -> None:
        out.clear()
        _refuse_while_closing(doc, now)
        cur = self_explain.open_prompt(doc)
        if cur is None or cur.get("id") != body.prompt_id:
            raise HTTPException(status_code=409, detail=_NO_OPEN_SELF_EXPLAIN)
        self_explain.close_open(doc)
        if reply:
            self_explain.set_ack(doc, body.prompt_id)
        out["pose"] = _pose_prequestion(body.user_id, course_id, doc, now=now) if pq_on else _NO_POSE

    _update_loop_state(body.session_id, close, require_open=True, require_existing=True)
    request_id = _request_id(request)
    if reply:
        try:
            save_message(body.session_id, "user", reply)
        except Exception:
            logger.warning("self-explanation reply row not saved", exc_info=True)
    _emit_self_explanation(
        body.user_id,
        request_id,
        body.session_id,
        prompt,
        "replied" if reply else "skipped",
        **({"reply_chars": len(reply)} if reply else {}),
    )
    prequestion = _posed_prequestion(body.user_id, body.session_id, request_id, out.get("pose", _NO_POSE))
    return {
        "recorded": True,
        "status": "replied" if reply else "skipped",
        **({"prequestion": prequestion} if prequestion else {}),
    }


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
    return any(grade_checkpoint.KEY in e or _live(e, "grading_claim", now) for e in entries)


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


def _close_misconception_keys(user_id: str, evidence: list[dict]) -> list[str]:
    """PKG-10: the student's OPEN misconception keys on the concepts this
    session's evidence rows touched (`open_for`; identifier-shaped keys only,
    count descending). No evidence → no read, []. Never raises."""
    node_ids = sorted({e.get("node_id") for e in evidence or [] if e.get("node_id")})
    keys = [r["wrong_key"] for r in open_for(user_id, node_ids) if is_key(r.get("wrong_key"))]
    return list(dict.fromkeys(keys))  # one key open on two nodes is listed once


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
    """The decrypted transcript and this session's evidence journal rows.
    Spec §13 A123: a concept graded in this session against an item staff
    retired since is left out of the close altogether — its void rows are no
    evidence, and the recorded p_before → p_after of its other rows ran
    through the void ones, so they no longer describe a valid trajectory."""
    msgs = table("messages").select(
        "role,content", filters={"session_id": f"eq.{session_id}"}, order="created_at.asc"
    )
    transcript = [
        {"role": m.get("role"), "content": decrypt_if_present(m.get("content"))}
        for m in msgs or []
    ]
    evidence = list(
        table("node_mastery_events").select(
            # A117: the columns learning.probe.is_probe_row binds a row's planning
            # envelope to, so the close counts check-in answers apart; A123: the
            # row id the void filter below reads
            "id,node_id,p_before,p_after,correct,channel,session_id,question_hash,"
            "check_item_id,assisted,max_rung,reason,planning_observation",
            filters={"session_id": f"eq.{session_id}", "event_type": "eq.evidence"},
            order="created_at.asc,evidence_seq.asc",
        )
        or []
    )
    voided = voided_event_ids(session_id=session_id) if evidence else set()
    void_nodes = {e.get("node_id") for e in evidence if e.get("id") in voided}
    return transcript, [e for e in evidence if e.get("node_id") not in void_nodes]


def _measured_before(user_id: str, session_id: str, evidence: list[dict]) -> set[str]:
    """Spec §13 A117: the nodes of this session's evidence that the journal
    measured BEFORE this session did — the node's first evidence row (journal
    order, owner-scoped) belongs to another session or to none (a quiz, a
    post-test). They report their change from the estimate before the session;
    every other node was first measured here and starts at that measurement,
    never at the BKT prior. Propagation is never journaled, so it measures
    nothing. Spec §13 A123: nor does a void row (graded against an item staff
    retired), so the node's first VALID row decides. The student's void ids
    are read once, by node, and each node's are left out of its read before
    the limit. One limit-1 read per node (idx_node_mastery_events_node); a
    failed read propagates (the close is retried, like the evidence read)."""
    out: set[str] = set()
    nodes = list(dict.fromkeys(e.get("node_id") for e in evidence or [] if e.get("node_id")))
    voided = voided_by_node(user_id) if nodes else {}
    for node_id in nodes:
        filters = {
            "graph_nodes.user_id": f"eq.{user_id}",
            "node_id": f"eq.{node_id}",
            "event_type": "eq.evidence",
        }
        if voided.get(node_id):
            filters["id"] = f"not.in.({','.join(pg_quote_value(v) for v in sorted(voided[node_id]))})"
        first = table("node_mastery_events").select(
            "session_id,graph_nodes!inner(user_id)",
            filters=filters,
            order="created_at.asc,evidence_seq.asc",
            limit=1,
        )
        if first and first[0].get("session_id") != session_id:
            out.add(node_id)
    return out


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


async def _model_close(
    draft, *, user_id: str, request_id: str, session_id: str | None = None
) -> object | None:
    """One close run under CLOSE_RUN_TIMEOUT_S (a timed-out run is the
    unavailable agent: the deterministic close is stored)."""
    try:
        return await asyncio.wait_for(
            run_session_close(draft, user_id=user_id, request_id=request_id, session_id=session_id),
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
            raise HTTPException(status_code=404, detail="Session not found")
        PENDING_SESSIONS.pop(session_id, None)
        phase = "close"
        record = fallback_close(build_close([], [], [], measured_before=()))
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
            raise HTTPException(status_code=404, detail="Session not found")
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
                _close_misconception_keys(user_id, evidence),
                # A117: honest baselines, and check-in answers counted apart
                # (the probe history is the claimed document's)
                measured_before=_measured_before(user_id, session_id, evidence),
                probe_hashes=session_probe_hashes(doc),
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
                    out = await _model_close(
                        draft, user_id=user_id, request_id=request_id, session_id=session_id
                    )
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
        body.user_id = await guard_off_loop(get_session_user_id, request)
    await guard_off_loop(_gate, body.user_id, request)
    return await close_session(
        body.session_id, body.user_id, request_id=_request_id(request), rate_limit="raise"
    )


def end_session(body: EndSessionBody, request: Request) -> None:
    """The legacy end_session's loop delegate (PKG-07's pass-through, filled by
    PKG-09): a materialised session with loop state gets its real close first
    (A20 inline check: rate-limited, the deterministic close; the run bounded by
    CLOSE_RUN_TIMEOUT_S); the legacy body then runs unchanged (ended_at, XP,
    the `summary_json` `flashcards._get_session_summary` reads, achievements).
    A pending session keeps the legacy early return. A check still being
    graded — a live grading claim, or a saved grade checkpoint (ADR 0038) —
    propagates the close's 409, and a close that was not acknowledged is a
    503: either way the legacy handler never sets ended_at over an unsettled
    grade (spec §13 A142 corrects A60, which said the session ended without a
    close). Nobody is stuck: a claim with no checkpoint goes stale after
    LOOP_GRADING_CLAIM_STALE_S, and a checkpoint is finished by the student's
    explicit retry (`pending_grade`), after which the end goes through.
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
    except HTTPException:
        raise
    except Exception:
        logger.warning("loop session close was not acknowledged; end deferred")
        raise HTTPException(status_code=503, detail="Session close unavailable; retry ending the session") from None
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

    @property
    def unsourced(self) -> bool:
        """A128: drafted from extracted text after a failed index — the probe
        ranks such an item after an equal one with its sources."""
        return item_unsourced(self.item)

    @property
    def quality(self) -> tuple:
        """Spec §13 A129: checks.serve_quality — the probe ranks an item by it
        among equal challenges (a confirmed key, then clean, never-linted,
        flagged; A128's sourced item first among flagged ones)."""
        return serve_quality(self.item)

    def __getattr__(self, name: str):
        return getattr(self.item, name)


def _require_phase(doc: dict, phase: str) -> None:
    current = _loop_phase(doc)
    if current != phase:
        raise HTTPException(status_code=409, detail=f"phase is {current}")


def _validate_goal(goal, states: dict[str, float]) -> None:
    if goal is not None and not set(goal.target_node_ids) <= set(states):
        raise HTTPException(status_code=422, detail="Choose target concepts from this course")


def _goal_scope_for(state: dict, states: dict[str, float], edges) -> frozenset[str] | None:
    goal = state.get("goal")
    if not isinstance(goal, dict) or not goal.get("target_node_ids"):
        return None
    targets = goal["target_node_ids"]
    if not set(targets) <= set(states):
        raise HTTPException(status_code=422, detail="A goal concept is no longer available; edit the goal")
    return planner.goal_scope(targets, edges, nodes=states)


def _check_goal_version(doc: dict, expected: int) -> None:
    if goal_version(doc) != expected:
        raise HTTPException(status_code=409, detail="Goal changed; refresh the learning session")


def _learning_scope_payload(state: dict) -> dict:
    pr = state.get("probe") or {}
    skills = pr.get("scope", pr.get("skills", []))
    payload = {
        "goal": public_goal(state),
        "goal_version": goal_version(state),
        "diagnosis": probe_policy.diagnostic_summary(
            pr.get("history") or [], skills=skills,
            stop_reason=pr.get("stop_reason"),
            available_difficulties=pr.get("available_difficulties"),
        ),
    }
    plan = state.get("plan") if isinstance(state.get("plan"), dict) else {}
    progress = plan.get("goal_progress")
    if state.get("goal") and isinstance(progress, dict):
        payload["goal_progress"] = copy.deepcopy(progress)
    if state.get("goal"):
        payload["practice_unavailable_node_ids"] = list(plan.get("practice_unavailable_node_ids") or [])
    return payload


def _with_goal_context(history: list, state: dict, user_id: str) -> list:
    goal = public_goal(state)
    if goal is None:
        return history
    names = _plan_node_names(user_id, goal["target_node_ids"])
    text = "Student-confirmed learning goal: " + goal["text"]
    text += "\nTarget concepts: " + ", ".join(names.get(n, n) for n in goal["target_node_ids"])
    text += "\nConnect the approved prerequisites and practice to this objective."
    context = wrap_untrusted(neutralise_control_tags(text), source="student_goal")
    return [_brief_message(context), *history]


@router.post("/goal")
def set_goal(body: LoopGoalBody, request: Request) -> dict:
    """Change confirmed scope before teaching, preserving evidence and fatigue caps."""
    _gate(body.user_id, request)
    # crisis support: the goal text later rides every tutor prompt; it is not stored
    if crisis := crisis_support.screen(
        body.user_id, "loop_goal", body.goal.text if body.goal is not None else None
    ):
        return crisis_support.json_body(crisis)
    _probe_plan_read_limit(body.user_id)
    pending = PENDING_SESSIONS.get(body.session_id)
    if pending is not None:
        if pending.get("user_id") != body.user_id:
            raise HTTPException(status_code=404, detail="Session not found")
        if _loop_phase(pending.get("loop_state") or {}) not in ("probe", "plan"):
            raise HTTPException(status_code=409, detail="Start a new session to change a teaching goal")
        course_id = pending.get("course_id") or ""
    else:
        _, course_id = _session_scope(body.session_id, body.user_id)
    states = _plan_states(body.user_id, course_id)
    _validate_goal(body.goal, states)
    _consume_pending(body.session_id, body.user_id)
    encoded = encode_goal(body.goal)
    now = _now_s()

    def change(doc: dict) -> None:
        _refuse_while_closing(doc, now)
        if _loop_phase(doc) not in ("probe", "plan"):
            raise HTTPException(status_code=409, detail="Start a new session to change a teaching goal")
        pr = _probe_doc(doc)
        current = pr.get("current") or {}
        if current.get("grading_claim"):
            raise HTTPException(status_code=409, detail="Wait for the current answer to finish grading")
        if current.get("question_hash") and current["question_hash"] not in pr["unavailable"]:
            pr["unavailable"].append(current["question_hash"])
        for key in ("skills", "scope", "available_difficulties", "stop_reason", "novice_floor"):
            pr.pop(key, None)
        pr["current"] = None
        doc["goal"], doc["goal_version"] = encoded, goal_version(doc) + 1
        doc.pop("plan", None)
        doc["phase"] = "probe"

    saved = _update_loop_state(body.session_id, change, require_open=True)
    return {"phase": "probe", **_learning_scope_payload(saved)}


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


class _PlanNodesRead:
    """Read-only paging adapter; all graph writes still use graph_service."""
    def select_with_count(self, *args, **kwargs):
        return table("graph_nodes").select_with_count(*args, **kwargs)


class _PlanEdgesRead:
    def select_with_count(self, *args, **kwargs):
        return table("graph_edges").select_with_count(*args, **kwargs)


def _plan_states(user_id: str, course_id: str) -> dict[str, float]:
    """Decayed p_known for every graph node of (user, course) — one
    `graph_nodes` read, one `learner_state` read (PKG-03); BKT_L0 for a node
    with no learner_state row."""
    rows = list(page_all(
        _PlanNodesRead(), "id",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        order="id.asc",
    ))
    ids = [r["id"] for r in rows if r.get("id")]
    states = read_states(user_id, ids)
    return {n: (states[n].p_known if n in states else BKT_L0) for n in ids}


def _plan_prereq_edges(user_id: str, node_ids: list[str]) -> list[tuple[str, str]]:
    """The user's prerequisite edges among `node_ids`, oriented (prerequisite,
    dependent) by EDGE_PREREQ_SOURCE_IS_PREREQ — the direction PKG-03's
    propagation and PKG-07's `_prereq_proficient` read. One `graph_edges` read."""
    rows = list(page_all(
        _PlanEdgesRead(), "id,source_node_id,target_node_id",
        filters={"user_id": f"eq.{user_id}",
                 "relationship_type": f"eq.{PREREQ_RELATIONSHIP_TYPE}"},
        order="id.asc",
    ))
    keep = set(node_ids)
    out = []
    for e in rows:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src in keep and tgt in keep:
            out.append((src, tgt) if EDGE_PREREQ_SOURCE_IS_PREREQ else (tgt, src))
    return out


#: Spec §13 A130: the matched pretest probe start (services/feature_flags.py).
PROBE_MATCHED_PRETEST_FLAG = "probe_matched_pretest"


def _probe_history(doc: dict) -> list:
    """The probe's recorded observations, read without touching the document
    (`_probe_doc` fills defaults in place; this reads only)."""
    pr = doc.get("probe")
    history = pr.get("history") if isinstance(pr, dict) else None
    return history if isinstance(history, list) else []


def _unanchored_skills(user_id: str, skills: list[str], history: list) -> frozenset[str]:
    """Spec §13 A130: the probe's skills whose next graded answer is their
    pretest — no graded answer in this session's probe history
    (`probe.graded_strands`) and no anchor in the evidence journal: the
    `posttest_anchors` SQL function, the one anchor rule the post-test
    windows, the due read and evidence_spans share (a void row anchors
    nothing). The anchors are read only when some skill could still be
    steered. A failed read steers nothing this time — a WARNING, and the
    probe keeps its own first-item rule (the pose later records how well the
    outcome item matched whatever pretest was asked)."""
    open_skills = [n for n in skills if n not in probe_policy.graded_strands(history)]
    if not open_skills:
        return frozenset()
    try:
        rows, _ = posttest_anchors(user_id=user_id)
    except Exception as exc:
        logger.warning("probe: anchors unread (%s); no matched pretest this time", type(exc).__name__)
        return frozenset()
    anchored = {row.get("node_id") for row in rows}
    return frozenset(n for n in open_skills if n not in anchored)


def _probe_course_has_items(course_id: str) -> bool:
    """A23: one `limit=1` read; False for a session with no course."""
    return bool(course_id) and course_has_items(course_id)


def _preparing(user_id: str, course_id: str, *, no_items: bool = False) -> dict:
    """Spec §13 A128: `{"preparing": True}` while the course has no item to
    serve and the student's own upload in it is still being drafted
    (`check_item_service.drafting_pending`), else {} — present only when true.
    `no_items`: the caller already read that the course has none. Advisory
    copy, so a read that fails answers {} (the pre-A128 state), never an error."""
    try:
        if not no_items and _probe_course_has_items(course_id):
            return {}
        return {"preparing": True} if drafting_pending(user_id, course_id) else {}
    except Exception as exc:
        logger.warning("loop: the preparing state could not be read (%s)", type(exc).__name__)
        return {}


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
        f"loop_probe_plan:{user_id}", limit=config.LOOP_PROBE_PLAN_READS_PER_MIN, window_sec=60
    )
    if retry is not None:
        raise HTTPException(
            status_code=429, detail="too many requests", headers={"Retry-After": str(retry)}
        )


def _update_if_changed(session_id: str, doc: dict, mutate: Callable[[dict], None], *, require_open: bool = False) -> dict:
    """`_update_loop_state`, skipped when `mutate` leaves the document as read
    unchanged (a re-served item, a re-GET of the same plan): the mutate runs on a
    copy first; only a real change costs a compare-and-set write."""
    trial = copy.deepcopy(doc)
    mutate(trial)
    if trial == doc:
        return trial
    return _update_loop_state(session_id, mutate, require_open=require_open)


def _claim_live(current: dict, now: float) -> bool:
    if grade_checkpoint.KEY in current:
        return True
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
    item whose answer this student has been shown (`revealed_hashes`), one they
    reported (`reported_hashes`, A113), one the
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
    if _pending_grade(state):
        return {"done": False, "pending_grade": _pending_grade(state), **_learning_scope_payload(state)}
    request_id = _request_id(request)
    version = goal_version(state)
    fixed = (
        (state.get("probe") or {}).get("skills") if isinstance(state.get("probe"), dict) else None
    )
    if fixed is None and not _probe_course_has_items(course_id):
        empty_scope = []
        if state.get("goal"):
            goal_states = _plan_states(body.user_id, course_id)
            goal_edges = _plan_prereq_edges(body.user_id, list(goal_states))
            empty_scope = sorted(_goal_scope_for(state, goal_states, goal_edges) or [])

        def finish_empty(doc: dict) -> None:
            _require_phase(doc, "probe")
            _check_goal_version(doc, version)
            pr = _probe_doc(doc)
            pr["scope"] = empty_scope
            pr["stop_reason"] = "item_bank_exhausted"
            pr["skills"] = []
            pr["current"] = None
            doc["phase"] = "plan"

        saved = _update_loop_state(body.session_id, finish_empty)
        _emit_probe_done(saved, body.user_id, request_id)
        return {
            "done": True,
            "phase": "plan",
            "no_check_items": True,
            # A128: the student's own upload is still being drafted — the UI says
            # "preparing" instead of "no check items" (present only when true)
            **_preparing(body.user_id, course_id, no_items=True),
            **_learning_scope_payload(saved),
        }

    states = _plan_states(body.user_id, course_id)
    edges = _plan_prereq_edges(body.user_id, list(states))
    scope = _goal_scope_for(state, states, edges)
    if fixed is None:
        fringe = planner.outer_fringe(states, edges)
        targets = list((state.get("goal") or {}).get("target_node_ids") or [])
        candidates = targets + fringe + (sorted(scope) if scope is not None else [])
        skills = list(dict.fromkeys(n for n in candidates if scope is None or n in scope))[:PROBE_MAX_SKILLS]
    else:
        skills = [s for s in fixed if isinstance(s, str) and s in states and (scope is None or s in scope)]
    items = _probe_items(body.user_id, course_id, skills)
    # A113: an item the student reported is never posed again, like a revealed one
    revealed = (revealed_hashes(body.user_id) | reported_hashes(body.user_id)) if items else set()
    seen = seen_hashes(body.user_id) if items else set()
    reserves = {  # A23, A126: every concept's protected post-test items
        qh
        for n in {it.node_id for it in items}
        for qh in posttest_reserves([it for it in items if it.node_id == n])
    }
    by_hash = {it.question_hash: it for it in items}
    # spec §13 A130 (flag probe_matched_pretest, off by default): the skills
    # whose next graded answer is their pretest — no graded probe answer in
    # this session and no anchor in the journal — start on a form parallel to
    # their post-test reserves. Off: no anchors read, nothing steered.
    unanchored = (
        _unanchored_skills(body.user_id, skills, _probe_history(state))
        if items and flag_on(PROBE_MATCHED_PRETEST_FLAG, body.user_id)
        else frozenset()
    )
    now = _now_s()
    out: dict = {}

    def select(doc: dict) -> None:
        out.clear()
        _require_phase(doc, "probe")
        _check_goal_version(doc, version)
        _refuse_while_closing(doc, now)
        doc["phase"] = "probe"  # explicit from the first item on
        pr = _probe_doc(doc)
        if pr.get("skills") is None:
            pr["skills"] = list(skills)
        pr["scope"] = sorted(scope) if scope is not None else list(skills)
        pr.setdefault("presented", [])
        cur = pr.get("current")
        if isinstance(cur, dict) and grade_checkpoint.KEY in cur:
            out["pending_grade"] = _pending_grade(doc)
            return
        # Keep fresh teaching practice separately from the delayed posttest.
        # The reserved question stays stable across answers and goal changes.
        practice = pr.setdefault("practice_reserves", {})
        asked = {h.get("question_hash") for h in pr["history"]}
        current_hash = cur.get("question_hash") if isinstance(cur, dict) else None
        forms: dict[str, str] = {}  # A130: node → its matched pretest form
        for node in skills:
            eligible = [it.question_hash for it in items if it.node_id == node
                        and it.question_hash not in reserves | revealed | seen | asked | set(pr["unavailable"])
                        and it.question_hash != current_hash and is_servable(it)]
            # A130: what a pretest form may not be (the reserves are its own rule)
            spent = revealed | seen | asked | set(pr["unavailable"]) | ({current_hash} - {None})
            bank = [it for it in items if it.node_id == node] if node in unanchored else []
            best = pretest_form(bank, spent) if bank else None
            if practice.get(node) not in eligible:
                practice.pop(node, None)
                # A130: teaching keeps another fresh item when there is one, so
                # the probe can ask the best form; with only the form fresh,
                # teaching keeps it (the reserve predates the flag)
                spare = [qh for qh in eligible if best is None or qh != best.question_hash] or eligible
                if spare:
                    practice[node] = max(spare)
            if bank:
                form = pretest_form(bank, spent | {practice.get(node)} - {None})
                if form is not None:
                    forms[node] = form.question_hash
        practice_hashes = set(practice.values())
        pr["available_difficulties"] = {
            n: sorted({it.difficulty for it in items if it.node_id == n
                       and it.question_hash not in reserves | revealed | practice_hashes and is_servable(it)})
            for n in pr["scope"]
        }
        if isinstance(cur, dict) and cur.get("question_hash"):
            qh = cur["question_hash"]
            if (not cur.get("grading_claim") or _claim_live(cur, now)) and qh in by_hash:
                out["item"] = by_hash[qh]  # posed and not answered: the same item again
                return
            # withdrawn (A23) or held (A124, A123), or left under a stale claim
            # (C2): never asked again
            if qh not in pr["unavailable"]:
                pr["unavailable"].append(qh)
            pr["current"] = None
        asked = {h.get("question_hash") for h in pr["history"]}
        if len(set(pr["presented"]) | asked | set(pr["unavailable"])) >= PROBE_SESSION_CAP:
            pr["stop_reason"] = "session_limit"
            doc["phase"], out["done"] = "plan", True
            return
        per_node = Counter(h.get("node_id") for h in pr["history"])
        skill_states = {n: states.get(n, BKT_L0) for n in pr["skills"]}

        def pick(extra_never: set[str]):
            never = (reserves | practice_hashes | revealed | set(pr["unavailable"]) | extra_never) - asked
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
                history=pr["history"],
                # A130: only with a form to ask, so the flag-off call is the one before it
                **({"pretest_forms": forms} if forms else {}),
            )

        item = pick(seen) or pick(set())  # seen items only when nothing unseen is left
        if item is None:
            reason = probe_policy.diagnostic_summary(pr["history"], skills=pr["skills"])["stop_reason"]
            if reason == "observed_boundaries" and set(pr["scope"]) - set(pr["skills"]):
                reason = "coverage_limit"
            pr["stop_reason"] = reason or "item_bank_exhausted"
            doc["phase"] = "plan"
            out["done"] = True
            return
        if item.question_hash not in pr["presented"]:
            pr["presented"].append(item.question_hash)
        pr["current"] = {
            "check_item_id": item.id,
            "question_hash": item.question_hash,
            "node_id": item.node_id,
            "difficulty": item.difficulty,
            "channel": CHANNEL_FOR_FORMAT[item.format],
            "previously_seen": item.question_hash in seen,
        }
        out["item"] = item
        out["new"] = True

    saved = _update_if_changed(body.session_id, state, select)
    if out.get("pending_grade"):
        return {"done": False, "pending_grade": out["pending_grade"], **_learning_scope_payload(saved)}
    if out.get("done"):
        _emit_probe_done(saved, body.user_id, request_id)
        return {"done": True, "phase": "plan", **_learning_scope_payload(saved)}
    item = out["item"]
    if out.get("new"):  # A93: posed — in the scan set until graded
        _ledger(record_posed, body.user_id, item.question_hash, source="probe", session_id=body.session_id)
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
        **_learning_scope_payload(saved),
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
    cur.pop(grade_checkpoint.KEY, None)


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
    if grade_checkpoint.KEY in posed:
        checkpoint = _open_grade_checkpoint(posed, body, course_id, kind="probe")
        return _finish_probe_checkpoint(checkpoint, request, loop_on=loop_on)
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
        # spec §13 A120: the probe feeds the §3.3 slip/misconception rule too —
        # the hook appends this answer to the session attempt log on a copy;
        # the change rides the checkpoint into the claimed save below
        loop_state=copy.deepcopy(state),
    )
    # PKG-10 (spec §13 A76, fix round 3): a probe item is the next graded item
    # on its concept after a release too — the same rule as the check route
    recheck = recheck_after_release(
        body.user_id,
        node_id,
        state,
        now=datetime.fromtimestamp(now, tz=timezone.utc),
        item=item.item,
    )
    checkpointed = False
    synthetic_idk = False
    # A93: a probe item graded with help anywhere (another session's hints, a
    # reveal) carries no unassisted credit — the same help floor as every grade
    floor = _reveal_floor(body.user_id, item.item, None)
    answer = CheckAnswer(
        question_hash=qh,
        answer_text=body.answer,
        selected_option=body.option,
        reason=body.reason,
        idk=idk,
        # spec §13 A127: the stated confidence; an idk (a box or a phrase) states none
        confidence=None if idk else body.confidence,
    )
    try:
        outcome = await grade_answer(
            item.item,
            answer,
            deps=deps,
            node_id=node_id,
            max_rung=floor,
            same_session_recheck=recheck,
            confront=False,  # A120: the probe is a diagnostic — it never sets a marker
        )
        if outcome.refused:  # A33, read BEFORE `unavailable`: never a skip

            disowned = outcome.refused == "disowned_answer"  # A97: never escalated to idk

            def count_refusal(pr: dict, cur: dict) -> None:
                if not disowned:
                    pr["refusals"][qh] = int(pr["refusals"].get(qh) or 0) + 1
                if disowned or pr["refusals"][qh] < CHECK_REFUSALS_AS_IDK:
                    _release(pr, cur)  # nothing was graded: asked again

            state = _update_loop_state(
                body.session_id, _under_probe_claim(qh, claim, count_refusal)
            )
            if (_probe_doc(state).get("current") or {}).get("grading_claim") != claim:
                return {"graded": False, "refused": True}
            synthetic_idk = True
            idk = True  # the CHECK_REFUSALS_AS_IDK-th refusal is an idk observation (A1)
            answer = CheckAnswer(question_hash=qh, idk=True)
            outcome = await grade_answer(
                item.item,
                answer,
                deps=deps,
                node_id=node_id,
                max_rung=floor,
                same_session_recheck=recheck,
                confront=False,
            )
        if outcome.unavailable:  # invariant 28: nothing for either outcome
            _update_loop_state(body.session_id, _under_probe_claim(qh, claim, _not_asked))
            return {"graded": False, "unavailable": True}

        floor = _refloor(deps.pending_evidence, body.user_id, item.item, None, floor)
        previously_seen = bool(posed.get("previously_seen", False)) or qh in seen_hashes(body.user_id)
        _tag_planning_evidence(deps.pending_evidence, item.item, synthetic_idk=synthetic_idk,
                               previously_seen=previously_seen, operation_id=claim, observed_at=now)
        correct = bool(outcome.correct)
        evidence = outcome.evidence or {}
        observation = {
            "node_id": node_id, "question_hash": qh, "difficulty": int(posed["difficulty"]),
            "channel": posed["channel"], "correct": correct,
            "idk": bool(evidence.get("idk", idk)),
            "independent": floor == 0 and not recheck and not synthetic_idk and not previously_seen,
            "max_rung": int(floor), "same_session_recheck": bool(recheck),
            "synthetic_idk": synthetic_idk,
        }
        checkpoint = grade_checkpoint.GradeCheckpoint(
            kind="probe", operation_id=claim, user_id=body.user_id,
            session_id=body.session_id, course_id=course_id or None, question_hash=qh,
            goal_version=goal_version(state), evidence=copy.deepcopy(deps.pending_evidence),
            continuation={"observation": observation, "correct": correct,
                          "check_item_id": item.id,
                          # A120: the attempt log change (and a row to record), re-applied below
                          "diagnosis": getattr(outcome, "diagnosis", None),
                          "answer": answer.model_dump(mode="json")},
        )
        checkpointed = True
        _save_grade_checkpoint(checkpoint)
        return _finish_probe_checkpoint(checkpoint, request, loop_on=loop_on, deps=deps)
    except BaseException as exc:
        if not checkpointed:
            try:
                _update_loop_state(body.session_id, _under_probe_claim(qh, claim, _release))
            except Exception:
                logger.warning("probe grading claim could not be released")
        if isinstance(exc, PlanningPersistenceUnavailable):
            raise HTTPException(status_code=503, detail="Learning evidence unavailable; retry the same answer") from None
        raise


def _finish_probe_checkpoint(checkpoint, request, *, loop_on, deps=None):
    receipt = _flush_grade_checkpoint(checkpoint, request, loop_on=loop_on, deps=deps)
    if receipt is _ITEM_RETIRED:  # A123: the item was retired while it was graded
        return {"graded": False, "unavailable": True, "superseded": True, "withdrawn": True}
    if receipt is False:
        return {"graded": False, "unavailable": True, "superseded": True}
    try:
        node_id = checkpoint.continuation["observation"]["node_id"]
        p_after = (receipt or {}).get("posteriors", {}).get(node_id)
        if type(p_after) not in (int, float) or not 0 <= p_after <= 1:
            raise PlanningPersistenceUnavailable("Saved grade posterior unavailable")
    except PlanningPersistenceUnavailable:
        raise HTTPException(status_code=503, detail="Saved grade recovery unavailable; retry the same answer") from None
    committed = _committed_grade_observation(checkpoint, receipt, node_id)
    observation = {**checkpoint.continuation["observation"], **committed, "p_after": p_after,
                   "grade_operation_id": checkpoint.operation_id}
    diagnosis = checkpoint.continuation.get("diagnosis")  # A120; None before A120
    reference = item = None
    if not checkpoint.continuation["correct"]:
        # Read corrective source text while the checkpoint is still recoverable.
        try:
            item = get_check_item(checkpoint.continuation["check_item_id"])
            reference = item.reference_answer if item is not None else None
        except Exception:
            raise HTTPException(status_code=503, detail="Corrective feedback unavailable; retry the same answer") from None
    out: dict = {}

    def record(pr: dict, _cur: dict) -> None:
        pr["history"].append(observation)
        pr["current"] = None
        out["recorded"] = True
        out["done"] = probe_policy.probe_done(pr["history"], skills=pr.get("skills") or [])
        out["novice_floor"] = probe_policy.novice_floor(pr["history"])
        if out["done"]:
            reason = probe_policy.diagnostic_summary(pr["history"], skills=pr.get("skills") or [])["stop_reason"]
            if reason == "observed_boundaries" and set(pr.get("scope", [])) - set(pr.get("skills", [])):
                reason = "coverage_limit"
            pr["stop_reason"] = reason

    def record_posed(doc: dict) -> None:
        out.clear()
        _require_phase(doc, "probe")
        _refuse_while_closing(doc, _now_s())
        _check_goal_version(doc, checkpoint.goal_version)
        _under_probe_claim(checkpoint.question_hash, checkpoint.operation_id, record)(doc)
        if out.get("recorded"):
            # spec §13 A120: this answer joins the session attempt log the §3.3
            # rule reads, on the FRESH document, in the write that records it
            carry(doc, diagnosis)
        if out.get("done"):
            doc["phase"] = "plan"

    saved = _update_loop_state(checkpoint.session_id, record_posed, require_open=True, require_existing=True)
    if not out.get("recorded"):
        raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
    if (diagnosis or {}).get("record") and item is not None:
        # A120 (A75 (a)'s order): the row the rule marked, written only after the
        # one flush and the save that recorded the answer under OUR claim
        try:
            _write_misconception(
                checkpoint.user_id, GradeOutcome(diagnosis=diagnosis), _item_like(item),
                CheckAnswer.model_validate(checkpoint.continuation["answer"]),
            )
        except Exception:
            logger.warning("probe misconception not recorded after saved grade")
    # spec §13 A127 (same order): a correct, unassisted probe answer on an
    # isomorph closes what its item tests; the response below is unchanged
    _resolve_misconceptions(checkpoint, diagnosis, committed, surface="probe", request=request)
    if out.get("done"):
        _emit_probe_done(saved, checkpoint.user_id, _request_id(request))
    response = {
        "graded": True, "correct": checkpoint.continuation["correct"], "p_known": p_after,
        "probe_done": bool(out.get("done")), "novice_floor": bool(out.get("novice_floor")),
        **_learning_scope_payload(saved),
    }
    if reference is not None:
        response["reference_answer"] = reference
    return response


@router.post("/probe/answer")
async def probe_answer(body: ProbeAnswerBody, request: Request) -> dict:
    """Behaviour 11: grade_answer only (A16) — no tutor turn, no tutor budget
    (A20); the rate limit is the one model-cost guard here (spec §9), checked
    inline AFTER the gate (PKG-12's pattern) so a gate-off student gets the
    404, never a 429."""
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    # crisis support: before the rate limit; the probe item stays posed, ungraded
    if crisis := await crisis_support.screen_async(
        body.user_id, "loop_probe_answer", body.answer, body.reason
    ):
        return crisis_support.json_body(crisis, graded=False)
    ai_budget.enforce_rate_limit_for(body.user_id)
    await _consume_pending_off_loop(body.session_id, body.user_id)
    return await _agent_turn_or_http_error(
        _probe_submission(body, request, loop_on=loop_on), what="probe grader"
    )


@dataclass(frozen=True)
class _PlanView:
    states: dict[str, float]
    planning_states: dict[str, float]
    scope: frozenset[str] | None
    targets: frozenset[str]
    ready: frozenset[str]
    proposal: planner.Plan
    signature: str | None
    practice_unavailable: frozenset[str]


def _planning_observations(state: dict, user_id: str, course_id: str, nodes) -> list[dict]:
    try:
        return read_planning_history(user_id, course_id, nodes)
    except PlanningPersistenceUnavailable as exc:
        raise HTTPException(status_code=503, detail="Learning evidence unavailable; retry") from exc


def _current_plan(state: dict, user_id: str, course_id: str) -> _PlanView:
    states = _plan_states(user_id, course_id)
    edges = _plan_prereq_edges(user_id, list(states))
    scope = _goal_scope_for(state, states, edges)
    targets = frozenset((state.get("goal") or {}).get("target_node_ids") or [])
    observations = (_planning_observations(state, user_id, course_id, states)
                    if scope is not None else planning_observations(state))
    planning_states = planner.planning_states(states, observations)
    parents: dict[str, set[str]] = {}
    for prereq, dependent in edges:
        if prereq != dependent:
            parents.setdefault(dependent, set()).add(prereq)

    def siblings(node_id: str) -> list[str]:
        mine = parents.get(node_id, set())
        return sorted(m for m, ps in parents.items() if m != node_id and ps & mine)

    ready = planner.prerequisite_ready(planning_states, edges, transitive=True) if scope is not None else frozenset(states)
    attempted = set(attempted_nodes(state)) if scope is not None else set()
    fringe = planner.outer_fringe(planning_states, edges)
    reviews = list(dict.fromkeys(_plan_due_reviews(user_id, list(states)) + [
        n for n in sorted(targets) if planning_states[n] >= BKT_PROFICIENT
    ]))
    proficient = frozenset(n for n, p in planning_states.items() if p >= BKT_PROFICIENT)
    candidates = (set(fringe) | set(reviews) | {s for n in fringe for s in siblings(n) if s in proficient}
                  if scope is not None else set())
    unavailable = (_goal_practice_unavailable(
        user_id, course_id, state, sorted(candidates & scope & ready - attempted),
    ) if scope is not None else set())
    previous = state.get("plan") if isinstance(state.get("plan"), dict) else {}
    # Activation may have lost its last item after approval. Preserve that
    # exhausted attempt; new assets never reset this session's finite frontier.
    unavailable |= set(previous.get("practice_unavailable_node_ids") or []) & attempted
    proposal = planner.plan(
        fringe,
        reviews,
        siblings,
        (lambda n: n in scope and n in ready and n not in attempted and n not in unavailable) if scope is not None else None,
        proficient=proficient,
    )
    return _PlanView(states, planning_states, scope, targets, ready, proposal,
                     scope_signature(targets, scope, edges) if scope is not None else None,
                     frozenset(unavailable))


def _continue_goal(session_id: str, user_id: str, course_id: str, state: dict) -> dict:
    """Offer another finite frontier only after an explicit 'Check me' request.

    Every exhausted concept is remembered, so an unresolved/bank-starved
    foundation cannot repeat indefinitely. A new frontier still needs approval.
    """
    previous = state.get("plan") if isinstance(state.get("plan"), dict) else {}
    if not state.get("goal") or not previous.get("done"):
        return state
    version = goal_version(state)
    view = _current_plan(state, user_id, course_id)
    progress = goal_progress(state, view.planning_states, view.scope,
                             continue_available=bool(view.proposal.concepts))
    attempted = attempted_nodes(state)

    def offer(doc: dict) -> None:
        _require_teaching(doc)
        _check_goal_version(doc, version)
        _refuse_while_closing(doc, _now_s())
        plan = doc.get("plan") or {}
        if not plan.get("done") or attempted_nodes(doc) != attempted or doc.get("current"):
            raise _StateConflict()
        plan["goal_progress"] = progress
        plan["practice_unavailable_node_ids"] = sorted(view.practice_unavailable)
        if view.proposal.concepts:
            for key in ("proposed", "proposed_kinds", "scope_signature"):
                plan.pop(key, None)
            doc["phase"] = "plan"
        doc["plan"] = plan

    return _update_loop_state(session_id, offer, require_open=True)


@router.get("/plan")
def plan_get(request: Request, user_id: str = Query(...), session_id: str = Query(...)) -> dict:
    """Current goal-scoped frontier; every new frontier requires explicit approval."""
    _gate(user_id, request)
    _probe_plan_read_limit(user_id)
    _, course_id = _session_scope(session_id, user_id)
    state = _load_loop_state(session_id)
    _require_phase(state, "plan")
    version = goal_version(state)
    view = _current_plan(state, user_id, course_id)
    proposal, targets = view.proposal, view.targets
    ids = [c.node_id for c in proposal.concepts]
    kinds = {c.node_id: c.kind for c in proposal.concepts}

    def store(doc: dict) -> None:
        _require_phase(doc, "plan")
        _check_goal_version(doc, version)
        _refuse_while_closing(doc, _now_s())
        plan_doc = doc.get("plan") if isinstance(doc.get("plan"), dict) else {}
        plan_doc["proposed"], plan_doc["proposed_kinds"] = list(ids), dict(kinds)
        plan_doc["goal_version"] = version
        if view.scope is not None:
            plan_doc["scope_signature"] = view.signature
            plan_doc["practice_unavailable_node_ids"] = sorted(view.practice_unavailable)
            plan_doc["goal_progress"] = goal_progress(doc, view.planning_states, view.scope,
                                                       continue_available=bool(ids))
        doc["plan"] = plan_doc
        if not ids:
            plan_doc["approved"], plan_doc["cursor"] = [], 0
            if view.scope is not None:
                plan_doc["done"] = True
            doc["phase"] = "teach"

    saved = _update_if_changed(session_id, state, store, require_open=bool(state.get("goal")))
    if not ids:
        return {"concepts": [], "order": list(PLAN_ORDER), "empty": True, "phase": "teach", **_learning_scope_payload(saved)}
    names = _plan_node_names(user_id, ids)
    return {
        "concepts": [
            {
                "node_id": n,
                "concept_name": names.get(n, ""),
                "kind": kinds[n],
                "p_known": view.states.get(n, BKT_L0),
                "reason": "goal" if n in targets else "prerequisite" if view.scope is not None and n in view.scope else "review" if kinds[n] == "review" else "related",
                "target_node_ids": sorted(targets),
            }
            for n in ids
        ],
        "order": list(PLAN_ORDER),
        **_learning_scope_payload(saved),
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
    snapshot = _load_loop_state(body.session_id)
    view = _current_plan(snapshot, body.user_id, course_id) if snapshot.get("goal") else None
    chosen = list(body.concept_ids)
    out: dict = {}
    # spec §13 A138: the first concept's segment starts here — its prequestion
    # is posed (or skipped) in the approval's own write; flag read once
    pq_on = _prequestion_on(body.user_id)

    def approve(doc: dict) -> None:
        _require_phase(doc, "plan")
        _refuse_while_closing(doc, _now_s())
        plan_doc = doc.get("plan") if isinstance(doc.get("plan"), dict) else {}
        version = goal_version(doc)
        if version and (body.goal_version != version or plan_doc.get("goal_version") != version):
            raise HTTPException(status_code=409, detail="Goal changed; review the current plan")
        if view is not None:
            if plan_doc.get("scope_signature") != view.signature:
                raise HTTPException(status_code=409, detail="Goal prerequisites changed; review the current plan")
            allowed = view.scope & view.ready - set(attempted_nodes(doc))
            if not set(chosen) <= allowed:
                raise HTTPException(status_code=409, detail="Goal prerequisites changed; review the current plan")
            if _goal_practice_unavailable(body.user_id, course_id, doc, chosen):
                raise HTTPException(status_code=409, detail="Fresh practice is unavailable; review the current plan")
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
        plan_doc.pop("goal_progress", None)
        doc["plan"] = plan_doc
        doc["concept"] = chosen[0]
        doc["teach_turns"] = 0
        doc["concept_checks"] = 0
        doc["phase"] = "teach"
        out["pose"] = _pose_prequestion(body.user_id, course_id, doc, now=_now_s()) if pq_on else _NO_POSE

    _update_loop_state(body.session_id, approve, require_open=bool(snapshot.get("goal")))
    prequestion = _posed_prequestion(body.user_id, body.session_id, _request_id(request), out["pose"])
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
    # spec §13 A138: present only when a prequestion was posed (never null)
    return {"phase": "teach", "concept_ids": chosen, **({"prequestion": prequestion} if prequestion else {})}


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
                    if item.kind == "check" and item.question_hash:  # A93: posed
                        _ledger(record_posed, user_id, item.question_hash, source="review", session_id=sid)
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


def _review_posed_at(loop_state: dict, item) -> datetime | None:
    """When today's review served this item (loop_state["open"][key].served_at)."""
    entry = (loop_state.get("open") or {}).get(review.sr_key(item)) or {}
    return _ts(entry.get("served_at")) if isinstance(entry, dict) else None


@router.post("/review/answer")
async def review_answer(body: ReviewAnswerBody, request: Request) -> dict:
    """Grade one answer to the item today's session served for its key: a check
    through PKG-05's grade_answer (inside review.grade_review — its ONE evidence
    write), a flashcard through PKG-11's FSRS path. The item, its node (A2) and
    its reference are re-loaded here. Grading is a claim (A52): a second submit of
    the same served item is a 409 and is never graded or written twice."""
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    # crisis support: the item stays due and ungraded (a flashcard carries no text);
    # `unavailable` is this route's "nothing was recorded, still answerable"
    if crisis := await crisis_support.screen_async(
        body.user_id, "loop_review_answer", body.answer, body.reason
    ):
        return crisis_support.json_body(crisis, correct=None, unavailable=True, refused=False)
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
            confidence=body.confidence,  # spec §13 A127 (a check's; a flashcard body has none)
            deps=deps,
            claim=claim,
            # A88/A93: an item with recorded help anywhere has no unassisted credit
            max_rung=(review_floor := (
                _reveal_floor(body.user_id, check, _review_posed_at(loop_state, item))
                if check is not None
                else 0
            )),
            # A93: re-read inside the claim, right before the one write
            refloor=(
                (lambda ev: _refloor([ev], body.user_id, check, _review_posed_at(loop_state, item), review_floor))
                if check is not None
                else None
            ),
        )
        if check is not None and not outcome.unavailable:
            _ledger(mark_graded, body.user_id, check.question_hash)
    except review.ReviewClaimRefused as exc:
        raise HTTPException(status_code=409, detail=_REVIEW_CLAIM_DETAIL[exc.reason]) from None
    except EvidenceItemRetired:
        # A123: staff retired the item while it was graded: nothing was written
        # (the grade is void) and the claim was released; the queue moves on
        raise HTTPException(status_code=409, detail=_WITHDRAWN_ITEM) from None
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
    """The frontend's cheap loop probe (`getLoopStatus`): `{active}` — the gate's
    answer, 200 either way (PKG-13 reopen). It is the one loop route that does not
    404 when the gate is off: its job IS to answer the gate, and a 404 made every
    legacy student's /learn and /study visit log an `error.4xx` event. Still
    require_self first (403). Builds nothing (PKG-07's GET /status needs a loop
    session id)."""
    return {"active": _gate_value(user_id, request)}
