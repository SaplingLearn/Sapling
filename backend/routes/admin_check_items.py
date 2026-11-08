"""Admin review queue for learning-loop check items (spec §13 A113; GitHub #695),
and the key audit (spec §13 A124).

Check items are drafted by a model from classmates' uploads and keyed from
peer material; no instructor reviews them before they grade students. This is
where staff do: every stored item the item-flaw linter flagged
(`check_items.lint_flags`, learning/item_lint.py) or a student reported
(`check_item_reports`, counted by reason), unless an admin approved it after its
last report — and every item a key hold withdraws (A124: the blind solve
disputed its key or found the passages do not settle it, or an audit found it
wrong or ambiguous), whatever an older approval said. An item whose retire was
decided but did not finish (the delete failed) is listed first, as
`retire_pending`; held items next.

- `GET /queue` — the queue. Every entry by its plaintext columns; the first
  QUEUE_PAGE also carry the item's text (prompt, options with the correct one
  marked, final answer, reference, and a numeric item's canonical value and
  tolerance — what the A22 numeric gate grades with once the key is
  confirmed), decrypted here, at the read boundary
  (check_item_service.items_by_ids → `_row_to_item`).
- `POST /{item_id}/approve` — reviewed, OK: clears the course item from the
  queue until a newer report (which also counts toward retirement afresh), and
  confirms its key (A124: `canonical_verified`, the A22 instructor
  confirmation — a held item is served again). A retired item cannot be
  approved (409).
- `POST /{item_id}/retire` — retires the course item (every row of the course
  with its question_hash) through check_item_service's A23 retire path; it is
  never drafted for the course again. Evidence already written stays.
- `GET /audit/sample?course_id=…&n=…&seed=…` — A124: a stratified sample of
  the course's stored keys for staff to judge (learning/item_audit.py), with
  their text and any verdict already recorded, and the course's audit summary.
- `POST /{item_id}/audit` — A124: staff's verdict on the item's key (correct /
  wrong / ambiguous), recorded in check_item_audits; "correct" confirms the
  key, "wrong" / "ambiguous" holds it (check_item_service.record_item_audit).
- `GET /audit/summary?course_id=…` — A124: the course's key-error rate with a
  Wilson 95% interval, overall and by the key's status when audited.

Every endpoint calls `require_admin` first. Queue decisions run through
learning.item_reports, under the same per-item database lock as the students'
reports, and each emits an audit event.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from learning import item_reports
from learning.checks import CheckItem
from learning.item_audit import stratified_sample, summary
from learning.params import (
    ITEM_AUDIT_SAMPLE_DEFAULT,
    ITEM_AUDIT_SAMPLE_MAX,
    ITEM_REPORT_RETIRE_MIN_REPORTERS,
)
from services.auth_guard import get_session_user_id, require_admin
from services.check_item_service import (
    audit_population,
    confirm_course_item,
    course_audit_rows,
    flagged_item_rows,
    get_check_item,
    item_rows_for,
    items_by_ids,
    key_status,
    record_item_audit,
    retire_course_item,
)
from services.events_service import log_event

logger = logging.getLogger("sapling.routes.admin_check_items")
router = APIRouter()

#: Entries one GET returns with their decrypted text (the rest by count only).
QUEUE_PAGE = 100
_APPROVED_EVENT = "learn.check_item_approved"
_RETIRED_EVENT = "learn.check_item_retired"
_NUMERIC = "numeric"


def _item_text(item: CheckItem | None) -> dict:
    """What staff judge an item by — only for an admin, only here."""
    if item is None:  # not readable (or gone since the queue was read)
        return {
            "prompt": None,
            "options": None,
            "final_answer": None,
            "reference_answer": None,
            "canonical_answer": None,
            "tolerance": None,
        }
    options = [
        {"letter": o.letter, "text": o.text, "correct": o.letter == item.correct_option}
        for o in item.options or []
    ]
    numeric = item.answer_kind == _NUMERIC
    return {
        "prompt": item.prompt,
        "options": options or None,
        "final_answer": item.final_answer,
        "reference_answer": item.reference_answer,
        # A124: what the A22 numeric gate grades with once the key is confirmed
        "canonical_answer": item.canonical_answer if numeric else None,
        "tolerance": item.tolerance if numeric else None,
    }


@router.get("/queue")
def review_queue(request: Request) -> dict:
    """The review queue: flagged, reported or held items still needing a
    decision, retire-pending first, then held, then the most reported, then
    the most flagged."""
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
    """The stored item, held or not (A124: staff decide on held items)."""
    item = get_check_item(item_id, include_held=True)
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
    """Reviewed, OK: the course item leaves the queue until a newer report,
    and its key is confirmed (A124) — a held item is served again. The
    decision is recorded first; a failed confirmation (503) is finished by
    approving again, and the queue lists a still-held item meanwhile."""
    require_admin(request)
    admin = get_session_user_id(request)
    item = _stored(item_id)
    decision = _decide(item, item_reports.APPROVED, admin)
    if not decision.applied:
        raise HTTPException(status_code=409, detail="This question was retired; it cannot be approved.")
    try:
        confirm_course_item(item.course_id, item.question_hash)
    except Exception:
        logger.warning("check item key not confirmed (item %s)", item.id, exc_info=True)
        raise HTTPException(
            status_code=503, detail="Approved, but its key was not confirmed yet; approve it again."
        ) from None
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


# ── the key audit (A124) ─────────────────────────────────────────────────────


class AuditBody(BaseModel):
    """Staff's verdict on an item's key. An enum only: no free text is ever
    accepted or stored."""

    model_config = ConfigDict(extra="forbid")
    verdict: Literal["correct", "wrong", "ambiguous"]


def _audit_reads(course_id: str) -> tuple[list[dict], list[dict]]:
    try:
        return audit_population(course_id), course_audit_rows(course_id)
    except Exception:
        logger.warning("check item audit read failed (course %s)", course_id, exc_info=True)
        raise HTTPException(status_code=503, detail="Audit unavailable; try again.") from None


@router.get("/audit/sample")
def audit_sample(
    request: Request,
    course_id: str,
    n: int = ITEM_AUDIT_SAMPLE_DEFAULT,
    seed: str | None = None,
) -> dict:
    """A stratified sample of the course's stored keys (format × difficulty ×
    concept; learning/item_audit.py), each with its text, its key status and
    the verdict already recorded for it, plus the course's audit summary. The
    seed defaults to the course id, so the same course draws the same sample
    while its items stay as they are."""
    require_admin(request)
    if not 1 <= n <= ITEM_AUDIT_SAMPLE_MAX:
        raise HTTPException(status_code=422, detail=f"n must be 1..{ITEM_AUDIT_SAMPLE_MAX}")
    seed = seed or course_id
    population, audits = _audit_reads(course_id)
    sample = stratified_sample(population, n, seed=seed)
    verdicts = {a.get("question_hash"): a for a in audits}
    texts = {i.id: i for i in items_by_ids(r["id"] for r in sample)}
    items = []
    for row in sample:
        audit = verdicts.get(row.get("question_hash")) or {}
        items.append(
            {
                "id": row["id"],
                "course_id": row.get("course_id"),
                "concept_key": row.get("concept_key"),
                "question_hash": row.get("question_hash"),
                "format": row.get("format"),
                "difficulty": row.get("difficulty"),
                "key_status": key_status(row),
                "verdict": audit.get("verdict"),
                "audited_at": audit.get("audited_at"),
                **_item_text(texts.get(row["id"])),
            }
        )
    return {
        "course_id": course_id,
        "seed": seed,
        "population": len(population),
        "items": items,
        "summary": summary(audits),
    }


@router.get("/audit/summary")
def audit_summary(request: Request, course_id: str) -> dict:
    """The course's key-error rate with its Wilson 95% interval, overall and
    by the key's status when audited."""
    require_admin(request)
    _, audits = _audit_reads(course_id)
    return {"course_id": course_id, **summary(audits)}


@router.post("/{item_id}/audit")
def audit(item_id: str, body: AuditBody, request: Request) -> dict:
    """Record staff's verdict on the item's key and act on it: "correct"
    confirms the key, "wrong" / "ambiguous" holds it (503 when it could not
    be recorded; recording it again finishes it)."""
    require_admin(request)
    admin = get_session_user_id(request)
    item = _stored(item_id)
    try:
        status = record_item_audit(item, body.verdict, auditor=admin)
    except Exception:
        logger.warning("check item audit not recorded (item %s)", item.id, exc_info=True)
        raise HTTPException(status_code=503, detail="Verdict not recorded; try again.") from None
    # "correct" confirms the key; "wrong" / "ambiguous" hold it
    return {"id": item_id, "verdict": body.verdict, "key_status": status, "held": body.verdict != "correct"}
