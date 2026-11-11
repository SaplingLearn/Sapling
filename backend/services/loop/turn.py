"""`_LoopTurn`: one loop turn, shared by the JSON and streamed run sites
(phase, band and ceiling before the budget read; plan; complete).
"""
from __future__ import annotations

import copy
import logging
import threading
import uuid
from datetime import datetime, timezone
from services.loop.errors import HTTPException
from starlette.requests import Request
import config
from agents.loop_tutor import (
    LOOP_TIER_SLOTS,
    item_visible,
    new_nonce,
    phase_prefix,
    plan_focus_block,
    prequestion_answer_block,
    prequestion_item_block,
    routable_tier,
)
from agents.usage import record_agent_usage, served_model_name
from learning import arms, gates, ladder, policy, turn_activity, zpd_events
from learning import prequestion as prequestion_rules
from learning import self_explain
from learning.self_explain_store import record_prompt as record_self_explain_prompt
from learning.bkt import band as bkt_band
from learning.ladder import Rung
from learning.leak import confront_text_states_answer, detect_leak, leak_spans
from learning.served_scan import ScanSet
from learning.misconceptions import confront_of, set_confront
from learning.reveal_store import record_reveals, record_unscanned
from services.loop.posed import posed_items
from learning.help_ledger import record_help, record_posed
from learning.params import (
    MISCONCEPTION_CONFRONT_MIN_RUNG,
    LOOP_SESSION_MAX_DEEP_REQUESTS,
    LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE,
    LOOP_SOURCE_CHUNKS_MAX,
    LOOP_TEACH_TURNS_BEFORE_CHECK,
    RUNG_NO_CREDIT_MIN,
)
from learning.turn_shape import FIELD_JOIN, clamp_model_ceiling, turn_limits
from models import ChatBody
from services.tutor import save_message_sync as save_message
from services.tutor import _observe_persisted_turn
from services.tutor_sessions import get_pending
from services import events_service
from services.agent_events import SaplingEvent
from services.check_item_service import get_check_item
from services import varied_practice

from services.loop.constants import (
    _ANSWER_REFUSED_REPLY,
    _DETERMINISTIC_RUNGS,
    _GRADE_UNAVAILABLE_REPLY,
    _SUBMISSION_KINDS,
    _WITHDRAWN_FEEDBACK,
)
from services.loop.flags import (
    _ANSWER_CLAIM,
    OPEN_QUESTION_KEY,
    _prequestion_on,
    _self_explain_on,
    _tutor_v2_on,
)
from services.loop.state import (
    _arm_for,
    _budget_data,
    _live,
    _load_loop_state,
    _ms,
    _now_s,
    _pending_grade,
    _phase_for,
    _refuse_while_closing,
    _request_id,
    _SESSION_CLOSED,
    _session_scope,
    _StateConflict,
    _step_state,
    _steps,
    _turn_phase,
    _update_loop_state,
)
from services.loop.history import _load_loop_history
from services.loop.learner import (
    _band_ceiling_delta,
    _band_of,
    _ceiling_for,
    _failed_on_concept,
    _learner_state,
    _learner_view,
    _node_for_item,
    _prereq_proficient,
    _seconds_since,
)
from services.loop.context import (
    _materials_notice,
    _note_retrieval_failure,
    _prepare_loop_run,
    _RETRIEVAL_FAILED_VALUE,
    _RETRIEVAL_KEY,
)
from services.loop.continuation import _requests_of, _template_feedback
from services.loop.served import (
    _item_check_kwargs,
    loop_leak_rung,
    served_lead,
    served_model_text,
    served_partial,
    served_render,
)
from services.loop.reveals import _ledger, _mark_revealed, _persist_reveals
from services.loop.guard import (
    confront_line_for,
    CONFRONT_TIERS,
    _confrontation_text,
    _cut_before_leak,
    _guard_history,
    _LeakGuard,
    option_text,
    _visible_text,
    with_confrontation,
)
from services.loop.planning import _plan_node_names, _with_goal_context
from services.loop.cursor import _auto_poses_checks, _h6_ok, _leak_checked_payload
from services.loop.pose import (
    _emit_prequestion,
    _emit_self_explanation,
    _NO_POSE,
    _pose_prequestion,
    _posed_prequestion,
    _self_explain_payload,
    _superseded_prequestion,
    _undo_pose,
    _without_claim,
)
from services.loop.practice import (
    _activate_next_item,
    _count_feedback_and_move,
    plan_focus,
    _pose_payload,
    _worked_example_owed,
)

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


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
        # — never a turn that explains a prequestion (review fix): that turn is
        # about the next concept's guess, so the acknowledgement is dropped
        # (this turn consumes it; the card already said "Saved")
        explains = self.pq_record is not None or self.kind == "prequestion"
        self.se_ack = self_explain.ack_due(self.state) if self.se_on and not explains else None

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
        failed = turn_activity.failed_at(self.state)  # durable: any worker sees it
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
                varied_practice.note_posed(self.user_id, self.session_id, item)  # A141
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
                _superseded_prequestion(self.user_id, self.session_id, self.request_id, node, rec, at=self._now)
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
            # a guess being saved under its claim is no open card: it commits
            if rec is not None and not _live(rec, _ANSWER_CLAIM, self._now):
                records = dict(prequestion_rules.records(state))
                records[self.concept_node] = {**_without_claim(rec), "status": prequestion_rules.SUPERSEDED}
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
        operation_id = getattr(self, "activity_id", None)
        if operation_id is not None:  # None: the lazy opener (no row, no credit)
            try:
                _update_loop_state(
                    self.session_id,
                    lambda doc: turn_activity.fail(doc, operation_id, now),
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
                        None if get_pending(self.session_id) is not None else self.session_id,
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
