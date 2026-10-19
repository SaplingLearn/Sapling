"""
Unit tests for the one score → tier map (PKG-14b, spec §11.2).

config.py's legacy tier function (0.75 / 0.45 / 0.1) is deleted; every caller
uses learning.bkt.tier_for on the spec §3.1 cuts TIER_UNEXPLORED_MAX /
BAND_NOVICE_MAX / BKT_PROFICIENT (0.10 / 0.30 / 0.95). The class name is kept
so the history of these boundary tests reads straight through.
"""
import pytest

from learning.bkt import tier_for
from learning.params import BAND_NOVICE_MAX, BKT_PROFICIENT, TIER_UNEXPLORED_MAX


class TestGetMasteryTier:
    # ── unexplored ────────────────────────────────────────────────────────────

    def test_zero_is_unexplored(self):
        assert tier_for(0.0) == "unexplored"

    def test_just_below_struggling_threshold_is_unexplored(self):
        assert tier_for(0.09) == "unexplored"

    def test_negative_is_rejected(self):
        # Clamping happens upstream; tier_for refuses a belief outside [0, 1]
        # (spec §Error semantics) instead of classifying it.
        with pytest.raises(ValueError):
            tier_for(-1.0)

    # ── struggling ────────────────────────────────────────────────────────────

    def test_at_struggling_threshold(self):
        assert tier_for(TIER_UNEXPLORED_MAX) == "struggling"

    def test_mid_struggling(self):
        assert tier_for(0.25) == "struggling"

    def test_just_below_learning_is_struggling(self):
        assert tier_for(0.29) == "struggling"

    # ── learning ──────────────────────────────────────────────────────────────

    def test_at_learning_threshold(self):
        assert tier_for(BAND_NOVICE_MAX) == "learning"

    def test_mid_learning(self):
        assert tier_for(0.6) == "learning"

    def test_just_below_mastered_is_learning(self):
        assert tier_for(0.94) == "learning"

    # ── mastered ──────────────────────────────────────────────────────────────

    def test_at_mastered_threshold(self):
        assert tier_for(BKT_PROFICIENT) == "mastered"

    def test_mid_mastered(self):
        assert tier_for(0.97) == "mastered"

    def test_perfect_score_is_mastered(self):
        assert tier_for(1.0) == "mastered"

    def test_cuts_are_the_spec_3_1_mirror(self):
        assert (TIER_UNEXPLORED_MAX, BAND_NOVICE_MAX, BKT_PROFICIENT) == (0.10, 0.30, 0.95)
