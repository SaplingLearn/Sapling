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
        if op == "in":  # values may be pg_quote_value-quoted
            return sval in [v.strip('"') for v in target.strip("()").split(",")]
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


def _evidence(i, *, node="n1", session, correct=True, assisted=False, max_rung=0,
              channel="free_response", p_before=None, weight=1.0):
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
        "channel": channel,
        "p_before": p_before,
        "weight": weight,
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
    assert b["caught_leaks"] == 1  # caught and redacted: never served (m5)
    assert b["served_reveals"] == 0 and b["unscanned_turns"] == 0
    assert b["ceiling_compliance"]["steps"] == params.BAND_WINDOW + 4
    assert b["ceiling_compliance"]["compliant"] == params.BAND_WINDOW + 3
    assert b["gates"] == {
        "zero_leaks": True,
        "ceiling_compliance_ok": False,
        "earnest_revise_ok": None,  # A109: no step carries the signal → inconclusive
    }
    assert b["unassisted_next_session"] == {
        "sessions": 2,
        "successes": 1,
        "rate": 0.5,
        "quiz_ask_excluded": 0,
    }
    trend = {t["concept_id"]: t for t in b["htc_k_trend"]}
    assert trend["c1"]["direction"] == "insufficient"  # one week with data
    assert b["truncated"] is False
    assert b["range"] == RANGE


def test_empty_range_is_nones_not_zeros(monkeypatch):
    monkeypatch.setattr(analytics, "table", lambda name: _FakeTable([]))
    b = client.get(URL, params=RANGE).json()
    assert b["in_band_share"] is None and b["ceiling_compliance"]["rate"] is None
    assert b["unassisted_next_session"]["rate"] is None
    assert b["gates"] == {
        "zero_leaks": True,
        "ceiling_compliance_ok": False,
        "earnest_revise_ok": None,  # A109: no step carries the signal → inconclusive
    }
    assert b["htc_k_trend"] == []


@pytest.mark.parametrize(
    "value,expected",
    [
        ("H3", 3),
        (3, 3),
        ("h0", 0),
        (None, None),
        ("x", None),
        (True, None),
        ("H9", None),
        (-1, None),
    ],
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
    assert analytics._next_session_rate(rows) == {
        "sessions": 1,
        "successes": 0,
        "rate": 0.0,
        "quiz_ask_excluded": 0,
    }


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
    assert by_table["events"]["event_type"] == "in.(zpd.step,zpd.leak,zpd.reveal)"
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


def _reveal_event(hashes, *, unscanned=False):
    return {
        "event_type": "zpd.reveal",
        "category": "usage",
        "user_id": "u1",
        "request_id": "t",
        "payload": {
            "question_hashes": hashes,
            "count": len(hashes),
            "unscanned": unscanned,
            "phase": "teach",
            "session_id": "s1",
        },
        "created_at": "2026-07-12T00:00:00+00:00",
    }


def test_zero_leaks_gate_counts_served_solution_reveals(monkeypatch):
    """Spec §13 A90 (m5): zpd.leak is a leak CAUGHT on the active item and
    redacted before serving, so it never turns the gate red; the gate counts
    the open posed items whose answer a served turn stated (zpd.reveal hashes)."""
    store = {
        "events": [_reveal_event(["q1", "q2"]), _reveal_event([], unscanned=True)],
        "node_mastery_events": [],
    }
    _serve(monkeypatch, store)
    b = client.get(URL, params=RANGE).json()
    assert b["caught_leaks"] == 0
    assert b["served_reveals"] == 2 and b["unscanned_turns"] == 1
    assert b["gates"]["zero_leaks"] is (2 <= params.GATE_LEAKS_MAX)


def test_caught_leaks_alone_keep_the_gate_green(monkeypatch):
    leak = {
        "event_type": "zpd.leak",
        "category": "error",
        "user_id": "u1",
        "request_id": "t",
        "payload": {"rung_emitted": 3, "ceiling": 3, "detector": "exact", "request_id": "t"},
        "created_at": "2026-07-12T00:00:00+00:00",
    }
    _serve(monkeypatch, {"events": [leak, leak], "node_mastery_events": []})
    b = client.get(URL, params=RANGE).json()
    assert b["caught_leaks"] == 2 and b["served_reveals"] == 0
    assert b["gates"]["zero_leaks"] is True


# ── PKG-14/15 review m2 (spec §13 A106): quiz-ask sessions are not sessions here ──


def test_quiz_ask_sessions_are_excluded_from_the_next_session_rate(seeded):
    seeded["sessions"] = [
        {"id": "s2", "loop_state->>origin": "quiz_ask", "started_at": "2026-07-10T00:00:00+00:00"}
    ]
    b = client.get(URL, params=RANGE).json()
    # s1 → s3 (s2, a probe-less quiz-ask session, is not a session of the KPI)
    assert b["unassisted_next_session"] == {
        "sessions": 1,
        "successes": 0,
        "rate": 0.0,
        "quiz_ask_excluded": 1,
    }


def test_the_quiz_ask_read_names_the_origin_marker(monkeypatch):
    calls = []

    class _Rec(_FakeTable):
        def __init__(self, name):
            super().__init__([])
            self.name = name

        def select_with_count(self, columns="*", filters=None, **kw):
            calls.append((self.name, filters))
            return [], 0

    monkeypatch.setattr(analytics, "table", _Rec)
    assert client.get(URL, params=RANGE).status_code == 200
    (filters,) = [f for n, f in calls if n == "sessions"]
    assert filters["loop_state->>origin"] == "eq.quiz_ask"


# ── earnest-revise (spec §10 gate, §13 A109) ─────────────────────────────────


def _earnest_step(i, blocked, *, phase="check"):
    row = _step(i, phase=phase)
    row["payload"]["earnest_blocked"] = blocked
    return row


def test_earnest_revise_rate_and_gate(monkeypatch):
    events = [_earnest_step(0, True)] + [_earnest_step(i, False) for i in range(1, 20)]
    events.append(_step(40))  # a pre-A109 step: no key → unmeasured, not a zero
    events.append(_earnest_step(41, False, phase="posttest"))  # never reaches /hint
    _serve(monkeypatch, {"events": events})
    b = client.get(URL, params=RANGE).json()
    assert b["earnest_revise"] == {
        "graded_steps": 20,
        "earnest_blocked": 1,
        "unmeasured_steps": 1,
        "rate": pytest.approx(0.05),
        "gate": "pass",
    }
    assert b["gates"]["earnest_revise_ok"] is True


def test_earnest_revise_gate_fails_above_the_max(monkeypatch):
    events = [_earnest_step(0, True), _earnest_step(1, True)]
    events += [_earnest_step(i, False) for i in range(2, 20)]
    _serve(monkeypatch, {"events": events})
    b = client.get(URL, params=RANGE).json()
    assert b["earnest_revise"]["rate"] == pytest.approx(0.1)
    assert b["earnest_revise"]["gate"] == "fail"
    assert b["gates"]["earnest_revise_ok"] is (0.1 <= params.GATE_EARNEST_REVISE_MAX)


def test_earnest_revise_without_graded_steps_is_inconclusive(monkeypatch):
    monkeypatch.setattr(analytics, "table", lambda name: _FakeTable([]))
    b = client.get(URL, params=RANGE).json()
    assert b["earnest_revise"]["rate"] is None
    assert b["earnest_revise"]["gate"] == "inconclusive"
    assert b["gates"]["earnest_revise_ok"] is None, "inconclusive, never a pass"


def test_calibration_reports_bkt_predictions_against_unassisted_outcomes(monkeypatch):
    evidence = [
        _evidence(1, session=None, correct=True, p_before=0.95),  # post-test, came true
        _evidence(2, session=None, correct=False, p_before=0.95),  # post-test, did not
        _evidence(3, session="s1", correct=True, p_before=0.4),  # in-session, independent
        _evidence(4, session="s1", correct=True, p_before=0.4, assisted=True),  # helped
        _evidence(5, session="s1", correct=True, p_before=0.4, channel="mc"),  # weak
    ]
    _serve(monkeypatch, {"events": [], "node_mastery_events": evidence})
    b = client.get(URL, params=RANGE).json()
    cal = b["calibration"]
    assert cal["all"]["n"] == 3
    assert cal["posttest"]["n"] == 2
    assert cal["posttest"]["observed_rate"] == pytest.approx(0.5)
    assert cal["posttest"]["brier"] is not None
    assert len(cal["all"]["bins"]) == params.CALIBRATION_BINS


def test_calibration_is_empty_not_zero_without_independent_evidence(monkeypatch):
    monkeypatch.setattr(analytics, "table", lambda name: _FakeTable([]))
    cal = client.get(URL, params=RANGE).json()["calibration"]
    assert cal["all"]["n"] == 0 and cal["all"]["brier"] is None
    assert cal["posttest"]["observed_rate"] is None


def test_the_evidence_scan_reads_the_calibration_columns(monkeypatch):
    calls = []

    class _Rec(_FakeTable):
        def __init__(self, name):
            super().__init__([])
            self.name = name

        def select_with_count(self, columns="*", filters=None, **kw):
            calls.append((self.name, columns))
            return [], 0

    monkeypatch.setattr(analytics, "table", _Rec)
    assert client.get(URL, params=RANGE).status_code == 200
    cols = dict(calls)["node_mastery_events"].split(",")
    assert {"channel", "p_before", "weight"} <= set(cols)
    # spec §13 A127: the students' stated confidence, never the grader's alone
    assert "student_confidence" in cols


def test_confidence_calibration_reports_stated_confidence_per_channel(monkeypatch):
    """Spec §13 A127: stated confidence against correctness, per channel, over
    the same evidence scan; an answer with none stated is no row of it."""
    sure, guessing = (params.STUDENT_CONFIDENCE_LEVELS[k] for k in ("sure", "guessing"))
    evidence = [
        {**_evidence(1, session="s1", correct=True), "student_confidence": sure},
        {**_evidence(2, session="s1", correct=False), "student_confidence": sure},
        {**_evidence(3, session="s1", correct=False, channel="mc_reasoned"),
         "student_confidence": guessing},
        _evidence(4, session="s1", correct=True),  # none stated
    ]
    _serve(monkeypatch, {"events": [], "node_mastery_events": evidence})
    cc = client.get(URL, params=RANGE).json()["confidence_calibration"]
    assert cc["all"]["n"] == 3 and cc["all"]["observed_rate"] == pytest.approx(1 / 3)
    assert cc["all"]["overconfidence"] == pytest.approx((2 * sure + guessing) / 3 - 1 / 3)
    assert [c["channel"] for c in cc["channels"]] == ["free_response", "mc_reasoned"]
    free = {lv["level"]: lv for lv in cc["channels"][0]["levels"]}
    assert (free["sure"]["n"], free["sure"]["correct"], free["sure"]["observed"]) == (2, 1, 0.5)
    assert free["guessing"]["n"] == 0 and free["guessing"]["observed"] is None


def test_confidence_calibration_leaves_out_void_evidence(monkeypatch):
    """A123 × A127: the one void rule covers the confidence calibration too. A
    confidence stated on a grade against an item staff retired measures
    nothing about the student, so the row is left out, as it is from the BKT
    calibration beside it; the same item in another course, and a quiz row,
    stay."""
    sure = params.STUDENT_CONFIDENCE_LEVELS["sure"]

    def row(i, *, course, qh, correct, item=True):
        return {**_evidence(i, session=f"s{i}", correct=correct, p_before=0.6),
                "student_confidence": sure,
                "question_hash": qh, "check_item_id": f"ci-{qh}" if item else None,
                "graph_nodes": {"course_id": course}}

    evidence = [
        row(0, course="c1", qh="q-bad", correct=False),  # void
        row(1, course="c1", qh="q-ok", correct=True),
        row(2, course="c2", qh="q-bad", correct=True),  # another course's item
    ]
    _serve(monkeypatch, {"events": [], "node_mastery_events": evidence})
    monkeypatch.setattr(analytics, "retired_items", lambda: {("c1", "q-bad")})
    body = client.get(URL, params=RANGE).json()
    cc = body["confidence_calibration"]
    assert cc["all"]["n"] == 2 and cc["all"]["observed_rate"] == 1.0
    assert body["calibration"]["excluded_void"] == 1
    monkeypatch.setattr(analytics, "retired_items", lambda: set())
    cc = client.get(URL, params=RANGE).json()["confidence_calibration"]
    assert cc["all"]["n"] == 3


def test_confidence_calibration_is_empty_not_zero(monkeypatch):
    monkeypatch.setattr(analytics, "table", lambda name: _FakeTable([]))
    cc = client.get(URL, params=RANGE).json()["confidence_calibration"]
    assert cc["channels"] == [] and cc["all"]["n"] == 0
    assert cc["all"]["observed_rate"] is None and cc["all"]["brier"] is None


# ── spec §13 A112: the pre/post learning gain per fixed post-test window ──────

W1, W2 = params.POSTTEST_WINDOWS_DAYS


def _anchor(event_id, *, session, qh, correct, node="n1"):
    """A concept's first evidence row as the single graph writer journals it,
    with the REAL planning envelope (a probe or an in-session check grade)."""
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
    }  # no created_at: outside the evidence scan, read only by id


def _answered(node, window, *, correct, anchor, rung=0, days=10.0):
    return {
        "user_id": "u1", "node_id": node, "window_days": window, "correct": correct,
        "max_rung": rung, "anchor_event_id": anchor, "days_since_evidence": days,
        "answered_at": "2026-07-20T00:00:00+00:00",
    }


def test_learning_gain_is_empty_not_zero_without_post_tests(monkeypatch):
    monkeypatch.setattr(analytics, "table", lambda name: _FakeTable([]))
    gain = client.get(URL, params=RANGE).json()["learning_gain"]
    assert gain["delayed_min_days"] == params.POSTTEST_DELAYED_MIN_DAYS
    assert [w["window_days"] for w in gain["windows"]] == list(params.POSTTEST_WINDOWS_DAYS)
    for w in gain["windows"]:
        assert w["n"] == 0 and w["posttests"] == 0
        assert w["pre_correct_rate"] is None and w["post_correct_rate"] is None
        assert w["paired_difference"] is None and w["delayed"]["n"] == 0


def test_learning_gain_pairs_the_probe_pretest_with_each_window(monkeypatch):
    """Only an anchor its session's PROBE history names is a pretest (a check
    after teaching carries planning provenance too); only an unassisted post-test
    is an outcome; the delayed stratum needs ≥ delayed_min_days without evidence."""
    anchors = [
        _anchor("ev-a", session="s1", qh="qa", correct=False, node="na"),
        _anchor("ev-b", session="s1", qh="qb", correct=True, node="nb"),
        _anchor("ev-c", session="s2", qh="qc", correct=False, node="nc"),  # a check
    ]
    sessions = [
        {"id": "s1", "history": [{"question_hash": "qa"}, {"question_hash": "qb"}]},
        {"id": "s2", "history": [{"question_hash": "q-something-else"}]},
    ]
    poses = [
        _answered("na", W1, correct=True, anchor="ev-a", days=9.0),  # improved, delayed
        _answered("nb", W1, correct=True, anchor="ev-b", days=0.5),  # same, recently practised
        _answered("nc", W1, correct=True, anchor="ev-c"),  # no pretest: anchored on a check
        _answered("na", W2, correct=False, anchor="ev-a", rung=params.RUNG_NO_CREDIT_MIN),
        {**_answered("nb", W2, correct=False, anchor="ev-b"), "answered_at": "2026-09-01"},
    ]
    _serve(monkeypatch, {"events": [], "node_mastery_events": anchors, "sessions": sessions,
                         "posttest_poses": poses})
    b = client.get(URL, params=RANGE).json()
    gain = {w["window_days"]: w for w in b["learning_gain"]["windows"]}
    first = gain[W1]
    assert first["posttests"] == 3 and first["n"] == 2
    assert first["pre_correct_rate"] == pytest.approx(0.5)
    assert first["post_correct_rate"] == pytest.approx(1.0)
    assert first["paired_difference"] == pytest.approx(0.5)
    assert (first["improved"], first["same"], first["worse"]) == (1, 1, 0)
    assert first["delayed"]["n"] == 1 and first["delayed"]["improved"] == 1
    second = gain[W2]  # a no-credit grade is no outcome; September is outside the range
    assert second["posttests"] == 0 and second["n"] == 0 and second["pre_correct_rate"] is None
    assert b["calibration"]["all"]["n"] == 0  # the anchors are not in-range evidence rows


def test_the_pretest_reads_are_bounded_to_the_anchors_and_their_sessions(monkeypatch):
    calls = []
    store = {
        "node_mastery_events": [_anchor("ev-a", session="s1", qh="qa", correct=False)],
        "sessions": [{"id": "s1", "history": [{"question_hash": "qa"}]}],
        "posttest_poses": [
            _answered("n1", W1, correct=True, anchor="ev-a"),
            _answered("n2", W1, correct=True, anchor="ev-z", rung=1),  # no outcome: never read
        ],
    }

    class _Rec(_FakeTable):
        def __init__(self, name):
            super().__init__(store.get(name, []))
            self.name = name

        def select(self, columns="*", filters=None, order=None, limit=None):
            calls.append((self.name, columns, dict(filters or {})))
            return super().select(columns, filters, order, limit)

    monkeypatch.setattr(analytics, "table", _Rec)
    assert client.get(URL, params=RANGE).status_code == 200
    reads = {name: f for name, _, f in calls if "id" in f}
    assert reads["node_mastery_events"]["id"] == 'in.("ev-a")'
    assert reads["sessions"]["id"] == 'in.("s1")'
    (columns,) = [c for n, c, f in calls if n == "sessions" and "id" in f]
    assert "loop_state->probe->history" in columns  # the probe history only, not all of loop_state


def test_no_pretest_read_without_an_unassisted_outcome(monkeypatch):
    calls = []

    class _Rec(_FakeTable):
        def __init__(self, name):
            rows = [_answered("n1", W1, correct=True, anchor="ev-a", rung=4)]
            super().__init__(rows if name == "posttest_poses" else [])
            self.name = name

        def select(self, columns="*", filters=None, order=None, limit=None):
            calls.append((self.name, dict(filters or {})))
            return super().select(columns, filters, order, limit)

    monkeypatch.setattr(analytics, "table", _Rec)
    assert client.get(URL, params=RANGE).status_code == 200
    assert not [c for c in calls if "id" in c[1]]
    assert not [c for c in calls if c[0] == "check_item_reviews"]  # A113: nor a retire read


def test_the_pose_scan_bounds_answered_at_and_counts_toward_truncation(monkeypatch):
    calls = []

    class _Rec(_FakeTable):
        def __init__(self, name):
            super().__init__([])
            self.name = name

        def select_with_count(self, columns="*", filters=None, **kw):
            calls.append((self.name, columns, filters, kw.get("order")))
            return [], 0

    monkeypatch.setattr(analytics, "table", _Rec)
    assert client.get(URL, params=RANGE).status_code == 200
    (scan,) = [c for c in calls if c[0] == "posttest_poses"]
    assert scan[2]["answered_at"] == [f"gte.{RANGE['from']}", f"lte.{RANGE['to']}"]
    assert {"window_days", "correct", "max_rung", "anchor_event_id", "days_since_evidence"} <= set(
        scan[1].split(",")
    )
    assert {"course_id", "question_hash"} <= set(scan[1].split(","))  # the item an A113 retire keys
    assert scan[3].startswith("answered_at.asc")
    monkeypatch.setattr(analytics, "_SCAN_CAP", 1)
    monkeypatch.setattr(analytics, "_PAGE", 1)
    two = [_answered("n1", W1, correct=True, anchor="a"), _answered("n2", W1, correct=True, anchor="b")]
    _serve(monkeypatch, {"posttest_poses": two})
    assert client.get(URL, params=RANGE).json()["truncated"] is True


# ── A112 × A113: an outcome on an item retired as broken is no measurement ───


def _asked(node, window, *, course, qh, correct=True, anchor="ev-a", rung=0, days=10.0):
    """An answered pose with the course item it asked."""
    pose = _answered(node, window, correct=correct, anchor=anchor, rung=rung, days=days)
    return {**pose, "course_id": course, "question_hash": qh}


def _review(course, qh, status, decided_by):
    """A check_item_reviews row as A113's SQL functions write it."""
    return {
        "course_id": course, "question_hash": qh, "status": status, "decided_by": decided_by,
        "reviewed_by": "admin-1" if decided_by == "admin" else None,
        "reviewed_at": "2026-07-25T00:00:00+00:00",
    }


def _windows(monkeypatch, store, calls=None) -> dict:
    """GET the KPIs over `store`; the gain windows by window_days. `calls`, when
    given, records every `select` as (table, columns, filters)."""

    class _Rec(_FakeTable):
        def __init__(self, name):
            super().__init__(store.get(name, []))
            self.name = name

        def select(self, columns="*", filters=None, order=None, limit=None):
            if calls is not None:
                calls.append((self.name, columns, dict(filters or {})))
            return super().select(columns, filters, order, limit)

    monkeypatch.setattr(analytics, "table", _Rec)
    r = client.get(URL, params=RANGE)
    assert r.status_code == 200, r.text
    return {w["window_days"]: w for w in r.json()["learning_gain"]["windows"]}


def test_an_outcome_on_a_retired_item_is_excluded_and_counted(monkeypatch):
    """Spec §13 A123, the one void rule: a post-test outcome whose item STAFF
    retired — even while its void and delete are still pending and the item
    row remains — is left out of its window and counted in
    `excluded_retired`; a QUARANTINED item (its reporters' decision, pending
    staff) is no retire and its outcome stays; the same hash in another course
    is another item. The retired items are ONE read of the structured record,
    and a retired outcome's anchor is never read for a pretest."""
    calls: list = []
    store = {
        "node_mastery_events": [_anchor("ev-a", session="s1", qh="qa", correct=False)],
        "sessions": [{"id": "s1", "history": [{"question_hash": "qa"}]}],
        "posttest_poses": [
            _asked("na", W1, course="c1", qh="q-quarantined", anchor="ev-a"),
            _asked("nb", W1, course="c1", qh="q-admin", anchor="ev-b"),
            _asked("nc", W1, course="c2", qh="q-admin", anchor="ev-a"),
        ],
        "check_items": [{"id": "ci-1", "course_id": "c1", "question_hash": "q-admin"}],  # pending
    }
    reads = []
    monkeypatch.setattr(
        analytics, "retired_items", lambda: reads.append("retired") or {("c1", "q-admin")}
    )
    gain = _windows(monkeypatch, store, calls)
    first = gain[W1]
    assert (first["posttests"], first["excluded_retired"]) == (2, 1)
    assert first["n"] == 2 and first["improved"] == 2  # both stand, paired with the probe
    assert gain[W2]["excluded_retired"] == 0
    assert reads == ["retired"]
    anchors = [f["id"] for name, _, f in calls if name == "node_mastery_events" and "id" in f]
    assert anchors == ['in.("ev-a")']  # ev-b anchors only a retired outcome: never read


def test_calibration_and_next_session_success_leave_out_void_evidence(monkeypatch):
    """The calibration bug A123 fixes: the learning gain left out a retired
    item's outcomes while the calibration beside it read every row. Now both
    apply the one rule — an observation graded against a staff-retired item is
    void — and the calibration counts what it left out (`excluded_void`). Its
    course is the node's (the scan's graph_nodes embed); a quiz row (no check
    item) and the same hash in another course are never void."""
    def row(i, *, course, qh, item=True, **kw):
        return {**_evidence(i, session=f"s{i}", p_before=0.6, **kw), "question_hash": qh,
                "check_item_id": f"ci-{qh}" if item else None, "graph_nodes": {"course_id": course}}

    evidence = [
        row(0, course="c1", qh="q-bad", correct=False),  # void
        row(1, course="c1", qh="q-ok", correct=True),
        row(2, course="c2", qh="q-bad", correct=True),  # another course's item
        row(3, course="c1", qh="q-bad", item=False, channel="mc", correct=True),  # a quiz question
    ]
    _serve(monkeypatch, {"node_mastery_events": evidence})
    monkeypatch.setattr(analytics, "retired_items", lambda: {("c1", "q-bad")})
    body = client.get(URL, params=RANGE).json()
    calibration = body["calibration"]
    assert calibration["all"]["n"] == 2 and calibration["excluded_void"] == 1
    assert calibration["all"]["observed_rate"] == 1.0  # the void miss is not judged
    monkeypatch.setattr(analytics, "retired_items", lambda: set())
    body = client.get(URL, params=RANGE).json()
    assert body["calibration"]["all"]["n"] == 3 and body["calibration"]["excluded_void"] == 0


def test_next_session_success_opens_on_the_first_valid_row(monkeypatch):
    """The same rule for unassisted next-session success: a void row (graded
    against a staff-retired item) is no opportunity, so a session whose first
    row is void opens on the row after it."""
    def row(i, *, session, qh, correct):
        return {**_evidence(i, session=session, correct=correct), "question_hash": qh,
                "check_item_id": f"ci-{qh}", "graph_nodes": {"course_id": "c1"}}

    evidence = [
        row(0, session="s1", qh="q-ok", correct=True),
        row(1, session="s2", qh="q-bad", correct=False),  # void: s2's first row were it counted
        row(2, session="s2", qh="q-ok2", correct=True),
    ]
    _serve(monkeypatch, {"node_mastery_events": evidence})
    monkeypatch.setattr(analytics, "retired_items", lambda: {("c1", "q-bad")})
    nxt = client.get(URL, params=RANGE).json()["unassisted_next_session"]
    assert (nxt["sessions"], nxt["successes"]) == (1, 1)
    monkeypatch.setattr(analytics, "retired_items", lambda: set())
    nxt = client.get(URL, params=RANGE).json()["unassisted_next_session"]
    assert (nxt["sessions"], nxt["successes"]) == (1, 0)


def test_a_void_pretest_anchor_is_no_pretest(monkeypatch):
    """The concept's first evidence (the post-test anchor) was a probe grade on
    an item staff retired since: no pretest — the pair is dropped, the
    post-test outcome itself (another item) still counts."""
    store = {
        "node_mastery_events": [_anchor("ev-a", session="s1", qh="qa", correct=False)],
        "sessions": [{"id": "s1", "history": [{"question_hash": "qa"}]}],
        "posttest_poses": [_asked("na", W1, course="c1", qh="q-post", anchor="ev-a")],
    }
    monkeypatch.setattr(analytics, "retired_items", lambda: {("c1", "qa")})
    first = _windows(monkeypatch, store)[W1]
    assert (first["posttests"], first["n"], first["excluded_retired"]) == (1, 0, 0)
    monkeypatch.setattr(analytics, "retired_items", lambda: set())
    assert _windows(monkeypatch, store)[W1]["n"] == 1


def test_an_outcome_on_a_reported_but_unretired_item_is_still_counted(monkeypatch):
    """A report alone (the item pending review) or a staff approval is no
    retire: the outcomes stay counted and nothing is excluded."""
    reports = [
        {"user_id": u, "course_id": "c1", "question_hash": qh, "reason": "wrong_answer",
         "surface": "loop", "created_at": "2026-07-21T00:00:00+00:00"}
        for u, qh in (("u2", "q-approved"), ("u3", "q-approved"), ("u2", "q-pending"))
    ]
    store = {
        "posttest_poses": [
            _asked("na", W1, course="c1", qh="q-approved"),
            _asked("nb", W1, course="c1", qh="q-pending"),
        ],
        "check_item_reports": reports,
        "check_item_reviews": [_review("c1", "q-approved", "approved", "admin")],
    }
    first = _windows(monkeypatch, store)[W1]
    assert (first["posttests"], first["excluded_retired"]) == (2, 0)


def test_an_outcome_on_a_consent_withdrawn_item_is_still_counted(monkeypatch):
    """A23's consent withdrawal deletes item rows too, and writes no review
    record: an item merely gone is no retire, and its outcome stays counted."""
    store = {
        "posttest_poses": [_asked("na", W1, course="c1", qh="q-withdrawn")],
        "check_items": [],  # withdrawn: the row is gone
        "check_item_reviews": [],
    }
    first = _windows(monkeypatch, store)[W1]
    assert (first["posttests"], first["excluded_retired"]) == (1, 0)


# ── spec §13 A126: the funnel, the intervals, the delay bins, visibility ──────

from datetime import datetime, timedelta, timezone  # noqa: E402

START = datetime.fromisoformat(RANGE["from"])
END = datetime.fromisoformat(RANGE["to"])


def _anchors(rows, *, calls=None, truncated=False):
    def read(**kw):
        if calls is not None:
            calls.append(kw)
        return list(rows), truncated

    return read


def test_the_funnel_counts_the_windows_that_opened_in_the_range(monkeypatch):
    """Every due window — opened in the range — is answered, expired, open,
    skipped (by reason) or never opened; the anchors read asks for exactly the
    anchors whose windows can open in the range."""
    day = timedelta(days=1)
    opens_in_range = START + 5 * day - W1 * day  # W1 opens on July 6
    anchors = [
        {"user_id": "u1", "node_id": n, "course_id": "c1", "anchor_at": opens_in_range.isoformat()}
        for n in ("answered", "expired", "skipped", "never")
    ] + [{"user_id": "u2", "node_id": "late", "course_id": "c1",
          "anchor_at": (END + day - W1 * day).isoformat()}]  # opens after the range
    calls: list = []
    monkeypatch.setattr(analytics, "posttest_anchors", _anchors(anchors, calls=calls))
    posed = (opens_in_range + W1 * day).isoformat()
    store = {
        "posttest_poses": [
            {"user_id": "u1", "node_id": "answered", "window_days": W1, "posed_at": posed,
             "answered_at": posed, "correct": True, "max_rung": 0},
            {"user_id": "u1", "node_id": "expired", "window_days": W1, "posed_at": posed,
             "answered_at": None},
        ],
        "posttest_skips": [
            {"user_id": "u1", "node_id": "skipped", "window_days": W1, "reason": "exhausted"},
        ],
    }
    _serve(monkeypatch, store)
    body = client.get(URL, params=RANGE).json()
    funnel = {w["window_days"]: w for w in body["learning_gain"]["funnel"]}
    first = funnel[W1]
    assert (first["due"], first["opened"], first["answered"], first["unassisted"]) == (4, 2, 1, 1)
    assert (first["expired"], first["open"], first["skipped"], first["not_opened"]) == (1, 0, 1, 1)
    assert first["skip_reasons"] == {"no_items": 0, "exhausted": 1, "reported": 0}
    # the same four concepts' 28-day windows open on July 27 — in the range too,
    # never posed; u2's windows open after the range
    assert (funnel[W2]["due"], funnel[W2]["not_opened"]) == (4, 4)
    (read,) = calls
    assert read["anchor_from"] == START - timedelta(days=W2)
    assert read["anchor_to"] == END - timedelta(days=W1)
    assert read.get("user_id") is None and read["limit"] == analytics._SCAN_CAP


def test_the_funnel_applies_the_void_rule_with_the_reports_one_retired_read(monkeypatch):
    """A123 × A126: an answered funnel pose on an item staff retired is counted
    in the funnel's `excluded_retired`, never in `answered`; the funnel reads
    the item it asked, and the report reads the retired items once for all of
    its parts."""
    day = timedelta(days=1)
    opens_in_range = START + 5 * day - W1 * day
    anchors = [
        {"user_id": "u1", "node_id": n, "course_id": "c1", "anchor_at": opens_in_range.isoformat()}
        for n in ("void", "kept")
    ]
    monkeypatch.setattr(analytics, "posttest_anchors", _anchors(anchors))
    posed = (opens_in_range + W1 * day).isoformat()
    answered = {"window_days": W1, "posed_at": posed, "answered_at": posed, "correct": True,
                "max_rung": 0, "course_id": "c1", "user_id": "u1"}
    store = {"posttest_poses": [{**answered, "node_id": "void", "question_hash": "q-bad"},
                                {**answered, "node_id": "kept", "question_hash": "q-ok"}]}
    _serve(monkeypatch, store)
    reads = []
    monkeypatch.setattr(analytics, "retired_items", lambda: reads.append(1) or {("c1", "q-bad")})
    gain = client.get(URL, params=RANGE).json()["learning_gain"]
    first = {w["window_days"]: w for w in gain["funnel"]}[W1]
    assert (first["opened"], first["answered"], first["unassisted"]) == (2, 1, 1)
    assert first["excluded_retired"] == 1
    assert reads == [1]
    assert {"course_id", "question_hash"} <= set(analytics._FUNNEL_POSE_COLS.split(","))


def test_a_funnel_answer_alone_is_reason_enough_to_read_the_retired_items(monkeypatch):
    """The retired items are read only when there is an observation to judge:
    an answered funnel pose is one, even with no evidence row and no post-test
    answered in the range."""
    reads = []
    monkeypatch.setattr(analytics, "retired_items", lambda: reads.append(1) or set())
    assert analytics._void_items([], [], []) == set() and reads == []
    assert analytics._void_items([], [], [{"answered_at": None}]) == set() and reads == []
    analytics._void_items([], [], [{"answered_at": "2026-07-20T00:00:00+00:00"}])
    assert reads == [1]


def test_the_funnel_is_unknown_not_zero_when_the_anchors_cannot_be_read(monkeypatch):
    def _down(**_kw):
        raise RuntimeError("function missing: migration not applied")

    monkeypatch.setattr(analytics, "posttest_anchors", _down)
    _serve(monkeypatch, {})
    gain = client.get(URL, params=RANGE).json()["learning_gain"]
    assert gain["funnel"] is None
    assert [w["window_days"] for w in gain["windows"]] == list(params.POSTTEST_WINDOWS_DAYS)


def test_a_capped_anchor_read_marks_the_report_truncated(monkeypatch):
    monkeypatch.setattr(analytics, "posttest_anchors", _anchors([], truncated=True))
    _serve(monkeypatch, {})
    assert client.get(URL, params=RANGE).json()["truncated"] is True


def test_the_gain_report_carries_intervals_delay_bins_and_visibility(monkeypatch):
    anchors = [_anchor(f"ev-{i}", session="s1", qh=f"q{i}", correct=False, node=f"n{i}") for i in range(4)]
    sessions = [{"id": "s1", "history": [{"question_hash": f"q{i}"} for i in range(4)]}]
    anchor_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    poses = [
        {**_answered(f"n{i}", W1, correct=i != 3, anchor=f"ev-{i}"), "user_id": f"u{i % 2}",
         "anchor_at": anchor_at.isoformat(),
         "answered_at": (anchor_at + timedelta(days=8 + i)).isoformat(),
         "hidden_count": 1 if i == 0 else 0, "hidden_s": 12.0 if i == 0 else 0.0}
        for i in range(4)
    ]
    monkeypatch.setattr(analytics, "posttest_anchors", _anchors([]))
    _serve(monkeypatch, {"node_mastery_events": anchors, "sessions": sessions, "posttest_poses": poses})
    gain = client.get(URL, params=RANGE).json()["learning_gain"]
    first = gain["windows"][0]
    assert first["n"] == 4 and first["students"] == 2
    lo, hi = first["post_correct_ci"]
    assert 0.0 <= lo <= first["post_correct_rate"] <= hi <= 1.0
    assert first["paired_difference_ci"] is not None
    assert first["visibility_loss"]["n"] == 1 and first["visibility_unreported"] == 0
    assert gain["ci"]["method"] == "student_cluster_bootstrap_percentile"
    assert gain["ci"]["resamples"] == params.LEARNING_GAIN_BOOTSTRAP_RESAMPLES
    bins = {b["lo_days"]: b for b in gain["delay_bins"]}
    assert bins[7]["n"] == 4 and bins[14]["n"] == 0 and bins[42]["hi_days"] is None
    assert gain["delay_unknown"] == 0


def test_the_pose_scan_reads_the_delay_and_visibility_columns():
    cols = set(analytics._POSE_COLS.split(","))
    assert {"user_id", "anchor_at", "answered_at", "hidden_count", "hidden_s"} <= cols
