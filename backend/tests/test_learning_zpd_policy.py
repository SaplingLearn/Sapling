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


# ── policy: ceiling table (spec §3.3, every row) ──────────────────────────────


def _learner(band, prereq=True, p=0.5, un=None, opps=0, streak=0):
    from learning.policy import LearnerView

    return LearnerView(
        p_known=p,
        band=band,
        prereq_proficient=prereq,
        unassisted_next=un,
        opps=opps,
        streak_unassisted=streak,
    )


def _step(fails=0, showed_work=False, exam=False, rung=0, first=1000.0, last=None, attempts=()):
    from learning.ladder import Rung
    from learning.policy import StepState

    return StepState(
        question_hash="q" * 64,
        rung=Rung(rung),
        genuine_attempts=fails,
        first_shown_at=first,
        last_rung_at=last,
        attempted_at=list(attempts),
        showed_work=showed_work,
        exam_mode=exam,
    )


CEILING_CASES = [
    # (band, prereq, fails, showed_work, exam) -> rung name, reason name
    ("profic", True, 0, False, True, "H1", "EXAM"),
    ("develop", True, 3, True, True, "H1", "EXAM"),  # exam beats the shown-work floor
    ("profic", True, 0, False, False, "H1", "PROFIC"),
    ("profic", True, 1, False, False, "H1", "PROFIC"),
    ("profic", True, 2, False, False, "H3", "PROFIC_ESCALATED"),
    ("profic", True, 0, True, False, "H3", "SHOWED_WORK_FLOOR"),
    ("profic", True, 2, True, False, "H3", "PROFIC_ESCALATED"),  # already at the floor
    ("develop", True, 0, False, False, "H3", "DEVELOP"),
    ("develop", True, 1, False, False, "H4", "DEVELOP"),
    ("develop", True, 2, False, False, "H6", "DEVELOP_H6"),
    ("develop", True, 5, False, False, "H6", "DEVELOP_H6"),
    ("novice", True, 0, False, False, "H5", "NOVICE_PREREQ_OK"),
    ("novice", True, 3, False, False, "H5", "NOVICE_PREREQ_OK"),
    ("novice", False, 0, False, False, "H4", "NOVICE_WORKED_FIRST"),
    ("novice", False, 1, False, False, "H5", "NOVICE_PREREQ_GAP"),
    ("novice", False, 0, True, False, "H4", "NOVICE_WORKED_FIRST"),  # floor never lowers
]


@pytest.mark.parametrize("band,prereq,fails,showed,exam,rung,reason", CEILING_CASES)
def test_ceiling_table(band, prereq, fails, showed, exam, rung, reason):
    from learning.ladder import Rung
    from learning.policy import CeilingReason, ceiling, ceiling_with_reason

    learner, step = _learner(band, prereq), _step(fails=fails, showed_work=showed, exam=exam)
    assert ceiling(learner, step) is Rung[rung]
    assert ceiling_with_reason(learner, step) == (Rung[rung], CeilingReason[reason])


def test_ceiling_never_exceeds_h6_or_drops_below_floor():
    from learning.ladder import Rung
    from learning.policy import ceiling

    for band in ("novice", "develop", "profic"):
        for fails in range(0, 12):
            r = ceiling(_learner(band, True), _step(fails=fails, showed_work=True))
            assert Rung.H3 <= r <= Rung.H6


def test_ceiling_rejects_programmer_errors():
    """Typed state only: an unknown band or a negative attempt count is a bug
    in the caller, never a silent H3."""
    from learning.policy import ceiling

    with pytest.raises(ValueError):
        ceiling(_learner("expert"), _step())
    with pytest.raises(ValueError):
        ceiling(_learner("develop"), _step(fails=-1))


def test_attempt_first_false_only_for_novice_without_prereq():
    from learning.policy import attempt_first

    assert attempt_first(_learner("novice", prereq=False)) is False
    assert attempt_first(_learner("novice", prereq=True)) is True
    assert attempt_first(_learner("develop", prereq=False)) is True
    assert attempt_first(_learner("profic", prereq=False)) is True


def test_band_alias_matches_bkt_band():
    from typing import get_args

    from learning import bkt, policy

    assert get_args(policy.Band) == get_args(bkt.Band)


# ── policy: evidence mapping ──────────────────────────────────────────────────

EVIDENCE_CASES = [
    # correct, max_rung, same_session -> weight, streak, rating
    (True, 0, False, 1.0, True, "FSRS_RATING_GOOD"),
    (True, 1, False, params.WEIGHT_ASSISTED, False, "FSRS_RATING_HARD"),
    (True, 3, False, params.WEIGHT_ASSISTED, False, "FSRS_RATING_HARD"),
    (True, 4, False, 0.0, False, "FSRS_RATING_AGAIN"),
    (True, 6, False, 0.0, False, "FSRS_RATING_AGAIN"),
    (False, 0, False, 1.0, False, "FSRS_RATING_AGAIN"),
    (False, 5, False, 1.0, False, "FSRS_RATING_AGAIN"),
    # A correct same-session re-check is not a first attempt: PKG-03's
    # apply_graph_update counts it as an opportunity only (neither extends nor
    # breaks streak_unassisted), so the policy says the same (HANDOFF-03).
    (True, 0, True, params.WEIGHT_SAME_SESSION_RECHECK, False, "FSRS_RATING_GOOD"),
    (
        True,
        2,
        True,
        params.WEIGHT_ASSISTED * params.WEIGHT_SAME_SESSION_RECHECK,
        False,
        "FSRS_RATING_HARD",
    ),
    (False, 0, True, params.WEIGHT_SAME_SESSION_RECHECK, False, "FSRS_RATING_AGAIN"),
]


@pytest.mark.parametrize("correct,rung,same,weight,streak,rating", EVIDENCE_CASES)
def test_evidence_for_rung_table(correct, rung, same, weight, streak, rating):
    from learning.ladder import Rung
    from learning.policy import evidence_for_rung

    ev = evidence_for_rung(correct, Rung(rung), same_session=same)
    assert ev == (pytest.approx(weight), streak, getattr(params, rating))
    assert ev.weight == pytest.approx(weight) and ev.counts_toward_streak is streak


@pytest.mark.parametrize("rung", range(params.LADDER_MAX_RUNG + 1))
@pytest.mark.parametrize("correct", [True, False])
@pytest.mark.parametrize("same", [True, False])
def test_evidence_for_rung_agrees_with_the_evidence_model(rung, correct, same):
    """One weight rule: PKG-03's evidence_weight over the same flags gives the
    same number as the ZPD mapping, and PKG-02's rating_for the same rating."""
    from learning.evidence import Evidence, evidence_weight
    from learning.fsrs import rating_for
    from learning.ladder import Rung
    from learning.policy import evidence_for_rung

    ev = Evidence(
        node_id="n1",
        channel="free_response",
        correct=correct,
        assisted=rung >= params.RUNG_ASSISTED_MIN,
        max_rung=rung,
        same_session_recheck=same,
    )
    mapped = evidence_for_rung(correct, Rung(rung), same_session=same)
    assert mapped.weight == pytest.approx(evidence_weight(ev))
    assert mapped.fsrs_rating == rating_for("free_response", correct, rung)


@pytest.mark.parametrize("bad", [-1, params.LADDER_MAX_RUNG + 1])
def test_evidence_for_rung_rejects_a_rung_off_the_ladder(bad):
    from learning.policy import evidence_for_rung

    with pytest.raises(ValueError):
        evidence_for_rung(True, bad)


# ── policy: band control + wheelspin ──────────────────────────────────────────

W = params.BAND_WINDOW


def _window(rate_last, rate_prev=None):
    """Newest-last bool window with an exact hit rate per BAND_WINDOW block."""

    def block(rate):
        hits = round(rate * W)
        return [True] * hits + [False] * (W - hits)

    return (block(rate_prev) if rate_prev is not None else []) + block(rate_last)


def test_band_control_table():
    from learning.policy import BandAction, band_control

    hi = params.BAND_CONTROL_HI + (1 - params.BAND_CONTROL_HI) / 2
    lo = params.PRACTICE_TARGET_LO / 2
    mid = (params.PRACTICE_TARGET_LO + params.BAND_CONTROL_HI) / 2
    p_ok, p_low = params.BKT_PROFICIENT, params.BKT_PROFICIENT - 0.01
    assert band_control([], p_ok, True) is BandAction.HOLD
    assert band_control(_window(1.0, 1.0), p_ok, True) is BandAction.STOP_PRACTICE
    assert band_control(_window(1.0, 1.0), p_ok, False) is BandAction.HARDER  # belief not stable
    assert band_control(_window(1.0, 1.0), p_low, True) is BandAction.HARDER  # p below proficient
    assert band_control(_window(1.0), p_ok, True) is BandAction.HARDER  # only one window high
    assert (
        band_control(_window(1.0, mid), p_ok, True) is BandAction.HARDER
    )  # previous window not high
    assert band_control(_window(hi), p_low, True) is BandAction.HARDER
    assert band_control(_window(mid), p_low, True) is BandAction.HOLD
    assert band_control(_window(lo), p_low, True) is BandAction.EASIER_CHECK_PREREQS
    assert band_control(_window(mid), p_ok, True, wheelspin=True) is BandAction.WHEELSPIN


def test_band_control_edges_are_the_spec_inequalities():
    """Spec §3.3: "> 0.90" is harder, "0.65 ≤ unassisted_next ≤ 0.90" holds,
    "< 0.65" is easier. With BAND_WINDOW first attempts the reachable rates are
    k / BAND_WINDOW, so each edge is tested at the hit counts either side of it."""
    import math

    from learning.policy import BandAction, band_control

    def hits(k):
        return [True] * k + [False] * (W - k)

    k_lo = math.ceil(params.PRACTICE_TARGET_LO * W)  # fewest hits still in the hold band
    k_hi = math.floor(params.BAND_CONTROL_HI * W)  # most hits still in the hold band
    assert band_control(hits(k_lo), 0.5, True) is BandAction.HOLD
    assert band_control(hits(k_lo - 1), 0.5, True) is BandAction.EASIER_CHECK_PREREQS
    assert band_control(hits(k_hi), 0.5, True) is BandAction.HOLD
    assert band_control(hits(k_hi + 1), 0.5, True) is BandAction.HARDER
    # a partial previous window never counts toward STOP_PRACTICE
    partial = [True] * (W - 1) + hits(W)
    assert band_control(partial, params.BKT_PROFICIENT, True) is BandAction.HARDER
    # an older full window beyond the two the rule reads does not rescue a low one
    assert band_control(hits(W) + hits(k_hi) + hits(W), params.BKT_PROFICIENT, True) is (
        BandAction.HARDER
    )


def test_unassisted_rate_uses_last_window_only():
    from learning.policy import unassisted_rate

    assert unassisted_rate([]) is None
    assert unassisted_rate([False] * W + [True] * W) == pytest.approx(1.0)


def test_wheelspin_rule():
    from learning.policy import wheelspin

    n, e, u = params.WHEELSPIN_OPPS, params.WHEELSPIN_OPPS_EARLY, params.WHEELSPIN_UNASSISTED_MAX
    assert wheelspin(n, False, 0.9) is True
    assert wheelspin(n, True, 0.9) is False
    assert wheelspin(n - 1, False, None) is False
    assert wheelspin(e, True, u - 0.01) is True
    assert wheelspin(e, True, u) is False
    assert wheelspin(e - 1, False, 0.0) is False
    assert wheelspin(e, True, None) is False


# ── policy: LoopState round trip ──────────────────────────────────────────────


def test_loop_state_json_round_trip_and_trim():
    from learning.policy import LoopState

    s = LoopState()
    step = _step(fails=2, last=1010.0, attempts=(1005.0, 1020.0))
    s.steps[step.question_hash] = step
    s.current = step.question_hash
    for i in range(W * params.BAND_CONTROL_STOP_WINDOWS + 3):
        s.record_first_attempt(i % 2 == 0)
    assert len(s.first_attempts) == W * params.BAND_CONTROL_STOP_WINDOWS
    doc = s.to_json()
    assert set(doc) == {"v", "current", "checks_since_rating", "first_attempts", "steps"}
    assert set(doc["steps"][step.question_hash]) == {
        "rung",
        "attempts",
        "first_shown_at",
        "last_rung_at",
        "attempted_at",
        "showed_work",
        "exam_mode",
    }
    assert LoopState.from_json(doc) == s
    assert LoopState.from_json({}) == LoopState()
    with pytest.raises(ValueError):
        LoopState.from_json({"steps": "not-a-dict"})
    s.checks_since_rating = params.ZPD_RATING_EVERY_N_CHECKS - 1
    assert s.rating_due() is False
    s.checks_since_rating += 1
    assert s.rating_due() is True


def test_loop_state_document_is_ids_numbers_and_bools_only():
    import json

    from learning.policy import LoopState

    s = LoopState(current="q" * 64, checks_since_rating=3)
    s.steps["q" * 64] = _step(fails=1, rung=2, last=1004.5, attempts=(1003.0,), showed_work=True)
    s.record_first_attempt(True)
    doc = s.to_json()
    assert json.loads(json.dumps(doc)) == doc  # plain JSON, no enums or tuples
    assert doc["steps"]["q" * 64]["rung"] == 2 and type(doc["steps"]["q" * 64]["rung"]) is int


def test_loop_state_keeps_the_keys_later_packages_add():
    """Spec §4 names top-level keys later packages add to sessions.loop_state
    ("revealed", "probe", "plan", "sr", "review"; §9 "active", "concept", …).
    A load/save through LoopState must carry them unchanged, never drop them."""
    from learning.policy import LoopState

    doc = LoopState().to_json()
    doc["revealed"] = ["b" * 64]
    doc["plan"] = {"approved": ["node-1"], "cursor": 0}
    back = LoopState.from_json(doc).to_json()
    assert back["revealed"] == ["b" * 64] and back["plan"] == {"approved": ["node-1"], "cursor": 0}
    assert LoopState.from_json(doc) == LoopState.from_json(back)
    # the typed keys still win over a same-named extra, and the input is not aliased
    doc["plan"]["cursor"] = 5
    assert back["plan"]["cursor"] == 0


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {"first_attempts": "yes"},
        {"first_attempts": [1, 0]},
        {"checks_since_rating": "3"},
        {"checks_since_rating": -1},
        {"current": 7},
        {"steps": {"q": "not-a-dict"}},
        {"steps": {"q": {}}},
        {"steps": {"q": {"first_shown_at": "1000"}}},
        {"steps": {"q": {"first_shown_at": True}}},
        {"steps": {"q": {"first_shown_at": 1.0, "rung": 9}}},
        {"steps": {"q": {"first_shown_at": 1.0, "attempts": -1}}},
        {"steps": {"q": {"first_shown_at": 1.0, "attempted_at": ["x"]}}},
        {"steps": {"q": {"first_shown_at": 1.0, "last_rung_at": "soon"}}},
        {"steps": {"q": {"first_shown_at": 1.0, "exam_mode": "false"}}},
    ],
)
def test_loop_state_from_json_rejects_malformed_documents(bad):
    from learning.policy import LoopState

    with pytest.raises(ValueError):
        LoopState.from_json(bad)


# ── policy: tutor tier routing (spec §3.5 LOOP_MODEL_TIER, A15) ────────────────

TIER_ORDER = {"none": 0, "lite": 1, "standard": 2, "deep": 3}
FAILS = params.LOOP_TIER_DEEP_MIN_FAILS

TIER_CASES = [
    # (phase, band, rung, fails, misconception, kwargs) -> tier
    ("teach", "develop", 0, 0, False, {"budget_level": "hard"}, "none"),
    (
        "feedback_wrong",
        "novice",
        0,
        FAILS,
        True,
        {"budget_level": "hard", "arm_session": True},
        "none",
    ),
    ("check_pose", "novice", 0, 0, False, {}, "none"),
    ("check_pose", "develop", 0, FAILS, True, {}, "none"),  # the pose is a template, always
    ("hint", "develop", 2, 0, False, {"deterministic_payload": True}, "none"),
    ("hint", "novice", 4, 0, False, {"deterministic_payload": True}, "none"),
    ("hint", "develop", 6, 0, False, {}, "none"),
    ("feedback_correct", "novice", 0, 0, False, {}, "lite"),
    (
        "feedback_correct",
        "develop",
        0,
        FAILS,
        False,
        {},
        "lite",
    ),  # a correct answer closed the step
    ("hint", "profic", 0, 0, False, {}, "lite"),  # proficient-band verification †
    ("teach", "novice", 0, 0, False, {}, "deep"),
    ("hint", "novice", 4, 0, False, {}, "deep"),  # H4 with no usable sibling
    ("hint", "develop", 5, 0, False, {}, "deep"),
    ("teach", "develop", 0, 0, True, {}, "deep"),  # misconception confrontation
    ("hint", "develop", 1, FAILS, False, {}, "deep"),
    ("feedback_wrong", "profic", 0, FAILS, False, {}, "deep"),
    ("opener", "novice", 0, 0, False, {}, "standard"),
    ("teach", "develop", 0, 0, False, {}, "standard"),
    ("teach", "profic", 0, 0, False, {}, "standard"),
    ("hint", "develop", 1, FAILS - 1, False, {}, "standard"),
    ("hint", "novice", 3, 0, False, {}, "standard"),
    ("feedback_wrong", "develop", 0, FAILS - 1, False, {}, "standard"),
    ("hint", "develop", 2, 0, False, {}, "standard"),  # H2, no clean payload †
    ("hint", "develop", 0, 0, False, {}, "standard"),  # H0 outside profic †
    # then-rows: downgrades (deep -> standard only)
    ("teach", "develop", 0, 0, True, {"budget_level": "soft"}, "standard"),
    ("hint", "profic", 5, 0, False, {"deep_cap_reached": True}, "standard"),
    ("teach", "develop", 0, 0, True, {"budget_level": "soft", "arm_session": True}, "deep"),
    (
        "teach",
        "novice",
        0,
        0,
        False,
        {"budget_level": "soft"},
        "deep",
    ),  # $-soft never downgrades novice deep
    (
        "teach",
        "novice",
        0,
        0,
        False,
        {"deep_cap_reached": True},
        "deep",
    ),  # the develop/profic cap is not the novice cap
    ("teach", "novice", 0, 0, False, {"novice_deep_cap_reached": True}, "standard"),
    (
        "teach",
        "novice",
        0,
        0,
        False,
        {"novice_deep_cap_reached": True, "arm_session": True},
        "deep",
    ),
    ("hint", "develop", 5, 0, False, {"novice_deep_cap_reached": True}, "deep"),
    ("feedback_correct", "develop", 0, 0, False, {"budget_level": "soft"}, "lite"),
]


@pytest.mark.parametrize("phase,band,rung,fails,misc,kw,tier", TIER_CASES)
def test_model_tier_table(phase, band, rung, fails, misc, kw, tier):
    from learning.ladder import Rung
    from learning.policy import model_tier

    assert model_tier(phase, band, Rung(rung), fails, misc, **kw) == tier


def test_model_tier_adjustments_never_raise_a_tier():
    import itertools
    from typing import get_args

    from learning.ladder import Rung
    from learning.policy import Tier, TurnPhase, model_tier

    flags = [
        {"budget_level": "soft"},
        {"deep_cap_reached": True},
        {"novice_deep_cap_reached": True},
        {"budget_level": "soft", "arm_session": True},
    ]
    for phase, band, rung, fails, misc, det in itertools.product(
        get_args(TurnPhase),
        ("novice", "develop", "profic"),
        list(Rung),
        range(FAILS + 1),
        (False, True),
        (False, True),
    ):
        base = model_tier(phase, band, rung, fails, misc, deterministic_payload=det)
        assert base in get_args(Tier)
        assert (
            model_tier(
                phase, band, rung, fails, misc, deterministic_payload=det, budget_level="hard"
            )
            == "none"
        )
        assert (
            model_tier(phase, band, rung, fails, misc, deterministic_payload=det, arm_session=True)
            == base
        )
        for kw in flags:
            adjusted = model_tier(phase, band, rung, fails, misc, deterministic_payload=det, **kw)
            assert TIER_ORDER[adjusted] <= TIER_ORDER[base], (
                phase,
                band,
                rung,
                fails,
                misc,
                det,
                kw,
            )
            assert adjusted == base or (base, adjusted) == ("deep", "standard")


def test_model_tier_takes_a_plain_int_rung():
    """PKG-07 may pass loop_state's stored int; Rung(rung) normalises it and an
    off-ladder value is a programmer error."""
    from learning.policy import model_tier

    assert model_tier("hint", "develop", 6, 0, False) == "none"
    with pytest.raises(ValueError):
        model_tier("hint", "develop", params.LADDER_MAX_RUNG + 1, 0, False)


# ── policy: context and tool policy by phase (A18) ────────────────────────────


def test_context_policy_by_phase():
    from learning.policy import ContextPolicy, context_policy

    k, k_soft, chunks = (
        params.LOOP_RAG_K_TEACH,
        params.LOOP_RAG_K_TEACH_SOFT,
        params.LOOP_SOURCE_CHUNKS_MAX,
    )
    assert context_policy("teach", opener=False, budget_level="normal") == ContextPolicy(
        k, True, 0, False, "auto"
    )
    assert context_policy("teach", opener=True, budget_level="normal") == ContextPolicy(
        k, True, 0, True, "auto"
    )
    for level in ("soft", "hard"):
        assert context_policy("teach", opener=False, budget_level=level) == ContextPolicy(
            k_soft, True, 0, False, "none"
        )
    for phase in ("hint", "feedback"):
        for level in ("normal", "soft", "hard"):
            assert context_policy(phase, opener=False, budget_level=level) == ContextPolicy(
                0, False, chunks, False, "none"
            )
    assert context_policy("check", opener=False, budget_level="normal") == ContextPolicy(
        0, False, 0, False, "none"
    )


def test_context_policy_catalog_only_on_the_opener_and_tools_only_in_normal_teach():
    from typing import get_args

    from learning.policy import BudgetLevel, ContextPhase, context_policy

    for phase in get_args(ContextPhase):
        for level in get_args(BudgetLevel):
            assert context_policy(phase, opener=False, budget_level=level).catalog is False
            assert context_policy(phase, opener=True, budget_level=level).catalog is True
            expected = "auto" if (phase == "teach" and level == "normal") else "none"
            assert context_policy(phase, opener=False, budget_level=level).tool_choice == expected
