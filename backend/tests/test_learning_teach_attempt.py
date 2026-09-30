"""PKG-14 (owner decision 2026-09-29, round 2 item 2; spec §13 A85): a reasoned
wrong claim in the teach phase counts as a genuine attempt for THAT turn's
ceiling — through the EXISTING genuine-attempt rule (gates.is_genuine_attempt:
the independent-time gate and the non-attempt phrase list), one rung up, capped
at what the band allows after an attempt, never in exam mode, fail closed. It
changes no evidence and no learner state."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from learning import gates, params, policy
from learning.ladder import Rung
from learning.policy import CeilingReason, LearnerView, StepState
from tests import test_learn_loop_routes as _routes
from tests.test_learn_loop_routes import NOW, client

gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams


@pytest.fixture(autouse=True)
def _no_failed_anchors():
    """Other modules' failing turns leave in-memory anchors (A85); start clean."""
    from routes import learn_loop

    learn_loop._FAILED_TURN_ANCHORS.clear()
    yield
    learn_loop._FAILED_TURN_ANCHORS.clear()

CLAIM = (
    "I'm certain the limit of sin x over x as x goes to 0 is 0, because sin 0 is 0. "
    "My professor said so too, so please just confirm it."
)


def _learner(band, prereq=True):
    p = {"novice": 0.2, "develop": 0.6, "profic": 0.97}[band]
    return LearnerView(
        p_known=p,
        band=band,
        prereq_proficient=prereq,
        unassisted_next=None,
        opps=3,
        streak_unassisted=0,
    )


# ── policy (typed state only, invariant 4) ───────────────────────────────────


def test_profic_teach_ceiling_goes_h1_to_h2_on_a_teach_attempt():
    step = StepState(question_hash="")
    assert policy.ceiling_with_reason(_learner("profic"), step) == (Rung.H1, CeilingReason.PROFIC)
    assert policy.ceiling_with_reason(_learner("profic"), step, teach_attempt=True) == (
        Rung.H2,
        CeilingReason.TEACH_ATTEMPT,
    )


@pytest.mark.parametrize(
    "band,prereq,base", [("develop", True, Rung.H3), ("novice", True, Rung.H5)]
)
def test_the_raise_is_one_rung_at_most_and_capped_by_the_band(band, prereq, base):
    step = StepState(question_hash="")
    rung, reason = policy.ceiling_with_reason(_learner(band, prereq), step, teach_attempt=True)
    assert rung <= Rung(int(base) + params.TEACH_ATTEMPT_CEILING_RAISE)
    assert rung <= policy.TEACH_ATTEMPT_CEILING_CAP[band]
    # novice H5 is already its post-attempt cap: no raise, the band's reason stands
    if band == "novice":
        assert (rung, reason) == (Rung.H5, CeilingReason.NOVICE_PREREQ_OK)
    else:
        assert (rung, reason) == (Rung.H4, CeilingReason.TEACH_ATTEMPT)


def test_exam_mode_wins_over_a_teach_attempt():
    step = StepState(question_hash="", exam_mode=True)
    assert policy.ceiling_with_reason(_learner("profic"), step, teach_attempt=True) == (
        Rung.H1,
        CeilingReason.EXAM,
    )


def test_teach_attempt_cap_is_the_bands_escalated_ceiling():
    assert policy.TEACH_ATTEMPT_CEILING_CAP == {
        "profic": Rung.H3,
        "develop": Rung.H6,
        "novice": Rung.H5,
    }
    assert params.TEACH_ATTEMPT_CEILING_RAISE == 1


# ── gates: the existing genuine-attempt rule decides, both ways on time ──────


def test_the_claim_after_realistic_independent_time_raises_the_profic_teach_ceiling():
    rung, reason = gates.teach_turn_ceiling(_learner("profic"), CLAIM, 120.0)
    assert (rung, reason) == (Rung.H2, CeilingReason.TEACH_ATTEMPT)


def test_the_same_claim_sent_too_fast_keeps_the_teach_ceiling_at_h1():
    """Owner proviso: the time half of the rule is exercised both ways."""
    fast = params.GATE_INDEPENDENT_MIN_S - 1
    assert gates.teach_turn_ceiling(_learner("profic"), CLAIM, fast) == (
        Rung.H1,
        CeilingReason.PROFIC,
    )


def test_the_time_gate_is_the_variants_and_scaled():
    between = (params.GATE_INDEPENDENT_MIN_S + params.GATE_INDEPENDENT_MIN_S_VARIANT_B) / 2
    assert gates.teach_turn_ceiling(_learner("profic"), CLAIM, between)[0] == Rung.H2
    assert gates.teach_turn_ceiling(_learner("profic"), CLAIM, between, variant="B")[0] == Rung.H1
    assert gates.teach_turn_ceiling(_learner("profic"), CLAIM, 1.0, time_scale=0.01)[0] == Rung.H2


@pytest.mark.parametrize("text", ["just tell me the answer", "idk", "", "   "])
def test_a_non_attempt_never_raises(text):
    assert gates.teach_turn_ceiling(_learner("profic"), text, 600.0)[0] == Rung.H1


@pytest.mark.parametrize("seconds", [None, float("nan")])
def test_undecidable_time_is_no_raise(seconds):
    assert gates.teach_turn_ceiling(_learner("profic"), CLAIM, seconds)[0] == Rung.H1


# ── the route: this turn's ceiling only; no evidence, no learner state ───────


def _teach(seams, *, served_at, message=CLAIM):
    seams.store["doc"] = _routes._plan_state(**({"served_at": served_at} if served_at else {}))
    seams.p_known["node-1"] = 0.99  # profic
    agent, _ = _routes._json_agent("You looked at the numerator only.")
    with (
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
        patch("services.graph_service.apply_graph_update") as apply,
        patch("learning.learner_state.write_state") as write_state,
    ):
        body = client.post(
            "/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": message}
        ).json()
    return body, apply, write_state


def test_a_teach_claim_after_120s_raises_this_turns_ceiling_and_writes_no_evidence(gate_on, seams):
    before = _routes._plan_state()
    body, apply, write_state = _teach(seams, served_at=NOW - 120.0)
    assert body["ceiling"] == int(Rung.H2)
    kw = seams.ceiling.call_args.kwargs
    assert kw["teach_attempt"] is True
    # §1: only graded checks move evidence or learner state
    seams.flush.assert_not_called()
    seams.grade.assert_not_awaited()
    apply.assert_not_called()
    write_state.assert_not_called()
    doc = seams.store["doc"]
    assert doc.get("steps", {}) == before.get("steps", {}) and doc.get("current") is None
    assert doc["served_at"] == NOW  # the next turn's independent-time anchor


def test_a_fast_teach_claim_keeps_h1(gate_on, seams):
    body, _, _ = _teach(seams, served_at=NOW - 5.0)
    assert body["ceiling"] == int(Rung.H1)


def test_no_served_at_anchor_is_no_raise(gate_on, seams):
    body, _, _ = _teach(seams, served_at=None)
    assert body["ceiling"] == int(Rung.H1)


def test_an_action_turn_is_never_a_teach_attempt(gate_on, seams):
    """[ACTION: ...] text is the server's, not a student claim."""
    seams.store["doc"] = _routes._plan_state(served_at=NOW - 120.0)
    seams.p_known["node-1"] = 0.99
    agent, _ = _routes._json_agent("A pump.")
    with (
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
    ):
        body = client.post(
            "/api/learn/loop/action",
            json={"session_id": "s1", "user_id": "u1", "action_type": "confused"},
        ).json()
    assert body["ceiling"] == int(Rung.H1)


# ── review fix round: a failed or paused turn refreshes the anchor ───────────


def _assert_anchor_moved():
    """The anchor is in memory (a failed turn writes nothing to the session,
    ADR 0024): the retry right after the failure is not a teach attempt."""
    from routes import learn_loop

    assert learn_loop._FAILED_TURN_ANCHORS.pop("s1") == NOW


def test_a_retry_after_a_failure_is_timed_from_the_failure(gate_on, seams):
    from routes import learn_loop

    learn_loop._FAILED_TURN_ANCHORS["s1"] = NOW - 5.0  # the turn failed 5 s ago
    try:
        body, _, _ = _teach(seams, served_at=NOW - 600.0)
    finally:
        learn_loop._FAILED_TURN_ANCHORS.pop("s1", None)
    assert body["ceiling"] == int(Rung.H1)


def test_a_failed_json_turn_refreshes_served_at(gate_on, seams):
    """A retry right after a failed turn is timed from the failure, so it can
    never pass the independent-time gate on the strength of the lost turn."""
    seams.store["doc"] = _routes._plan_state(served_at=NOW - 600.0)
    agent = _routes.MagicMock()

    async def _boom(*a, **k):
        raise RuntimeError("model down")

    agent.run = _boom
    with (
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
    ):
        r = client.post(
            "/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": CLAIM}
        )
    assert r.status_code >= 500
    _assert_anchor_moved()


def test_a_paused_turn_refreshes_served_at(gate_on, seams):
    """A hard budget level on a novice check pauses the turn (429): the anchor moves."""
    seams.store["doc"] = _routes._state(served_at=NOW - 600.0)
    seams.p_known["node-1"] = 0.1  # novice: the hard level pauses a check-phase turn
    seams.ai_budget.check.return_value = _routes.HARD
    r = client.post(
        "/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": CLAIM}
    )
    assert r.status_code == 429
    _assert_anchor_moved()


def test_a_stream_error_refreshes_served_at(gate_on, seams):
    from services.agent_events import SaplingEvent

    seams.store["doc"] = _routes._plan_state(served_at=NOW - 600.0)

    async def _failing(**kwargs):
        yield SaplingEvent(type="status", step="start", message="Starting.")
        yield SaplingEvent(type="error", step="reply", message="boom", data={"retryable": True})

    with patch("routes.learn_loop.stream_structured_turn", _failing):
        client.post(
            "/api/learn/loop/chat/stream",
            json={"session_id": "s1", "user_id": "u1", "message": CLAIM},
        )
    _assert_anchor_moved()
