"""Spec §13 A122 (Bug 2): a novice without the prerequisite gets the worked
example FIRST (H4), then H5, then near-transfer (§3.3's ceiling row).

* A concept with NO prerequisite edge has prerequisite status UNKNOWN, never
  proficient, and takes the "prerequisite not known" row.
* policy.attempt_first is the one decision point: the novice band format of
  every model turn, which item opens on the worked example, and the first
  hint's rung all read it.
* The worked example is the ordinary H4 hint turn — the leak-checked
  deterministic sibling (template, no model) when one exists, else the deep
  tier under the served leak guards — unlocked with no attempt before it.
  H5 keeps the attempt + dwell gate; the next item on the concept is the
  near-transfer, attempted first.

Route tests use the shared hermetic harness of tests/test_learn_loop_routes.py.
No DB, no model.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.loop_tutor import NOVICE_WORKED_FIRST_FORMAT, _BAND_FORMATS, phase_prefix
from learning import policy
from learning.ladder import Rung, intent
from learning.learner_state import LearnerState
from learning.params import BAND_DEVELOP_MAX, BKT_L0, RUNG_NO_CREDIT_MIN
from learning.policy import CeilingReason, LearnerView, StepState
from services.loop.learner import _prereq_proficient as REAL_PREREQ_PROFICIENT
from tests import test_learn_loop_routes as routes
from tests.split_patches import patch_loop

gate_on, no_rate_limit, seams = routes.gate_on, routes.no_rate_limit, routes.seams

NOVICE_P = 0.1


def _view(band="novice", prereq=False, p=NOVICE_P) -> LearnerView:
    return LearnerView(
        p_known=p, band=band, prereq_proficient=prereq, unassisted_next=None, opps=0,
        streak_unassisted=0,
    )


# ── policy: one decision point ───────────────────────────────────────────────


def test_attempt_first_is_false_only_for_a_novice_without_the_prerequisite():
    assert policy.attempt_first(_view("novice", prereq=False)) is False
    assert policy.attempt_first(_view("novice", prereq=True)) is True
    assert policy.attempt_first(_view("develop", prereq=False, p=0.5)) is True
    assert policy.attempt_first(_view("profic", prereq=False, p=0.9)) is True


def test_the_first_item_opens_on_the_worked_example_the_next_is_near_transfer():
    novice = _view()
    assert policy.opens_on_worked_example(novice, shown_on_concept=False) is True
    assert policy.opens_on_worked_example(novice, shown_on_concept=True) is False
    assert policy.opens_on_worked_example(_view(prereq=True), shown_on_concept=False) is False
    assert policy.opens_on_worked_example(_view("develop", p=0.5), shown_on_concept=False) is False


def test_worked_example_rung_unlocks_h4_first_and_nothing_after():
    novice = _view()
    fresh = StepState("qh")
    assert policy.worked_example_rung(novice, fresh, worked_first=True) is Rung.H4
    assert policy.worked_example_rung(novice, fresh, worked_first=False) is None
    assert policy.worked_example_rung(novice, StepState("qh", rung=Rung.H4), worked_first=True) is None
    # exam mode's H1 ceiling never admits the jump; nor a learner who left the row
    assert policy.worked_example_rung(novice, StepState("qh", exam_mode=True), worked_first=True) is None
    assert policy.worked_example_rung(_view(prereq=True), fresh, worked_first=True) is None
    assert policy.worked_example_rung(_view("develop", p=0.5), fresh, worked_first=True) is None


def test_the_ceiling_rows_for_an_unknown_prerequisite_are_the_not_known_rows():
    """UNKNOWN (no edge) maps to prereq_proficient False: worked example first
    (H4 at no failed attempt), then H5 — the §3.3 'not known' row, unchanged."""
    unknown = _view(prereq=policy.prerequisite_status([]) is policy.PrerequisiteStatus.PROFICIENT)
    assert policy.ceiling_with_reason(unknown, StepState("q")) == (Rung.H4, CeilingReason.NOVICE_WORKED_FIRST)
    after = StepState("q", genuine_attempts=1)
    assert policy.ceiling_with_reason(unknown, after) == (Rung.H5, CeilingReason.NOVICE_PREREQ_GAP)


# ── the route's prerequisite status ──────────────────────────────────────────


def _states(**p):
    def read(user_id, node_ids, **kw):
        return {
            n: LearnerState(user_id=user_id, node_id=n, p_known=p[n], exists=True)
            for n in node_ids
            if n in p
        }

    return read


@pytest.mark.parametrize(
    "edges,p,expected",
    [
        ([], {}, False),  # no prerequisite edge: UNKNOWN, never proficient
        ([("node-1", "node-2")], {}, False),  # node-1 is only a prerequisite OF another node
        ([("node-0", "node-1")], {"node-0": BAND_DEVELOP_MAX}, True),
        ([("node-0", "node-1")], {"node-0": BAND_DEVELOP_MAX - 0.01}, False),
        ([("node-0", "node-1")], {}, BKT_L0 >= BAND_DEVELOP_MAX),  # no row: the prior
        ([("node-0", "node-1"), ("node-9", "node-1")], {"node-0": 0.9, "node-9": 0.2}, False),
    ],
)
def test_prereq_proficient_is_true_only_for_a_known_proficient_prerequisite(edges, p, expected):
    with (
        patch_loop("_prerequisite_edges", return_value=edges),
        patch_loop("read_states", side_effect=_states(**p)),
    ):
        assert REAL_PREREQ_PROFICIENT("u1", "node-1") is expected


# ── the novice band format (agents/loop_tutor.py: format selection only) ─────


def test_phase_prefix_selects_the_novice_format_by_attempt_first():
    worked = phase_prefix(phase="teach", band="novice", ceiling=Rung.H4, attempt_first=False)
    assert NOVICE_WORKED_FIRST_FORMAT in worked and _BAND_FORMATS["novice"] not in worked
    plain = phase_prefix(phase="teach", band="novice", ceiling=Rung.H4)
    assert _BAND_FORMATS["novice"] in plain and NOVICE_WORKED_FIRST_FORMAT not in plain
    with pytest.raises(ValueError):
        phase_prefix(phase="teach", band="develop", ceiling=Rung.H3, attempt_first=False)


def test_the_worked_first_format_never_reads_as_another_phase_to_the_e2e_handlers():
    from agents.function_handlers_e2e import E2E_LOOP_PHASE_PATTERNS

    for pattern in E2E_LOOP_PHASE_PATTERNS.values():
        assert pattern not in NOVICE_WORKED_FIRST_FORMAT


def test_a_novice_teach_turn_without_the_prerequisite_is_told_worked_example_first(gate_on, seams):
    seams.store["doc"] = routes._plan_state()
    seams.p_known["node-1"] = NOVICE_P
    agent, seen = routes._json_agent()
    with (
        patch_loop("_prereq_proficient", REAL_PREREQ_PROFICIENT),
        patch_loop("_prerequisite_edges", return_value=[]),  # zero edges
        patch_loop("loop_tutor_agent", agent),
        patch_loop("record_agent_usage", side_effect=lambda r, **k: r),
    ):
        body = routes.client.post(
            "/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "explain"}
        ).json()
    assert NOVICE_WORKED_FIRST_FORMAT in seen["msg"]
    assert _BAND_FORMATS["novice"] not in seen["msg"]
    assert body["ceiling"] == int(Rung.H4)  # NOVICE_WORKED_FIRST: the not-known row
    assert seams.ceiling.call_args.args[0].prereq_proficient is False


def test_a_novice_teach_turn_with_a_proficient_prerequisite_stays_attempt_first(gate_on, seams):
    seams.store["doc"] = routes._plan_state()
    seams.p_known["node-1"] = NOVICE_P
    seams.p_known["node-0"] = 0.9
    agent, seen = routes._json_agent()
    with (
        patch_loop("_prereq_proficient", REAL_PREREQ_PROFICIENT),
        patch_loop("_prerequisite_edges", return_value=[("node-0", "node-1")]),
        patch_loop("loop_tutor_agent", agent),
        patch_loop("record_agent_usage", side_effect=lambda r, **k: r),
    ):
        body = routes.client.post(
            "/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "explain"}
        ).json()
    assert _BAND_FORMATS["novice"] in seen["msg"] and NOVICE_WORKED_FIRST_FORMAT not in seen["msg"]
    assert body["ceiling"] == int(Rung.H5)  # NOVICE_PREREQ_OK


# ── activation: which item opens on the worked example ───────────────────────


def _check_next():
    r = routes.client.post("/api/learn/loop/check/next", json={"session_id": "s1", "user_id": "u1"})
    assert r.status_code == 200, r.text
    return r.json()


def test_zero_edges_make_a_novices_first_item_open_on_the_worked_example(gate_on, seams):
    seams.store["doc"] = routes._plan_state()
    seams.p_known["node-1"] = NOVICE_P
    seams.list_items.return_value = [routes.ITEM]
    with (
        patch_loop("_prereq_proficient", REAL_PREREQ_PROFICIENT),
        patch_loop("_prerequisite_edges", return_value=[]),
    ):
        body = _check_next()
    assert body["check"]["worked_first"] is True
    step = seams.store["doc"]["steps"][routes.ITEM.question_hash]
    assert step["worked_first"] is True and step["rung"] == int(Rung.H0)  # nothing granted yet


@pytest.mark.parametrize(
    "p,edges,parent_p",
    [
        (NOVICE_P, [("node-0", "node-1")], 0.9),  # novice, prerequisite proficient
        (0.5, [], None),  # develop: attempt-first whatever the prerequisite
    ],
)
def test_other_learners_get_an_ordinary_pose(gate_on, seams, p, edges, parent_p):
    seams.store["doc"] = routes._plan_state()
    seams.p_known["node-1"] = p
    if parent_p is not None:
        seams.p_known["node-0"] = parent_p
    seams.list_items.return_value = [routes.ITEM]
    with (
        patch_loop("_prereq_proficient", REAL_PREREQ_PROFICIENT),
        patch_loop("_prerequisite_edges", return_value=edges),
    ):
        body = _check_next()
    assert "worked_first" not in body["check"]
    assert "worked_first" not in seams.store["doc"]["steps"][routes.ITEM.question_hash]


@pytest.mark.parametrize("earlier_rung,expected", [(int(Rung.H4), False), (int(Rung.H2), True)])
def test_the_item_after_a_shown_worked_example_is_the_near_transfer(gate_on, seams, earlier_rung, expected):
    seams.store["doc"] = routes._plan_state(
        concept_checks=1,
        steps={"qh-old": routes._step(check_item_id="item-old", rung=earlier_rung, worked_first=True,
                                      graded_at=routes.NOW - 50, feedback_given=True)},
    )
    seams.p_known["node-1"] = NOVICE_P
    seams.prereq.return_value = False
    seams.list_items.return_value = [routes.ITEM]
    body = _check_next()
    assert ("worked_first" in body["check"]) is expected
    assert (seams.store["doc"]["steps"][routes.ITEM.question_hash].get("worked_first") is True) is expected


def test_a_teach_turn_activation_carries_the_worked_example_flag(gate_on, seams):
    from learning.params import LOOP_TEACH_TURNS_BEFORE_CHECK

    seams.store["doc"] = routes._plan_state(teach_turns=LOOP_TEACH_TURNS_BEFORE_CHECK - 1)
    seams.p_known["node-1"] = NOVICE_P
    seams.prereq.return_value = False
    seams.list_items.return_value = [routes.ITEM]
    agent, _ = routes._json_agent()
    with (
        patch_loop("loop_tutor_agent", agent),
        patch_loop("record_agent_usage", side_effect=lambda r, **k: r),
    ):
        body = routes.client.post(
            "/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "go on"}
        ).json()
    assert body["check"]["worked_first"] is True


# ── /hint: the worked example comes first; H5 keeps the gate ─────────────────


def _hint():
    r = routes.client.post("/api/learn/loop/hint", json={"session_id": "s1", "user_id": "u1", "question_hash": "qh-1"})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def worked(gate_on, seams):
    """qh-1 active, opened on the worked example, for a novice whose
    prerequisite is not known; no attempt yet, posed just now."""
    seams.store["doc"] = routes._state(rung=0, worked_first=True, first_shown_at=routes.NOW)
    seams.p_known["node-1"] = NOVICE_P
    seams.prereq.return_value = False
    return seams


def test_the_first_hint_is_the_worked_example_with_no_attempt_before_it(worked):
    with patch_loop("record_help") as help_ledger:
        assert _hint() == {"rung": int(Rung.H4), "intent": intent(Rung.H4)}
    entry = worked.store["doc"]["steps"]["qh-1"]
    assert entry["rung"] == int(Rung.H4) and entry["last_rung_at"] == routes.NOW
    assert entry["rungs"] == [{"rung": int(Rung.H4), "at": routes.NOW}]
    # A93: recorded in the help ledger before its text is served
    assert help_ledger.call_args.args == ("u1", "qh-1", int(Rung.H4))


def test_after_the_worked_example_h5_keeps_the_attempt_and_dwell_gate(worked):
    _hint()
    assert _hint() == {"denied": "no_genuine_attempt"}  # nothing after H4 is free
    entry = worked.store["doc"]["steps"]["qh-1"]
    later = routes.NOW + 30
    entry.update(attempted_at=[later - 1], attempts=1)  # a failed genuine attempt after H4
    with patch_loop("_now_s", return_value=later):
        assert _hint() == {"rung": int(Rung.H5), "intent": intent(Rung.H5)}
        entry = worked.store["doc"]["steps"]["qh-1"]
        entry.update(attempted_at=[later - 1, later + 20], attempts=2)
    with patch_loop("_now_s", return_value=later + 60):
        assert _hint() == {"denied": "ceiling"}  # §3.3: the not-known novice row stops at H5


def test_past_the_worked_example_the_gate_denies_before_any_read(worked):
    """/hint carries no rate limit, so a denied request stays as cheap as before
    A122: once the worked example is granted (H4), the ordinary gate answers
    before any item, node, learner-state or prerequisite read."""
    _hint()
    for mock in (worked.item, worked.node, worked.read_states, worked.prereq):
        mock.reset_mock()
    assert _hint() == {"denied": "no_genuine_attempt"}
    for mock in (worked.item, worked.node, worked.read_states, worked.prereq):
        mock.assert_not_called()


@pytest.mark.parametrize("change", ["exam", "develop", "flag_off"])
def test_without_the_worked_example_row_the_ordinary_gate_answers(worked, change):
    if change == "exam":
        worked.store["doc"]["steps"]["qh-1"]["exam_mode"] = True
    elif change == "develop":
        worked.p_known["node-1"] = 0.5
    else:
        worked.store["doc"]["steps"]["qh-1"].pop("worked_first")
    assert _hint() == {"denied": "no_genuine_attempt"}
    assert worked.store["doc"]["steps"]["qh-1"]["rung"] == 0


def test_the_worked_example_is_the_leak_checked_sibling_template(worked):
    """H4 per A17: a stepwise isomorph's prompt and reference, leak-checked
    against the ACTIVE item's answer forms before it is served, no model; the
    sibling is revealed (never posed later) and ledgered as a worked answer."""
    _hint()
    shown = routes._sibling(
        "qh-9", "What does sum(0) return?", "An empty sum is 0, the identity for addition.", "0"
    )
    worked.list_items.return_value = [routes.ITEM, shown]
    never = MagicMock(side_effect=AssertionError("a leak-clean worked example needs no model"))
    with (
        patch_loop("loop_tutor_agent", MagicMock(run=never)),
        patch_loop("record_help") as help_ledger,
    ):
        body = routes.client.post(
            "/api/learn/loop/action", json={"session_id": "s1", "user_id": "u1", "action_type": "hint"}
        ).json()
    assert body["tier"] == "none" and body["phase"] == "hint"
    assert body["reply"] == f"{shown.prompt}\n\n{shown.reference_answer}"
    assert routes.ITEM.final_answer not in body["reply"]
    assert worked.detect.call_args.kwargs == {
        "reference": routes.ITEM.reference_answer,
        "emitted": body["reply"],
        "rung": Rung.H4,
        "final_answer": routes.ITEM.final_answer,
        "canonical_answer": None,
        "correct_option": None,
    }
    assert worked.store["doc"]["revealed"] == ["qh-9"]
    assert ("u1", "qh-9", RUNG_NO_CREDIT_MIN) in [c.args for c in help_ledger.call_args_list]


def test_a_leaking_sibling_is_never_the_worked_example(worked):
    """A sibling whose text states the active item's final answer is not
    served below the hard level: the deep tier writes H4 under the served
    leak guard instead, and nothing is revealed."""
    _hint()
    leaky = routes._sibling(
        "qh-8", "Why does fact(0) stop?", f"Because {routes.ITEM.final_answer} when n is 0.", "1"
    )
    worked.list_items.return_value = [routes.ITEM, leaky]
    agent, _ = routes._json_agent("Here is a different recursion, worked step by step.")
    with (
        patch_loop("loop_tutor_agent", agent),
        patch_loop("record_agent_usage", side_effect=lambda r, **k: r),
    ):
        body = routes.client.post(
            "/api/learn/loop/action", json={"session_id": "s1", "user_id": "u1", "action_type": "hint"}
        ).json()
    assert body["tier"] == "deep"  # §3.5: H4 with no usable sibling
    assert leaky.reference_answer not in body["reply"] and routes.ITEM.final_answer not in body["reply"]
    assert "revealed" not in worked.store["doc"]
    assert worked.model_tier.call_args.kwargs["deterministic_payload"] is False


def test_status_says_the_worked_example_is_owed_only_until_it_is_granted(worked):
    st = routes.client.get("/api/learn/loop/status", params={"user_id": "u1", "session_id": "s1"}).json()
    assert st["check"]["worked_first"] is True
    _hint()
    st = routes.client.get("/api/learn/loop/status", params={"user_id": "u1", "session_id": "s1"}).json()
    assert "worked_first" not in st["check"]
