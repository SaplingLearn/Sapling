"""Admin view of the background job queue (#116).

`GET /api/admin/jobs` answers the two questions an operator has about the
queue the worker drains (services/jobs.py, `python -m worker`):

* **Is it keeping up?** `status_counts` (every row, by status: exact counts)
  and `outstanding` (unfinished rows by type and status: queued, failed =
  waiting out a retry backoff, running). A growing `queued` with no `running`
  means no worker is claiming that type.
* **What gave up?** `dead_letter`: the newest `dead` rows, with the error that
  killed them. Dead rows are never pruned, so this list is complete.

Read-only, admin-only (`require_admin`), through `table()`; `jobs` is a
service-only table, so the router is mounted with `admin_service_route`.
Payloads hold ids only, never student content (the migration's column
comment), so they are returned as they are.
"""
from __future__ import annotations

from itertools import islice

from fastapi import APIRouter, Query, Request

from db.connection import MAX_ROWS, page_all, table
from services.auth_guard import require_admin

router = APIRouter()

STATUSES = ("queued", "failed", "running", "succeeded", "dead")
_OUTSTANDING = ("queued", "failed", "running")

#: Unfinished rows read for the per-type breakdown. A backlog past this is
#: reported as `outstanding_truncated` (status_counts stays exact). Follow-up:
#: a `jobs_overview()` SQL function (GROUP BY type, status) would make this one
#: exact aggregate instead of a capped scan, but it needs a migration.
OUTSTANDING_SCAN_CAP = 10 * MAX_ROWS

_DEAD_COLUMNS = ",".join((
    "id", "type", "payload", "attempts", "max_attempts", "last_error",
    "dedupe_key", "locked_by", "created_at", "updated_at",
))


def _status_counts() -> dict[str, int]:
    """Exact count per status (PostgREST `count=exact`, one row read each)."""
    out = {}
    for status in STATUSES:
        _rows, total = table("jobs").select_with_count(
            "id", filters={"status": f"eq.{status}"}, limit=1,
        )
        out[status] = int(total or 0)
    return out


def _outstanding() -> tuple[dict[str, dict[str, int]], bool]:
    """{type: {queued, failed, running}} over unfinished rows, and whether
    there are more than OUTSTANDING_SCAN_CAP of them (one row past the cap is
    read to know: `truncated` is never set for a backlog of exactly the cap)."""
    by_type: dict[str, dict[str, int]] = {}
    rows = page_all(
        table("jobs"), "id,type,status",
        filters={"status": f"in.({','.join(_OUTSTANDING)})"},
        order="created_at,id",
        page=min(MAX_ROWS, OUTSTANDING_SCAN_CAP + 1),
    )
    scanned = list(islice(rows, OUTSTANDING_SCAN_CAP + 1))
    truncated = len(scanned) > OUTSTANDING_SCAN_CAP
    for row in scanned[:OUTSTANDING_SCAN_CAP]:
        counts = by_type.setdefault(row["type"], {s: 0 for s in _OUTSTANDING})
        if row.get("status") in counts:
            counts[row["status"]] += 1
    return dict(sorted(by_type.items())), truncated


@router.get("")
def queue_overview(
    request: Request,
    dead_limit: int = Query(50, ge=1, le=500),
    job_type: str | None = Query(None, alias="type", max_length=63),
) -> dict:
    """Queue depth by status and by type, plus the newest dead letters.

    `type` narrows the dead-letter list to one job type; `dead_limit` caps it
    (newest first).
    """
    require_admin(request)
    counts = _status_counts()
    outstanding, truncated = _outstanding()
    filters = {"status": "eq.dead"}
    if job_type:
        filters["type"] = f"eq.{job_type}"
    dead = table("jobs").select(
        _DEAD_COLUMNS, filters=filters, order="updated_at.desc,id", limit=dead_limit,
    ) or []
    return {
        "status_counts": counts,
        "depth": sum(counts[s] for s in _OUTSTANDING),
        "outstanding": outstanding,
        "outstanding_truncated": truncated,
        "dead_letter": dead,
        "dead_total": counts["dead"],
    }
