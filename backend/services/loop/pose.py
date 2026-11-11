"""The segment prequestion's pose (A138), the self-explanation prompts (A139)
and the teach-prompt juncture they open.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import NamedTuple
from learning import prequestion as prequestion_rules
from learning import self_explain
from learning.loop_state_store import reported_hashes, revealed_hashes, seen_hashes
from learning.help_ledger import mark_graded, record_posed
from services.tutor import save_message_sync as save_message
from services import events_service
from services.check_item_service import get_check_item, list_items

from services.loop.flags import (
    _ANSWER_CLAIM,
    OPEN_QUESTION_KEY,
    _prequestion_on,
    PREQUESTION_SOURCE,
    _self_explain_on,
)
from services.loop.learner import _band_for, _concept_key_for_node
from services.loop.reveals import _ledger, _persist_reveals

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


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


def _spend_prequestion_item(user_id: str, session_id: str, question_hash: str | None, *, at: float) -> None:
    """Spec §13 A138 (review fix): a posed prequestion's item is SPENT however
    its card closes — answered (its answer is about to be shown) or superseded
    (a turn was served, or a check opened, while its question was in front of
    the student, and that turn's text cannot be trusted not to have worked it).
    A durable reveal (A88: never served to this student again, and any grade of
    it carries no credit), then its ledger 'posed' row closes: the reveal floors
    every later grade, so the scan has nothing left to protect. Only then
    (second review): when both reveal stores failed, the row stays open, so
    A88's scan still covers the item — a superseded card has no stored answer
    to stand in for the reveal. Never raises."""
    if not question_hash:
        return
    if _persist_reveals(
        user_id, session_id, [question_hash], unscanned=False, source=PREQUESTION_SOURCE,
        at=datetime.fromtimestamp(at, tz=timezone.utc),
    ):
        _ledger(mark_graded, user_id, question_hash)


def _superseded_prequestion(user_id: str, session_id: str, request_id: str, node: str, rec: dict, *, at: float) -> None:
    """After the write that superseded a posed card: the item spent, the event."""
    _spend_prequestion_item(user_id, session_id, rec.get("question_hash"), at=at)
    _emit_prequestion(user_id, request_id, session_id, node, "superseded", question_hash=rec.get("question_hash"))


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
    # A88/A93: the card's item is a posed item — the served-text scan covers it
    # while the card is open, like a check's (review fix: it was outside it)
    _ledger(record_posed, user_id, pose.item.question_hash, source=PREQUESTION_SOURCE, session_id=session_id)
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


def _without_claim(rec: dict) -> dict:
    """A card's record without its answer claim's keys."""
    return {k: v for k, v in rec.items() if k not in (_ANSWER_CLAIM, f"{_ANSWER_CLAIM}_at")}
