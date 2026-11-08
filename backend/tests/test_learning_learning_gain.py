"""learning/learning_gain.py (spec §13 A112): the pre/post learning gain per
fixed post-test window — a concept's probe pretest (its first graded evidence,
when that is an independent probe grade) against its unassisted delayed
post-test outcome. Observed outcomes only: never p_known."""

from __future__ import annotations

import pytest

from learning import learning_gain as lg
from learning.evidence import Evidence, planning_observation
from learning.params import POSTTEST_DELAYED_MIN_DAYS, POSTTEST_WINDOWS_DAYS, RUNG_NO_CREDIT_MIN

W1, W2 = POSTTEST_WINDOWS_DAYS
PROBED = {"q-probe"}


def _anchor(*, correct=True, idk=False, max_rung=0, previously_seen=False, synthetic_idk=False,
            session="s1", qh="q-probe", channel="free_response", event_id="ev-1"):
    """A journal row as services/graph_service.py writes it, carrying the REAL
    planning envelope (learning.evidence.planning_observation)."""
    ev = Evidence(
        node_id="n1", channel=channel, correct=correct, idk=idk, max_rung=max_rung,
        session_id=session, check_item_id="item-1", question_hash=qh,
        planning_provenance={"check_item_id": "item-1", "difficulty": 2,
                             "synthetic_idk": synthetic_idk, "previously_seen": previously_seen},
    )
    return {
        "id": event_id, "node_id": ev.node_id, "session_id": ev.session_id,
        "question_hash": ev.question_hash, "check_item_id": ev.check_item_id,
        "channel": ev.channel, "correct": ev.correct, "assisted": ev.assisted,
        "max_rung": ev.max_rung,
        "reason": f"evidence:{ev.channel}:idk" if ev.idk else f"evidence:{ev.channel}",
        "planning_observation": planning_observation(ev),
    }


def _pose(window=W1, *, correct=True, rung=0, anchor="ev-1", days=10.0, answered=True):
    return {
        "user_id": "u", "node_id": "n1", "window_days": window, "correct": correct,
        "max_rung": rung, "anchor_event_id": anchor, "days_since_evidence": days,
        "answered_at": "2026-10-01T00:00:00+00:00" if answered else None,
    }


# ── the pretest ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("correct,idk,expected", [(True, False, True), (False, False, False),
                                                  (False, True, False)])
def test_an_independent_probe_anchor_is_the_pretest(correct, idk, expected):
    """A real "I don't know" on the probe is an honest pretest outcome: not known."""
    assert lg.pretest_outcome(_anchor(correct=correct, idk=idk), PROBED) is expected


@pytest.mark.parametrize(
    "row,probed",
    [
        (_anchor(qh="q-check"), PROBED),  # an in-session check after teaching: not a probe item
        (_anchor(), set()),  # its session's probe history lacks it (or is unreadable)
        (_anchor(session=None), PROBED),  # sessionless: a quiz or post-test answer
        (None, PROBED),
    ],
    ids=["check", "not-in-history", "sessionless", "no-row"],
)
def test_an_anchor_that_is_not_a_probe_grade_is_no_pretest(row, probed):
    """Planning provenance tags in-session checks too: only the session's probe
    history makes the row a probe grade."""
    assert lg.pretest_outcome(row, probed) is None


@pytest.mark.parametrize(
    "row",
    [
        _anchor(max_rung=2),  # helped on the way
        _anchor(max_rung=RUNG_NO_CREDIT_MIN, correct=False),
        _anchor(previously_seen=True),  # not a fresh item
        _anchor(correct=False, idk=True, synthetic_idk=True),  # a refused answer turned idk
    ],
    ids=["hint", "no-credit", "seen", "synthetic-idk"],
)
def test_a_probe_grade_that_was_not_independent_is_no_pretest(row):
    assert row["planning_observation"]["independent"] is False
    assert lg.pretest_outcome(row, PROBED) is None


def test_a_legacy_or_relabelled_envelope_is_no_pretest():
    """Unknown is never inferred, and the envelope cannot relabel its own row."""
    legacy = {**_anchor(), "planning_observation": None}
    flipped = _anchor()
    flipped["planning_observation"] = {**flipped["planning_observation"], "correct": False}
    other_item = _anchor()
    other_item["planning_observation"] = {**other_item["planning_observation"], "question_hash": "q-x"}
    idk_lie = {**_anchor(correct=False), "reason": "evidence:free_response:idk"}
    no_flag = _anchor()
    del no_flag["planning_observation"]["independent"]
    for row in (legacy, flipped, other_item, idk_lie, no_flag):
        assert lg.pretest_outcome(row, PROBED) is None


# ── the post-test outcome ────────────────────────────────────────────────────


def test_only_an_answered_unassisted_post_test_is_an_outcome():
    assert lg.posttest_outcome(_pose(correct=True)) is True
    assert lg.posttest_outcome(_pose(correct=False)) is False
    assert lg.posttest_outcome(_pose(rung=RUNG_NO_CREDIT_MIN)) is None  # worked or revealed since
    assert lg.posttest_outcome(_pose(rung=1)) is None  # helped
    assert lg.posttest_outcome(_pose(rung=None)) is None
    assert lg.posttest_outcome(_pose(rung=False)) is None  # a bool is no rung
    assert lg.posttest_outcome(_pose(correct=None)) is None  # a pose from before A112
    assert lg.posttest_outcome(_pose(answered=False)) is None


# ── the summary ──────────────────────────────────────────────────────────────


def test_summary_rates_paired_difference_and_transitions():
    pairs = [(False, True), (False, True), (True, True), (True, False), (False, False)]
    out = lg.summarize(pairs)
    assert out["n"] == 5
    assert out["pre_correct_rate"] == pytest.approx(2 / 5)
    assert out["post_correct_rate"] == pytest.approx(3 / 5)
    assert out["paired_difference"] == pytest.approx(1 / 5)  # mean(post − pre)
    assert (out["improved"], out["same"], out["worse"]) == (2, 2, 1)


def test_an_empty_summary_is_nones_not_zeros():
    out = lg.summarize([])
    assert out == {"n": 0, "pre_correct_rate": None, "post_correct_rate": None,
                   "paired_difference": None, "improved": 0, "same": 0, "worse": 0}


# ── per window ───────────────────────────────────────────────────────────────


def test_every_window_is_reported_in_order_even_when_empty():
    out = lg.learning_gain([], {})
    assert out["delayed_min_days"] == POSTTEST_DELAYED_MIN_DAYS
    assert [w["window_days"] for w in out["windows"]] == list(POSTTEST_WINDOWS_DAYS)
    for w in out["windows"]:
        assert w["n"] == 0 and w["posttests"] == 0
        assert w["pre_correct_rate"] is None and w["paired_difference"] is None
        assert w["delayed"]["n"] == 0 and w["delayed"]["post_correct_rate"] is None


def test_pairs_need_both_a_pretest_and_an_unassisted_outcome_in_the_window():
    pretests = {"ev-a": False, "ev-b": True, "ev-c": False}
    poses = [
        _pose(W1, correct=True, anchor="ev-a", days=9.0),  # improved, delayed
        _pose(W1, correct=False, anchor="ev-b", days=0.5),  # worse, recently practised
        _pose(W1, correct=True, anchor="ev-none"),  # an outcome with no usable pretest
        _pose(W1, correct=True, anchor="ev-c", rung=RUNG_NO_CREDIT_MIN),  # no clean outcome
        _pose(W2, correct=True, anchor="ev-b", days=None),  # unknown delay: not "delayed"
        _pose(99, correct=True, anchor="ev-a"),  # a window outside the constant: ignored
    ]
    out = {w["window_days"]: w for w in lg.learning_gain(poses, pretests)["windows"]}
    first = out[W1]
    assert first["posttests"] == 3 and first["n"] == 2
    assert first["pre_correct_rate"] == pytest.approx(0.5)
    assert first["post_correct_rate"] == pytest.approx(0.5)
    assert first["paired_difference"] == pytest.approx(0.0)
    assert (first["improved"], first["same"], first["worse"]) == (1, 0, 1)
    assert first["delayed"]["n"] == 1 and first["delayed"]["improved"] == 1
    second = out[W2]
    assert second["n"] == 1 and second["posttests"] == 1 and second["same"] == 1
    assert second["delayed"]["n"] == 0 and second["delayed"]["pre_correct_rate"] is None
    assert set(out) == set(POSTTEST_WINDOWS_DAYS)


def test_the_delayed_stratum_starts_at_its_threshold():
    pretests = {"ev-1": False}
    at = lg.learning_gain([_pose(days=float(POSTTEST_DELAYED_MIN_DAYS))], pretests)
    below = lg.learning_gain([_pose(days=POSTTEST_DELAYED_MIN_DAYS - 0.01)], pretests)
    assert at["windows"][0]["delayed"]["n"] == 1
    assert below["windows"][0]["delayed"]["n"] == 0 and below["windows"][0]["n"] == 1


def test_beliefs_never_enter_the_report():
    """Never p_known: belief columns on the rows change nothing."""
    pretests = {"ev-1": True}
    plain = lg.learning_gain([_pose(correct=False)], pretests)
    with_beliefs = lg.learning_gain(
        [{**_pose(correct=False), "p_known": 0.99, "p_before": 0.99, "p_after": 0.99}], pretests
    )
    assert plain == with_beliefs
    assert plain["windows"][0]["worse"] == 1
