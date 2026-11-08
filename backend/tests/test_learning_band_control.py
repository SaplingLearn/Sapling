"""Spec §13 A122 (Bug 1): the §3.3 band controller and wheel-spin detector run
after every graded in-session check, and their verdict drives what is posed
next — the next item's difficulty, stop / advance, the prerequisite-repair
cursor — and emits zpd.band_adjust / zpd.wheelspin with the spec §6 payloads.
The controller never changes how much help a turn gets: ceilings, gates and
leak guards are untouched.

Policy tests run the pure layer; route tests drive /check/answer (and the
feedback turn it serves) through the shared hermetic harness of
tests/test_learn_loop_routes.py, with the concept's evidence window and
learner state patched at the route seam. No DB, no model.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from learning import params, policy
from learning.learner_state import LearnerState
from learning.ladder import Rung
from learning.policy import BandAction, CursorMove, Opportunity, Prerequisite
from tests import test_learn_loop_routes as routes

gate_on, no_rate_limit, seams = routes.gate_on, routes.no_rate_limit, routes.seams

HIT = Opportunity(correct=True, assisted=False, max_rung=0, p_before=0.5, p_after=0.6)
MISS = Opportunity(correct=False, assisted=False, max_rung=0, p_before=0.6, p_after=0.4)
HELPED = Opportunity(correct=True, assisted=True, max_rung=2, p_before=0.5, p_after=0.55)
STEADY = Opportunity(correct=True, assisted=False, max_rung=0, p_before=0.96, p_after=0.97)


# ── the pure controller ──────────────────────────────────────────────────────


def test_the_window_holds_unassisted_first_attempt_outcomes_only():
    assert policy.unassisted_first(HIT) is True
    assert policy.unassisted_first(MISS) is False
    assert policy.unassisted_first(HELPED) is False  # correct after help is not unassisted
    assert policy.unassisted_first(HIT._replace(max_rung=1)) is False  # a rung shown is help
    assert policy.unassisted_first(HIT._replace(assisted=True)) is False


@pytest.mark.parametrize(
    "window,p,opps,streak,action",
    [
        ([], 0.5, 0, 0, BandAction.HOLD),
        ([HIT] * 3, 0.5, 3, 3, BandAction.HOLD),  # A40: HARDER needs 4 outcomes
        ([HIT] * 4, 0.5, 4, 4, BandAction.HARDER),
        ([HIT] * 7 + [MISS], 0.5, 8, 7, BandAction.HOLD),  # 0.875 sits in the practice band
        ([MISS], 0.4, 1, 0, BandAction.EASIER_CHECK_PREREQS),
        ([HIT, MISS, HELPED], 0.4, 3, 1, BandAction.EASIER_CHECK_PREREQS),
        ([STEADY] * 16, 0.97, 16, 16, BandAction.STOP_PRACTICE),
        ([HIT] * 16, 0.97, 16, 16, BandAction.HARDER),  # the belief still moves: not stable
        ([STEADY] * 16, 0.9, 16, 16, BandAction.HARDER),  # below BKT_PROFICIENT
        ([HIT] * 6 + [MISS] * 4, 0.5, 10, 2, BandAction.WHEELSPIN),  # never a streak of 3
        ([HIT, MISS, MISS, MISS, MISS, MISS], 0.3, 6, 1, BandAction.WHEELSPIN),  # early clause
        ([HIT] * 6 + [MISS] * 4, 0.5, 10, 3, BandAction.EASIER_CHECK_PREREQS),
    ],
)
def test_band_verdict_follows_the_spec_table(window, p, opps, streak, action):
    verdict = policy.band_verdict(window, p_known=p, opps=opps, max_streak_unassisted=streak)
    assert verdict.action is action
    assert verdict.wheelspin is (action is BandAction.WHEELSPIN)


def test_band_verdict_reads_the_newest_two_windows_and_uses_the_live_rate():
    old_misses = [MISS] * 30
    verdict = policy.band_verdict(
        old_misses + [STEADY] * 16, p_known=0.97, opps=46, max_streak_unassisted=16
    )
    assert verdict.action is BandAction.STOP_PRACTICE  # 30 older misses are outside WINDOW_KEEP
    assert verdict.rate == 1.0 and verdict.n == params.BAND_WINDOW
    assert verdict.full_windows == params.BAND_CONTROL_STOP_WINDOWS
    # wheelspin's clause 2 reads the window's live rate, not a stored (nightly) one
    low = policy.band_verdict([MISS] * 6, p_known=0.2, opps=6, max_streak_unassisted=0)
    assert low.wheelspin is True and low.rate == 0.0


def test_stable_belief_needs_a_small_last_move():
    assert policy.stable_belief([]) is False
    assert policy.stable_belief([HIT._replace(p_before=None)]) is False
    small = params.BAND_CONTROL_STABLE_DELTA / 2
    assert policy.stable_belief([HIT._replace(p_before=0.9, p_after=0.9 + small)]) is True
    big = params.BAND_CONTROL_STABLE_DELTA
    assert policy.stable_belief([HIT._replace(p_before=0.9, p_after=0.9 + big)]) is False
    assert params.BAND_CONTROL_STABLE_DELTA == params.PROBE_STOP_DELTA


def test_htc_k_is_the_mean_rung_over_the_newest_correct_opportunities():
    assert policy.hints_to_criterion([]) is None
    assert policy.hints_to_criterion([MISS, MISS]) is None
    window = [HELPED._replace(max_rung=6)] + [HELPED, HIT, MISS, HELPED._replace(max_rung=4), HIT]
    # the newest HTC_K_WINDOW (5): HELPED(2), HIT(0), MISS, H4, HIT(0) → (2 + 0 + 4 + 0) / 4
    assert params.HTC_K_WINDOW == 5
    assert policy.hints_to_criterion(window) == pytest.approx(1.5)


def test_next_difficulty_steps_one_level_and_clamps():
    lo, mid, hi = params.CHECK_ITEM_DIFFICULTIES
    assert policy.next_difficulty(BandAction.HARDER, lo) == mid
    assert policy.next_difficulty(BandAction.HARDER, hi) == hi
    assert policy.next_difficulty(BandAction.EASIER_CHECK_PREREQS, hi) == mid
    assert policy.next_difficulty(BandAction.EASIER_CHECK_PREREQS, lo) == lo
    for action in (BandAction.HOLD, BandAction.STOP_PRACTICE, BandAction.WHEELSPIN):
        assert policy.next_difficulty(action, mid) is None
    assert params.BAND_CONTROL_DIFFICULTY_STEP == 1


def test_prerequisite_status_is_unknown_without_edges():
    S = policy.PrerequisiteStatus
    assert policy.prerequisite_status([]) is S.UNKNOWN
    edge = params.BAND_DEVELOP_MAX
    assert policy.prerequisite_status([Prerequisite("a", edge), Prerequisite("b", 0.99)]) is S.PROFICIENT
    assert policy.prerequisite_status([Prerequisite("a", edge - 0.01)]) is S.NOT_PROFICIENT


def test_repair_target_is_the_weakest_unproficient_prerequisite():
    assert policy.repair_target([]) is None
    assert policy.repair_target([Prerequisite("a", 0.9)]) is None
    got = policy.repair_target(
        [Prerequisite("c", 0.6), Prerequisite("b", 0.2), Prerequisite("a", 0.2), Prerequisite("d", 0.95)]
    )
    assert got == Prerequisite("a", 0.2)  # the lowest belief; ties by node id


@pytest.mark.parametrize(
    "action,available,move",
    [
        (BandAction.STOP_PRACTICE, True, CursorMove.ADVANCE),
        (BandAction.STOP_PRACTICE, False, CursorMove.ADVANCE),
        (BandAction.WHEELSPIN, True, CursorMove.REPAIR_REPLACE),
        (BandAction.WHEELSPIN, False, CursorMove.ADVANCE),
        (BandAction.EASIER_CHECK_PREREQS, True, CursorMove.REPAIR_RETURN),
        (BandAction.EASIER_CHECK_PREREQS, False, CursorMove.STAY),
        (BandAction.HARDER, True, CursorMove.STAY),
        (BandAction.HOLD, True, CursorMove.STAY),
    ],
)
def test_cursor_move_table(action, available, move):
    assert policy.cursor_move(action, repair_available=available) is move


def test_every_adjusting_verdict_has_a_spec_trigger():
    from typing import get_args

    assert set(policy.BAND_TRIGGERS) == set(BandAction) - {BandAction.HOLD}
    assert set(policy.BAND_TRIGGERS.values()) == set(get_args(policy.BandTrigger))


# ── the store's window read ──────────────────────────────────────────────────


def test_opportunity_window_is_owner_scoped_newest_last_and_bounded(monkeypatch):
    from learning import loop_state_store

    calls = []
    rows_newest_first = [
        {"correct": True, "assisted": False, "max_rung": 0, "p_before": 0.5, "p_after": 0.6},
        {"correct": False, "assisted": True, "max_rung": 2, "p_before": 0.6, "p_after": 0.3},
    ]

    class _Table:
        def select(self, cols, **kw):
            calls.append((cols, kw))
            return rows_newest_first

    monkeypatch.setattr(loop_state_store, "table", lambda name: calls.append(name) or _Table())
    got = loop_state_store.opportunity_window("u1", "node-1")
    assert calls[0] == "node_mastery_events"
    cols, kw = calls[1]
    assert "graph_nodes!inner(user_id)" in cols
    assert kw["filters"] == {
        "graph_nodes.user_id": "eq.u1",
        "node_id": "eq.node-1",
        "event_type": "eq.evidence",
        "question_hash": "not.is.null",
    }
    assert kw["order"] == "created_at.desc,evidence_seq.desc.nullslast,id.desc"
    assert kw["limit"] == policy.WINDOW_KEEP
    assert got == [
        Opportunity(False, True, 2, 0.6, 0.3),
        Opportunity(True, False, 0, 0.5, 0.6),
    ]  # newest LAST


def test_opportunity_window_fails_soft_and_never_reads_unknown_help_as_none(monkeypatch):
    from learning import loop_state_store

    class _Broken:
        def select(self, *a, **k):
            raise RuntimeError("down")

    monkeypatch.setattr(loop_state_store, "table", lambda name: _Broken())
    assert loop_state_store.opportunity_window("u1", "n") is None

    class _Odd:
        def select(self, *a, **k):
            return [{"correct": None, "assisted": None, "max_rung": None}]

    monkeypatch.setattr(loop_state_store, "table", lambda name: _Odd())
    [op] = loop_state_store.opportunity_window("u1", "n")
    assert op.correct is False and op.assisted is True and policy.unassisted_first(op) is False


# ── the route: verdict after a graded check, applied at feedback ─────────────


def _learner_reads(seams, *, p=0.5, opps=4, streak=0, prereqs=None):
    """read_states for node-1 (the checked concept) and its prerequisites."""
    prereqs = prereqs or {}

    def read(user_id, node_ids, **kw):
        out = {}
        for n in node_ids:
            if n == "node-1":
                out[n] = LearnerState(
                    user_id=user_id, node_id=n, p_known=p, opps=opps,
                    max_streak_unassisted=streak, n_strong_unassisted=1, exists=True,
                )
            elif n in prereqs:
                out[n] = LearnerState(user_id=user_id, node_id=n, p_known=prereqs[n], exists=True)
        return out

    seams.read_states.side_effect = read


def _answer(seams, window, *, correct=True, edges=()):
    """POST /check/answer on qh-1 (graded `correct` or not) and serve its
    feedback turn, with the concept's evidence window patched to `window`."""
    seams.grade.return_value = routes.CORRECT if correct else routes.WRONG
    agent, _ = routes._json_agent()
    with (
        patch("routes.learn_loop.opportunity_window", return_value=window) as read_window,
        patch("routes.learn_loop._prerequisite_edges", return_value=list(edges)),
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
    ):
        r = routes.client.post(
            "/api/learn/loop/check/answer",
            json={"session_id": "s1", "user_id": "u1", "question_hash": "qh-1", "answer": "n == 0"},
        )
    assert r.status_code == 200, r.text
    return r, read_window


@pytest.fixture
def loop(gate_on, seams):
    """qh-1 (difficulty 2, node-1) active on the plan [node-1, node-2]."""
    st = routes._plan_state(teach_turns=2)
    st.update(routes._state())
    seams.store["doc"] = st
    return seams


def _band_events(seams):
    return [c.kwargs for c in seams.zpd.emit_zpd_band_adjust.call_args_list]


def _wheel_events(seams):
    return [c.kwargs for c in seams.zpd.emit_zpd_wheelspin.call_args_list]


def test_harder_steps_the_next_item_up_and_keeps_the_concept(loop):
    _learner_reads(loop, p=0.6)
    _, read_window = _answer(loop, [HIT] * 4)
    read_window.assert_called_once_with("u1", "node-1")
    doc = loop.store["doc"]
    assert doc["steps"]["qh-1"]["band_control"] == {
        "action": "harder", "difficulty": 3, "repair": None,
        "ceiling_delta": -1, "ceiling": int(Rung.H2),  # develop H3, one rung down
    }
    assert doc["band_difficulty"] == {"node-1": 3}
    assert doc["band_ceiling"] == {"node-1": -1}
    assert doc["concept"] == "node-1" and doc["plan"]["cursor"] == 0 and doc["concept_checks"] == 1
    [ev] = _band_events(loop)
    assert ev["direction"] is BandAction.HARDER and ev["trigger"] == "high"
    assert ev["user_id"] == "u1" and ev["request_id"]
    assert ev["window_stats"] == {
        "rate": 1.0, "n": 4, "full_windows": 0, "stable": False, "p_known": 0.6, "opps": 4,
        "difficulty": 2, "next_difficulty": 3, "repair": False,
    }
    assert set(ev) == {"user_id", "request_id", "direction", "trigger", "window_stats", "ceiling_delta"}
    assert ev["ceiling_delta"] == -1
    assert _wheel_events(loop) == []
    # the next activation on node-1 targets the controller's difficulty, not the band's
    loop.list_items.return_value = [routes.ITEM.model_copy(update={"question_hash": "qh-2", "id": "item-2"})]
    r = routes.client.post("/api/learn/loop/check/next", json={"session_id": "s1", "user_id": "u1"})
    assert r.status_code == 200 and loop.store["doc"]["current"] == "qh-2"
    assert {c.kwargs["difficulty"] for c in loop.select_item.call_args_list} == {3}


def test_easier_without_a_weak_prerequisite_lowers_the_difficulty_and_raises_the_ceiling(loop):
    _learner_reads(loop, p=0.4, prereqs={"node-0": 0.9})
    _answer(loop, [MISS], correct=False, edges=[("node-0", "node-1")])
    doc = loop.store["doc"]
    assert doc["steps"]["qh-1"]["band_control"] == {
        "action": "easier_check_prereqs", "difficulty": 1, "repair": None,
        "ceiling_delta": 1, "ceiling": int(Rung.H4),  # develop H3, one rung up
    }
    assert doc["band_difficulty"] == {"node-1": 1}
    assert doc["band_ceiling"] == {"node-1": 1}
    assert doc["concept"] == "node-1" and doc["plan"]["approved"] == ["node-1", "node-2"]
    [ev] = _band_events(loop)
    assert ev["direction"] is BandAction.EASIER_CHECK_PREREQS and ev["trigger"] == "low"
    assert ev["window_stats"]["repair"] is False and ev["window_stats"]["next_difficulty"] == 1
    assert ev["ceiling_delta"] == 1


def test_easier_with_a_weak_prerequisite_repairs_it_first_then_comes_back(loop):
    _learner_reads(loop, p=0.4, prereqs={"node-0": 0.2, "node-9": 0.5})
    _answer(loop, [MISS], correct=False, edges=[("node-0", "node-1"), ("node-9", "node-1")])
    doc = loop.store["doc"]
    assert doc["steps"]["qh-1"]["band_control"]["repair"] == "node-0"  # the weakest
    plan = doc["plan"]
    assert plan["approved"] == ["node-0", "node-1", "node-2"] and plan["cursor"] == 0
    assert plan["repairs"] == [
        {"node_id": "node-0", "for": "node-1", "action": "easier_check_prereqs"}
    ]
    assert doc["concept"] == "node-0" and doc["concept_checks"] == 0 and doc["teach_turns"] == 0
    assert _band_events(loop)[0]["window_stats"]["repair"] is True
    # the prerequisite's checks done, the cursor comes back to the concept
    from routes.learn_loop import _advance_cursor

    assert _advance_cursor(doc) is True and doc["concept"] == "node-1"


def test_a_repair_runs_once_per_concept_and_prerequisite(loop):
    doc = loop.store["doc"]
    doc["plan"]["repairs"] = [{"node_id": "node-0", "for": "node-1", "action": "easier_check_prereqs"}]
    _learner_reads(loop, p=0.4, prereqs={"node-0": 0.2})
    _answer(loop, [MISS], correct=False, edges=[("node-0", "node-1")])
    doc = loop.store["doc"]
    assert doc["concept"] == "node-1" and doc["plan"]["approved"] == ["node-1", "node-2"]
    assert doc["band_difficulty"] == {"node-1": 1}  # the easier item still applies


def test_stop_practice_hands_the_concept_to_the_scheduler(loop):
    _learner_reads(loop, p=0.97, opps=16, streak=16)
    _answer(loop, [STEADY] * 16)
    doc = loop.store["doc"]
    assert doc["steps"]["qh-1"]["band_control"] == {
        "action": "stop_practice", "difficulty": None, "repair": None,
        "ceiling_delta": 0, "ceiling": int(Rung.H1),  # confirmed profic, no clause
    }
    assert "band_ceiling" not in doc
    # one check below LOOP_CHECKS_PER_CONCEPT, yet the concept is left
    assert params.LOOP_CHECKS_PER_CONCEPT > 1
    assert doc["plan"]["cursor"] == 1 and doc["concept"] == "node-2" and doc["concept_checks"] == 0
    [ev] = _band_events(loop)
    assert ev["direction"] is BandAction.STOP_PRACTICE and ev["trigger"] == "stable_high"
    assert ev["window_stats"]["full_windows"] == 2 and ev["window_stats"]["stable"] is True


def test_wheelspin_stops_more_of_the_same_and_repairs_in_its_place(loop):
    _learner_reads(loop, p=0.3, opps=10, streak=2, prereqs={"node-0": 0.25})
    window = [HIT, MISS] * 5
    _answer(loop, window, correct=False, edges=[("node-0", "node-1")])
    doc = loop.store["doc"]
    assert doc["steps"]["qh-1"]["band_control"] == {
        "action": "wheelspin", "difficulty": None, "repair": "node-0",
        "ceiling_delta": 0, "ceiling": int(Rung.H3),  # develop, no clause
    }
    assert "band_ceiling" not in doc
    plan = doc["plan"]
    assert plan["approved"] == ["node-0", "node-2"]  # node-1 does not come back this session
    assert doc["concept"] == "node-0" and doc["concept_checks"] == 0
    assert plan["repairs"] == [{"node_id": "node-0", "for": "node-1", "action": "wheelspin"}]
    [ev] = _band_events(loop)
    assert ev["direction"] is BandAction.WHEELSPIN and ev["trigger"] == "wheelspin"
    [spin] = _wheel_events(loop)
    assert spin == {
        "user_id": "u1", "request_id": spin["request_id"], "concept_id": "node-1", "opps": 10,
        "unassisted_next": 0.5, "htc_k": 0.0, "prerequisite_ids": ["node-0"],
    }


def test_wheelspin_without_prerequisite_edges_advances_and_still_flags(loop):
    _learner_reads(loop, p=0.3, opps=10, streak=2)
    _answer(loop, [HIT, MISS] * 5, correct=False)
    doc = loop.store["doc"]
    assert doc["plan"]["cursor"] == 1 and doc["concept"] == "node-2"
    assert "repairs" not in doc["plan"]
    [spin] = _wheel_events(loop)
    assert spin["prerequisite_ids"] == [] and spin["concept_id"] == "node-1"


def test_wheelspin_in_a_goal_session_records_the_concept_attempted(loop):
    doc = loop.store["doc"]
    doc["goal"] = {"target_node_ids": ["node-2"], "text_encrypted": None}
    _learner_reads(loop, p=0.3, opps=10, streak=2, prereqs={"node-0": 0.25})
    _answer(loop, [HIT, MISS] * 5, correct=False, edges=[("node-0", "node-1")])
    plan = loop.store["doc"]["plan"]
    assert "node-1" in plan["attempted"] and "node-1" in plan["checked_nodes"]


def test_hold_stores_nothing_emits_nothing_and_counts_as_before(loop):
    _learner_reads(loop, p=0.6)
    _answer(loop, [HIT] * 7 + [MISS])
    doc = loop.store["doc"]
    assert "band_control" not in doc["steps"]["qh-1"] and "band_difficulty" not in doc
    assert doc["concept_checks"] == 1 and doc["concept"] == "node-1"
    loop.zpd.emit_zpd_band_adjust.assert_not_called()
    loop.zpd.emit_zpd_wheelspin.assert_not_called()


def test_a_failed_window_read_applies_no_verdict_and_the_grade_stands(loop):
    _learner_reads(loop, p=0.6)
    r, _ = _answer(loop, None)
    assert r.json()["graded"] is True and r.json()["verdict"] == "correct"
    doc = loop.store["doc"]
    assert "band_control" not in doc["steps"]["qh-1"]
    assert doc["concept_checks"] == 1 and doc["concept"] == "node-1"
    loop.zpd.emit_zpd_band_adjust.assert_not_called()


@pytest.mark.parametrize("failing", ["learner", "prerequisites"])
def test_a_failed_read_yields_no_verdict_rather_than_an_invented_one(failing):
    from routes.learn_loop import _band_verdict

    reads = {"learner": "routes.learn_loop.read_states", "prerequisites": "routes.learn_loop._prerequisite_edges"}
    state = {"node-1": LearnerState(user_id="u1", node_id="node-1", p_known=0.4, opps=2, exists=True)}
    with (
        patch("routes.learn_loop.opportunity_window", return_value=[MISS]),
        patch("routes.learn_loop.read_states", return_value=state),
        patch("routes.learn_loop._prerequisite_edges", return_value=[]),
        patch(reads[failing], side_effect=RuntimeError("store down")),
    ):
        assert _band_verdict("u1", "node-1", 2) is None


def test_band_verdict_reads_prerequisites_only_when_the_verdict_checks_them():
    from routes.learn_loop import _band_verdict

    state = {"node-1": LearnerState(user_id="u1", node_id="node-1", p_known=0.6, opps=4, exists=True)}
    with (
        patch("routes.learn_loop.opportunity_window", return_value=[HIT] * 4),
        patch("routes.learn_loop.read_states", return_value=state),
        patch("routes.learn_loop._prerequisite_edges") as edges,
    ):
        got = _band_verdict("u1", "node-1", 2)
    edges.assert_not_called()  # HARDER checks no prerequisite
    assert got.stored == {
        "action": "harder", "difficulty": 3, "repair": None, "ceiling_delta": -1, "ceiling": int(Rung.H2),
    }
    assert got.prerequisite_ids == []


def test_the_verdict_is_read_once_even_when_its_save_retries(loop):
    """The verdict is computed once, outside the compare-and-set mutate; a
    conflict on the save that records the grade re-applies the mutate, never
    the reads or the events."""
    _learner_reads(loop, p=0.6)

    def flush(*a, **k):  # the record save, right after the flush, loses one race
        loop.store["conflicts"] = 1
        loop.store["racer"] = lambda doc: doc.update(racer=True)
        return [{"node_id": "node-1"}]

    loop.flush.side_effect = flush
    _, read_window = _answer(loop, [HIT] * 4)
    assert read_window.call_count == 1
    assert len(_band_events(loop)) == 1
    doc = loop.store["doc"]
    assert doc["racer"] is True  # the race happened
    assert doc["steps"]["qh-1"]["band_control"]["action"] == "harder"


def test_a_verdict_on_a_concept_the_cursor_left_moves_no_cursor():
    from routes.learn_loop import _apply_band_control

    state = routes._plan_state(concept="node-2", plan={"approved": ["node-1", "node-2"], "cursor": 1})
    entry = {"node_id": "node-1", "band_control": {"action": "stop_practice", "difficulty": None, "repair": None}}
    assert _apply_band_control(state, entry) is False
    assert state["concept"] == "node-2" and state["plan"]["cursor"] == 1
    entry["band_control"] = {"action": "harder", "difficulty": 3, "repair": None}
    assert _apply_band_control(state, entry) is False
    assert state["band_difficulty"] == {"node-1": 3}


@pytest.mark.parametrize(
    "stored",
    [
        None,
        "harder",
        {"action": "sideways"},
        {"action": "harder", "difficulty": 9},
        {"action": "harder", "difficulty": True},
        {"action": "wheelspin", "repair": ""},
    ],
)
def test_a_malformed_stored_verdict_is_ignored_safely(stored):
    """A malformed field is ignored; a valid action still applies what it
    names. The ceiling clause comes from the action itself, never a stored
    number, so a bad difficulty cannot stop HARDER's one rung down."""
    from routes.learn_loop import _apply_band_control

    state = routes._plan_state()
    entry = {"node_id": "node-1", "band_control": stored}
    before = json.loads(json.dumps(state))
    moved = _apply_band_control(state, entry)
    action = stored.get("action") if isinstance(stored, dict) else None
    if action == "wheelspin":
        assert moved is True and state["concept"] == "node-2"  # no valid repair: stop and advance
    elif action == "harder":
        assert moved is False and "band_difficulty" not in state
        assert state == {**before, "band_ceiling": {"node-1": -1}}
    else:
        assert moved is False and state == before


def test_without_a_plan_the_verdict_sets_only_the_difficulty_and_the_ceiling():
    from routes.learn_loop import _apply_band_control

    state = {"phase": "teach", "concept": "node-1"}
    entry = {"node_id": "node-1", "band_control": {"action": "easier_check_prereqs", "difficulty": 1, "repair": "node-0"}}
    assert _apply_band_control(state, entry) is False
    assert state == {
        "phase": "teach", "concept": "node-1",
        "band_difficulty": {"node-1": 1}, "band_ceiling": {"node-1": 1},
    }


def test_easier_raises_the_next_items_ceiling_one_rung_and_the_gate_still_holds(loop):
    """§3.3 "unassisted_next < 0.65 → … ceiling +1 rung": after the verdict's
    feedback turn the concept's next item opens at H0 under the band's ceiling
    plus one (develop H3 → H4); the attempt/dwell gate still answers first."""
    _learner_reads(loop, p=0.5)
    _answer(loop, [MISS], correct=False)
    doc = loop.store["doc"]
    assert doc["steps"]["qh-1"]["band_control"]["ceiling"] == int(Rung.H4)
    loop.list_items.return_value = [routes.ITEM.model_copy(update={"question_hash": "qh-2", "id": "item-2"})]
    routes.client.post("/api/learn/loop/check/next", json={"session_id": "s1", "user_id": "u1"})
    new = loop.store["doc"]["steps"]["qh-2"]
    assert new["rung"] == int(Rung.H0) and new["attempts"] == 0
    st = routes.client.get("/api/learn/loop/status", params={"user_id": "u1", "session_id": "s1"}).json()
    assert st["band"] == "develop" and st["ceiling"] == int(Rung.H4)
    r = routes.client.post(
        "/api/learn/loop/hint", json={"session_id": "s1", "user_id": "u1", "question_hash": "qh-2"}
    )
    assert r.json() == {"denied": "no_genuine_attempt"}  # more help allowed, never help before effort


def test_band_control_reads_happen_after_the_flush(loop):
    """The window must hold the check just graded: it is read after flush_pending."""
    order = []
    loop.flush.side_effect = lambda *a, **k: order.append("flush") or [{"node_id": "node-1"}]
    _learner_reads(loop, p=0.6)
    window = MagicMock(side_effect=lambda *a: order.append("window") or [HIT] * 4)
    agent, _ = routes._json_agent()
    with (
        patch("routes.learn_loop.opportunity_window", window),
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
    ):
        routes.client.post(
            "/api/learn/loop/check/answer",
            json={"session_id": "s1", "user_id": "u1", "question_hash": "qh-1", "answer": "n == 0"},
        )
    assert order == ["flush", "window"]
