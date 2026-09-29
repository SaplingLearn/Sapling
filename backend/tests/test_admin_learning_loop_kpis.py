"""PKG-14: /api/admin/analytics/learning-loop — the three KPIs and two gates of spec §10."""

from __future__ import annotations

import fnmatch

import pytest
from fastapi.testclient import TestClient

import routes.admin_analytics as analytics
from learning import params
from main import app

client = TestClient(app)
URL = "/api/admin/analytics/learning-loop"
RANGE = {"from": "2026-07-01T00:00:00+00:00", "to": "2026-08-01T00:00:00+00:00"}


class _FakeTable:
    """Copy of tests/test_admin_analytics_routes.py::_FakeTable (never imported
    across test modules), plus the `in.(…)` op the KPI scans use."""

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
            return sval in target.strip("()").split(",")
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
        return sorted(
            rows, key=lambda r: (r.get(col) is None, r.get(col)), reverse=direction == "desc"
        )

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


def _step(
    i,
    *,
    user="u1",
    concept="c1",
    phase="check",
    correct=True,
    assisted=False,
    max_rung=0,
    ceiling="H3",
    day=10,
    month=7,
):
    return {
        "event_type": "zpd.step",
        "category": "usage",
        "user_id": user,
        "request_id": f"r{i}",
        "payload": {
            "concept_id": concept,
            "phase": phase,
            "first_attempt_correct": correct,
            "assisted": assisted,
            "max_rung_used": max_rung,
            "ceiling": ceiling,
        },
        "created_at": f"2026-{month:02d}-{day:02d}T00:{i:02d}:00+00:00",
    }


def _evidence(i, *, node="n1", session, correct=True, assisted=False, max_rung=0):
    return {
        "id": f"e{i}",
        "node_id": node,
        "event_type": "evidence",
        "session_id": session,
        "correct": correct,
        "assisted": assisted,
        "max_rung": max_rung,
        "question_hash": "q",
        "created_at": f"2026-07-10T01:{i:02d}:00+00:00",
    }


def _serve(monkeypatch, store):
    monkeypatch.setattr(analytics, "table", lambda name: _FakeTable(store.get(name, [])))


@pytest.fixture
def seeded(monkeypatch):
    W = params.BAND_WINDOW
    events = [_step(i, correct=True) for i in range(W)]  # 8 unassisted correct → window full
    events.append(_step(W, correct=True))  # rolling rate 1.0 > PRACTICE_TARGET_HI → out of band
    events.append(_step(W + 1, correct=False))  # rolling 1.0 still → out of band
    events.append(_step(30, user="u2", phase="teach"))  # no band → excluded
    events.append(_step(31, user="u2", max_rung=5, ceiling="H3"))  # ceiling breach
    events.append(
        {
            "event_type": "zpd.leak",
            "category": "error",
            "user_id": "u2",
            "request_id": "L",
            "payload": {"rung_emitted": "H6", "ceiling": "H3"},
            "created_at": "2026-07-12T00:00:00+00:00",
        }
    )
    events.append(  # another event type in range: never read as a step
        {
            "event_type": "quiz.completed",
            "category": "usage",
            "user_id": "u1",
            "request_id": "q",
            "payload": {},
            "created_at": "2026-07-12T00:00:00+00:00",
        }
    )
    evidence = [
        _evidence(0, session="s1"),
        _evidence(1, session="s1", correct=False),
        _evidence(2, session="s2", correct=True),
        _evidence(3, session="s3", correct=True, assisted=True, max_rung=2),
    ]
    store = {"events": events, "node_mastery_events": evidence, "learner_state": []}
    _serve(monkeypatch, store)
    return store


def test_kpis_shape_and_values(seeded):
    r = client.get(URL, params=RANGE)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "private"
    b = r.json()
    assert b["steps_total"] == params.BAND_WINDOW + 4
    assert b["banded_steps"] == 2 and b["in_band_share"] == pytest.approx(0.0)
    assert b["leak_count"] == 1
    assert b["ceiling_compliance"]["steps"] == params.BAND_WINDOW + 4
    assert b["ceiling_compliance"]["compliant"] == params.BAND_WINDOW + 3
    assert b["gates"] == {"zero_leaks": False, "ceiling_compliance_ok": False}
    assert b["unassisted_next_session"] == {"sessions": 2, "successes": 1, "rate": 0.5}
    trend = {t["concept_id"]: t for t in b["htc_k_trend"]}
    assert trend["c1"]["direction"] == "insufficient"  # one week with data
    assert b["truncated"] is False
    assert b["range"] == RANGE


def test_empty_range_is_nones_not_zeros(monkeypatch):
    monkeypatch.setattr(analytics, "table", lambda name: _FakeTable([]))
    b = client.get(URL, params=RANGE).json()
    assert b["in_band_share"] is None and b["ceiling_compliance"]["rate"] is None
    assert b["unassisted_next_session"]["rate"] is None
    assert b["gates"] == {"zero_leaks": True, "ceiling_compliance_ok": False}
    assert b["htc_k_trend"] == []


@pytest.mark.parametrize(
    "value,expected",
    [("H3", 3), (3, 3), ("h0", 0), (None, None), ("x", None), (True, None), ("H9", None), (-1, None)],
)
def test_rung_int(value, expected):
    assert analytics._rung_int(value) == expected


def test_phase_band_mapping():
    assert analytics._phase_band("probe", False) == (params.PROBE_TARGET_LO, params.PROBE_TARGET_HI)
    assert analytics._phase_band("check", True) == (params.ACQ_TARGET_LO, params.ACQ_TARGET_HI)
    assert analytics._phase_band("check", False) == (
        params.PRACTICE_TARGET_LO,
        params.PRACTICE_TARGET_HI,
    )
    for p in ("teach", "feedback", "close", "plan", "posttest"):
        assert analytics._phase_band(p, False) is None


def test_in_band_share_counts_a_rolling_rate_inside_the_band():
    """Practice band 0.65–0.85: a window of 6/8 correct (0.75) is in band."""
    W = params.BAND_WINDOW
    steps = [_step(i, correct=i % 4 != 0) for i in range(W)] + [_step(W, correct=True)]
    rows = [dict(s) for s in steps]
    in_band, banded = analytics._in_band_share(rows)
    assert (in_band, banded) == (1, 1)


def test_windows_are_per_kind_and_per_student_concept():
    """Assisted and unassisted check steps never share a window; nor do students."""
    W = params.BAND_WINDOW
    steps = [_step(i, correct=True, assisted=True) for i in range(W)]
    steps += [_step(W + i, correct=True, assisted=False) for i in range(W - 1)]
    steps += [_step(40 + i, user="u2", correct=True, assisted=True) for i in range(W - 1)]
    steps.append(_step(59, correct=False, assisted=False))  # the 8th unassisted: 7 prior, unbanded
    assert analytics._in_band_share(steps) == (0, 0)


def test_ceiling_compliance_excludes_rows_missing_a_key():
    s1 = _step(1, max_rung=2, ceiling="H3")
    s2 = _step(2, max_rung=4, ceiling=3)  # numeric wire form
    s3 = _step(3)
    del s3["payload"]["ceiling"]
    out = analytics._ceiling_compliance([s1, s2, s3])
    assert out.steps == 2 and out.compliant == 1 and out.rate == pytest.approx(0.5)


def test_htc_k_trend_direction_over_weeks():
    """Mean max_rung_used over correct steps per ISO week; falling when the last
    week with data is below the first."""
    steps = [
        _step(1, max_rung=4, day=7),  # week of 2026-07-06
        _step(2, max_rung=2, day=8),
        _step(3, max_rung=1, day=21),  # week of 2026-07-20
        _step(4, max_rung=6, correct=False, day=22),  # incorrect: not counted
        _step(5, concept="c2", max_rung=1, day=7),
        _step(6, concept="c2", max_rung=3, day=28),
    ]
    trend = {t.concept_id: t for t in analytics._htc_k_trend(steps, RANGE["to"])}
    assert [(w.week_start, w.mean_rung) for w in trend["c1"].weeks] == [
        ("2026-07-06", pytest.approx(3.0)),
        ("2026-07-20", pytest.approx(1.0)),
    ]
    assert trend["c1"].direction == "falling"
    assert trend["c2"].direction == "rising"


def test_htc_k_trend_keeps_only_the_last_kpi_weeks():
    old = _step(1, max_rung=5, day=1, month=6)
    new = _step(2, max_rung=1, day=28)
    (t,) = analytics._htc_k_trend([old, new], RANGE["to"])
    assert [w.week_start for w in t.weeks] == ["2026-07-27"]
    assert len({w.week_start for w in t.weeks}) <= params.KPI_TREND_WEEKS


def test_next_session_rate_skips_rows_without_a_session():
    rows = [
        _evidence(0, session="s1"),
        _evidence(1, session=None),  # a post-test / quiz answer: no session
        _evidence(2, session="s2", correct=False),
        _evidence(3, node="n2", session="s9"),  # a node's only session is its first
    ]
    assert analytics._next_session_rate(rows) == {"sessions": 1, "successes": 0, "rate": 0.0}


def test_scans_ask_for_only_the_rows_they_need(monkeypatch):
    calls = []

    class _Rec(_FakeTable):
        def __init__(self, name):
            super().__init__([])
            self.name = name

        def select_with_count(self, columns="*", filters=None, **kw):
            calls.append((self.name, columns, filters))
            return [], 0

    monkeypatch.setattr(analytics, "table", _Rec)
    assert client.get(URL, params=RANGE).status_code == 200
    by_table = {n: f for n, _, f in calls}
    assert by_table["events"]["event_type"] == "in.(zpd.step,zpd.leak)"
    assert by_table["node_mastery_events"]["event_type"] == "eq.evidence"


def test_truncated_is_the_or_of_both_scans(monkeypatch):
    monkeypatch.setattr(analytics, "_SCAN_CAP", 1)
    monkeypatch.setattr(analytics, "_PAGE", 1)
    store = {
        "events": [_step(1), _step(2)],
        "node_mastery_events": [],
    }
    _serve(monkeypatch, store)
    assert client.get(URL, params=RANGE).json()["truncated"] is True


def test_requires_admin(monkeypatch):
    from services import auth_guard

    monkeypatch.setattr(analytics, "require_admin", auth_guard._real_require_admin)
    assert client.get(URL, params=RANGE).status_code in (401, 403)
