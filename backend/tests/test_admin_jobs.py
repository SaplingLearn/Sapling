"""/api/admin/jobs: the job queue's depth and dead letters (#116).

`table()` is faked: these pin the route's reads and its shape. What the
statuses mean is pinned against real SQL in
tests/integration/test_jobs_queue_db.py / test_jobs_upkeep_db.py.
"""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import routes.admin_jobs as admin_jobs
from main import app

client = TestClient(app)
BASE = "/api/admin/jobs"

DEAD = {
    "id": "j-dead", "type": "document.index", "payload": {"document_id": "d1"},
    "attempts": 5, "max_attempts": 5, "last_error": "TimeoutError: x",
    "dedupe_key": None, "locked_by": "w1", "created_at": "2026-11-08T10:00:00Z",
    "updated_at": "2026-11-08T11:00:00Z",
}


class FakeJobs:
    def __init__(self, rows):
        self.rows = rows
        self.selects: list[dict] = []
        self.counts: list[dict] = []

    def _match(self, filters):
        out = list(self.rows)
        for col, rule in (filters or {}).items():
            op, _, val = rule.partition(".")
            if op == "eq":
                out = [r for r in out if str(r.get(col)) == val]
            elif op == "in":
                wanted = set(val.strip("()").split(","))
                out = [r for r in out if r.get(col) in wanted]
        return out

    def select_with_count(self, columns="*", filters=None, order=None, limit=None,
                          offset=None, timeout=None):
        self.counts.append({"filters": filters, "limit": limit})
        rows = self._match(filters)
        return rows[:limit], len(rows)

    def select(self, columns="*", filters=None, order=None, limit=None, offset=None,
               timeout=None):
        self.selects.append({"columns": columns, "filters": filters, "order": order,
                             "limit": limit, "offset": offset})
        rows = self._match(filters)
        start = offset or 0
        return rows[start:start + limit] if limit else rows[start:]


def _rows():
    rows = []
    for i, (type_, status) in enumerate([
        ("course_context.refresh", "queued"), ("course_context.refresh", "queued"),
        ("course_context.refresh", "running"), ("document.index", "failed"),
        ("document.index", "succeeded"), ("jobs.prune", "succeeded"),
    ]):
        rows.append({"id": f"j-{i}", "type": type_, "status": status})
    rows.append(dict(DEAD, status="dead"))
    return rows


@pytest.fixture
def fake(monkeypatch):
    jobs = FakeJobs(_rows())
    monkeypatch.setattr(admin_jobs, "table", lambda name: jobs)
    monkeypatch.setattr(admin_jobs, "require_admin", lambda request: None)
    return jobs


def test_is_admin_only(monkeypatch):
    def deny(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    touched = []
    monkeypatch.setattr(admin_jobs, "require_admin", deny)
    monkeypatch.setattr(admin_jobs, "table", lambda name: touched.append(name))
    assert client.get(BASE).status_code == 403
    assert touched == []


def test_reports_depth_by_status_and_type_and_the_dead_letters(fake):
    body = client.get(BASE).json()
    assert body["status_counts"] == {
        "queued": 2, "failed": 1, "running": 1, "succeeded": 2, "dead": 1,
    }
    assert body["depth"] == 4
    assert body["outstanding"] == {
        "course_context.refresh": {"queued": 2, "failed": 0, "running": 1},
        "document.index": {"queued": 0, "failed": 1, "running": 0},
    }
    assert body["outstanding_truncated"] is False
    assert body["dead_total"] == 1
    (dead,) = body["dead_letter"]
    assert dead["id"] == "j-dead" and dead["last_error"] == "TimeoutError: x"


def test_the_dead_letter_list_is_newest_first_capped_and_filterable(fake):
    client.get(BASE, params={"dead_limit": 7, "type": "document.index"})
    dead_read = fake.selects[-1]
    assert dead_read["filters"] == {"status": "eq.dead", "type": "eq.document.index"}
    assert dead_read["order"] == "updated_at.desc,id"
    assert dead_read["limit"] == 7
    assert "payload" in dead_read["columns"] and "last_error" in dead_read["columns"]


@pytest.mark.parametrize("params", [{"dead_limit": 0}, {"dead_limit": 501}])
def test_dead_limit_is_bounded(fake, params):
    assert client.get(BASE, params=params).status_code == 422


def test_the_outstanding_scan_pages_and_stops_at_its_cap(monkeypatch):
    many = [{"id": f"q-{i}", "type": "t.x", "status": "queued"} for i in range(25)]
    jobs = FakeJobs(many)
    monkeypatch.setattr(admin_jobs, "table", lambda name: jobs)
    monkeypatch.setattr(admin_jobs, "require_admin", lambda request: None)
    monkeypatch.setattr(admin_jobs, "MAX_ROWS", 10)
    monkeypatch.setattr(admin_jobs, "OUTSTANDING_SCAN_CAP", 20)

    body = client.get(BASE).json()
    assert body["outstanding"] == {"t.x": {"queued": 20, "failed": 0, "running": 0}}
    assert body["outstanding_truncated"] is True
    assert body["status_counts"]["queued"] == 25  # exact regardless
    scans = [s for s in jobs.selects if s["columns"] == "id,type,status"]
    assert [s["offset"] for s in scans] == [0, 10]
