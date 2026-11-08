"""Admin review queue for learning-loop check items (spec §13 A113; GitHub #695).

Check items are drafted by a model from classmates' uploads and keyed from
peer material; no instructor reviews them before they grade students. This is
where staff do: every stored item the item-flaw linter flagged
(`check_items.lint_flags`, learning/item_lint.py) or a student reported
(`check_item_reports`, counted by reason), unless an admin approved it after its
last report. An item whose retire was decided but did not finish (the delete
failed) is listed first, as `retire_pending`.

- `GET /queue` — the queue. Every entry by its plaintext columns; the first
  QUEUE_PAGE also carry the item's text (prompt, options with the correct one
  marked, final answer, reference), decrypted here, at the read boundary
  (check_item_service.items_by_ids → `_row_to_item`).
- `POST /{item_id}/approve` — reviewed, OK: clears the course item from the
  queue until a newer report (which also counts toward retirement afresh). A
  retired item cannot be approved (409).
- `POST /{item_id}/retire` — retires the course item (every row of the course
  with its question_hash) through check_item_service's A23 retire path; it is
  never drafted for the course again. Evidence already written stays.

Every endpoint calls `require_admin` first. Decisions run through
learning.item_reports, under the same per-item database lock as the students'
reports, and each emits an audit event.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from learning import item_reports
from learning.checks import CheckItem
from learning.params import ITEM_REPORT_RETIRE_MIN_REPORTERS
from services.auth_guard import get_session_user_id, require_admin
from services.check_item_service import (
    flagged_item_rows,
    get_check_item,
    item_rows_for,
    items_by_ids,
    retire_course_item,
)
from services.events_service import log_event

logger = logging.getLogger("sapling.routes.admin_check_items")
router = APIRouter()

#: Entries one GET returns with their decrypted text (the rest by count only).
QUEUE_PAGE = 100
_APPROVED_EVENT = "learn.check_item_approved"
_RETIRED_EVENT = "learn.check_item_retired"


def _item_text(item: CheckItem | None) -> dict:
    """What staff judge an item by — only for an admin, only here."""
    if item is None:  # not readable (or gone since the queue was read)
        return {"prompt": None, "options": None, "final_answer": None, "reference_answer": None}
    options = [
        {"letter": o.letter, "text": o.text, "correct": o.letter == item.correct_option}
        for o in item.options or []
    ]
    return {
        "prompt": item.prompt,
        "options": options or None,
        "final_answer": item.final_answer,
        "reference_answer": item.reference_answer,
    }


@router.get("/queue")
def review_queue(request: Request) -> dict:
    """The review queue: flagged or reported items still needing a decision,
    retire-pending first, then the most reported, then the most flagged."""
    require_admin(request)
    counts = item_reports.report_counts()
    decisions = item_reports.reviews()
    rows = {r["id"]: r for r in flagged_item_rows() if r.get("id")}
    wanted = set(counts) | {k for k, d in decisions.items() if d.get("status") == item_reports.RETIRED}
    for row in item_rows_for(wanted):
        if row.get("id"):
            rows.setdefault(row["id"], row)
    entries = item_reports.queue_entries(rows.values(), counts, decisions)
    page = entries[:QUEUE_PAGE]
    texts = {i.id: i for i in items_by_ids(e["id"] for e in page)}
    return {
        "items": [{**e, **_item_text(texts.get(e["id"]))} for e in page],
        "count": len(entries),
        "page_size": QUEUE_PAGE,
        "retire_min_reporters": ITEM_REPORT_RETIRE_MIN_REPORTERS,
    }


def _stored(item_id: str) -> CheckItem:
    item = get_check_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Check item not found")
    return item


def _decide(item: CheckItem, status: str, admin: str) -> item_reports.Decision:
    try:
        return item_reports.decide(item.course_id, item.question_hash, status, reviewed_by=admin)
    except Exception:
        logger.warning("check item review not recorded (item %s)", item.id, exc_info=True)
        raise HTTPException(status_code=503, detail="Decision not recorded; try again.") from None


@router.post("/{item_id}/approve")
def approve(item_id: str, request: Request) -> dict:
    """Reviewed, OK: the course item leaves the queue until a newer report."""
    require_admin(request)
    admin = get_session_user_id(request)
    item = _stored(item_id)
    decision = _decide(item, item_reports.APPROVED, admin)
    if not decision.applied:
        raise HTTPException(status_code=409, detail="This question was retired; it cannot be approved.")
    log_event(
        _APPROVED_EVENT,
        category="audit",
        user_id=admin,
        payload={"course_id": item.course_id, "question_hash": item.question_hash},
    )
    return {"id": item_id, "status": item_reports.APPROVED}


@router.post("/{item_id}/retire")
def retire(item_id: str, request: Request) -> dict:
    """Retire the course item now. The decision is recorded first, so a failed
    delete (503) is finished by retiring again; the queue lists it as
    retire-pending meanwhile."""
    require_admin(request)
    admin = get_session_user_id(request)
    item = _stored(item_id)
    _decide(item, item_reports.RETIRED, admin)
    try:
        removed = retire_course_item(item.course_id, item.question_hash)
    except Exception:
        logger.error("check item retire FAILED (item %s)", item.id, exc_info=True)
        raise HTTPException(
            status_code=503, detail="Retired, but the question was not removed yet; retire it again."
        ) from None
    log_event(
        _RETIRED_EVENT,
        category="audit",
        user_id=admin,
        payload={
            "course_id": item.course_id,
            "question_hash": item.question_hash,
            "decided_by": item_reports.DECIDED_BY_ADMIN,
            "reporters": None,
            "items": removed,
        },
    )
    return {"id": item_id, "status": item_reports.RETIRED, "items": removed}
