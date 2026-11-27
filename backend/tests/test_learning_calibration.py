"""learning/calibration.py: BKT's predicted P(correct) against observed
unassisted outcomes, surfaced as the admin learning-loop KPI `calibration`."""

from __future__ import annotations

import pytest

from learning import calibration as cal
from learning.params import CALIBRATION_BINS, CHANNELS


def _row(p, correct, *, channel="free_response", assisted=False, max_rung=0, weight=1.0,
         session="s1"):
    return {"p_before": p, "correct": correct, "channel": channel, "assisted": assisted,
            "max_rung": max_rung, "weight": weight, "session_id": session}


def test_prediction_is_the_bkt_emission_probability():
    g, s = CHANNELS["free_response"]["G"], CHANNELS["free_response"]["S"]
    assert cal.predicted_correct(0.0, "free_response") == pytest.approx(g)
    assert cal.predicted_correct(1.0, "free_response") == pytest.approx(1 - s)
    assert cal.predicted_correct(0.5, "free_response") == pytest.approx(0.5 * (1 - s) + 0.5 * g)


@pytest.mark.parametrize(
    "row",
    [
        _row(0.5, True, channel="mc"),  # weak channel: guessable
        _row(0.5, True, channel="chat_turn"),
        _row(0.5, True, assisted=True),  # helped: not independent
        _row(0.5, True, max_rung=2),
        _row(0.5, True, max_rung="H1"),
        _row(0.5, True, weight=0.5),  # recheck / low confidence / propagation
        _row(0.5, True, weight=True),
        _row(None, True),
        _row(1.5, True),
        _row(True, True),
        _row(0.5, None),
        _row(0.5, "yes"),
    ],
)
def test_only_independent_observations_count(row):
    assert cal.eligible(row) is None


def test_independent_observations_are_kept():
    assert cal.eligible(_row(0.9, True)) is not None
    assert cal.eligible(_row(0.9, False, channel="mc_reasoned", max_rung="H0")) is not None
    assert cal.eligible({**_row(0.9, True), "weight": None}) is not None  # legacy row


def test_empty_is_nones_not_zeros():
    out = cal.calibration([])
    for part in ("all", "posttest"):
        rep = out[part]
        assert rep["n"] == 0
        assert rep["brier"] is None and rep["ece"] is None
        assert rep["mean_predicted"] is None and rep["observed_rate"] is None
        assert len(rep["bins"]) == CALIBRATION_BINS
        assert all(b["n"] == 0 and b["observed"] is None for b in rep["bins"])


def test_brier_and_rates():
    rows = [_row(1.0, True), _row(0.0, False)]
    rep = cal.calibration(rows)["all"]
    hi = cal.predicted_correct(1.0, "free_response")
    lo = cal.predicted_correct(0.0, "free_response")
    assert rep["n"] == 2
    assert rep["brier"] == pytest.approx(((hi - 1) ** 2 + lo ** 2) / 2)
    assert rep["observed_rate"] == pytest.approx(0.5)
    assert rep["mean_predicted"] == pytest.approx((hi + lo) / 2)


def test_overconfident_model_shows_a_gap_in_the_top_bin():
    # predicted ≈0.9 but only half came true → ECE ≈ 0.4 for that bin's share
    rows = [_row(1.0, True), _row(1.0, False)] * 5
    rep = cal.calibration(rows)["all"]
    top = rep["bins"][-1]
    assert top["n"] == 10 and top["observed"] == pytest.approx(0.5)
    assert rep["ece"] == pytest.approx(abs(0.5 - cal.predicted_correct(1.0, "free_response")))


def test_bins_cover_the_unit_interval_and_clamp_the_top_edge():
    rep = cal.summarize([(1.0, True), (0.0, False), (0.5, True)])
    assert rep["bins"][0]["lo"] == 0.0 and rep["bins"][-1]["hi"] == 1.0
    assert sum(b["n"] for b in rep["bins"]) == 3
    assert rep["bins"][-1]["n"] == 1  # 1.0 lands in the last bin, not past it


def test_posttest_subset_is_sessionless_strong_evidence():
    rows = [
        _row(0.9, True, session=None),  # post-test
        _row(0.9, False, session=""),  # post-test
        _row(0.9, True, session="s1"),  # in-session check
        _row(0.9, True, channel="mc", session=None),  # quiz: weak, excluded everywhere
    ]
    out = cal.calibration(rows)
    assert out["all"]["n"] == 3
    assert out["posttest"]["n"] == 2
    assert out["posttest"]["observed_rate"] == pytest.approx(0.5)
