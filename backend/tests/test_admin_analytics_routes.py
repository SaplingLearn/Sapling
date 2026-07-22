"""Tests for routes/admin_analytics.py — the admin cost-rollup / analytics API
(issue #120).

A small but faithful fake of the PostgREST `table()` seam interprets the
`eq.`/`gte.`/`lte.`/`like.` filters, ordering, and limit/offset that the route
builds, so date-range filtering, aggregation, and pagination are exercised for
real (not mocked away).
"""
from __future__ import annotations

import fnmatch

import pytest
from fastapi.testclient import TestClient

from main import app
import routes.admin_analytics as analytics

client = TestClient(app)

BASE = "/api/admin/analytics"

# In-range = July 2026; OUT = 2020. Default range is last 30 days from today
# (2026-07-21 per the test clock), so the July rows are in the default window.
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


def test_default_range_is_last_30_days(seeded):
    # No from/to: default window (last 30 days from 2026-07-21) covers the July
    # rows but not the 2020 ones.
    r = client.get(f"{BASE}/usage/summary")
    assert r.status_code == 200
    assert r.json()["total_events"] == 4


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
