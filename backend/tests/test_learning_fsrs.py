"""learning.fsrs — FSRS-6 scheduler (spec §3.2). Pure maths, no DB, no LLM.

Reference values were computed from the spec §3.2 formulas over FSRS_W, plus
the FSRS-6 reference guards the spec's transcription omits (py-fsrs 6.3.2,
same default weights; HANDOFF-02 Deviations), and are stated to four
decimals; ``pytest.approx(abs=5e-5)`` throughout.
"""

from __future__ import annotations

import ast
import copy
import math
import pathlib
import random
from datetime import datetime, timedelta, timezone

import pytest

from learning import fsrs
from learning.fsrs import (
    Rating,
    SuccessiveRelearning,
    budget_items,
    budget_select,
    initial_difficulty,
    initial_stability,
    interval,
    item_retrievability,
    mc_cap_applies,
    next_state,
    order_due,
    rating_for,
    retention_target,
    retrievability,
)
from learning.params import (
    CHANNELS,
    FSRS_EXAM_WINDOW_DAYS,
    FSRS_LARGE_SET_CONCEPTS,
    FSRS_RETENTION_DEFAULT,
    FSRS_RETENTION_EXAM,
    FSRS_RETENTION_LARGE_SET,
    FSRS_S0_GOOD,
    FSRS_W,
    MC_STABILITY_GAIN_CAP,
    REVIEW_DAILY_BUDGET_MIN,
    REVIEW_ORDER_THRESHOLD,
    REVIEW_SECONDS_PER_CHECK,
    SR_INITIAL_CRITERION,
    SR_RELEARN_SESSIONS,
)

A = pytest.approx
TOL = 5e-5
NAN = float("nan")
INF = float("inf")
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def _approx(x):
    return A(x, abs=TOL)


# --- curves -----------------------------------------------------------------


def test_factor_is_derived_from_w20():
    assert fsrs.FACTOR == _approx(0.9803)
    assert fsrs.FACTOR == A(0.9 ** (-1 / FSRS_W[20]) - 1)


def test_retrievability_at_t_equals_s_is_exactly_0_9():
    for s in (0.5, FSRS_S0_GOOD, 10.0, 100.0):
        assert retrievability(s, s) == A(0.9, abs=1e-12)


def test_retrievability_reference_values():
    assert retrievability(0.0, 5.0) == 1.0
    assert retrievability(10.0, FSRS_S0_GOOD) == _approx(0.7744)
    assert retrievability(30.0, FSRS_S0_GOOD) == _approx(0.6675)


def test_retrievability_monotone_decreasing_in_days():
    rng = random.Random(2)
    for _ in range(50):
        s = rng.uniform(0.1, 200.0)
        days = sorted(rng.uniform(0.0, 400.0) for _ in range(6))
        rs = [retrievability(t, s) for t in days]
        assert all(0.0 < r <= 1.0 for r in rs)
        assert rs == sorted(rs, reverse=True)


def test_interval_is_the_inverse_of_retrievability():
    assert interval(0.9, FSRS_S0_GOOD) == A(FSRS_S0_GOOD, abs=1e-9)
    assert interval(0.9, 10.0) == A(10.0, abs=1e-9)
    assert interval(0.85, 10.0) == _approx(19.0643)
    assert interval(0.95, 10.0) == _approx(4.0256)
    assert interval(0.7, FSRS_S0_GOOD) == _approx(21.4226)
    for r in (0.7, 0.85, 0.9, 0.95):
        for s in (0.5, FSRS_S0_GOOD, 10.0, 100.0):
            assert retrievability(interval(r, s), s) == A(r, abs=1e-9)


@pytest.mark.parametrize(
    "bad", [(-1.0, 5.0), (1.0, 0.0), (1.0, -2.0), (NAN, 5.0), (1.0, NAN), (1.0, INF)]
)
def test_retrievability_rejects_bad_inputs(bad):
    with pytest.raises(ValueError):
        retrievability(*bad)


@pytest.mark.parametrize(
    "bad", [(0.0, 5.0), (1.5, 5.0), (0.9, 0.0), (NAN, 5.0), (0.9, NAN), (0.9, INF)]
)
def test_interval_rejects_bad_inputs(bad):
    with pytest.raises(ValueError):
        interval(*bad)


# --- retention target -------------------------------------------------------


def test_retention_target_rules():
    assert retention_target(10) == FSRS_RETENTION_DEFAULT
    assert retention_target(FSRS_LARGE_SET_CONCEPTS) == FSRS_RETENTION_DEFAULT
    assert retention_target(FSRS_LARGE_SET_CONCEPTS + 1) == FSRS_RETENTION_LARGE_SET
    assert retention_target(10, exam_within_days=FSRS_EXAM_WINDOW_DAYS) == FSRS_RETENTION_EXAM
    assert retention_target(10, exam_within_days=0) == FSRS_RETENTION_EXAM
    assert (
        retention_target(10, exam_within_days=FSRS_EXAM_WINDOW_DAYS + 1) == FSRS_RETENTION_DEFAULT
    )
    # exam window wins over the large-set rule
    assert retention_target(FSRS_LARGE_SET_CONCEPTS + 1, exam_within_days=1) == FSRS_RETENTION_EXAM
    assert retention_target(10, exam_within_days=None) == FSRS_RETENTION_DEFAULT


@pytest.mark.parametrize(
    "args",
    [(NAN,), (INF,), (-1,), (2.5,), ("10",), (10, NAN), (10, INF), (10, -1), (10, 2.5)],
)
def test_retention_target_rejects_bad_inputs(args):
    # n_scheduled is a count and exam_within_days a whole-day count >= 0
    # (exam_proximity.days_until_next_exam); NaN fell through every comparison
    # to the default retention before.
    with pytest.raises(ValueError):
        retention_target(*args)


# --- first rating -----------------------------------------------------------


@pytest.mark.parametrize(
    "rating, s0, d0",
    [
        (Rating.AGAIN, 0.212, 6.4133),
        (Rating.HARD, 1.2931, 5.1122),
        (Rating.GOOD, 2.3065, 2.1181),
        (Rating.EASY, 8.2956, 1.0),  # raw D0(4) = −4.7716, clamped to 1
    ],
)
def test_first_rating_uses_s0_and_d0(rating, s0, d0):
    assert initial_stability(rating) == _approx(s0)
    assert initial_difficulty(rating) == _approx(d0)
    assert next_state(None, None, rating, 0.0) == (_approx(d0), _approx(s0))


def test_s0_good_matches_params():
    assert initial_stability(Rating.GOOD) == FSRS_S0_GOOD == FSRS_W[2]


@pytest.mark.parametrize("bad", [0, 5, -1, 2.5, "3"])
def test_bad_rating_rejected(bad):
    with pytest.raises(ValueError):
        next_state(None, None, bad, 0.0)


# --- later ratings: reference trajectory from a first Good ------------------


def _after_first_good():
    return next_state(None, None, Rating.GOOD, 0.0)


def test_good_after_three_days_reference():
    d, s = _after_first_good()
    assert retrievability(3.0, s) == _approx(0.8809)
    nd, ns = next_state(d, s, Rating.GOOD, 3.0)
    assert nd == _approx(2.1112)
    assert ns == _approx(13.8269)


def test_hard_after_three_days_reference():
    d, s = _after_first_good()
    nd, ns = next_state(d, s, Rating.HARD, 3.0)
    assert nd == _approx(4.7529)
    assert ns == _approx(9.2349)


def test_again_after_three_days_reference():
    d, s = _after_first_good()
    nd, ns = next_state(d, s, Rating.AGAIN, 3.0)
    assert nd == _approx(7.3945)
    assert ns == _approx(0.6369)


def test_lapse_is_capped_below_the_prior_stability():
    # FSRS-6 caps S_lapse at S / e^(w17·w18). Without the cap, low D, tiny S
    # and a long gap made an Again RAISE S (0.05 → 0.0572 here).
    _, ns = next_state(1.0, 0.05, Rating.AGAIN, 60.0)
    assert ns == _approx(0.0476)
    rng = random.Random(19)
    for _ in range(2000):
        d = rng.uniform(1.0, 10.0)
        s = rng.uniform(0.05, 5.0) if rng.random() < 0.5 else rng.uniform(0.05, 500.0)
        days = rng.uniform(0.0, 365.0)
        _, ns = next_state(d, s, Rating.AGAIN, days)
        assert 0.0 < ns < s, (d, s, days)


def test_same_day_reference():
    d, s = _after_first_good()
    # FSRS-6 floors the same-day increase at 1 for Hard/Good/Easy: the raw
    # spec §3.2 value here is 2.2938 < S, i.e. a correct answer shrank S.
    nd, ns = next_state(d, s, Rating.GOOD, 0.0, same_day=True)
    assert (nd, ns) == (_approx(2.1112), _approx(2.3065))
    nd, ns = next_state(d, s, Rating.HARD, 0.0, same_day=True)
    assert ns == _approx(2.3065)  # raw 1.3334
    nd, ns = next_state(d, s, Rating.AGAIN, 0.0, same_day=True)
    assert (nd, ns) == (_approx(7.3945), _approx(0.7751))  # Again is not floored
    # where the raw increase is already >= 1 the floor changes nothing
    _, ns = next_state(d, 0.5, Rating.GOOD, 0.0, same_day=True)
    assert ns == _approx(0.5499)


def test_same_day_pass_never_lowers_stability():
    for s in (0.05, 0.5, FSRS_S0_GOOD, 10.0, 50.0, 500.0):
        for d in (1.0, 2.1181, 5.0, 10.0):
            for g in (Rating.HARD, Rating.GOOD, Rating.EASY):
                _, ns = next_state(d, s, g, 0.0, same_day=True)
                assert ns >= s, (s, d, g)
            _, ns_again = next_state(d, s, Rating.AGAIN, 0.0, same_day=True)
            assert ns_again < s


def test_same_session_correct_recalls_do_not_undo_the_first():
    # SR acquisition: a first Good then SR_INITIAL_CRITERION − 1 more correct
    # recalls in the same session; and a first Good then two assisted (Hard)
    # correct answers. Neither may end below a single Good's S0.
    for g in (Rating.GOOD, Rating.HARD):
        d, s = _after_first_good()
        for _ in range(SR_INITIAL_CRITERION - 1):
            d, s = next_state(d, s, g, 0.0, same_day=True)
        assert s >= FSRS_S0_GOOD


def test_ratings_order_stability_and_difficulty():
    for s in (0.5, FSRS_S0_GOOD, 10.0, 50.0):
        for d in (1.0, 2.1181, 5.0, 9.0):
            for days in (1.0, 3.0, 10.0, 60.0):
                d_a, s_a = next_state(d, s, Rating.AGAIN, days)
                d_h, s_h = next_state(d, s, Rating.HARD, days)
                d_g, s_g = next_state(d, s, Rating.GOOD, days)
                d_e, s_e = next_state(d, s, Rating.EASY, days)
                assert s_a < s_h < s_g < s_e
                assert d_a >= d_h >= d_g >= d_e


def test_spacing_effect_lower_r_grows_stability_more():
    d, s = _after_first_good()
    _, s_soon = next_state(d, s, Rating.GOOD, 3.0)
    _, s_late = next_state(d, s, Rating.GOOD, 30.0)
    assert s_late == _approx(37.4206)
    assert s_late > s_soon


def test_difficulty_stays_in_bounds_and_stability_positive():
    rng = random.Random(7)
    for _ in range(300):
        d = rng.uniform(1.0, 10.0)
        s = rng.uniform(0.05, 500.0)
        g = rng.choice(list(Rating))
        days = rng.uniform(0.0, 365.0)
        same_day = rng.random() < 0.2
        nd, ns = next_state(d, s, g, 0.0 if same_day else days, same_day=same_day)
        assert 1.0 <= nd <= 10.0
        assert ns > 0.0


def test_difficulty_update_reference_and_clamp():
    assert fsrs._next_difficulty(5.0, Rating.GOOD) == _approx(4.9902)
    assert fsrs._next_difficulty(5.0, Rating.AGAIN) == _approx(8.3418)
    assert fsrs._next_difficulty(10.0, Rating.AGAIN) == _approx(9.9852)
    assert fsrs._next_difficulty(1.0, Rating.EASY) == 1.0


def test_mean_reversion_targets_the_unclamped_d0_easy():
    # FSRS-6 reverts toward the RAW D0(4) = w4 − e^(3·w5) + 1 = −4.7716, not
    # the clamped 1.0 a first Easy gets (py-fsrs 6.3.2 clamp=False).
    raw_d0_easy = FSRS_W[4] - math.exp(3 * FSRS_W[5]) + 1
    assert raw_d0_easy == _approx(-4.7716)
    assert initial_difficulty(Rating.EASY) == 1.0  # the first rating stays clamped
    for d in (2.0, 5.0, 8.0):  # Good: ΔD = 0, so D'' is the reversion alone
        assert fsrs._next_difficulty(d, Rating.GOOD) == A(
            FSRS_W[7] * raw_d0_easy + (1 - FSRS_W[7]) * d, abs=1e-12
        )


def test_mc_cap_limits_stability_gain():
    d, s = _after_first_good()
    _, uncapped = next_state(d, s, Rating.GOOD, 30.0)
    _, capped = next_state(d, s, Rating.GOOD, 30.0, mc_unassisted=True)
    assert uncapped > s * MC_STABILITY_GAIN_CAP
    assert capped == A(s * MC_STABILITY_GAIN_CAP, abs=1e-9)
    assert capped == _approx(4.6130)
    # the cap never raises a gain that was already under it
    _, small = next_state(d, s, Rating.HARD, 1.0)
    _, small_capped = next_state(d, s, Rating.HARD, 1.0, mc_unassisted=True)
    assert small_capped == A(min(small, s * MC_STABILITY_GAIN_CAP))


def test_mc_cap_never_applies_to_a_first_rating():
    assert next_state(None, None, Rating.EASY, 0.0, mc_unassisted=True) == (
        initial_difficulty(Rating.EASY),
        initial_stability(Rating.EASY),
    )


def test_next_state_rejects_bad_inputs():
    with pytest.raises(ValueError):
        next_state(2.0, 0.0, Rating.GOOD, 1.0)
    with pytest.raises(ValueError):
        next_state(2.0, 2.0, Rating.GOOD, -1.0)


@pytest.mark.parametrize(
    "d, s, days",
    [
        (0.0, 2.0, 1.0),  # D outside [1, 10]: D^(−w12) would divide by zero
        (-1.0, 2.0, 1.0),  # a negative base to a fractional power is complex
        (10.5, 2.0, 1.0),
        (NAN, 2.0, 1.0),
        (2.0, NAN, 1.0),
        (2.0, INF, 1.0),
        (2.0, 2.0, NAN),
    ],
)
def test_next_state_rejects_out_of_domain_state(d, s, days):
    with pytest.raises(ValueError):
        next_state(d, s, Rating.GOOD, days)
    with pytest.raises(ValueError):
        next_state(d, s, Rating.AGAIN, days, same_day=True)


# --- rating map (spec §3.2; §13 A1: idk is a flag, not a channel) -----------


@pytest.mark.parametrize(
    "channel, correct, max_rung, idk, expected",
    [
        ("free_response", True, 0, False, Rating.GOOD),
        ("teachback_llm", True, 0, False, Rating.GOOD),
        ("mc_reasoned", True, 0, False, Rating.GOOD),
        ("mc", True, 0, False, Rating.GOOD),
        ("chat_turn", True, 0, False, Rating.HARD),  # † spec omits chat_turn (§13 A7)
        ("free_response", True, 1, False, Rating.HARD),
        ("free_response", True, 3, False, Rating.HARD),
        ("mc", True, 2, False, Rating.HARD),
        ("free_response", True, 4, False, Rating.AGAIN),
        ("free_response", True, 6, False, Rating.AGAIN),
        ("free_response", False, 0, False, Rating.AGAIN),
        ("mc", False, 3, False, Rating.AGAIN),
        ("chat_turn", False, 0, False, Rating.AGAIN),
        ("free_response", False, 0, True, Rating.AGAIN),
        ("mc", True, 0, True, Rating.AGAIN),  # idk overrides a stray correct=True
    ],
)
def test_rating_map(channel, correct, max_rung, idk, expected):
    assert rating_for(channel, correct, max_rung, idk=idk) == int(expected)


def test_rating_channels_are_the_evidence_channels():
    # §13 A1 / spec §5: Evidence.channel is the ITEM's channel; there is no
    # "idk" channel. params.CHANNELS is the one list; PKG-03 asserts its
    # Evidence Literal equals this set.
    assert fsrs.RATING_CHANNELS == frozenset(CHANNELS)
    assert fsrs.RATING_CHANNELS == {
        "free_response",
        "mc_reasoned",
        "mc",
        "teachback_llm",
        "chat_turn",
    }
    assert fsrs.STRONG_GOOD_CHANNELS < fsrs.RATING_CHANNELS


def test_rating_for_never_emits_easy():
    for channel in sorted(fsrs.RATING_CHANNELS):
        for correct in (True, False):
            for idk in (True, False):
                for max_rung in range(0, 7):
                    rating = rating_for(channel, correct, max_rung, idk=idk)
                    assert rating != int(Rating.EASY)
                    assert rating in (Rating.AGAIN, Rating.HARD, Rating.GOOD)


def test_rating_for_rejects_unknown_channel_and_negative_rung():
    with pytest.raises(ValueError):
        rating_for("quiz", True, 0)
    with pytest.raises(ValueError):
        rating_for("idk", False, 0)  # §13 A1: idk=True on the item's channel instead
    with pytest.raises(ValueError):
        rating_for("mc", True, -1)


@pytest.mark.parametrize("bad_rung", [NAN, INF, -INF, 2.5, "0", None])
def test_rating_for_and_mc_cap_reject_a_non_integer_rung(bad_rung):
    # NaN rated Again and 2.5 rated Hard before: a rung is a whole ladder step.
    with pytest.raises(ValueError):
        rating_for("mc", True, bad_rung)
    with pytest.raises(ValueError):
        mc_cap_applies("mc", True, bad_rung)


@pytest.mark.parametrize("args", [("quiz", True, 0), ("idk", False, 0), ("mc", True, -1)])
def test_mc_cap_applies_validates_like_rating_for(args):
    # PKG-03 calls both with the same arguments; they must agree on the domain.
    with pytest.raises(ValueError):
        rating_for(*args)
    with pytest.raises(ValueError):
        mc_cap_applies(*args)


def test_mc_cap_applies_only_to_unassisted_mc_correct():
    assert mc_cap_applies("mc", True, 0) is True
    assert mc_cap_applies("mc", True, 1) is False
    assert mc_cap_applies("mc", False, 0) is False
    assert mc_cap_applies("mc", True, 0, idk=True) is False
    assert mc_cap_applies("mc_reasoned", True, 0) is False


def test_mc_cap_applies_exactly_when_mc_rates_good():
    for correct in (True, False):
        for idk in (True, False):
            for max_rung in range(0, 7):
                good = rating_for("mc", correct, max_rung, idk=idk) == Rating.GOOD
                assert mc_cap_applies("mc", correct, max_rung, idk=idk) is good


# --- due ordering + budget --------------------------------------------------


def _row(node_id, s, days_ago):
    return {
        "node_id": node_id,
        "fsrs_s": s,
        "fsrs_last_review_at": (NOW - timedelta(days=days_ago)).isoformat(),
    }


def test_order_due_sorts_by_distance_from_threshold():
    rng = random.Random(11)
    rows = [_row(f"n{i}", rng.uniform(0.2, 60.0), rng.uniform(0.0, 120.0)) for i in range(40)]
    before = copy.deepcopy(rows)
    ordered = order_due(rows, NOW)
    dist = [abs(item_retrievability(r, NOW) - REVIEW_ORDER_THRESHOLD) for r in ordered]
    assert dist == sorted(dist)
    assert sorted(r["node_id"] for r in ordered) == sorted(r["node_id"] for r in rows)
    assert rows == before  # input untouched: same rows, same order
    assert ordered is not rows


def test_order_due_is_stable_on_ties():
    rows = [_row(f"n{i}", 5.0, 5.0) for i in range(6)]
    assert [r["node_id"] for r in order_due(rows, NOW)] == [f"n{i}" for i in range(6)]


def test_order_due_never_reviewed_rows_sort_last():
    rows = [
        {"node_id": "fresh", "fsrs_s": None, "fsrs_last_review_at": None},
        _row("stale", FSRS_S0_GOOD, 60.0),
    ]
    assert [r["node_id"] for r in order_due(rows, NOW)] == ["stale", "fresh"]
    assert item_retrievability(rows[0], NOW) == 1.0
    assert item_retrievability({"node_id": "bare"}, NOW) == 1.0


def test_item_retrievability_accepts_datetime_and_z_suffix():
    dt_row = {"fsrs_s": 10.0, "fsrs_last_review_at": NOW - timedelta(days=10)}
    z_row = {"fsrs_s": 10.0, "fsrs_last_review_at": "2026-09-16T12:00:00Z"}
    naive_row = {"fsrs_s": 10.0, "fsrs_last_review_at": datetime(2026, 9, 16, 12, 0)}
    assert item_retrievability(dt_row, NOW) == A(0.9, abs=1e-9)
    assert item_retrievability(z_row, NOW) == A(0.9, abs=1e-9)
    assert item_retrievability(naive_row, NOW) == A(0.9, abs=1e-9)  # naive = UTC
    assert item_retrievability(z_row, "2026-09-26T12:00:00Z") == A(0.9, abs=1e-9)


def test_item_retrievability_rejects_a_corrupt_row():
    with pytest.raises(ValueError):
        item_retrievability({"fsrs_s": 0.0, "fsrs_last_review_at": NOW}, NOW)
    with pytest.raises(ValueError):
        item_retrievability({"fsrs_s": 1.0, "fsrs_last_review_at": "not a date"}, NOW)


def test_order_due_custom_keys_for_flashcards():
    rows = [
        {"id": "a", "fsrs_s": 1.0, "last_reviewed_at": (NOW - timedelta(days=30)).isoformat()},
        {"id": "b", "fsrs_s": 1.0, "last_reviewed_at": NOW.isoformat()},
    ]
    ordered = order_due(rows, NOW, last_review_key="last_reviewed_at")
    assert [r["id"] for r in ordered] == ["a", "b"]


def test_budget_items_from_constants():
    assert budget_items() == (REVIEW_DAILY_BUDGET_MIN * 60) // REVIEW_SECONDS_PER_CHECK == 16
    assert budget_items(0) == 0
    assert budget_items(-5) == 0
    with pytest.raises(ValueError):
        budget_items(10, 0)
    with pytest.raises(ValueError):
        budget_items(10, NAN)
    with pytest.raises(ValueError):
        budget_items(NAN)


def test_budget_select_never_exceeds_budget():
    rng = random.Random(3)
    for _ in range(30):
        n = rng.randint(0, 60)
        budget_min = rng.choice([0, 1, 5, REVIEW_DAILY_BUDGET_MIN, 30])
        seconds_per = rng.choice([15, REVIEW_SECONDS_PER_CHECK, 120])
        items = list(range(n))
        chosen = budget_select(items, budget_min, seconds_per)
        assert len(chosen) <= budget_min * 60 // seconds_per
        assert len(chosen) <= n
        assert chosen == items[: len(chosen)]
    assert budget_select(list(range(40))) == list(range(16))


# --- flag-off inertness -----------------------------------------------------


def _imports_fsrs(source: str) -> bool:
    """True when `source` imports learning.fsrs in any spelling: `import
    learning.fsrs`, `from learning.fsrs import x`, `from learning import bkt,
    fsrs`, parenthesised lists, or an import inside a function (ast, not regex)."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(
                a.name == "learning.fsrs" or a.name.startswith("learning.fsrs.") for a in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom) and not node.level:
            module = node.module or ""
            if module == "learning.fsrs" or module.startswith("learning.fsrs."):
                return True
            if module == "learning" and any(a.name == "fsrs" for a in node.names):
                return True
    return False


@pytest.mark.parametrize(
    "source, expected",
    [
        ("import learning.fsrs", True),
        ("from learning.fsrs import next_state", True),
        ("from learning import bkt, fsrs", True),
        ("from learning import (\n    fsrs,\n)", True),
        ("def f():\n    from learning import fsrs", True),
        ("from learning import bkt", False),
        ("from learning.gate import learning_loop_active", False),
        ("# from learning import fsrs", False),
    ],
)
def test_fsrs_import_detector(source, expected):
    assert _imports_fsrs(source) is expected


def _calls_gate(source: str) -> bool:
    """True when `source` CALLS learning_loop_active (bare or as an attribute).
    A comment, a string, or an import of the name alone is not a call."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "learning_loop_active":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "learning_loop_active":
                return True
    return False


def _route_violates_gate_rule(source: str) -> bool:
    """Behaviour 10's standing rule for a route module: importing learning.fsrs
    requires a learning_loop_active(...) call in the same module."""
    return _imports_fsrs(source) and not _calls_gate(source)


_UNGATED_ROUTE = """
from learning.fsrs import next_state
# TODO: wrap in learning_loop_active later
def h(row):
    return next_state(row["d"], row["s"], 3, 1.0)
"""


@pytest.mark.parametrize(
    "source, violates",
    [
        (_UNGATED_ROUTE, True),  # the gate named only in a comment
        ("from learning.gate import learning_loop_active\nfrom learning import fsrs", True),
        ("from learning import fsrs\nGATE = 'learning_loop_active'", True),
        (
            "from learning import fsrs\nfrom learning.gate import learning_loop_active\n"
            "def h(uid):\n    if learning_loop_active(uid):\n        fsrs.order_due([], 0)",
            False,
        ),
        (
            "from learning import fsrs, gate\ndef h(uid):\n    return gate.learning_loop_active(uid)",
            False,
        ),
        ("from learning.gate import learning_loop_active\ndef h(uid):\n    return 1", False),
    ],
)
def test_route_gate_rule_detector(source, violates):
    assert _route_violates_gate_rule(source) is violates


def test_routes_import_fsrs_only_behind_the_gate():
    """Every module under routes/ that imports learning.fsrs calls learning_loop_active.

    This pins the standing rule, not the PKG-02 state "nothing imports fsrs":
    PKG-03 (services/graph_service.py), PKG-11 (routes/flashcards.py) and
    PKG-12 (its review service) add sanctioned importers, and PKG-03/PKG-11 may
    not edit this module. The zero-importer state is acceptance 8's grep.
    """
    routes = pathlib.Path(__file__).resolve().parents[1] / "routes"
    paths = sorted(routes.rglob("*.py"))
    assert paths, "routes/ not found"
    offenders = [
        str(path.relative_to(routes))
        for path in paths
        if _route_violates_gate_rule(path.read_text())
    ]
    assert offenders == [], f"routes import learning.fsrs without calling the gate: {offenders}"


# --- successive relearning --------------------------------------------------


def test_relearning_initial_criterion_then_three_sessions():
    st = SuccessiveRelearning()
    assert st.phase == fsrs.SR_ACQUISITION and not st.complete
    st = st.advance(False, session_id="s1")
    assert st.correct_in_acquisition == 0
    for i in range(SR_INITIAL_CRITERION - 1):
        st = st.advance(True, session_id="s1")
        assert st.phase == fsrs.SR_ACQUISITION, i
    st = st.advance(True, session_id="s1")
    assert st.phase == fsrs.SR_RELEARN
    assert st.correct_in_acquisition == SR_INITIAL_CRITERION
    # a correct recall in the acquisition session does not count as a relearn session
    assert st.advance(True, session_id="s1") == st
    for k in range(1, SR_RELEARN_SESSIONS + 1):
        st = st.advance(False, session_id=f"r{k}")
        st = st.advance(True, session_id=f"r{k}")
        st = st.advance(True, session_id=f"r{k}")  # second correct in the same session: no-op
        assert st.relearn_sessions_done == k
    assert st.phase == fsrs.SR_DONE and st.complete
    assert st.advance(True, session_id="later") == st


def test_relearning_acquisition_counts_cumulative_not_consecutive():
    st = SuccessiveRelearning()
    for correct in (True, False, True, False, True):
        st = st.advance(correct, session_id="s1")
    assert st.phase == fsrs.SR_RELEARN


def test_relearning_is_immutable_and_round_trips():
    a = SuccessiveRelearning()
    b = a.advance(True, session_id="s1")
    assert a.correct_in_acquisition == 0 and b.correct_in_acquisition == 1
    assert SuccessiveRelearning.from_dict(b.as_dict()) == b
    assert SuccessiveRelearning.from_dict(None) == SuccessiveRelearning()
    assert SuccessiveRelearning.from_dict({}) == SuccessiveRelearning()


@pytest.mark.parametrize(
    "data",
    [
        {"phase": "review"},
        {"correct_in_acquisition": -1},
        {"relearn_sessions_done": -1},
        # from_dict must not coerce before validating: int() truncated 2.7 to 2,
        # parsed "2", and raised TypeError/OverflowError on None/inf.
        {"correct_in_acquisition": 2.7},
        {"correct_in_acquisition": "2"},
        {"correct_in_acquisition": None},
        {"relearn_sessions_done": INF},
        {"relearn_sessions_done": NAN},
    ],
)
def test_relearning_rejects_a_corrupt_stored_state(data):
    with pytest.raises(ValueError):
        SuccessiveRelearning.from_dict(data)


def test_relearning_stores_whole_counters_as_int():
    # A JSON 2.0 is a whole number: accepted, and stored as the int it names.
    for st in (
        SuccessiveRelearning(correct_in_acquisition=2.0, relearn_sessions_done=1.0),
        SuccessiveRelearning.from_dict(
            {"correct_in_acquisition": 2.0, "relearn_sessions_done": 1.0}
        ),
    ):
        assert (st.correct_in_acquisition, st.relearn_sessions_done) == (2, 1)
        assert type(st.correct_in_acquisition) is int
        assert type(st.relearn_sessions_done) is int


@pytest.mark.parametrize(
    "kwargs",
    [
        {"correct_in_acquisition": NAN},
        {"correct_in_acquisition": 1.5},
        {"relearn_sessions_done": INF},
    ],
)
def test_relearning_rejects_a_non_integer_counter(kwargs):
    with pytest.raises(ValueError):
        SuccessiveRelearning(**kwargs)
