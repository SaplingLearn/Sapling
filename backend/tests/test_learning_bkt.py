"""PKG-01: learning.params constants + learning.bkt pure BKT (spec §3.1).

Hand-computed expectations are derived from the spec §3.1 equations with the
§3.1 channel table; see PKG-01-bkt-core.md §Spec "Hand-computed expectations".
No DB, no LLM, no fixtures beyond monkeypatch.
"""

from __future__ import annotations

import ast
import math
import pathlib
import sys

import pytest

from learning import bkt, params


def _disallowed_imports(src: str, package: str, allowed: set[str]) -> set[str]:
    """Every module `src` imports (parsed with ast: comma lists, relative and
    function-local imports all count) that is neither standard library nor in
    `allowed`. `from <package> import x` and `from . import x` name the
    submodule `<package>.x`, so `from learning import fsrs` is caught."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                parent = ".".join(parts[: len(parts) - node.level + 1])
                base = f"{parent}.{base}" if base else parent
            if base == package:
                found.update(f"{base}.{alias.name}" for alias in node.names)
            else:
                found.add(base)
    return {m for m in found if m.split(".")[0] not in sys.stdlib_module_names and m not in allowed}


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
    "GRADER_SECOND_OPINION_CONFIDENCE",
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


# Spec §3.1–§3.4 values, typed out from the spec (not read back from params),
# so changing a constant is a deliberate two-place edit. The band, tier and
# mastery tests read their cuts from params and would pass any number.
SPEC_VALUES = {
    # §3.1
    "BKT_L0": 0.35,
    "BKT_T": 0.15,
    "BKT_G_MAX": 0.30,
    "BKT_S_MAX": 0.30,
    "BKT_PROFICIENT": 0.95,
    "BKT_MASTERED": 0.98,
    "BKT_MASTERED_MIN_STRONG": 3,
    "BAND_NOVICE_MAX": 0.30,
    "BAND_DEVELOP_MAX": 0.80,
    "TIER_UNEXPLORED_MAX": 0.10,
    "WEIGHT_ASSISTED": 0.5,
    "WEIGHT_SAME_SESSION_RECHECK": 0.5,
    "WEIGHT_PROPAGATION": 0.5,
    "WEIGHT_LOW_CONFIDENCE": 0.5,
    "S_IDK": 0.02,
    "CHANNELS": {
        "free_response": {"G": 0.08, "S": 0.10, "strong": True},
        "mc_reasoned": {"G": 0.10, "S": 0.10, "strong": True},
        "mc": {"G": 0.25, "S": 0.10, "strong": False},
        "teachback_llm": {"G": 0.25, "S": 0.20, "strong": False},
        "chat_turn": {"G": 0.30, "S": 0.30, "strong": False},
    },
    "STRONG_CHANNELS": frozenset({"free_response", "mc_reasoned"}),
    "PROPAGATION_CHANNEL": "chat_turn",
    "EDGE_PREREQ_SOURCE_IS_PREREQ": True,  # PKG-08 may flip it: edit here in the same commit
    # §3.2
    "FSRS_W": (
        0.212,
        1.2931,
        2.3065,
        8.2956,
        6.4133,
        0.8334,
        3.0194,
        0.001,
        1.8722,
        0.1666,
        0.796,
        1.4835,
        0.0614,
        0.2629,
        1.6483,
        0.6014,
        1.8729,
        0.5425,
        0.0912,
        0.0658,
        0.1542,
    ),
    "FSRS_RETENTION_DEFAULT": 0.90,
    "FSRS_RETENTION_LARGE_SET": 0.85,
    "FSRS_LARGE_SET_CONCEPTS": 150,
    "FSRS_RETENTION_EXAM": 0.95,
    "FSRS_EXAM_WINDOW_DAYS": 14,
    "FSRS_S0_GOOD": 2.3065,
    "REVIEW_ORDER_THRESHOLD": 0.33,
    "REVIEW_DAILY_BUDGET_MIN": 12,
    "REVIEW_SECONDS_PER_CHECK": 45,
    "MC_STABILITY_GAIN_CAP": 2.0,
    "SR_INITIAL_CRITERION": 3,
    "SR_RELEARN_SESSIONS": 3,
    # §3.3
    "GATE_INDEPENDENT_MIN_S": 45,
    "GATE_INDEPENDENT_MIN_S_NOVICE": 90,
    "GATE_RUNG_DWELL_MIN_S": 8,
    "H6_MIN_GENUINE_ATTEMPTS": 2,
    "OFFER_BANDS": frozenset({"novice"}),
    "BAND_WINDOW": 8,
    "PROBE_TARGET_LO": 0.50,
    "PROBE_TARGET_HI": 0.62,
    "ACQ_TARGET_LO": 0.75,
    "ACQ_TARGET_HI": 0.90,
    "PRACTICE_TARGET_LO": 0.65,
    "PRACTICE_TARGET_HI": 0.85,
    "EXAM_TARGET_LO": 0.70,
    "EXAM_TARGET_HI": 0.85,
    "PI_LO": 0.35,
    "PI_HI": 0.70,
    "PI_MIN_ROOM": 5,
    "WHEELSPIN_OPPS": 10,
    "MISCONCEPTION_CONFIDENCE": 0.7,
    "NOVICE_FLOOR_MISSES": 3,
    # §3.4
    "PROBE_ITEMS_PER_SKILL_MIN": 4,
    "PROBE_ITEMS_PER_SKILL_MAX": 6,
    "PROBE_SESSION_CAP": 12,
    "PROBE_STOP_DELTA": 0.05,
    "PLAN_MAX_CONCEPTS": 5,
    "PLAN_MAX_COUPLED": 2,
    "PLAN_ORDER": ("due_reviews", "new_material", "interleaved_siblings"),
    "STEP_MAX_SENTENCES": 5,
    "STEP_QUESTIONS_PER_TURN": 1,
    "LOOP_HISTORY_MAX_MESSAGES": 20,
    "LEARNER_BRIEF_MAX_CHARS": 1800,
    "LEARNER_BRIEF_LAST_CLOSES": 3,
    "LEARNER_BRIEF_TOP_STATES": 5,
    "LEARNER_BRIEF_MAX_MISCONCEPTIONS": 5,
    "LOOP_LIMITS": {"request_limit": 14, "tool_calls_limit": 14, "total_tokens_limit": 120_000},
    "GRADER_LIMITS": {"request_limit": 2, "tool_calls_limit": 0, "total_tokens_limit": 20_000},
    "GRADER_LOW_CONFIDENCE": 0.6,
    "GRADER_SECOND_OPINION_CONFIDENCE": 0.4,
    "LEAK_NGRAM": 6,
    "CHECK_ITEM_FORMATS": ("free", "teachback", "mc_reason"),
    "CHECK_ITEM_DIFFICULTIES": (1, 2, 3),
    "CHECK_ITEM_MIN_RUBRIC": 2,
    "CHECK_ITEM_MIN_WRONG": 1,
    "MISCONCEPTION_ROLLUP_MIN_USERS": 5,
    "ZPD_RATING_EVERY_N_CHECKS": 30,
}


def test_spec_values_cover_every_spec_name():
    assert set(SPEC_VALUES) == set(SPEC_31_NAMES + SPEC_32_NAMES + SPEC_33_NAMES + SPEC_34_NAMES)


@pytest.mark.parametrize("name", sorted(SPEC_VALUES))
def test_every_spec_constant_has_the_spec_value(name):
    got, want = getattr(params, name), SPEC_VALUES[name]
    assert got == want, f"{name} = {got!r}; spec §3 says {want!r}"
    assert type(got) is type(want), (
        f"{name} is {type(got).__name__}, spec shape is {type(want).__name__}"
    )


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
    # BKT_P_MAX: spec §13 row pending; the cap must leave BKT_MASTERED reachable.
    assert params.BKT_MASTERED < params.BKT_P_MAX < 1.0
    assert params.TIER_UNEXPLORED_MAX < params.BAND_NOVICE_MAX < params.BAND_DEVELOP_MAX
    assert params.PROBE_TARGET_LO < params.PROBE_TARGET_HI
    assert params.ACQ_TARGET_LO < params.ACQ_TARGET_HI
    assert params.PRACTICE_TARGET_LO < params.PRACTICE_TARGET_HI
    assert params.EXAM_TARGET_LO < params.EXAM_TARGET_HI
    assert params.PI_LO < params.PI_HI
    assert params.PROBE_ITEMS_PER_SKILL_MIN < params.PROBE_ITEMS_PER_SKILL_MAX
    assert params.GRADER_SECOND_OPINION_CONFIDENCE < params.GRADER_LOW_CONFIDENCE


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
    src = pathlib.Path(params.__file__).read_text()
    assert _disallowed_imports(src, "learning", set()) == set()


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


def _idk_posterior(p: float, channel: str) -> float:
    """Spec §3.1 incorrect line with the item channel's G and S_IDK, written
    out here so the test does not trust bkt._posterior."""
    g = params.CHANNELS[channel]["G"]
    return p * params.S_IDK / (p * params.S_IDK + (1.0 - p) * (1.0 - g))


@pytest.mark.parametrize("channel", sorted(params.CHANNELS))
def test_idk_uses_the_item_channels_g(channel):
    """§13 A1: idk keeps the item channel's G. Only free_response was checked
    before, so an idk that always used G = 0.08 passed."""
    post = _idk_posterior(P_HIGH, channel)
    want = post + (1.0 - post) * params.BKT_T
    assert bkt.update(P_HIGH, channel, False, idk=True) == pytest.approx(want, abs=1e-12)
    assert bkt.update(P_HIGH, channel, True, idk=True) == pytest.approx(want, abs=1e-12)


def test_idk_on_mc_hand_computed():
    # 0.90·0.02 / (0.018 + 0.10·0.75) = 0.1935; + 0.8065·0.15 = 0.3145
    assert bkt.update(P_HIGH, "mc", False, idk=True) == pytest.approx(0.3145, abs=TOL)


@pytest.mark.parametrize("channel", ["free_response", "mc"])
def test_idk_honours_weight_and_skips_learn_step(channel):
    post = _idk_posterior(P_HIGH, channel)
    want = P_HIGH + 0.5 * (post - P_HIGH)
    got = bkt.update(P_HIGH, channel, False, weight=0.5, idk=True)
    assert got == pytest.approx(want, abs=1e-12)


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
    """Correct never lowers belief below where it started, except that update
    caps its output at BKT_P_MAX, so an input above the cap (1.0) comes back
    at the cap."""
    up = bkt.update(p, channel, True)
    down = bkt.update(p, channel, False, weight=0.5)
    assert 0.0 <= up <= params.BKT_P_MAX and 0.0 <= down <= params.BKT_P_MAX
    assert up >= min(p, params.BKT_P_MAX)
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


def test_bkt_p_max_value():
    """BKT_P_MAX is not a spec §3.1 name (spec §13 row pending, CodeRabbit PR
    #673), so it is pinned here rather than in SPEC_VALUES: a † engineering
    choice that keeps belief interior."""
    assert params.BKT_P_MAX == 0.999
    assert type(params.BKT_P_MAX) is float


def _correct_streak(n: int) -> float:
    p = params.BKT_L0
    for _ in range(n):
        p = bkt.update(p, "free_response", True)
    return p


@pytest.mark.parametrize("n", [15, 50])
def test_correct_streak_stops_at_the_cap(n):
    """HANDOFF-01 Known gap (j), closed. Back-to-back full-weight corrects used
    to round p to exactly 1.0 (15 on free_response), where the incorrect
    posterior is 1·S/(1·S + 0) = 1 and no wrong answer or idk moved it. update
    now stops at BKT_P_MAX (reached after 3 corrects from BKT_L0)."""
    p = _correct_streak(n)
    assert p == params.BKT_P_MAX
    assert p < 1.0
    assert bkt.decayed_p(p, 1.0, None) <= p  # decay never pushes it back up


def test_one_wrong_from_the_cap_lowers_p_but_does_not_unmaster():
    """From BKT_P_MAX a wrong free_response: posterior 0.999·0.10 /
    (0.0999 + 0.001·0.92) = 0.99087; learn step + 0.00913·0.15 = 0.99224.
    One slip lowers belief and stays at or above BKT_MASTERED."""
    p = _correct_streak(15)
    once = bkt.update(p, "free_response", False)
    assert once == pytest.approx(0.99224, abs=1e-5)
    assert once < p
    assert once >= params.BKT_MASTERED
    assert bkt.is_mastered(once, params.BKT_MASTERED_MIN_STRONG)


def test_two_wrongs_from_the_cap_unmaster():
    """Second wrong from 0.99224: posterior 0.93291; learn step 0.94297,
    below BKT_MASTERED (and BKT_PROFICIENT)."""
    once = bkt.update(_correct_streak(15), "free_response", False)
    twice = bkt.update(once, "free_response", False)
    assert twice == pytest.approx(0.94297, abs=1e-5)
    assert twice < params.BKT_MASTERED
    assert not bkt.is_mastered(twice, params.BKT_MASTERED_MIN_STRONG)


def test_idk_from_the_cap_lowers_p():
    """idk from BKT_P_MAX on free_response: posterior 0.999·0.02 /
    (0.01998 + 0.001·0.92) = 0.95598; learn step 0.96258."""
    p = _correct_streak(15)
    got = bkt.update(p, "free_response", True, idk=True)
    assert got == pytest.approx(0.96258, abs=1e-5)
    assert got < p


@pytest.mark.parametrize("channel", sorted(params.CHANNELS))
@pytest.mark.parametrize("p", [params.BKT_P_MAX, math.nextafter(1.0, 0.0), 1.0])
def test_update_output_never_exceeds_the_cap(channel, p):
    """A stored p above the cap is still a valid input (the domain is [0, 1]);
    whatever is observed, the result is at most BKT_P_MAX, and wrong or idk
    evidence always lowers belief (1.0 used to be a fixed point)."""
    for correct in (True, False):
        for weight in (0.0, 0.5, 1.0):
            assert bkt.update(p, channel, correct, weight=weight) <= params.BKT_P_MAX
    assert bkt.update(p, channel, False) < p
    assert bkt.update(p, channel, False, idk=True) < p


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
    src = pathlib.Path(bkt.__file__).read_text()
    assert _disallowed_imports(src, "learning", {"learning.params"}) == set()


# The substring scan the two import tests above used to run passed every one
# of these (`from learning import fsrs` has no "import learning.fsrs" or
# "from learning.fsrs" in it; comma lists hid the second module).
IMPORT_MUTANTS = [
    ("from learning import fsrs", "learning.fsrs"),
    ("from . import fsrs", "learning.fsrs"),
    ("import os, config", "config"),
    ("import httpx", "httpx"),
    ("import services.encryption", "services.encryption"),
    ("from learning.gate import learning_loop_active", "learning.gate"),
    ("def f():\n    import db.connection", "db.connection"),
]


@pytest.mark.parametrize("line, culprit", IMPORT_MUTANTS, ids=[m[1] for m in IMPORT_MUTANTS])
def test_import_guard_catches_what_a_substring_scan_missed(line, culprit):
    src = "from __future__ import annotations\n\nfrom learning.params import BKT_L0\n" + line
    assert culprit in _disallowed_imports(src, "learning", {"learning.params"})


def test_import_guard_accepts_the_shipped_shapes():
    src = (
        "from __future__ import annotations\nimport math\nfrom typing import Literal\n"
        "from collections.abc import Mapping\nfrom learning.params import BKT_L0\n"
        "from learning import params\nfrom .params import BKT_T\n"
    )
    assert _disallowed_imports(src, "learning", {"learning.params"}) == set()
    assert _disallowed_imports(src, "learning", set()) == {"learning.params"}
