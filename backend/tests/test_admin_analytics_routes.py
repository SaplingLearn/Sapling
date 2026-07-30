"""Tests for routes/admin_analytics.py — the admin cost-rollup / analytics API
(issue #120).

A small but faithful fake of the PostgREST `table()` seam interprets the
`eq.`/`gte.`/`lte.`/`like.` filters, ordering, and limit/offset that the route
builds, so date-range filtering, aggregation, and pagination are exercised for
real (not mocked away).
"""
from __future__ import annotations

import fnmatch
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from main import app
import routes.admin_analytics as analytics

client = TestClient(app)

BASE = "/api/admin/analytics"

# In-range = July 2026; OUT = 2020. The default-range test freezes the module
# clock at 2026-07-21 so its 30-day window covers the July rows, not the 2020 one.
IN1 = "2026-07-10T09:00:00+00:00"
IN2 = "2026-07-12T09:00:00+00:00"
IN3 = "2026-07-15T09:00:00+00:00"
OUT = "2020-01-01T00:00:00+00:00"


def _seed():
    events = [
        {"event_type": "document.upload", "category": "usage", "user_id": "u1", "request_id": "r1", "payload": {}, "created_at": IN1},
        {"event_type": "quiz.completed", "category": "usage", "user_id": "u1", "request_id": "r2", "payload": {}, "created_at": IN2},
        {"event_type": "quiz.completed", "category": "usage", "user_id": "u2", "request_id": "r3", "payload": {}, "created_at": IN3},
        {"event_type": "error.5xx", "category": "error", "user_id": "u2", "request_id": "r4",
         "payload": {"path": "/api/quiz", "method": "POST", "status_code": 500, "duration_ms": 12.3}, "created_at": IN3},
        {"event_type": "auth.login", "category": "audit", "user_id": "u1", "request_id": "r0", "payload": {}, "created_at": OUT},
    ]
    llm = [
        {"user_id": "u1", "feature": "quiz", "task": "quiz", "model": "gemini-2.5-flash", "provider": "gemini",
         "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost_usd": 0.01, "created_at": IN1},
        {"user_id": "u1", "feature": "chat_tutor", "task": "chat_tutor", "model": "gemini-2.5-pro", "provider": "gemini",
         "prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300, "cost_usd": 0.05, "created_at": IN2},
        {"user_id": "u2", "feature": "quiz", "task": "quiz", "model": "gemini-2.5-flash", "provider": "gemini",
         "prompt_tokens": 80, "completion_tokens": 40, "total_tokens": 120, "cost_usd": 0.02, "created_at": IN3},
        {"user_id": "u1", "feature": "quiz", "task": "quiz", "model": "gemini-2.5-flash", "provider": "gemini",
         "prompt_tokens": 999, "completion_tokens": 999, "total_tokens": 1998, "cost_usd": 9.99, "created_at": OUT},
    ]
    return {"events": events, "llm_usage": llm}


class _FakeTable:
    def __init__(self, rows):
        self.rows = rows

    @staticmethod
    def _match(value, cond: str) -> bool:
        op, _, target = cond.partition(".")
        sval = "" if value is None else str(value)
        if op == "eq":
            return sval == target
        if op == "gte":
            return sval >= target
        if op == "lte":
            return sval <= target
        if op == "like":
            return fnmatch.fnmatch(sval, target)
        raise AssertionError(f"unsupported op in test fake: {op}")

    def _filtered(self, filters):
        rows = list(self.rows)
        for col, cond in (filters or {}).items():
            conds = cond if isinstance(cond, list) else [cond]
            for c in conds:
                rows = [r for r in rows if self._match(r.get(col), c)]
        return rows

    @staticmethod
    def _ordered(rows, order):
        if not order:
            return rows
        col, _, direction = order.partition(".")
        return sorted(rows, key=lambda r: (r.get(col) is None, r.get(col)), reverse=direction == "desc")

    def select_with_count(self, columns="*", filters=None, order=None, limit=None, offset=None):
        rows = self._ordered(self._filtered(filters), order)
        total = len(rows)
        if offset:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return rows, total

    def select(self, columns="*", filters=None, order=None, limit=None):
        rows, _ = self.select_with_count(columns, filters, order, limit, None)
        return rows


@pytest.fixture
def seeded(monkeypatch):
    store = _seed()
    monkeypatch.setattr(analytics, "table", lambda name: _FakeTable(store.get(name, [])))
    return store


# Explicit window covering the July rows (and excluding the 2020 rows).
RANGE = {"from": "2026-07-01T00:00:00+00:00", "to": "2026-08-01T00:00:00+00:00"}


# ── /usage/summary ───────────────────────────────────────────────────────────


def test_usage_summary_counts(seeded):
    r = client.get(f"{BASE}/usage/summary", params=RANGE)
    assert r.status_code == 200
    body = r.json()
    assert body["total_events"] == 4  # the 2020 auth.login is excluded
    assert body["distinct_active_users"] == 2
    assert body["truncated"] is False  # nowhere near the scan cap
    by_type = {row["event_type"]: row["count"] for row in body["by_event_type"]}
    assert by_type["quiz.completed"] == 2
    assert by_type["document.upload"] == 1
    assert "auth.login" not in by_type


# ── /usage/by-user ───────────────────────────────────────────────────────────


def test_usage_by_user_totals(seeded):
    r = client.get(f"{BASE}/usage/by-user", params=RANGE)
    assert r.status_code == 200
    body = r.json()
    users = {u["user_id"]: u for u in body["users"]}
    assert body["total_users"] == 2
    assert users["u1"]["event_count"] == 2
    assert users["u1"]["llm_cost_usd"] == pytest.approx(0.06)
    assert users["u1"]["total_tokens"] == 450
    assert users["u2"]["llm_cost_usd"] == pytest.approx(0.02)


def test_usage_by_user_pagination(seeded):
    r = client.get(f"{BASE}/usage/by-user", params={**RANGE, "limit": 1, "offset": 0})
    body = r.json()
    assert body["total_users"] == 2
    assert len(body["users"]) == 1


# ── /llm/cost ────────────────────────────────────────────────────────────────


def test_llm_cost_group_by_feature(seeded):
    r = client.get(f"{BASE}/llm/cost", params={**RANGE, "group_by": "feature"})
    assert r.status_code == 200
    body = r.json()
    rows = {row["key"]: row for row in body["rows"]}
    assert rows["quiz"]["cost_usd"] == pytest.approx(0.03)
    assert rows["quiz"]["calls"] == 2
    assert rows["chat_tutor"]["cost_usd"] == pytest.approx(0.05)
    assert body["totals"]["cost_usd"] == pytest.approx(0.08)


def test_llm_cost_group_by_model(seeded):
    r = client.get(f"{BASE}/llm/cost", params={**RANGE, "group_by": "model"})
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["gemini-2.5-flash"]["cost_usd"] == pytest.approx(0.03)
    assert rows["gemini-2.5-pro"]["cost_usd"] == pytest.approx(0.05)


def test_llm_cost_group_by_user(seeded):
    r = client.get(f"{BASE}/llm/cost", params={**RANGE, "group_by": "user"})
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["u1"]["cost_usd"] == pytest.approx(0.06)
    assert rows["u2"]["total_tokens"] == 120


def test_llm_cost_rejects_bad_group_by(seeded):
    r = client.get(f"{BASE}/llm/cost", params={**RANGE, "group_by": "banana"})
    assert r.status_code == 422


# ── /errors ──────────────────────────────────────────────────────────────────


def test_errors_returns_error_events_with_payload_fields(seeded):
    r = client.get(f"{BASE}/errors", params=RANGE)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    err = body["errors"][0]
    assert err["event_type"] == "error.5xx"
    assert err["path"] == "/api/quiz"
    assert err["method"] == "POST"
    assert err["status_code"] == 500
    assert err["duration_ms"] == pytest.approx(12.3)


# ── date filtering + defaults ────────────────────────────────────────────────


def test_narrow_range_excludes_rows(seeded):
    # A window that only covers IN1 (2026-07-10).
    r = client.get(f"{BASE}/usage/summary", params={
        "from": "2026-07-09T00:00:00+00:00", "to": "2026-07-11T00:00:00+00:00",
    })
    assert r.json()["total_events"] == 1


def test_default_range_is_last_30_days(seeded, monkeypatch):
    # Freeze the module clock at 2026-07-21 so the default 30-day window covers
    # the July fixture rows but not the 2020 one — whatever today's date is.
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 21, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(analytics, "datetime", _FrozenDatetime)
    r = client.get(f"{BASE}/usage/summary")
    assert r.status_code == 200
    assert r.json()["total_events"] == 4


def test_rejects_malformed_from(seeded):
    r = client.get(f"{BASE}/usage/summary", params={"from": "not-a-date", "to": RANGE["to"]})
    assert r.status_code == 422
    assert "'from'" in r.json()["detail"]


def test_rejects_malformed_to(seeded):
    r = client.get(f"{BASE}/usage/summary", params={"from": RANGE["from"], "to": "2026-13-45"})
    assert r.status_code == 422
    assert "'to'" in r.json()["detail"]


def test_rejects_from_after_to(seeded):
    r = client.get(f"{BASE}/usage/summary", params={"from": RANGE["to"], "to": RANGE["from"]})
    assert r.status_code == 422


# ── scan-cap truncation + response headers ───────────────────────────────────


def test_scan_cap_truncation_is_surfaced(seeded, monkeypatch):
    # Shrink the paging + cap so the 4 in-range event rows overflow the scan.
    monkeypatch.setattr(analytics, "_PAGE", 1)
    monkeypatch.setattr(analytics, "_SCAN_CAP", 2)
    r = client.get(f"{BASE}/usage/summary", params=RANGE)
    assert r.status_code == 200
    body = r.json()
    assert body["truncated"] is True
    assert body["total_events"] == 2  # capped, and the response says so


def test_responses_are_cache_control_private(seeded):
    for path, params in [
        ("/usage/summary", RANGE),
        ("/usage/by-user", RANGE),
        ("/llm/cost", {**RANGE, "group_by": "feature"}),
        ("/errors", RANGE),
    ]:
        r = client.get(f"{BASE}{path}", params=params)
        assert r.status_code == 200
        assert r.headers.get("Cache-Control") == "private", path


# ── range serialization + day bucketing (#121 backend) ───────────────────────


def test_range_serializes_as_from(seeded):
    # The wire key must be "from" (matching the query param), not the Python
    # field name "from_" — the TS client types freeze on this shape.
    r = client.get(f"{BASE}/usage/summary", params=RANGE)
    assert r.json()["range"] == {"from": RANGE["from"], "to": RANGE["to"]}


def test_usage_summary_bucket_day_series(seeded):
    r = client.get(f"{BASE}/usage/summary", params={**RANGE, "bucket": "day"})
    assert r.status_code == 200
    body = r.json()
    assert [p["date"] for p in body["series"]] == ["2026-07-10", "2026-07-12", "2026-07-15"]
    assert [p["count"] for p in body["series"]] == [1, 1, 2]
    # Bucketing adds the series; it must not change the aggregate fields.
    assert body["total_events"] == 4
    assert body["distinct_active_users"] == 2


def test_usage_summary_without_bucket_has_no_series(seeded):
    r = client.get(f"{BASE}/usage/summary", params=RANGE)
    assert r.json()["series"] is None


def test_llm_cost_bucket_day_series(seeded):
    r = client.get(f"{BASE}/llm/cost", params={**RANGE, "bucket": "day"})
    assert r.status_code == 200
    series = r.json()["series"]
    assert [p["date"] for p in series] == ["2026-07-10", "2026-07-12", "2026-07-15"]
    assert [p["calls"] for p in series] == [1, 1, 1]
    assert [p["total_tokens"] for p in series] == [150, 300, 120]
    assert series[0]["cost_usd"] == pytest.approx(0.01)
    assert series[1]["cost_usd"] == pytest.approx(0.05)
    assert series[2]["cost_usd"] == pytest.approx(0.02)


def test_errors_bucket_day_series(seeded):
    r = client.get(f"{BASE}/errors", params={**RANGE, "bucket": "day"})
    assert r.status_code == 200
    body = r.json()
    assert body["series"] == [{"date": "2026-07-15", "count": 1}]
    assert body["total"] == 1
    assert body["truncated"] is False


def test_bucket_rejects_invalid_value(seeded):
    r = client.get(f"{BASE}/usage/summary", params={**RANGE, "bucket": "hour"})
    assert r.status_code == 422


def test_errors_bucket_series_truncation_is_surfaced(monkeypatch):
    # The errors series needs its own range scan (the feed itself is paginated
    # server-side); that scan can hit the cap and must say so, never silently.
    store = {
        "events": [
            {"event_type": "error.5xx", "category": "error", "user_id": "u1", "request_id": f"r{i}",
             "payload": {"path": "/api/x", "method": "GET", "status_code": 500, "duration_ms": 1.0},
             "created_at": ts}
            for i, ts in enumerate([IN1, IN2, IN3])
        ],
        "llm_usage": [],
    }
    monkeypatch.setattr(analytics, "table", lambda name: _FakeTable(store.get(name, [])))
    monkeypatch.setattr(analytics, "_PAGE", 1)
    monkeypatch.setattr(analytics, "_SCAN_CAP", 2)
    r = client.get(f"{BASE}/errors", params={**RANGE, "bucket": "day"})
    assert r.status_code == 200
    body = r.json()
    assert body["truncated"] is True
    assert [p["count"] for p in body["series"]] == [1, 1]  # capped at 2 scanned rows


# ── admin gating ─────────────────────────────────────────────────────────────


def test_endpoints_reject_non_admin(seeded, monkeypatch):
    from fastapi import HTTPException

    def _deny(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    monkeypatch.setattr(analytics, "require_admin", _deny)
    for path, params in [
        ("/usage/summary", RANGE),
        ("/usage/by-user", RANGE),
        ("/llm/cost", {**RANGE, "group_by": "feature"}),
        ("/errors", RANGE),
    ]:
        resp = client.get(f"{BASE}{path}", params=params)
        assert resp.status_code == 403, f"{path} should be admin-only"
