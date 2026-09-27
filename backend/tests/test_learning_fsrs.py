"""learning.fsrs — FSRS-6 scheduler (spec §3.2). Pure maths, no DB, no LLM.

Reference values were computed from the spec §3.2 formulas over FSRS_W and
are stated to four decimals; ``pytest.approx(abs=5e-5)`` throughout.
"""

from __future__ import annotations

import random

import pytest

from learning import fsrs
from learning.fsrs import (
    Rating,
    initial_difficulty,
    initial_stability,
    interval,
    next_state,
    retention_target,
    retrievability,
)
from learning.params import (
    FSRS_EXAM_WINDOW_DAYS,
    FSRS_LARGE_SET_CONCEPTS,
    FSRS_RETENTION_DEFAULT,
    FSRS_RETENTION_EXAM,
    FSRS_RETENTION_LARGE_SET,
    FSRS_S0_GOOD,
    FSRS_W,
    MC_STABILITY_GAIN_CAP,
)

A = pytest.approx
TOL = 5e-5
NAN = float("nan")
INF = float("inf")


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
    assert nd == _approx(2.1170)
    assert ns == _approx(13.8269)


def test_hard_after_three_days_reference():
    d, s = _after_first_good()
    nd, ns = next_state(d, s, Rating.HARD, 3.0)
    assert nd == _approx(4.7586)
    assert ns == _approx(9.2349)


def test_again_after_three_days_reference():
    d, s = _after_first_good()
    nd, ns = next_state(d, s, Rating.AGAIN, 3.0)
    assert nd == _approx(7.4003)
    assert ns == _approx(0.6369)


def test_same_day_reference():
    d, s = _after_first_good()
    nd, ns = next_state(d, s, Rating.GOOD, 0.0, same_day=True)
    assert (nd, ns) == (_approx(2.1170), _approx(2.2938))
    nd, ns = next_state(d, s, Rating.AGAIN, 0.0, same_day=True)
    assert (nd, ns) == (_approx(7.4003), _approx(0.7751))


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
    assert fsrs._next_difficulty(5.0, Rating.GOOD) == _approx(4.9960)
    assert fsrs._next_difficulty(5.0, Rating.AGAIN) == _approx(8.3475)
    assert fsrs._next_difficulty(10.0, Rating.AGAIN) == _approx(9.9910)
    assert fsrs._next_difficulty(1.0, Rating.EASY) == 1.0


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
