"""POST /rating and POST /report (A113, A123): the turn rating and a student's
report of a check item.
"""
from __future__ import annotations

import logging
from datetime import datetime
from services.loop.errors import HTTPException
from starlette.requests import Request
from learning import review, zpd_events
from learning import grade_checkpoint, item_reports
from learning.checks import CheckItem
from learning.loop_state_store import LoopStateConflict
from learning.params import LOOP_GRADING_CLAIM_STALE_S, ZPD_RATING_EVERY_N_CHECKS
from models import LoopRatingBody, LoopReportBody
from services import events_service
from services.auth_guard import get_session_user_id
from services.check_item_service import get_check_item
from services.feature_flags import flag_on

from services.loop.constants import _WITHDRAWN_ITEM
from services.loop.state import (
    _gate,
    _load_loop_state,
    _now_s,
    _request_id,
    _require_open,
    _session_scope,
    _StateConflict,
    _steps,
    _update_loop_state,
)
from services.loop.reviews import (
    _REVIEW_CLAIM_DETAIL,
    _review_course,
    _REVIEW_EXPIRED,
    _review_now,
)

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


_NO_RATING_ASKED = "no rating was asked for"


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
