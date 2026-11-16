"""Admin-only, read-only analytics + cost-rollup API (issue #120).

Turns the `events` and `llm_usage` tables (written by services/events_service.py,
#116/#118) into usage summaries, per-user rollups, LLM cost breakdowns, and an
error feed. Mounted at `/api/admin/analytics`; every endpoint is gated by
`require_admin`. Read-only — no mutation endpoints.

Aggregation strategy: PostgREST (via `db/connection.py::table()`) has no
GROUP BY, so the grouped endpoints scan the (date-bounded) rows and aggregate
in Python. Scans page through `select_with_count` and use its exact count both
to know when to stop and to detect the rare truncation case (logged and
surfaced as `truncated: true` in the response, never silent). The `/errors`
feed needs no aggregation, so it paginates server-side.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request, Response

from db.connection import rpc, table
from services.admin.analytics import db_scope as admin_db_scope
from services.admin.analytics import scan as _scan
from services.admin.errors import Unprocessable
from services.auth_guard import require_admin
from services.llm_pricing import COST_SCALE

# The response models, range scan and day bucketing moved to
# services/admin/analytics/ (#118); re-exported so imports and patches of the
# old names on this module keep working.
from services.admin.analytics.models import (  # noqa: F401  (re-export, #118)
    _NULL_COST,
    Bucket,
    CostDayPoint,
    CostPerActiveUser,
    CostRow,
    CostTotals,
    CostWeek,
    DayCount,
    DbScopeGroup,
    DbScopeReport,
    DbScopeWindow,
    ErrorEvent,
    ErrorsPage,
    EventTypeCount,
    GroupBy,
    LLMCost,
    Range,
    UsageByUser,
    UsageSummary,
    UserUsage,
)
from services.admin.analytics.scan import (  # noqa: F401  (re-export, #118)
    _NOT_SYSTEM,
    _PAGE,
    _SCAN_CAP,
    _as_float,
    _as_int,
    _scan_range,
)
from services.admin.analytics.series import (  # noqa: F401  (re-export, #118)
    _bucket_date,
    _cost_series,
    _count_series,
)

logger = logging.getLogger("sapling.admin_analytics")

router = APIRouter()

_GROUP_COLUMN = {"user": "user_id", "feature": "feature", "model": "model"}


def _resolve_range(from_: str | None, to: str | None) -> tuple[str, str]:
    """``services.admin.analytics.scan._resolve_range`` (default: the last 30
    days), with a bad bound mapped to the 422 it always was."""
    try:
        return _scan._resolve_range(from_, to)
    except Unprocessable as e:
        raise HTTPException(status_code=422, detail=e.detail)


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/usage/summary", response_model=UsageSummary)
def usage_summary(
    request: Request,
    response: Response,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    bucket: Bucket | None = Query(None),
) -> UsageSummary:
    """Event totals for the range; `truncated: true` means the scan cap cut the aggregation short."""
    require_admin(request)
    response.headers["Cache-Control"] = "private"
    from_iso, to_iso = _resolve_range(from_, to)
    rows, truncated = _scan_range(
        "events", "event_type,user_id,created_at", from_iso, to_iso,
        extra_filters=_NOT_SYSTEM,
    )

    by_type: dict[str, int] = defaultdict(int)
    users: set[str] = set()
    for r in rows:
        by_type[r.get("event_type") or ""] += 1
        if r.get("user_id"):
            users.add(r["user_id"])

    return UsageSummary(
        range=Range(from_=from_iso, to=to_iso),
        total_events=len(rows),
        distinct_active_users=len(users),
        by_event_type=sorted(
            (EventTypeCount(event_type=k, count=v) for k, v in by_type.items()),
            key=lambda e: e.count, reverse=True,
        ),
        truncated=truncated,
        series=_count_series(rows) if bucket else None,
    )


@router.get("/usage/by-user", response_model=UsageByUser)
def usage_by_user(
    request: Request,
    response: Response,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> UsageByUser:
    """Per-user event/cost rollup; `truncated: true` means a scan cap cut the aggregation short."""
    require_admin(request)
    response.headers["Cache-Control"] = "private"
    from_iso, to_iso = _resolve_range(from_, to)

    event_rows, events_truncated = _scan_range(
        "events", "user_id,category,created_at", from_iso, to_iso,
        extra_filters=_NOT_SYSTEM,
    )
    usage_rows, usage_truncated = _scan_range(
        "llm_usage", "user_id,cost_usd,total_tokens,created_at", from_iso, to_iso,
    )

    agg: dict[str, dict] = defaultdict(
        lambda: {"event_count": 0, "by_category": defaultdict(int), "llm_cost_usd": 0.0, "total_tokens": 0},
    )
    for r in event_rows:
        uid = r.get("user_id")
        if not uid:
            continue
        a = agg[uid]
        a["event_count"] += 1
        a["by_category"][r.get("category") or ""] += 1
    for r in usage_rows:
        uid = r.get("user_id")
        if not uid:
            continue
        a = agg[uid]
        a["llm_cost_usd"] += _as_float(r.get("cost_usd"))
        a["total_tokens"] += _as_int(r.get("total_tokens"))

    # Sort by spend then activity so the most expensive users surface first.
    ordered = sorted(
        agg.items(),
        key=lambda kv: (kv[1]["llm_cost_usd"], kv[1]["event_count"]),
        reverse=True,
    )
    page = ordered[offset:offset + limit]
    users = [
        UserUsage(
            user_id=uid,
            event_count=a["event_count"],
            by_category=dict(a["by_category"]),
            llm_cost_usd=round(a["llm_cost_usd"], COST_SCALE),
            total_tokens=a["total_tokens"],
        )
        for uid, a in page
    ]
    return UsageByUser(
        range=Range(from_=from_iso, to=to_iso),
        total_users=len(ordered), limit=limit, offset=offset, users=users,
        truncated=events_truncated or usage_truncated,
    )


@router.get("/llm/cost", response_model=LLMCost)
def llm_cost(
    request: Request,
    response: Response,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    group_by: GroupBy = Query("feature"),
    bucket: Bucket | None = Query(None),
) -> LLMCost:
    """LLM token/cost rollup; `truncated: true` means the scan cap cut the aggregation short."""
    require_admin(request)
    response.headers["Cache-Control"] = "private"
    from_iso, to_iso = _resolve_range(from_, to)
    column = _GROUP_COLUMN[group_by]
    rows, truncated = _scan_range(
        "llm_usage",
        f"{column},prompt_tokens,completion_tokens,total_tokens,cost_usd,created_at",
        from_iso, to_iso,
    )

    buckets: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0},
    )
    for r in rows:
        key = r.get(column)
        b = buckets["" if key is None else str(key)]
        b["calls"] += 1
        b["prompt_tokens"] += _as_int(r.get("prompt_tokens"))
        b["completion_tokens"] += _as_int(r.get("completion_tokens"))
        b["total_tokens"] += _as_int(r.get("total_tokens"))
        b["cost_usd"] += _as_float(r.get("cost_usd"))

    cost_rows = sorted(
        (
            CostRow(
                key=k, calls=b["calls"],
                prompt_tokens=b["prompt_tokens"], completion_tokens=b["completion_tokens"],
                total_tokens=b["total_tokens"], cost_usd=round(b["cost_usd"], COST_SCALE),
            )
            for k, b in buckets.items()
        ),
        key=lambda c: c.cost_usd, reverse=True,
    )
    totals = CostTotals(
        calls=sum(c.calls for c in cost_rows),
        prompt_tokens=sum(c.prompt_tokens for c in cost_rows),
        completion_tokens=sum(c.completion_tokens for c in cost_rows),
        total_tokens=sum(c.total_tokens for c in cost_rows),
        cost_usd=round(sum(c.cost_usd for c in cost_rows), COST_SCALE),
    )
    return LLMCost(
        range=Range(from_=from_iso, to=to_iso), group_by=group_by,
        rows=cost_rows, totals=totals, truncated=truncated,
        series=_cost_series(rows) if bucket else None,
    )


@router.get("/llm/cost-per-active-user", response_model=CostPerActiveUser)
def llm_cost_per_active_user(request: Request, response: Response) -> CostPerActiveUser:
    """Weekly LLM cost per active user and the "2x jump" alert signal (#119).

    One call to the SQL function `llm_cost_per_active_user_weekly()`
    (migration 20261108213311) — the same definition Canopy's metrics should
    read, so the two never disagree. Cost = priced `llm_usage` rows; active =
    distinct non-system `events` users, as `distinct_active_users` above.
    503 when the database can't answer: never a made-up zero."""
    require_admin(request)
    response.headers["Cache-Control"] = "private"
    try:
        payload = rpc("llm_cost_per_active_user_weekly", {})
        if isinstance(payload, list):
            payload = payload[0] if payload else None
        return CostPerActiveUser.model_validate(payload)
    except Exception as exc:
        logger.warning("llm cost-per-active-user unavailable: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="LLM cost signal unavailable") from exc


@router.get("/errors", response_model=ErrorsPage)
def errors(
    request: Request,
    response: Response,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    bucket: Bucket | None = Query(None),
) -> ErrorsPage:
    """Paginated error-category event feed; `?bucket=day` adds a per-day series (its own capped scan)."""
    require_admin(request)
    response.headers["Cache-Control"] = "private"
    from_iso, to_iso = _resolve_range(from_, to)
    # ALL category="error" events, newest first — not just the error.* HTTP
    # names. Backend failures like quiz.context_write_failed (#529/B3) and
    # the rag.* pair (#482) carry the error category without the name
    # prefix; filtering by name hid exactly the events whose invisibility
    # they were added to end. Non-HTTP rows simply null the payload fields.
    rows, total = table("events").select_with_count(
        "created_at,event_type,request_id,user_id,payload",
        filters={"created_at": [f"gte.{from_iso}", f"lte.{to_iso}"], "category": "eq.error"},
        order="created_at.desc", limit=limit, offset=offset,
    )
    series = None
    series_truncated = False
    if bucket:
        scan_rows, series_truncated = _scan_range(
            "events", "created_at", from_iso, to_iso,
            extra_filters={"category": "eq.error"},
        )
        series = _count_series(scan_rows)
    items = []
    for r in rows:
        payload = r.get("payload") or {}
        items.append(ErrorEvent(
            created_at=r.get("created_at"),
            event_type=r.get("event_type") or "",
            request_id=r.get("request_id"),
            user_id=r.get("user_id"),
            path=payload.get("path"),
            method=payload.get("method"),
            status_code=payload.get("status_code"),
            duration_ms=payload.get("duration_ms"),
        ))
    return ErrorsPage(
        range=Range(from_=from_iso, to=to_iso),
        total=total, limit=limit, offset=offset, errors=items,
        truncated=series_truncated, series=series,
    )


# ── db_user_scope rollout report (#115) ──────────────────────────────────────
#
# docs/security/db-user-scope-rollout.md: the "read the report" step of the
# shadow -> enforce ladder. Two views of the same signal: `top` groups the
# db.* events every worker wrote to the `events` table over the window (the
# cross-worker, survives-a-deploy view), and `process` is THIS worker's
# in-process tally since boot (db/scope_report.py), which also carries what
# the events cannot: shadow-read coverage and the inventory of writes shadow
# could not verify.

_DB_SCOPE_EVENTS = ("db.rls_shadow_divergence", "db.unscoped_query", "db.rls_denied")

#: One GROUP BY in Postgres (migration 20261109023455); grouping/merging in
#: services/admin/analytics/db_scope.py. Until the migration is applied (or if the call
#: fails) the report falls back to a capped scan grouped in Python: at most
#: _DB_SCOPE_SCAN_CAP events (newest first), flagged `truncated`. The window
#: is at most _DB_SCOPE_MAX_HOURS either way.
DB_SCOPE_FN = "db_scope_divergences"
_DB_SCOPE_SCAN_CAP = 20_000
_DB_SCOPE_MAX_HOURS = 168


@router.get("/db-scope", response_model=DbScopeReport)
def db_scope_report(
    request: Request,
    response: Response,
    hours: int = Query(24, ge=1, le=_DB_SCOPE_MAX_HOURS),
    limit: int = Query(50, ge=1, le=500),
) -> DbScopeReport:
    """Top `db_user_scope` divergences by route + table over the last `hours`
    (at most a week), plus this worker's in-process tally. Ids, counts and
    codes only. One SQL GROUP BY; before its migration, a scan of at most
    `_DB_SCOPE_SCAN_CAP` events, newest first."""
    require_admin(request)
    response.headers["Cache-Control"] = "private"
    from db import scope_report
    from db.connection import pg_quote_value

    now = datetime.now(timezone.utc)
    from_iso, to_iso = (now - timedelta(hours=hours)).isoformat(), now.isoformat()
    try:
        groups, total = admin_db_scope.group_rpc_rows(rpc(DB_SCOPE_FN, {
            "p_from": from_iso, "p_to": to_iso, "p_events": list(_DB_SCOPE_EVENTS)}))
        truncated = False
    except Exception as exc:  # not migrated yet / PostgREST down: the capped scan
        logger.info("%s() unavailable (%s); scanning", DB_SCOPE_FN, type(exc).__name__)
        rows, truncated = _scan_range(
            "events", "created_at,event_type,user_id,request_id,payload", from_iso, to_iso,
            extra_filters={"event_type": "in.(" + ",".join(pg_quote_value(e) for e in _DB_SCOPE_EVENTS) + ")"},
            cap=_DB_SCOPE_SCAN_CAP, newest_first=True,
        )
        groups, total = admin_db_scope.group_rows(rows), len(rows)
    return DbScopeReport(
        window=DbScopeWindow(from_=from_iso, to=to_iso, hours=hours),
        total=total, groups=len(groups), truncated=truncated,
        top=[DbScopeGroup(**g) for g in admin_db_scope.ranked(groups, limit)],
        scan_cap=_DB_SCOPE_SCAN_CAP, process=scope_report.snapshot(limit),
    )
