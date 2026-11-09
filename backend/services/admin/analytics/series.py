"""
backend/services/admin/analytics/series.py

Day bucketing for the admin analytics series (#121; #118: moved verbatim out
of ``routes/admin_analytics.py``). Sparse: days with no rows are omitted.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from services.admin.analytics.models import CostDayPoint, DayCount
from services.admin.analytics.scan import _as_float, _as_int
from services.llm_pricing import COST_SCALE


def _bucket_date(raw) -> str | None:
    """UTC calendar day (YYYY-MM-DD) for a created_at value; None if unparseable."""
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        # Legacy naive rows are UTC by construction (pre-#248 writes).
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).date().isoformat()


def _count_series(rows: list[dict]) -> list[DayCount]:
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        day = _bucket_date(r.get("created_at"))
        if day:
            counts[day] += 1
    return [DayCount(date=d, count=c) for d, c in sorted(counts.items())]


def _cost_series(rows: list[dict]) -> list[CostDayPoint]:
    days: dict[str, dict] = defaultdict(lambda: {"calls": 0, "total_tokens": 0, "cost_usd": 0.0})
    for r in rows:
        day = _bucket_date(r.get("created_at"))
        if not day:
            continue
        d = days[day]
        d["calls"] += 1
        d["total_tokens"] += _as_int(r.get("total_tokens"))
        d["cost_usd"] += _as_float(r.get("cost_usd"))
    return [
        CostDayPoint(date=k, calls=v["calls"], total_tokens=v["total_tokens"], cost_usd=round(v["cost_usd"], COST_SCALE))
        for k, v in sorted(days.items())
    ]
