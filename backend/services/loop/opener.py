"""`_LoopOpener`: the session opener (A27, A121) and the quiz-ask state it
carries.
"""
from __future__ import annotations

import logging
import threading
import uuid
from services.loop.errors import HTTPException
from starlette.requests import Request
from learning.goals import encode_goal
from learning.turn_shape import LOOP_PLAN_OPENER, LOOP_PROBE_OPENER, LOOP_QUIZ_ASK_OPENER
from models import StartSessionBody
from services.tutor import _get_course_id_for_topic_sync as _get_course_id_for_topic
from services.tutor_sessions import stash_pending
from services.academics import require_course_enrollment, resolve_offering
from services.graph_service import get_graph
from services.quiz_ask import QUIZ_ASK_ORIGIN, open_quiz_ask

from services.loop.constants import _LOOP_OPENER_TEMPLATE
from services.loop.flags import OPEN_QUESTION_KEY
from services.loop.state import _arm_for, _budget_data, _loop_phase, _now_s, _request_id
from services.loop.context import _materials_notice, _note_retrieval_failure
from services.loop.planning import (
    _plan_states,
    _probe_course_has_items,
    _validate_goal,
    _with_goal_context,
)
from services.loop.turn import _LoopTurn

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


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
    legacy lazy-session contract — `complete` stashes the pending session
    (`stash_pending`: process memory, or the table with
    `stateless_tutor_sessions` on, #117) and
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
        # #115: a course the session names — the client's, or a quiz-ask's node
        # course (main's legacy opener names that one on the body too) — passes
        # the enrollment gate first (404 unless the student is enrolled), and
        # the session keys on the offering the gate returns; a topic-derived
        # course keeps the current-term resolution (routes/learn.py::
        # _session_offering).
        if self.course_id and (self.quiz_ask is not None or body.course_id):
            self.offering_id = require_course_enrollment(self.user_id, self.course_id)
        else:
            self.offering_id = (
                resolve_offering(self.course_id, create=True) if self.course_id else ""
            )
        if body.goal is not None:
            _validate_goal(body.goal, _plan_states(self.user_id, self.course_id or ""))
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
        payload = {
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
            payload["loop_state"] = dict(self.state)
        stash_pending(self.session_id, payload)  # #117: the table, flag on
        return {
            "reply": reply,
            "session_id": self.session_id,
            "graph_state": get_graph(self.user_id),
            "tier": self.tier,
            "phase": self.phase,
            "budget": _budget_data(self.planned) if self.planned.level == "hard" else None,
            **_materials_notice(notice),
        }
