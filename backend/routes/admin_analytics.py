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
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Literal, NamedTuple

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from agents._providers import slot_warnings
from db.connection import page_all, pg_quote_value, table
from learning.calibration import calibration as bkt_calibration
from learning.calibration import confidence_calibration
from learning.calibration import eligible as calibration_eligible
from learning.cost_per_gain import LOOP_TASKS, cost_per_gain
from learning.earnest_revise import earnest_revise
from learning.evidence_void import is_void_row, pose_is_void
from learning.help_abuse import LOOP_SOURCE as HELP_LOOP_SOURCE
from learning.help_abuse import help_abuse as help_abuse_report
from learning.item_reports import retired_items
from learning.learning_gain import (
    due_windows,
    learning_gain,
    posttest_funnel,
    posttest_outcome,
    pretest_outcome,
    window_bounds,
)
from learning.posttest_store import posttest_anchors
from learning.params import (
    ACQ_TARGET_HI,
    ACQ_TARGET_LO,
    BAND_WINDOW,
    GATE_CEILING_COMPLIANCE_MIN,
    GATE_LEAKS_MAX,
    KPI_TREND_WEEKS,
    LADDER_MAX_RUNG,
    PRACTICE_TARGET_HI,
    PRACTICE_TARGET_LO,
    PROBE_TARGET_HI,
    PROBE_TARGET_LO,
)
from learning.probe import probe_history_hashes
from services.academics import offering_course_id
from services.auth_guard import require_admin
from services.quiz_ask import quiz_ask_session_ids
from services.events_service import SYSTEM_CATEGORY
from services.llm_pricing import COST_SCALE

logger = logging.getLogger("sapling.admin_analytics")

router = APIRouter()

# Page size for range scans, and a hard ceiling so a pathological range can't
# pull unbounded rows into memory. Hitting the cap is logged and surfaced via
# the response's `truncated` flag, never silent.
_PAGE = 1000
_SCAN_CAP = 100_000

GroupBy = Literal["user", "feature", "model"]
_GROUP_COLUMN = {"user": "user_id", "feature": "feature", "model": "model"}

# Day is the only bucket the dashboard needs (#121); the Literal keeps the
# param 422-validated so a future "week"/"hour" is an explicit contract change.
Bucket = Literal["day"]


# ── Response models ──────────────────────────────────────────────────────────


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


# ── Date range helpers ───────────────────────────────────────────────────────


def _resolve_range(from_: str | None, to: str | None) -> tuple[str, str]:
    """Default to the last 30 days; echo caller-supplied ISO bounds otherwise.

    Bounds are validated before use: each must parse as ISO 8601 (422 naming
    the bad param otherwise) and `from` must not be after `to`. The strings are
    returned as supplied — validation never reformats them.
    """
    now = datetime.now(timezone.utc)
    to_iso = to or now.isoformat()
    from_iso = from_ or (now - timedelta(days=30)).isoformat()

    def _parse(param: str, value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid {param!r} datetime: {value!r} is not ISO 8601",
            )
        # Treat naive bounds as UTC so mixed naive/aware bounds stay comparable.
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    from_dt = _parse("from", from_iso)
    to_dt = _parse("to", to_iso)
    if from_dt > to_dt:
        raise HTTPException(status_code=422, detail="'from' must not be after 'to'")
    return from_iso, to_iso


#: Usage rollups count what users DID. Server-emitted rows about their
#: requests (category "system", e.g. decision.made per routed chat turn) are
#: excluded, or every routed turn would count twice toward a user's activity.
_NOT_SYSTEM = {"category": f"neq.{SYSTEM_CATEGORY}"}


def _scan_range(
    table_name: str, columns: str, from_iso: str, to_iso: str,
    extra_filters: dict | None = None,
    *,
    time_column: str = "created_at",
    order: str | None = None,
) -> tuple[list[dict], bool]:
    """Fetch every row in [from, to] for a table, paging via select_with_count.

    Aggregation endpoints need the full (date-bounded) set — PostgREST won't
    GROUP BY for us — so we page to completion rather than relying on the
    server's default row cap. Returns ``(rows, truncated)``: a range large
    enough to hit _SCAN_CAP stops the scan early, logs a warning, and sets
    ``truncated=True`` so callers can surface the partial aggregation.
    `time_column` is the timestamp the range bounds (``created_at`` unless a
    table has none); `order` defaults to it, ascending.
    """
    out: list[dict] = []
    offset = 0
    truncated = False
    while True:
        filters: dict = {time_column: [f"gte.{from_iso}", f"lte.{to_iso}"]}
        if extra_filters:
            filters.update(extra_filters)
        rows, total = table(table_name).select_with_count(
            columns, filters=filters, order=order or f"{time_column}.asc", limit=_PAGE, offset=offset,
        )
        out.extend(rows)
        if len(out) >= total or not rows:
            break
        if len(out) >= _SCAN_CAP:
            truncated = True
            logger.warning(
                "admin_analytics scan hit cap %d on %r (total=%d); results truncated",
                _SCAN_CAP, table_name, total,
            )
            break
        offset += _PAGE
    return out, truncated


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


# ── Day bucketing (#121) ─────────────────────────────────────────────────────


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


# ── Learning loop KPIs (PKG-14; spec §10) ────────────────────────────────────
#
# The three headline KPIs and the two measurable gates of the evaluation
# ladder, over `zpd.step`/`zpd.leak` events and the evidence journal. Admin-only
# and read-only like every endpoint here. The earnest-revise gate (spec §10) is
# measured since spec §13 A109: the feedback zpd.step's `earnest_blocked` bool.

_STEP_EVENT = "zpd.step"
_LEAK_EVENT = "zpd.leak"
_REVEAL_EVENT = "zpd.reveal"  # spec §13 A88 (m5): a solution SERVED for an open posed item
#: spec §13 A123: the check item and the node's course name the course item a
#: row was graded against — what the void rule (learning/evidence_void.py) keys on
_EVIDENCE_COLS = (
    "id,node_id,session_id,correct,assisted,max_rung,question_hash,created_at,"
    "channel,p_before,weight,check_item_id,"
    # spec §13 A127: the student's stated confidence (metacognitive calibration)
    "student_confidence,"
    "graph_nodes!inner(course_id)"
)
TrendDirection = Literal["falling", "flat", "rising", "insufficient"]


class WeekPoint(BaseModel):
    week_start: str  # the Monday of the ISO week, YYYY-MM-DD (UTC)
    mean_rung: float  # mean max_rung_used over the week's correct steps
    steps: int


class ConceptTrend(BaseModel):
    concept_id: str
    weeks: list[WeekPoint]
    direction: TrendDirection


class CeilingCompliance(BaseModel):
    steps: int
    compliant: int
    rate: float | None


class NextSessionSuccess(BaseModel):
    sessions: int
    successes: int
    rate: float | None
    # spec §13 A106 (review m2): quiz-ask sessions (probe-less) left out of the rate
    quiz_ask_excluded: int = 0


class EarnestRevise(BaseModel):
    """Spec §10's earnest-revise gate (A109): graded check steps whose /hint was
    denied at the ceiling or the H6 gate after a genuine attempt."""

    graded_steps: int  # check steps carrying the earnest_blocked bool
    earnest_blocked: int
    unmeasured_steps: int  # check steps written before A109 (no key): not counted
    rate: float | None
    gate: Literal["pass", "fail", "inconclusive"]


class Gates(BaseModel):
    zero_leaks: bool
    ceiling_compliance_ok: bool
    # A109: None = inconclusive (no graded step carries the signal), never a pass
    earnest_revise_ok: bool | None


class CalibrationBin(BaseModel):
    lo: float
    hi: float
    n: int
    mean_predicted: float | None
    observed: float | None


class CalibrationReport(BaseModel):
    """BKT's predicted P(correct) vs observed outcomes on independent
    (strong-channel, unassisted, rung-0, full-weight) evidence
    (learning/calibration.py). None rates mean nothing to judge."""

    n: int
    brier: float | None
    mean_predicted: float | None
    observed_rate: float | None
    ece: float | None
    bins: list[CalibrationBin]


class Calibration(BaseModel):
    all: CalibrationReport
    posttest: CalibrationReport  # rung 3: fresh reserve item, tool-free, delayed
    # spec §13 A123: independent observations left out because they were
    # graded against an item staff retired (void evidence) — the drop, visible
    excluded_void: int = 0


class ConfidenceLevel(BaseModel):
    """One stated-confidence level (learning/calibration.py, spec §13 A127)."""

    level: str | None  # a STUDENT_CONFIDENCE_LEVELS label; None = a value no label names
    stated: float  # the level's value on the 0..1 scale
    n: int
    correct: int
    observed: float | None  # None when n = 0, never a zero


class ConfidenceReport(BaseModel):
    """The student's stated confidence against correctness (metacognitive
    calibration, spec §13 A127). None rates mean nothing to judge."""

    n: int
    mean_stated: float | None
    observed_rate: float | None
    overconfidence: float | None  # mean stated − observed; above 0 = surer than right
    brier: float | None
    levels: list[ConfidenceLevel]


class ChannelConfidenceReport(ConfidenceReport):
    channel: str


class ConfidenceCalibration(BaseModel):
    all: ConfidenceReport
    channels: list[ChannelConfidenceReport]  # only channels with a stated confidence


class GainSummary(BaseModel):
    """Pre/post outcomes over (student, concept) pairs (learning/learning_gain.py,
    spec §13 A112): the probe's unassisted pretest against the unassisted
    post-test. Observed outcomes only — never p_known. None rates: n = 0."""

    n: int
    pre_correct_rate: float | None
    post_correct_rate: float | None
    paired_difference: float | None  # mean(post − pre) over the pairs, in [−1, 1]
    improved: int  # pretest wrong → post-test right
    same: int
    worse: int  # pretest right → post-test wrong


class GainWindow(GainSummary):
    window_days: int  # a POSTTEST_WINDOWS_DAYS window
    posttests: int  # unassisted post-test outcomes in the window, paired or not
    # unassisted outcomes left out because staff retired their item (A113/A123:
    # retired as broken, so the outcome is void evidence) — the drop, visible
    excluded_retired: int
    # A126: the students behind the pairs, and the student-cluster bootstrap
    # percentile intervals ([lo, hi]; None below two students)
    students: int
    post_correct_ci: list[float] | None
    paired_difference_ci: list[float] | None
    delayed: GainSummary  # the pairs with no evidence for ≥ delayed_min_days before the pose
    # A126: the pairs whose page was hidden while the item was on screen (nothing
    # is excluded for it), and the outcomes with no visibility record
    visibility_loss: GainSummary
    visibility_unreported: int


class GainCi(BaseModel):
    """How the intervals were computed (A126) — enough to reproduce them."""

    method: str
    level: float
    resamples: int
    seed: str


class DelayBin(GainSummary):
    """Every window's pairs by the days from the anchor to the answer (A126)."""

    lo_days: int
    hi_days: int | None  # None: open-ended
    posttests: int


class FunnelWindow(BaseModel):
    """What happened to the windows that opened in the range (A126): every due
    window is answered, expired, open, skipped (by reason) or never opened;
    `still_open` counts the unanswered ones whose window has not closed."""

    window_days: int
    due: int
    opened: int
    answered: int
    unassisted: int
    excluded_retired: int  # answered on an item staff retired (A123): void
    expired: int
    open: int
    skipped: int
    skip_reasons: dict[str, int]
    not_opened: int
    still_open: int


class LearningGain(BaseModel):
    """Post-tests answered in the range, per fixed window (A112), with their
    uncertainty, actual delay and visibility (A126), and the funnel of the
    windows that opened in the range (None: the anchors could not be read)."""

    delayed_min_days: int
    ci: GainCi
    windows: list[GainWindow]
    delay_bins: list[DelayBin]
    delay_unknown: int
    delay_out_of_range: int
    funnel: list[FunnelWindow] | None


class CostWindow(BaseModel):
    """One post-test window's pairs against the range's loop spend (A137).
    Intervals are [lo, hi] with hi None when unbounded; None below two students."""

    window_days: int
    pairs: int
    students: int
    gain_points: int  # improved − worse: Σ(post − pre) over the pairs
    per_pair: float | None
    per_pair_ci: list[float | None] | None
    per_gain_point: float | None  # None unless gain_points > 0
    per_gain_point_ci: list[float | None] | None


class CostBlock(BaseModel):
    """The loop's spend, overall (course_id None) or for one course (A137)."""

    course_id: str | None
    cost_usd: float
    tutor_usd: float  # the tutor tiers: what §3.5's target prices
    drafting_usd: float  # check-item drafting and its checks (course assets)
    rows: int
    unpriced_rows: int  # rows with no cost_usd (an unpriced model): no dollars added
    active_students: int
    per_active_student_month: float | None
    tutor_per_active_student_month: float | None
    target_ratio: float | None  # per_active_student_month ÷ the §3.5 target
    sessions: int
    per_session: float | None  # the rows that carry a session, per session
    windows: list[CostWindow]


class CostUnattributed(BaseModel):
    cost_usd: float
    rows: int


class CostPerGain(BaseModel):
    """What the loop cost against what it measurably taught (spec §13 A137,
    learning/cost_per_gain.py): the loop tasks' llm_usage spend in the range,
    check-item drafting included, beside the learning-gain pairs answered in
    it, overall and per course. Every figure has its n; None means nothing to
    divide by, never zero. A row with no course of its own and no session is
    `unattributed` (overall only)."""

    target_usd_per_student_month: float
    range_days: float | None
    ci: GainCi
    overall: CostBlock
    courses: list[CostBlock]
    unattributed: CostUnattributed


class SlotWarning(BaseModel):
    """Spec §13 A128: an evidence-producing model slot this API process runs
    outside its evaluated set (`unevaluated`: reason pending_claude_eval |
    not_evaluated), or resolved to the model it must be independent of
    (`not_independent`: A22's second opinion, A124's key solve). The process's
    CURRENT configuration, not the date range: warnings are about now."""

    kind: Literal["unevaluated", "not_independent"]
    slot: str
    model: str
    reason: str | None = None
    independent_of: str | None = None
    rule: str | None = None


class HelpMedian(BaseModel):
    n: int
    median: float | None  # seconds; None when n = 0, never a zero


class HelpAttempts(BaseModel):
    """Counted hint-unlocking attempts and their signals (zpd.attempt, A134)."""

    counted: int
    rapid: int  # less than the band's independent time alone with the latest help
    repeat: int  # said nothing a counted attempt on the item had not said
    strict_refused: int  # under the strict gate: refused, though the §3.3 rule counted it


class BottomOutAttempts(BaseModel):
    """The counted attempts that bought a bottom-out's climb (below H5)."""

    measured: int
    unmeasured: int  # no attempt record (a step before A134): never a zero
    held_by_strict: int  # one climb attempt or more the strict rule would not count
    no_strict_attempt: int  # no climb attempt the strict rule would count


class HelpNextOutcome(BaseModel):
    """The next graded opportunity on the concept with another item."""

    graded: int  # steps with a graded, non-void evidence row in the range
    unassisted_correct: int
    other: int
    none: int  # no later opportunity in the range


class HelpAbuseGroup(BaseModel):
    key: str
    steps: int  # loop check items posed (student × session × item)
    bottom_outs: int
    full_solutions: int
    bottom_out_rate: float | None
    time_to_bottom_out_s: HelpMedian
    help_gap_s: HelpMedian
    climb_gap_s: HelpMedian
    attempts: HelpAttempts
    bottom_out_attempts: BottomOutAttempts
    next: dict[str, HelpNextOutcome]  # by the step's help: none / partial / bottom_out


class HelpAbuse(BaseModel):
    """Spec §13 A133: help abuse, measured (learning/help_abuse.py)."""

    bottom_out_rung: int
    overall: HelpAbuseGroup
    by_band: list[HelpAbuseGroup]
    by_gate: list[HelpAbuseGroup]
    by_course: list[HelpAbuseGroup]
    by_student: list[HelpAbuseGroup]
    truncated: bool = False


class LearningLoopKpis(BaseModel):
    range: Range
    steps_total: int
    banded_steps: int
    in_band: int
    in_band_share: float | None
    htc_k_trend: list[ConceptTrend]
    unassisted_next_session: NextSessionSuccess
    # m5 (spec §13 A90): zpd.leak is a leak CAUGHT on the active item and
    # redacted before serving; the gate counts solutions actually SERVED
    caught_leaks: int
    served_reveals: int  # open posed items whose answer a served turn stated
    unscanned_turns: int  # served turns whose open items could not be read (fail-closed)
    ceiling_compliance: CeilingCompliance
    earnest_revise: EarnestRevise
    gates: Gates
    calibration: Calibration
    # spec §13 A127: do students know what they know? stated confidence vs correctness
    confidence_calibration: ConfidenceCalibration
    learning_gain: LearningGain
    # A137: the loop's spend against the learning gain; None when the spend
    # could not be read (the rest of the report stands)
    cost_per_gain: CostPerGain | None = None
    # A128: the active evidence-slot warnings ([] when none; never blocking)
    slot_warnings: list[SlotWarning] = Field(default_factory=list)
    # spec §13 A133: help abuse — None when its reads failed (the rest stands)
    help_abuse: HelpAbuse | None = None
    truncated: bool = False


def _rung_int(value) -> int | None:
    """A rung's wire form ("H3", "h0" or 3, HANDOFF-06) as an int, None when it
    is not a rung (a bool, an unknown string, out of H0..H6)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        n = value
    elif isinstance(value, str) and value[:1] in ("H", "h") and value[1:].isdigit():
        n = int(value[1:])
    else:
        return None
    return n if 0 <= n <= LADDER_MAX_RUNG else None


def _phase_band(phase, assisted) -> tuple[float, float] | None:
    """The phase band a step's rolling success rate is judged against (spec §3.3):
    probe → PROBE_TARGET, assisted check → ACQ_TARGET, unassisted check →
    PRACTICE_TARGET; every other phase has no band."""
    if phase == "probe":
        return (PROBE_TARGET_LO, PROBE_TARGET_HI)
    if phase == "check":
        return (ACQ_TARGET_LO, ACQ_TARGET_HI) if assisted else (PRACTICE_TARGET_LO, PRACTICE_TARGET_HI)
    return None


def _payload(row: dict) -> dict:
    p = row.get("payload")
    return p if isinstance(p, dict) else {}


def _step_kind(p: dict) -> str | None:
    phase = p.get("phase")
    if phase == "probe":
        return "probe"
    if phase == "check":
        return "check-assisted" if p.get("assisted") else "check-unassisted"
    return None


def _in_band_share(steps: list[dict]) -> tuple[int, int]:
    """(in_band, banded_steps): per (user_id, concept_id) in created_at order, a
    step of a banded kind with at least BAND_WINDOW earlier steps of the SAME
    kind is judged by the first-attempt success rate over those BAND_WINDOW."""
    history: dict[tuple, list[bool]] = defaultdict(list)
    in_band = banded = 0
    for row in sorted(steps, key=lambda r: str(r.get("created_at") or "")):
        p = _payload(row)
        kind = _step_kind(p)
        if kind is None:
            continue
        prior = history[(row.get("user_id"), p.get("concept_id"), kind)]
        if len(prior) >= BAND_WINDOW:
            window = prior[-BAND_WINDOW:]
            rate = sum(window) / len(window)
            lo, hi = _phase_band(p.get("phase"), p.get("assisted"))
            banded += 1
            in_band += int(lo <= rate <= hi)
        prior.append(p.get("first_attempt_correct") is True)
    return in_band, banded


def _parse_ts(raw) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _week_start(ts: datetime):
    iso = ts.isocalendar()
    return date.fromisocalendar(iso.year, iso.week, 1)


def _step_correct(p: dict) -> bool:
    """A step that ended correct: first attempt correct, or a time to correct."""
    return p.get("first_attempt_correct") is True or p.get("time_to_correct_ms") is not None


def _htc_k_trend(steps: list[dict], to_iso: str) -> list[ConceptTrend]:
    """Per concept, mean max_rung_used over its correct steps per ISO week, for
    the KPI_TREND_WEEKS weeks ending at `to` (hints-to-criterion must fall)."""
    to_dt = _parse_ts(to_iso)
    last = _week_start(to_dt) if to_dt else None
    first = last - timedelta(weeks=KPI_TREND_WEEKS - 1) if last else None
    rungs: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    for row in steps:
        p = _payload(row)
        concept = p.get("concept_id")
        rung = _rung_int(p.get("max_rung_used"))
        ts = _parse_ts(row.get("created_at"))
        if not concept or rung is None or ts is None or not _step_correct(p):
            continue
        week = _week_start(ts)
        if first is None or not (first <= week <= last):
            continue
        rungs[str(concept)][week].append(rung)
    out = []
    for concept in sorted(rungs):
        weeks = [
            WeekPoint(week_start=w.isoformat(), mean_rung=sum(v) / len(v), steps=len(v))
            for w, v in sorted(rungs[concept].items())
        ]
        if len(weeks) < 2:
            direction: TrendDirection = "insufficient"
        elif weeks[-1].mean_rung < weeks[0].mean_rung:
            direction = "falling"
        elif weeks[-1].mean_rung > weeks[0].mean_rung:
            direction = "rising"
        else:
            direction = "flat"
        out.append(ConceptTrend(concept_id=concept, weeks=weeks, direction=direction))
    return out


def _next_session_rate(evidence_rows: list[dict], quiz_ask: set[str] | frozenset = frozenset()) -> dict:
    """Unassisted next-opportunity success on the FOLLOWING session's first item:
    per node, its sessions in order of their first evidence row; for every
    session after the first, its first row is a success when it is correct,
    unassisted and at rung 0. Rows with no session_id (post-test, quiz) are
    not a session, and neither is a quiz-ask session (spec §13 A106: it skips
    the probe and opens on the concept just asked about) — those are counted
    in `quiz_ask_excluded`."""
    by_node: dict[str, dict[str, dict]] = defaultdict(dict)
    excluded: set[str] = set()
    for row in sorted(
        evidence_rows, key=lambda r: (str(r.get("created_at") or ""), str(r.get("id") or ""))
    ):
        session = row.get("session_id")
        if not session or not row.get("node_id"):
            continue
        if session in quiz_ask:
            excluded.add(session)
            continue
        by_node[row["node_id"]].setdefault(session, row)  # the session's first row
    sessions = successes = 0
    for firsts in by_node.values():
        for row in list(firsts.values())[1:]:
            sessions += 1
            successes += int(
                row.get("correct") is True
                and not row.get("assisted")
                and _rung_int(row.get("max_rung")) == 0
            )
    return {
        "sessions": sessions,
        "successes": successes,
        "rate": successes / sessions if sessions else None,
        "quiz_ask_excluded": len(excluded),
    }


#: spec §13 A112: an answered post-test pose — its window, its recorded outcome,
#: its anchor (the concept's first evidence row), the delay it had, and the
#: course item it asked (what an A113 retire is keyed on); A126: the anchor's
#: time (the actual delay) and the page-hidden telemetry (the visibility stratum)
_POSE_COLS = (
    "user_id,node_id,window_days,answered_at,correct,max_rung,anchor_event_id,anchor_at,"
    "days_since_evidence,course_id,question_hash,hidden_count,hidden_s"
)
#: A126: what the funnel classifies a due window's pose and skip by
#: A123: course_id and question_hash name the item the void rule keys on
_FUNNEL_POSE_COLS = (
    "user_id,node_id,window_days,posed_at,answered_at,correct,max_rung,course_id,question_hash"
)
_FUNNEL_SKIP_COLS = "user_id,node_id,window_days,reason"
#: an anchor row, with what learning_gain.pretest_outcome binds its envelope to
_ANCHOR_COLS = (
    "id,node_id,session_id,question_hash,check_item_id,channel,correct,assisted,max_rung,"
    "reason,planning_observation"
)
#: ids per `in.(…)` read, so a GET URL stays well under common proxy limits
_IN_BATCH = 100


def _in(values: list[str]) -> str:
    return f"in.({','.join(pg_quote_value(v) for v in values)})"


def _batches(values: list[str]):
    for start in range(0, len(values), _IN_BATCH):
        yield values[start : start + _IN_BATCH]


def _pretests(poses: list[dict], retired: set[tuple[str, str]] = frozenset()) -> dict[str, bool]:
    """A112: anchor event id → the concept's pretest outcome
    (learning_gain.pretest_outcome), for the poses with an unassisted outcome.
    Two bounded reads: their anchor rows (each concept's first evidence) by id,
    then the probe histories of those rows' sessions — planning provenance tags
    the loop's in-session checks too, so only the session's probe history says
    a row was a probe grade. A123: an anchor graded against an item staff
    retired is void evidence — no pretest (the void rule, keyed on the pose's
    course)."""
    course_of = {
        str(p["anchor_event_id"]): p.get("course_id")
        for p in poses
        if p.get("anchor_event_id") and posttest_outcome(p) is not None
    }
    ids = sorted(course_of)
    anchors: list[dict] = []
    for batch in _batches(ids):
        anchors += (
            table("node_mastery_events").select(
                _ANCHOR_COLS, filters={"id": _in(batch), "event_type": "eq.evidence"}
            )
            or []
        )
    anchors = [
        row for row in anchors
        if not is_void_row(row, retired, course_of.get(str(row.get("id"))))
    ]
    sessions = sorted({str(r["session_id"]) for r in anchors if r.get("session_id")})
    probed: dict[str, set[str]] = {}
    for batch in _batches(sessions):
        for row in table("sessions").select(
            "id,history:loop_state->probe->history", filters={"id": _in(batch)}
        ) or []:
            probed[str(row.get("id"))] = probe_history_hashes(row.get("history"))
    out: dict[str, bool] = {}
    for row in anchors:
        outcome = pretest_outcome(row, probed.get(str(row.get("session_id")), set()))
        if outcome is not None and row.get("id"):
            out[str(row["id"])] = outcome
    return out


def _void_items(
    evidence: list[dict], poses: list[dict], funnel_poses: Iterable[dict] = ()
) -> set[tuple[str, str]]:
    """Spec §13 A123 — the ONE rule every report here applies: an observation
    graded against a check item STAFF retired is void (learning/evidence_void.py).
    The staff-retired course items, as (course_id, question_hash) — the
    structured record (`check_item_reviews`, status 'retired'), never an item
    row being gone (A23's consent withdrawal and A119's re-key delete rows too,
    and that evidence stands); a quarantine, a report or an approval is no
    retire. Read only when there is an observation to judge — a scanned
    evidence row, an answered post-test in the range, or an answered pose of
    the A126 funnel: ONE paged, status-filtered read (retired items are staff
    decisions, so few)."""
    if (
        not evidence
        and not any(posttest_outcome(p) is not None for p in poses)
        and not any(p.get("answered_at") for p in funnel_poses)
    ):
        return set()
    return retired_items()


class _FunnelReads(NamedTuple):
    """What the A126 funnel classifies: the due windows, their poses and the
    recorded skips, keyed (user_id, node_id, window_days)."""

    due: list[dict]
    poses: dict[tuple, dict]
    skips: dict[tuple, str]
    truncated: bool


def _funnel_reads(from_iso: str, to_iso: str) -> _FunnelReads | None:
    """A126: the reads behind the funnel of the post-test windows that OPENED
    in the range (learning_gain.due_windows over every concept's anchor;
    posttest_funnel classifies each, after the one retired read). Reads: the
    anchors in the one range any window could open from (the
    `posttest_anchors` SQL function, keyset-paged, capped at _SCAN_CAP — the
    cap sets `truncated`), then the poses and the recorded skips of the
    students those windows belong to (user ids per `in.(…)`, paged). None
    when a read failed — the funnel is then unknown, never zeros that read as
    "nothing was due"."""
    start, end = _parse_ts(from_iso), _parse_ts(to_iso)
    if start is None or end is None:
        return None
    opens = [o for _, o, _ in window_bounds()]
    try:
        anchors, truncated = posttest_anchors(
            anchor_from=start - timedelta(days=max(opens)),
            anchor_to=end - timedelta(days=min(opens)),
            limit=_SCAN_CAP,
        )
        due = due_windows(anchors, start=start, end=end)
        users = sorted({d["user_id"] for d in due})
        poses: dict[tuple, dict] = {}
        skips: dict[tuple, str] = {}
        for batch in _batches(users):
            for row in page_all(
                table("posttest_poses"),
                _FUNNEL_POSE_COLS,
                filters={"user_id": _in(batch)},
                order="user_id.asc,node_id.asc,window_days.asc",
            ):
                poses[(row.get("user_id"), row.get("node_id"), row.get("window_days"))] = row
            for row in page_all(
                table("posttest_skips"),
                _FUNNEL_SKIP_COLS,
                filters={"user_id": _in(batch)},
                order="user_id.asc,node_id.asc,window_days.asc",
            ):
                skips[(row.get("user_id"), row.get("node_id"), row.get("window_days"))] = row.get("reason")
    except Exception:
        logger.warning("learning-gain funnel unavailable", exc_info=True)
        return None
    return _FunnelReads(due, poses, skips, truncated)


_ATTEMPT_EVENT = "zpd.attempt"  # spec §13 A133/A134: one hint-unlocking attempt, as judged
#: spec §13 A133: the help ledger's loop rows (learning/help_ledger.py) — poses and help
_LEDGER_COLS = "id,user_id,kind,question_hash,rung,session_id,source,at"


def _session_courses(session_ids: Iterable[str]) -> dict[str, str]:
    """Session id → abstract course id (the session's offering's course),
    for the sessions that have one: bounded `in.(...)` reads of `sessions`,
    then services.academics.offering_course_id per distinct offering (cached)."""
    ids = sorted({str(s) for s in session_ids if s})
    offering: dict[str, str] = {}
    for batch in _batches(ids):
        for row in table("sessions").select("id,offering_id", filters={"id": _in(batch)}) or []:
            if row.get("id") and row.get("offering_id"):
                offering[str(row["id"])] = str(row["offering_id"])
    course = {o: offering_course_id(o) for o in set(offering.values())}
    return {sid: course[o] for sid, o in offering.items() if course.get(o)}


def _help_abuse(
    events: list[dict], steps: list[dict], valid: list[dict], from_iso: str, to_iso: str
) -> HelpAbuse | None:
    """Spec §13 A133 over the range: the help ledger's loop poses and help in
    it, the zpd.attempt / zpd.step events and the non-void evidence the
    endpoint already scanned, and the sessions' courses. Additive: a failed
    read logs a WARNING and answers None — the rest of the report stands."""
    try:
        ledger, truncated = _scan_range(
            "learning_reveals",
            _LEDGER_COLS,
            from_iso,
            to_iso,
            extra_filters={"kind": "in.(posed,help)", "source": f"eq.{HELP_LOOP_SOURCE}"},
            time_column="at",
            order="at.asc,id.asc",
        )
        courses = _session_courses(r.get("session_id") for r in ledger if r.get("kind") == "posed")
        attempts = [e for e in events if e.get("event_type") == _ATTEMPT_EVENT]
        return HelpAbuse(
            **help_abuse_report(ledger, attempts, steps, valid, courses), truncated=truncated
        )
    except Exception:
        logger.warning("admin learning-loop: the help-abuse report could not be built", exc_info=True)
        return None


#: A137: the llm_usage columns the cost report reads (course_id from
#: 20261108163653; a database before it is read without the column)
_USAGE_COST_COLS = "id,task,cost_usd,user_id,session_id,course_id,created_at"


class _CostRead(NamedTuple):
    report: CostPerGain | None
    truncated: bool


def _http_error_text(exc: BaseException) -> str:
    """The message plus, for db.connection's httpx.HTTPStatusError, its body."""
    try:
        return f"{exc} {exc.response.text}"  # type: ignore[attr-defined]
    except Exception:
        return str(exc)


def _range_days(from_iso: str, to_iso: str) -> float | None:
    def parse(value: str) -> datetime:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

    try:
        return (parse(to_iso) - parse(from_iso)).total_seconds() / 86400
    except ValueError:
        return None


def _cost_per_gain(
    from_iso: str, to_iso: str, poses: list[dict], pretests: dict[str, bool], retired
) -> _CostRead:
    """A137: the loop tasks' llm_usage rows in the range (one paged read,
    task-filtered), the courses of the sessions behind rows that name no course
    of their own (sessions by id in `in.(…)` batches, offering → course), and
    learning/cost_per_gain.py over them and the learning gain's own inputs.
    Any read failure leaves the field None (one WARNING), never the report."""
    filters = {"task": f"in.({','.join(LOOP_TASKS)})"}
    order = "created_at.asc,id.asc"
    try:
        try:
            usage, truncated = _scan_range(
                "llm_usage", _USAGE_COST_COLS, from_iso, to_iso, extra_filters=filters, order=order
            )
        except Exception as exc:
            if "course_id" not in _http_error_text(exc):
                raise
            logger.warning(
                "admin_analytics: llm_usage has no course_id column (migration "
                "20261108163653 not applied?); session-less loop spend is unattributed"
            )
            usage, truncated = _scan_range(
                "llm_usage",
                _USAGE_COST_COLS.replace(",course_id", ""),
                from_iso,
                to_iso,
                extra_filters=filters,
                order=order,
            )
        sessions = sorted(
            {str(r["session_id"]) for r in usage if r.get("session_id") and not r.get("course_id")}
        )
        session_courses: dict[str, str] = {}
        for batch in _batches(sessions):
            for row in table("sessions").select("id,offering_id", filters={"id": _in(batch)}) or []:
                course = offering_course_id(row.get("offering_id") or "")
                if course:
                    session_courses[str(row.get("id"))] = course
        report = cost_per_gain(
            usage,
            session_courses,
            poses,
            pretests,
            range_days=_range_days(from_iso, to_iso),
            retired=retired,
        )
        return _CostRead(CostPerGain(**report), truncated)
    except Exception:
        logger.warning("admin_analytics: the loop's spend could not be read", exc_info=True)
        return _CostRead(None, False)


def _ceiling_compliance(steps: list[dict]) -> CeilingCompliance:
    n = ok = 0
    for row in steps:
        p = _payload(row)
        used, ceiling = _rung_int(p.get("max_rung_used")), _rung_int(p.get("ceiling"))
        if used is None or ceiling is None:
            continue
        n += 1
        ok += int(used <= ceiling)
    return CeilingCompliance(steps=n, compliant=ok, rate=ok / n if n else None)


@router.get("/learning-loop", response_model=LearningLoopKpis)
def learning_loop_kpis(
    request: Request,
    response: Response,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
) -> LearningLoopKpis:
    """Spec §10: in-band share, the htc_k trend, next-session unassisted success,
    and the zero-leak, ceiling-compliance and earnest-revise (A109) gates; the
    BKT calibration (A110), the students' own confidence calibration per
    channel (A127: stated confidence vs correctness, over the same evidence
    scan) and the pre/post learning gain of the post-tests answered in the
    range, per fixed window (A112), with its student-cluster bootstrap
    intervals, actual-delay bins and visibility-loss stratum, and the funnel
    of the windows that opened in the range (A126). One void rule (A123) for
    every evidence read here: an observation graded against an item staff
    retired is left out — of the BKT calibration (counted in `excluded_void`),
    the confidence calibration, the next-session success, the learning gain's
    post-tests (counted per window in `excluded_retired`) and its pretests;
    the active evidence-slot warnings of this process's configuration (A128);
    help abuse (A133: bottom-outs, their pace, the attempts that bought them
    and what the student did next, per band, gate, course and student — None
    when its reads failed); the loop's spend in the range against those
    learning-gain pairs, overall and per course (A137: per active student-month
    against §3.5's target, per session, per pair and per gain point, each with
    its n); `truncated: true` means a scan cap cut the aggregation short."""
    require_admin(request)
    response.headers["Cache-Control"] = "private"
    from_iso, to_iso = _resolve_range(from_, to)
    events, events_truncated = _scan_range(
        "events",
        "event_type,user_id,payload,created_at",
        from_iso,
        to_iso,
        extra_filters={
            "event_type": f"in.({_STEP_EVENT},{_LEAK_EVENT},{_REVEAL_EVENT},{_ATTEMPT_EVENT})"
        },
    )
    evidence, evidence_truncated = _scan_range(
        "node_mastery_events",
        _EVIDENCE_COLS,
        from_iso,
        to_iso,
        extra_filters={"event_type": "eq.evidence"},
    )
    poses, poses_truncated = _scan_range(  # A112: post-test outcomes answered in the range
        "posttest_poses",
        _POSE_COLS,
        from_iso,
        to_iso,
        time_column="answered_at",
        order="answered_at.asc,user_id.asc,node_id.asc,window_days.asc",
    )
    quiz_ask = quiz_ask_session_ids(table("sessions"), to_iso=to_iso)  # A106
    steps = [e for e in events if e.get("event_type") == _STEP_EVENT]
    caught = sum(1 for e in events if e.get("event_type") == _LEAK_EVENT)
    reveals = [_payload(e) for e in events if e.get("event_type") == _REVEAL_EVENT]
    served = sum(len(p.get("question_hashes") or []) for p in reveals)
    unscanned = sum(1 for p in reveals if p.get("unscanned") is True)
    in_band, banded = _in_band_share(steps)
    compliance = _ceiling_compliance(steps)
    earnest = EarnestRevise(**earnest_revise(steps))
    funnel_reads = _funnel_reads(from_iso, to_iso)  # A126
    # A123: ONE void rule for every evidence read — graded against an item
    # staff retired. An outcome on one is excluded (and counted), so its anchor
    # is never read for a pretest; a void anchor is no pretest; an answered
    # funnel pose on one is counted as excluded, never as answered.
    retired = _void_items(
        evidence, poses, funnel_reads.poses.values() if funnel_reads is not None else ()
    )
    valid = [row for row in evidence if not is_void_row(row, retired)]
    excluded_void = sum(
        1 for row in evidence if is_void_row(row, retired) and calibration_eligible(row) is not None
    )
    pretests = _pretests([p for p in poses if not pose_is_void(p, retired)], retired)
    funnel = (
        posttest_funnel(
            funnel_reads.due,
            funnel_reads.poses,
            funnel_reads.skips,
            now=datetime.now(timezone.utc),
            retired=retired,
        )
        if funnel_reads is not None
        else None
    )
    funnel_truncated = funnel_reads.truncated if funnel_reads is not None else False
    # spec §13 A133: help abuse, over the same events and non-void evidence
    help_abuse = _help_abuse(events, steps, valid, from_iso, to_iso)
    cost = _cost_per_gain(from_iso, to_iso, poses, pretests, retired)  # A137
    return LearningLoopKpis(
        range=Range(from_=from_iso, to=to_iso),
        steps_total=len(steps),
        banded_steps=banded,
        in_band=in_band,
        in_band_share=in_band / banded if banded else None,
        htc_k_trend=_htc_k_trend(steps, to_iso),
        unassisted_next_session=NextSessionSuccess(**_next_session_rate(valid, quiz_ask)),
        caught_leaks=caught,
        served_reveals=served,
        unscanned_turns=unscanned,
        ceiling_compliance=compliance,
        earnest_revise=earnest,
        gates=Gates(
            zero_leaks=served <= GATE_LEAKS_MAX,
            ceiling_compliance_ok=compliance.rate is not None
            and compliance.rate >= GATE_CEILING_COMPLIANCE_MIN,
            earnest_revise_ok=None if earnest.gate == "inconclusive" else earnest.gate == "pass",
        ),
        calibration=Calibration(**bkt_calibration(valid), excluded_void=excluded_void),
        # A123 × A127: the one void rule here too — a confidence stated on a
        # grade against a retired item is no calibration evidence either
        confidence_calibration=ConfidenceCalibration(**confidence_calibration(valid)),
        learning_gain=LearningGain(**learning_gain(poses, pretests, retired=retired), funnel=funnel),
        cost_per_gain=cost.report,
        slot_warnings=[SlotWarning(**w) for w in slot_warnings()],
        help_abuse=help_abuse,
        truncated=events_truncated
        or evidence_truncated
        or poses_truncated
        or funnel_truncated
        or bool(help_abuse is not None and help_abuse.truncated)
        or cost.truncated,
    )
