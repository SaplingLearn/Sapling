"""Hourly ops alerts by email: AI spend, spend outliers, auth/5xx spikes.

Until this existed the only spend signal was the admin analytics dashboard,
which nobody watches at 3 a.m. A lifespan task (same pattern as
`services/index_sweeper.py`) wakes every `CHECK_INTERVAL_SECONDS` and checks:

- ``daily_spend``: today's (UTC) total LLM cost (`llm_usage.cost_usd`) at or
  over `config.spend_alert_daily_usd()`;
- ``user_spend``: any student whose own cost today is at or over
  `config.spend_alert_user_daily_usd()` (a runaway loop, a scripted abuser);
- ``permission_denied_spike`` / ``error_5xx_spike``: the last hour's
  `auth.permission_denied` / `error.5xx` events at or over their per-hour
  threshold AND at least `config.spend_alert_spike_factor()` times the
  previous 24 h's hourly mean (so a steady background rate never pages).

Each firing alert is emailed to every admin through
`services/email_service.send_email`, with dedupe key
``ops_alert:<type>:<UTC date>:<recipient hash>`` — so an admin hears about a
given alert type at most ONCE per UTC day however many hourly checks see it
(`email_sends` holds the claim; `RESEND_API_KEY` unset records ``skipped``
and sends nothing). The emails carry aggregate numbers only: no student
names, ids or content — the dashboard has the detail.

Switches:
- The `spend_alerts` feature flag (resolved globally) is the kill switch,
  read before every check; it is seeded "on" by migration.
  ``SAPLING_FLAG_SPEND_ALERTS=off`` forces it off from the environment.
- The task never starts under pytest, ``APP_ENV=test``, or any non-"real"
  ``SAPLING_MODEL_MODE`` (function/E2E lanes have no real spend, and must
  never email).
Thresholds are config (`config.spend_alert_*`, env-overridable, read at call
time).

Reads use the service role (outside any request, `db/scope.py` rule 5) and
reuse the admin analytics range scan (`services/admin/analytics/scan.py`).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import config
from agents._providers import model_mode
from db.connection import table
from services import email_service, email_templates
from services.admin.analytics.scan import _as_float, _scan_range

logger = logging.getLogger(__name__)

FLAG = "spend_alerts"
CHECK_INTERVAL_SECONDS = 3600
EMAIL_KIND = "ops_alert"
DASHBOARD_PATH = "/admin/analytics"

# The two event types watched for spikes, and the name of the config reader
# of each one's per-hour threshold (looked up at call time).
SPIKE_EVENTS: dict[str, tuple[str, str]] = {
    "permission_denied_spike": ("auth.permission_denied", "spend_alert_denied_per_hour"),
    "error_5xx_spike": ("error.5xx", "spend_alert_5xx_per_hour"),
}

_task: asyncio.Task | None = None


def _now() -> datetime:
    """The clock (patched by tests)."""
    return datetime.now(timezone.utc)


@dataclass
class Alert:
    type: str
    title: str
    points: list[tuple[str, str]] = field(default_factory=list)


# ── switches ─────────────────────────────────────────────────────────────────


def alerts_runnable() -> bool:
    """Whether this process may run the task at all (not the flag)."""
    if "pytest" in sys.modules or os.getenv("PYTEST_CURRENT_TEST"):
        return False
    if getattr(config, "APP_ENV", "") == "test":
        return False
    return model_mode() == "real"


def _flag_on() -> bool:
    from services.feature_flags import flag_on

    try:
        return flag_on(FLAG, None)
    except Exception:  # noqa: BLE001 — a flag-store failure must not end the loop
        logger.warning("spend alerts: could not read the %s flag; skipping", FLAG, exc_info=True)
        return False


# ── checks ───────────────────────────────────────────────────────────────────


def _usd(value: float) -> str:
    return f"${value:,.2f}"


def _spend_alerts(now: datetime) -> list[Alert]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows, truncated = _scan_range(
        "llm_usage", "user_id,cost_usd,created_at", day_start.isoformat(), now.isoformat(),
    )
    total = 0.0
    per_user: dict[str, float] = defaultdict(float)
    for r in rows:
        cost = _as_float(r.get("cost_usd"))
        total += cost
        if r.get("user_id"):
            per_user[r["user_id"]] += cost
    note = " (scan capped; the true figure is higher)" if truncated else ""

    alerts: list[Alert] = []
    daily = config.spend_alert_daily_usd()
    if total >= daily:
        alerts.append(Alert(
            "daily_spend",
            f"AI spend today is {_usd(total)}",
            [("Spend today (UTC)", f"{_usd(total)}{note}"),
             ("Daily threshold", _usd(daily)),
             ("AI calls today", f"{len(rows):,}")],
        ))
    user_limit = config.spend_alert_user_daily_usd()
    outliers = sorted((c for c in per_user.values() if c >= user_limit), reverse=True)
    if outliers:
        alerts.append(Alert(
            "user_spend",
            f"{len(outliers)} student(s) over {_usd(user_limit)} of AI spend today",
            [("Students over the per-student threshold", str(len(outliers))),
             ("Highest single-student spend", _usd(outliers[0])),
             ("Per-student threshold", _usd(user_limit)),
             ("Where to look", "Admin analytics, usage by user, today")],
        ))
    return alerts


def _count(event_type: str, since: datetime, until: datetime) -> int:
    _rows, total = table("events").select_with_count(
        "id",
        filters={"event_type": f"eq.{event_type}",
                 "created_at": [f"gte.{since.isoformat()}", f"lt.{until.isoformat()}"]},
        limit=1,
    )
    return int(total or 0)


def _spike_alerts(now: datetime) -> list[Alert]:
    alerts: list[Alert] = []
    factor = config.spend_alert_spike_factor()
    hour_ago = now - timedelta(hours=1)
    for alert_type, (event_type, reader) in SPIKE_EVENTS.items():
        last_hour = _count(event_type, hour_ago, now)
        threshold = getattr(config, reader)()
        if last_hour < threshold:
            continue
        baseline = _count(event_type, hour_ago - timedelta(hours=24), hour_ago) / 24
        if last_hour < factor * max(baseline, 1.0):
            continue
        alerts.append(Alert(
            alert_type,
            f"Spike in {event_type}: {last_hour} in the last hour",
            [("Last hour", str(last_hour)),
             ("Hourly mean, previous 24 h", f"{baseline:.1f}"),
             ("Thresholds", f"at least {threshold:g} and {factor:g}x the mean")],
        ))
    return alerts


def evaluate(now: datetime | None = None) -> list[Alert]:
    """Every alert that fires at `now`. Each check fails on its own: a broken
    spend read must not hide a 5xx spike."""
    now = now or _now()
    alerts: list[Alert] = []
    for check in (_spend_alerts, _spike_alerts):
        try:
            alerts.extend(check(now))
        except Exception:  # noqa: BLE001
            logger.warning("spend alerts: %s failed", check.__name__, exc_info=True)
    return alerts


# ── delivery ─────────────────────────────────────────────────────────────────


def admin_recipients() -> list[str]:
    """`config.spend_alert_recipients()`, else every live admin's address."""
    configured = config.spend_alert_recipients()
    if configured:
        return sorted(set(configured))
    from services.encryption import decrypt_if_present

    roles = table("user_roles").select(
        "user_id,roles!inner(slug)", filters={"roles.slug": "eq.admin"},
    ) or []
    ids = sorted({r["user_id"] for r in roles if r.get("user_id")})
    if not ids:
        return []
    users = table("users").select(
        "id,email", filters={"id": f"in.({','.join(ids)})", "deleted_at": "is.null"},
    ) or []
    out = set()
    for u in users:
        address = (decrypt_if_present(u.get("email")) or "").strip()
        if "@" in address:
            out.add(address)
    return sorted(out)


def _dedupe_key(alert: Alert, now: datetime, address: str) -> str:
    return f"{EMAIL_KIND}:{alert.type}:{now.date().isoformat()}:{email_service.recipient_hash(address)[:16]}"


def run_once(now: datetime | None = None) -> dict[str, list[str]]:
    """One check: evaluate, then email each firing alert to each admin.

    Returns {alert type: [send status per recipient]}. Never raises.
    """
    if not _flag_on():
        return {}
    now = now or _now()
    alerts = evaluate(now)
    if not alerts:
        return {}
    try:
        recipients = admin_recipients()
    except Exception:  # noqa: BLE001
        logger.warning("spend alerts: could not resolve admin recipients", exc_info=True)
        recipients = []
    for alert in alerts:
        logger.warning("ops alert %s: %s", alert.type, alert.title)
    if not recipients:
        logger.warning("spend alerts: %d alert(s) fired but no admin has an email address", len(alerts))
        return {a.type: [] for a in alerts}

    dashboard = f"{(config.FRONTEND_URL or '').rstrip('/')}{DASHBOARD_PATH}"
    scope = email_service.suppression_scope(EMAIL_KIND)
    # One read of who must not get an ops alert, for every send below
    # (send_email would otherwise read two tables per recipient per alert).
    try:
        suppressions = email_service.suppressions_for(scope)
    except Exception:  # noqa: BLE001 — each send then reads its own
        logger.warning("spend alerts: could not read the suppressions; each send checks its own",
                       exc_info=True)
        suppressions = None
    results: dict[str, list[str]] = {}
    for alert in alerts:
        statuses = []
        for address in recipients:
            subject, html, text = email_templates.ops_alert(
                alert.title, alert.points, dashboard_url=dashboard,
                unsubscribe_url=email_service.unsubscribe_url(address, scope=scope),
            )
            statuses.append(email_service.send_email(
                kind=EMAIL_KIND, to=address, subject=subject, html=html, text=text,
                dedupe_key=_dedupe_key(alert, now, address), suppressions=suppressions,
            ))
        results[alert.type] = statuses
    return results


# ── lifespan task ────────────────────────────────────────────────────────────


async def _loop(interval: float = CHECK_INTERVAL_SECONDS) -> None:
    # Sleep first: a deploy restarts every instance at once.
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(run_once)
        except Exception:  # noqa: BLE001 — run_once does not raise; backstop
            logger.exception("spend alerts: check raised; the loop continues")


def start_spend_alerts() -> None:
    """Start the hourly loop on the running event loop (app lifespan)."""
    global _task
    if not alerts_runnable():
        logger.info("spend alerts not started (pytest, APP_ENV=test or not real model mode)")
        return
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_loop(), name="spend-alerts")
        logger.info("spend alerts started (every %ss)", CHECK_INTERVAL_SECONDS)


async def stop_spend_alerts() -> None:
    """Cancel the loop. Safe when it never started."""
    global _task
    task, _task = _task, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
