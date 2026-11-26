"""Spec §13 A133: help abuse, measured — learning/help_abuse.py (pure) and the
`help_abuse` field of GET /api/admin/analytics/learning-loop.

Hand-built help ledgers (learning_reveals' loop rows), zpd.attempt / zpd.step
events and evidence rows; the develop-band scenario of six one-character
attempts (spec §13 A134) is one of them. No DB, no model.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from services.admin.analytics import learning_loop as analytics
from tests.split_patches import ADMIN_ANALYTICS_MODULES, setattr_in
from learning import params
from learning.help_abuse import BOTTOM_OUT_RUNG, help_abuse
from main import app
from tests.test_admin_learning_loop_kpis import URL, _FakeTable

T = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)
GATE_MS = params.GATE_INDEPENDENT_MIN_S * 1000
NOVICE_GATE_MS = params.GATE_INDEPENDENT_MIN_S_NOVICE * 1000


def at(s: float) -> str:
    return (T + timedelta(seconds=s)).isoformat()


def posed(user, session, qh, s=0.0):
    return {"kind": "posed", "source": "loop", "user_id": user, "session_id": session,
            "question_hash": qh, "rung": None, "at": at(s)}


def helped(user, session, qh, rung, s):
    return {"kind": "help", "source": "loop", "user_id": user, "session_id": session,
            "question_hash": qh, "rung": rung, "at": at(s)}


def attempt(user, session, qh, s, *, rung, alone_s, gate_ms=GATE_MS, novel=True, standard=True,
            strict=None, counted=True, gate="standard", band="develop"):
    strict = (standard and novel and alone_s * 1000 >= gate_ms) if strict is None else strict
    return {"event_type": "zpd.attempt", "user_id": user, "created_at": at(s), "payload": {
        "session_id": session, "question_hash": qh, "band": band, "gate": gate, "rung": rung,
        "since_pose_ms": int(s * 1000), "alone_ms": int(alone_s * 1000), "gate_ms": gate_ms,
        "novel": novel, "standard": standard, "strict": strict, "counted": counted,
        "concept_id": "n-" + user}}


def step_event(user, session, qh, *, band, s=0.0):
    return {"event_type": "zpd.step", "user_id": user, "created_at": at(s), "payload": {
        "phase": "check", "session_id": session, "question_hash": qh, "band": band,
        "concept_id": "n-" + user}}


def evidence(node, session, qh, s, *, correct, assisted=False, max_rung=0, i=0):
    return {"id": f"e-{node}-{qh}-{i}", "node_id": node, "session_id": session, "question_hash": qh,
            "correct": correct, "assisted": assisted, "max_rung": max_rung, "created_at": at(s)}


def spam_student(user="u-spam", session="s-spam", qh="q-spam"):
    """The develop-band scenario (spec §13 A134): six one-character attempts,
    H1 at 45 s then one rung per 8 s dwell; each hint turn writes its rung
    again two seconds later (A93 records the grant AND the served turn). The
    copied answer is graded at 100 s; the next item on the concept is wrong."""
    dwell = params.GATE_RUNG_DWELL_MIN_S
    times = [params.GATE_INDEPENDENT_MIN_S + dwell * i for i in range(6)]
    ledger = [posed(user, session, qh)]
    attempts = []
    for k, t in enumerate(times):
        ledger += [helped(user, session, qh, k + 1, t), helped(user, session, qh, k + 1, t + 2)]
        attempts.append(attempt(user, session, qh, t, rung=k, alone_s=times[0] if k == 0 else dwell))
    ev = [evidence("n-" + user, session, qh, 100, correct=True, assisted=True, max_rung=6),
          evidence("n-" + user, "s-later", "q-iso", 600, correct=False, i=1)]
    return ledger, attempts, [step_event(user, session, qh, band="develop", s=100)], ev


def _report(ledger=(), attempts=(), steps=(), ev=(), courses=None):
    return help_abuse(ledger, attempts, steps, ev, courses or {})


def test_the_six_one_character_attempts_bottom_out_and_the_strict_rule_would_have_held_them():
    ledger, attempts, steps, ev = spam_student()
    r = _report(ledger, attempts, steps, ev, {"s-spam": "course-1"})
    o = r["overall"]
    assert r["bottom_out_rung"] == BOTTOM_OUT_RUNG == 5
    assert (o["steps"], o["bottom_outs"], o["full_solutions"], o["bottom_out_rate"]) == (1, 1, 1, 1.0)
    # H5 at 45 + 4 × 8 = 77 s after the pose; every new rung 8 s after the last
    assert o["time_to_bottom_out_s"] == {"n": 1, "median": 77.0}
    assert o["help_gap_s"] == {"n": 5, "median": 8.0}
    assert o["climb_gap_s"] == {"n": 4, "median": 8.0}  # H1 → H5
    # six counted attempts, five of them 8 s after a hint: rapid, never repeats
    assert o["attempts"] == {"counted": 6, "rapid": 5, "repeat": 0, "strict_refused": 0}
    # the climb (attempts below H5): the first came after 45 s alone, four did not
    assert o["bottom_out_attempts"] == {
        "measured": 1, "unmeasured": 0, "held_by_strict": 1, "no_strict_attempt": 0,
    }
    assert o["next"]["bottom_out"] == {"graded": 1, "unassisted_correct": 0, "other": 1, "none": 0}
    assert [g["key"] for g in r["by_band"]] == ["develop"]
    assert [g["key"] for g in r["by_gate"]] == ["standard"]
    assert [g["key"] for g in r["by_course"]] == ["course-1"]
    assert [g["key"] for g in r["by_student"]] == ["u-spam"]


def test_a_climb_with_no_strict_attempt_at_all():
    """Every attempt of the climb rapid (or a repeat): `no_strict_attempt`."""
    ledger = [posed("u", "s", "q")] + [helped("u", "s", "q", r, 10 * r) for r in range(1, 6)]
    attempts = [attempt("u", "s", "q", 10 * r - 1, rung=r - 1, alone_s=5, novel=r != 3) for r in range(1, 6)]
    o = _report(ledger, attempts)["overall"]
    assert o["bottom_out_attempts"] == {
        "measured": 1, "unmeasured": 0, "held_by_strict": 1, "no_strict_attempt": 1,
    }
    assert o["attempts"]["repeat"] == 1 and o["attempts"]["rapid"] == 5


def test_a_genuine_climb_is_not_held_and_partial_help_is_its_own_bucket():
    """Two attempts after real time alone (H1, H2), graded correct with H2;
    the next isomorph is answered right with no help."""
    ledger = [posed("g", "s", "q"), helped("g", "s", "q", 1, 60), helped("g", "s", "q", 2, 130)]
    attempts = [attempt("g", "s", "q", 60, rung=0, alone_s=60), attempt("g", "s", "q", 130, rung=1, alone_s=70)]
    ev = [evidence("n-g", "s", "q", 200, correct=True, assisted=True, max_rung=2),
          evidence("n-g", "s2", "q-iso", 900, correct=True, i=1)]
    o = _report(ledger, attempts, [], ev)["overall"]
    assert o["bottom_outs"] == 0 and o["bottom_out_rate"] == 0.0
    assert o["time_to_bottom_out_s"] == {"n": 0, "median": None}  # never a zero
    assert o["attempts"] == {"counted": 2, "rapid": 0, "repeat": 0, "strict_refused": 0}
    assert o["next"]["partial"] == {"graded": 1, "unassisted_correct": 1, "other": 0, "none": 0}
    assert o["next"]["bottom_out"]["graded"] == 0


def test_no_help_no_later_opportunity_and_an_assisted_or_helped_next_answer():
    # a session is one student's, so (session, item) names one step
    ledger = [posed("a", "sa", "q"), posed("b", "sb", "q"), posed("c", "sc", "q")]
    ev = [
        evidence("n-a", "sa", "q", 50, correct=True),  # a: graded, nothing after it → none
        evidence("n-b", "sb", "q", 50, correct=True),
        evidence("n-b", "sb9", "q2", 70, correct=True, assisted=True, max_rung=1, i=1),  # helped
        evidence("n-c", "sc", "q", 50, correct=True),
        evidence("n-c", "sc9", "q", 70, correct=True, i=1),  # the SAME item again: no isomorph
        evidence("n-c", "sc9", "q3", 80, correct=True, max_rung=4, i=2),  # a floor above 0
    ]
    o = _report(ledger, (), (), ev)["overall"]
    assert o["next"]["none"] == {"graded": 3, "unassisted_correct": 0, "other": 2, "none": 1}


def test_a_bottom_out_before_a134_is_unmeasured_never_a_zero():
    ledger = [posed("old", "s", "q")] + [helped("old", "s", "q", r, 9 * r) for r in range(1, 6)]
    r = _report(ledger)
    o = r["overall"]
    assert o["bottom_outs"] == 1
    assert o["bottom_out_attempts"] == {
        "measured": 0, "unmeasured": 1, "held_by_strict": 0, "no_strict_attempt": 0,
    }
    assert [g["key"] for g in r["by_gate"]] == ["none"]  # no attempt record: the gate never acted
    assert [g["key"] for g in r["by_band"]] == ["unknown"]


def test_the_novice_worked_example_path_and_the_strict_cohort():
    """A novice on the worked-example path reaches H5 by design (A122): H4 with
    no attempt, H5 after 90 s alone — a measured bottom-out the strict rule
    would grant. Under the strict gate a refused attempt the §3.3 rule would
    have counted is the strict gate's friction (`strict_refused`)."""
    ledger = [posed("nv", "s", "q"), helped("nv", "s", "q", 4, 1), helped("nv", "s", "q", 5, 95)]
    attempts = [
        attempt("nv", "s", "q", 51, rung=4, alone_s=50, gate_ms=NOVICE_GATE_MS, counted=False,
                gate="strict", band="novice"),
        attempt("nv", "s", "q", 95, rung=4, alone_s=94, gate_ms=NOVICE_GATE_MS, gate="strict",
                band="novice"),
    ]
    r = _report(ledger, attempts, [step_event("nv", "s", "q", band="novice", s=120)])
    o = r["overall"]
    assert o["bottom_outs"] == 1 and o["full_solutions"] == 0
    assert o["climb_gap_s"] == {"n": 1, "median": 94.0}  # H4 → H5
    assert o["attempts"] == {"counted": 1, "rapid": 0, "repeat": 0, "strict_refused": 1}
    assert o["bottom_out_attempts"]["measured"] == 1 and o["bottom_out_attempts"]["held_by_strict"] == 0
    assert [g["key"] for g in r["by_gate"]] == ["strict"]
    assert [g["key"] for g in r["by_band"]] == ["novice"]


def test_groups_by_band_gate_course_and_student_with_honest_n():
    spam = spam_student()
    genuine = ([posed("g", "s-g", "q"), helped("g", "s-g", "q", 1, 60)],
               [attempt("g", "s-g", "q", 60, rung=0, alone_s=60, gate="strict")], [], [])
    quiet = ([posed("quiet", "s-q", "q")], [], [step_event("quiet", "s-q", "q", band="profic")], [])
    parts = [spam, genuine, quiet]
    r = _report(*(sum((list(p[i]) for p in parts), []) for i in range(4)),
                courses={"s-spam": "c1", "s-g": "c1", "s-q": "c2"})
    assert r["overall"]["steps"] == 3 and r["overall"]["bottom_outs"] == 1
    assert {g["key"]: g["steps"] for g in r["by_band"]} == {"develop": 2, "profic": 1}
    assert [g["key"] for g in r["by_band"]] == ["develop", "profic"]  # band order
    assert {g["key"]: (g["steps"], g["bottom_outs"]) for g in r["by_gate"]} == {
        "standard": (1, 1), "strict": (1, 0), "none": (1, 0),
    }
    assert {g["key"]: g["steps"] for g in r["by_course"]} == {"c1": 2, "c2": 1}
    assert [g["key"] for g in r["by_student"]][0] == "u-spam"  # most bottom-outs first
    assert all(g["bottom_out_rate"] is not None for g in r["by_student"])


def test_rows_outside_the_loop_or_unposed_are_ignored():
    ledger = [
        posed("u", "s", "q"),
        {**helped("u", "s", "q", 6, 10), "source": "quiz"},  # A99 quiz-ask help: not the ladder
        helped("u", "s", "other", 6, 10),  # help on an item not posed in the range
        {**posed("u", "s", "probe-q"), "source": "probe"},  # a probe pose: no hints exist there
        helped("u", "s", "q", 2, 30),
    ]
    o = _report(ledger)["overall"]
    assert (o["steps"], o["bottom_outs"]) == (1, 0)
    assert o["next"]["partial"]["graded"] == 0  # never graded in the range: not counted


def test_an_empty_range_answers_nones_never_zeros():
    r = _report()
    o = r["overall"]
    assert (o["steps"], o["bottom_out_rate"]) == (0, None)
    assert o["time_to_bottom_out_s"] == {"n": 0, "median": None}
    assert r["by_band"] == r["by_gate"] == r["by_course"] == r["by_student"] == []


# ── the admin endpoint (routes/admin_analytics.py) ───────────────────────────


@pytest.fixture
def served(monkeypatch):
    ledger, attempts, steps, ev = spam_student()
    for row in ev:
        row.update(event_type="evidence", channel="free_response", p_before=0.5, weight=1.0,
                   check_item_id=None, student_confidence=None, graph_nodes={"course_id": "course-1"})
    store = {
        "learning_reveals": [{"id": f"r{i}", **row} for i, row in enumerate(ledger)],
        "events": [{**e, "category": "usage"} for e in attempts + steps],
        "node_mastery_events": ev,
        "sessions": [{"id": "s-spam", "offering_id": "off-1", "user_id": "u-spam"}],
    }
    setattr_in(monkeypatch, ADMIN_ANALYTICS_MODULES, "table", lambda name: _FakeTable(store.get(name, [])))
    monkeypatch.setattr(analytics, "offering_course_id", lambda o: {"off-1": "course-1"}.get(o))
    return store


RANGE = {"from": "2026-07-01T00:00:00+00:00", "to": "2026-08-01T00:00:00+00:00"}


def test_the_endpoint_reports_help_abuse_additively(served):
    r = TestClient(app).get(URL, params=RANGE)
    assert r.status_code == 200, r.text
    body = r.json()
    h = body["help_abuse"]
    assert h["bottom_out_rung"] == 5 and h["truncated"] is False
    assert h["overall"]["bottom_outs"] == 1
    assert h["overall"]["bottom_out_attempts"]["held_by_strict"] == 1
    assert h["overall"]["next"]["bottom_out"]["other"] == 1
    assert [g["key"] for g in h["by_course"]] == ["course-1"]
    # additive: the earlier fields still answer, from the same scans
    assert body["steps_total"] == 1 and "earnest_revise" in body


def test_a_failed_ledger_read_leaves_the_rest_of_the_report_standing(served, monkeypatch):
    real = analytics.table

    def failing(name):
        if name == "learning_reveals":
            raise RuntimeError("ledger down")
        return real(name)

    setattr_in(monkeypatch, ADMIN_ANALYTICS_MODULES, "table", failing)
    r = TestClient(app).get(URL, params=RANGE)
    assert r.status_code == 200 and r.json()["help_abuse"] is None
    assert r.json()["steps_total"] == 1


def test_help_abuse_is_pure_and_outside_the_pkg06_layer():
    """The admin route must not import a PKG-06 module (the inertness scan):
    the report reads params only, like learning/earnest_revise.py."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "learning" / "help_abuse.py"
    tree = ast.parse(src.read_text())
    learning_imports = sorted(
        f"{n.module}:{a.name}"
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("learning")
        for a in n.names
    ) + sorted(
        a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.Import)
        for a in n.names
        if a.name.startswith("learning")
    )
    assert learning_imports == ["learning:params"]
