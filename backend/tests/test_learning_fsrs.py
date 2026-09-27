"""learning.fsrs — FSRS-6 scheduler (spec §3.2). Pure maths, no DB, no LLM.

Reference values were computed from the spec §3.2 formulas over FSRS_W and
are stated to four decimals; ``pytest.approx(abs=5e-5)`` throughout.
"""

from __future__ import annotations

import random

import pytest

from learning import fsrs
from learning.fsrs import (
    interval,
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
