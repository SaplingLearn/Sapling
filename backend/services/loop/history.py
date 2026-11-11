"""The tutor's message history for a loop turn: the learner brief request
(A19), the history window and the brief's node ids.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pydantic_ai.messages import ModelRequest, UserPromptPart
from db.connection import table
from learning.learner_brief import course_concept_names, store_brief
from learning.params import (
    LEARNER_BRIEF_CANDIDATE_NODES,
    LEARNER_BRIEF_RETRY_AFTER_S,
    LEARNER_BRIEF_TOP_STATES,
    LOOP_HISTORY_TRIM_BLOCK,
)
from services.tutor import _load_message_history_sync as _load_message_history
from services.encryption import decrypt_if_present
from services.session_modes import NOT_REVIEW

from services.loop.state import _now_s

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


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
