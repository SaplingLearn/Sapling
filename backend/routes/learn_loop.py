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
import logging
import re
import uuid
from datetime import datetime, timezone
from collections import Counter
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from agents.deps import SaplingDeps
from agents._run import run_agent_sync
from agents.session_close import run_session_close, shape_close
from agents.tools.check import CHANNEL_FOR_FORMAT, CheckAnswer, GradeOutcome, grade_answer
from db.connection import pg_quote_value, table
from learning import planner
from learning import grade_checkpoint
from learning import probe as probe_policy
from learning.checks import is_servable, posttest_reserves, pretest_form
from learning.evidence import PlanningPersistenceUnavailable
from learning.void_store import voided_by_node, voided_event_ids
from learning.gate import learning_loop_active
from learning.goals import encode_goal, goal_version, attempted_nodes, progress as goal_progress
from learning.ladder import Rung
from learning.leak import detect_leak
from learning.learner_brief import store_brief
from learning.misconceptions import carry, is_key, open_for, recheck_after_release
from learning.loop_state_store import reported_hashes, revealed_hashes, seen_hashes
from learning.help_ledger import record_posed
from learning.params import (
    BKT_L0,
    CHECK_REFUSALS_AS_IDK,
    CLOSE_RUN_TIMEOUT_S,
    PLAN_ORDER,
    PROBE_MAX_SKILLS,
    PROBE_SESSION_CAP,
)
from learning.session_close import (
    CLOSE_FALLBACK_DETAILS,
    CloseRecord,
    build_close,
    fallback_close,
    session_probe_hashes,
    store_close,
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
from services.tutor.pending import _consume_pending, _consume_pending_off_loop
from services.tutor.turns import _agent_turn_or_http_error
from services.tutor_sessions import PENDING_SESSIONS, claim_pending, get_pending
from services import ai_budget, crisis_support, events_service
from services.ai_budget import AIBudgetExceeded, enforce_rate_limit
from services.auth_guard import get_session_user_id, guard_off_loop
from services.encryption import decrypt_if_present, decrypt_json_column
from services.check_item_service import get_check_item
from services.feature_flags import flag_on
from services.request_context import current_request_id
from services.session_modes import NOT_REVIEW
import services.loop as loop_service
from routes._docs import same_doc
from services.loop.constants import _ALREADY_GRADED, _NOT_ENABLED
from services.loop.flags import _prequestion_on
from services.loop.state import (
    _CLOSE_IN_PROGRESS,
    _close_phase,
    _CLOSE_STORE_FAILED,
    _gate,
    _GRADING_IN_FLIGHT,
    _grading_in_flight,
    _item_like,
    _live,
    _load_loop_state,
    _loop_phase,
    _now_s,
    _pending_grade,
    _refuse_while_closing,
    _request_id,
    _session_scope,
    _update_loop_state,
)
from services.loop.served import _item_check_kwargs
from services.loop.reveals import _ledger, _refloor, _reveal_floor, _tag_planning_evidence
from services.loop.guard import option_text
from services.loop.planning import (
    _check_goal_version,
    _claim_live,
    _current_plan,
    _emit_probe_done,
    _goal_practice_unavailable,
    _goal_scope_for,
    _learning_scope_payload,
    _plan_node_names,
    _plan_prereq_edges,
    _plan_states,
    _preparing,
    _probe_course_has_items,
    _probe_doc,
    _probe_history,
    _probe_items,
    PROBE_MATCHED_PRETEST_FLAG,
    _PROBE_NOT_POSED,
    _probe_plan_read_limit,
    _require_phase,
    _unanchored_skills,
    _update_if_changed,
    _validate_goal,
)
from services.loop.pose import _NO_POSE, _pose_prequestion, _posed_prequestion
from services.loop.practice import _pose_payload
from services.loop.claims import (
    _is_idk_phrase,
    _not_asked,
    _resolve_misconceptions,
    _under_probe_claim,
    _write_misconception,
)
from services.loop.checkpoint import (
    _committed_grade_observation,
    _flush_grade_checkpoint,
    _ITEM_RETIRED,
    _open_grade_checkpoint,
    _save_grade_checkpoint,
)

logger = logging.getLogger(__name__)
router = APIRouter()


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


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/status")
@same_doc(loop_service.status)
def status(request: Request, user_id: str = Query(...), session_id: str = Query(...)) -> dict:
    return loop_service.status(request, user_id, session_id)


@router.get("/sessions")
@same_doc(loop_service.list_open_sessions)
def list_open_sessions(
    request: Request,
    user_id: str = Query(...),
    course_id: str = Query(...),
    resume: str | None = Query(None),
) -> dict:
    return loop_service.list_open_sessions(request, user_id, course_id, resume)


@router.post("/chat", dependencies=_screened("loop_chat", "message", respond=crisis_support.turn_response))
@same_doc(loop_service.chat)
async def chat(body: ChatBody, request: Request):
    return await loop_service.chat(body, request)


@router.post("/chat/stream", dependencies=_screened("loop_chat", "message", respond=crisis_support.turn_stream))
@same_doc(loop_service.chat_stream)
async def chat_stream(body: ChatBody, request: Request):
    return await loop_service.chat_stream(body, request)


# crisis support: a crisis answer leaves the item posed and ungraded (no claim, no evidence)
@router.post(
    "/check/answer",
    dependencies=_screened("loop_check_answer", "answer", "reason", respond=crisis_support.turn_response),
)
@same_doc(loop_service.check_answer)
async def check_answer(body: LoopCheckAnswerBody, request: Request):
    return await loop_service.check_answer(body, request)


@router.post(
    "/check/answer/stream",
    dependencies=_screened("loop_check_answer", "answer", "reason", respond=crisis_support.turn_stream),
)
@same_doc(loop_service.check_answer_stream)
async def check_answer_stream(body: LoopCheckAnswerBody, request: Request):
    return await loop_service.check_answer_stream(body, request)


@router.post("/rating", dependencies=_RATE_LIMITED)
@same_doc(loop_service.rating)
def rating(body: LoopRatingBody, request: Request) -> dict:
    return loop_service.rating(body, request)


@router.post("/report", dependencies=_RATE_LIMITED)
@same_doc(loop_service.report_item)
def report_item(body: LoopReportBody, request: Request) -> dict:
    return loop_service.report_item(body, request)


@router.post("/posttest/start", dependencies=_RATE_LIMITED)
@same_doc(loop_service.posttest_start)
def posttest_start(body: PosttestStartBody, request: Request) -> dict:
    return loop_service.posttest_start(body, request)


# crisis support: a crisis answer leaves the pose open and unclaimed, nothing graded
@router.post(
    "/posttest/answer",
    dependencies=_screened(
        "loop_posttest_answer", "answer", "reason", respond=crisis_support.plain_response(graded=False)
    ),
)
@same_doc(loop_service.posttest_answer)
async def posttest_answer(body: PosttestAnswerBody, request: Request):
    return await loop_service.posttest_answer(body, request)


@router.post("/posttest/shown")
@same_doc(loop_service.posttest_shown)
def posttest_shown(body: PosttestShownBody, request: Request) -> dict:
    return loop_service.posttest_shown(body, request)


@router.get("/posttest/due")
@same_doc(loop_service.posttest_due)
def posttest_due(request: Request, user_id: str = Query("")) -> dict:
    return loop_service.posttest_due(request, user_id)


# crisis support: a crisis attempt stops the hint flow — nothing counts toward a hint
@router.post(
    "/step/attempt",
    dependencies=_screened(
        "loop_step_attempt",
        "attempt_text",
        respond=crisis_support.plain_response(genuine=False, counted=False),
    ),
)
@same_doc(loop_service.step_attempt)
def step_attempt(body: LoopAttemptBody, request: Request) -> dict:
    return loop_service.step_attempt(body, request)


@router.post("/hint")
@same_doc(loop_service.hint)
def hint(body: LoopHintBody, request: Request) -> dict:
    return loop_service.hint(body, request)


@router.post("/action", dependencies=_RATE_LIMITED)
@same_doc(loop_service.action)
async def action(body: ActionBody, request: Request):
    return await loop_service.action(body, request)


# crisis support: a crisis topic or goal opens no session (nothing is stashed or
# written). The legacy /api/learn routes that delegate here screen first themselves.
@router.post(
    "/start-session",
    dependencies=_screened("loop_start", "topic", "goal.text", respond=crisis_support.start_response),
)
@same_doc(loop_service.start_session)
async def start_session(body: StartSessionBody, request: Request):
    return await loop_service.start_session(body, request)


@router.post(
    "/start-session/stream",
    dependencies=_screened("loop_start", "topic", "goal.text", respond=crisis_support.start_stream),
)
@same_doc(loop_service.start_session_stream)
async def start_session_stream(body: StartSessionBody, request: Request):
    return await loop_service.start_session_stream(body, request)


@router.post("/check/next")
@same_doc(loop_service.check_next)
def check_next(body: LoopCheckNextBody, request: Request) -> dict:
    return loop_service.check_next(body, request)


@router.post(
    "/prequestion/answer",
    dependencies=_screened("loop_prequestion_answer", "answer", "reason", respond=crisis_support.turn_response),
)
@same_doc(loop_service.prequestion_answer)
async def prequestion_answer(body: PrequestionAnswerBody, request: Request):
    return await loop_service.prequestion_answer(body, request)


@router.post(
    "/prequestion/answer/stream",
    dependencies=_screened("loop_prequestion_answer", "answer", "reason", respond=crisis_support.turn_stream),
)
@same_doc(loop_service.prequestion_answer_stream)
async def prequestion_answer_stream(body: PrequestionAnswerBody, request: Request):
    return await loop_service.prequestion_answer_stream(body, request)


# ── The self-explanation reply (spec §13 A139) ─────────────────────────────


@router.post(
    "/self-explain",
    dependencies=_screened("loop_self_explain", "reply", respond=crisis_support.plain_response(recorded=False)),
)
@same_doc(loop_service.self_explain_reply)
def self_explain_reply(body: SelfExplainBody, request: Request) -> dict:
    return loop_service.self_explain_reply(body, request)


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
    pending = await asyncio.to_thread(claim_pending, session_id, user_id)  # 404 if foreign
    claim = ""
    if pending is not None:
        phase = "close"
        record = fallback_close(build_close([], [], [], measured_before=()))
        row_defaults = {
            "mode": pending.get("mode"),
            "topic": pending.get("topic"),
            "offering_id": pending.get("offering_id"),
        }
    else:
        rows = await asyncio.to_thread(  # #117: off the event loop
            table("sessions").select,
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
            return await asyncio.to_thread(_reread_close, session_id)
        phase = _close_phase(doc) if had_state else "close"
        row_defaults = None
        try:
            transcript, evidence = await asyncio.to_thread(_session_record, session_id)  # #117
            keys = _close_misconception_keys(user_id, evidence)
            # A117: honest baselines, and check-in answers counted apart
            # (the probe history is the claimed document's)
            measured = await asyncio.to_thread(_measured_before, user_id, session_id, evidence)
            names = await asyncio.to_thread(
                _concept_names, user_id, [e.get("node_id") for e in evidence]
            )
            draft = build_close(
                transcript,
                evidence,
                keys,
                measured_before=measured,
                probe_hashes=session_probe_hashes(doc),
                concept_names=names,
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
        return await asyncio.to_thread(_reread_close, session_id)
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
    pending = get_pending(body.session_id)
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


def _release(_pr: dict, cur: dict) -> None:
    cur.pop("grading_claim", None)
    cur.pop("grading_claim_at", None)
    cur.pop(grade_checkpoint.KEY, None)


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
    _, course_id = await asyncio.to_thread(_session_scope, body.session_id, body.user_id)  # #117
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
    probe_items = await asyncio.to_thread(_probe_items, body.user_id, course_id, skills)  # #117
    item = next(
        (
            it
            for it in probe_items
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


@router.get("/review/next")
@same_doc(loop_service.review_next)
def review_next(
    request: Request, user_id: str = Query(...), course_id: str | None = Query(None)
) -> dict:
    return loop_service.review_next(request, user_id, course_id)


@router.post("/review/answer")
@same_doc(loop_service.review_answer)
async def review_answer(body: ReviewAnswerBody, request: Request) -> dict:
    return await loop_service.review_answer(body, request)


@router.get("/review/summary")
@same_doc(loop_service.review_summary)
def review_summary(
    request: Request, user_id: str = Query(...), course_id: str | None = Query(None)
) -> dict:
    return loop_service.review_summary(request, user_id, course_id)


@router.get("/review/active")
@same_doc(loop_service.review_active)
def review_active(request: Request, user_id: str = Query(...)) -> dict:
    return loop_service.review_active(request, user_id)
