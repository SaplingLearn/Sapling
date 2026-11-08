"""Spec §13 A137: GET /api/admin/analytics/learning-loop's `cost_per_gain` — the
loop's llm_usage spend in the range against the learning-gain pairs, overall
and per course. The arithmetic is learning/cost_per_gain.py's
(tests/test_learning_cost_per_gain.py); this pins the route's reads: the
task-filtered usage scan, a row's course (its own, else its session's offering's
course), a database before the course column, and a failed read."""

from __future__ import annotations

import fnmatch

import httpx
import pytest
from fastapi.testclient import TestClient

import routes.admin_analytics as analytics
from learning import params
from learning.cost_per_gain import LOOP_TASKS
from main import app

client = TestClient(app)
URL = "/api/admin/analytics/learning-loop"
RANGE = {"from": "2026-07-01T00:00:00+00:00", "to": "2026-07-31T00:00:00+00:00"}  # 30 days
W1 = params.POSTTEST_WINDOWS_DAYS[0]


class _FakeTable:
    """The KPI tests' PostgREST fake (eq/gte/lte/like/in, order, paging)."""

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
        if op == "in":
            return sval in [v.strip('"') for v in target.strip("()").split(",")]
        raise AssertionError(f"unsupported op in test fake: {op}")

    def select_with_count(self, columns="*", filters=None, order=None, limit=None, offset=None):
        rows = list(self.rows)
        for col, cond in (filters or {}).items():
            for c in cond if isinstance(cond, list) else [cond]:
                rows = [r for r in rows if self._match(r.get(col), c)]
        if order:
            rows.sort(key=lambda r: (r.get(order.partition(".")[0]) is None, r.get(order.partition(".")[0])))
        total = len(rows)
        rows = rows[offset or 0 :]
        return (rows[:limit] if limit is not None else rows), total

    def select(self, columns="*", filters=None, order=None, limit=None):
        return self.select_with_count(columns, filters, order, limit, None)[0]


def _anchor(event_id, *, session, qh, correct, node):
    from learning.evidence import Evidence, planning_observation

    ev = Evidence(
        node_id=node, channel="free_response", correct=correct, session_id=session,
        check_item_id=f"item-{qh}", question_hash=qh,
        planning_provenance={"check_item_id": f"item-{qh}", "difficulty": 2,
                             "synthetic_idk": False, "previously_seen": False},
    )
    return {
        "id": event_id, "node_id": node, "event_type": "evidence", "session_id": session,
        "question_hash": qh, "check_item_id": ev.check_item_id, "channel": ev.channel,
        "correct": ev.correct, "assisted": ev.assisted, "max_rung": ev.max_rung,
        "reason": "evidence:free_response", "planning_observation": planning_observation(ev),
    }


def _answered(user, node, course, *, correct, anchor):
    return {
        "user_id": user, "node_id": node, "course_id": course, "window_days": W1,
        "correct": correct, "max_rung": 0, "anchor_event_id": anchor,
        "days_since_evidence": 10.0, "question_hash": f"post-{node}",
        "answered_at": "2026-07-20T00:00:00+00:00",
    }


def _usage(i, task, usd, *, user="u1", session=None, course=None, day=12):
    row = {"id": f"lu{i}", "task": task, "cost_usd": usd, "user_id": user,
           "session_id": session, "created_at": f"2026-07-{day:02d}T00:00:{i:02d}+00:00"}
    if course is not None:
        row["course_id"] = course
    return row


def _store():
    return {
        "llm_usage": [
            _usage(1, "loop_tutor", 0.02, session="s1"),  # course via the session
            _usage(2, "grader", 0.004, session="s1"),
            _usage(3, "check_items", 0.01, user=None, course="cA"),  # drafting: its own course
            _usage(4, "grader", 0.002, user="u2", course="cB"),  # a post-test grade: no session
            _usage(5, "loop_tutor_deep", 0.03, user="u2", session="s9"),  # a session with no offering
            _usage(6, "chat_tutor", 5.0, session="s1"),  # not the loop
            _usage(7, "loop_tutor", 9.0, session="s1", day=1) | {"created_at": "2026-06-01T00:00:00+00:00"},
        ],
        "sessions": [
            {"id": "s1", "offering_id": "off-a", "history": [{"question_hash": "qa"}, {"question_hash": "qb"}]},
            {"id": "s9", "offering_id": None, "history": []},
        ],
        "node_mastery_events": [
            _anchor("ev-a", session="s1", qh="qa", correct=False, node="na"),
            _anchor("ev-b", session="s1", qh="qb", correct=True, node="nb"),
        ],
        "posttest_poses": [
            _answered("u1", "na", "cA", correct=True, anchor="ev-a"),  # +1
            _answered("u1", "nb", "cA", correct=True, anchor="ev-b"),  # 0
        ],
    }


@pytest.fixture
def courses(monkeypatch):
    monkeypatch.setattr(analytics, "offering_course_id", {"off-a": "cA"}.get)


def _serve(monkeypatch, store, table_cls=_FakeTable):
    monkeypatch.setattr(analytics, "table", lambda name: table_cls(store.get(name, [])))


def _block(report, course):
    return next(b for b in report["courses"] if b["course_id"] == course)


def _win(block):
    return next(w for w in block["windows"] if w["window_days"] == W1)


def test_the_loop_spend_meets_the_gain_pairs_overall_and_per_course(monkeypatch, courses):
    _serve(monkeypatch, _store())
    body = client.get(URL, params=RANGE).json()
    report = body["cost_per_gain"]
    assert report["target_usd_per_student_month"] == params.LOOP_COST_TARGET_USD_PER_STUDENT_MONTH
    assert report["range_days"] == pytest.approx(30.0)
    overall = report["overall"]
    assert overall["cost_usd"] == pytest.approx(0.066)  # 0.02 + 0.004 + 0.01 + 0.002 + 0.03
    assert overall["active_students"] == 2 and overall["sessions"] == 2  # s1, s9
    assert overall["per_session"] == pytest.approx((0.02 + 0.004 + 0.03) / 2)
    assert overall["per_active_student_month"] == pytest.approx(0.066 / 2 / (30 / (365.25 / 12)))
    assert _win(overall)["pairs"] == 2 and _win(overall)["gain_points"] == 1
    assert _win(overall)["per_gain_point"] == pytest.approx(0.066)
    a = _block(report, "cA")  # s1's rows through its offering, and the drafting row
    assert a["cost_usd"] == pytest.approx(0.034) and a["drafting_usd"] == pytest.approx(0.01)
    assert _win(a)["pairs"] == 2 and _win(a)["per_pair"] == pytest.approx(0.017)
    b = _block(report, "cB")
    assert b["cost_usd"] == pytest.approx(0.002) and _win(b)["pairs"] == 0
    assert report["unattributed"] == {"cost_usd": pytest.approx(0.03), "rows": 1}  # s9: no offering
    assert body["learning_gain"]["windows"][0]["n"] == 2  # the same pairs


def test_the_usage_read_is_task_filtered_and_totally_ordered(monkeypatch, courses):
    calls = []

    class _Rec(_FakeTable):
        def select_with_count(self, columns="*", filters=None, order=None, limit=None, offset=None):
            if self.rows and self.rows[0].get("id", "").startswith("lu"):
                calls.append((columns, dict(filters or {}), order))
            return super().select_with_count(columns, filters, order, limit, offset)

    _serve(monkeypatch, _store(), _Rec)
    client.get(URL, params=RANGE)
    (columns, filters, order) = calls[0]
    assert columns == analytics._USAGE_COST_COLS
    assert filters["task"] == f"in.({','.join(LOOP_TASKS)})"
    assert order == "created_at.asc,id.asc"  # page_all's rule: a total order


def test_a_database_before_the_course_column_still_reports(monkeypatch, courses):
    """Code ahead of 20261108163653: the read names course_id and PostgREST
    refuses it; the route reads without it, so session rows keep their course
    and a session-less row is unattributed."""
    store = _store()

    class _NoCourse(_FakeTable):
        def select_with_count(self, columns="*", filters=None, order=None, limit=None, offset=None):
            if "course_id" in columns.split(","):
                request = httpx.Request("GET", "http://pgrst/llm_usage")
                response = httpx.Response(
                    400, json={"code": "42703", "message": "column llm_usage.course_id does not exist"},
                    request=request,
                )
                raise httpx.HTTPStatusError("Client error '400 Bad Request'", request=request, response=response)
            rows = [{k: v for k, v in r.items() if k != "course_id"} for r in self.rows]
            return _FakeTable(rows).select_with_count(columns, filters, order, limit, offset)

    monkeypatch.setattr(
        analytics, "table",
        lambda name: (_NoCourse if name == "llm_usage" else _FakeTable)(store.get(name, [])),
    )
    report = client.get(URL, params=RANGE).json()["cost_per_gain"]
    assert report["overall"]["cost_usd"] == pytest.approx(0.066)
    assert _block(report, "cA")["cost_usd"] == pytest.approx(0.024)  # s1 only: drafting lost its course
    assert report["unattributed"] == {"cost_usd": pytest.approx(0.042), "rows": 3}


def test_an_unreadable_spend_leaves_the_field_null_and_the_report_standing(monkeypatch, courses):
    store = _store()

    class _Down(_FakeTable):
        def select_with_count(self, *a, **k):
            raise RuntimeError("503 upstream timeout")

    monkeypatch.setattr(
        analytics, "table",
        lambda name: (_Down if name == "llm_usage" else _FakeTable)(store.get(name, [])),
    )
    r = client.get(URL, params=RANGE)
    assert r.status_code == 200
    body = r.json()
    assert body["cost_per_gain"] is None and body["learning_gain"]["windows"][0]["n"] == 2


def test_nothing_spent_reads_none_never_zero(monkeypatch, courses):
    _serve(monkeypatch, {})
    report = client.get(URL, params=RANGE).json()["cost_per_gain"]
    overall = report["overall"]
    assert overall["cost_usd"] == 0 and overall["per_active_student_month"] is None
    assert overall["per_session"] is None and _win(overall)["per_pair"] is None
    assert report["courses"] == []
