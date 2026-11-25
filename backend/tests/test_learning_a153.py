"""Spec §13 A153: what planning calls proficient, how the check-in ends, which
messages are attempts, what a slip is, and what the review queue decays from."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from learning import bkt, gates, params, planner
from learning.learner_next import ConceptState, learner_next
from learning.learner_state import LearnerState, planning_p
from learning.misconceptions import Attempt, slip_or_misconception
from learning.quiz_plan import weakest_ready
from learning.probe import diagnostic_summary, next_probe_item, novice_floor, probe_done
from tests.test_learning_adaptive_probe import bank, observation

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
FORMATS = {"free": "free_response"}


def learned(days: float, stability: float, p: float = params.BKT_P_MAX) -> LearnerState:
    return LearnerState(
        "u", "n", p_known=bkt.decayed_p(p, days, stability), p_at_evidence=p, exists=True
    )


# ── planning ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("stability", [params.FSRS_S0_GOOD, 12.0, 50.0])
@pytest.mark.parametrize("share", [0.0, 0.3, 0.65, 1.0])
def test_a_learned_concept_stays_proficient_until_its_review_is_due(stability, share):
    """Decay-at-read alone left proficiency at about 60% of the interval."""
    state = learned(stability * share, stability)
    assert planning_p(state) >= params.BKT_PROFICIENT
    if share == 1.0:
        assert state.p_known < params.BKT_PROFICIENT, "the decay itself is unchanged"


def test_a_concept_forgotten_below_the_profic_band_is_planned_again():
    state = learned(60, params.FSRS_S0_GOOD)
    assert state.p_known < params.BAND_DEVELOP_MAX
    assert planning_p(state) == state.p_known


@pytest.mark.parametrize("p", [0.1, 0.8, 0.9, 0.949])
def test_a_belief_never_proficient_is_never_held_proficient(p):
    assert planning_p(learned(1.0, 2.3, p)) < params.BKT_PROFICIENT


def test_a_concept_with_no_row_plans_on_the_prior():
    assert planning_p(LearnerState("u", "n")) == params.BKT_L0


def test_the_day_two_plan_teaches_new_concepts_and_keeps_dependents_open():
    states = {f"L{i}": planning_p(learned(2, params.FSRS_S0_GOOD)) for i in range(6)}
    states |= {"new-1": params.BKT_L0, "new-2": params.BKT_L0}
    fringe = planner.outer_fringe(states, [("L0", "new-1")])
    assert set(fringe) == {"new-1", "new-2"}


def test_learner_next_decides_readiness_on_the_planning_belief():
    held = learned(2, params.FSRS_S0_GOOD)
    assert held.p_known < params.BKT_PROFICIENT
    states = [
        ConceptState("base", held.p_known, planning_p=planning_p(held)),
        ConceptState("next", params.BKT_L0),
    ]
    ready = learner_next(states, [("base", "next")], NOW).ready
    assert [c.node_id for c in ready] == ["next"]
    assert ConceptState("x", 0.4).p_plan == 0.4, "a caller that passes none keeps p_known"


def test_a_course_with_no_edges_is_planned_in_the_order_of_the_material():
    """Ties used to fall to the node id, a random UUID: no order at all."""
    states = {"z-first": params.BKT_L0, "m-second": params.BKT_L0, "a-third": params.BKT_L0}
    assert planner.outer_fringe(states, []) == list(states)
    states["a-third"] = params.BKT_L0 + 0.2
    assert planner.outer_fringe(states, [])[0] == "a-third", "belief still ranks first"
    assert weakest_ready({"z": 0.35, "a": 0.35}, []) == "z"


def test_the_plan_reads_the_nodes_oldest_first():
    from services.loop import planning

    with (
        patch.object(planning, "page_all", return_value=[{"id": "z"}, {"id": "a"}]) as read,
        patch.object(planning, "read_states", return_value={}),
    ):
        assert list(planning._plan_states("u", "c")) == ["z", "a"]
    assert read.call_args.kwargs["order"] == "created_at.asc,id.asc"


# ── the check-in ─────────────────────────────────────────────────────────────


def idk(node, k):
    return observation(node, correct=False, idk=True, k=k)


def test_two_idks_on_one_strand_close_that_strand_only():
    """They used to end the whole check-in, leaving the other strands unplaced."""
    history = [idk("A", 0), observation("B", k=1), observation("C", k=2), idk("A", 3)]
    assert not novice_floor(history) and not probe_done(history, skills="ABC")
    item = next_probe_item(
        dict.fromkeys("ABC", 0.6), bank(*"ABC"), [], channel_for_format=FORMATS, history=history
    )
    assert item is not None and item.node_id in {"B", "C"}


def test_misses_at_the_easiest_level_close_their_own_strand():
    history = [observation("B", k=9)]
    history += [observation("A", difficulty=1, correct=False, k=k) for k in range(3)]
    item = next_probe_item(
        dict.fromkeys("AB", 0.6), bank(*"AB"), [], channel_for_format=FORMATS, history=history
    )
    assert item is not None and item.node_id == "B"


@pytest.mark.parametrize("nodes", ["AA", "AB"])
def test_a_student_with_nothing_right_still_leaves_early(nodes):
    """Spec §3.3's novice exit stands: repeated idk and no correct answer."""
    history = [idk(node, k) for k, node in enumerate(nodes)]
    assert novice_floor(history)
    report = diagnostic_summary(history, skills="ABC")
    assert report["stop_reason"] == "novice_floor"


def test_the_check_in_ends_when_every_strand_is_closed():
    history = [observation("B", k=k, difficulty=2) for k in range(params.PROBE_ITEMS_PER_SKILL_MAX)]
    history += [idk("A", 20), idk("A", 21)]
    assert probe_done(history, skills="AB")
    assert diagnostic_summary(history, skills="AB")["stop_reason"] == "per_skill_cap"


# ── attempts ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "?", "...", "…", "🙂", "hint please", "can you explain more", "what?", "help me", "ok", "lol",
        "I forgot", "what does this mean", "what’s this", "tell me the answer please", "why",
        "show me the steps", "explain the base case", "I need a hint", "I need help with this",
    ],
)
def test_a_message_that_only_asks_is_no_attempt(text):
    assert gates.vetoes_attempt(text)
    assert not gates.is_genuine_attempt(len(text), False, gates.vetoes_attempt(text), 999, "develop")


@pytest.mark.parametrize(
    "text",
    [
        "5", "x", "B", "yes", "no", "not", "true", "both", "next", "skip", "2x", "is it 4?", "maybe 4",
        "because it is", "why not", "the mean", "the base case", "what if n = 0", "it stops when n is 0",
        "I need a help function that returns", "I want a solution where x is positive",
        "explain it as heat. it moves from hot to cold",
        "-", "+", ">", "[]", "∅", "π", "∞", "√", "→", "水", "да", "π please",
    ],
)
def test_anything_that_could_answer_still_counts(text):
    assert not gates.vetoes_attempt(text)


# ── misconceptions ───────────────────────────────────────────────────────────


def test_right_after_an_idk_is_no_slip():
    """A slip is a wrong answer by someone who knows; an idk claimed nothing."""
    later = Attempt(question_hash="b", node_id="n", correct=True, difficulty=2, isomorph_of="a")

    def prior(**kw):
        return Attempt(question_hash="a", node_id="n", correct=False, difficulty=2, **kw)

    assert slip_or_misconception([prior(), later]) == "slip"
    assert slip_or_misconception([prior(idk=True), later]) != "slip"


# ── the review queue ─────────────────────────────────────────────────────────


def _due(rows, nodes):
    from learning import review

    handles = {"learner_state": MagicMock(), "graph_nodes": MagicMock()}
    handles["learner_state"].select.return_value = rows

    def read(_cols, filters):
        wanted = filters["id"].removeprefix("in.(").removesuffix(")").split(",")
        return [n for n in nodes if n["id"] in wanted]

    handles["graph_nodes"].select.side_effect = read
    with patch.object(review, "table", side_effect=lambda name: handles[name]):
        got = review._due_concepts("u", "c1", NOW, pause=lambda: False, stats={})
    return got, handles


def _row(node_id, **kw):
    past = (NOW - timedelta(days=20)).isoformat()
    return {
        "node_id": node_id, "p_known": 0.95, "streak_unassisted": 1, "fsrs_d": 5.0, "fsrs_s": 2.0,
        "fsrs_last_review_at": past, "fsrs_due_at": past, "last_evidence_at": past, **kw,
    }


def test_the_review_band_decays_from_the_last_evidence():
    """An assisted answer is evidence but no FSRS review; the tutor and the plan
    already decay from it, so the queue's band agrees with theirs."""
    nodes = [{"id": n, "course_id": "c1", "concept_name": n} for n in ("old", "fresh")]
    rows = [_row("old"), _row("fresh", last_evidence_at=(NOW - timedelta(hours=1)).isoformat())]
    concepts, _ = _due(rows, nodes)
    bands = {c.node["id"]: c.band for c in concepts}
    assert bands["fresh"] == "profic" and bands["old"] != "profic"


def test_hundreds_of_due_concepts_are_read_in_bounded_lists():
    ids = [f"node-{i:04d}" for i in range(250)]
    nodes = [{"id": n, "course_id": "c1", "concept_name": n} for n in ids]
    concepts, handles = _due([_row(n) for n in ids], nodes)
    assert len(concepts) == 250
    calls = handles["graph_nodes"].select.call_args_list
    assert [len(c.kwargs["filters"]["id"].split(",")) for c in calls] == [100, 100, 50]
