"""PKG-14 nightly ZPD metrics: pure compute + idempotent write through write_metrics
(spec §10 rung 2, ZPD report LOG block), plus the read-only cost and mix report."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from learning import params

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _script():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module("derive_zpd_metrics")


def _opp(correct, max_rung=0, assisted=False, qh="q"):
    return {
        "correct": correct,
        "max_rung": max_rung,
        "assisted": assisted,
        "question_hash": qh,
        "channel": "free_response",
    }


# ── compute (pure) ───────────────────────────────────────────────────────────


def test_compute_htc_k_is_mean_rung_over_correct_in_window():
    s = _script()
    opps = [
        _opp(True, 2),
        _opp(False, 3),
        _opp(True, 0),
        _opp(True, 4),
        _opp(True, 0),
        _opp(True, 6),
    ]
    out = s.compute(opps)
    # window = HTC_K_WINDOW newest → rungs of the correct ones: 2, 0, 4, 0 → 1.5
    assert params.HTC_K_WINDOW == 5
    assert out["htc_k"] == pytest.approx(1.5)


def test_compute_htc_k_none_without_a_correct_opportunity():
    s = _script()
    assert s.compute([_opp(False, 3)] * 3)["htc_k"] is None


def test_compute_unassisted_next_and_gap():
    s = _script()
    opps = (
        [_opp(True, 0, assisted=False)] * 3
        + [_opp(False, 0, assisted=False)] * 1
        + [_opp(True, 2, assisted=True)] * 3
        + [_opp(False, 3, assisted=True)] * 1
    )
    out = s.compute(opps)
    assert out["unassisted_next"] == pytest.approx(3 / 8)
    assert out["assist_gap"] == pytest.approx(0.75 - 0.75)
    assert out["in_zone"] is False


def test_compute_in_zone_true():
    s = _script()
    opps = (
        [_opp(True, 2, assisted=True)] * 4
        + [_opp(False, 0, assisted=False)] * 3
        + [_opp(True, 0, assisted=False)]
    )
    out = s.compute(opps)
    assert out["assist_gap"] == pytest.approx(1.0 - 0.25)
    assert out["in_zone"] is True


def test_compute_reads_only_the_band_window():
    """Opportunities past BAND_WINDOW (older) never move the window's shares."""
    s = _script()
    newest = [_opp(True, 0)] * params.BAND_WINDOW
    older = [_opp(False, 5, assisted=True)] * 4
    assert s.compute(newest + older) == s.compute(newest)


def test_compute_gap_none_when_one_side_is_empty():
    s = _script()
    out = s.compute([_opp(True, 0)] * 4)  # no assisted opportunity
    assert out["assist_gap"] is None and out["in_zone"] is None
    assert out["unassisted_next"] == pytest.approx(1.0)


def test_compute_unassisted_next_needs_rung_zero():
    """A correct, unassisted answer after an H1 hint is not an unassisted-next success."""
    s = _script()
    assert s.compute([_opp(True, 1, assisted=False)])["unassisted_next"] == pytest.approx(0.0)


def test_compute_empty_is_all_none():
    s = _script()
    assert s.compute([]) == {
        "htc_k": None,
        "unassisted_next": None,
        "assist_gap": None,
        "in_zone": None,
    }


def test_propagation_rows_are_not_opportunities():
    s = _script()
    rows = [{"correct": True, "max_rung": 0, "assisted": False, "question_hash": None}]
    assert s._opportunities(rows) == []


def test_compute_is_a_pure_function_of_the_events():
    s = _script()
    opps = [_opp(True, 2, assisted=True), _opp(False, 0), _opp(True, 0)]
    assert json.dumps(s.compute(opps), sort_keys=True) == json.dumps(
        s.compute(list(opps)), sort_keys=True
    )


# ── main: the derived-column pass ────────────────────────────────────────────


class _T:
    def __init__(self, rows, *, fail=None):
        self.rows, self.calls, self.fail = rows, [], fail

    def select(self, cols, filters=None, order=None, limit=None, offset=None):
        self.calls.append(("select", cols, filters, order, limit))
        if self.fail:
            raise self.fail
        return list(self.rows)

    def select_with_count(self, cols, filters=None, order=None, limit=None, offset=None):
        self.calls.append(("select_with_count", cols, filters, order, limit, offset))
        if self.fail:
            raise self.fail
        rows = list(self.rows)[offset or 0 : (offset or 0) + (limit or len(self.rows))]
        return rows, len(self.rows)


@pytest.fixture
def world(monkeypatch):
    """The script's reads, keyed by table; states come from learner_state's reader."""
    s = _script()
    w = {"states": [], "tables": {}, "written": [], "handles": {}, "coverage": {}}

    def _table(name):
        handle = w["handles"].get(name)
        if handle is None:
            spec = w["tables"].get(name, [])
            handle = spec if isinstance(spec, _T) else _T(spec)
            w["handles"][name] = handle
        return handle

    monkeypatch.setattr(s, "table", _table)
    monkeypatch.setattr(s, "opportunity_states", lambda user_id=None: list(w["states"]))
    monkeypatch.setattr(
        s, "write_metrics", lambda uid, nid, **kw: w["written"].append((uid, nid, kw))
    )
    monkeypatch.setattr(s, "coverage", lambda course_id: w["coverage"][course_id])
    w["s"] = s
    return w


def _ev(i, **kw):
    return dict(_opp(**{"correct": True, **kw}), created_at="2026-09-20T00:00:00+00:00", id=f"e{i}")


def test_main_writes_via_write_metrics_and_is_idempotent(world):
    s = world["s"]
    world["states"] = [{"user_id": "u", "node_id": "n", "opps": 3}]
    world["tables"]["node_mastery_events"] = [_ev(i) for i in range(3)]
    assert s.main([]) == 0
    assert s.main([]) == 0
    first, second = world["written"]
    assert first == second
    assert first[:2] == ("u", "n")
    assert first[2]["unassisted_next"] == pytest.approx(1.0)
    assert set(first[2]) == {"htc_k", "unassisted_next", "assist_gap", "in_zone"}


def test_evidence_read_is_the_nodes_journal_newest_first(world):
    s = world["s"]
    world["states"] = [{"user_id": "u", "node_id": "n", "opps": 1}]
    world["tables"]["node_mastery_events"] = [_ev(0)]
    assert s.main([]) == 0
    ((_, cols, filters, order, limit),) = [
        c for c in world["handles"]["node_mastery_events"].calls if c[0] == "select"
    ]
    # review fix round: opportunities only BEFORE the limit (a propagation-free
    # journal can still hold rows without a question_hash)
    assert filters == {
        "node_id": "eq.n",
        "event_type": "eq.evidence",
        "question_hash": "not.is.null",
    }
    # spec §13 A36: the apply order within one call is evidence_seq
    assert order == "created_at.desc,evidence_seq.desc.nullslast,id.desc"
    assert limit == max(params.BAND_WINDOW, params.HTC_K_WINDOW)
    assert "question_hash" in cols


def test_dry_run_writes_nothing(world, capsys):
    s = world["s"]
    world["states"] = [{"user_id": "u", "node_id": "n", "opps": 1}]
    world["tables"]["node_mastery_events"] = [_ev(0)]
    s.write_metrics = lambda *a, **k: pytest.fail("dry run must not write")
    assert s.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "(dry run)" in out
    assert "REPORT {" in out  # the cost/mix report is read-only, so a dry run prints it too


def test_zero_evidence_for_expected_rows_exits_2(world):
    s = world["s"]
    world["states"] = [{"user_id": "u", "node_id": "n", "opps": 5}]
    assert s.main([]) == 2


def test_some_evidence_is_not_a_keyspace_mismatch(world):
    s = world["s"]
    world["states"] = [
        {"user_id": "u", "node_id": "n", "opps": 5},
        {"user_id": "u", "node_id": "m", "opps": 5},
    ]
    handle = _T([])
    handle.select = lambda cols, filters=None, **kw: (
        [_ev(0)] if filters["node_id"] == "eq.n" else []
    )
    world["tables"]["node_mastery_events"] = handle
    assert s.main([]) == 0


def test_no_rows_is_ok_unless_expected(world, capsys):
    s = world["s"]
    assert s.main([]) == 0
    assert "0 rows" in capsys.readouterr().out
    assert s.main(["--expect-rows"]) == 2


def test_a_row_failure_is_reported_and_the_run_continues(world, capsys):
    s = world["s"]
    world["states"] = [
        {"user_id": "u", "node_id": "n", "opps": 1},
        {"user_id": "u", "node_id": "m", "opps": 1},
    ]
    world["tables"]["node_mastery_events"] = [_ev(0)]

    def _write(uid, nid, **kw):
        if nid == "n":
            raise RuntimeError("boom")
        world["written"].append((uid, nid, kw))

    s.write_metrics = _write
    assert s.main([]) == 1
    assert "FAIL u n RuntimeError" in capsys.readouterr().out
    assert [w[1] for w in world["written"]] == ["m"]


def test_user_flag_reaches_the_state_reader(world, monkeypatch):
    s = world["s"]
    seen = []
    monkeypatch.setattr(s, "opportunity_states", lambda user_id=None: seen.append(user_id) or [])
    assert s.main(["--user", "u9"]) == 0
    assert seen == ["u9"]


# ── the report (pure) ────────────────────────────────────────────────────────


def _usage(req, task, usd, day="20", user="u"):
    return {
        "id": f"{req}-{task}",
        "user_id": user,
        "request_id": req,
        "task": task,
        "cost_usd": usd,
        "created_at": f"2026-09-{day}T10:00:00+00:00",
    }


USAGE = [
    _usage("r1", "loop_tutor", "0.010"),
    _usage("r1", "grader", "0.001"),
    _usage("r2", "loop_tutor_deep", "0.030", day="21"),
    _usage(None, "check_items", "0.050", user=None),
    _usage("r3", "chat_tutor", "0.500"),  # not a series slot: excluded
]
STEPS = [
    {
        "user_id": "u",
        "request_id": "r1",
        "payload": {"band": "develop", "tier": "standard", "grader_backend": "gemini"},
    },
    {
        "user_id": "u",
        "request_id": "r9",
        "payload": {"band": "novice"},
    },  # no tier / grader_backend keys: not counted
]
CAPS = [
    {"payload": {"scope": "daily_usd", "level": "soft"}},
    {"payload": {"scope": "daily_usd", "level": "soft"}},
]


def test_report_bands_mixes_and_caps():
    out = _script().report(USAGE, STEPS, CAPS, sessions_by_request={})
    assert out["cost_per_band"] == {
        "develop": pytest.approx(0.011),
        "unknown": pytest.approx(0.030),
    }
    assert out["check_items_usd"] == pytest.approx(0.050)
    assert out["tier_mix"] == {"standard": 1}
    assert out["grader_backend_mix"] == {"gemini": 1}
    assert out["cap_hits"] == {"daily_usd/soft": 2}


def test_report_null_cost_counts_as_zero():
    out = _script().report([_usage("r1", "grader", None)], STEPS, [], sessions_by_request={})
    assert out["cost_per_band"] == {"develop": 0.0}


def test_report_never_guesses_a_band_for_a_request_with_two():
    steps = STEPS + [{"user_id": "u", "request_id": "r1", "payload": {"band": "novice"}}]
    out = _script().report([_usage("r1", "grader", "0.002")], steps, [], sessions_by_request={})
    assert out["cost_per_band"] == {"unknown": pytest.approx(0.002)}


def test_report_groups_per_session_and_falls_back_per_row():
    """Spec §13 A82: a loop row whose request maps to a session is costed per
    session; only a row with no session key (older rows, before zpd.step
    carried one) falls back to its user-day."""
    out = _script().report(
        USAGE, STEPS, CAPS, sessions_by_request={("u", "r1"): "s1"}
    )  # r2 unmapped
    assert out["cost_per_session"] == {"s1": pytest.approx(0.011)}
    assert out["cost_per_user_day"] == {"u/2026-09-21": pytest.approx(0.030)}


def test_report_uses_sessions_when_every_row_maps():
    out = _script().report(
        USAGE, STEPS, CAPS, sessions_by_request={("u", "r1"): "s1", ("u", "r2"): "s2"}
    )
    assert out["cost_per_session"] == {"s1": pytest.approx(0.011), "s2": pytest.approx(0.030)}
    assert out["cost_per_user_day"] == {}


def test_report_without_any_session_key_is_all_user_day():
    out = _script().report(USAGE, STEPS, CAPS, sessions_by_request={})
    assert out["cost_per_session"] == {}
    assert out["cost_per_user_day"] == {
        "u/2026-09-20": pytest.approx(0.011),
        "u/2026-09-21": pytest.approx(0.030),
    }


def test_sessions_by_request_reads_every_event_carrying_a_session():
    s = _script()
    events = [
        {"user_id": "u", "request_id": "r1", "payload": {"session_id": "s1"}},  # zpd.step (A82)
        {
            "user_id": "u",
            "request_id": "r2",
            "payload": {"mode": "socratic", "session_id": "s2"},
        },  # chat.message_sent
        {"user_id": "u", "request_id": "r3", "payload": {"band": "develop"}},  # no session
        {"user_id": "u", "request_id": None, "payload": {"session_id": "s9"}},  # no request
        {"user_id": None, "request_id": "r4", "payload": {"session_id": "s4"}},  # no user
    ]
    assert s.sessions_by_request(events) == {("u", "r1"): "s1", ("u", "r2"): "s2"}


def test_a_request_id_is_joined_only_with_its_own_user():
    """Review fix round: X-Request-ID is client-set, so a request id alone never
    joins — another user's events can neither band nor session this row."""
    s = _script()
    usage = [_usage("r1", "loop_tutor", "0.010", user="mallory")]
    steps = [{"user_id": "u", "request_id": "r1", "payload": {"band": "develop"}}]
    out = s.report(usage, steps, [], sessions_by_request={("u", "r1"): "s1"})
    assert out["cost_per_band"] == {"unknown": pytest.approx(0.010)}
    assert out["cost_per_session"] == {}
    assert out["cost_per_user_day"] == {"mallory/2026-09-20": pytest.approx(0.010)}


def test_series_slots_are_invariant_6():
    from tests.test_learning_loop_invariants import SERIES_AGENT_TASKS

    assert set(_script().SERIES_SLOTS) == {
        "check_items",
        "grader",
        "grader_second",
        "decision",
        "loop_tutor",
        "loop_tutor_lite",
        "loop_tutor_deep",
        "session_close",
    }
    assert set(_script().SERIES_SLOTS) == set(SERIES_AGENT_TASKS)


# ── main: the report reads ───────────────────────────────────────────────────


def _report_line(out: str) -> dict:
    (line,) = [ln for ln in out.splitlines() if ln.startswith("REPORT ")]
    return json.loads(line[len("REPORT ") :])


def test_main_prints_the_report_with_coverage(world, capsys):
    s = world["s"]
    world["tables"]["llm_usage"] = USAGE
    world["tables"]["events"] = [
        {
            "id": "x1",
            "event_type": "zpd.step",
            "user_id": "u",
            "request_id": "r1",
            "payload": {**STEPS[0]["payload"], "session_id": "s1"},
            "created_at": "2026-09-20T10:00:00+00:00",
        },
        {
            "id": "x2",
            "event_type": "ai.budget_capped",
            **CAPS[0],
            "created_at": "2026-09-20T10:00:00+00:00",
        },
        {
            "id": "x3",
            "event_type": "learn.session_closed",
            "request_id": "r1",
            "payload": {"session_id": "s1"},
            "created_at": "2026-09-20T11:00:00+00:00",
        },
    ]
    world["tables"]["graph_nodes"] = [{"course_id": "c1"}, {"course_id": "c2"}, {"course_id": "c1"}]
    world["coverage"] = {"c1": (1, 2), "c2": (0, 3)}
    assert s.main(["--from", "2026-09-01T00:00:00+00:00", "--to", "2026-10-01T00:00:00+00:00"]) == 0
    rep = _report_line(capsys.readouterr().out)
    assert rep["check_item_coverage"] == {"c1": [1, 2], "c2": [0, 3]}
    assert rep["cap_hits"] == {"daily_usd/soft": 1}
    assert rep["cost_per_session"] == {"s1": pytest.approx(0.011)}  # r1: zpd.step's session
    assert rep["cost_per_user_day"] == {"u/2026-09-21": pytest.approx(0.030)}  # r2 has none
    usage_call = [c for c in world["handles"]["llm_usage"].calls if c[0] == "select_with_count"][0]
    assert usage_call[2]["created_at"] == [
        "gte.2026-09-01T00:00:00+00:00",
        "lt.2026-10-01T00:00:00+00:00",
    ]
    assert usage_call[3] == "created_at,id"
    events_call = [c for c in world["handles"]["events"].calls if c[0] == "select_with_count"][0]
    assert (
        events_call[2]["event_type"]
        == "in.(zpd.step,ai.budget_capped,learn.session_closed,chat.message_sent)"
    )


def test_default_window_is_kpi_trend_weeks(world, monkeypatch):
    from datetime import datetime, timedelta, timezone

    s = world["s"]
    now = datetime(2026, 9, 29, tzinfo=timezone.utc)
    monkeypatch.setattr(s, "_now", lambda: now)
    assert s.main([]) == 0
    call = [c for c in world["handles"]["llm_usage"].calls if c[0] == "select_with_count"][0]
    assert call[2]["created_at"] == [
        f"gte.{(now - timedelta(weeks=params.KPI_TREND_WEEKS)).isoformat()}",
        f"lt.{now.isoformat()}",
    ]


@pytest.mark.parametrize("failing", ["llm_usage", "events"])
def test_a_report_read_error_is_exit_1_and_the_pass_still_runs(world, capsys, failing):
    s = world["s"]
    world["states"] = [{"user_id": "u", "node_id": "n", "opps": 1}]
    world["tables"]["node_mastery_events"] = [_ev(0)]
    world["tables"][failing] = _T([], fail=RuntimeError("down"))
    assert s.main([]) == 1
    out = capsys.readouterr().out
    assert f"REPORT_FAIL {failing} RuntimeError" in out
    assert world["written"], "the derived-column pass still ran"


def test_a_coverage_read_error_is_exit_1(world, capsys, monkeypatch):
    s = world["s"]
    world["tables"]["graph_nodes"] = [{"course_id": "c1"}]

    def _boom(course_id):
        raise RuntimeError("down")

    monkeypatch.setattr(s, "coverage", _boom)
    assert s.main([]) == 1
    assert "REPORT_FAIL check_items RuntimeError" in capsys.readouterr().out


# ── learner_state: the one derived-column write and the state reader ────────


def test_write_metrics_updates_only_derived_columns(monkeypatch):
    from learning import learner_state

    t = _T([])
    t.update = lambda data, filters, **kw: t.calls.append(("update", data, filters, kw)) or []
    monkeypatch.setattr(learner_state, "table", lambda name: t)
    learner_state.write_metrics(
        "u", "n", htc_k=1.0, unassisted_next=0.5, assist_gap=0.25, in_zone=True
    )
    ((_, data, filters, kw),) = [c for c in t.calls if c[0] == "update"]
    assert set(data) == {"htc_k", "unassisted_next", "assist_gap", "in_zone", "updated_at"}
    assert {k: data[k] for k in ("htc_k", "unassisted_next", "assist_gap", "in_zone")} == {
        "htc_k": 1.0,
        "unassisted_next": 0.5,
        "assist_gap": 0.25,
        "in_zone": True,
    }
    assert filters == {"user_id": "eq.u", "node_id": "eq.n"}
    assert params.BAND_WINDOW == 8  # the window the script reads


def test_opportunity_states_pages_rows_with_opportunities(monkeypatch):
    from learning import learner_state

    t = _T([{"user_id": "u", "node_id": "n", "opps": 2}])
    names = []
    monkeypatch.setattr(learner_state, "table", lambda name: names.append(name) or t)
    assert learner_state.opportunity_states() == [{"user_id": "u", "node_id": "n", "opps": 2}]
    learner_state.opportunity_states("u9")
    assert names == ["learner_state", "learner_state"]
    calls = [c for c in t.calls if c[0] == "select_with_count"]
    assert calls[0][2] == {"opps": "gt.0"}
    assert calls[-1][2] == {"opps": "gt.0", "user_id": "eq.u9"}
    assert calls[0][3] == "user_id,node_id"  # a total order (the primary key)
