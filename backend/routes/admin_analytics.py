"""Admin-only, read-only analytics + cost-rollup API (issue #120).

Turns the `events` and `llm_usage` tables (written by services/events_service.py,
#116/#118) into usage summaries, per-user rollups, LLM cost breakdowns, and an
error feed. Mounted at `/api/admin/analytics`; every endpoint is gated by
`require_admin`. Read-only — no mutation endpoints.

Aggregation strategy: PostgREST (via `db/connection.py::table()`) has no
GROUP BY, so the grouped endpoints scan the (date-bounded) rows and aggregate
in Python. Scans page through `select_with_count` and use its exact count both
to know when to stop and to detect the rare truncation case (logged, never
silent). The `/errors` feed needs no aggregation, so it paginates server-side.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from db.connection import table
from services.auth_guard import require_admin

logger = logging.getLogger("sapling.admin_analytics")

router = APIRouter()

# Page size for range scans, and a hard ceiling so a pathological range can't
# pull unbounded rows into memory. Hitting the cap is logged, never silent.
_PAGE = 1000
_SCAN_CAP = 100_000

GroupBy = Literal["user", "feature", "model"]
_GROUP_COLUMN = {"user": "user_id", "feature": "feature", "model": "model"}


# ── Response models ──────────────────────────────────────────────────────────


class Range(BaseModel):
    from_: str
    to: str


class EventTypeCount(BaseModel):
    event_type: str
    count: int


class UsageSummary(BaseModel):
    range: Range
    total_events: int
    distinct_active_users: int
    by_event_type: list[EventTypeCount]


class UserUsage(BaseModel):
    user_id: str
    event_count: int
    by_category: dict[str, int]
    llm_cost_usd: float
    total_tokens: int


class UsageByUser(BaseModel):
    range: Range
    total_users: int
    limit: int
    offset: int
    users: list[UserUsage]


class CostRow(BaseModel):
    key: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float


class CostTotals(BaseModel):
    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float


class LLMCost(BaseModel):
    range: Range
    group_by: GroupBy
    rows: list[CostRow]
    totals: CostTotals


class ErrorEvent(BaseModel):
    created_at: str | None
    event_type: str
    request_id: str | None
    user_id: str | None
    path: str | None
    method: str | None
    status_code: int | None
    duration_ms: float | None


class ErrorsPage(BaseModel):
    range: Range
    total: int
    limit: int
    offset: int
    errors: list[ErrorEvent]


# ── Date range helpers ───────────────────────────────────────────────────────


def _resolve_range(from_: str | None, to: str | None) -> tuple[str, str]:
    """Default to the last 30 days; echo caller-supplied ISO bounds otherwise."""
    now = datetime.now(timezone.utc)
    to_iso = to or now.isoformat()
    from_iso = from_ or (now - timedelta(days=30)).isoformat()
    return from_iso, to_iso


def _scan_range(
    table_name: str, columns: str, from_iso: str, to_iso: str,
    extra_filters: dict | None = None,
) -> list[dict]:
    """Fetch every row in [from, to] for a table, paging via select_with_count.

    Aggregation endpoints need the full (date-bounded) set — PostgREST won't
    GROUP BY for us — so we page to completion rather than relying on the
    server's default row cap. A range large enough to hit _SCAN_CAP is logged.
    """
    out: list[dict] = []
    offset = 0
    while True:
        filters: dict = {"created_at": [f"gte.{from_iso}", f"lte.{to_iso}"]}
        if extra_filters:
            filters.update(extra_filters)
        rows, total = table(table_name).select_with_count(
            columns, filters=filters, order="created_at.asc", limit=_PAGE, offset=offset,
        )
        out.extend(rows)
        if len(out) >= total or not rows:
            break
        if len(out) >= _SCAN_CAP:
            logger.warning(
                "admin_analytics scan hit cap %d on %r (total=%d); results truncated",
                _SCAN_CAP, table_name, total,
            )
            break
        offset += _PAGE
    return out


def _as_float(value) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _as_int(value) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/usage/summary", response_model=UsageSummary)
def usage_summary(
    request: Request,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
) -> UsageSummary:
    require_admin(request)
    from_iso, to_iso = _resolve_range(from_, to)
    rows = _scan_range("events", "event_type,user_id,created_at", from_iso, to_iso)

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
    )


@router.get("/usage/by-user", response_model=UsageByUser)
def usage_by_user(
    request: Request,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> UsageByUser:
    require_admin(request)
    from_iso, to_iso = _resolve_range(from_, to)

    event_rows = _scan_range("events", "user_id,category,created_at", from_iso, to_iso)
    usage_rows = _scan_range(
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
            llm_cost_usd=round(a["llm_cost_usd"], 6),
            total_tokens=a["total_tokens"],
        )
        for uid, a in page
    ]
    return UsageByUser(
        range=Range(from_=from_iso, to=to_iso),
        total_users=len(ordered), limit=limit, offset=offset, users=users,
    )


@router.get("/llm/cost", response_model=LLMCost)
def llm_cost(
    request: Request,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    group_by: GroupBy = Query("feature"),
) -> LLMCost:
    require_admin(request)
    from_iso, to_iso = _resolve_range(from_, to)
    column = _GROUP_COLUMN[group_by]
    rows = _scan_range(
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
                total_tokens=b["total_tokens"], cost_usd=round(b["cost_usd"], 6),
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
        cost_usd=round(sum(c.cost_usd for c in cost_rows), 6),
    )
    return LLMCost(
        range=Range(from_=from_iso, to=to_iso), group_by=group_by,
        rows=cost_rows, totals=totals,
    )


@router.get("/errors", response_model=ErrorsPage)
def errors(
    request: Request,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ErrorsPage:
    require_admin(request)
    from_iso, to_iso = _resolve_range(from_, to)
    # error.* events, newest first — paginated server-side (no aggregation).
    rows, total = table("events").select_with_count(
        "created_at,event_type,request_id,user_id,payload",
        filters={"created_at": [f"gte.{from_iso}", f"lte.{to_iso}"], "event_type": "like.error.*"},
        order="created_at.desc", limit=limit, offset=offset,
    )
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
    )
