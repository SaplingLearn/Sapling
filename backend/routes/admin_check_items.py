"""Admin review queue for learning-loop check items (spec §13 A113, A123;
GitHub #695), and the key audit (spec §13 A124).

Check items are drafted by a model from classmates' uploads and keyed from
peer material; no instructor reviews them before they grade students. This is
where staff do: every stored item the item-flaw linter flagged
(`check_items.lint_flags`, learning/item_lint.py) or a student reported
(`check_item_reports`, counted by reason), unless an admin approved it after its
last report — and every item a hold withdraws from students, whatever an
older approval said: a key hold (A124: the blind solve disputed its key or
found the passages do not settle it, or an audit found it wrong or
ambiguous) or a staff hold (A123: its reporters quarantined it —
`reports_threshold`; nothing is deleted until a decision here). An item whose
retire was decided but did not finish (a void or the delete failed) is
listed first, as `retire_pending`; held items next.

- `GET /queue` — the queue. Every entry by its plaintext columns; the first
  QUEUE_PAGE also carry the item's text (prompt, options with the correct one
  marked, final answer, reference, and a numeric item's canonical value and
  tolerance — what the A22 numeric gate grades with once the key is
  confirmed), decrypted here, at the read boundary
  (check_item_service.items_by_ids → `_row_to_item`).
- `POST /{item_id}/approve` — reviewed, OK: lifts a quarantine (the
  database drops `reports_threshold` with the decision), clears the course
  item from the queue until a newer report (which counts toward a quarantine
  afresh), confirms its key (A124: `canonical_verified`, the A22 instructor
  confirmation, which lifts a key hold) and re-lints its rows — a held item
  is served again (`restored`). A retired item cannot be approved (409).
- `POST /{item_id}/retire` — retires the course item: the decision first (no
  new grade of it commits; the database holds every row, `staff_retired`, so
  nothing serves it), then every student's evidence
  graded against it is VOIDED and their learner state recomputed from the rest
  of their journal through the single graph writer, then every row of the
  course with its question_hash is deleted (check_item_service's A23 retire
  path). It is never drafted for the course again. A failure is a 503 that
  leaves it retire-pending; retiring again finishes it (idempotent).
- `GET /audit/sample?course_id=…&n=…&seed=…` — A124: a stratified sample of
  the course's stored keys for staff to judge (learning/item_audit.py), with
  their text and any verdict already recorded, and the course's audit summary.
- `POST /{item_id}/audit` — A124: staff's verdict on the item's key (correct /
  wrong / ambiguous), recorded in check_item_audits; "correct" confirms the
  key, "wrong" / "ambiguous" holds it (check_item_service.record_item_audit).
- `GET /audit/summary?course_id=…` — A124: the course's key-error rate with a
  Wilson 95% interval, overall and by the key's status when audited.
- `GET /stats?course_id=…` — A131: empirical item statistics over the
  course's evidence journal (learning/item_stats.py: n, p-value, item–rest
  discrimination, data flags) for every stored item, and the items the data
  flags as review entries with their text. Read-only: staff decide.

Every endpoint calls `require_admin` first. Queue decisions run through
learning.item_reports, under the same per-item database lock as the students'
reports, and each emits an audit event.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from db.connection import page_all, table
from learning import item_reports
from learning.checks import CheckItem, held
from learning.item_audit import stratified_sample, summary
from learning.item_stats import empty_stats, item_statistics
from learning.params import (
    ITEM_AUDIT_SAMPLE_DEFAULT,
    ITEM_AUDIT_SAMPLE_MAX,
    ITEM_REPORT_QUARANTINE_MIN_REPORTERS,
    ITEM_STATS_EASY_P,
    ITEM_STATS_FLAGS,
    ITEM_STATS_HARD_P,
    ITEM_STATS_LOW_DISCRIMINATION,
    ITEM_STATS_MIN_N,
)
from services.auth_guard import get_session_user_id, require_admin
from services.check_item_service import (
    audit_population,
    confirm_course_item,
    course_audit_rows,
    course_item_rows,
    flagged_item_rows,
    get_check_item,
    item_rows_for,
    items_by_ids,
    key_status,
    record_item_audit,
    relint_course_item,
    retire_course_item,
)
from services.events_service import log_event
from services.timestamps import parse_ts

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
    decision — retire-pending first, then held (a key hold, or a quarantine
    by reports), then the most reported, then the most flagged."""
    require_admin(request)
    counts = item_reports.report_counts()
    decisions = item_reports.reviews()
    rows = {r["id"]: r for r in flagged_item_rows() if r.get("id")}
    awaiting = (item_reports.QUARANTINED, item_reports.RETIRED)
    wanted = set(counts) | {k for k, d in decisions.items() if d.get("status") in awaiting}
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
        "quarantine_min_reporters": ITEM_REPORT_QUARANTINE_MIN_REPORTERS,
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
    its quarantine is lifted (A123) and its key confirmed (A124), so a held
    item is served to every student again (`restored`: it was held — the
    row staff decided on, read with its hold before the decision). The
    decision is recorded first; a failed confirmation or re-lint (503) is
    finished by approving again, and the queue lists a still-held item
    meanwhile."""
    require_admin(request)
    admin = get_session_user_id(request)
    item = _stored(item_id)
    restored = held(item)
    decision = _decide(item, item_reports.APPROVED, admin)
    if not decision.applied:
        raise HTTPException(status_code=409, detail="This question was retired; it cannot be approved.")
    try:
        confirm_course_item(item.course_id, item.question_hash)
        # A123: a never-linted row a quarantine held reads "linted clean" once
        # the hold is lifted; lint it now (a no-op for every other row)
        relint_course_item(item.course_id, item.question_hash)
    except Exception:
        logger.warning("check item key not confirmed (item %s)", item.id, exc_info=True)
        raise HTTPException(
            status_code=503, detail="Approved, but its key was not confirmed yet; approve it again."
        ) from None
    log_event(
        _APPROVED_EVENT,
        category="audit",
        user_id=admin,
        payload={"course_id": item.course_id, "question_hash": item.question_hash, "restored": restored},
    )
    return {"id": item_id, "status": item_reports.APPROVED, "restored": restored}


@router.post("/{item_id}/retire")
def retire(item_id: str, request: Request) -> dict:
    """Retire the course item now: the decision is recorded first (from then
    on no grade of it commits and nothing serves it), then its evidence is
    voided student by student and its rows deleted. A failure (503) leaves it
    retire-pending in the queue; retiring again finishes it."""
    require_admin(request)
    admin = get_session_user_id(request)
    item = _stored(item_id)
    _decide(item, item_reports.RETIRED, admin)
    try:
        outcome = retire_course_item(item.course_id, item.question_hash)
    except Exception:
        logger.error("check item retire FAILED (item %s)", item.id, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Retired, but its results were not all voided yet; retire it again.",
        ) from None
    log_event(
        _RETIRED_EVENT,
        category="audit",
        user_id=admin,
        payload={
            "course_id": item.course_id,
            "question_hash": item.question_hash,
            "decided_by": item_reports.DECIDED_BY_ADMIN,
            "items": outcome.items,
            "students": outcome.students,
            "voided": outcome.voided,
        },
    )
    return {
        "id": item_id,
        "status": item_reports.RETIRED,
        "items": outcome.items,
        "students": outcome.students,
        "voided": outcome.voided,
    }

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


# ── empirical item statistics (A131) ─────────────────────────────────────────

#: What the statistics read off each evidence row (learning/item_stats.py):
#: the item and the student (the node's owner and course), the outcome, and
#: what decides an unassisted first attempt — the help and rung, the re-check
#: flag (journaled since A123; on an older row the planning envelope's, or the
#: weight with the grader's confidence) — plus the journal's total order.
_STATS_EVIDENCE_COLUMNS = (
    "id,node_id,question_hash,check_item_id,channel,reason,correct,assisted,max_rung,weight,"
    "confidence,same_session_recheck,planning_recheck:planning_observation->same_session_recheck,"
    "created_at,evidence_seq,graph_nodes!inner(user_id,course_id)"
)
#: The most evidence rows one statistics read scans (admin analytics' scan cap).
STATS_SCAN_CAP = 100_000
#: The data flags, worst first: a negative item–rest correlation is the
#: classic sign of a wrong key, an item almost nobody gets right the next.
_FLAG_SEVERITY = ("negative_discrimination", "too_hard", "low_discrimination", "too_easy")
assert set(_FLAG_SEVERITY) == set(ITEM_STATS_FLAGS)


def _course_evidence(course_id: str) -> tuple[list[dict], bool]:
    """Every check-item evidence row of the course, every student's, in the
    journal's total order — oldest first, so a cut at STATS_SCAN_CAP keeps
    every first attempt it reached. Returns (rows, truncated). Raises on a
    failed read."""
    rows: list[dict] = []
    for row in page_all(
        table("node_mastery_events"),
        _STATS_EVIDENCE_COLUMNS,
        filters={
            "graph_nodes.course_id": f"eq.{course_id}",
            "event_type": "eq.evidence",
            "check_item_id": "not.is.null",
        },
        order="created_at.asc,evidence_seq.asc.nullslast,id.asc",
    ):
        if len(rows) >= STATS_SCAN_CAP:
            return rows, True
        rows.append(row)
    return rows, False


def _decided_on_these_numbers(entry: dict, stats: dict) -> bool:
    """Staff approved the item at or after its numbers last changed
    (`numbers_changed_at`: its newest counted attempt, its students' newest
    attempt on the concept's other items, or a retire that voided one) — they
    decided on the numbers shown — so it leaves the "flagged by data" view
    until they change again (the queue's rule for reports, A113). A held or
    retire-pending item always stays."""
    if entry["status"] != item_reports.APPROVED or entry["held"] or entry["retire_pending"]:
        return False
    reviewed, changed = parse_ts(entry["reviewed_at"]), parse_ts(stats["numbers_changed_at"])
    return reviewed is not None and changed is not None and changed <= reviewed


def _retired_at(decisions: dict) -> dict:
    """The staff-retired course items (the void rule's key, A123) with their
    decision time: the review decisions with status 'retired' — the same
    rows `item_reports.retired_items` reads, so no read of its own."""
    return {
        key: parse_ts(d.get("reviewed_at"))
        for key, d in decisions.items()
        if d.get("status") == item_reports.RETIRED
    }


@router.get("/stats")
def item_statistics_report(request: Request, course_id: str) -> dict:
    """Spec §13 A131: classical item analysis of the course's check items
    over its evidence journal (learning/item_stats.py) — per stored item, n
    (students whose first attempt was unassisted), the p-value with its
    Wilson 95% interval, the corrected item–rest discrimination and its n,
    and the data flags (too easy, too hard, low or negative discrimination;
    each only from ITEM_STATS_MIN_N students). Void rows are left out (A123).

    `items`: every stored item of the course, held ones included, by its
    plaintext columns and statistics. `flagged`: the items the data flags,
    each as the review queue lists an item (its reports, decision, hold) with
    its statistics, worst first — held and retire-pending first, then by the
    worst flag — leaving out an item staff approved on these numbers (at or
    after they last changed); the first QUEUE_PAGE carry their decrypted text
    so staff can approve or retire them here. Nothing is written: no flag
    reaches lint_flags or a hold — staff decide. 503 when a read failed."""
    require_admin(request)
    try:
        stored = course_item_rows(course_id)
        evidence, truncated = _course_evidence(course_id)
        counts = item_reports.report_counts()
        decisions = item_reports.reviews()
    except Exception:
        logger.warning("check item statistics unavailable (course %s)", course_id, exc_info=True)
        raise HTTPException(status_code=503, detail="Item statistics unavailable; try again.") from None
    stats = item_statistics(evidence, retired=_retired_at(decisions))
    items: list[dict] = []
    flagged: list[dict] = []
    for row in stored:
        if not row.get("id"):
            continue
        s = stats.get((row.get("course_id"), row.get("question_hash"))) or empty_stats()
        items.append(
            {
                "id": row["id"],
                "concept_key": row.get("concept_key"),
                "question_hash": row.get("question_hash"),
                "format": row.get("format"),
                "difficulty": row.get("difficulty"),
                **s,
            }
        )
        if s["flags"]:
            entry = item_reports.review_entry(row, counts, decisions)
            if not _decided_on_these_numbers(entry, s):
                flagged.append({**entry, "stats": s})
    flagged.sort(
        key=lambda e: (
            not e["retire_pending"],
            not e["held"],
            min(_FLAG_SEVERITY.index(f) for f in e["stats"]["flags"]),
            -e["stats"]["n"],
            str(e["concept_key"]),
            str(e["id"]),
        )
    )
    page = flagged[:QUEUE_PAGE]
    try:
        texts = {i.id: i for i in items_by_ids(e["id"] for e in page)} if page else {}
    except Exception:
        logger.warning("check item statistics: texts unread (course %s)", course_id, exc_info=True)
        raise HTTPException(status_code=503, detail="Item statistics unavailable; try again.") from None
    return {
        "course_id": course_id,
        "min_n": ITEM_STATS_MIN_N,
        "easy_p": ITEM_STATS_EASY_P,
        "hard_p": ITEM_STATS_HARD_P,
        "low_discrimination": ITEM_STATS_LOW_DISCRIMINATION,
        "rows_scanned": len(evidence),
        "truncated": truncated,
        "items": items,
        "flagged": [{**e, **_item_text(texts.get(e["id"]))} for e in page],
        "flagged_count": len(flagged),
        "page_size": QUEUE_PAGE,
    }
