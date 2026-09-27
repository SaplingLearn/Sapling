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
    assert LoopState.from_json(recovered.to_json()) == recovered
    for qh, step in recovered.steps.items():  # a malformed step restarts fresh
        assert (step.rung, step.genuine_attempts, step.attempted_at) == (0, 0, [])
        assert (step.last_rung_at, step.showed_work) == (None, False)
        # the exam flag fails closed: a malformed one ("false") is exam mode
        assert step.exam_mode is ("exam_mode" in bad["steps"][qh])


def test_recover_keeps_the_exam_cap_of_a_malformed_step():
    """A malformed step restarts fresh, but exam mode is the strictest ceiling
    row (H1, and h6_allowed never admits H6): a stored `exam_mode: true` is
    kept and a non-bool one is exam mode, so recovery never loosens the cap."""
    from learning.gates import h6_allowed
    from learning.ladder import Rung
    from learning.policy import CeilingReason, LoopState, ceiling_with_reason

    qh = "q" * 64
    for flag in (True, "false", 1, None):
        raw = {
            "rung": 9,
            "attempts": 3,
            "first_shown_at": 100.0,
            "exam_mode": flag,
            "check_item_id": "x",
        }
        step = LoopState.recover({"steps": {qh: raw}}).steps[qh]
        assert step.exam_mode is True, flag
        assert step.extra == {"check_item_id": "x"}
        step.genuine_attempts = 2
        assert ceiling_with_reason(_learner("develop"), step) == (Rung.H1, CeilingReason.EXAM)
        assert h6_allowed(step, item_taught=True, item_practice=True, item_graded=False) is False
    for raw in (
        {"rung": 9, "first_shown_at": 1.0},
        {"rung": 9, "first_shown_at": 1.0, "exam_mode": False},
    ):
        assert LoopState.recover({"steps": {qh: raw}}).steps[qh].exam_mode is False


def test_recover_keeps_a_malformed_steps_foreign_keys():
    """A step that fails validation restarts fresh (PKG-06 fields at their
    defaults, a finite first_shown_at kept) but keeps every key a later package
    stored on it (A27: check_item_id, taught, …), so the next save erases none
    of them. A non-object step is dropped, and `current` naming it is cleared."""
    from learning.ladder import Rung
    from learning.policy import LoopState

    doc = {
        "steps": {
            "qa": {"first_shown_at": "bad", "rung": 3, "check_item_id": "ci-1", "taught": True},
            "qb": {"first_shown_at": 5.0, "rung": 9, "node_id": "n-1"},
            "qc": {"first_shown_at": 1.0, "taught": True},
            "qd": "garbage",
        },
        "current": "qa",
        "revealed": ["x"],
    }
    state = LoopState.recover(doc)
    out = state.to_json()
    assert set(out["steps"]) == {"qa", "qb", "qc"}
    assert out["steps"]["qa"]["check_item_id"] == "ci-1" and out["steps"]["qa"]["taught"] is True
    assert state.steps["qa"].rung is Rung.H0 and state.steps["qa"].first_shown_at == 0.0
    assert out["steps"]["qb"]["node_id"] == "n-1" and state.steps["qb"].first_shown_at == 5.0
    assert state.steps["qb"].rung is Rung.H0
    assert out["steps"]["qc"]["taught"] is True
    assert state.current == "qa" and out["revealed"] == ["x"]
    assert LoopState.from_json(out) == state  # the recovered document is valid
    assert LoopState.recover({"steps": {"qd": "garbage"}, "current": "qd"}).current is None
    assert LoopState.recover({"steps": ["qa"], "current": "qa"}).current is None
    assert LoopState.recover({"steps": {}, "current": "qz"}).current == "qz"


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
        # coordinator decision (B): answer-capable words are answers
        "even, idk",
        "on, idk",
        "in? idk",
        "hours? idk",
        "at the start? idk",
        "I think it's even, idk",
        "x = 7 idk",
        "just tell me, is it 7?",  # a digit makes a request-phrase message graded
        "what's the answer to part 2, is it 7?",  # a label aside, a digit is an answer
        "just tell me if it's 7",
        "question 3 is 7, just tell me",
        "just tell me the answer to question 3 and 4",  # "4" labels nothing
        "idk how to do part 2",  # labels are set aside only beside a request phrase
        # a relation between operands is an answer, digit or not
        "F = ma, idk",
        "a > b? idk",
        "x ≠ y, i don't know",
        "just tell me if F = ma",
        "(a+b) = c idk",
    ],
)
def test_a_hedged_answer_is_not_a_non_attempt(text):
    """Spec §3.3: a genuine attempt is "a submitted answer or shown work, not
    idk/just tell me". A16 routes a matched message away from grading (idk
    evidence or a hint request), so a submitted answer that also carries a
    hedge must not match, whether or not punctuation separates the two
    (coordinator decision (B): fail toward grading). Any digit, or a relation
    symbol between operands, is an answer anywhere; beside an idk phrase, any
    word outside the filler set is one."""
    from learning.gates import matches_non_attempt, non_attempt_phrases

    assert matches_non_attempt(text) is False
    assert non_attempt_phrases(text) == ()


# Words that can answer an item on their own. None is filler: beside an idk
# phrase each is an answer and the message is graded (decision (B)).
_ANSWER_CAPABLE = (
    "even", "on", "in", "some", "any", "much", "still", "then", "when", "hour",
    "hours", "minute", "minutes", "start", "started", "begin", "up", "yes", "no",
    "true", "false", "hard", "right", "both", "none", "one", "bit", "lot", "lost",
    "solution", "id", "us", "impossible", "forever",
)  # fmt: skip


@pytest.mark.parametrize("word", _ANSWER_CAPABLE)
def test_an_answer_capable_word_beside_an_idk_phrase_is_graded(word):
    from learning.gates import non_attempt_phrases

    for text in (f"{word}, idk", f"idk {word}", f"{word}? I don't know", f"the {word} idk"):
        assert non_attempt_phrases(text) == (), text


# Function words that can answer an item alone: a yes/no-equivalent auxiliary
# or modal ("it isn't", "it does", "cannot"), a connective ("or", "not"), the
# imaginary unit "i", an article or a lettered option ("a", "an"). They are
# filler beside a word asking for help, but a clause holding nothing else (a
# subject or a hedge aside) is an answer, so it is graded (decision (B)).
_BARE_ANSWER_WORDS = tuple(
    """
    a an and or not if i is isnt are arent was wasnt were werent do does doesnt
    did didnt dont can cant cannot could couldnt will wont would wouldnt should
    shouldnt have has had havent hasnt might
    """.split()
)


@pytest.mark.parametrize("word", _BARE_ANSWER_WORDS)
def test_a_bare_function_word_answer_beside_an_idk_phrase_is_graded(word):
    from learning.gates import non_attempt_phrases

    for text in (
        f"{word}, idk",
        f"{word}? I don't know",
        f"it {word}, idk",
        f"idk, it {word}",
        f"I think it {word}, idk",
        f"maybe {word}? idk",
        f"idk, {word}. what do I do?",  # a plea in another clause does not hide it
    ):
        assert non_attempt_phrases(text) == (), text


@pytest.mark.parametrize(
    "text",
    ["it isn't, idk", "It is, idk", "cannot, idk", "or? idk", "not? idk", "i, idk", "an, idk",
     "A? idk", "idk, it should", "I think it is, idk", "it isn't, idk, what do I do?",
     "idk if it is"],
)  # fmt: skip
def test_a_hedged_yes_no_or_connective_answer_is_graded_but_no_attempt(text):
    """For "Is |x| differentiable at 0?", "it isn't, idk" answers the item as
    surely as "no, idk": it is graded (B), never idk evidence with the answer
    released, and it still never counts toward hint unlocking (A)."""
    from learning.gates import has_non_attempt_phrase, non_attempt_phrases

    assert non_attempt_phrases(text) == ()
    assert has_non_attempt_phrase(text) is True


@pytest.mark.parametrize(
    "text",
    ["not really, idk", "it can't be, idk", "it's not really, idk", "it just does, idk",
     "it actually is idk", "it doesnt really, idk", "it will be idk", "idk it has to",
     "idk it does though", "it isnt lol, idk", "it does tho, idk", "it isnt man, idk",
     "it is honestly, idk", "nah it isnt, idk", "it kinda is, idk", "idk it isnt im not sure",
     "idk it is im so lost", "it isnt i am so confused, idk", "it's i, idk",
     "I think so, idk", "i guess so idk", "idk, I think not"],
)  # fmt: skip
def test_a_bare_answer_with_chat_filler_or_a_later_plea_is_graded(text):
    """A hedged yes/no answer is still an answer when an intensifier or chat
    slang sits beside it ("not really", "it isnt lol"), and when a
    first-person plea follows it in the same clause ("it isnt im not sure"):
    graded (B), never idk evidence with the answer released; still no
    genuine attempt (A)."""
    from learning.gates import has_non_attempt_phrase, non_attempt_phrases

    assert non_attempt_phrases(text) == ()
    assert has_non_attempt_phrase(text) is True


@pytest.mark.parametrize(
    "text",
    ["idk, can I get a hint", "I don't know, can you give me a hint?", "idk what to do",
     "idk, I have no idea", "idk, can we move on?", "idk, what does that mean?",
     "I can't do this, idk", "idk, I can't do it", "idk, I really don't know", "idk it",
     "hmm... I don't know", "idk, is there a hint?", "idk, I don't remember", "i dunno, idk",
     "idk! I give up", "idk im not sure", "idk, I'm so lost", "idk lol", "idk tho",
     "idk, i guess im stuck", "idk, I think I'm lost", "idk, I just don't know",
     "idk, I really can't do this", "idk, honestly I'm lost", "idk, I think"],
)  # fmt: skip
def test_function_words_beside_a_help_word_stay_an_idk_plea(text):
    from learning.gates import non_attempt_phrases

    assert "idk" in non_attempt_phrases(text) or "i don't know" in non_attempt_phrases(text)


@pytest.mark.parametrize(
    "text,phrases",
    [
        ("idk", ("idk",)),
        ("I don't know", ("i don't know",)),
        ("idk lmao", ("idk",)),
        ("idk =(", ("idk",)),  # an emoticon is not a relation
        ("idk >.<", ("idk",)),
        ("idk =)", ("idk",)),
        ("idk >_<", ("idk",)),
        ("idk :-(", ("idk",)),
        ("idk xD", ("idk",)),
        ("idk man", ("idk",)),
        ("nah idk", ("idk",)),
        ("idk bruh", ("idk",)),
        ("idk haha ngl", ("idk",)),
        ("sry idk tho", ("idk",)),
        ("idk, give me another hint", ("idk",)),
        ("idk, show me an example", ("idk",)),
        ("idk skip", ("idk",)),
        ("idk, next question", ("idk",)),
        ("idk, i forgot", ("idk",)),
        ("idk, I don't remember", ("idk",)),
        ("idk what that means", ("idk",)),
        ("I dont know how to do this problem", ("i don't know",)),
        ("I missed the lecture, idk", ("idk",)),
        # answer-capable words inside a recognised plea n-gram stay a plea
        ("idk, where do I even start?", ("idk",)),
        ("i don't know how to begin", ("i don't know",)),
        ("idk how to get started", ("idk",)),
        ("idk, I've been at this for hours", ("idk",)),
        ("idk, I spent an hour on this", ("idk",)),
        ("idk, this is too much", ("idk",)),
        ("idk, I'm lost", ("idk",)),
        ("idk, I'm a bit confused", ("idk",)),
        ("idk, this is impossible", ("idk",)),
        ("idk, it's taking forever", ("idk",)),
        ("idk, I really don't know", ("idk",)),
        # a request phrase: no digit and no relation → never graded
        ("just tell me", ("just tell me",)),
        ("man just tell me", ("just tell me",)),
        ("just tell me the steps", ("just tell me",)),
        ("just tell me =/", ("just tell me",)),
        ("just tell me >:(", ("just tell me",)),
        ("just tell me, I hate this", ("just tell me",)),
        ("bruh just tell me", ("just tell me",)),
        ("just tell me, is it the mitochondria?", ("just tell me",)),
        # idk beside a request: idk only when its residue is empty
        ("idk, just tell me", ("just tell me", "idk")),
        ("idk the mitochondria, just tell me", ("just tell me",)),
    ],
)
def test_the_a16_route_split_idk_request_or_graded(text, phrases):
    """Decision (B): an idk phrase routes to idk evidence only when nothing
    but phrases, a request's object, pleas and filler remain; a request phrase
    routes to no evidence unless a digit or an operand relation appears."""
    from learning.gates import matches_non_attempt, non_attempt_phrases

    assert non_attempt_phrases(text) == phrases
    assert matches_non_attempt(text) is True


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


def _two_attempts(texts):
    """Feed `texts` as develop-band attempts, each past the independent gate,
    through the route's contract: matched_non_attempt = has_non_attempt_phrase."""
    from learning.gates import has_non_attempt_phrase, is_genuine_attempt

    step = _step(first=0.0)
    now = 0.0
    for text in texts:
        now += IND * 10
        if is_genuine_attempt(len(text), False, has_non_attempt_phrase(text), IND * 10, "develop"):
            step.attempted_at.append(now)
            step.genuine_attempts += 1
    return step, now


def test_pleas_never_count_toward_hint_unlocking_or_h6():
    """A plea is never a genuine attempt, so two of them in the develop band,
    each past the independent gate, unlock no rung and never reach H6."""
    from learning.gates import h6_allowed, rung_unlock
    from learning.policy import ceiling

    step, now = _two_attempts(("Just tell me. This is too hard", "give me the answer, I give up"))
    assert step.genuine_attempts == 0 and step.attempted_at == []
    assert rung_unlock(step, now) is False
    assert ceiling(_learner("develop"), step) < ceiling(_learner("develop"), _step(fails=2))
    assert h6_allowed(step, item_taught=True, item_practice=True, item_graded=False) is False


# Review round 2's 49 probe pleas plus the coordinator's (A) list: every one
# holds a non-attempt phrase, so none may unlock a rung or count toward H6.
_PROBE_PLEAS = (
    "bro just tell me", "bruh just tell me", "idk man", "nah idk", "idk bruh", "idk lmao",
    "idk haha", "idk ngl", "idk what that means", "i don't know what the question is asking",
    "idk how to do this problem", "idk how to approach this", "idk this makes no sense",
    "idk what you mean", "idk, what does that mean?", "i don't know how to do this one",
    "idk im bad at this", "idk im dumb", "just tell me, I hate this",
    "idk, can you explain it differently?", "idk where to even begin", "idk what to write",
    "idk what formula to use", "i don't know which equation to use", "idk what this is",
    "i don't know, help", "idk please help me", "idk, I'm confused", "i don't know!!! ugh",
    "idk, i forgot", "idk i never learned this", "idk we didnt cover this",
    "i don't know, i wasn't in class", "just tell me already", "just tell me pls",
    "can you just tell me the answer", "give me the answer now", "whats the answer lol",
    "idk sorry", "I don't know, sorry", "idk, next question", "idk skip",
    "idk, can we move on?", "idk, give me another hint", "idk, can I get a hint",
    "idk, show me an example", "idk, walk me through it", "i don't know, explain please",
    "idk what im doing",
    # the coordinator's list beyond the probe
    "idk xD", "idk =(", "idk >.<", "just tell me =/", "I dont know how to do this problem",
)  # fmt: skip


def test_the_probe_plea_list_is_complete():
    assert len(_PROBE_PLEAS) == 49 + 5 and len(set(_PROBE_PLEAS)) == len(_PROBE_PLEAS)


@pytest.mark.parametrize("text", _PROBE_PLEAS)
def test_every_probe_plea_holds_a_non_attempt_phrase(text):
    """Decision (A), fail closed: a NON_ATTEMPT_PATTERNS phrase anywhere (or a
    _PLEA plea) makes the message no genuine attempt, whatever else it says."""
    from learning.gates import has_non_attempt_phrase

    assert has_non_attempt_phrase(text) is True


@pytest.mark.parametrize(
    "first,second", list(zip(_PROBE_PLEAS, _PROBE_PLEAS[1:] + _PROBE_PLEAS[:1]))
)
def test_two_probe_pleas_unlock_no_rung_and_never_reach_h6(first, second):
    from learning.gates import h6_allowed, rung_unlock

    step, now = _two_attempts((first, second))
    assert step.genuine_attempts == 0 and step.attempted_at == []
    assert rung_unlock(step, now) is False
    assert h6_allowed(step, item_taught=True, item_practice=True, item_graded=False) is False


# Decision (B)'s accepted residual: a probe plea whose residue holds a word
# that can answer an item alone ("one", "bad", "formula", "equation",
# "never", "in") is graded, never idk. It still unlocks nothing (A).
_PROBE_PLEAS_GRADED = (
    "i don't know how to do this one",
    "idk im bad at this",
    "idk what formula to use",
    "i don't know which equation to use",
    "idk i never learned this",
    "i don't know, i wasn't in class",
)


def test_probe_pleas_route_to_idk_or_a_request_except_the_residual():
    from learning.gates import non_attempt_phrases

    graded = tuple(t for t in _PROBE_PLEAS if non_attempt_phrases(t) == ())
    assert graded == _PROBE_PLEAS_GRADED


@pytest.mark.parametrize(
    "text",
    ["idk maybe 7", "even, idk", "the mitochondria idk", "x = 7 idk", "just tell me, is it 7?"],
)
def test_a_hedged_answer_is_graded_but_never_unlocks_hints(text):
    """The split: (B) grades a hedged submission, (A) keeps it from counting
    toward hint unlocking or H6. matches_non_attempt is the routing rule and
    is never the is_genuine_attempt argument."""
    from learning.gates import has_non_attempt_phrase, matches_non_attempt, non_attempt_phrases

    assert non_attempt_phrases(text) == () and matches_non_attempt(text) is False
    assert has_non_attempt_phrase(text) is True
    step, _ = _two_attempts((text, text))
    assert step.genuine_attempts == 0


@pytest.mark.parametrize(
    "text",
    ["no idea", "Where do I start?", "I really don't know", "dunno", "not sure", "I give up",
     "this is too hard", "I'm lost", "I've been at this for hours"],
)  # fmt: skip
def test_a_plea_without_a_pattern_phrase_is_graded_but_no_attempt(text):
    """NON_ATTEMPT_PATTERNS is exactly the spec's five, so a plea without one
    routes to grading (Known gaps); a _PLEA plea still vetoes the attempt."""
    from learning.gates import has_non_attempt_phrase, non_attempt_phrases

    assert non_attempt_phrases(text) == ()
    assert has_non_attempt_phrase(text) is True


@pytest.mark.parametrize(
    "text",
    ["I think it's photosynthesis", "x = 7", "the mitochondria", "no", "even", "an electron", ""],
)
def test_an_answer_without_a_phrase_or_plea_can_be_a_genuine_attempt(text):
    from learning.gates import has_non_attempt_phrase

    assert has_non_attempt_phrase(text) is False


def test_every_routed_non_attempt_is_also_no_genuine_attempt():
    """A message the route sends to idk evidence or a hint request is never a
    genuine attempt: non_attempt_phrases(t) != () implies has_non_attempt_phrase(t)."""
    from learning.gates import has_non_attempt_phrase, non_attempt_phrases

    texts = [t for t, _ in _PLEAS] + list(_PROBE_PLEAS) + [
        "Sorry, idk", "idk, just tell me", "Please just tell me how photosynthesis works",
        "ok. What's the answer?", "Honestly? I don’t know", "IDK...", "i dont know",
        "Just TELL me the steps", "give me the answer!!", "whats the answer?",
    ]  # fmt: skip
    routed = [t for t in texts if non_attempt_phrases(t)]
    assert len(routed) > len(texts) // 2
    assert all(has_non_attempt_phrase(t) for t in routed)


_FUZZ_PARTS = (
    "idk", "i", "don't", "dont", "don’t", "know", "just", "tell", "me", "give", "the",
    "answer", "what's", "whats", "but", "no", "idea", "it", "is", "isn't", "7", "x", "part",
    "question", "to", "give up", "'", "`", "’", "´", " ", " ", " ", ",", ".", "?", "!", "=",
    "(", ")", "-", "\n",
)  # fmt: skip


def test_a_routed_non_attempt_always_holds_a_non_attempt_phrase_property():
    """non_attempt_phrases(t) != () implies has_non_attempt_phrase(t) for any
    text: an apostrophe glued between a phrase and "but" ("give but`idk` the")
    never makes the clause split see a phrase the whole-message view does not."""
    import random

    from learning.gates import has_non_attempt_phrase, non_attempt_phrases

    for text in ("give but`idk` the ", "i don’t know'but -? is ", "idk'but", "but'idk"):
        assert not non_attempt_phrases(text) or has_non_attempt_phrase(text), text
    rng = random.Random(606)
    for _ in range(20_000):
        text = "".join(rng.choice(_FUZZ_PARTS) for _ in range(rng.randint(1, 9)))
        assert not non_attempt_phrases(text) or has_non_attempt_phrase(text), repr(text)


@pytest.mark.parametrize(
    "text,phrases",
    [
        ("just tell me the answer to question 3", ("just tell me",)),
        ("what's the answer to part 2", ("what's the answer",)),
        ("give me the answer for 4b", ("give me the answer",)),
        ("whats the answer to q3", ("what's the answer",)),
        ("What's the answer to #3?", ("what's the answer",)),
        ("what's the answer to no. 3", ("what's the answer",)),
        ("what's the answer to number 5", ("what's the answer",)),
        ("just tell me the steps for problem 2.1", ("just tell me",)),
        ("just tell me part 2(b)", ("just tell me",)),
        ("give me the answer to questions 3-5", ("give me the answer",)),
        ("give me the answer to 3", ("give me the answer",)),
        ("idk, what's the answer to part 2", ("idk", "what's the answer")),
    ],
)
def test_a_question_label_in_a_request_is_no_answer(text, phrases):
    """Spec §13 A16: "just tell me" / "give me the answer" / "what's the
    answer" → no evidence, served as a hint request. The number of the
    question asked about ("question 3", "part 2", "4b" after "the answer
    for") is no submitted answer, so it never turns the request into a
    graded, wrong submission; any other digit still does (decision (B))."""
    from learning.gates import has_non_attempt_phrase, non_attempt_phrases

    assert non_attempt_phrases(text) == phrases
    assert has_non_attempt_phrase(text) is True


def _fastest_of_three(fn, text):
    import time

    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        fn(text)
        best = min(best, time.perf_counter() - start)
    return best


@pytest.mark.parametrize("size", [500, 5000])
def test_the_text_rules_run_in_linear_time_on_long_whitespace(size):
    """PKG-07 runs non_attempt_phrases on every raw submission, so no
    whitespace run may make a regex backtrack super-linearly: "part" followed
    by thousands of spaces and no digit took seconds (cubic) through
    _QUESTION_REF's three adjacent whitespace runs. A linear scan of these
    inputs takes well under a millisecond; 50 ms catches cubic at 500 and
    quadratic at 5000."""
    from learning.gates import has_non_attempt_phrase, non_attempt_phrases

    ws = (" ", "\t", "\n")
    shapes = [
        f"just tell me {label}{w * size}{tail}"
        for label in ("part", "question", "q", "no .", "#", "the answer to", "step")
        for w in ws
        for tail in ("a", "x 1", "?", ".")
    ]
    shapes += [
        "just tell me" + (" part" + " " * (size // 20)) * 20,
        "idk a" + " " * size + "=" + " " * size + "(",
        "what's the answer to step" + "\t" * size + "?",
        "just tell me " + "part. " * (size // 6),
    ]
    for text in shapes:
        for fn in (non_attempt_phrases, has_non_attempt_phrase):
            took = _fastest_of_three(fn, text)
            assert took < 0.05, (fn.__name__, text[:30], size, took)


@pytest.mark.parametrize(
    "text",
    ["I can't do it by factoring, so I used the quadratic formula and got x = 3",
     "I couldn't do this with substitution so I integrated by parts: x sin x + cos x",
     "I cannot do it using the chain rule, so I expanded first: 6x + 6",
     "I can't do it without a calculator, but roughly 1.41"],
)  # fmt: skip
def test_a_method_the_student_could_not_use_is_no_plea(text):
    """ "I can't do it" is a plea (it keeps "idk, I can't do it" idk), but a
    method after it ("by factoring", "with substitution") makes it part of
    worked reasoning, which may count as a genuine attempt."""
    from learning.gates import has_non_attempt_phrase, non_attempt_phrases

    assert has_non_attempt_phrase(text) is False
    assert non_attempt_phrases(text) == ()


def test_i_cannot_do_it_alone_is_a_plea():
    from learning.gates import has_non_attempt_phrase

    for text in (
        "I can't do this",
        "I can't do it.",
        "i cannot do this, sorry",
        "I couldn't do it",
    ):
        assert has_non_attempt_phrase(text) is True, text


@pytest.mark.parametrize(
    "text", ["just tell me, is it CH4?", "just tell me if it is CH3OH", "give me the answer, CH2O?"]
)
def test_a_chemical_formula_is_no_question_label(text):
    """An all-caps "CH" glued to a digit is a formula, not "chapter N": the
    digit is an answer, so the message is graded."""
    from learning.gates import non_attempt_phrases

    assert non_attempt_phrases(text) == ()


@pytest.mark.parametrize(
    "text,phrases",
    [
        ("whats the answer to ch3", ("what's the answer",)),
        ("just tell me the answer to Ch4", ("just tell me",)),
        ("just tell me the answer to CH 4", ("just tell me",)),
        ("give me the answer to ch. 3", ("give me the answer",)),
    ],
)
def test_a_chapter_label_is_still_a_question_label(text, phrases):
    from learning.gates import non_attempt_phrases

    assert non_attempt_phrases(text) == phrases


def test_has_non_attempt_phrase_matches_whole_words_only():
    from learning.gates import has_non_attempt_phrase

    assert has_non_attempt_phrase("idkfa") is False
    assert has_non_attempt_phrase("I don’t know") is True  # typographic apostrophe
    assert has_non_attempt_phrase("IDK!!!") is True
    assert has_non_attempt_phrase("just. tell me") is True  # normalised across punctuation


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


# ── leak detector (spec §3.4 LEAK_NGRAM, §13 A34; research "Guardrails") ───────
#
# A34: the final-answer rule matches the item's STRUCTURED final_answer
# (PKG-04's check_items.final_answer, stated by the generator verbatim from
# its reference) and, for a numeric item, its canonical_answer by value. The
# reference text is never parsed for a final answer, so every fixture names
# its item's final answer.

REF_POWER = (
    "The derivative of x squared is two x because the power rule brings "
    "the exponent down and reduces it by one"
)
FA_POWER = "two x"
REF_EQ = "x + 3 = 10, so x = 7"
FA_EQ = "7"
REF_VEL = "The final velocity is 9.8 m/s"
FA_VEL = "9.8 m/s"
REF_SYM = "F = m a"
FA_SYM = "m a"
# Shorter than LEAK_NGRAM tokens: only the whole-reference run can catch these
# under the n-gram rule (free / mc_reason references may be this short).
REF_SHORT = "The mitochondria."
FA_SHORT = "mitochondria"
REF_LAW = "Newton's third law"
FA_LAW = "third law"
REF_CELL = "The powerhouse of the cell"
FA_CELL = "powerhouse of the cell"

LEAKS = [
    (
        REF_POWER,
        FA_POWER,
        "Remember: the power rule brings the exponent down, so try that.",
        "ngram",
    ),
    (
        REF_POWER,
        FA_POWER,
        "It reduces it by one and the power rule brings the exponent down.",
        "ngram",
    ),
    (REF_EQ, FA_EQ, "So x must be 7.", "final_answer"),
    (REF_EQ, FA_EQ, "Check whether 7 satisfies the equation.", "final_answer"),
    (REF_VEL, FA_VEL, "Plug in and you get 9.8 m/s.", "final_answer"),
    (REF_SYM, FA_SYM, "Force is just m a, multiply them.", "final_answer"),
    (REF_POWER, FA_POWER, "the derivative of x squared is two x", "ngram"),
    (REF_POWER, FA_POWER, "So it comes out as two x.", "final_answer"),
    (
        REF_SHORT,
        FA_SHORT,
        "Cellular respiration happens in the mitochondria, which produce most ATP.",
        "ngram",
    ),
    (REF_SHORT, FA_SHORT, "Mitochondria!", "final_answer"),
    (REF_CELL, FA_CELL, "It is the powerhouse of the cell.", "ngram"),
    (REF_LAW, FA_LAW, "This is Newton's third law at work.", "ngram"),
    (REF_LAW, FA_LAW, "It is the Third Law.", "final_answer"),
]

SAFE = [
    (REF_POWER, FA_POWER, "What rule applies when a variable is raised to a power?"),
    (REF_POWER, FA_POWER, "Look at the exponent first. What happens to it?"),
    (REF_EQ, FA_EQ, "Subtract 3 from both sides, then look at what is left."),
    (REF_EQ, FA_EQ, "What operation undoes adding 3?"),
    (REF_EQ, FA_EQ, "Try it with 17, then with 0.7."),  # a number is never read inside another
    (REF_VEL, FA_VEL, "Which kinematic equation links acceleration and time?"),
    (REF_SYM, FA_SYM, "What is force in terms of mass? Think about Newton's second law."),
    (REF_POWER, FA_POWER, "The power rule is in section 2.3 of your notes; read the first line."),
    (REF_SHORT, FA_SHORT, "Which organelle makes most of the cell's ATP?"),
    (REF_LAW, FA_LAW, "Which of Newton's laws pairs every force with another?"),
]


@pytest.mark.parametrize("reference,final,emitted,detector", LEAKS)
def test_detect_leak_catches(reference, final, emitted, detector):
    from learning.ladder import Rung
    from learning.leak import detect_leak

    v = detect_leak(reference, emitted, Rung.H3, final_answer=final)
    assert (v.leaked, v.detector) == (True, detector)


@pytest.mark.parametrize("reference,final,emitted", SAFE)
def test_detect_leak_zero_false_positives(reference, final, emitted):
    from learning.ladder import Rung
    from learning.leak import detect_leak, tokens

    assert detect_leak(reference, emitted, Rung.H0, final_answer=final) == (False, "none")
    ref, em = tokens(reference), tokens(emitted)
    n = min(params.LEAK_NGRAM, len(ref))
    em_grams = {tuple(em[j : j + n]) for j in range(len(em) - n + 1)}
    assert not any(tuple(ref[i : i + n]) in em_grams for i in range(len(ref) - n + 1))


def test_h6_is_never_a_leak():
    from learning.ladder import Rung
    from learning.leak import detect_leak

    assert detect_leak(REF_EQ, REF_EQ, Rung.H6, final_answer=FA_EQ).leaked is False
    assert detect_leak(REF_EQ, REF_EQ, Rung.H5, final_answer=FA_EQ).leaked is True


def test_a_final_answer_is_required():
    """A34: callers hold only items that passed selection (checks.is_servable),
    so a missing or empty final answer is a programmer error — never a silent
    fallback to parsing the reference."""
    import inspect

    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    for missing in (None, "", "   ", "...", "“ ”"):
        with pytest.raises(ValueError):
            detect_leak(REF_EQ, "hint", Rung.H3, final_answer=missing)
        with pytest.raises(ValueError):
            detect_leak(REF_EQ, "hint", Rung.H6, final_answer=missing)
        with pytest.raises(ValueError):
            strip_leak("hint", REF_EQ, final_answer=missing)
    for fn in (detect_leak, strip_leak):
        params_ = inspect.signature(fn).parameters
        assert params_["final_answer"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params_["final_answer"].default is inspect.Parameter.empty
        assert params_["canonical_answer"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params_["canonical_answer"].default is None
    with pytest.raises(TypeError):
        detect_leak(REF_EQ, "hint", Rung.H3)
    with pytest.raises(TypeError):
        detect_leak(REF_EQ, "hint", Rung.H3, "7")
    with pytest.raises(TypeError):
        strip_leak("hint", REF_EQ, "7")


def test_the_reference_is_never_parsed_for_a_final_answer():
    """The text heuristics (cue words, '=' clauses, last number, power terms,
    justifications) are gone: only the structured answer is matched. An
    intermediate number of the reference is no leak; the stated answer is."""
    from learning import leak
    from learning.ladder import Rung
    from learning.leak import detect_leak

    for gone in ("final_answer", "_final_answer_text", "_pick", "_CUE", "_ASIDE", "_eq_clauses"):
        assert not hasattr(leak, gone), gone
    ref = "x + 3 = 10, so x = 7"
    assert detect_leak(ref, "What is 10 minus 3?", Rung.H3, final_answer="7") == (False, "none")
    assert detect_leak(ref, "It is 7.", Rung.H3, final_answer="7") == (True, "final_answer")
    # a final answer the reference text states differently is still the answer
    assert detect_leak(ref, "Is it 3?", Rung.H3, final_answer="x = 7") == (False, "none")
    assert detect_leak(ref, "So x=7 then.", Rung.H3, final_answer="x = 7").leaked


DIFF_REF = "Differentiate term by term: the derivative of 2x^3 + 5 is 6x^2."
G_REF = "The ball is in free fall, so g = 9.8 m/s^2"


@pytest.mark.parametrize(
    "hint", ["You should get 6x^2.", "You should get 6x².", "It is 6 x ^ 2.", "It is 6*x**2."]
)
def test_a_symbolic_final_answer_leaks_in_any_spelling(hint):
    from learning.ladder import Rung
    from learning.leak import WITHHELD, detect_leak, strip_leak

    assert detect_leak(DIFF_REF, hint, Rung.H3, final_answer="6x^2") == (True, "final_answer")
    once = strip_leak(hint, DIFF_REF, final_answer="6x^2")
    assert WITHHELD in once and "6" not in once, once
    assert detect_leak(DIFF_REF, once, Rung.H0, final_answer="6x^2") == (False, "none")
    assert strip_leak(once, DIFF_REF, final_answer="6x^2") == once


def test_a_hint_about_the_steps_is_clean():
    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    hint = "What happens to the constant 5 when you differentiate?"
    assert detect_leak(DIFF_REF, hint, Rung.H3, final_answer="6x^2") == (False, "none")
    assert strip_leak(hint, DIFF_REF, final_answer="6x^2") == hint
    for clean in ("Bring the exponent 3 down.", "What is 2 times 3?", "Try x^2 first.", "12x^2?"):
        assert detect_leak(DIFF_REF, clean, Rung.H1, final_answer="6x^2") == (False, "none"), clean


def test_a_final_answer_with_a_unit_leaks_reformatted():
    from learning.ladder import Rung
    from learning.leak import WITHHELD, detect_leak, strip_leak

    final = "9.8 m/s^2"
    for hint in ("It is 9.80 m/s².", "that gives 9.8 m/s**2", "about 9.8 m / s ^ 2 here"):
        assert detect_leak(G_REF, hint, Rung.H3, final_answer=final) == (True, "final_answer")
        once = strip_leak(hint, G_REF, final_answer=final)
        assert (
            WITHHELD in once and detect_leak(G_REF, once, Rung.H0, final_answer=final)[0] is False
        )
    # a free item's answer is its whole run: the bare number alone is not it
    # (a numeric item's canonical_answer catches that, below)
    assert detect_leak(G_REF, "Use 9.8 for g.", Rung.H3, final_answer=final) == (False, "none")
    assert detect_leak(
        G_REF, "Use 9.8 for g.", Rung.H3, final_answer=final, canonical_answer="9.8"
    ) == (True, "final_answer")


MC_REF = "C: It never terminates, because no base case stops the calls."
MC_FINAL = "It never terminates"  # option C's text (A34: the mc_reason final answer)


def test_an_mc_reason_items_correct_option_text_leaks():
    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    hint = "So it never terminates?"
    assert detect_leak(MC_REF, hint, Rung.H3, final_answer=MC_FINAL) == (True, "final_answer")
    assert strip_leak(hint, MC_REF, final_answer=MC_FINAL) == "So [withheld]?"
    for clean in ("What stops the calls?", "Which option describes the missing base case?"):
        assert detect_leak(MC_REF, clean, Rung.H3, final_answer=MC_FINAL) == (False, "none")


TB_REF = (
    "Recursion works because a function calls itself on smaller inputs until a base case stops it."
)
TB_FINAL = "calls itself on smaller inputs"  # the teachback's decisive claim


def test_a_teachback_claim_leaks_but_the_concept_name_alone_is_clean():
    """PKG-04's validate_draft never accepts a final answer that is (part of)
    the concept name, so a hint naming the concept is clean."""
    from learning.ladder import Rung
    from learning.leak import detect_leak

    leak_ = "It calls itself on smaller inputs."
    assert detect_leak(TB_REF, leak_, Rung.H3, final_answer=TB_FINAL) == (True, "final_answer")
    for clean in (
        "Think about recursion: what does the function do each time?",
        "Recursion needs a stopping point. What is it here?",
    ):
        assert detect_leak(TB_REF, clean, Rung.H3, final_answer=TB_FINAL) == (False, "none")


REF_SLIDE = "The block slides 14 m before it stops; friction removes 3 J per metre of travel."
FA_SLIDE = "14 m"


def test_canonical_answer_is_matched_by_value():
    """A numeric item's canonical_answer (PKG-04, decrypted by the caller) is
    also matched as a number by value anywhere in the text; its sign and an
    e-notation exponent are not part of the matched value."""
    from learning.ladder import Rung
    from learning.leak import WITHHELD, detect_leak, strip_leak

    hint_3 = "Where do the 3 J go?"  # an intermediate number is no leak
    for canonical in (None, "14"):
        v = detect_leak(
            REF_SLIDE, hint_3, Rung.H3, final_answer=FA_SLIDE, canonical_answer=canonical
        )
        assert v == (False, "none")
    hint_14 = "So it should travel about 14.0 metres."
    assert detect_leak(REF_SLIDE, hint_14, Rung.H3, final_answer=FA_SLIDE) == (False, "none")
    assert detect_leak(
        REF_SLIDE, hint_14, Rung.H3, final_answer=FA_SLIDE, canonical_answer="14"
    ) == (True, "final_answer")
    once = strip_leak(hint_14, REF_SLIDE, final_answer=FA_SLIDE, canonical_answer="14")
    assert once == f"So it should travel about {WITHHELD} metres."
    for canonical, hint in (
        ("1250", "It comes to 1,250 J."),
        ("1250.0", "It comes to 1250 J."),
        ("2.50", "So v is 2.5 m/s."),
        ("0.5", "About .50 of it."),
        (".5", "About 0.5 of it."),
        ("-3", "The root is −3."),
        ("+42", "It is 42."),
        ("6.022e23", "About 6.022 x 10^23 of them."),
        (" 7 ", "Is it 7?"),
    ):
        v = detect_leak(REF_SLIDE, hint, Rung.H3, final_answer=FA_SLIDE, canonical_answer=canonical)
        assert v == (True, "final_answer"), (canonical, hint)
        once = strip_leak(hint, REF_SLIDE, final_answer=FA_SLIDE, canonical_answer=canonical)
        assert WITHHELD in once, (canonical, once)
        assert not detect_leak(
            REF_SLIDE, once, Rung.H0, final_answer=FA_SLIDE, canonical_answer=canonical
        ).leaked
    assert detect_leak(
        REF_SLIDE, "It is 12,500 J.", Rung.H3, final_answer=FA_SLIDE, canonical_answer="1250"
    ) == (False, "none")
    # a blank or non-numeric canonical_answer adds no value match
    for canonical in ("", "   ", "abc", "nan", "x = 7"):
        v = detect_leak(
            REF_SLIDE, "Is it 7?", Rung.H3, final_answer=FA_SLIDE, canonical_answer=canonical
        )
        assert v == (False, "none"), canonical
    # the n-gram rule still reads the reference
    copied = "It slides 14 m before it stops, see?"
    v = detect_leak(REF_SLIDE, copied, Rung.H3, final_answer="99 m", canonical_answer="99")
    assert v == (True, "ngram")


REF_CURRENT = "I = V/R = 5/2000 = 2.5 \u00d7 10^-3 A. Final answer: 2.5 \u00d7 10^-3 A."
FA_CURRENT = "2.5 \u00d7 10^-3 A"


@pytest.mark.parametrize(
    "canonical,hint,stripped",
    [
        # canonical in plain decimal (PKG-04's prompt), hint in scientific notation
        ("0.0025", "You should get 2.5 \u00d7 10\u207b\u00b3.", "You should get [withheld]."),
        ("0.0025", "It is 2.5 x 10^-3 amps", "It is [withheld] amps"),
        ("0.0025", "So I = 2.5e-3 here.", "So I = [withheld] here."),
        ("0.0025", "So I = 2.5*10**-3.", "So I = [withheld]."),
        ("0.0025", "About 25 \u00d7 10^-4, then.", "About [withheld], then."),
        # canonical in e-notation, hint in plain decimal
        ("2.5e-3", "So I = 0.0025", "So I = [withheld]"),
        ("2.5e-3", "So I = 0.00250 A.", "So I = [withheld] A."),
        ("1e3", "It is 1000 m.", "It is [withheld] m."),
        ("6.022e23", "N is 602,200,000,000,000,000,000,000.", "N is [withheld]."),
        # a signed canonical matches the magnitude, as the mantissa rule does
        ("-0.0025", "It is 2.5 \u00d7 10^-3.", "It is [withheld]."),
    ],
)
def test_canonical_answer_is_matched_by_value_in_any_notation(canonical, hint, stripped):
    """A numeric item's canonical_answer also matches a number whose WRITTEN
    value (with an exponent right after it: e-notation, "\u00d7 10^k", "x 10^k", a
    superscript) equals it, in either direction: the hint's unit-less
    scientific notation otherwise passes both the final-answer run (it carries
    the unit) and the mantissa match."""
    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    kw = {"final_answer": FA_CURRENT, "canonical_answer": canonical}
    assert detect_leak(REF_CURRENT, hint, Rung.H3, **kw) == (True, "final_answer")
    once = strip_leak(hint, REF_CURRENT, **kw)
    assert once == stripped
    assert detect_leak(REF_CURRENT, once, Rung.H0, **kw) == (False, "none")
    assert strip_leak(once, REF_CURRENT, **kw) == once


def test_a_number_is_its_value_whatever_exponent_follows_it():
    """The bare number with the canonical value is flagged even when an
    exponent follows it, as the mantissa rule already is: otherwise a strip
    that masks the exponent's base for another rule (here the final answer
    "10") would leave a bare "0.1" the detector then flags (a seeded fuzz
    found it)."""
    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    kw = {"final_answer": "10", "canonical_answer": "1e-1"}
    text = "Use 0.1, 10\u207b\u00b3 here."
    assert detect_leak("x", text, Rung.H3, **kw) == (True, "final_answer")
    once = strip_leak(text, "x", **kw)
    assert "0.1" not in once and detect_leak("x", once, Rung.H0, **kw) == (False, "none")
    assert strip_leak(once, "x", **kw) == once


@pytest.mark.parametrize(
    "canonical,hint",
    [
        ("0.0025", "Try 2.5 \u00d7 10^-2 first."),  # another value
        ("0.0025", "Divide 5 by 2000."),
        ("0.0025", "The exponent is -3 and the mantissa 2.5?"),
        ("0.0025", "What is 2.5 e.g. in amps?"),  # "e" not before a digit
    ],
)
def test_canonical_value_in_notation_is_not_a_partial_match(canonical, hint):
    from learning.ladder import Rung
    from learning.leak import detect_leak

    kw = {"final_answer": FA_CURRENT, "canonical_answer": canonical}
    assert detect_leak(REF_CURRENT, hint, Rung.H3, **kw) == (False, "none"), hint


REF_BIG_O = (
    "An O(n) loop grows linearly while an O(2^n) recursion doubles with every n. "
    "Final answer: Linear (O(n)) is much better than exponential (O(2^n))."
)
FA_BIG_O = "Linear (O(n)) is much better than exponential (O(2^n))."


@pytest.mark.parametrize(
    "reference,final,canonical,hint",
    [
        # (a) an mc_reason item's correct option LETTER: the final answer is the
        # option's text (A34), and the n-gram rule never matches one letter
        (MC_REF, MC_FINAL, None, "The answer is C."),
        (MC_REF, MC_FINAL, None, "Is it option C?"),
        (MC_REF, MC_FINAL, None, "Look again at (C) - it is right."),
        # (b) LaTeX macros (the loop tutor may write math in LaTeX): \cdot,
        # \times, \text{}, \mathrm{}, \frac{}{}, \pi, \sqrt{}, \left/\right
        # each read as word tokens that split the run
        (DIFF_REF, "6x^2", None, "So you get $6 \\cdot x^{2}$."),
        (DIFF_REF, "6x^2", None, "So you get $6 \\times x^2$."),
        (G_REF, "9.8 m/s^2", None, "$g = 9.8\\,\\mathrm{m/s^2}$"),
        ("It factors as (x-3)^2.", "(x-3)^2", None, "So it is $\\left(x-3\\right)^2$."),
        (G_REF, "9.8 m/s^2", None, "$g = 9.8\\,\\text{m/s}^2$"),
        ("x = 1/2", "1/2", None, "x = $\\frac{1}{2}$"),
        ("The circumference is 2πr.", "2πr", None, "So it is $2\\pi r$."),
        ("The side is √2.", "√2", None, "So the side is $\\sqrt{2}$."),
        # ... and the other direction: a final answer the generator copied in
        # LaTeX against a plain hint
        ("x = $\\frac{1}{2}x^2$", "$\\frac{1}{2}x^2$", None, "So it is 1/2 x^2"),
        ("The area is $6 \\cdot x^{2}$.", "$6 \\cdot x^{2}$", None, "So it is 6x^2."),
        ("The circumference is 2\\pi r.", "2\\pi r", None, "So it is 2πr."),
        ("The side is $\\sqrt{2}$.", "$\\sqrt{2}$", None, "So the side is √2."),
        # U+2044 FRACTION SLASH (what NFKC makes of U+00BD) and U+2215 DIVISION
        # SLASH are not "/", so a vulgar fraction misses "1/2" (and 0.5)
        ("x = 1/2", "1/2", None, "It is \u00bd"),
        ("x = 1/2", "1/2", "0.5", "It is \u00bd"),
        ("x = 1/2", "1/2", None, "It is 1\u20442"),
        ("x = 1/2", "1/2", None, "It is 1\u22152"),
        # (c) a hyphenated answer in its spaced spelling ('-' is a token)
        (
            "It is a first-order reaction.",
            "first-order reaction",
            None,
            "So is it a first order reaction?",
        ),
        ("The eigenvalues are non-negative.", "non-negative", None, "Are they non negative?"),
        # (d) a bare power of ten has no mantissa to scale
        ("It is 1000 m.", "1000 m", "1e3", "Is it 10^3?"),
        # (e) the decisive part of a long final answer (most free and
        # teachback final answers are 6+ tokens; the rule matches the whole run)
        (REF_BIG_O, FA_BIG_O, None, "Compare O(n) with O(2^n): which grows slower?"),
        # (f) a paraphrase of a teachback claim
        (TB_REF, TB_FINAL, None, "So it calls itself on a smaller problem?"),
        # (g) an answer spelled in words, another unit spelling, or (on a free
        # item, with no canonical value) scientific notation written otherwise
        (DIFF_REF, "6x^2", None, "So it is six x squared."),
        (G_REF, "9.8 m/s^2", None, "So g is 9.8 m s^-2."),
        (G_REF, "9.8 m/s^2", None, "So g is 9.8 metres per second squared."),
        ("Avogadro: 6.022e23 per mole.", "6.022e23", None, "About 6.022 x 10^23 of them."),
        # (h) unicode: a superscript letter outside the exponent set folds
        # without its "^"; a decomposed accent (letter + combining mark) splits
        # the word
        ("It is x^a.", "x^a", None, "So it is x\u1d43."),
        ("Send your r\u00e9sum\u00e9.", "r\u00e9sum\u00e9", None, "Send the re\u0301sume\u0301."),
    ],
)
def test_known_gaps_of_the_final_answer_rule_are_pinned(reference, final, canonical, hint):
    """Residuals the owner accepted as documented known gaps (review round 7:
    "accept the remaining leak-detector edge cases as documented known gaps"):
    HANDOFF-06 Known gaps and spec §13 A34's known limits list each. A change
    that closes one updates both and moves its case to LEAKS."""
    from learning.ladder import Rung
    from learning.leak import detect_leak

    kw = {"final_answer": final, "canonical_answer": canonical}
    assert detect_leak(reference, hint, Rung.H3, **kw) == (False, "none"), hint


@pytest.mark.parametrize(
    "reference,final,canonical,hint",
    [
        # brackets are no token: "x - 3^2" is read as "(x-3)^2"
        ("It factors as (x-3)^2.", "(x-3)^2", None, "Is it x - 3^2?"),
        # '*' is juxtaposition: "6 x" is read as "6*x"
        ("d/dx 3x^2 = 6*x", "6*x", None, "It is 6 x."),
        # a numeric item's canonical value flags that number anywhere
        ("It is 2.", "2", "2", "In step 2, square it."),
    ],
)
def test_known_over_matches_of_the_final_answer_rule_are_pinned(reference, final, canonical, hint):
    """Over-matching is the safe direction and stays (HANDOFF-06 Known gaps;
    Open question (n)): a false withhold costs a word, a false pass reveals
    the answer."""
    from learning.ladder import Rung
    from learning.leak import detect_leak

    kw = {"final_answer": final, "canonical_answer": canonical}
    assert detect_leak(reference, hint, Rung.H3, **kw) == (True, "final_answer"), hint


REF_FACTOR = "Expand x^2 - 6x + 9: it factors as (x-3)^2."


@pytest.mark.parametrize(
    "reference,final,canonical,emitted,stripped",
    [
        # a bracket opened inside a withheld run is closed with it
        (DIFF_REF, "6x^2", None, "So you get $6x^{2}$.", "So you get $[withheld]$."),
        (DIFF_REF, "6x^2", None, "So you get $6x^{ 2 }$.", "So you get $[withheld]$."),
        (REF_CURRENT, FA_CURRENT, "2.5e-3", "I = 2.5 × 10^(-3)", "I = [withheld]"),
        (REF_CURRENT, FA_CURRENT, "2.5e-3", "I = 2.5 × 10^{-3}", "I = [withheld]"),
        (REF_CURRENT, FA_CURRENT, "2.5e-3", "So 2.5 × 10^{(-3)} here", "So [withheld] here"),
        (REF_CURRENT, FA_CURRENT, "0.0025", "I = 2.5 × (10^-3).", "I = [withheld]."),
        # a closer inside the run takes the opener right before it
        (REF_FACTOR, "(x-3)^2", None, "So it is (x-3)^2 then.", "So it is [withheld] then."),
        (REF_FACTOR, "(x-3)^2", None, "So it is ((x-3)^2).", "So it is ([withheld])."),
        (REF_FACTOR, "(x-3)^2", None, "So it is [(x - 3)^2].", "So it is [[withheld]]."),
        # brackets around a whole run are not the run's, and stay
        (REF_CURRENT, FA_CURRENT, "0.0025", "I = (2.5 × 10^-3)", "I = ([withheld])"),
        (DIFF_REF, "6x^2", None, "Is it {6x^2}?", "Is it {[withheld]}?"),
    ],
)
def test_strip_leak_keeps_brackets_paired(reference, final, canonical, emitted, stripped):
    """The stripper masks answer tokens, and brackets are no token: a run that
    spans an exponent's "(" or a LaTeX "{" (or a factor's ")") would leave its
    partner behind ("I = [withheld])", "$[withheld]}$"). A bracket paired
    across the run's edge is withheld with it when only whitespace parts it
    from the run; detect-clean and idempotence are unchanged."""
    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    kw = {"final_answer": final, "canonical_answer": canonical}
    once = strip_leak(emitted, reference, **kw)
    assert once == stripped
    assert detect_leak(reference, once, Rung.H0, **kw) == (False, "none")
    assert strip_leak(once, reference, **kw) == once


def test_strip_leak_may_leave_a_bracket_a_token_parts_from_the_run():
    """Known cosmetic gap (HANDOFF-06): a bracket whose partner lies beyond a
    token outside the run stays, so the partner is not masked with it (masking
    the "+ 1" too would withhold text that is no leak). Detect-clean holds."""
    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    kw = {"final_answer": FA_CURRENT, "canonical_answer": "0.0025"}
    once = strip_leak("I = 2.5 × 10^(-3 + 1)", REF_CURRENT, **kw)
    assert once == "I = [withheld] + 1)"
    assert detect_leak(REF_CURRENT, once, Rung.H0, **kw) == (False, "none")


def test_a_short_reference_leaks_when_it_appears_whole():
    """A reference shorter than LEAK_NGRAM tokens has no LEAK_NGRAM-gram, so the
    n-gram rule compares its whole token run instead (PKG-04's leak_in_prompt
    does the same for any length); a partial mention is not a leak."""
    from learning.ladder import Rung, deterministic_content
    from learning.leak import detect_leak, strip_leak

    item = _item(ACTIVE_HASH, reference_answer=REF_SHORT, final_answer=FA_SHORT)
    passage = "Cellular respiration happens in the mitochondria, which produce most ATP."
    payload = deterministic_content(Rung.H2, item, [], [passage])
    verdict = detect_leak(
        item.reference_answer, payload.text, payload.rung, final_answer=item.final_answer
    )
    assert verdict == (True, "ngram")
    assert strip_leak("It is the mitochondria.", REF_SHORT, final_answer=FA_SHORT) == (
        "It is [withheld]."
    )
    assert detect_leak(REF_LAW, "Think about the law.", Rung.H1, final_answer=FA_LAW) == (
        False,
        "none",
    )
    assert detect_leak("Paris", "The capital is Paris.", Rung.H1, final_answer="Paris") == (
        True,
        "ngram",
    )
    assert detect_leak("", "anything at all", Rung.H1, final_answer="x") == (False, "none")


REF_STEPS = (
    "1. Identify the limiting reagent from the mole ratio.\n"
    "2. Use it to compute the theoretical yield.\n"
    "Final answer: the theoretical yield."
)
FA_STEPS = "the theoretical yield"


def test_a_stepwise_reference_leaks_its_final_answer_not_its_step_labels():
    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    sibling = (
        "Nitrogen reacts with hydrogen...\n\n1. Convert each mass to moles.\n"
        "2. Compare against the balanced equation..."
    )
    assert detect_leak(REF_STEPS, sibling, Rung.H4, final_answer=FA_STEPS) == (False, "none")
    hint = "What should step 2 of your plan be?"
    assert detect_leak(REF_STEPS, hint, Rung.H3, final_answer=FA_STEPS) == (False, "none")
    assert strip_leak(hint, REF_STEPS, final_answer=FA_STEPS) == hint
    leaked = "Then you get the theoretical yield."
    assert detect_leak(REF_STEPS, leaked, Rung.H3, final_answer=FA_STEPS) == (True, "final_answer")


REF_WORK = "The work done is 1,250 J"
FA_WORK = "1,250 J"
REF_SPEED = "The speed is v = 2.50 m/s"
FA_SPEED = "2.50 m/s"


@pytest.mark.parametrize(
    "reference,final,emitted,stripped",
    [
        (REF_WORK, FA_WORK, "It is 1250 J.", "It is [withheld]."),
        (REF_WORK, FA_WORK, "It is 1250.0 J here.", "It is [withheld] here."),
        (REF_WORK, FA_WORK, "It comes to 01,250 J", "It comes to [withheld]"),
        (REF_SPEED, FA_SPEED, "So v is 2.5 m/s here.", "So v is [withheld] here."),
        (REF_SPEED, FA_SPEED, "So v is 2.500 m/s.", "So v is [withheld]."),
        ("x = 7", "7", "Is it 7.0?", "Is it [withheld]?"),
        ("It is 0.5", "0.5", "About .50 then.", "About [withheld] then."),
        (REF_WORK, FA_WORK, "٣٤ then 1250 J", "٣٤ then [withheld]"),
    ],
)
def test_final_answer_matches_numbers_by_value(reference, final, emitted, stripped):
    """Numbers compare by value on both sides: a hint that writes the answer
    without the thousands separator, or with other trailing zeros, still leaks
    it, and the stripper withholds the whole number (never half of "1,250")."""
    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    assert detect_leak(reference, emitted, Rung.H1, final_answer=final) == (True, "final_answer")
    assert strip_leak(emitted, reference, final_answer=final) == stripped
    assert detect_leak(reference, stripped, Rung.H0, final_answer=final) == (False, "none")
    assert strip_leak(stripped, reference, final_answer=final) == stripped


def test_final_answer_by_value_is_not_a_prefix_or_part_match():
    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    for safe in ("It is 12,500 J.", "Use 1.25 kJ as a check?", "2.05 m/s is too slow", "250 J"):
        assert detect_leak(REF_WORK, safe, Rung.H1, final_answer=FA_WORK) == (False, "none"), safe
        assert detect_leak(REF_SPEED, safe, Rung.H1, final_answer=FA_SPEED) == (False, "none"), safe
    # "1,250" is one number, never "1" and "250"
    assert strip_leak("Add 1,250 to it", "x = 250", final_answer="250") == "Add 1,250 to it"
    # an n-gram run that touches a number withholds the whole number
    ref = "the measured work comes to 1,250 joules on the ramp"
    once = strip_leak(
        "so it comes to 1,250 joules on the ramp today", ref, final_answer="1,250 joules"
    )
    assert once == "so it [withheld] today", once
    # non-ASCII digits are never tokens, so stripping stays detect-clean
    for reference, final, emitted in (("x = ٣", "x", "x٣ is it"), ("x = 7", "7", "x٣7 or ٣ 7")):
        once = strip_leak(emitted, reference, final_answer=final)
        assert detect_leak(reference, once, Rung.H0, final_answer=final) == (False, "none"), once
        assert strip_leak(once, reference, final_answer=final) == once


@pytest.mark.parametrize("reference,final,emitted,_", LEAKS)
def test_strip_leak_makes_text_safe_and_is_idempotent(reference, final, emitted, _):
    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    once = strip_leak(emitted, reference, final_answer=final)
    assert "[withheld]" in once
    assert detect_leak(reference, once, Rung.H0, final_answer=final).leaked is False
    assert strip_leak(once, reference, final_answer=final) == once


@pytest.mark.parametrize("reference,final,emitted", SAFE)
def test_strip_leak_leaves_safe_text_unchanged(reference, final, emitted):
    from learning.leak import strip_leak

    assert strip_leak(emitted, reference, final_answer=final) == emitted


def test_strip_leak_withholds_only_the_leaked_runs():
    from learning.leak import strip_leak

    assert strip_leak("So x must be 7.", REF_EQ, final_answer=FA_EQ) == "So x must be [withheld]."
    assert (
        strip_leak("Plug in and you get 9.8 m/s.", REF_VEL, final_answer=FA_VEL)
        == "Plug in and you get [withheld]."
    )
    assert (
        strip_leak(
            "Remember: The Power Rule brings the exponent down, so try that.",
            REF_POWER,
            final_answer=FA_POWER,
        )
        == "Remember: [withheld], so try that."
    )
    assert (
        strip_leak("It is 6*x**2, or 6x² if you like.", DIFF_REF, final_answer="6x^2")
        == "It is [withheld], or [withheld] if you like."
    )


_PROPERTY_CASES = [
    (REF_POWER, FA_POWER, None),
    (REF_EQ, FA_EQ, None),
    (REF_VEL, FA_VEL, None),
    (REF_SYM, FA_SYM, None),
    (REF_SHORT, FA_SHORT, None),
    (REF_LAW, FA_LAW, None),
    (REF_WORK, FA_WORK, "1250"),
    (REF_SPEED, FA_SPEED, "2.50"),
    (DIFF_REF, "6x^2", None),
    (G_REF, "9.8 m/s^2", "9.8"),
    (MC_REF, MC_FINAL, None),
    (TB_REF, TB_FINAL, None),
    (REF_SLIDE, FA_SLIDE, "14"),
    ("It is 6.022e23 molecules", "6.022e23", "6.022e23"),
    ("The root is -3.", "-3", "-3"),
    ("Expand x^2 - 6x + 9: it factors as (x-3)^2.", "(x-3)^2", None),
    (REF_CURRENT, FA_CURRENT, "0.0025"),
    (REF_CURRENT, FA_CURRENT, "2.5e-3"),
    ("It is 1000 m.", "1000 m", "1e3"),
]


def test_strip_leak_is_safe_and_idempotent_on_shuffled_reference_text():
    """Property check: any text built from the reference's own words and the
    final answer's spellings, in any order, with any separators (unicode,
    superscripts, multiplication signs, '**', newlines, case), comes out with
    no n-gram or final-answer leak after ONE strip, and a second strip is a
    no-op."""
    import random

    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    rng = random.Random(606)
    seps = [" ", ", ", "\n", " — ", "; ", " é ", "(", ") ", "/", " = ", "^", "**", " x "]
    seps += ["*", "×", "·", "−", "²", "³", ".", "", "[withheld]"]
    numbers = ["1250", "1,250", "01250.0", "12,500", "2.5", "2.500", "25", "7.0", "250", ".5"]
    numbers += ["3x^2", "6x²", "6*x**2", "6", "x", "10^23", "m/s²", "−3", "14.0"]
    numbers += ["2.5e-3", "0.0025", "25", "10⁻³", "10^-4", "e", "10", "1000", "1e3"]
    numbers += ["10^(-3)", "10^{-3}", "(10^-3)", "{2}", "(x-3)^2", "$6x^{2}$", "[", "}"]
    for reference, final, canonical in _PROPERTY_CASES:
        words = reference.split() + final.split() + numbers
        for _ in range(200):
            picked = [rng.choice(words) for _ in range(rng.randint(1, 30))]
            if rng.random() < 0.5:  # splice in a verbatim stretch of the reference
                start = rng.randrange(len(words))
                picked[rng.randrange(len(picked)) :] = words[start:]
            text = ""
            for w in picked:
                text += (w.upper() if rng.random() < 0.2 else w) + rng.choice(seps)
            kw = {"final_answer": final, "canonical_answer": canonical}
            once = strip_leak(text, reference, **kw)
            verdict = detect_leak(reference, once, Rung.H0, **kw)
            assert verdict.leaked is False, (reference, text, once)
            assert strip_leak(once, reference, **kw) == once


def test_strip_leak_is_safe_and_idempotent_on_random_unicode_math():
    """Property check over random text, references and final answers drawn
    from the characters the A34 normalisation rewrites (superscript runs, '**',
    multiplication signs, unicode minus and dashes, NFKC-folded characters,
    thousands separators, bare decimals, existing markers): ONE strip leaves
    nothing detect_leak flags, and a second strip is a no-op. It found a
    superscript run masked in part (the rest read as a new '^'; PKG-04's
    answer_tokens now spans a run whole)."""
    import random

    from learning.checks import answer_run
    from learning.ladder import Rung
    from learning.leak import WITHHELD, detect_leak, strip_leak

    rng = random.Random(3406)
    alphabet = list("abxyz0123456789 .,*^-+=/()\u00b2\u00b3\u207b\u00b9\u207d\u207e\u207f")
    alphabet += list("\u00d7\u00b7\u2212\u2013\ufb01\uff11\u212a\u0663\n")
    alphabet += ["**", "1,250", "0.5", ".5", WITHHELD, "e", "10"]
    alphabet += ["{", "}", "[", "]", "10^(-3)", "10^{-3}", "( ", " )"]
    checked = 0
    for _ in range(5000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        reference = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
        final = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8)))
        if not answer_run(final) or "withheld" in (final + reference).lower():
            continue
        kw = {
            "final_answer": final,
            "canonical_answer": rng.choice(
                [None, "1", "0.5", "-3", "1250", "6.022e23", "0.0025", "2.5e-3", "1e3", "0.1"]
            ),
        }
        once = strip_leak(text, reference, **kw)
        assert detect_leak(reference, once, Rung.H0, **kw).leaked is False, (text, once, kw)
        assert strip_leak(once, reference, **kw) == once
        checked += 1
    assert checked > 1000  # not vacuous


def test_leak_check_runs_in_linear_time():
    """References and hints are model text of any length."""
    import time

    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    big = 20_000
    for text, final in (
        ("x" + " " * big + "^", "x ^"),
        ("**a " * (big // 4), "a"),
        ("1 " * (big // 2), "1 1"),
        ("6x^2 + " * (big // 7), "6x^2 + 6x^2 + 1"),
        ("²" * big, "x"),
        ("1," * big, "1,1"),
        ("( " * (big // 4) + ") " * (big // 4), "a"),
        ("(1" * (big // 2) + " )" * (big // 2), "1"),  # a run holding every opener
        ("( " * (big // 2) + "1)" * (big // 2), "1"),  # and every closer
    ):
        start = time.perf_counter()
        detect_leak(text, text, Rung.H3, final_answer=final)
        strip_leak(text, text, final_answer=final, canonical_answer="1")
        assert time.perf_counter() - start < 1.0, text[:20]


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
        final_answer="3x^2",
        canonical_answer=None,
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
    detect_leak does, with the active item's final_answer and canonical_answer
    (A34). A passage quoting the reference leaks at H2; a passage stating the
    final answer leaks; a pointer does not."""
    from learning.ladder import Rung, deterministic_content
    from learning.leak import detect_leak

    item = _item(ACTIVE_HASH, reference_answer=REF_POWER, final_answer=FA_POWER)
    leaking = deterministic_content(Rung.H2, item, [], ["From the notes: " + REF_POWER])
    stating = deterministic_content(Rung.H2, item, [], ["Squared terms differentiate to two x."])
    pointer = deterministic_content(
        Rung.H2, item, [], ["The power rule is in section 2.3 of your notes; read the first line."]
    )

    def check(payload):
        return detect_leak(
            item.reference_answer,
            payload.text,
            payload.rung,
            final_answer=item.final_answer,
            canonical_answer=item.canonical_answer,
        )

    assert check(leaking) == (True, "ngram")
    assert check(stating) == (True, "final_answer")
    assert check(pointer) == (False, "none")


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
    """A malformed PKG-06 field starts fresh on its own (a bad step restarts
    with its PKG-06 fields at their defaults; a bad current /
    checks_since_rating takes its default), but every key PKG-06 does not own
    survives the load, top-level or on a step, so the next save cannot erase
    the session request counters (§3.5), this session's A23 "revealed"
    siblings or a step's check_item_id."""
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
    assert list(state.steps) == ["q", "r" * 64] and int(state.steps["r" * 64].rung) == 3
    assert state.steps["r" * 64].extra == {"node_id": "node-1"}
    assert state.steps["q"].genuine_attempts == 0 and state.steps["q"].first_shown_at == 1.0
    assert state.steps["q"].extra == {"check_item_id": "ci-1"}
    assert loop_state_store.save_loop_state("s1", state) is True
    written = t.update.call_args.args[0]["loop_state"]
    assert written["revealed"] == ["b" * 64]
    assert (written["tutor_requests"], written["deep_requests"]) == (39, 6)
    assert written["plan"] == {"approved": ["node-1"], "cursor": 0}
    assert set(written["steps"]) == {"q", "r" * 64} and written["checks_since_rating"] == 4
    assert written["steps"]["q"]["check_item_id"] == "ci-1"


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


def _pkg06_imports(source: str, package: str = "") -> list[str]:
    """Every PKG-06 module `source` imports, in any form: `import learning.x`,
    `from learning.x import y`, `from learning import x`, a relative import
    resolved against `package` (the importing file's dotted package), and
    `importlib.import_module(...)` / `import_module(...)` / `__import__(...)`
    with a string literal, at any depth."""
    import ast

    def resolve(level: int, module: str | None, base: str) -> str | None:
        parts = base.split(".") if base else []
        if level - 1 > len(parts):
            return None
        return ".".join(parts[: len(parts) - (level - 1)] + ([module] if module else []))

    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = resolve(node.level, node.module, package) if node.level else node.module
            if not module:
                continue
            names = [module] + [f"{module}.{a.name}" for a in node.names]
        elif isinstance(node, ast.Call) and (
            getattr(node.func, "id", None) in ("import_module", "__import__")
            or getattr(node.func, "attr", None) == "import_module"
        ):

            def literal(arg: ast.expr | None) -> str:
                ok = isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                return arg.value if ok else ""

            name = literal(node.args[0] if node.args else None)
            if name.startswith("."):  # import_module(".x", package="learning")
                pkg = [k.value for k in node.keywords if k.arg == "package"]
                base = literal(node.args[1] if len(node.args) > 1 else (pkg or [None])[0])
                level = len(name) - len(name.lstrip("."))
                name = resolve(level, name.lstrip(".") or None, base) or ""
            names = [name]
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
    # relative imports inside learning/, and dynamic imports by string
    assert _pkg06_imports("from . import policy, bkt", package="learning") == ["learning.policy"]
    assert _pkg06_imports("def f():\n    from .gates import x", package="learning") == [
        "learning.gates",
        "learning.gates.x",
    ]
    assert _pkg06_imports("from ..learning import leak", package="services") == ["learning.leak"]
    assert _pkg06_imports("from . import policy", package="services") == []
    assert _pkg06_imports("import importlib\nimportlib.import_module('learning.policy')") == [
        "learning.policy"
    ]
    assert _pkg06_imports(
        "from importlib import import_module\nimport_module('learning.leak')"
    ) == ["learning.leak"]
    assert _pkg06_imports("def f():\n    __import__('learning.gates')") == ["learning.gates"]
    assert _pkg06_imports("import_module('.ladder', 'learning')") == ["learning.ladder"]
    assert _pkg06_imports("import_module('.ladder', package='learning')") == ["learning.ladder"]
    assert _pkg06_imports("importlib.import_module(name)\nimport_module('learning.bkt')") == []
    assert _pkg06_imports("import_module(name, 'learning.policy')") == []  # no literal name


def test_inertness_scan_covers_learning_modules_outside_pkg06(tmp_path):
    """The scan skips only the six PKG-06 modules (they import each other) and
    tests: a lazy import of a PKG-06 module inside a learning module the app
    already loads (gate, evidence, checks, learner_state) is a load the
    subprocess probe below cannot see, since it reads sys.modules after
    `import main`, before any function body runs."""
    (tmp_path / "learning").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "learning" / "gate.py").write_text(
        "def learning_loop_active():\n    from learning import policy\n"
    )
    (tmp_path / "learning" / "evidence.py").write_text(
        "import importlib\n\ndef f():\n    return importlib.import_module('learning.leak')\n"
    )
    (tmp_path / "learning" / "checks.py").write_text("def f():\n    from . import ladder\n")
    (tmp_path / "learning" / "gates.py").write_text("from learning.policy import Band\n")
    (tmp_path / "tests" / "test_x.py").write_text("from learning import gates\n")
    assert _inertness_offenders(tmp_path) == [
        "learning/checks.py",
        "learning/evidence.py",
        "learning/gate.py",
    ]


def _inertness_offenders(root) -> list[str]:
    offenders = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).parts
        if rel[0] in ("tests", "venv", ".venv"):
            continue
        if rel[0] == "learning" and len(rel) == 2 and rel[1][:-3] in _PKG06_MODULES:
            continue
        package = ".".join(rel[:-1])
        if _pkg06_imports(path.read_text(errors="ignore"), package=package):
            offenders.append("/".join(rel))
    return offenders


def test_zpd_layer_is_inert_nothing_imports_it():
    offenders = _inertness_offenders(BACKEND)
    assert offenders == [], f"PKG-06 modules must stay unreferenced until PKG-07: {offenders}"


def test_importing_the_app_loads_no_pkg06_module():
    """The ast scan above sees import statements and literal dynamic imports,
    not what actually loads (a computed module name, a loader outside the
    tree). Import the real app in a clean interpreter and read sys.modules:
    flag-off byte-identity needs no PKG-06 module loaded at all. The two are
    complementary: this probe cannot see a lazy import inside a function
    body, which the ast scan catches."""
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
