"""PKG-06 ZPD policy layer (spec §3.3, §3.4, §4, §6). Pure-code tests: fake
clocks are floats, the only I/O is a mocked `table`."""

from __future__ import annotations

import pytest

from learning import params

PARAM_NAMES = (
    "BKT_PROFICIENT",
    "BKT_MASTERED_MIN_STRONG",
    "WEIGHT_ASSISTED",
    "WEIGHT_SAME_SESSION_RECHECK",
    "FSRS_RATING_AGAIN",
    "FSRS_RATING_HARD",
    "FSRS_RATING_GOOD",
    "FSRS_RATING_EASY",
    "GATE_INDEPENDENT_MIN_S",
    "GATE_INDEPENDENT_MIN_S_NOVICE",
    "GATE_RUNG_DWELL_MIN_S",
    "H6_MIN_GENUINE_ATTEMPTS",
    "OFFER_BANDS",
    "BAND_WINDOW",
    "PRACTICE_TARGET_LO",
    "BAND_CONTROL_HI",
    "BAND_CONTROL_STOP_WINDOWS",
    "CEILING_PROFIC_ESCALATE_FAILS",
    "CEILING_DEVELOP_H6_FAILS",
    "WHEELSPIN_OPPS",
    "WHEELSPIN_OPPS_EARLY",
    "WHEELSPIN_UNASSISTED_MAX",
    "LEAK_NGRAM",
    "ZPD_RATING_EVERY_N_CHECKS",
    "LOOP_RAG_K_TEACH",
    "LOOP_RAG_K_TEACH_SOFT",
    "LOOP_SOURCE_CHUNKS_MAX",
    "LOOP_TIER_DEEP_MIN_FAILS",
)


# ── params + ladder ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", PARAM_NAMES)
def test_params_exports_every_pkg06_name(name):
    assert hasattr(params, name), f"learning.params lacks {name}"


def test_params_relations_hold():
    assert (
        params.GATE_INDEPENDENT_MIN_S_NOVICE
        > params.GATE_INDEPENDENT_MIN_S
        > params.GATE_RUNG_DWELL_MIN_S
    )
    assert params.PRACTICE_TARGET_LO < params.BAND_CONTROL_HI < params.BKT_PROFICIENT
    assert params.WHEELSPIN_OPPS_EARLY < params.WHEELSPIN_OPPS
    assert (
        params.FSRS_RATING_AGAIN
        < params.FSRS_RATING_HARD
        < params.FSRS_RATING_GOOD
        < params.FSRS_RATING_EASY
    )
    assert "novice" in params.OFFER_BANDS
    assert 0 < params.LOOP_RAG_K_TEACH_SOFT < params.LOOP_RAG_K_TEACH
    assert params.LOOP_SOURCE_CHUNKS_MAX >= 1 and params.LOOP_TIER_DEEP_MIN_FAILS >= 1


def test_pkg06_param_values_are_the_spec_values():
    """Spec §3.3 band control / ceiling / wheelspin cut-points and §3.5 routing
    constants: one place each, the value the spec states."""
    assert params.BAND_CONTROL_HI == 0.90
    assert params.BAND_CONTROL_STOP_WINDOWS == 2
    assert params.CEILING_PROFIC_ESCALATE_FAILS == 2
    assert params.CEILING_DEVELOP_H6_FAILS == 2
    assert params.WHEELSPIN_OPPS_EARLY == 6
    assert params.WHEELSPIN_UNASSISTED_MAX == 0.50
    assert params.LOOP_RAG_K_TEACH == 5
    assert params.LOOP_RAG_K_TEACH_SOFT == 3
    assert params.LOOP_SOURCE_CHUNKS_MAX == 2
    assert params.LOOP_TIER_DEEP_MIN_FAILS == 2


def test_fsrs_rating_names_are_the_fsrs_rating_values():
    """params cannot import fsrs (fsrs imports params), so the four names are
    int literals; this pins them to PKG-02's Rating enum (one value, one meaning)."""
    from learning.fsrs import Rating

    assert (
        params.FSRS_RATING_AGAIN,
        params.FSRS_RATING_HARD,
        params.FSRS_RATING_GOOD,
        params.FSRS_RATING_EASY,
    ) == (Rating.AGAIN, Rating.HARD, Rating.GOOD, Rating.EASY)


def test_ladder_rungs_are_h0_to_h6_with_intent():
    from learning.ladder import RUNG_INTENT, Rung, intent, next_rung

    assert [r.name for r in Rung] == ["H0", "H1", "H2", "H3", "H4", "H5", "H6"]
    assert [int(r) for r in Rung] == list(range(len(Rung)))
    assert int(max(Rung)) == params.LADDER_MAX_RUNG
    assert set(RUNG_INTENT) == set(Rung)
    for r in Rung:
        assert intent(r) and intent(r) == RUNG_INTENT[r]
    assert next_rung(Rung.H0) is Rung.H1
    assert next_rung(Rung.H6) is Rung.H6
    assert "never" in intent(Rung.H6).lower()  # practice only, never graded, never exam
