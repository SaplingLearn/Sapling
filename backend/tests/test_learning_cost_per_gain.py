"""learning/cost_per_gain.py: the loop's spend against its measured learning
(spec §13 A137). Every expected number below is worked out by hand."""

from __future__ import annotations

import pytest

from learning import cost_per_gain as cpg
from learning.learning_gain import learning_gain
from learning.params import LOOP_COST_TARGET_USD_PER_STUDENT_MONTH

MONTH = cpg.DAYS_PER_MONTH

USAGE = [
    # u1's session s1 in course c1 (attributed through the session)
    {"task": "loop_tutor", "cost_usd": 0.02, "user_id": "u1", "session_id": "s1"},
    {"task": "grader", "cost_usd": "0.001", "user_id": "u1", "session_id": "s1"},  # numeric as text
    {"task": "loop_tutor", "cost_usd": None, "user_id": "u1", "session_id": "s1"},  # unpriced
    # u2 in c2: the row names its course itself (A137)
    {"task": "loop_tutor_deep", "cost_usd": 0.04, "user_id": "u2", "session_id": "s2", "course_id": "c2"},
    # background drafting for c1: no student, no session
    {"task": "check_items", "cost_usd": 0.01, "user_id": None, "session_id": None, "course_id": "c1"},
    # a post-test grade of u3 with no course recorded: unattributed
    {"task": "grader", "cost_usd": 0.003, "user_id": "u3", "session_id": None},
    # not the loop: ignored everywhere
    {"task": "chat_tutor", "cost_usd": 1.0, "user_id": "u1", "session_id": "s9"},
]
SESSIONS = {"s1": "c1", "s2": "c2", "s9": "c1"}


def _pose(user, course, anchor, window=7, correct=True, rung=0, question="q"):
    return {
        "user_id": user,
        "course_id": course,
        "anchor_event_id": anchor,
        "window_days": window,
        "correct": correct,
        "max_rung": rung,
        "answered_at": "2026-11-01T00:00:00+00:00",
        "question_hash": question,
    }


POSES = [
    _pose("u1", "c1", "a1", correct=True),  # pre False → post True: +1
    _pose("u1", "c1", "a2", correct=False),  # pre True → post False: −1
    _pose("u2", "c2", "a3", correct=True),  # pre True → post True: 0
    _pose("u2", "c2", "a4", correct=True),  # pre False → post True: +1
    _pose("u2", "c2", "a5", correct=True, rung=1),  # assisted: no outcome
    _pose("u2", "c2", "a9", correct=True),  # no pretest: no pair
    _pose("u1", "c1", "a6", correct=True, question="broken"),  # retired item: void
    _pose("u1", "c1", "a7", window=28, correct=True),  # pre True → post True at 28 days
]
PRETESTS = {"a1": False, "a2": True, "a3": True, "a4": False, "a5": False, "a6": False, "a7": True}
RETIRED = {("c1", "broken")}


def _report(**kw):
    args = dict(range_days=MONTH, retired=RETIRED, resamples=200)
    args.update(kw)
    return cpg.cost_per_gain(USAGE, SESSIONS, POSES, PRETESTS, **args)


def _window(block, days):
    return next(w for w in block["windows"] if w["window_days"] == days)


def test_overall_cost_rates_and_their_ns():
    overall = _report()["overall"]
    assert overall["cost_usd"] == pytest.approx(0.074)  # 0.02 + 0.001 + 0.04 + 0.01 + 0.003
    assert overall["tutor_usd"] == pytest.approx(0.06)
    assert overall["drafting_usd"] == pytest.approx(0.01)
    assert (overall["rows"], overall["unpriced_rows"]) == (6, 1)  # chat_tutor is not the loop
    assert overall["active_students"] == 3  # u1, u2, u3: the drafting row has no student
    assert overall["per_active_student_month"] == pytest.approx(0.074 / 3)
    assert overall["tutor_per_active_student_month"] == pytest.approx(0.02)
    assert overall["target_ratio"] == pytest.approx(0.074 / 3 / LOOP_COST_TARGET_USD_PER_STUDENT_MONTH)
    assert overall["sessions"] == 2  # s1, s2
    assert overall["per_session"] == pytest.approx((0.02 + 0.001 + 0.04) / 2)


def test_pairs_and_gain_points_per_window():
    overall = _report()["overall"]
    seven = _window(overall, 7)
    # a1 +1, a2 −1, a3 0, a4 +1; a5 assisted, a9 unpaired, a6 retired
    assert (seven["pairs"], seven["students"], seven["gain_points"]) == (4, 2, 1)
    assert seven["per_pair"] == pytest.approx(0.074 / 4)
    assert seven["per_gain_point"] == pytest.approx(0.074 / 1)
    twenty_eight = _window(overall, 28)
    assert (twenty_eight["pairs"], twenty_eight["gain_points"]) == (1, 0)
    assert twenty_eight["per_pair"] == pytest.approx(0.074)
    assert twenty_eight["per_gain_point"] is None  # no gain, no cost per gain
    assert twenty_eight["per_gain_point_ci"] is None


def test_the_pairs_are_exactly_the_learning_gain_reports():
    gain = learning_gain(POSES, PRETESTS, retired=RETIRED, resamples=10)
    report = _report()["overall"]
    for w in gain["windows"]:
        assert _window(report, w["window_days"])["pairs"] == w["n"]
        assert _window(report, w["window_days"])["gain_points"] == w["improved"] - w["worse"]


def test_courses_and_the_unattributed_spend():
    report = _report()
    c1, c2 = report["courses"]
    assert (c1["course_id"], c2["course_id"]) == ("c1", "c2")
    # c1: s1's priced rows (0.02 + 0.001), its unpriced row, and its drafting (0.01)
    assert c1["cost_usd"] == pytest.approx(0.031)
    assert (c1["rows"], c1["unpriced_rows"], c1["drafting_usd"]) == (4, 1, pytest.approx(0.01))
    assert c1["active_students"] == 1 and c1["per_active_student_month"] == pytest.approx(0.031)
    assert c1["per_session"] == pytest.approx(0.021)  # the drafting row has no session
    c1_seven = _window(c1, 7)
    assert (c1_seven["pairs"], c1_seven["gain_points"]) == (2, 0)
    assert c1_seven["per_pair"] == pytest.approx(0.0155) and c1_seven["per_gain_point"] is None
    assert c2["cost_usd"] == pytest.approx(0.04) and c2["per_session"] == pytest.approx(0.04)
    c2_seven = _window(c2, 7)
    assert (c2_seven["pairs"], c2_seven["gain_points"]) == (2, 1)
    assert c2_seven["per_pair"] == pytest.approx(0.02) and c2_seven["per_gain_point"] == pytest.approx(0.04)
    assert report["unattributed"] == {"cost_usd": pytest.approx(0.003), "rows": 1}
    assert sum(c["cost_usd"] for c in report["courses"]) + 0.003 == pytest.approx(0.074)


def test_a_course_with_pairs_but_no_spend_is_still_reported():
    report = cpg.cost_per_gain([], {}, [_pose("u1", "c7", "a1")], {"a1": False}, range_days=MONTH)
    (c7,) = report["courses"]
    assert c7["course_id"] == "c7" and c7["cost_usd"] == 0.0
    assert _window(c7, 7)["pairs"] == 1 and _window(c7, 7)["per_pair"] == 0.0


def test_nothing_measured_reads_none_never_zero():
    report = cpg.cost_per_gain([], {}, [], {}, range_days=MONTH)
    overall = report["overall"]
    assert overall["cost_usd"] == 0.0 and overall["active_students"] == 0
    for key in ("per_active_student_month", "tutor_per_active_student_month", "target_ratio", "per_session"):
        assert overall[key] is None, key
    for w in overall["windows"]:
        assert w["pairs"] == 0 and w["per_pair"] is None and w["per_gain_point"] is None
        assert w["per_pair_ci"] is None and w["per_gain_point_ci"] is None
    assert report["courses"] == [] and report["unattributed"] == {"cost_usd": 0.0, "rows": 0}


@pytest.mark.parametrize("days", [None, 0, -3])
def test_no_range_length_no_monthly_rate(days):
    overall = _report(range_days=days)["overall"]
    assert overall["per_active_student_month"] is None and overall["target_ratio"] is None
    assert overall["per_session"] is not None  # the other rates do not need it


def test_a_shorter_range_scales_to_a_month():
    week = _report(range_days=7.0)["overall"]
    assert week["per_active_student_month"] == pytest.approx(0.074 / 3 * MONTH / 7.0)


def test_identical_students_give_a_point_interval():
    """Every resample of two identical students has the same ratio."""
    clusters = {"a": (0.01, 1, 1), "b": (0.01, 1, 1)}
    pair_ci, gain_ci = cpg.ratio_ci(clusters, 0.0, resamples=50, seed="s", level=0.95)
    assert pair_ci == [pytest.approx(0.01), pytest.approx(0.01)]
    assert gain_ci == [pytest.approx(0.01), pytest.approx(0.01)]


def test_a_resample_without_a_pair_or_a_gain_leaves_the_upper_bound_open():
    """b has cost and no pair: a resample of (b, b) — one in four — has no
    finite ratio, so the 97.5th percentile is unbounded (None); (a, a) is the
    lowest ratio, 0.02 / 2."""
    clusters = {"a": (0.01, 1, 1), "b": (0.01, 0, 0)}
    pair_ci, gain_ci = cpg.ratio_ci(clusters, 0.0, resamples=400, seed="s", level=0.95)
    assert pair_ci == [pytest.approx(0.01), None]
    assert gain_ci == [pytest.approx(0.01), None]


def test_the_fixed_cost_is_in_every_resample():
    clusters = {"a": (0.0, 1, 1), "b": (0.0, 1, 1)}
    pair_ci, _ = cpg.ratio_ci(clusters, 0.2, resamples=20, seed="s", level=0.95)
    assert pair_ci == [pytest.approx(0.1), pytest.approx(0.1)]  # 0.2 / 2 pairs, always


def test_intervals_need_two_students_and_are_reproducible():
    assert cpg.ratio_ci({"a": (0.01, 1, 1)}, 0.0, resamples=10, seed="s", level=0.95) == (None, None)
    first, second = _report(), _report()
    assert _window(first["overall"], 7)["per_pair_ci"] == _window(second["overall"], 7)["per_pair_ci"]
    shuffled = cpg.cost_per_gain(
        list(reversed(USAGE)), SESSIONS, list(reversed(POSES)), PRETESTS,
        range_days=MONTH, retired=RETIRED, resamples=200,
    )
    assert _window(shuffled["overall"], 7)["per_pair_ci"] == _window(first["overall"], 7)["per_pair_ci"]
    lo, hi = _window(first["overall"], 7)["per_pair_ci"]
    assert lo <= _window(first["overall"], 7)["per_pair"] and (hi is None or hi >= lo)


def test_the_loop_tasks_cover_every_evidence_slot():
    from agents._providers import EVIDENCE_SLOTS

    assert set(EVIDENCE_SLOTS) <= set(cpg.LOOP_TASKS)
    assert set(cpg.TUTOR_TASKS) | set(cpg.DRAFTING_TASKS) <= set(cpg.LOOP_TASKS)
    from services.ai_budget import UNCOUNTED_TASKS

    assert UNCOUNTED_TASKS <= set(cpg.LOOP_TASKS)  # the loop decisions' Jev rows
