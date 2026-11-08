"""Check-item reports and reviews (spec §13 A113, A123; GitHub #695): the store
behind "Report this question" and the admin review queue.

Two tables (migrations 20261108041639_learning_item_quality.sql,
20261108072715_learning_evidence_void.sql and
20261108193927_learning_report_course_key.sql):

- check_item_reports — one row per (student, course item): the student's
  report, its reason an enum (params.ITEM_REPORT_REASONS; no free text is ever
  stored) and the surface it came from, keyed (user_id, course_id,
  question_hash) since spec §13 A142 — the same question drafted in two
  courses shares its hash, and each course's item counts its own reports. The
  row stops the question being served to that student (in any course); the
  read half is loop_state_store.reported_hashes, which every selection unions
  with the seen/revealed sets.
- check_item_reviews — one row per course item (course_id, question_hash),
  the decision record: 'quarantined' by
  params.ITEM_REPORT_QUARANTINE_MIN_REPORTERS distinct reporters (A123:
  nothing deleted), then decided by staff: 'approved' (a report newer than
  the approval counts toward a quarantine afresh) or 'retired' (deleted, its
  evidence voided — A123; final: a retired item is never approved, and the
  ONLY status that blocks re-drafting the question).

What keeps a quarantined or retired item from every student is the A124 HOLD,
not a read of this table: the database writes the matching staff-hold code
(learning/checks.py STAFF_HOLD_FLAGS — `reports_threshold`, `staff_retired`)
onto every row of the course item in the decision's own transaction, and a
trigger re-derives it on every later write of a row, so every student read
that drops a held item (check_item_service `_unheld`, checks.is_servable)
drops these too, and an approval lifts it.

Both decisions are the database's: `record_report` and `decide` call the
migration's SQL functions, which take one per-item advisory lock, so two
reporters arriving together are counted one after the other and exactly one of
them is told it quarantined the item. Hashes, ids, enums and timestamps only —
never item text. Every function RAISES on a failed store call; the callers
decide (the report route answers 503, the drafting write drops the batch)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import NamedTuple

from db.connection import page_all, pg_quote_value, rpc, table
from learning.checks import held_flags
from learning.params import ITEM_REPORT_QUARANTINE_MIN_REPORTERS, ITEM_REPORT_REASONS
from services.timestamps import parse_ts

#: The feature flag (services/feature_flags.py REGISTRY) behind the student
#: control and POST /api/learn/loop/report; the frontend reads it with useFlag.
ITEM_REPORTS_FLAG = "item_reports"
REPORTS = "check_item_reports"  # loop_state_store.reported_hashes reads it too
REVIEWS = "check_item_reviews"
_REPORT_RPC = "check_item_report_quarantine"
_DECIDE_RPC = "check_item_review_decide"

APPROVED = "approved"
QUARANTINED = "quarantined"
RETIRED = "retired"
DECIDED_BY_REPORTS = "reports"
DECIDED_BY_ADMIN = "admin"
#: hashes per `in.(...)` read (a URL-length bound, check_item_service's batch)
_HASH_BATCH = 100


class StoreUnavailable(RuntimeError):
    """A report/review function returned no row (the store did not answer)."""


class ReportOutcome(NamedTuple):
    first: bool  # this student had not reported the item before (a repeat records nothing)
    reporters: int  # distinct reporters of the course item since its last approval
    quarantine: bool  # this report reached the threshold: the item is quarantined now


class Decision(NamedTuple):
    previous: str | None  # the status before ('approved' / 'quarantined' / 'retired' / None)
    applied: bool  # False only when approving an item already retired


def _one_row(rows, name: str) -> dict:
    row = rows[0] if isinstance(rows, list) and rows else None
    if not isinstance(row, dict):
        raise StoreUnavailable(f"{name} returned no row")
    return row


def record_report(
    user_id: str, course_id: str, question_hash: str, *, reason: str, surface: str
) -> ReportOutcome:
    """Record one report and learn whether it quarantines the course item —
    ONE call to `check_item_report_quarantine`, which inserts (student,
    course item) at most once and counts the distinct reporters under the
    item's lock."""
    if reason not in ITEM_REPORT_REASONS:
        raise ValueError(f"unknown report reason {reason!r}")
    row = _one_row(
        rpc(
            _REPORT_RPC,
            {
                "p_user_id": user_id,
                "p_course_id": course_id,
                "p_question_hash": question_hash,
                "p_reason": reason,
                "p_surface": surface,
                "p_min_reporters": ITEM_REPORT_QUARANTINE_MIN_REPORTERS,
            },
        ),
        _REPORT_RPC,
    )
    return ReportOutcome(
        first=bool(row.get("first_report")),
        reporters=int(row.get("reporters") or 0),
        quarantine=bool(row.get("quarantine")),
    )


def decide(course_id: str, question_hash: str, status: str, *, reviewed_by: str) -> Decision:
    """An admin's decision on a course item ('approved' — lifts a quarantine
    — or 'retired' — holds every row until `retire_course_item` deletes it),
    under the same lock as the reports; the database moves the staff-hold code
    with the status. Approving a retired item is refused (applied False) and
    changes nothing."""
    if status not in (APPROVED, RETIRED):
        raise ValueError(f"unknown review status {status!r}")
    row = _one_row(
        rpc(
            _DECIDE_RPC,
            {
                "p_course_id": course_id,
                "p_question_hash": question_hash,
                "p_status": status,
                "p_reviewed_by": reviewed_by,
            },
        ),
        _DECIDE_RPC,
    )
    return Decision(previous=row.get("previous"), applied=bool(row.get("applied")))


def review_statuses(course_id: str, hashes: Iterable[str]) -> dict[str, str]:
    """The pending-or-final decision on each of `hashes` for the course:
    question_hash -> 'quarantined' or 'retired' (an approved or undecided one
    is absent). The drafting write reads it once per batch: a retired question
    is never stored again; a quarantined one is stored held, like its other
    rows (A123: only a staff retire blocks a re-draft)."""
    keys = sorted({h for h in hashes if h})
    out: dict[str, str] = {}
    for start in range(0, len(keys), _HASH_BATCH):
        batch = keys[start : start + _HASH_BATCH]
        rows = table(REVIEWS).select(
            "question_hash,status",
            filters={
                "course_id": f"eq.{course_id}",
                "status": f"in.({QUARANTINED},{RETIRED})",
                "question_hash": f"in.({','.join(pg_quote_value(h) for h in batch)})",
            },
        )
        out.update(
            (r["question_hash"], r["status"])
            for r in rows or []
            if r.get("question_hash") and r.get("status") in (QUARANTINED, RETIRED)
        )
    return out


def retired_items() -> set[tuple[str, str]]:
    """Every course item staff retired, as (course_id, question_hash) — the
    key the void rule (learning/evidence_void.py) is applied with. Retired
    items are few (a staff action each), so one paged, status-filtered read."""
    return {
        (row["course_id"], row["question_hash"])
        for row in page_all(
            table(REVIEWS),
            "course_id,question_hash",
            filters={"status": f"eq.{RETIRED}"},
            order="course_id,question_hash",
        )
        if row.get("course_id") and row.get("question_hash")
    }


def report_counts() -> dict[tuple[str, str], dict]:
    """Every reported course item: (course_id, question_hash) -> {reason: n
    for every reason, "total": n, "last_reported_at": aware datetime or None}.
    Reads every report row (they are rare: one per student per item), paged."""
    out: dict[tuple[str, str], dict] = {}
    for row in page_all(
        table(REPORTS),
        "course_id,question_hash,reason,created_at",
        order="course_id,question_hash,user_id",
    ):
        key = (row.get("course_id"), row.get("question_hash"))
        if not all(key):
            continue
        entry = out.setdefault(
            key, {**dict.fromkeys(ITEM_REPORT_REASONS, 0), "total": 0, "last_reported_at": None}
        )
        if row.get("reason") in ITEM_REPORT_REASONS:
            entry[row["reason"]] += 1
        entry["total"] += 1
        stamp = parse_ts(row.get("created_at"))
        if stamp is not None and (
            entry["last_reported_at"] is None or stamp > entry["last_reported_at"]
        ):
            entry["last_reported_at"] = stamp
    return out


def reviews() -> dict[tuple[str, str], dict]:
    """Every review decision: (course_id, question_hash) -> its row."""
    return {
        (row["course_id"], row["question_hash"]): row
        for row in page_all(
            table(REVIEWS),
            "course_id,question_hash,status,decided_by,reviewed_at",
            order="course_id,question_hash",
        )
        if row.get("course_id") and row.get("question_hash")
    }


def _iso(stamp) -> str | None:
    return stamp.isoformat() if stamp is not None else None


def review_entry(
    row: dict,
    counts: dict[tuple[str, str], dict],
    decisions: dict[tuple[str, str], dict],
) -> dict:
    """One stored item row as staff review it — its plaintext columns, its
    report counts by reason and its review decision, retire-pending and held
    — whether or not it belongs in the queue (`queue_entries` decides that;
    spec §13 A131's "flagged by data" view lists items it would not). Pure."""
    key = (row.get("course_id"), row.get("question_hash"))
    count = counts.get(key)
    decision = decisions.get(key) or {}
    flags = list(row.get("lint_flags") or [])
    status = decision.get("status")
    reports = {r: (count or {}).get(r, 0) for r in ITEM_REPORT_REASONS}
    return {
        "id": row.get("id"),
        "course_id": key[0],
        "concept_key": row.get("concept_key"),
        "question_hash": key[1],
        "format": row.get("format"),
        "difficulty": row.get("difficulty"),
        "lint_flags": flags,
        "reports": {**reports, "total": sum(reports.values())},
        "last_reported_at": _iso(count["last_reported_at"] if count else None),
        "status": status,
        "reviewed_at": _iso(parse_ts(decision.get("reviewed_at"))),
        "retire_pending": status == RETIRED,
        # A124, A123: withdrawn from every student until staff decide
        "held": held_flags(flags, row.get("canonical_verified")),
    }


def queue_entries(
    rows: Iterable[dict],
    counts: dict[tuple[str, str], dict],
    decisions: dict[tuple[str, str], dict],
) -> list[dict]:
    """The admin review queue over stored item rows (their plaintext columns:
    id, course_id, concept_key, question_hash, format, difficulty,
    lint_flags, canonical_verified), given `report_counts()` and `reviews()`.
    An item is in the queue when it carries lint flags or reports and no
    approval at or after its last report clears it, when it is retired but
    still stored (the retire — the void of its evidence and the delete — did
    not finish: `retire_pending`), or when a hold withdraws it (`held`: a key
    hold, spec §13 A124, or a staff hold, A123 — its reporters quarantined it,
    `reports_threshold` in its flags and 'quarantined' its status), whatever
    an older approval said, so a held item is never stuck out of both the
    queue and the students' reach. Ordered: retire-pending first, then held,
    then the most-reported (latest first), then the most-flagged; ties by
    course, concept and id. Pure."""
    out: list[dict] = []
    for row in rows:
        entry = review_entry(row, counts, decisions)
        key = (entry["course_id"], entry["question_hash"])
        count = counts.get(key)
        last = count["last_reported_at"] if count else None
        reviewed_at = parse_ts((decisions.get(key) or {}).get("reviewed_at"))
        cleared = entry["status"] == APPROVED and (
            last is None or (reviewed_at is not None and last <= reviewed_at)
        )
        if not (entry["retire_pending"] or entry["held"]) and (cleared or not (entry["lint_flags"] or count)):
            continue
        out.append(entry)
    out.sort(
        key=lambda e: (
            not e["retire_pending"],
            not e["held"],
            -e["reports"]["total"],
            -(parse_ts(e["last_reported_at"]).timestamp() if e["last_reported_at"] else 0.0),
            -len(e["lint_flags"]),
            str(e["course_id"]),
            str(e["concept_key"]),
            str(e["id"]),
        )
    )
    return out
