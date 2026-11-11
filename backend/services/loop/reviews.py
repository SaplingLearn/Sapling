"""The /review/* handlers (PKG-12): the next due item, its answer, the summary
and the active check.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from services.loop.errors import HTTPException
from starlette.requests import Request
from agents.deps import SaplingDeps
from learning import review
from learning.evidence_transaction import EvidenceItemRetired
from learning.loop_state_store import LoopStateConflict
from services.loop.posed import _ts
from learning.help_ledger import mark_graded, record_posed
from models import ReviewAnswerBody
from services import ai_budget, crisis_support
from services.academics import user_offering_ids_for_course
from services.auth_guard import guard_off_loop
from services.check_item_service import get_check_item
from services import varied_practice

from services.loop.constants import _ALREADY_GRADED, _WITHDRAWN_ITEM
from services.loop.state import _gate, _gate_value, _item_like, _request_id, _StateConflict
from services.loop.learner import _node_for_item
from services.loop.reveals import _ledger, _refloor, _reveal_floor


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


def review_next(
    request: Request, user_id: str, course_id: str | None = None
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
        # spec §13 A140: passed only when on, so a flag-off build is the plain one
        **({"varied": True} if varied_practice.varied_on(user_id) else {}),
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
    # #117: every sync PostgREST read and write below hops off the event loop
    if body.kind == "check":  # the one review body that runs a model (the grader)
        await asyncio.to_thread(ai_budget.enforce_rate_limit_for, body.user_id)
    await asyncio.to_thread(_review_course, body.user_id, body.course_id)
    now = _review_now()
    if body.session_id != review.review_session_id(body.user_id, body.course_id, now):
        raise HTTPException(status_code=409, detail=_REVIEW_EXPIRED)  # a new UTC day began
    sid, loop_state = await asyncio.to_thread(_review_session, body.user_id, body.course_id, now)
    check = card_row = deps = None
    if body.kind == "check":
        check = await asyncio.to_thread(get_check_item, body.item_id)
        node_id = (  # #117: off the event loop
            await asyncio.to_thread(_node_for_item, body.user_id, check)
            if check is not None else None
        )
        if node_id is None:
            raise HTTPException(status_code=404, detail=_REVIEW_NOT_FOUND)
        if check.format == "mc_reason" and not body.selected_option:
            raise HTTPException(status_code=422, detail="an mc_reason answer needs selected_option")
        if check.format != "mc_reason" and not body.answer:
            raise HTTPException(status_code=422, detail="a free answer needs answer")
        deps = _review_deps(body.user_id, body.course_id, sid, _request_id(request), loop_on)
    else:
        card_row = await asyncio.to_thread(review.load_card, body.user_id, body.item_id)
        if card_row is None:
            raise HTTPException(status_code=404, detail=_REVIEW_NOT_FOUND)
    try:  # a stored fsrs_s that is not a finite positive number → 422 (InvalidStability)
        item = (
            await asyncio.to_thread(review.item_for_check, body.user_id, check, node_id, now)
            if check is not None
            else review.item_for_card(card_row, body.course_id, now)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    retention = loop_state["review"].get("retention") or await asyncio.to_thread(
        review.review_retention, body.user_id, body.course_id
    )
    claim = str(uuid.uuid4())
    try:
        await asyncio.to_thread(review.claim_item, sid, review.sr_key(item), item.id, claim, now)
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
            # spec §13 A140: the interleave's anchor records the graded difficulty
            **({"varied": True} if await asyncio.to_thread(varied_practice.varied_on, body.user_id) else {}),
            # A88/A93: an item with recorded help anywhere has no unassisted credit
            max_rung=(review_floor := (
                await asyncio.to_thread(
                    _reveal_floor, body.user_id, check, _review_posed_at(loop_state, item)
                )
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
            await asyncio.to_thread(_ledger, mark_graded, body.user_id, check.question_hash)
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


def review_summary(
    request: Request, user_id: str, course_id: str | None = None
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


def review_active(request: Request, user_id: str) -> dict:
    """The frontend's cheap loop probe (`getLoopStatus`): `{active}` — the gate's
    answer, 200 either way (PKG-13 reopen). It is the one loop route that does not
    404 when the gate is off: its job IS to answer the gate, and a 404 made every
    legacy student's /learn and /study visit log an `error.4xx` event. Still
    require_self first (403). Builds nothing (PKG-07's GET /status needs a loop
    session id)."""
    return {"active": _gate_value(user_id, request)}
