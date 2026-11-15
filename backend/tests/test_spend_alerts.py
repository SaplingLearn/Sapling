"""services/spend_alerts.py — hourly ops alert emails, on a fake clock."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import config
from services import email_service, spend_alerts

NOON = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def _cmp(value: str, cond: str) -> bool:
    op, _, arg = cond.partition(".")
    if op == "eq":
        return value == arg
    if op in ("gte", "lte", "gt", "lt"):
        a, b = datetime.fromisoformat(value), datetime.fromisoformat(arg)
        return {"gte": a >= b, "lte": a <= b, "gt": a > b, "lt": a < b}[op]
    if op == "is" and arg == "null":
        return value is None
    if op == "in":
        return value in arg.strip("()").split(",")
    raise AssertionError(f"fake does not understand {cond}")


class FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def _match(self, row, filters):
        for col, cond in (filters or {}).items():
            if col == "roles.slug":
                if not _cmp((row.get("roles") or {}).get("slug"), cond):
                    return False
                continue
            for c in cond if isinstance(cond, list) else [cond]:
                if c == "is.null":
                    if row.get(col) is not None:
                        return False
                elif not _cmp(row.get(col), c):
                    return False
        return True

    def select(self, columns="*", filters=None, order=None, limit=None, offset=None, **_):
        out = [r for r in self.rows if self._match(r, filters)][offset or 0:]
        return out[:limit] if limit else out

    def select_with_count(self, columns="*", filters=None, order=None, limit=None, offset=None, **_):
        hit = [r for r in self.rows if self._match(r, filters)]
        page = hit[offset or 0:]
        return (page[:limit] if limit else page), len(hit)


@pytest.fixture
def db(monkeypatch):
    data: dict[str, list[dict]] = {
        "llm_usage": [], "events": [],
        "user_roles": [{"user_id": "user_admin", "roles": {"slug": "admin"}},
                       {"user_id": "user_student", "roles": {"slug": "student"}}],
        "users": [{"id": "user_admin", "email": "admin@example.edu", "deleted_at": None},
                  {"id": "user_student", "email": "kid@example.edu", "deleted_at": None}],
    }

    def table(name):
        return FakeTable(data.setdefault(name, []))

    monkeypatch.setattr(spend_alerts, "table", table)
    import services.admin.analytics.scan as scan

    monkeypatch.setattr(scan, "table", table)
    monkeypatch.setattr(spend_alerts, "_flag_on", lambda: True)
    for name in ("SPEND_ALERT_DAILY_USD", "SPEND_ALERT_USER_DAILY_USD", "SPEND_ALERT_RECIPIENTS",
                 "SPEND_ALERT_DENIED_PER_HOUR", "SPEND_ALERT_5XX_PER_HOUR", "SPEND_ALERT_SPIKE_FACTOR"):
        monkeypatch.delenv(name, raising=False)
    return data


@pytest.fixture
def outbox(monkeypatch):
    """send_email stand-in with email_sends' contract: a key sends once."""
    sent: list[dict] = []
    seen: set[str] = set()

    def send_email(**kw):
        if kw["dedupe_key"] in seen:
            return "duplicate"
        seen.add(kw["dedupe_key"])
        sent.append(kw)
        return "sent"

    monkeypatch.setattr(email_service, "send_email", send_email)
    return sent


def _usage(data, user, cost, at):
    data["llm_usage"].append({"user_id": user, "cost_usd": cost, "created_at": at.isoformat()})


def _events(data, event_type, n, at):
    data["events"].extend(
        {"id": f"{event_type}-{at.isoformat()}-{i}", "event_type": event_type,
         "created_at": at.isoformat()} for i in range(n)
    )


def test_quiet_day_sends_nothing(db, outbox):
    _usage(db, "user_a", 1.0, NOON - timedelta(hours=1))
    _events(db, "error.5xx", 2, NOON - timedelta(minutes=10))
    assert spend_alerts.run_once(NOON) == {}
    assert outbox == []


def test_daily_spend_over_threshold_alerts_admins_once_per_day(db, outbox, monkeypatch):
    monkeypatch.setenv("SPEND_ALERT_DAILY_USD", "10")
    for h in range(1, 6):
        _usage(db, f"user_{h}", 3.0, NOON - timedelta(hours=h))  # $15 today
    _usage(db, "user_x", 500.0, NOON - timedelta(days=1))  # yesterday: not counted

    first = spend_alerts.run_once(NOON)
    assert first == {"daily_spend": ["sent"]}
    (mail,) = outbox
    assert mail["to"] == "admin@example.edu"  # admins only, never the student
    assert mail["kind"] == "ops_alert"
    assert "$15.00" in mail["text"] and "user_" not in mail["text"]

    # Every later hourly check the same day: deduped.
    for h in range(1, 6):
        assert spend_alerts.run_once(NOON + timedelta(hours=h)) == {"daily_spend": ["duplicate"]}
    assert len(outbox) == 1

    # Next UTC day, still over: one new email.
    tomorrow = NOON + timedelta(days=1)
    for h in range(1, 5):
        _usage(db, f"user_{h}", 4.0, tomorrow - timedelta(hours=h))  # $16, nobody over $5
    assert spend_alerts.run_once(tomorrow) == {"daily_spend": ["sent"]}
    assert len(outbox) == 2


def test_per_user_outlier(db, outbox, monkeypatch):
    monkeypatch.setenv("SPEND_ALERT_USER_DAILY_USD", "2")
    _usage(db, "user_runaway", 1.5, NOON - timedelta(hours=2))
    _usage(db, "user_runaway", 1.5, NOON - timedelta(hours=1))
    _usage(db, "user_ok", 0.5, NOON - timedelta(hours=1))
    _usage(db, None, 9.0, NOON - timedelta(hours=1))  # system rows are no student
    result = spend_alerts.run_once(NOON)
    assert result == {"user_spend": ["sent"]}
    text = outbox[0]["text"]
    assert "$3.00" in text and "user_runaway" not in text


def test_permission_denied_spike_needs_threshold_and_factor(db, outbox, monkeypatch):
    monkeypatch.setenv("SPEND_ALERT_DENIED_PER_HOUR", "20")
    # A steady 30/hour all day: over the absolute threshold, but no spike.
    for h in range(1, 26):
        _events(db, "auth.permission_denied", 30, NOON - timedelta(hours=h, minutes=-30))
    _events(db, "auth.permission_denied", 30, NOON - timedelta(minutes=5))
    assert spend_alerts.run_once(NOON) == {}

    # The next hour quadruples it: a spike.
    later = NOON + timedelta(hours=1)
    _events(db, "auth.permission_denied", 120, later - timedelta(minutes=5))
    assert spend_alerts.run_once(later) == {"permission_denied_spike": ["sent"]}


def test_5xx_spike_from_a_quiet_baseline(db, outbox):
    _events(db, "error.5xx", 25, NOON - timedelta(minutes=20))
    assert spend_alerts.run_once(NOON) == {"error_5xx_spike": ["sent"]}
    assert "error.5xx" in outbox[0]["subject"]


def test_flag_off_is_the_kill_switch(db, outbox, monkeypatch):
    monkeypatch.setattr(spend_alerts, "_flag_on", lambda: False)
    _events(db, "error.5xx", 500, NOON - timedelta(minutes=1))
    assert spend_alerts.run_once(NOON) == {}
    assert outbox == []


def test_flag_is_registered_off_first_and_seeded_on():
    from pathlib import Path

    from services.feature_flags import REGISTRY

    fd = REGISTRY["spend_alerts"]
    assert fd.variants == ("off", "on") and fd.client_visible is False
    migrations = Path(__file__).resolve().parents[1] / "db" / "migrations"
    seeded = [p for p in migrations.glob("*_spend_alerts_flag.sql")
              if "('spend_alerts', 'on')" in p.read_text()]
    assert len(seeded) == 1


def test_configured_recipients_override_admin_lookup(db, outbox, monkeypatch):
    monkeypatch.setenv("SPEND_ALERT_RECIPIENTS", "ops@example.org, oncall@example.org")
    _events(db, "error.5xx", 25, NOON - timedelta(minutes=20))
    spend_alerts.run_once(NOON)
    assert sorted(m["to"] for m in outbox) == ["oncall@example.org", "ops@example.org"]
    assert len({m["dedupe_key"] for m in outbox}) == 2  # one key per recipient


def test_a_failing_check_does_not_hide_the_others(db, outbox, monkeypatch):
    def boom(_now):
        raise RuntimeError("llm_usage unreadable")

    monkeypatch.setattr(spend_alerts, "_spend_alerts", boom)
    _events(db, "error.5xx", 25, NOON - timedelta(minutes=20))
    assert spend_alerts.run_once(NOON) == {"error_5xx_spike": ["sent"]}


def test_real_send_email_without_resend_key_records_skipped(db, monkeypatch):
    """Through the real send_email: RESEND_API_KEY unset sends nothing, and
    ops_alert is operational (neither an admin's notification opt-out nor an
    unsubscribe click can mute it)."""
    assert email_service.email_category("ops_alert") == "operational"
    claims = []

    class Sends:
        def upsert(self, row, **_):
            claims.append(row)
            return [{"id": "row-1", **row}]

        def update(self, *_a, **_k):
            return []

    monkeypatch.setattr(email_service, "table", lambda name: Sends())
    monkeypatch.setattr(email_service, "is_suppressed", lambda _h, scope="all", reasons=None: False)
    monkeypatch.setattr(config, "RESEND_API_KEY", "")
    _events(db, "error.5xx", 25, NOON - timedelta(minutes=20))
    assert spend_alerts.run_once(NOON) == {"error_5xx_spike": ["skipped"]}
    assert claims[0]["dedupe_key"].startswith("ops_alert:error_5xx_spike:2026-11-14:")
    assert "admin@example.edu" not in claims[0]["dedupe_key"]


def _sending(monkeypatch, suppressed_scopes, reason="unsubscribe", reads=None):
    """email_service over fakes: the given suppression scopes hold every
    address, with `reason`; returns the Resend payloads sent. The run reads
    each suppression table once (`_hashes_in`, recorded in `reads`); a
    per-recipient read (`is_suppressed`) is recorded as ("one", scope)."""
    sent = []
    reads = reads if reads is not None else []

    class Sends:
        def upsert(self, row, **_):
            return [{"id": "row-1", **row}]

        def update(self, *_a, **_k):
            return []

    def held(scope, reasons):
        return scope in suppressed_scopes and (reasons is None or reason in reasons)

    def hashes_in(scope, *, reasons=None):
        reads.append(("all-of", scope))
        if held(scope, reasons):
            return {email_service.recipient_hash(a) for a in ("admin@example.edu", "ops@example.org")}
        return set()

    def is_suppressed(_h, scope="all", reasons=None):
        reads.append(("one", scope))
        return held(scope, reasons)

    monkeypatch.setattr(email_service, "table", lambda name: Sends())
    monkeypatch.setattr(email_service, "_hashes_in", hashes_in)
    monkeypatch.setattr(email_service, "is_suppressed", is_suppressed)
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(email_service, "MIN_REQUEST_INTERVAL_S", 0.0)

    class Resp:
        status_code = 200

        def json(self):
            return {"id": "re_1"}

    monkeypatch.setattr(
        email_service, "_post_to_resend", lambda payload, key: sent.append(payload) or Resp(),
    )
    return sent


def test_a_broadcast_suppressed_admin_still_gets_the_alert_with_a_scoped_link(db, monkeypatch):
    """An admin who once clicked Unsubscribe on a broadcast is suppressed for
    every other kind; the ops alert still goes out, and its own unsubscribe
    link stops ops alerts only."""
    sent = _sending(monkeypatch, {"all"})
    _events(db, "error.5xx", 25, NOON - timedelta(minutes=20))
    assert spend_alerts.run_once(NOON) == {"error_5xx_spike": ["sent"]}
    (payload,) = sent
    scoped = email_service.unsubscribe_url("admin@example.edu", scope="ops_alert")
    assert payload["headers"]["List-Unsubscribe"] == f"<{scoped}>"
    assert scoped in payload["text"]


def test_an_admin_who_stopped_ops_alerts_gets_none(db, monkeypatch):
    sent = _sending(monkeypatch, {"ops_alert"})
    _events(db, "error.5xx", 25, NOON - timedelta(minutes=20))
    assert spend_alerts.run_once(NOON) == {"error_5xx_spike": ["suppressed"]}
    assert sent == []


def test_an_admin_whose_address_bounced_gets_none(db, monkeypatch):
    sent = _sending(monkeypatch, {"all"}, reason="bounce")
    _events(db, "error.5xx", 25, NOON - timedelta(minutes=20))
    assert spend_alerts.run_once(NOON) == {"error_5xx_spike": ["suppressed"]}
    assert sent == []


def test_a_run_reads_the_suppressions_once_not_per_recipient(db, monkeypatch):
    """Three alerts to two admins: the ops table and the `all` table's bounces
    and complaints are read once for the run, and no send reads its own."""
    reads = []
    sent = _sending(monkeypatch, set(), reads=reads)
    monkeypatch.setenv("SPEND_ALERT_RECIPIENTS", "admin@example.edu, ops@example.org")
    monkeypatch.setenv("SPEND_ALERT_DAILY_USD", "1")
    _usage(db, "user_a", 5.0, NOON - timedelta(hours=1))
    _events(db, "error.5xx", 25, NOON - timedelta(minutes=20))

    results = spend_alerts.run_once(NOON)

    assert sorted(results) == ["daily_spend", "error_5xx_spike", "user_spend"]
    assert all(statuses == ["sent", "sent"] for statuses in results.values())
    assert len(sent) == 6
    assert reads == [("all-of", "ops_alert"), ("all-of", "all")]


def test_a_failed_prefetch_leaves_each_send_to_read_its_own(db, monkeypatch):
    reads = []
    sent = _sending(monkeypatch, {"ops_alert"}, reads=reads)

    def down(scope, *, reasons=None):
        raise RuntimeError("PostgREST down")

    monkeypatch.setattr(email_service, "_hashes_in", down)
    _events(db, "error.5xx", 25, NOON - timedelta(minutes=20))
    assert spend_alerts.run_once(NOON) == {"error_5xx_spike": ["suppressed"]}
    assert sent == [] and ("one", "ops_alert") in reads


def test_never_runnable_under_pytest():
    assert spend_alerts.alerts_runnable() is False


def test_loop_checks_every_interval_on_a_fake_clock(monkeypatch):
    calls: list[datetime] = []
    clock = [NOON]

    async def fake_sleep(seconds):
        assert seconds == spend_alerts.CHECK_INTERVAL_SECONDS
        clock[0] += timedelta(seconds=seconds)
        if len(calls) >= 3:
            raise asyncio.CancelledError

    def fake_run_once(now=None):
        calls.append(spend_alerts._now())

    monkeypatch.setattr(spend_alerts.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(spend_alerts, "_now", lambda: clock[0])
    monkeypatch.setattr(spend_alerts, "run_once", fake_run_once)

    async def go():
        with pytest.raises(asyncio.CancelledError):
            await spend_alerts._loop()

    asyncio.run(go())
    assert calls == [NOON + timedelta(hours=1), NOON + timedelta(hours=2), NOON + timedelta(hours=3)]


def test_start_is_a_noop_when_not_runnable():
    async def go():
        spend_alerts.start_spend_alerts()
        assert spend_alerts._task is None
        await spend_alerts.stop_spend_alerts()

    asyncio.run(go())
