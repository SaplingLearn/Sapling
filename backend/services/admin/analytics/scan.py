"""
backend/services/admin/analytics/scan.py

Range handling for the admin analytics API (#118: moved verbatim out of
``routes/admin_analytics.py``). PostgREST has no GROUP BY, so the grouped
endpoints scan the date-bounded rows with ``_scan_range`` (paged through
``select_with_count``, capped, truncation surfaced) and aggregate in Python.
``_resolve_range`` raises ``services.admin.errors.Unprocessable``, which the
route maps to the same 422.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from db.connection import table
from services.admin.errors import Unprocessable
from services.events_service import SYSTEM_CATEGORY

# Same logger name as the route always used, so log filters keep matching.
logger = logging.getLogger("sapling.admin_analytics")


# Page size for range scans, and a hard ceiling so a pathological range can't
# pull unbounded rows into memory. Hitting the cap is logged and surfaced via
# the response's `truncated` flag, never silent.
_PAGE = 1000
_SCAN_CAP = 100_000


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
            raise Unprocessable(f"Invalid {param!r} datetime: {value!r} is not ISO 8601")
        # Treat naive bounds as UTC so mixed naive/aware bounds stay comparable.
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    from_dt = _parse("from", from_iso)
    to_dt = _parse("to", to_iso)
    if from_dt > to_dt:
        raise Unprocessable("'from' must not be after 'to'")
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
    cap: int | None = None,
    newest_first: bool = False,
) -> tuple[list[dict], bool]:
    """Fetch every row in [from, to] for a table, paging via select_with_count.

    Aggregation endpoints need the full (date-bounded) set — PostgREST won't
    GROUP BY for us — so we page to completion rather than relying on the
    server's default row cap. Returns ``(rows, truncated)``: a range large
    enough to hit ``cap`` (default _SCAN_CAP) stops the scan early, logs a
    warning, and sets ``truncated=True`` so callers can surface the partial
    aggregation. ``newest_first`` pages newest → oldest, so a truncated scan
    keeps the most recent rows rather than the oldest. `time_column` is the
    timestamp the range bounds (``created_at`` unless a table has none);
    `order` defaults to it, ascending (descending with ``newest_first``).
    """
    if cap is None:
        cap = _SCAN_CAP  # read at call time (tests shrink it)
    out: list[dict] = []
    offset = 0
    truncated = False
    while True:
        filters: dict = {time_column: [f"gte.{from_iso}", f"lte.{to_iso}"]}
        if extra_filters:
            filters.update(extra_filters)
        rows, total = table(table_name).select_with_count(
            columns, filters=filters,
            order=order or (f"{time_column}.desc" if newest_first else f"{time_column}.asc"),
            limit=_PAGE, offset=offset,
        )
        out.extend(rows)
        if len(out) >= total or not rows:
            break
        if len(out) >= cap:
            truncated = True
            logger.warning(
                "admin_analytics scan hit cap %d on %r (total=%d); results truncated",
                cap, table_name, total,
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
