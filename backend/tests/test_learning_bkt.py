"""PKG-01: learning.params constants + learning.bkt pure BKT (spec §3.1).

Hand-computed expectations are derived from the spec §3.1 equations with the
§3.1 channel table; see PKG-01-bkt-core.md §Spec "Hand-computed expectations".
No DB, no LLM, no fixtures beyond monkeypatch.
"""

from __future__ import annotations

import math

import pytest

from learning import bkt, params

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


# ------------------------------------------------------------------ update


P_LOW = 0.30
P_HIGH = 0.90
TOL = 1e-3


@pytest.mark.parametrize(
    "channel, post, final",
    [
        ("free_response", 0.8282, 0.8540),
        ("mc_reasoned", 0.7941, 0.8250),
        ("mc", 0.6067, 0.6657),
        ("teachback_llm", 0.5783, 0.6416),
        ("chat_turn", 0.5000, 0.5750),
    ],
)
def test_correct_from_p_low_matches_hand_computation(channel, post, final):
    g, s = params.CHANNELS[channel]["G"], params.CHANNELS[channel]["S"]
    assert bkt._posterior(P_LOW, g, s, True) == pytest.approx(post, abs=TOL)
    assert bkt.update(P_LOW, channel, True) == pytest.approx(final, abs=TOL)


def test_wrong_free_response_from_p_high_twice():
    """0.90 → 0.570 → 0.257 through update (learn step after each full-weight
    observation). The research report's ≈0.50 / ≈0.09 are the observation-only
    posteriors, pinned in the next test."""
    once = bkt.update(P_HIGH, "free_response", False)
    assert once == pytest.approx(0.5703, abs=TOL)
    twice = bkt.update(once, "free_response", False)
    assert twice == pytest.approx(0.2572, abs=TOL)


def test_wrong_free_response_observation_only_chain():
    g, s = params.CHANNELS["free_response"]["G"], params.CHANNELS["free_response"]["S"]
    once = bkt._posterior(P_HIGH, g, s, False)
    assert once == pytest.approx(0.4945, abs=TOL)
    assert bkt._posterior(once, g, s, False) == pytest.approx(0.0961, abs=TOL)


def test_idk_uses_channel_g_with_s_idk_and_ignores_correct():
    g = params.CHANNELS["free_response"]["G"]
    assert bkt._posterior(P_HIGH, g, params.S_IDK, False) == pytest.approx(0.1636, abs=TOL)
    got = bkt.update(P_HIGH, "free_response", False, idk=True)
    assert got == pytest.approx(0.2891, abs=TOL)
    assert bkt.update(P_HIGH, "free_response", True, idk=True) == got
    # idk drops belief harder than an ordinary wrong answer on the same channel
    assert got < bkt.update(P_HIGH, "free_response", False)


def test_weight_interpolates_and_skips_learn_step():
    half = bkt.update(P_LOW, "free_response", True, weight=0.5)
    assert half == pytest.approx(0.5641, abs=TOL)
    assert bkt.update(P_LOW, "free_response", True, weight=0.0) == pytest.approx(P_LOW)
    full = bkt.update(P_LOW, "free_response", True, weight=1.0)
    assert half < full


def test_learn_step_applies_only_at_full_weight():
    # weight=1.0 wrong from a low p can still RISE (learn step); weight<1 cannot
    assert bkt.update(0.0, "chat_turn", False) == pytest.approx(params.BKT_T)
    assert bkt.update(0.0, "chat_turn", False, weight=0.999) == pytest.approx(0.0)


@pytest.mark.parametrize("channel", sorted(params.CHANNELS))
@pytest.mark.parametrize("p", [0.0, 0.05, 0.35, 0.5, 0.8, 0.95, 1.0])
def test_monotone_and_bounded(channel, p):
    up = bkt.update(p, channel, True)
    down = bkt.update(p, channel, False, weight=0.5)
    assert 0.0 <= up <= 1.0 and 0.0 <= down <= 1.0
    assert up >= p
    assert down <= p


def test_stronger_channel_moves_more():
    fr = bkt.update(P_LOW, "free_response", True)
    mcr = bkt.update(P_LOW, "mc_reasoned", True)
    mc = bkt.update(P_LOW, "mc", True)
    chat = bkt.update(P_LOW, "chat_turn", True)
    assert fr > mcr > mc > chat > P_LOW


def test_one_graded_check_outweighs_a_chat_turn():
    """Spec §1: a chat-turn "correct" is undone, and more, by one graded wrong."""
    chat = bkt.update(P_LOW, "chat_turn", True)
    assert chat > P_LOW
    assert bkt.update(chat, "free_response", False) < P_LOW


def test_update_rejects_bad_inputs():
    with pytest.raises(ValueError, match="channel"):
        bkt.update(P_LOW, "idk", True)
    with pytest.raises(ValueError, match="channel"):
        bkt.update(P_LOW, "essay", True)
    with pytest.raises(ValueError, match="p"):
        bkt.update(1.5, "mc", True)
    with pytest.raises(ValueError, match="p"):
        bkt.update(-0.1, "mc", True)
    with pytest.raises(ValueError, match="weight"):
        bkt.update(P_LOW, "mc", True, weight=1.5)
    with pytest.raises(ValueError, match="weight"):
        bkt.update(P_LOW, "mc", True, weight=-0.5)


# --------------------------------------------------------------- decayed_p


def test_retrievability_is_point_nine_at_t_equals_s():
    for s in (0.5, params.FSRS_S0_GOOD, 10.0, 100.0):
        assert bkt._retrievability(s, s) == pytest.approx(0.9, abs=1e-9)
    assert bkt._retrievability(0.0, params.FSRS_S0_GOOD) == pytest.approx(1.0)


def test_decay_hand_computed():
    s0 = params.FSRS_S0_GOOD
    assert bkt.decayed_p(P_HIGH, s0, s0) == pytest.approx(0.845, abs=TOL)
    assert bkt.decayed_p(P_HIGH, 30.0, None) == pytest.approx(0.7171, abs=TOL)
    assert bkt.decayed_p(0.10, 30.0, None) == pytest.approx(0.1831, abs=TOL)


def test_no_time_no_decay():
    for p in (0.0, 0.10, params.BKT_L0, 0.7, 1.0):
        assert bkt.decayed_p(p, 0.0, None) == p
        assert bkt.decayed_p(p, -3.0, None) == p  # clock skew clamps to 0


def test_decay_moves_toward_prior_from_both_sides_and_is_monotone():
    above = [bkt.decayed_p(P_HIGH, d, None) for d in (0, 1, 7, 30, 365, 3650)]
    below = [bkt.decayed_p(0.05, d, None) for d in (0, 1, 7, 30, 365, 3650)]
    assert above == sorted(above, reverse=True)
    assert below == sorted(below)
    assert all(params.BKT_L0 <= x <= P_HIGH for x in above)
    assert all(0.05 <= x <= params.BKT_L0 for x in below)
    # power-law tail: ten years still leaves belief well above the prior
    assert above[-1] < above[0] and above[-1] > params.BKT_L0


def test_prior_is_a_fixed_point_of_decay():
    for d in (0.0, 1.0, 30.0, 1000.0):
        assert bkt.decayed_p(params.BKT_L0, d, None) == pytest.approx(params.BKT_L0)


def test_higher_stability_decays_slower():
    slow = bkt.decayed_p(P_HIGH, 30.0, 60.0)
    fast = bkt.decayed_p(P_HIGH, 30.0, params.FSRS_S0_GOOD)
    assert slow > fast


def test_missing_stability_uses_s0_good():
    assert bkt.decayed_p(P_HIGH, 9.0, None) == bkt.decayed_p(P_HIGH, 9.0, params.FSRS_S0_GOOD)


def test_decayed_p_rejects_nonpositive_stability():
    with pytest.raises(ValueError, match="stability"):
        bkt.decayed_p(P_HIGH, 1.0, 0.0)
    with pytest.raises(ValueError, match="stability"):
        bkt.decayed_p(P_HIGH, 1.0, -2.0)


@pytest.mark.parametrize("stability", [math.nan, math.inf])
def test_decayed_p_rejects_non_finite_stability(stability):
    """NaN slipped past `<= 0` and _clamp01 turned the NaN result into 0.0 (below
    the prior); inf read as "never forgets". Both are corrupt FSRS state."""
    with pytest.raises(ValueError, match="stability"):
        bkt.decayed_p(P_HIGH, 1.0, stability)
    with pytest.raises(ValueError, match="stability"):
        bkt.decayed_p(P_HIGH, 0.0, stability)


def test_decayed_p_rejects_nan_days():
    """max(0.0, nan) is 0.0, so NaN used to read as "no time passed"."""
    with pytest.raises(ValueError, match="days_since"):
        bkt.decayed_p(P_HIGH, math.nan, None)


def test_decayed_p_infinite_days_is_the_prior():
    """+inf is the documented limit, not an error: belief lands on BKT_L0."""
    assert bkt.decayed_p(P_HIGH, math.inf, None) == pytest.approx(params.BKT_L0)
    assert bkt.decayed_p(0.05, math.inf, None) == pytest.approx(params.BKT_L0)


# ------------------------------------------- propagate / band / tier / mastery


def test_propagation_correct_goes_to_parents_only():
    out = bkt.propagate_prereq(True, ["pre_a", "pre_b"], ["dep_c"])
    assert out == [
        ("pre_a", params.PROPAGATION_CHANNEL, True, params.WEIGHT_PROPAGATION),
        ("pre_b", params.PROPAGATION_CHANNEL, True, params.WEIGHT_PROPAGATION),
    ]


def test_propagation_incorrect_goes_to_children_only():
    out = bkt.propagate_prereq(False, ["pre_a", "pre_b"], ["dep_c", "dep_d"])
    assert out == [
        ("dep_c", params.PROPAGATION_CHANNEL, False, params.WEIGHT_PROPAGATION),
        ("dep_d", params.PROPAGATION_CHANNEL, False, params.WEIGHT_PROPAGATION),
    ]


def test_propagation_empty_and_shape():
    assert bkt.propagate_prereq(True, [], ["dep_c"]) == []
    assert bkt.propagate_prereq(False, ["pre_a"], []) == []
    for node_id, channel, correct, weight in bkt.propagate_prereq(True, ["x"], []):
        assert isinstance(node_id, str) and channel in params.CHANNELS
        assert isinstance(correct, bool) and 0.0 < weight < 1.0


def test_propagated_observation_is_weak():
    """A propagated hop is a half-weight chat-strength observation: it never
    triggers the learn step and moves belief less than the direct check."""
    ((node_id, channel, correct, weight),) = bkt.propagate_prereq(True, ["pre_a"], [])
    hop = bkt.update(P_LOW, channel, correct, weight=weight)
    direct = bkt.update(P_LOW, "free_response", True)
    assert P_LOW < hop < direct
    assert hop - P_LOW < 0.15


def _just_below(x: float) -> float:
    return math.nextafter(x, 0.0)


def test_band_boundaries():
    assert bkt.band(0.0) == "novice"
    assert bkt.band(_just_below(params.BAND_NOVICE_MAX)) == "novice"
    assert bkt.band(params.BAND_NOVICE_MAX) == "develop"
    assert bkt.band(_just_below(params.BAND_DEVELOP_MAX)) == "develop"
    assert bkt.band(params.BAND_DEVELOP_MAX) == "profic"
    assert bkt.band(1.0) == "profic"


def test_tier_boundaries_and_check_values():
    assert bkt.tier_for(0.0) == "unexplored"
    assert bkt.tier_for(_just_below(params.TIER_UNEXPLORED_MAX)) == "unexplored"
    assert bkt.tier_for(params.TIER_UNEXPLORED_MAX) == "struggling"
    assert bkt.tier_for(_just_below(params.BAND_NOVICE_MAX)) == "struggling"
    assert bkt.tier_for(params.BAND_NOVICE_MAX) == "learning"
    assert bkt.tier_for(_just_below(params.BKT_PROFICIENT)) == "learning"
    assert bkt.tier_for(params.BKT_PROFICIENT) == "mastered"
    assert bkt.tier_for(1.0) == "mastered"
    allowed = {"unexplored", "struggling", "learning", "mastered"}  # graph_nodes.mastery_tier CHECK
    assert {bkt.tier_for(p / 100) for p in range(0, 101)} <= allowed


def test_tier_for_is_not_the_legacy_tier():
    """Loop-path cuts differ from config.get_mastery_tier (legacy stays until PKG-14)."""
    import config

    assert bkt.tier_for(0.80) == "learning"
    assert config.get_mastery_tier(0.80) == "mastered"
    assert config.MASTERY_MASTERED_MIN == 0.75  # pinned by test_mastery_tier_unification; untouched


def test_proficient_and_mastered():
    assert bkt.is_proficient(params.BKT_PROFICIENT) is True
    assert bkt.is_proficient(_just_below(params.BKT_PROFICIENT)) is False
    assert bkt.is_mastered(params.BKT_MASTERED, params.BKT_MASTERED_MIN_STRONG) is True
    assert bkt.is_mastered(params.BKT_MASTERED, params.BKT_MASTERED_MIN_STRONG - 1) is False
    assert bkt.is_mastered(_just_below(params.BKT_MASTERED), 10) is False
    assert bkt.is_mastered(1.0, 0) is False


def test_mastered_implies_proficient():
    for p in (0.98, 0.99, 1.0):
        if bkt.is_mastered(p, params.BKT_MASTERED_MIN_STRONG):
            assert bkt.is_proficient(p)


BAD_P = [math.nan, -0.1, 1.5, math.inf, -math.inf]
P_CONSUMERS = {
    "update": lambda p: bkt.update(p, "mc", True),
    "decayed_p": lambda p: bkt.decayed_p(p, 1.0, None),
    "decayed_p_at_zero_days": lambda p: bkt.decayed_p(p, 0.0, None),
    "band": bkt.band,
    "tier_for": bkt.tier_for,
    "is_proficient": bkt.is_proficient,
    "is_mastered": lambda p: bkt.is_mastered(p, params.BKT_MASTERED_MIN_STRONG),
}


@pytest.mark.parametrize("p", BAD_P, ids=repr)
@pytest.mark.parametrize("fn", list(P_CONSUMERS.values()), ids=list(P_CONSUMERS))
def test_every_p_consumer_rejects_out_of_range_p(fn, p):
    """Spec §Error semantics: out-of-range p raises. Before, tier_for(nan) was
    "mastered", band(nan) "profic", and decayed_p(1.5, 0, None) returned 1.5."""
    with pytest.raises(ValueError, match="p must be in"):
        fn(p)


def test_bkt_imports_only_stdlib_and_params():
    import pathlib

    src = pathlib.Path(bkt.__file__).read_text()
    for root in ("agents", "pydantic_ai", "google", "db", "config", "learning.fsrs", "services"):
        assert f"import {root}" not in src and f"from {root}" not in src, root
