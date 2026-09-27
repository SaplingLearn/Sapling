"""PKG-01: learning.params constants + learning.bkt pure BKT (spec §3.1).

Hand-computed expectations are derived from the spec §3.1 equations with the
§3.1 channel table; see PKG-01-bkt-core.md §Spec "Hand-computed expectations".
No DB, no LLM, no fixtures beyond monkeypatch.
"""

from __future__ import annotations

import pytest

from learning import params

# ---------------------------------------------------------------- params


SPEC_31_NAMES = (
    "BKT_L0",
    "BKT_T",
    "BKT_G_MAX",
    "BKT_S_MAX",
    "BKT_PROFICIENT",
    "BKT_MASTERED",
    "BKT_MASTERED_MIN_STRONG",
    "BAND_NOVICE_MAX",
    "BAND_DEVELOP_MAX",
    "TIER_UNEXPLORED_MAX",
    "WEIGHT_ASSISTED",
    "WEIGHT_SAME_SESSION_RECHECK",
    "WEIGHT_PROPAGATION",
    "WEIGHT_LOW_CONFIDENCE",
    "S_IDK",
    "CHANNELS",
    "STRONG_CHANNELS",
    "PROPAGATION_CHANNEL",
    "EDGE_PREREQ_SOURCE_IS_PREREQ",
)
SPEC_32_NAMES = (
    "FSRS_W",
    "FSRS_RETENTION_DEFAULT",
    "FSRS_RETENTION_LARGE_SET",
    "FSRS_LARGE_SET_CONCEPTS",
    "FSRS_RETENTION_EXAM",
    "FSRS_EXAM_WINDOW_DAYS",
    "FSRS_S0_GOOD",
    "REVIEW_ORDER_THRESHOLD",
    "REVIEW_DAILY_BUDGET_MIN",
    "REVIEW_SECONDS_PER_CHECK",
    "MC_STABILITY_GAIN_CAP",
    "SR_INITIAL_CRITERION",
    "SR_RELEARN_SESSIONS",
)
SPEC_33_NAMES = (
    "GATE_INDEPENDENT_MIN_S",
    "GATE_INDEPENDENT_MIN_S_NOVICE",
    "GATE_RUNG_DWELL_MIN_S",
    "H6_MIN_GENUINE_ATTEMPTS",
    "OFFER_BANDS",
    "BAND_WINDOW",
    "PROBE_TARGET_LO",
    "PROBE_TARGET_HI",
    "ACQ_TARGET_LO",
    "ACQ_TARGET_HI",
    "PRACTICE_TARGET_LO",
    "PRACTICE_TARGET_HI",
    "EXAM_TARGET_LO",
    "EXAM_TARGET_HI",
    "PI_LO",
    "PI_HI",
    "PI_MIN_ROOM",
    "WHEELSPIN_OPPS",
    "MISCONCEPTION_CONFIDENCE",
    "NOVICE_FLOOR_MISSES",
)
SPEC_34_NAMES = (
    "PROBE_ITEMS_PER_SKILL_MIN",
    "PROBE_ITEMS_PER_SKILL_MAX",
    "PROBE_SESSION_CAP",
    "PROBE_STOP_DELTA",
    "PLAN_MAX_CONCEPTS",
    "PLAN_MAX_COUPLED",
    "PLAN_ORDER",
    "STEP_MAX_SENTENCES",
    "STEP_QUESTIONS_PER_TURN",
    "LOOP_HISTORY_MAX_MESSAGES",
    "LEARNER_BRIEF_MAX_CHARS",
    "LEARNER_BRIEF_LAST_CLOSES",
    "LEARNER_BRIEF_TOP_STATES",
    "LEARNER_BRIEF_MAX_MISCONCEPTIONS",
    "LOOP_LIMITS",
    "GRADER_LIMITS",
    "GRADER_LOW_CONFIDENCE",
    "GRADER_RETRY_BELOW",
    "LEAK_NGRAM",
    "CHECK_ITEM_FORMATS",
    "CHECK_ITEM_DIFFICULTIES",
    "CHECK_ITEM_MIN_RUBRIC",
    "CHECK_ITEM_MIN_WRONG",
    "MISCONCEPTION_ROLLUP_MIN_USERS",
    "ZPD_RATING_EVERY_N_CHECKS",
)


@pytest.mark.parametrize("name", SPEC_31_NAMES + SPEC_32_NAMES + SPEC_33_NAMES + SPEC_34_NAMES)
def test_every_spec_constant_is_defined(name):
    assert hasattr(params, name), f"spec §3 constant {name} missing from learning.params"


def test_channel_table_shape():
    for name, row in params.CHANNELS.items():
        assert set(row) == {"G", "S", "strong"}, name
    assert params.STRONG_CHANNELS == frozenset({"free_response", "mc_reasoned"})
    assert params.PROPAGATION_CHANNEL in params.CHANNELS
    assert params.PROPAGATION_CHANNEL not in params.STRONG_CHANNELS


def test_fsrs_weights_and_s0():
    assert len(params.FSRS_W) == 21
    assert params.FSRS_S0_GOOD == params.FSRS_W[2]
    assert isinstance(params.FSRS_W, tuple)


def test_ordered_pairs_are_ordered():
    assert params.BKT_PROFICIENT < params.BKT_MASTERED
    assert params.TIER_UNEXPLORED_MAX < params.BAND_NOVICE_MAX < params.BAND_DEVELOP_MAX
    assert params.PROBE_TARGET_LO < params.PROBE_TARGET_HI
    assert params.ACQ_TARGET_LO < params.ACQ_TARGET_HI
    assert params.PRACTICE_TARGET_LO < params.PRACTICE_TARGET_HI
    assert params.EXAM_TARGET_LO < params.EXAM_TARGET_HI
    assert params.PI_LO < params.PI_HI
    assert params.PROBE_ITEMS_PER_SKILL_MIN < params.PROBE_ITEMS_PER_SKILL_MAX
    assert params.GRADER_RETRY_BELOW < params.GRADER_LOW_CONFIDENCE


def test_limits_are_plain_dicts_with_usage_limits_keys():
    for limits in (params.LOOP_LIMITS, params.GRADER_LIMITS):
        assert set(limits) == {"request_limit", "tool_calls_limit", "total_tokens_limit"}


def test_validate_channels_accepts_the_shipped_table():
    params.validate_channels(params.CHANNELS, params.BKT_T)


@pytest.mark.parametrize(
    "row, needle",
    [
        ({"G": 0.5, "S": 0.6, "strong": False}, r"G \+ S"),
        ({"G": 0.31, "S": 0.10, "strong": False}, "BKT_G_MAX"),
        ({"G": 0.10, "S": 0.31, "strong": False}, "BKT_S_MAX"),
    ],
)
def test_validate_channels_rejects_bad_rows(row, needle):
    with pytest.raises(ValueError, match=needle):
        params.validate_channels({"bad": row}, params.BKT_T)


def test_validate_channels_rejects_bad_t():
    with pytest.raises(ValueError, match="BKT_T"):
        params.validate_channels(params.CHANNELS, 0.95)
    with pytest.raises(ValueError, match="BKT_T"):
        params.validate_channels(params.CHANNELS, 0.0)


def test_params_imports_only_stdlib():
    import pathlib

    src = pathlib.Path(params.__file__).read_text()
    for root in ("agents", "pydantic_ai", "google", "db", "config", "learning.fsrs"):
        assert f"import {root}" not in src and f"from {root}" not in src, root
