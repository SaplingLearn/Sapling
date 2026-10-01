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
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from db.connection import table
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
from services.auth_guard import require_admin
from services.quiz_ask import quiz_ask_session_ids

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


def _scan_range(
    table_name: str, columns: str, from_iso: str, to_iso: str,
    extra_filters: dict | None = None,
) -> tuple[list[dict], bool]:
    """Fetch every row in [from, to] for a table, paging via select_with_count.

    Aggregation endpoints need the full (date-bounded) set — PostgREST won't
    GROUP BY for us — so we page to completion rather than relying on the
    server's default row cap. Returns ``(rows, truncated)``: a range large
    enough to hit _SCAN_CAP stops the scan early, logs a warning, and sets
    ``truncated=True`` so callers can surface the partial aggregation.
    """
    out: list[dict] = []
    offset = 0
    truncated = False
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
        CostDayPoint(date=k, calls=v["calls"], total_tokens=v["total_tokens"], cost_usd=round(v["cost_usd"], 6))
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
    rows, truncated = _scan_range("events", "event_type,user_id,created_at", from_iso, to_iso)

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
            llm_cost_usd=round(a["llm_cost_usd"], 6),
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
# and read-only like every endpoint here. The earnest-revise gate (spec §10)
# is not computed: no event carries that signal (HANDOFF-14 Known gaps).

_STEP_EVENT = "zpd.step"
_LEAK_EVENT = "zpd.leak"
_REVEAL_EVENT = "zpd.reveal"  # spec §13 A88 (m5): a solution SERVED for an open posed item
_EVIDENCE_COLS = "id,node_id,session_id,correct,assisted,max_rung,question_hash,created_at"
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


class Gates(BaseModel):
    zero_leaks: bool
    ceiling_compliance_ok: bool


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
    gates: Gates
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
    and the zero-leak and ceiling-compliance gates; `truncated: true` means a
    scan cap cut the aggregation short."""
    require_admin(request)
    response.headers["Cache-Control"] = "private"
    from_iso, to_iso = _resolve_range(from_, to)
    events, events_truncated = _scan_range(
        "events",
        "event_type,user_id,payload,created_at",
        from_iso,
        to_iso,
        extra_filters={"event_type": f"in.({_STEP_EVENT},{_LEAK_EVENT},{_REVEAL_EVENT})"},
    )
    evidence, evidence_truncated = _scan_range(
        "node_mastery_events",
        _EVIDENCE_COLS,
        from_iso,
        to_iso,
        extra_filters={"event_type": "eq.evidence"},
    )
    quiz_ask = quiz_ask_session_ids(table("sessions"), to_iso=to_iso)  # A106
    steps = [e for e in events if e.get("event_type") == _STEP_EVENT]
    caught = sum(1 for e in events if e.get("event_type") == _LEAK_EVENT)
    reveals = [_payload(e) for e in events if e.get("event_type") == _REVEAL_EVENT]
    served = sum(len(p.get("question_hashes") or []) for p in reveals)
    unscanned = sum(1 for p in reveals if p.get("unscanned") is True)
    in_band, banded = _in_band_share(steps)
    compliance = _ceiling_compliance(steps)
    return LearningLoopKpis(
        range=Range(from_=from_iso, to=to_iso),
        steps_total=len(steps),
        banded_steps=banded,
        in_band=in_band,
        in_band_share=in_band / banded if banded else None,
        htc_k_trend=_htc_k_trend(steps, to_iso),
        unassisted_next_session=NextSessionSuccess(**_next_session_rate(evidence, quiz_ask)),
        caught_leaks=caught,
        served_reveals=served,
        unscanned_turns=unscanned,
        ceiling_compliance=compliance,
        gates=Gates(
            zero_leaks=served <= GATE_LEAKS_MAX,
            ceiling_compliance_ok=compliance.rate is not None
            and compliance.rate >= GATE_CEILING_COMPLIANCE_MIN,
        ),
        truncated=events_truncated or evidence_truncated,
    )
