"""
backend/services/admin/analytics/models.py

Response models for ``/api/admin/analytics`` (#118: moved verbatim out of
``routes/admin_analytics.py``, which re-exports them).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


GroupBy = Literal["user", "feature", "model"]


# Day is the only bucket the dashboard needs (#121); the Literal keeps the
# param 422-validated so a future "week"/"hour" is an explicit contract change.
Bucket = Literal["day"]


class Range(BaseModel):
    # Serialized as "from" to match the query param — the reserved word only
    # forces the underscore on the Python side, never on the wire.
    from_: str = Field(serialization_alias="from")
    to: str


class EventTypeCount(BaseModel):
    event_type: str
    count: int


class DayCount(BaseModel):
    date: str  # YYYY-MM-DD, UTC
    count: int


class CostDayPoint(BaseModel):
    date: str  # YYYY-MM-DD, UTC
    calls: int
    total_tokens: int
    cost_usd: float


class UsageSummary(BaseModel):
    range: Range
    total_events: int
    distinct_active_users: int
    by_event_type: list[EventTypeCount]
    truncated: bool = False
    # Present only when ?bucket=day. Sparse: days with no rows are omitted —
    # the client zero-fills the axis from `range`.
    series: list[DayCount] | None = None


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
    truncated: bool = False


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
    truncated: bool = False
    # Present only when ?bucket=day; sparse (see UsageSummary.series).
    series: list[CostDayPoint] | None = None


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
    # `series` needs its own range scan (the feed is paginated server-side),
    # so unlike the feed it can hit the scan cap — `truncated` refers to the
    # series only and stays False when no bucket was requested.
    truncated: bool = False
    series: list[DayCount] | None = None


#: The metrics contract's "absent, not zero" rule (#119): a NULL cost signal
#: is never a $0 — it means the window had no active users OR no priced
#: usage, so there is nothing honest to divide or compare.
_NULL_COST = "NULL when the window had no active users or no priced usage (never a $0)."


class CostWeek(BaseModel):
    week: int  # 0 = the last 7 days, 1-4 = the trailing four weeks
    from_: str = Field(validation_alias="from", serialization_alias="from")
    to: str
    usd: float | None = Field(
        description="Priced llm_usage cost in the window. NULL when it had no priced usage.")
    active_users: int
    usd_per_active_user: float | None = Field(description=_NULL_COST)


class CostPerActiveUser(BaseModel):
    """#119 / plan Targets: weekly LLM cost per active user + the 2x jump.
    Every cost field is NULL — absent, not zero — when its window had no
    active users OR no priced usage."""
    as_of: str
    threshold: float
    usd_per_active_user_7d: float | None = Field(description=_NULL_COST)
    baseline_usd_per_active_user: float | None = Field(
        description="Trailing 4-week average cost per active user. " + _NULL_COST)
    baseline_weeks: int
    ratio: float | None = Field(
        description="This week over the baseline. NULL when either side is NULL.")
    # True when this week's per-user cost is at least `threshold` times the
    # trailing 4-week average; None when either side is NULL (no active users
    # or no priced usage in that window).
    jump: bool | None = Field(
        description="ratio >= threshold. NULL when either side had no active "
                    "users or no priced usage.")
    weeks: list[CostWeek]


class DbScopeWindow(BaseModel):
    from_: str = Field(serialization_alias="from")
    to: str
    hours: int


class DbScopeGroup(BaseModel):
    event: str
    kind: str
    mode: str
    method: str
    route: str
    target: str
    op: str
    status: str | None = None
    code: str | None = None
    count: int
    users: int
    first_seen: str | None = None
    last_seen: str | None = None
    sample_request_ids: list[str]


class DbScopeReport(BaseModel):
    window: DbScopeWindow
    total: int
    groups: int
    top: list[DbScopeGroup]
    truncated: bool = False
    #: The most events one report groups (newest first); `truncated` is True
    #: when the window held more, and then `top` covers only the newest.
    scan_cap: int
    process: dict
