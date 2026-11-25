"""POST /check/answer (JSON and stream): `_grade_submission`, the loop's one
chat-path evidence writer (invariant 26), and the feedback turn after it.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from datetime import datetime, timezone
from services.loop.errors import HTTPException
from starlette.requests import Request
from agents.tools.check import CHANNEL_FOR_FORMAT, CheckAnswer, grade_answer
from learning import arms, check_reason, gates, policy
from learning import grade_checkpoint
from learning.claim_deadline import within_grade_deadline
from learning.multi_concept import is_multi_concept
from learning.goals import goal_version
from learning.ladder import Rung
from learning.misconceptions import recheck_after_release
from learning.loop_state_store import seen_hashes
from services.loop.posed import _ts
from learning.params import CHECK_REFUSALS_AS_IDK
from models import ChatBody, LoopCheckAnswerBody
from services.tutor import _consume_pending_off_loop
from services.tutor import _agent_turn_or_http_error
from services.check_item_service import get_check_item

from services.loop.constants import _ALREADY_GRADED, _WITHDRAWN_ITEM
from services.loop.state import (
    _arm_for,
    _agate,
    _item_like,
    _load_loop_state,
    _now_s,
    _require_open,
    _session_scope,
    _steps,
    _update_loop_state,
)
from services.loop.learner import _band_for, _genuine, _node_for_item, _seconds_since
from services.loop.reveals import _refloor, _reveal_floor, _tag_planning_evidence
from services.loop.turn import _LoopTurn
from services.loop.runner import _json_turn, _sse
from services.loop.claims import (
    _claim_grading,
    _is_idk_phrase,
    _record_attempt,
    _render_submission,
    _Submission,
    _under_claim,
)
from services.loop.checkpoint import (
    CHECK_KIND,
    grading_deps,
    grading_failure_http,
    submitted_answer,
    _finish_check_checkpoint,
    _open_grade_checkpoint,
    _save_grade_checkpoint,
)

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


#: A refusal reason that is never escalated to idk (A97).
_DISOWNED = "disowned_answer"

#: The verdicts a graded check answer is given.
_VERDICT_IDK, _VERDICT_CORRECT, _VERDICT_NOT_YET = "idk", "correct", "not_yet"

_NO_SUCH_ITEM = "No such check item in this session"
_NO_GRAPH_NODE = "no graph node for this item"


def _require_gradable(state: dict, entry, qh: str) -> dict:
    """The step of this session's current check `qh`: 409 for an item already
    graded, being graded or superseded; 404 for one that is not current."""
    if isinstance(entry, dict) and (
        entry.get("graded_at") is not None or entry.get("grading_claim") or entry.get("grading_superseded")
    ):
        raise HTTPException(status_code=409, detail=_ALREADY_GRADED)
    if not isinstance(entry, dict) or state.get("current") != qh:
        raise HTTPException(status_code=404, detail=_NO_SUCH_ITEM)
    return entry


def _stash_reasoning(body: LoopCheckAnswerBody, item):
    """W2.3: the optional free/teachback reasoning, sealed on the step."""

    def stash(e: dict) -> None:
        check_reason.stash_on_step(
            e, body.session_id, format=item.format, reasoning=body.reasoning
        )

    return stash


def _count_refusal(disowned: bool):
    """A33: count a refusal on the step; below CHECK_REFUSALS_AS_IDK (or a
    disowned answer, A97) the claim goes with the count — nothing was graded."""

    def count(e: dict) -> None:
        if not disowned:
            e["refusals"] = int(e.get("refusals") or 0) + 1
        if disowned or e["refusals"] < CHECK_REFUSALS_AS_IDK:
            # nothing was graded: the claim goes with the count
            e.pop("grading_claim", None)
            e.pop("grading_claim_at", None)

    return count


def _note_attempt(genuine: bool, now: float):
    """Invariant 28: an unavailable grade records only a genuine failed attempt."""

    def note(e: dict) -> None:
        if genuine:
            _record_attempt(e, now, failed=True)

    return note


def _verdict(idk: bool, correct: bool) -> str:
    return _VERDICT_IDK if idk else (_VERDICT_CORRECT if correct else _VERDICT_NOT_YET)


def _graded_step(outcome, *, now, rung: int, node_id: str, p_before, verdict: str) -> dict:
    """What the graded step records (its continuation's `graded`)."""
    correct = bool(outcome.correct)
    evidence = outcome.evidence or {}
    return {
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


def _goal_observation(outcome, item, *, qh, node_id, rung, idk, recheck, previously_seen, refused) -> dict:
    """The goal's observation of this grade (only while a goal is set)."""
    correct = bool(outcome.correct)
    evidence = outcome.evidence or {}
    effective_rung = max(rung, int(evidence.get("max_rung") or 0))
    rechecked = bool(recheck or evidence.get("same_session_recheck"))
    return {
        "node_id": node_id, "question_hash": qh, "difficulty": item.difficulty,
        "channel": CHANNEL_FOR_FORMAT[item.format], "correct": correct, "idk": bool(idk),
        "max_rung": effective_rung, "same_session_recheck": rechecked,
        "previously_seen": previously_seen, "synthetic_idk": bool(refused),
        "independent": effective_rung == 0 and not rechecked and not refused
        and not previously_seen and not evidence.get("assisted", False),
    }


async def _release_unsaved_claim(session_id: str, qh: str, claim: str) -> None:
    """Give up a claim no checkpoint was saved under (never raises)."""
    try:
        await asyncio.to_thread(
            _update_loop_state,
            session_id,
            _under_claim(qh, claim, lambda e: None, release=True),
        )
    except Exception:
        logger.warning("grading claim could not be released")


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
    scope = await asyncio.to_thread(_session_scope, body.session_id, body.user_id)  # #117
    course_id = scope[1]
    # #117: every sync PostgREST read and write below hops off the event loop
    state = await asyncio.to_thread(_load_loop_state, body.session_id)
    _require_open(state)
    qh = body.question_hash
    entry = _steps(state).get(qh)
    if isinstance(entry, dict) and grade_checkpoint.KEY in entry:
        checkpoint = _open_grade_checkpoint(entry, body, course_id, kind=CHECK_KIND)
        return await asyncio.to_thread(
            _finish_check_checkpoint, checkpoint, scope, request, loop_on=loop_on
        )
    entry = _require_gradable(state, entry, qh)
    item = (
        await asyncio.to_thread(get_check_item, entry["check_item_id"])
        if entry.get("check_item_id") else None
    )
    if item is None:  # A23 withdrawal: nothing is graded
        raise HTTPException(status_code=409, detail=_WITHDRAWN_ITEM)
    text = body.answer or body.reason
    idk = body.idk or _is_idk_phrase(text)
    rendered = _render_submission(body, idk=idk)
    if not idk and gates.matches_non_attempt(text):
        return _Submission("hint_request", state, rendered, scope)  # never graded
    node_id = await asyncio.to_thread(_node_for_item, body.user_id, item)  # #117
    if node_id is None:  # evidence needs the student's node for this concept (A2)
        raise HTTPException(status_code=409, detail=_NO_GRAPH_NODE)
    band, p_before = await asyncio.to_thread(_band_for, body.user_id, node_id)
    now = _now_s()
    # hint-unlock bookkeeping only: the independent-time gate never blocks grading (A16)
    arm = await asyncio.to_thread(_arm_for, body.user_id, request)  # #117
    variant = arms.variant_for(body.user_id, node_id, arm)
    genuine = not idk and _genuine(
        text, _seconds_since(entry.get("first_shown_at"), now), band, variant
    )
    # PKG-10: the hook's attempt log + marker; its change rides
    # outcome.diagnosis into the grade's compare-and-set save below
    deps = grading_deps(body, course_id, request, kind=CHECK_KIND, loop_on=loop_on, state=state)
    # A88: a posed item a served turn revealed grades with no unassisted credit
    rung = max(
        int(entry.get("rung") or 0),
        await asyncio.to_thread(
            _reveal_floor, body.user_id, item, _ts(entry.get("first_shown_at"))
        ),
    )
    # PKG-10 (spec §13 A76): the next graded item on a concept after a release
    # is a re-check, never a full-weight unassisted first attempt
    recheck = await asyncio.to_thread(
        recheck_after_release,
        body.user_id,
        node_id,
        state,
        now=datetime.fromtimestamp(now, tz=timezone.utc),
        item=item,
    )
    claim = str(uuid.uuid4())
    await asyncio.to_thread(_claim_grading, body.session_id, qh, claim, now)
    # W2.3: optional free/teachback reasoning — sealed on the step under the
    # claim, never passed to CheckAnswer / grade_answer (not evidence).
    if check_reason.normalize(item.format, body.reasoning):
        await asyncio.to_thread(
            _update_loop_state,
            body.session_id,
            _under_claim(qh, claim, _stash_reasoning(body, item), release=False),
        )
    checkpointed = False
    # spec §13 A141: a multi-concept item's answer is a partial observation on
    # its apex (node_id above); the keyword is passed only for one
    combo = {"multi_concept": True} if is_multi_concept(item) else {}
    answer = submitted_answer(body, idk=idk)
    try:
        async with within_grade_deadline(_now_s() - now):
            outcome = await grade_answer(
                _item_like(item),
                answer,
                deps=deps,
                node_id=node_id,
                max_rung=rung,
                same_session_recheck=recheck,
                **combo,
            )
            refused = bool(outcome.refused)
            if refused:  # A33, read BEFORE `unavailable`: not an outage, never a genuine attempt
                # A97: a disowned answer is never escalated to idk — the student may
                # have been right; they are only asked to state their own answer
                state = await asyncio.to_thread(
                    _update_loop_state,
                    body.session_id,
                    _under_claim(qh, claim, _count_refusal(outcome.refused == _DISOWNED), release=False),
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
                    **combo,
                )
            if outcome.unavailable:  # invariant 28: nothing for either outcome; the item stays open
                state = await asyncio.to_thread(
                    _update_loop_state,
                    body.session_id,
                    _under_claim(qh, claim, _note_attempt(genuine, now), release=True),
                )
                return _Submission("unavailable", state, rendered, scope, refused=refused)
            # A93: the help floor re-read inside the claim, right before the write
            rung = await asyncio.to_thread(
                _refloor,
                deps.pending_evidence,
                body.user_id,
                item,
                _ts(entry.get("first_shown_at")),
                rung,
            )
            previously_seen = qh in await asyncio.to_thread(seen_hashes, body.user_id)
            _tag_planning_evidence(deps.pending_evidence, item, synthetic_idk=bool(refused),
                                   previously_seen=previously_seen, operation_id=claim, observed_at=now)
            verdict = _verdict(idk, bool(outcome.correct))
            graded = _graded_step(outcome, now=now, rung=rung, node_id=node_id, p_before=p_before, verdict=verdict)
            if state.get("goal"):
                graded["goal_observation"] = _goal_observation(
                    outcome, item, qh=qh, node_id=node_id, rung=rung, idk=idk, recheck=recheck,
                    previously_seen=previously_seen, refused=refused,
                )
            checkpoint = grade_checkpoint.GradeCheckpoint(
                kind=CHECK_KIND, operation_id=claim, user_id=body.user_id,
                session_id=body.session_id, course_id=course_id or None, question_hash=qh,
                goal_version=goal_version(state), evidence=copy.deepcopy(deps.pending_evidence),
                continuation={"graded": graded, "correct": bool(outcome.correct), "genuine": genuine,
                              "diagnosis": getattr(outcome, "diagnosis", None), "rendered": rendered,
                              "answer": answer.model_dump(mode="json"), "verdict": verdict, "refused": refused},
            )
        # Treat a lost checkpoint acknowledgment as potentially saved. Never release
        # its claim or call the grader again while that uncertainty exists.
        checkpointed = True
        await asyncio.to_thread(_save_grade_checkpoint, checkpoint)
        return await asyncio.to_thread(
            _finish_check_checkpoint,
            checkpoint,
            scope,
            request,
            loop_on=loop_on,
            deps=deps,
            difficulty=item.difficulty,
        )
    except BaseException as exc:
        if not checkpointed:
            await _release_unsaved_claim(body.session_id, qh, claim)
        mapped = grading_failure_http(exc)
        if mapped is not None:
            raise mapped from None
        raise


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
    turn.feedback_dwell_ms = sub.feedback_dwell_ms  # W2.5
    return turn


# crisis support: a crisis answer leaves the item posed and ungraded (no claim, no evidence)
async def check_answer(body: LoopCheckAnswerBody, request: Request):
    loop_on = await _agate(body.user_id, request)
    await _consume_pending_off_loop(body.session_id, body.user_id)
    sub = await _agent_turn_or_http_error(
        _grade_submission(body, request, loop_on=loop_on), what="loop grader"
    )
    return await _json_turn(
        lambda: _submission_turn(sub, body, request, loop_on=loop_on), "loop feedback agent"
    )


async def check_answer_stream(body: LoopCheckAnswerBody, request: Request):
    loop_on = await _agate(body.user_id, request)
    await _consume_pending_off_loop(body.session_id, body.user_id)
    sub = await _agent_turn_or_http_error(
        _grade_submission(body, request, loop_on=loop_on), what="loop grader"
    )
    # #117: building the feedback turn reads the session's state; off the loop
    return _sse(await asyncio.to_thread(_submission_turn, sub, body, request, loop_on=loop_on))
