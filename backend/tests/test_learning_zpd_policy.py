"""PKG-06 ZPD policy layer (spec §3.3, §3.4, §4, §6). Pure-code tests: fake
clocks are floats, the only I/O is a mocked `table`."""

from __future__ import annotations

import logging
import pathlib
import re
from unittest.mock import MagicMock

import pytest

from learning import params

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MIG_DIR = BACKEND / "db" / "migrations"

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
    "EVENT_PAYLOAD_STR_MAX",
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
    assert params.EVENT_PAYLOAD_STR_MAX == 64  # a sha256 question_hash (Behaviour 10)


def test_pkg06_modules_hold_no_numeral():
    """Every threshold is a params.NAME: the only bare numerals in the PKG-06
    modules are 0 / 1 (identity, empty) and the Rung member values."""
    import ast

    for name in _PKG06_MODULES:
        tree = ast.parse((BACKEND / "learning" / f"{name}.py").read_text())
        rung_body = {
            id(n)
            for c in ast.walk(tree)
            if isinstance(c, ast.ClassDef) and c.name == "Rung"
            for n in ast.walk(c)
        }
        stray = [
            (name, node.lineno, node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
            and node.value not in (0, 1)
            and id(node) not in rung_body
        ]
        assert stray == [], stray


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


def test_loop_state_json_round_trip():
    from learning.policy import LoopState

    s = LoopState()
    step = _step(fails=2, last=1010.0, attempts=(1005.0, 1020.0))
    s.steps[step.question_hash] = step
    s.current = step.question_hash
    doc = s.to_json()
    assert set(doc) == {"v", "current", "checks_since_rating", "steps"}
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
    doc = s.to_json()
    assert json.loads(json.dumps(doc)) == doc  # plain JSON, no enums or tuples
    assert doc["steps"]["q" * 64]["rung"] == 2 and type(doc["steps"]["q" * 64]["rung"]) is int


def test_loop_state_holds_no_session_scoped_band_window():
    """Band control is per user x concept across sessions (spec §3.3 over the ZPD
    report's STATE block: unassisted_next is the concept's last BAND_WINDOW
    opportunities, compared with that concept's p_known). A concept-less list in
    the per-session loop_state mixes concepts and resets every session, and with
    LOOP_CHECKS_PER_CONCEPT checks per concept per session it can never hold two
    windows of one concept. The band_control caller builds the concept's window
    from its evidence rows, so LoopState keeps none."""
    from learning.policy import LoopState

    s = LoopState()
    assert not hasattr(s, "first_attempts") and not hasattr(s, "record_first_attempt")
    assert "first_attempts" not in s.to_json()


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


def test_loop_state_steps_keep_the_step_keys_later_packages_add():
    """A later package's per-item fields (spec §9: wrong, check_item_id, node_id,
    feedback_given, taught) survive a round trip under "steps"; the typed keys
    still win over a same-named extra."""
    from learning.policy import LoopState

    doc = LoopState().to_json()
    doc["steps"]["q" * 64] = {
        "rung": 1,
        "attempts": 1,
        "first_shown_at": 1000.0,
        "check_item_id": "ci-1",
        "node_id": "node-1",
        "wrong": 1,
        "taught": True,
    }
    state = LoopState.from_json(doc)
    step = state.steps["q" * 64]
    assert step.genuine_attempts == 1 and step.extra == {
        "check_item_id": "ci-1",
        "node_id": "node-1",
        "wrong": 1,
        "taught": True,
    }
    back = state.to_json()["steps"]["q" * 64]
    assert back["check_item_id"] == "ci-1" and back["taught"] is True and back["rung"] == 1
    step.extra["rung"] = 6  # a stray extra never overrides the typed rung
    assert state.to_json()["steps"]["q" * 64]["rung"] == 1
    assert LoopState.from_json(state.to_json()).steps["q" * 64].extra.get("rung") is None


@pytest.mark.parametrize(
    "bad",
    [
        [],
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
    recovered = LoopState.recover(bad)  # the store's fallback never raises
    assert recovered.steps == {} and LoopState.from_json(recovered.to_json()) == recovered


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


# ── gates (spec §3.3 GATES; §13 A5, A32) ──────────────────────────────────────

IND, IND_N, DWELL = (
    params.GATE_INDEPENDENT_MIN_S,
    params.GATE_INDEPENDENT_MIN_S_NOVICE,
    params.GATE_RUNG_DWELL_MIN_S,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("just tell me", True),
        ("Just TELL me the steps", True),
        ("give me the answer!!", True),
        ("idk", True),
        ("IDK...", True),
        ("I don't know", True),
        ("I don’t know", True),  # typographic apostrophe
        ("i dont know", True),
        ("what's the answer", True),
        ("whats the answer?", True),
        ("I think the derivative is 2x", False),
        ("idkfa", False),
        ("the answer is 7", False),
        ("", False),
    ],
)
def test_matches_non_attempt(text, expected):
    from learning.gates import NON_ATTEMPT_PATTERNS, matches_non_attempt

    assert len(NON_ATTEMPT_PATTERNS) == 5
    assert matches_non_attempt(text) is expected


@pytest.mark.parametrize(
    "text",
    [
        "x = 7. idk if the units are right",
        "I got 12 N, i dont know if thats right",
        "Can you just tell me if step 2 is right? I did F = ma = 6",
        "my answer: 42 (what's the answer supposed to look like?)",
        "The mitochondria? idk",
        "I think it's 7 but idk",
        "idk. I tried dividing both sides by two",
        "Energy is conserved; I don't know why friction matters though",
        "v = 9.8 m/s just tell me if that's right",
        # a hedge with no clause break: the answer shares the idk phrase's clause
        "idk maybe 7",
        "i dont know if its 12 N",
        "idk is it 12N",
        "idk 7?",
        "i think 7 idk",
        "idk if the answer is photosynthesis",
        "i dont know maybe mitochondria",
        "42 idk",
        "I think its 42 idk",
        "the mitochondria idk",
        "idk is it the mitochondria",
        "42 i dont know",
        "i dont know maybe the mitochondria",
        "7? idk",
        "idk... 7",
        "idk, 42",
        "is it 7 just tell me",  # before a request phrase is not its object
        "no, idk",  # "no" answers a yes/no item, so it is graded, never idk
    ],
)
def test_a_hedged_answer_is_not_a_non_attempt(text):
    """Spec §3.3: a genuine attempt is "a submitted answer or shown work, not
    idk/just tell me". A16 routes a matched message away from grading (idk
    evidence or a hint request), so a submitted answer that also carries a
    hedge must not match, whether or not punctuation separates the two: a
    number or a content word outside a request phrase's object, or a relation
    symbol anywhere, is an answer."""
    from learning.gates import matches_non_attempt, non_attempt_phrases

    assert matches_non_attempt(text) is False
    assert non_attempt_phrases(text) == ()


@pytest.mark.parametrize(
    "text,phrases",
    [
        ("Sorry, idk", ("idk",)),
        ("hmm... I don't know", ("i don't know",)),
        ("I'm stuck, just tell me", ("just tell me",)),
        ("ok. What's the answer?", ("what's the answer",)),
        ("idk, just tell me", ("just tell me", "idk")),
        ("Please just tell me how photosynthesis works", ("just tell me",)),
        ("Honestly? I don’t know", ("i don't know",)),
    ],
)
def test_a_non_attempt_may_carry_filler_and_names_its_phrases(text, phrases):
    """A request phrase's object may say anything ("just tell me the steps");
    everything else may only be filler. non_attempt_phrases names every
    pattern found (NON_ATTEMPT_PATTERNS order), so the route can tell idk from
    a hint request (A16) with the same rule."""
    from learning.gates import matches_non_attempt, non_attempt_phrases

    assert matches_non_attempt(text) is True
    assert non_attempt_phrases(text) == phrases


_PLEAS = (
    ("I don't know. Where do I start?", ("i don't know",)),
    ("idk, no idea", ("idk",)),
    ("no idea, just tell me", ("just tell me",)),
    ("give me the answer, I give up", ("give me the answer",)),
    ("What's the answer? I have no clue", ("what's the answer",)),
    ("Can you just tell me? I really don't get it", ("just tell me",)),
    ("Just tell me. This is too hard", ("just tell me",)),
    ("I don't get it, just tell me", ("just tell me",)),
    ("I give up. What's the answer?", ("what's the answer",)),
    ("this is too hard, give me the answer", ("give me the answer",)),
    ("I have no idea what to do, idk", ("idk",)),
    ("I'm tired, just tell me", ("just tell me",)),
    ("no clue, just tell me the answer", ("just tell me",)),
    ("Just tell me. I've spent an hour on this", ("just tell me",)),
    ("i dunno, idk", ("idk",)),
    ("idk, what do I do?", ("idk",)),
    ("I don't know, can you give me a hint?", ("i don't know",)),
    ("idk. where do I start?", ("idk",)),
    ("idk, give me a hint", ("idk",)),
    ("idk! I give up", ("idk",)),
    ("I don't know. Can you show me?", ("i don't know",)),
    ("idk, this is hard", ("idk",)),
    ("idk, no clue", ("idk",)),
    ("what's the answer? I've been trying for ages", ("what's the answer",)),
    ("idk what to do", ("idk",)),
    ("i dont know how to start", ("i don't know",)),
    ("I don't know the answer", ("i don't know",)),
)


@pytest.mark.parametrize("text,phrases", _PLEAS)
def test_a_plea_beside_a_non_attempt_phrase_is_still_a_non_attempt(text, phrases):
    """Spec §3.3: "not idk/just tell me". A clause asking for help, giving up
    or complaining holds no answer, so it never turns a non-attempt into a
    graded submission (A16) — only a number, a content word or a relation
    does."""
    from learning.gates import matches_non_attempt, non_attempt_phrases

    assert matches_non_attempt(text) is True
    assert non_attempt_phrases(text) == phrases


def test_pleas_never_count_toward_hint_unlocking_or_h6():
    """A plea is never a genuine attempt, so two of them in the develop band,
    each past the independent gate, unlock no rung and never reach H6."""
    from learning.gates import h6_allowed, is_genuine_attempt, matches_non_attempt, rung_unlock
    from learning.policy import ceiling

    step = _step(first=0.0)
    now = 0.0
    for text in ("Just tell me. This is too hard", "give me the answer, I give up"):
        now += IND * 10
        if is_genuine_attempt(len(text), False, matches_non_attempt(text), IND * 10, "develop"):
            step.attempted_at.append(now)
            step.genuine_attempts += 1
    assert step.genuine_attempts == 0 and step.attempted_at == []
    assert rung_unlock(step, now) is False
    assert ceiling(_learner("develop"), step) < ceiling(_learner("develop"), _step(fails=2))
    assert h6_allowed(step, item_taught=True, item_practice=True, item_graded=False) is False


def test_non_attempt_patterns_are_exactly_the_spec_list():
    from learning.gates import NON_ATTEMPT_PATTERNS

    assert NON_ATTEMPT_PATTERNS == (
        "just tell me",
        "give me the answer",
        "idk",
        "i don't know",
        "what's the answer",
    )


@pytest.mark.parametrize(
    "chars,work,matched,secs,band,expected",
    [
        (12, False, False, IND, "develop", True),
        (12, False, False, IND - 1, "develop", False),
        (12, False, False, IND, "novice", False),  # novice needs the longer gate
        (12, False, False, IND_N, "novice", True),
        (0, True, False, IND, "profic", True),  # shown work counts without text
        (0, False, False, IND_N, "novice", False),  # nothing submitted
        (40, True, True, IND_N, "novice", False),  # non-attempt phrase wins
    ],
)
def test_is_genuine_attempt(chars, work, matched, secs, band, expected):
    from learning.gates import is_genuine_attempt

    assert is_genuine_attempt(chars, work, matched, secs, band) is expected


def test_rung_unlock_needs_dwell_and_an_attempt_since_last_rung():
    from learning.gates import rung_unlock

    t0 = 1000.0
    assert rung_unlock(_step(first=t0), now=t0 + DWELL) is False  # no attempt yet
    assert rung_unlock(_step(first=t0, attempts=(t0 + 1,)), now=t0 + DWELL - 1) is False  # too soon
    assert rung_unlock(_step(first=t0, attempts=(t0 + 1,)), now=t0 + DWELL) is True
    shown = t0 + 50
    # attempt predates rung
    assert rung_unlock(_step(first=t0, last=shown, attempts=(t0 + 1,)), now=shown + DWELL) is False
    assert (
        rung_unlock(_step(first=t0, last=shown, attempts=(t0 + 1, shown + 2)), now=shown + DWELL)
        is True
    )


def test_gate_seconds_scale_every_gate_constant():
    """§13 A5: every GATE_* seconds constant is scaled by one factor (the E2E
    lane sets 0.01; production never sets it). The factor is passed in: pure
    modules never read config (invariant 2, HANDOFF-01 Known gap (g))."""
    from learning.gates import is_genuine_attempt, rung_unlock

    scale = 0.01
    for name in (
        "GATE_INDEPENDENT_MIN_S",
        "GATE_INDEPENDENT_MIN_S_NOVICE",
        "GATE_RUNG_DWELL_MIN_S",
    ):
        assert params.gate_seconds(name) == float(getattr(params, name))
        assert params.gate_seconds(name, scale) == pytest.approx(getattr(params, name) * scale)
    for bad_name in ("BAND_WINDOW", "LEAK_NGRAM", "gate_seconds", "GATE_NOPE"):
        with pytest.raises(ValueError):
            params.gate_seconds(bad_name)
    for bad_scale in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            params.gate_seconds("GATE_RUNG_DWELL_MIN_S", bad_scale)
    secs = IND_N * scale
    assert is_genuine_attempt(12, False, False, secs, "novice", time_scale=scale) is True
    assert is_genuine_attempt(12, False, False, secs, "novice") is False
    t0 = 1000.0
    fast = _step(first=t0, attempts=(t0 + DWELL * scale / 2,))
    assert rung_unlock(fast, now=t0 + DWELL * scale, time_scale=scale) is True
    assert rung_unlock(fast, now=t0 + DWELL * scale) is False


def test_gates_reject_programmer_errors():
    from learning.gates import is_genuine_attempt

    with pytest.raises(ValueError):
        is_genuine_attempt(12, False, False, IND, "expert")
    with pytest.raises(ValueError):
        is_genuine_attempt(12, False, False, float("nan"), "develop")


def test_h6_allowed_and_offer_allowed():
    from learning.gates import h6_allowed, offer_allowed

    n = params.H6_MIN_GENUINE_ATTEMPTS
    ok = {"item_taught": True, "item_practice": True, "item_graded": False}
    assert h6_allowed(_step(fails=n), **ok) is True
    assert h6_allowed(_step(fails=n - 1), **ok) is False
    assert h6_allowed(_step(fails=n), **{**ok, "item_taught": False}) is False  # not taught
    assert (
        h6_allowed(_step(fails=n), **{**ok, "item_practice": False}) is False
    )  # ungraded but not practice (A32)
    assert h6_allowed(_step(fails=n), **{**ok, "item_graded": True}) is False  # graded coursework
    assert h6_allowed(_step(fails=n, exam=True), **ok) is False
    with pytest.raises(TypeError):
        h6_allowed(
            _step(fails=n), True, True, False
        )  # keyword-only: the three predicates cannot be swapped
    assert offer_allowed("novice", True) is True
    assert offer_allowed("novice", False) is False
    assert offer_allowed("develop", True) is False
    assert offer_allowed("profic", True) is False


def test_policy_never_imports_the_text_gate_but_gates_may_import_policy():
    """Invariant 4's direction: gates reads text and uses policy's types;
    policy never reaches gates."""
    import importlib

    gates = importlib.import_module("learning.gates")
    policy = importlib.import_module("learning.policy")
    assert gates.StepState is policy.StepState
    assert not hasattr(policy, "matches_non_attempt") and not hasattr(policy, "gates")


# ── leak detector (spec §3.4 LEAK_NGRAM; research "Guardrails") ───────────────

REF_POWER = (
    "The derivative of x squared is two x because the power rule brings "
    "the exponent down and reduces it by one"
)
REF_EQ = "x + 3 = 10, so x = 7"
REF_VEL = "The final velocity is 9.8 m/s"
REF_SYM = "F = m a"
# Shorter than LEAK_NGRAM tokens, no '=' and no number: only the whole-reference
# run can catch these (free / mc_reason references may be this short).
REF_SHORT = "The mitochondria."
REF_LAW = "Newton's third law"

LEAKS = [
    (REF_POWER, "Remember: the power rule brings the exponent down, so try that.", "ngram"),
    (REF_POWER, "It reduces it by one and the power rule brings the exponent down.", "ngram"),
    (REF_EQ, "So x must be 7.", "final_answer"),
    (REF_EQ, "Check whether 7 satisfies the equation.", "final_answer"),
    (REF_VEL, "Plug in and you get 9.8 m/s.", "final_answer"),
    (REF_SYM, "Force is just m a, multiply them.", "final_answer"),
    (REF_POWER, "the derivative of x squared is two x", "ngram"),
    (
        REF_SHORT,
        "Cellular respiration happens in the mitochondria, which produce most ATP.",
        "ngram",
    ),
    ("The powerhouse of the cell", "It is the powerhouse of the cell.", "ngram"),
    (REF_LAW, "This is Newton's third law at work.", "ngram"),
]

SAFE = [
    (REF_POWER, "What rule applies when a variable is raised to a power?"),
    (REF_POWER, "Look at the exponent first. What happens to it?"),
    (REF_EQ, "Subtract 3 from both sides, then look at what is left."),
    (REF_EQ, "What operation undoes adding 3?"),
    (REF_VEL, "Which kinematic equation links acceleration and time?"),
    (REF_SYM, "What is force in terms of mass? Think about Newton's second law."),
    (REF_POWER, "The power rule is in section 2.3 of your notes; read the first line."),
    (REF_SHORT, "Which organelle makes most of the cell's ATP?"),
    (REF_LAW, "Which of Newton's laws pairs every force with another?"),
]


@pytest.mark.parametrize("reference,emitted,detector", LEAKS)
def test_detect_leak_catches(reference, emitted, detector):
    from learning.ladder import Rung
    from learning.leak import detect_leak

    v = detect_leak(reference, emitted, Rung.H3)
    assert (v.leaked, v.detector) == (True, detector)


@pytest.mark.parametrize("reference,emitted", SAFE)
def test_detect_leak_zero_false_positives(reference, emitted):
    from learning.ladder import Rung
    from learning.leak import detect_leak, tokens

    assert detect_leak(reference, emitted, Rung.H0) == (False, "none")
    ref, em = tokens(reference), tokens(emitted)
    n = min(params.LEAK_NGRAM, len(ref))
    em_grams = {tuple(em[j : j + n]) for j in range(len(em) - n + 1)}
    assert not any(tuple(ref[i : i + n]) in em_grams for i in range(len(ref) - n + 1))


def test_h6_is_never_a_leak():
    from learning.ladder import Rung
    from learning.leak import detect_leak

    assert detect_leak(REF_EQ, REF_EQ, Rung.H6).leaked is False
    assert detect_leak(REF_EQ, REF_EQ, Rung.H5).leaked is True


def test_final_answer_extraction():
    from learning.leak import final_answer

    assert final_answer(REF_EQ) == ("7",)
    assert final_answer(REF_VEL) == ("9", "8")
    assert final_answer(REF_SYM) == ("m", "a")
    assert final_answer(REF_POWER) == ()
    assert final_answer("y = 2x + 3") == ("2x", "3")


def test_final_answer_clause_ends_at_a_sentence_break():
    """The answer after the last '=' stops at a clause or sentence break, so a
    trailing explanation does not dilute the run; a decimal point is not a break;
    an empty right-hand side falls back to the last standalone number."""
    from learning.leak import final_answer

    assert final_answer("x = 7. Check it by substitution.") == ("7",)
    assert final_answer("v = 9.8 AND nothing else") == ("9", "8")
    assert final_answer("t = 4.5\nThen the ball lands.") == ("4", "5")
    assert final_answer("After 12 steps the value is x =") == ("12",)
    assert final_answer("") == ()


REF_STEPS = (
    "1. Identify the limiting reagent from the mole ratio.\n"
    "2. Use it to compute the theoretical yield."
)


def test_a_short_reference_leaks_when_it_appears_whole():
    """A reference shorter than LEAK_NGRAM tokens has no LEAK_NGRAM-gram, so the
    n-gram rule compares its whole token run instead (PKG-04's leak_in_prompt
    does the same for any length); a partial mention is not a leak."""
    from learning.ladder import Rung, deterministic_content
    from learning.leak import detect_leak, strip_leak

    item = _item(ACTIVE_HASH, reference_answer=REF_SHORT)
    passage = "Cellular respiration happens in the mitochondria, which produce most ATP."
    payload = deterministic_content(Rung.H2, item, [], [passage])
    assert detect_leak(item.reference_answer, payload.text, payload.rung) == (True, "ngram")
    assert strip_leak("It is the mitochondria.", REF_SHORT) == "It is [withheld]."
    assert detect_leak(REF_LAW, "Think about the third law.", Rung.H1) == (False, "none")
    assert detect_leak("Paris", "The capital is Paris.", Rung.H1) == (True, "ngram")
    assert detect_leak("", "anything at all", Rung.H1) == (False, "none")


def test_final_answer_skips_numbered_step_labels():
    """A stepwise reference (A17's H4-eligible items) with no '=' and no number
    of its own has no final answer: its step labels are not answers, or every
    stepwise sibling and every "step 2" in a hint would be a leak."""
    from learning.ladder import Rung
    from learning.leak import detect_leak, final_answer, strip_leak

    assert final_answer(REF_STEPS) == ()
    assert final_answer("1) Convert to moles.\n2) The yield is 42 g") == ("42",)
    assert final_answer("Steps:\n  1. Add 3.\n  2. Divide by 2.") == ("2",)  # "by 2" is no label
    assert final_answer("The answer is\n42.") == ("42",)  # a number alone on a line is no label
    sibling = (
        "Nitrogen reacts with hydrogen...\n\n1. Convert each mass to moles.\n"
        "2. Compare against the balanced equation..."
    )
    assert detect_leak(REF_STEPS, sibling, Rung.H4) == (False, "none")
    hint = "What should step 2 of your plan be?"
    assert detect_leak(REF_STEPS, hint, Rung.H3) == (False, "none")
    assert strip_leak(hint, REF_STEPS) == hint


def test_final_answer_keeps_a_thousands_separator():
    from learning.ladder import Rung
    from learning.leak import detect_leak, final_answer

    assert final_answer("The work done = 1,250 J") == ("1", "250", "j")
    assert final_answer("The work done is 1,250 J") == ("1", "250")
    assert final_answer("x = 3, so the rest follows") == ("3",)  # ", " is still a clause break
    assert detect_leak(
        "The work done = 1,250 J", "Start with step 1: what is the force?", Rung.H1
    ) == (
        False,
        "none",
    )
    assert detect_leak("The work done = 1,250 J", "It comes to 1,250 J.", Rung.H1).leaked is True


@pytest.mark.parametrize("reference,emitted,_", LEAKS)
def test_strip_leak_makes_text_safe_and_is_idempotent(reference, emitted, _):
    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    once = strip_leak(emitted, reference)
    assert "[withheld]" in once
    assert detect_leak(reference, once, Rung.H0).leaked is False
    assert strip_leak(once, reference) == once


@pytest.mark.parametrize("reference,emitted", SAFE)
def test_strip_leak_leaves_safe_text_unchanged(reference, emitted):
    from learning.leak import strip_leak

    assert strip_leak(emitted, reference) == emitted


def test_strip_leak_withholds_only_the_leaked_runs():
    from learning.leak import strip_leak

    assert strip_leak("So x must be 7.", REF_EQ) == "So x must be [withheld]."
    assert (
        strip_leak("Plug in and you get 9.8 m/s.", REF_VEL) == "Plug in and you get [withheld] m/s."
    )
    assert (
        strip_leak("Remember: The Power Rule brings the exponent down, so try that.", REF_POWER)
        == "Remember: [withheld], so try that."
    )


def test_strip_leak_is_safe_and_idempotent_on_shuffled_reference_text():
    """Property check: any text built from the reference's own words, in any
    order, with any separators (unicode, newlines, case), comes out with no
    n-gram or final-answer leak after ONE strip, and a second strip is a no-op."""
    import random

    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    rng = random.Random(606)
    seps = [" ", ", ", "\n", " — ", "; ", " é ", "(", ") ", "/", " = "]
    for reference in (REF_POWER, REF_EQ, REF_VEL, REF_SYM, "y = 2x + 3", REF_SHORT, REF_LAW):
        words = reference.split()
        for _ in range(200):
            picked = [rng.choice(words) for _ in range(rng.randint(1, 30))]
            if rng.random() < 0.5:  # splice in a verbatim stretch of the reference
                start = rng.randrange(len(words))
                picked[rng.randrange(len(picked)) :] = words[start:]
            text = ""
            for w in picked:
                text += (w.upper() if rng.random() < 0.2 else w) + rng.choice(seps)
            once = strip_leak(text, reference)
            assert detect_leak(reference, once, Rung.H0).leaked is False, (reference, text, once)
            assert strip_leak(once, reference) == once


# ── ladder: deterministic turns (spec §13 A17) ────────────────────────────────

ACTIVE_HASH = "a" * 64


def _item(question_hash, **over):
    """Structural stand-in for PKG-04's CheckItem (ladder.ItemLike)."""
    from types import SimpleNamespace

    base = dict(
        question_hash=question_hash,
        concept_key="power_rule",
        format="free",
        difficulty=2,
        prompt="Differentiate x^3.",
        reference_answer="Bring the exponent down: 3x^2",
        stepwise=True,
    )
    return SimpleNamespace(**{**base, **over})


def test_check_pose_is_the_item_prompt_verbatim():
    from learning.ladder import check_pose

    prompt = "Differentiate x^3. Show the first step."
    assert check_pose(prompt) == prompt
    with pytest.raises(ValueError):
        check_pose("   ")


def test_deterministic_h2_joins_at_most_the_source_chunk_cap():
    from learning.ladder import PAYLOAD_JOIN, Rung, deterministic_content

    item = _item(ACTIVE_HASH)
    passages = [f"Passage {i} on the power rule." for i in range(params.LOOP_SOURCE_CHUNKS_MAX + 2)]
    p = deterministic_content(Rung.H2, item, [], ["  "] + passages)
    assert (p.rung, p.source, p.revealed_hash) == (Rung.H2, "passages", None)
    assert p.text == PAYLOAD_JOIN.join(passages[: params.LOOP_SOURCE_CHUNKS_MAX])
    assert deterministic_content(Rung.H2, item, [], []) is None
    assert deterministic_content(Rung.H2, item, [], ["", "  "]) is None


def test_deterministic_h4_takes_the_first_true_isomorph():
    from learning.ladder import PAYLOAD_JOIN, Rung, deterministic_content

    item = _item(ACTIVE_HASH)
    good = _item(
        "b" * 64,
        prompt="Differentiate x^5.",
        reference_answer="1. Bring 5 down. 2. Lower the exponent: 5x^4",
    )
    later = _item("g" * 64, prompt="Differentiate x^7.")
    not_isomorphs = [
        _item(ACTIVE_HASH),  # the active item itself
        _item("c" * 64, concept_key="chain_rule"),  # other concept
        _item("d" * 64, format="teachback"),  # other format
        _item("e" * 64, difficulty=3),  # other difficulty
        _item("f" * 64, stepwise=False),  # not a worked solution
        _item("h" * 64, reference_answer="  "),  # nothing to show
    ]
    p = deterministic_content(Rung.H4, item, [*not_isomorphs, good, later], [])
    assert p == (
        Rung.H4,
        PAYLOAD_JOIN.join((good.prompt, good.reference_answer)),
        "sibling",
        "b" * 64,
    )
    assert deterministic_content(Rung.H4, item, not_isomorphs, ["a passage"]) is None


def test_deterministic_h4_never_shows_an_excluded_sibling():
    """The concept's post-test reserve is a free item at CHECK_ITEM_DIFFICULTIES[1]
    (A23), the develop band's target difficulty, so it can be the first
    isomorph; showing it would reveal the post-test. The caller passes the
    reserve (and any other hash it must not reveal) as exclude_hashes."""
    import inspect

    from learning.ladder import Rung, deterministic_content

    item = _item(ACTIVE_HASH)
    reserve = _item("0" * 64, prompt="Differentiate x^4.")
    other = _item("b" * 64, prompt="Differentiate x^5.")
    assert deterministic_content(Rung.H4, item, [reserve, other], []).revealed_hash == "0" * 64
    p = deterministic_content(Rung.H4, item, [reserve, other], [], exclude_hashes={"0" * 64})
    assert p.revealed_hash == "b" * 64
    both = {"0" * 64, "b" * 64}
    assert deterministic_content(Rung.H4, item, [reserve, other], [], exclude_hashes=both) is None
    param = inspect.signature(deterministic_content).parameters["exclude_hashes"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY and tuple(param.default) == ()


def test_deterministic_h6_is_the_reference_and_other_rungs_have_none():
    from learning.ladder import Rung, deterministic_content

    item = _item(ACTIVE_HASH)
    assert deterministic_content(Rung.H6, item, [], []) == (
        Rung.H6,
        item.reference_answer,
        "reference",
        None,
    )
    assert deterministic_content(Rung.H6, _item(ACTIVE_HASH, reference_answer=""), [], []) is None
    for rung in (Rung.H0, Rung.H1, Rung.H3, Rung.H5):
        assert deterministic_content(rung, item, [_item("b" * 64)], ["a passage"]) is None


def test_deterministic_payloads_are_leak_checked_by_the_caller():
    """Invariant 27's contract: deterministic_content never filters; the caller's
    detect_leak does. A passage quoting the reference leaks at H2; a pointer does not."""
    from learning.ladder import Rung, deterministic_content
    from learning.leak import detect_leak

    item = _item(ACTIVE_HASH, reference_answer=REF_POWER)
    leaking = deterministic_content(Rung.H2, item, [], ["From the notes: " + REF_POWER])
    pointer = deterministic_content(
        Rung.H2, item, [], ["The power rule is in section 2.3 of your notes; read the first line."]
    )
    assert detect_leak(item.reference_answer, leaking.text, leaking.rung).leaked is True
    assert detect_leak(item.reference_answer, pointer.text, pointer.rung).leaked is False


def test_pkg04_check_item_satisfies_item_like():
    """ItemLike mirrors PKG-04's CheckItem field names; a real CheckItem works
    as the item and as a sibling without an adapter (ladder never imports it)."""
    import typing

    from learning.checks import CheckItem
    from learning.ladder import ItemLike, Rung, deterministic_content

    fields = set(typing.get_type_hints(ItemLike)) - {"return"}
    assert fields <= set(CheckItem.model_fields), fields - set(CheckItem.model_fields)

    def real(qh, reference):
        return CheckItem(
            id=f"id-{qh[:4]}",
            course_id="c1",
            concept_key="power_rule",
            format="free",
            difficulty=2,
            prompt=f"Differentiate x^{len(reference)}.",
            reference_answer=reference,
            rubric=[],
            common_wrong=[],
            stepwise=True,
            source_chunk_ids=[],
            question_hash=qh,
        )

    active, sibling = real(ACTIVE_HASH, "3x^2"), real("b" * 64, "1. Bring 5 down. 2. 5x^4")
    p = deterministic_content(Rung.H4, active, [active, sibling], [])
    assert p is not None and p.revealed_hash == "b" * 64
    assert deterministic_content(Rung.H6, active, [], []).text == "3x^2"


# ── sessions.loop_state: migration + store ───────────────────────────────────


def test_migration_adds_loop_state_jsonb_default_empty():
    hits = sorted(MIG_DIR.glob("*_learning_session_loop_state.sql"))
    assert len(hits) == 1, f"expected exactly one loop_state migration, got {hits}"
    sql = hits[0].read_text()
    assert re.fullmatch(r"\d{14}_learning_session_loop_state\.sql", hits[0].name)
    assert re.search(
        r"ALTER TABLE sessions ADD COLUMN IF NOT EXISTS loop_state jsonb NOT NULL DEFAULT '\{\}'::jsonb;",
        sql,
    )
    assert "PKG-06" in sql


def test_migration_sorts_after_the_sessions_table():
    """A replay from empty applies it after 0025 creates `sessions`, and after
    every frozen NNNN_ file (the runner applies basenames in sorted order)."""
    names = sorted(p.name for p in MIG_DIR.glob("*.sql"))
    mine = next(n for n in names if n.endswith("_learning_session_loop_state.sql"))
    frozen = [n for n in names if re.match(r"\d{4}_", n)]
    assert "0025_study_integrity.sql" in frozen
    assert all(n < mine for n in frozen)


def _sessions_table(select_rows=None, update_rows=None):
    mock = MagicMock(name="sessions")
    mock.select.return_value = select_rows if select_rows is not None else []
    mock.update.return_value = update_rows if update_rows is not None else []
    mock.upsert.return_value = [{"id": "s1"}]
    return mock


def test_load_loop_state_reads_by_session_id_and_round_trips(monkeypatch):
    from learning import loop_state_store
    from learning.policy import LoopState

    state = LoopState(current="q" * 64, checks_since_rating=4)
    state.steps[state.current] = _step(fails=1, attempts=(1001.0,))
    t = _sessions_table(select_rows=[{"loop_state": state.to_json()}])
    monkeypatch.setattr(loop_state_store, "table", lambda name: t if name == "sessions" else None)
    assert loop_state_store.load_loop_state("s1") == state
    t.select.assert_called_once_with("loop_state", filters={"id": "eq.s1"}, limit=1)


def test_load_loop_state_missing_row_or_garbage_is_fresh(monkeypatch, caplog):
    from learning import loop_state_store
    from learning.policy import LoopState

    monkeypatch.setattr(loop_state_store, "table", lambda name: _sessions_table(select_rows=[]))
    assert loop_state_store.load_loop_state("s1") == LoopState()
    monkeypatch.setattr(
        loop_state_store,
        "table",
        lambda name: _sessions_table(select_rows=[{"loop_state": {"steps": 5}}]),
    )
    with caplog.at_level(logging.WARNING):
        assert loop_state_store.load_loop_state("s1") == LoopState()
    assert any("loop_state" in r.getMessage() for r in caplog.records)
    for garbage in (None, [], "text", 7):
        monkeypatch.setattr(
            loop_state_store,
            "table",
            lambda name, g=garbage: _sessions_table(select_rows=[{"loop_state": g}]),
        )
        assert loop_state_store.load_loop_state("s1") == LoopState()


def test_a_malformed_pkg06_field_never_erases_other_packages_keys(monkeypatch, caplog):
    """A malformed PKG-06 field starts fresh on its own (a bad step is dropped;
    a bad current / checks_since_rating takes its default), but every key PKG-06
    does not own survives the load, so the next save cannot erase the session
    request counters (§3.5) or this session's A23 "revealed" siblings."""
    from learning import loop_state_store

    stored = {
        "v": 1,
        "current": 7,
        "checks_since_rating": 4,
        "steps": {
            "q": {"first_shown_at": 1.0, "attempts": 1.5, "check_item_id": "ci-1"},
            "r" * 64: {"first_shown_at": 2.0, "rung": 3, "node_id": "node-1"},
        },
        "revealed": ["b" * 64],
        "tutor_requests": 39,
        "deep_requests": 6,
        "plan": {"approved": ["node-1"], "cursor": 0},
    }
    t = _sessions_table(select_rows=[{"loop_state": stored}], update_rows=[{"id": "s1"}])
    monkeypatch.setattr(loop_state_store, "table", lambda name: t)
    with caplog.at_level(logging.WARNING):
        state = loop_state_store.load_loop_state("s1")
    assert any("malformed" in r.getMessage() for r in caplog.records)
    assert state.current is None and state.checks_since_rating == 4
    assert list(state.steps) == ["r" * 64] and int(state.steps["r" * 64].rung) == 3
    assert state.steps["r" * 64].extra == {"node_id": "node-1"}
    assert loop_state_store.save_loop_state("s1", state) is True
    written = t.update.call_args.args[0]["loop_state"]
    assert written["revealed"] == ["b" * 64]
    assert (written["tutor_requests"], written["deep_requests"]) == (39, 6)
    assert written["plan"] == {"approved": ["node-1"], "cursor": 0}
    assert set(written["steps"]) == {"r" * 64} and written["checks_since_rating"] == 4


def test_load_loop_state_propagates_a_read_failure(monkeypatch):
    """A failed read is not an empty state: answering it with a fresh LoopState
    would let the next save overwrite the stored one. The error propagates."""
    from learning import loop_state_store

    t = _sessions_table()
    t.select.side_effect = RuntimeError("postgrest down")
    monkeypatch.setattr(loop_state_store, "table", lambda name: t)
    with pytest.raises(RuntimeError):
        loop_state_store.load_loop_state("s1")


def test_save_loop_state_updates_by_id_and_reports_missing_row(monkeypatch, caplog):
    from learning import loop_state_store
    from learning.policy import LoopState

    state = LoopState(checks_since_rating=1)
    t = _sessions_table(update_rows=[{"id": "s1"}])
    monkeypatch.setattr(loop_state_store, "table", lambda name: t)
    assert loop_state_store.save_loop_state("s1", state) is True
    t.update.assert_called_once_with({"loop_state": state.to_json()}, filters={"id": "eq.s1"})
    t.upsert.assert_not_called()

    lazy = _sessions_table(update_rows=[])
    monkeypatch.setattr(loop_state_store, "table", lambda name: lazy)
    with caplog.at_level(logging.WARNING):
        assert loop_state_store.save_loop_state("s1", state) is False
    assert any("not materialised" in r.getMessage() for r in caplog.records)


def test_save_loop_state_never_inserts_or_upserts_sessions(monkeypatch):
    """Spec §9 / §13 A11: never `upsert` on `sessions`. A missing row is reported,
    never created here (PKG-07 materialises through _consume_pending; PKG-09 owns
    the insert-if-missing helper)."""
    import inspect

    from learning import loop_state_store
    from learning.policy import LoopState

    assert list(inspect.signature(loop_state_store.save_loop_state).parameters) == [
        "session_id",
        "state",
    ]
    t = _sessions_table(update_rows=[])
    monkeypatch.setattr(loop_state_store, "table", lambda name: t)
    assert loop_state_store.save_loop_state("s1", LoopState()) is False
    t.upsert.assert_not_called()
    t.insert.assert_not_called()
    src = inspect.getsource(loop_state_store)
    assert ".upsert(" not in src and ".insert(" not in src


def test_load_save_round_trip_keeps_later_packages_keys(monkeypatch):
    """What PKG-07+ store beside the PKG-06 keys survives load -> save."""
    from learning import loop_state_store

    stored = {"v": 1, "steps": {}, "revealed": ["b" * 64], "active": "a" * 64}
    t = _sessions_table(select_rows=[{"loop_state": stored}], update_rows=[{"id": "s1"}])
    monkeypatch.setattr(loop_state_store, "table", lambda name: t)
    state = loop_state_store.load_loop_state("s1")
    state.checks_since_rating += 1
    assert loop_state_store.save_loop_state("s1", state) is True
    written = t.update.call_args.args[0]["loop_state"]
    assert written["revealed"] == ["b" * 64] and written["active"] == "a" * 64
    assert written["checks_since_rating"] == 1


# ── zpd.* events (spec §6) ────────────────────────────────────────────────────

PAYLOAD_STR_MAX = 64  # a sha256 question_hash is exactly this long; nothing longer is an id


def _recorder(monkeypatch):
    from learning import zpd_events

    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(zpd_events, "log_event", lambda et, **kw: calls.append((et, kw)))
    return calls


def _assert_ids_only(value):
    if isinstance(value, str):
        assert len(value) <= PAYLOAD_STR_MAX, f"payload string too long: {value[:20]}…"
    elif isinstance(value, dict):
        for v in value.values():
            _assert_ids_only(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _assert_ids_only(v)
    else:
        assert value is None or isinstance(value, (bool, int, float)), type(value)


def test_zpd_events_in_taxonomy_with_spec_categories():
    from services.events_service import EVENT_TAXONOMY

    for et in (
        "zpd.step",
        "zpd.offer",
        "zpd.band_adjust",
        "zpd.wheelspin",
        "zpd.leak",
        "zpd.rating",
    ):
        assert et in EVENT_TAXONOMY


def test_emit_helpers_send_spec_payloads(monkeypatch):
    from learning import zpd_events
    from learning.ladder import Rung
    from learning.policy import BandAction, CeilingReason

    calls = _recorder(monkeypatch)
    common = dict(user_id="user_andres", request_id="req-1")
    zpd_events.emit_zpd_step(
        **common,
        concept_id="node-1",
        question_hash="q" * 64,
        phase="check",
        channel="free_response",
        band="develop",
        ceiling=Rung.H3,
        ceiling_reason=CeilingReason.DEVELOP,
        first_attempt_correct=False,
        n_attempts=2,
        max_rung_used=Rung.H2,
        rungs=[{"rung": 1, "dwell_ms": 9000}, {"rung": 2, "dwell_ms": 12000}],
        time_to_first_attempt_ms=61000,
        time_to_correct_ms=140000,
        independent_time_ms=61000,
        assisted=True,
        confidence=0.8,
        fsrs_rating=params.FSRS_RATING_HARD,
        p_known_before=0.41,
        p_known_after=0.52,
        r_before=0.93,
        item_difficulty=2,
        tier="standard",
        grader_backend="gemini",
    )
    zpd_events.emit_zpd_offer(**common, accepted=True, band="novice")
    zpd_events.emit_zpd_band_adjust(
        **common, direction=BandAction.HARDER, trigger="high", window_stats={"n": 8, "rate": 1.0}
    )
    zpd_events.emit_zpd_wheelspin(
        **common,
        concept_id="node-1",
        opps=11,
        unassisted_next=0.3,
        htc_k=2.5,
        prerequisite_ids=["node-0"],
    )
    zpd_events.emit_zpd_leak(**common, rung_emitted=Rung.H6, ceiling=Rung.H3, detector="ngram")
    zpd_events.emit_zpd_rating(
        **common, rating="too_hard", checks_since_last=params.ZPD_RATING_EVERY_N_CHECKS
    )

    got = {et: kw for et, kw in calls}
    assert set(got) == {
        "zpd.step",
        "zpd.offer",
        "zpd.band_adjust",
        "zpd.wheelspin",
        "zpd.leak",
        "zpd.rating",
    }
    assert {et: kw["category"] for et, kw in calls} == {
        "zpd.step": "usage",
        "zpd.offer": "usage",
        "zpd.band_adjust": "usage",
        "zpd.wheelspin": "error",
        "zpd.leak": "error",
        "zpd.rating": "usage",
    }
    assert set(got["zpd.step"]["payload"]) == {
        "concept_id",
        "question_hash",
        "phase",
        "channel",
        "band",
        "ceiling",
        "ceiling_reason",
        "first_attempt_correct",
        "n_attempts",
        "max_rung_used",
        "rungs",
        "time_to_first_attempt_ms",
        "time_to_correct_ms",
        "independent_time_ms",
        "assisted",
        "confidence",
        "fsrs_rating",
        "p_known_before",
        "p_known_after",
        "r_before",
        "item_difficulty",
        "tier",
        "grader_backend",
    }
    assert got["zpd.step"]["payload"]["ceiling"] == int(Rung.H3)
    assert got["zpd.step"]["payload"]["ceiling_reason"] == "develop"
    assert (got["zpd.step"]["payload"]["tier"], got["zpd.step"]["payload"]["grader_backend"]) == (
        "standard",
        "gemini",
    )
    assert set(got["zpd.offer"]["payload"]) == {"accepted", "band"}
    assert set(got["zpd.band_adjust"]["payload"]) == {"direction", "trigger", "window_stats"}
    assert got["zpd.band_adjust"]["payload"]["direction"] == "harder"
    assert set(got["zpd.wheelspin"]["payload"]) == {
        "concept_id",
        "opps",
        "unassisted_next",
        "htc_k",
        "prerequisite_ids",
    }
    assert set(got["zpd.leak"]["payload"]) == {"rung_emitted", "ceiling", "detector", "request_id"}
    assert set(got["zpd.rating"]["payload"]) == {"rating", "checks_since_last"}
    for et, kw in calls:
        assert kw["user_id"] == "user_andres" and kw["request_id"] == "req-1"
        _assert_ids_only(kw["payload"])
    # enums and rungs reach the payload as plain JSON values
    assert type(got["zpd.step"]["payload"]["max_rung_used"]) is int
    assert type(got["zpd.leak"]["payload"]["rung_emitted"]) is int
    assert type(got["zpd.step"]["payload"]["ceiling_reason"]) is str


def test_zpd_step_omits_tier_and_grader_backend_when_unset(monkeypatch):
    """A15/A24 keys are omitted when None — never zeroed or blanked."""
    from learning import zpd_events
    from learning.ladder import Rung
    from learning.policy import CeilingReason

    calls = _recorder(monkeypatch)
    zpd_events.emit_zpd_step(
        user_id="u",
        request_id=None,
        concept_id="node-1",
        question_hash="q" * 64,
        phase="probe",
        channel="free_response",
        band="novice",
        ceiling=Rung.H4,
        ceiling_reason=CeilingReason.NOVICE_WORKED_FIRST,
        first_attempt_correct=True,
        n_attempts=1,
        max_rung_used=Rung.H0,
        rungs=[],
        time_to_first_attempt_ms=None,
        time_to_correct_ms=None,
        independent_time_ms=None,
        assisted=False,
        confidence=None,
        fsrs_rating=params.FSRS_RATING_GOOD,
        p_known_before=0.2,
        p_known_after=0.3,
        r_before=None,
        item_difficulty=1,
    )
    [(event_type, kw)] = calls
    assert event_type == "zpd.step"
    assert "tier" not in kw["payload"] and "grader_backend" not in kw["payload"]


def test_emit_helpers_are_keyword_only():
    import inspect

    from learning import zpd_events

    for name in (
        "emit_zpd_step",
        "emit_zpd_offer",
        "emit_zpd_band_adjust",
        "emit_zpd_wheelspin",
        "emit_zpd_leak",
        "emit_zpd_rating",
    ):
        params_ = inspect.signature(getattr(zpd_events, name)).parameters.values()
        assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params_), name


def test_emit_helper_drops_a_malformed_event_instead_of_raising(monkeypatch, caplog):
    """Event capture never raises into a request (events_service contract): a
    caller bug in the rungs list drops the event with a log line."""
    from learning import zpd_events
    from learning.ladder import Rung
    from learning.policy import CeilingReason

    calls = _recorder(monkeypatch)
    with caplog.at_level(logging.WARNING):
        zpd_events.emit_zpd_step(
            user_id="u",
            request_id="r",
            concept_id="node-1",
            question_hash="q" * 64,
            phase="check",
            channel="mc",
            band="develop",
            ceiling=Rung.H3,
            ceiling_reason=CeilingReason.DEVELOP,
            first_attempt_correct=False,
            n_attempts=1,
            max_rung_used=Rung.H1,
            rungs=[{"rung": 1}],  # no dwell_ms
            time_to_first_attempt_ms=None,
            time_to_correct_ms=None,
            independent_time_ms=None,
            assisted=True,
            confidence=None,
            fsrs_rating=params.FSRS_RATING_HARD,
            p_known_before=0.5,
            p_known_after=0.55,
            r_before=None,
            item_difficulty=2,
        )
    assert calls == []
    assert any("zpd.step" in r.getMessage() for r in caplog.records)


def test_emit_helpers_drop_a_payload_that_could_carry_text(monkeypatch, caplog):
    """The ids/counts/enums/bools rule holds at runtime, not only for the test's
    own fixtures: a payload string longer than PAYLOAD_STR_MAX (student or tutor
    text; events.payload is plaintext) or a value that is not JSON-plain drops
    the event with a WARNING. A 64-char id still passes."""
    from learning import zpd_events
    from learning.policy import BandAction

    assert params.EVENT_PAYLOAD_STR_MAX == PAYLOAD_STR_MAX
    assert not hasattr(zpd_events, "PAYLOAD_STR_MAX")  # one value, one name (params)
    calls = _recorder(monkeypatch)
    wheel = dict(user_id="u", request_id="r", opps=6, unassisted_next=0.2, htc_k=None)
    band = dict(user_id="u", request_id="r", direction=BandAction.HOLD, trigger="high")
    with caplog.at_level(logging.WARNING):
        zpd_events.emit_zpd_band_adjust(**band, window_stats={"note": "I think " + "x" * 80})
        zpd_events.emit_zpd_band_adjust(**band, window_stats={"obj": object()})
        zpd_events.emit_zpd_wheelspin(**wheel, concept_id="n" * 65, prerequisite_ids=[])
        zpd_events.emit_zpd_wheelspin(**wheel, concept_id="n", prerequisite_ids=["p" * 65])
    assert calls == []
    assert sum("event dropped" in r.getMessage() for r in caplog.records) == 4
    zpd_events.emit_zpd_wheelspin(**wheel, concept_id="n" * 64, prerequisite_ids=["p" * 64])
    zpd_events.emit_zpd_band_adjust(**band, window_stats={"rate": 0.95, "n": 8, "full": True})
    assert [et for et, _ in calls] == ["zpd.wheelspin", "zpd.band_adjust"]


def test_zpd_leak_keeps_a_long_request_id(monkeypatch, caplog):
    """request_context accepts a caller's X-Request-ID of up to 128 chars, and
    zpd.leak carries request_id in its payload (spec §6). The same value is the
    events row's request_id column, so the length cap never drops the leak
    signal for it; any other long string still drops the event."""
    from learning import zpd_events
    from learning.ladder import Rung
    from services.request_context import _SAFE_ID

    rid = "a" * 100
    assert _SAFE_ID.match(rid)
    calls = _recorder(monkeypatch)
    with caplog.at_level(logging.WARNING):
        zpd_events.emit_zpd_leak(
            user_id="u", request_id=rid, rung_emitted=Rung.H3, ceiling=Rung.H3, detector="ngram"
        )
    [(event_type, kw)] = calls
    assert event_type == "zpd.leak"
    assert kw["request_id"] == rid and kw["payload"]["request_id"] == rid
    assert not any("event dropped" in r.getMessage() for r in caplog.records)
    zpd_events.emit_zpd_wheelspin(
        user_id="u",
        request_id=rid,
        concept_id="n" * 65,
        opps=6,
        unassisted_next=None,
        htc_k=None,
        prerequisite_ids=[],
    )
    assert len(calls) == 1


def test_emit_helpers_reach_log_event_without_raising(monkeypatch):
    """Through the real events_service: enqueue only, worker never runs here."""
    from learning import zpd_events
    from services import events_service

    rows: list = []
    monkeypatch.setattr(
        events_service,
        "table",
        lambda name: MagicMock(insert=lambda r: rows.append((name, r)) or r),
    )
    zpd_events.emit_zpd_offer(user_id="u", request_id="r", accepted=False, band="novice")
    events_service.flush_now()
    assert any(row["event_type"] == "zpd.offer" for _, batch in rows for row in batch)


_PKG06_MODULES = ("policy", "gates", "leak", "ladder", "loop_state_store", "zpd_events")


def _pkg06_imports(source: str) -> list[str]:
    """Every PKG-06 module `source` imports, in any form: `import learning.x`,
    `from learning.x import y`, `from learning import x`, at any depth."""
    import ast

    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        else:
            continue
        found += [n for n in names if n.split(".")[:2] in (["learning", m] for m in _PKG06_MODULES)]
    return found


def test_pkg06_import_detector():
    assert _pkg06_imports("import learning.policy") == ["learning.policy"]
    assert _pkg06_imports("from learning import gates, bkt") == ["learning.gates"]
    assert _pkg06_imports("def f():\n    from learning.leak import detect_leak") == [
        "learning.leak",
        "learning.leak.detect_leak",
    ]
    assert _pkg06_imports("import learning.bkt\nfrom learning import params") == []


def test_zpd_layer_is_inert_nothing_imports_it():
    offenders = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).parts
        if rel[0] in ("tests", "learning", "venv", ".venv"):
            continue
        if _pkg06_imports(path.read_text(errors="ignore")):
            offenders.append(str(path.relative_to(BACKEND)))
    assert offenders == [], f"PKG-06 modules must stay unreferenced until PKG-07: {offenders}"


def test_importing_the_app_loads_no_pkg06_module():
    """The ast scan above skips learning/, so a PKG-06 module pulled into the app
    through a learning module the app already loads (evidence, checks, gate, …)
    would pass it. Import the real app in a clean interpreter and read
    sys.modules: flag-off byte-identity needs no PKG-06 module loaded at all."""
    import os
    import subprocess
    import sys

    env = {
        k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "LEARNING_LOOP_ENABLED")
    }
    env.update(
        {
            "ENCRYPTION_KEY": "0" * 64,
            "APP_ENV": "test",
            "SUPABASE_URL": "https://dummy.supabase.co",
            "SUPABASE_SERVICE_KEY": "dummy-service-key",
            "SESSION_SECRET": "dummy-session-secret",
        }
    )
    wanted = tuple(f"learning.{m}" for m in _PKG06_MODULES)
    program = (
        "import dotenv; dotenv.load_dotenv = lambda *a, **k: False\n"
        "import sys\n"
        "import main\n"
        f"loaded = [m for m in {wanted!r} if m in sys.modules]\n"
        "print('LEARNING_LOADED=' + ','.join(sorted(m for m in sys.modules if m.startswith('learning.'))))\n"
        "print('PKG06_LOADED=' + ','.join(loaded))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", program],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, "importing main failed:\n" + proc.stderr
    lines = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "_LOADED=" in line)
    assert "learning.gate" in lines["LEARNING_LOADED"].split(","), lines  # not vacuous
    assert lines["PKG06_LOADED"] == "", f"the app imports PKG-06 modules: {lines['PKG06_LOADED']}"
