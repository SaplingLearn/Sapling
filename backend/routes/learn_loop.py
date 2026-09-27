"""/api/learn/loop/* — the learning-loop tutor routes (PKG-07; spec §7, §9; A15–A20, A27).

Mounted at /api/learn/loop. Every endpoint is require_self + gate-404; every
model-calling endpoint also carries the A20 rate-limit dependency. The legacy
learn routes delegate here (routes/learn.py) when the gate is true; they are
byte-identical when it is false.

Routing is code: learning.policy.model_tier picks the tier slot after
services.ai_budget.check has read the student's budget — in the same function
as every model run (invariant 23). Context comes from
learning.policy.context_policy, assembled with the legacy block builders.
Streaming rides services.chat_stream.stream_agent_turn unchanged; the loop
stream events are yielded AROUND it. Evidence is written ONLY by
_grade_submission, from an explicit answer submission (invariant 26). The
reference answer of the active check item lives only on the turn object —
never in deps, the prefix, a log line, or an event payload.

Loop state: PKG-06's `learning.loop_state_store` returns the typed `LoopState`;
this module works on its JSON document (`LoopState.to_json()`) and saves through
`LoopState.from_json`, so every write is validated by PKG-06's parser. The
spec's `loop_state["active"]` is the document's `current`, and the spec's
per-item `loop_state[qh]` entry is `steps[qh]`: PKG-06 owns its `rung`,
`attempts` (failed genuine attempts while the step is open), `first_shown_at`,
`last_rung_at`, `attempted_at` (Unix seconds), `showed_work` and `exam_mode`;
every other per-item key is this package's (HANDOFF-07 Deviations). The
session is checked to be the requesting student's before any read or write.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic_ai.exceptions import UnexpectedModelBehavior
from sse_starlette.sse import EventSourceResponse

import config
from agents import CONTINUATION_LIMITS, LOOP_LIMITS
from agents.deps import SaplingDeps
from agents.loop_tutor import (
    LOOP_TIER_SLOTS,
    loop_tutor_agent,
    phase_prefix,
    routable_tier,
    tier_run_kwargs,
)
from agents.tools.check import CheckAnswer, grade_answer
from agents.usage import record_agent_usage
from db.connection import table
from learning import gates, ladder, policy, zpd_events
from learning.bkt import band as bkt_band
from learning.checks import CheckItem, posttest_reserve_hash
from learning.evidence import flush_pending
from learning.gate import learning_loop_active
from learning.ladder import Rung
from learning.leak import detect_leak, strip_leak
from learning.learner_state import LearnerState, read_states
from learning.loop_state_store import load_loop_state, save_loop_state
from learning.params import (
    BAND_DEVELOP_MAX,
    BKT_L0,
    EDGE_PREREQ_SOURCE_IS_PREREQ,
    LOOP_HISTORY_MAX_MESSAGES,
    LOOP_SESSION_MAX_DEEP_REQUESTS,
    LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE,
    LOOP_SOURCE_CHUNKS_MAX,
)
from learning.policy import LearnerView, LoopState, StepState
from models import (
    ActionBody,
    ChatBody,
    EndSessionBody,
    LoopAttemptBody,
    LoopCheckAnswerBody,
    LoopHintBody,
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
    _new_run_text,
    save_message,
)
from services import ai_budget, events_service
from services.academics import offering_course_id, resolve_offering
from services.agent_events import SSE_CACHE_CONTROL, SaplingEvent, sapling_event_to_sse
from services.ai_budget import AIBudgetExceeded, enforce_rate_limit
from services.auth_guard import require_self
from services.chat_stream import stream_agent_turn
from services.check_item_service import get_check_item, list_items
from services.graph_context import build_graph_context_block
from services.graph_service import _normalize_concept, _prerequisite_edges, get_graph
from services.prompt_safety import wrap_untrusted
from services.rag_service import chunks_for_ids, format_rag_context, retrieve_chunks
from services.request_context import current_request_id

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

#: The idk subset of gates.NON_ATTEMPT_PATTERNS (A16: idk → idk evidence and
#: the answer is released; any other non-attempt phrase → a hint request).
IDK_PHRASES: tuple[str, ...] = ("idk", "i don't know")

_GRADE_UNAVAILABLE_REPLY = (
    "I couldn't check that answer just now, so nothing was recorded. "
    "Please submit it again in a moment."
)
_IDK_RENDERED = "I don't know"
_SUBMISSION_KINDS = ("feedback", "hint_request", "unavailable")
_DETERMINISTIC_RUNGS = (Rung.H2, Rung.H4, Rung.H6)

#: The three "[ACTION: ...]" texts, copied verbatim from routes/learn.py::_action_turn
#: (:1406–1411), where they are a local dict.
_ACTION_PROMPTS = {
    "hint": "The student asked for a hint. Give a small scaffold or clue without giving away the answer.",
    "confused": "The student said they are confused. Identify the likely point of confusion and re-explain with a different analogy.",
    "skip": "The student wants to skip this concept. Acknowledge and transition to the next recommended concept.",
}


def _gate(user_id: str, request: Request) -> None:
    require_self(user_id, request)
    if not learning_loop_active(user_id):
        raise HTTPException(status_code=404, detail=_NOT_ENABLED)


def _now_s() -> float:
    return datetime.now(timezone.utc).timestamp()


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or current_request_id() or str(uuid.uuid4())


def _session_scope(session_id: str, user_id: str) -> tuple[str, str]:
    """(offering_id, abstract course_id) of a materialised session the requesting
    student owns. The loop-state store keys on the session id alone, so this
    ownership check is the route's (HANDOFF-06 Known gaps): 404 when no row
    exists, 403 when it is another student's. One `sessions` read."""
    rows = table("sessions").select(
        "user_id,offering_id", filters={"id": f"eq.{session_id}"}, limit=1
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
    reset = decision.reset_at
    return {"level": decision.level, "reset_at": reset.isoformat() if reset else None}


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


def _load_loop_state(session_id: str) -> dict:
    """The session's loop state as PKG-06's JSON document (`LoopState.to_json()`)."""
    return load_loop_state(session_id).to_json()


def _save_loop_state(session_id: str, state: dict) -> bool:
    """Save through PKG-06's typed parser: a malformed PKG-06 field this route
    wrote raises ValueError here instead of reaching the database."""
    return save_loop_state(session_id, LoopState.from_json(state))


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


def _turn_phase(kind: str, state_phase: str) -> str:
    """The phase a turn of `kind` runs in, given the document's phase."""
    if kind == "feedback":
        return "feedback"
    if kind == "hint_request" or (kind == "action" and state_phase == "check"):
        return "hint"
    if kind == "unavailable":
        return "check"
    if kind == "opener":
        return "teach"
    return state_phase


def _load_loop_history(session_id: str) -> list:
    """The bounded loop history (spec §3.4 LOOP_HISTORY_MAX_MESSAGES; PKG-09
    prepends the brief and block-trims here, A19)."""
    return _load_message_history(session_id)[-LOOP_HISTORY_MAX_MESSAGES:]


# ── Learner state, band, ceiling ───────────────────────────────────────────


def _node_for_item(user_id: str, item) -> str | None:
    """The student's graph node for a course-asset item (A2): the user's
    `graph_nodes` row in the item's course whose normalised concept name is the
    item's `concept_key`. None when the student has never met the concept."""
    rows = table("graph_nodes").select(
        "id,concept_name",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{item.course_id}"},
    ) or []
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
    return all(
        (states[p].p_known if p in states else BKT_L0) >= BAND_DEVELOP_MAX for p in parents
    )


def _learner_view(
    state: LearnerState | None, *, band: str, prereq_proficient: bool
) -> LearnerView:
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
) -> tuple:
    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id or None,
        supabase=None,
        request_id=request_id,
        session_id=session_id,
        feature="loop_tutor",
        learning_loop=True,
        loop_state=state,
    )
    blocks = _context_blocks(
        user_id=user_id, course_id=course_id, user_message=user_message, context=context, item=item
    )
    body = (
        "\n\n".join(blocks) + "\n\n[STUDENT QUESTION]\n" + user_message if blocks else user_message
    )
    assembled = prefix + "\n\n" + body
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


async def _loop_continuation_text(turn, run_result) -> str | None:
    """The #646 twin of routes.learn._continuation_text for a loop turn: a
    budget check FIRST (invariant 23; None at the hard level), then the same
    tool-less continuation on the SAME slot. A twin, not a shared helper, so
    routes/learn.py stays delegation-only; the `override(tools=[], toolsets=[])`
    line is the safety property (pinned)."""
    decision = ai_budget.check(turn.user_id, "tutor", turn.band, **turn.budget_counters())
    if decision.level == "hard":
        return None
    carried = {k: turn.run_kwargs[k] for k in _CONTINUATION_RUN_KEYS if k in turn.run_kwargs}
    with turn.agent.override(tools=[], toolsets=[]):
        result = record_agent_usage(
            await turn.agent.run(
                _CONTINUATION_NUDGE,
                message_history=run_result.all_messages(),
                usage_limits=CONTINUATION_LIMITS,
                **carried,
            ),
            feature="loop_tutor_continuation",
            task=turn.slot,
            user_id=turn.user_id,
        )
    return _new_run_text(result).strip() or None


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
    ):
        self.user_id, self.session_id = body.user_id, body.session_id
        self.mode = body.mode
        self.message, self.kind, self.persist_user_row = message, kind, persist_user_row
        self.request_id = _request_id(request)
        self.offering_id, self.course_id = scope or _session_scope(body.session_id, body.user_id)
        self.state = state if state is not None else _load_loop_state(body.session_id)
        self._derive(verdict)

    def _derive(self, verdict: str | None) -> None:
        """Everything the turn knows before the budget is read."""
        active = self.state.get("current")
        entry = (self.state.get("steps") or {}).get(active) if active else None
        self.item = None
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
        self.verdict = verdict or (self.entry.get("last_verdict") if self.phase == "feedback" else None)
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
        return _load_loop_history(self.session_id)

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
        self.prefix = phase_prefix(
            phase=self.phase,
            band=self.band,
            ceiling=self.rung if self.phase == "hint" else self.ceiling,
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
            message_history=self.history(),
            request_id=self.request_id,
            prefix=self.prefix,
            state=self.state,
            tier=self.tier,
            context=context,
            item=self.item,
        )

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
        if self.phase == "check" and self.item is not None:
            return ladder.check_pose(self.item.prompt)
        if self.phase == "hint" and self.item is not None and self.rung in _DETERMINISTIC_RUNGS:
            payload, leaked = _leak_checked_payload(
                user_id=self.user_id, item=self.item, rung=self.rung, reference=self.item.reference_answer
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
                type="phase", step="loop", message=f"Phase: {self.phase}.", data={"phase": self.phase}
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

    def _leak_checked(self, reply: str) -> tuple[str, bool]:
        """Model-written text is leak-checked against the ACTIVE item at the rung
        it is served at: H6 once the answer is released, the hint rung on a hint
        turn, else the ceiling (A34: the item's structured final answer)."""
        if self.tier == "none" or self.item is None:
            return reply, False
        leak_rung = Rung.H6 if self.answer_released else (self.rung if self.phase == "hint" else self.ceiling)
        verdict = detect_leak(
            self.item.reference_answer,
            reply,
            leak_rung,
            final_answer=self.item.final_answer,
            canonical_answer=self.item.canonical_answer,
        )
        if not verdict.leaked:
            return reply, False
        zpd_events.emit_zpd_leak(
            user_id=self.user_id,
            request_id=self.request_id,
            rung_emitted=leak_rung,
            ceiling=self.ceiling,
            detector=verdict.detector,
        )
        stripped = strip_leak(
            reply,
            self.item.reference_answer,
            final_answer=self.item.final_answer,
            canonical_answer=self.item.canonical_answer,
        )
        return stripped, True

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
                {"rung": int(r["rung"]), "dwell_ms": _ms(ats[i + 1] - ats[i])} for i, r in enumerate(log)
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
                time_to_correct_ms=_ms(graded - shown) if (shown and entry.get("last_correct")) else None,
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
        """Called exactly once per served turn: leak check, feedback bookkeeping,
        counters, persistence. Applies this turn's changes to a FRESH load of
        the document (HANDOFF-06: never save a state loaded before a long stream
        without re-loading)."""
        reply, redacted = self._leak_checked(reply)
        state = _load_loop_state(self.session_id)
        steps = _steps(state)
        offer_rung = None
        if self.phase == "feedback" and self.active in steps:
            entry = steps[self.active]
            self._emit_step(entry)
            if gates.offer_allowed(self.band, self.verdict != "correct"):
                entry["offered"] = True
                offer_rung = min(int(self.ceiling), int(entry.get("rung") or 0) + 1)
            entry["feedback_given"] = True
            if state.get("current") == self.active:
                state["current"] = None
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
        if self.persist_user_row:
            save_message(self.session_id, "user", self.message)
        save_message(self.session_id, "assistant", reply, merged or None)
        if self.persist_user_row:
            events_service.log_event(
                "chat.message_sent",
                category="usage",
                user_id=self.user_id,
                request_id=self.request_id,
                payload={"mode": self.mode, "session_id": self.session_id},
                content=self.message,
            )
        _save_loop_state(self.session_id, state)
        extra = self._submission_extra()
        return {
            **extra,
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
        }


    def _submission_extra(self) -> dict:
        """The check-answer response keys (A16) — only on a submission's turn."""
        if self.kind not in _SUBMISSION_KINDS:
            return {}
        return {
            "graded": self.kind == "feedback",
            "verdict": self.verdict,
            "unavailable": self.kind == "unavailable",
            "answer_released": self.answer_released,
        }


class _LoopOpener(_LoopTurn):
    """The session opener (spec Behaviour 15): a fresh session, `teach` with no
    item and the BKT_L0 band, the catalog context (the opener only), and the
    legacy lazy-session contract — `complete` stashes PENDING_SESSIONS and
    persists and counts nothing (no sessions row exists yet)."""

    def __init__(self, *, body: StartSessionBody, request: Request, session_id: str | None = None):
        self.start = body
        self.user_id, self.session_id = body.user_id, session_id or str(uuid.uuid4())
        self.mode = body.mode
        self.kind, self.persist_user_row = "opener", False
        self.request_id = _request_id(request)
        self.course_id = body.course_id or _get_course_id_for_topic(body.topic, body.user_id)
        self.offering_id = resolve_offering(self.course_id, create=True) if self.course_id else ""
        # routes/learn.py::_start_session_agent (:540–543), verbatim
        self.message = (
            f"Student wants to learn about: {body.topic}\n\n"
            "Begin the session with a warm greeting and your first question or explanation."
        )
        self.state = {}
        self._derive(None)

    def history(self) -> list:
        return []

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
        reference or "",
        payload.text,
        rung,
        final_answer=item.final_answer,
        canonical_answer=item.canonical_answer,
    )
    return payload, verdict.leaked


def _ms(seconds: float) -> int:
    """Whole milliseconds, never negative (zpd.step's *_ms keys)."""
    return max(0, round(timedelta(seconds=seconds) / timedelta(milliseconds=1)))


# ── Run sites ──────────────────────────────────────────────────────────────


async def _run_turn_json(turn: _LoopTurn) -> dict:
    """The JSON run site (chat, action, check-answer turns, opener) and the
    stream's Rung-1 fallback: budget → plan → deterministic text or ONE model
    run → complete. Persist ordering mirrors routes.learn._chat_turn_json."""
    decision = ai_budget.check(turn.user_id, "tutor", turn.band, **turn.budget_counters())
    turn.plan(decision)
    if turn.paused:
        raise _BudgetPaused(decision)
    if turn.tier == "none":
        extra = turn.complete(turn.text, {}, [])
    else:
        result = await turn.agent.run(turn.assembled, **turn.run_kwargs)
        turn.record_usage(result)
        new_text = _new_run_text(result)
        reply = result.output if new_text.strip() else new_text
        if not reply.strip():
            try:
                rescued = await _loop_continuation_text(turn, result)
            except Exception:
                logger.warning("Continuation after a textless loop turn failed", exc_info=True)
                rescued = None
            if not rescued:
                raise UnexpectedModelBehavior("loop_tutor produced no reply text this turn")
            reply = rescued
        extra = turn.complete(reply, {}, [])
    return {"graph_update": {}, "mastery_changes": [], **extra}


def _pre_done_events(data: dict) -> list[SaplingEvent]:
    evs = [
        SaplingEvent(type="learner_state", step="loop", message="Learner state.", data=ls)
        for ls in (data.get("learner_state") or [])
    ]
    if data.get("hint_offer"):
        evs.append(
            SaplingEvent(type="hint_offer", step="loop", message="Hint available.", data=data["hint_offer"])
        )
    return evs


async def _stream_turn(turn: _LoopTurn):
    """The SSE run site (chat, check-answer turns, opener). Loop events are
    yielded AROUND stream_agent_turn, never from inside it."""
    decision = ai_budget.check(turn.user_id, "tutor", turn.band, **turn.budget_counters())
    turn.plan(decision)
    for ev in turn.pre_events():
        yield sapling_event_to_sse(ev)
    if turn.paused:
        yield sapling_event_to_sse(_budget_event(decision))
        return
    if decision.level == "hard":
        yield sapling_event_to_sse(_budget_event(decision))  # a deterministic turn at the hard level
    if turn.tier == "none":
        extra = turn.complete(turn.text, {}, [])
        data = {"graph_update": {}, "mastery_changes": [], **extra}
        for ev in _pre_done_events(data):
            yield sapling_event_to_sse(ev)
        yield sapling_event_to_sse(SaplingEvent(type="done", step="reply", message="Complete.", data=data))
        return
    async for ev in stream_agent_turn(
        agent=turn.agent,
        user_message=turn.assembled,
        run_kwargs=turn.run_kwargs,
        deps=turn.deps,
        on_complete=turn.complete,
        nonstream_fallback=lambda: _run_turn_json(turn),
        on_usage=turn.record_usage,
        request_id=turn.request_id,
        continuation=lambda rr: _loop_continuation_text(turn, rr),
    ):
        if ev.type == "done":
            for extra_ev in _pre_done_events(ev.data or {}):
                yield sapling_event_to_sse(extra_ev)
        yield sapling_event_to_sse(ev)


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
    item = get_check_item(entry["check_item_id"]) if isinstance(entry, dict) and entry.get("check_item_id") else None
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
    _gate(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)
    return await _json_turn(
        lambda: _LoopTurn(body=body, request=request, message=body.message), "loop chat agent"
    )


@router.post("/chat/stream", dependencies=_RATE_LIMITED)
async def chat_stream(body: ChatBody, request: Request):
    _gate(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)
    return _sse(_LoopTurn(body=body, request=request, message=body.message))


# ── The explicit-submission route (A16) ───────────────────────────────────


@dataclass
class _Submission:
    kind: str  # "feedback" | "hint_request" | "unavailable"
    state: dict
    rendered: str  # the user row persisted for this submission
    scope: tuple[str, str]
    verdict: str | None = None


def _is_idk_phrase(text: str) -> bool:
    """A16's idk split, as HANDOFF-06 defines it: the submission routes to idk
    when gates.non_attempt_phrases (the A16 routing rule, which fails toward
    grading) returns an IDK_PHRASES phrase — so a hedged answer ("idk maybe
    7") is graded, never turned into idk evidence."""
    return any(p in IDK_PHRASES for p in gates.non_attempt_phrases(text or ""))


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


async def _grade_submission(body: LoopCheckAnswerBody, request: Request) -> _Submission:
    """The ONLY loop-chat evidence path (spec A16; invariant 26's allow-list):
    grade ONE explicit submission and persist its evidence with ONE
    flush_pending, before any feedback turn or stream starts."""
    scope = _session_scope(body.session_id, body.user_id)
    course_id = scope[1]
    state = _load_loop_state(body.session_id)
    entry = _steps(state).get(body.question_hash)
    if not isinstance(entry, dict) or state.get("current") != body.question_hash:
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
        learning_loop=True,
    )
    rung = int(entry.get("rung") or 0)
    outcome = await grade_answer(
        _item_like(item),
        CheckAnswer(
            question_hash=body.question_hash,
            answer_text=body.answer,
            selected_option=body.option,
            reason=body.reason,
            idk=idk,
        ),
        deps=deps,
        node_id=node_id,
        max_rung=rung,
    )
    if outcome.unavailable:  # invariant 28: nothing for either outcome; the item stays open
        if genuine:
            _record_attempt(entry, now, failed=True)
        _save_loop_state(body.session_id, state)
        return _Submission("unavailable", state, rendered, scope)
    flush_pending(deps, course_id or None)  # ONE call: the loop's only evidence write
    correct = bool(outcome.correct)
    verdict = "idk" if idk else ("correct" if correct else "not_yet")
    if genuine:
        _record_attempt(entry, now, failed=not correct)
    evidence = outcome.evidence or {}
    if entry.get("graded_at") is None:
        entry["first_attempt_correct"] = correct
    entry.update(
        {
            "graded": int(entry.get("graded") or 0) + 1,
            "wrong": int(entry.get("wrong") or 0) + (0 if correct else 1),
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
    )
    _save_loop_state(body.session_id, state)  # a failed feedback turn is recovered by _phase_for
    return _Submission("feedback", state, rendered, scope, verdict)


def _submission_turn(sub: _Submission, body: LoopCheckAnswerBody, request: Request) -> _LoopTurn:
    chat_body = ChatBody(session_id=body.session_id, user_id=body.user_id, message=sub.rendered)
    return _LoopTurn(
        body=chat_body,
        request=request,
        message=sub.rendered,
        kind=sub.kind,
        state=sub.state,
        verdict=sub.verdict,
        scope=sub.scope,
    )


@router.post("/check/answer", dependencies=_RATE_LIMITED)
async def check_answer(body: LoopCheckAnswerBody, request: Request):
    _gate(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)
    sub = await _agent_turn_or_http_error(_grade_submission(body, request), what="loop grader")
    return await _json_turn(lambda: _submission_turn(sub, body, request), "loop feedback agent")


@router.post("/check/answer/stream", dependencies=_RATE_LIMITED)
async def check_answer_stream(body: LoopCheckAnswerBody, request: Request):
    _gate(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)
    sub = await _agent_turn_or_http_error(_grade_submission(body, request), what="loop grader")
    return _sse(_submission_turn(sub, body, request))


# ── Attempt / hint / action / openers / end-session ───────────────────────


@router.post("/step/attempt")
def step_attempt(body: LoopAttemptBody, request: Request) -> dict:
    """Records a genuine attempt for hint unlocking only (spec §3.3). The text
    is judged by gates.is_genuine_attempt and never stored, never graded."""
    _gate(body.user_id, request)
    _session_scope(body.session_id, body.user_id)
    state = _load_loop_state(body.session_id)
    entry = _steps(state).get(body.question_hash)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail="No such check item in this session")
    check = get_check_item(entry["check_item_id"]) if entry.get("check_item_id") else None
    band, _ = _band_for(body.user_id, _node_for_item(body.user_id, check) if check else None)
    now = _now_s()
    independent_s = _seconds_since(entry.get("first_shown_at"), now)
    genuine = bool(_genuine(body.attempt_text, independent_s, band))
    if genuine:
        _record_attempt(entry, now, failed=True)  # the step stays open: a failed genuine attempt
        _save_loop_state(body.session_id, state)
    return {
        "genuine": genuine,
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
    entry = _steps(state).get(body.question_hash)
    if not isinstance(entry, dict) or state.get("current") != body.question_hash:
        return {"denied": "no_active_item"}
    step = _step_state(state, body.question_hash)
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
    if next_rung == int(Rung.H6) and not _h6_ok(state, body.question_hash, entry, check):
        return {"denied": "h6_gate"}
    entry["rung"], entry["last_rung_at"] = next_rung, now
    entry["rungs"] = [*(entry.get("rungs") or []), {"rung": next_rung, "at": now}]
    if entry.get("offered"):
        entry["offered"] = False
        zpd_events.emit_zpd_offer(
            user_id=body.user_id, request_id=_request_id(request), accepted=True, band=band
        )
    _save_loop_state(body.session_id, state)
    return {"rung": next_rung, "intent": ladder.intent(Rung(next_rung))}


@router.post("/action", dependencies=_RATE_LIMITED)
async def action(body: ActionBody, request: Request):
    """An "[ACTION: ...]" turn: in the check phase a hint at the item's current
    rung, otherwise the current phase. Assistant-only persistence; never graded
    (invariant 26)."""
    _gate(body.user_id, request)
    _consume_pending(body.session_id, body.user_id)
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
            body=chat_body, request=request, message=message, kind="action", persist_user_row=False
        ),
        "loop action agent",
    )


@router.post("/start-session", dependencies=_RATE_LIMITED)
async def start_session(body: StartSessionBody, request: Request):
    _gate(body.user_id, request)
    result = await _json_turn(
        lambda: _LoopOpener(body=body, request=request), "loop start-session agent"
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
    _gate(body.user_id, request)
    return _sse(_LoopOpener(body=body, request=request))


def end_session(body: EndSessionBody, request: Request) -> dict | None:
    """PKG-07 pass-through: the legacy end_session body runs unchanged.
    PKG-09 returns the close payload (summary + brief) from here."""
    return None
