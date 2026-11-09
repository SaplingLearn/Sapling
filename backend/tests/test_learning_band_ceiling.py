"""Spec §13 A122: §3.3 band control's ceiling clauses — HARDER "ceiling −1
rung", EASIER_CHECK_PREREQS "ceiling +1 rung" — move the band's ceiling for
the concept, clamped to the ladder, and never past a gate: exam mode, the
shown-work floor, the teach-attempt cap, the attempt/dwell gate, the H6 item
predicates (A32), the A93 help floor and the leak checks all hold. The
post-test (H0) and review are untouched: tests in test_learning_posttest.py
and test_learning_review.py.

Policy tests run the pure layer; route tests use the shared hermetic harness
of tests/test_learn_loop_routes.py. No DB, no model.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from learning import params, policy
from learning.ladder import Rung, intent
from learning.policy import BandAction, CeilingReason, LearnerView, StepState
from tests import test_learn_loop_routes as routes
from tests.test_learning_band_control import HIT, MISS, _answer, _learner_reads

gate_on, no_rate_limit, seams = routes.gate_on, routes.no_rate_limit, routes.seams

UP, DOWN = params.BAND_CONTROL_CEILING_STEP, -params.BAND_CONTROL_CEILING_STEP


def _view(band, *, prereq=True, n_strong=1, p=None) -> LearnerView:
    p = p if p is not None else {"novice": 0.1, "develop": 0.5, "profic": 0.9}[band]
    return LearnerView(
        p_known=p, band=band, prereq_proficient=prereq, unassisted_next=None, opps=0,
        streak_unassisted=0, n_strong_unassisted=n_strong,
    )


# ── the pure clause ──────────────────────────────────────────────────────────


def test_ceiling_delta_is_the_spec_clause_of_each_verdict():
    assert params.BAND_CONTROL_CEILING_STEP == 1
    assert policy.ceiling_delta(BandAction.HARDER) == -1
    assert policy.ceiling_delta(BandAction.EASIER_CHECK_PREREQS) == 1
    for action in (BandAction.HOLD, BandAction.STOP_PRACTICE, BandAction.WHEELSPIN):
        assert policy.ceiling_delta(action) == 0


@pytest.mark.parametrize(
    "view,fails,base,up,down",
    [
        (_view("profic"), 0, Rung.H1, Rung.H2, Rung.H0),
        (_view("profic"), 2, Rung.H3, Rung.H4, Rung.H2),  # escalated row
        (_view("profic", n_strong=0), 0, Rung.H3, Rung.H4, Rung.H2),  # A110 (c) unconfirmed
        (_view("develop"), 0, Rung.H3, Rung.H4, Rung.H2),
        (_view("develop"), 1, Rung.H4, Rung.H5, Rung.H3),
        (_view("develop"), 2, Rung.H6, Rung.H6, Rung.H5),  # the ladder's top clamps +1
        (_view("novice", prereq=True), 0, Rung.H5, Rung.H6, Rung.H4),
        (_view("novice", prereq=False), 0, Rung.H4, Rung.H5, Rung.H3),
        (_view("novice", prereq=False), 1, Rung.H5, Rung.H6, Rung.H4),
    ],
)
def test_the_clause_moves_every_band_row_one_rung_within_the_ladder(view, fails, base, up, down):
    step = StepState("q", genuine_attempts=fails)
    rung, reason = policy.ceiling_with_reason(view, step)
    assert rung is base
    got_up = policy.ceiling_with_reason(view, step, band_delta=UP)
    got_down = policy.ceiling_with_reason(view, step, band_delta=DOWN)
    assert got_up == (up, CeilingReason.BAND_CONTROL if up != base else reason)
    assert got_down == (down, CeilingReason.BAND_CONTROL)
    assert policy.ceiling(view, step, band_delta=UP) is up


def test_exam_mode_ignores_the_clause():
    exam = StepState("q", exam_mode=True)
    for delta in (UP, DOWN):
        assert policy.ceiling_with_reason(_view("novice"), exam, band_delta=delta) == (
            Rung.H1, CeilingReason.EXAM,
        )


def test_the_shown_work_floor_still_binds_after_a_rung_down():
    worked = StepState("q", showed_work=True)
    assert policy.ceiling_with_reason(_view("profic"), worked, band_delta=DOWN) == (
        Rung.H3, CeilingReason.SHOWED_WORK_FLOOR,
    )
    assert policy.ceiling_with_reason(_view("develop"), worked, band_delta=DOWN) == (
        Rung.H3, CeilingReason.SHOWED_WORK_FLOOR,
    )


def test_the_teach_attempt_cap_still_binds_after_a_rung_up():
    fresh = StepState("q")
    # profic H1 +1 = H2; a teach attempt raises two, capped at the band's H3
    assert policy.ceiling_with_reason(_view("profic"), fresh, teach_attempt=True, band_delta=UP) == (
        Rung.H3, CeilingReason.TEACH_ATTEMPT,
    )
    # novice H5 +1 = H6 already above the novice cap (H5): the raise adds nothing
    assert policy.ceiling_with_reason(_view("novice"), fresh, teach_attempt=True, band_delta=UP) == (
        Rung.H6, CeilingReason.BAND_CONTROL,
    )


@pytest.mark.parametrize("bad", [2, -2, True, 0.5])
def test_only_the_spec_rung_moves_are_accepted(bad):
    with pytest.raises(ValueError):
        policy.ceiling_with_reason(_view("develop"), StepState("q"), band_delta=bad)


def test_the_worked_example_jump_reads_the_moved_ceiling():
    novice = _view("novice", prereq=False)  # worked example first: H4 at no failed attempt
    fresh = StepState("q")
    assert policy.worked_example_rung(novice, fresh, worked_first=True, band_delta=UP) is Rung.H4
    assert policy.worked_example_rung(novice, fresh, worked_first=True, band_delta=DOWN) is None


# ── the route: stored, applied, held, replaced ───────────────────────────────


@pytest.fixture
def loop(gate_on, seams):
    st = routes._plan_state(teach_turns=2)
    st.update(routes._state())
    seams.store["doc"] = st
    return seams


def test_hold_keeps_the_concepts_ceiling_clause(loop):
    loop.store["doc"]["band_ceiling"] = {"node-1": UP}
    _learner_reads(loop, p=0.6)
    _answer(loop, [HIT] * 7 + [MISS])  # 0.875: HOLD
    doc = loop.store["doc"]
    assert "band_control" not in doc["steps"]["qh-1"]
    assert doc["band_ceiling"] == {"node-1": UP}


def test_a_new_clause_replaces_the_last_one_never_stacks(loop):
    loop.store["doc"]["band_ceiling"] = {"node-1": UP, "node-2": UP}
    _learner_reads(loop, p=0.6)
    _answer(loop, [HIT] * 4)  # HARDER
    assert loop.store["doc"]["band_ceiling"] == {"node-1": DOWN, "node-2": UP}
    [ev] = [c.kwargs for c in loop.zpd.emit_zpd_band_adjust.call_args_list]
    assert ev["ceiling_delta"] == DOWN


@pytest.mark.parametrize("action", ["stop_practice", "wheelspin"])
def test_verdicts_without_a_clause_emit_a_zero_delta_and_move_no_ceiling(loop, action):
    from tests.test_learning_band_control import STEADY

    loop.store["doc"]["band_ceiling"] = {"node-1": UP}
    if action == "stop_practice":
        _learner_reads(loop, p=0.97, opps=16, streak=16)
        _answer(loop, [STEADY] * 16)
    else:
        _learner_reads(loop, p=0.3, opps=10, streak=2)
        _answer(loop, [HIT, MISS] * 5, correct=False)
    doc = loop.store["doc"]
    assert doc["steps"]["qh-1"]["band_control"]["action"] == action
    assert doc["steps"]["qh-1"]["band_control"]["ceiling_delta"] == 0
    assert doc["band_ceiling"] == {"node-1": UP}
    [ev] = [c.kwargs for c in loop.zpd.emit_zpd_band_adjust.call_args_list]
    assert ev["ceiling_delta"] == 0


@pytest.mark.parametrize("edges,parent,expected", [
    ([], None, Rung.H3),  # prerequisite UNKNOWN: worked-first row H4, one rung down
    ([("node-0", "node-1")], 0.9, Rung.H4),  # prerequisite proficient: H5, one rung down
])
def test_the_stored_ceiling_of_a_novice_reads_its_prerequisite(loop, edges, parent, expected):
    _learner_reads(loop, p=0.2, prereqs={"node-0": parent} if parent is not None else {})
    _answer(loop, [HIT] * 4, edges=edges)  # HARDER on a novice
    stored = loop.store["doc"]["steps"]["qh-1"]["band_control"]
    assert stored["ceiling_delta"] == DOWN and stored["ceiling"] == int(expected)


def _hint(qh="qh-1"):
    r = routes.client.post("/api/learn/loop/hint", json={"session_id": "s1", "user_id": "u1", "question_hash": qh})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize(
    "delta,rung,expected",
    [
        (DOWN, 2, {"denied": "ceiling"}),  # develop H3 − 1 = H2
        (0, 2, {"rung": 3, "intent": intent(Rung.H3)}),
        (UP, 3, {"rung": 4, "intent": intent(Rung.H4)}),  # develop H3 + 1 = H4
    ],
)
def test_the_hint_route_unlocks_up_to_the_moved_ceiling(gate_on, seams, delta, rung, expected):
    seams.store["doc"] = routes._state(rung=rung, attempted_at=[routes.T0 + 10])
    if delta:
        seams.store["doc"]["band_ceiling"] = {"node-1": delta}
    assert _hint() == expected


def test_a_rung_up_never_unlocks_h6_without_its_item_predicates(gate_on, seams):
    """Novice, prerequisite proficient: H5, +1 → H6 — the ceiling admits H6,
    yet A32's predicates still decide (two genuine attempts, taught, practice,
    not graded)."""
    seams.p_known["node-1"] = 0.1
    seams.store["doc"] = routes._state(rung=5, attempts=1, attempted_at=[routes.T0 + 10], taught=True)
    seams.store["doc"]["band_ceiling"] = {"node-1": UP}
    assert _hint() == {"denied": "h6_gate"}
    seams.store["doc"]["steps"]["qh-1"].update(attempts=2, taught=False)
    assert _hint() == {"denied": "h6_gate"}
    seams.store["doc"]["steps"]["qh-1"].update(taught=True)
    assert _hint() == {"rung": int(Rung.H6), "intent": intent(Rung.H6)}


def test_without_the_clause_the_novice_row_never_reaches_h6(gate_on, seams):
    seams.p_known["node-1"] = 0.1
    seams.store["doc"] = routes._state(rung=5, attempts=2, attempted_at=[routes.T0 + 10], taught=True)
    assert _hint() == {"denied": "ceiling"}


def test_exam_mode_holds_h1_whatever_the_clause(gate_on, seams):
    seams.store["doc"] = routes._state(rung=1, attempted_at=[routes.T0 + 10], exam_mode=True)
    seams.store["doc"]["band_ceiling"] = {"node-1": UP}
    assert _hint() == {"denied": "ceiling"}
    st = routes.client.get("/api/learn/loop/status", params={"user_id": "u1", "session_id": "s1"}).json()
    assert st["ceiling"] == int(Rung.H1)


def test_model_text_stays_below_h6_until_the_answer_is_released(gate_on, seams):
    """A teach turn at a moved ceiling of H6 still tells the model H5: model
    text never writes the full solution unreleased (turn_shape's clamp)."""
    seams.store["doc"] = routes._plan_state(band_ceiling={"node-1": UP})
    seams.p_known["node-1"] = 0.1  # novice, prerequisite proficient: H5 + 1
    agent, seen = routes._json_agent()
    with (
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
    ):
        body = routes.client.post(
            "/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "explain"}
        ).json()
    assert body["ceiling"] == int(Rung.H6)
    assert "you may emit at most rung H5" in seen["msg"] and "at most rung H6" not in seen["msg"]


def test_the_leak_check_runs_below_h6_at_a_moved_ceiling(gate_on, seams):
    """A correct-verdict feedback turn (answer unreleased) at a moved ceiling
    of H6 is leak-checked at H5, never at H6 (where the check would pass)."""
    seams.store["doc"] = routes._graded("correct")
    seams.store["doc"]["band_ceiling"] = {"node-1": UP}
    seams.p_known["node-1"] = 0.1
    agent, _ = routes._json_agent()
    with (
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
    ):
        body = routes.client.post(
            "/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "Continue"}
        ).json()
    assert body["phase"] == "feedback" and body["ceiling"] == int(Rung.H6)
    rungs = {c.kwargs["rung"] for c in seams.detect.call_args_list}
    assert rungs == {Rung.H5}


def test_a_rung_down_never_lowers_the_help_floor(gate_on, seams):
    """A93: help recorded on an item (here H3) floors its grade whatever the
    concept's ceiling clause says."""
    seams.store["doc"] = routes._state(rung=0)
    seams.store["doc"]["band_ceiling"] = {"node-1": DOWN}
    agent, _ = routes._json_agent()
    with (
        patch("routes.learn_loop.max_help", return_value=3),
        patch("routes.learn_loop.opportunity_window", return_value=None),
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
    ):
        r = routes.client.post(
            "/api/learn/loop/check/answer",
            json={"session_id": "s1", "user_id": "u1", "question_hash": "qh-1", "answer": "n == 0"},
        )
    assert r.status_code == 200, r.text
    assert seams.grade.call_args.kwargs["max_rung"] == 3


def test_a_malformed_stored_clause_moves_nothing():
    from routes.learn_loop import _band_ceiling_delta

    for raw in ({"node-1": 2}, {"node-1": True}, {"node-1": "1"}, ["node-1"], None):
        assert _band_ceiling_delta({"band_ceiling": raw}, "node-1") == 0
    assert _band_ceiling_delta({"band_ceiling": {"node-1": UP}}, None) == 0
    assert _band_ceiling_delta({"band_ceiling": {"node-1": DOWN}}, "node-1") == DOWN


def test_status_reports_the_moved_ceiling(gate_on, seams):
    seams.store["doc"] = routes._state(rung=0)
    seams.store["doc"]["band_ceiling"] = {"node-1": DOWN}
    st = routes.client.get("/api/learn/loop/status", params={"user_id": "u1", "session_id": "s1"}).json()
    assert st["band"] == "develop" and st["ceiling"] == int(Rung.H2)
