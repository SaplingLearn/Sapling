"""The quiz's learner-model choices and item rules, pure (learning-loop spec
§13 A143-A147): learning/quiz_plan.py and learning/quiz_gates.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from learning import item_keys, params, quiz_gates, quiz_plan
from learning.quiz_plan import ConceptState, MisconceptionKey

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


# ── quiz_plan: difficulty and question specs (A144) ─────────────────────────


@pytest.mark.parametrize(
    "p, expected",
    [(0.05, "easy"), (0.29, "easy"), (0.30, "medium"), (0.35, "medium"), (0.79, "medium"), (0.80, "hard"), (0.99, "hard")],
)
def test_adaptive_difficulty_is_the_bands_loop_check_level(p, expected):
    assert quiz_plan.difficulty_for(p) == expected


def test_the_quiz_difficulty_names_are_the_quizs_concrete_difficulties():
    from services.quiz_config import CONCRETE_DIFFICULTIES

    assert tuple(params.QUIZ_DIFFICULTY_NAMES) == tuple(CONCRETE_DIFFICULTIES)
    assert sorted(params.LOOP_CHECK_DIFFICULTY_BY_BAND.values()) == [1, 2, 3]


def test_is_key_matches_the_misconception_stores_rule():
    from learning.misconceptions import is_key

    for key in ("divides_by_entries", "a", "x1_y", "A", "has space", "", "_lead", "x" * 64, "x" * 65, None, 3):
        assert quiz_plan.is_key(key) == is_key(key), key


def test_misconception_keys_put_the_students_open_keys_first_then_the_bank():
    keys = quiz_plan.misconception_keys(
        [("rate_is_loss_value", 1), ("rate_sets_step_direction", 3), ("Not A Key", 9)],
        [
            ("rate_is_iteration_count", "Confuses the rate with iterations."),
            ("rate_is_loss_value", "Treats the rate as the loss."),
            ("rate_is_iteration_count", "a second text is ignored"),
            ("bad key", "never listed"),
        ],
    )
    assert [(k.key, k.held) for k in keys] == [
        ("rate_sets_step_direction", True),
        ("rate_is_loss_value", True),
        ("rate_is_iteration_count", False),
    ]
    # an open key the bank describes keeps the bank's text; one it does not, its words
    assert keys[1].text == "Treats the rate as the loss."
    assert keys[0].text == "rate sets step direction"


def test_misconception_keys_are_capped():
    bank = [(f"key_{i}", f"text {i}") for i in range(params.QUIZ_MISCONCEPTION_KEYS_MAX + 4)]
    assert len(quiz_plan.misconception_keys([], bank)) == params.QUIZ_MISCONCEPTION_KEYS_MAX


def _keys(*names, held=False):
    return [MisconceptionKey(n, n.replace("_", " "), held) for n in names]


def test_adaptive_specs_take_the_bands_difficulty_and_one_target_per_key():
    specs = quiz_plan.question_specs(
        4, requested="adaptive", p_known=0.85, keys=_keys("k_a", "k_b"), question_format="multiple_choice"
    )
    assert [(s.slot, s.difficulty, s.target) for s in specs] == [
        (1, "hard", "k_a"),
        (2, "hard", "k_b"),
        (3, "hard", None),
        (4, "hard", None),
    ]


def test_an_explicit_difficulty_is_the_students():
    specs = quiz_plan.question_specs(2, requested="easy", p_known=0.99, keys=[], question_format="mixed")
    assert [s.difficulty for s in specs] == ["easy", "easy"]
    assert quiz_plan.difficulty_source("easy") == quiz_plan.FROM_REQUEST
    assert quiz_plan.difficulty_source("adaptive") == quiz_plan.FROM_LEARNER_MODEL


@pytest.mark.parametrize("fmt", ["short_answer", "numeric", "symbolic"])
def test_a_written_quiz_targets_no_misconception(fmt):
    specs = quiz_plan.question_specs(2, requested="medium", p_known=0.5, keys=_keys("k_a"), question_format=fmt)
    assert all(s.target is None for s in specs)


def test_an_unknown_difficulty_is_a_caller_bug():
    with pytest.raises(ValueError):
        quiz_plan.question_specs(1, requested="impossible", p_known=0.5, keys=[], question_format="mixed")
    assert quiz_plan.question_specs(0, requested="easy", p_known=0.5, keys=[], question_format="mixed") == []


# ── quiz_plan: the concept plan (A143) ──────────────────────────────────────


def _state(node, p, *, due=None, s=None, last=None, mis=0):
    return ConceptState(node, p, fsrs_s=s, fsrs_last_review_at=last, fsrs_due_at=due, open_misconceptions=mis)


def test_the_plan_puts_due_reviews_first_then_misconceptions_then_the_ready_fringe():
    states = [
        _state("ready_low", 0.40),
        _state("ready_high", 0.70),
        _state("due_far", 0.96, due=NOW - timedelta(days=9), s=2.0, last=NOW - timedelta(days=10)),
        _state("due_near", 0.97, due=NOW - timedelta(hours=1), s=5.0, last=NOW - timedelta(days=5)),
        _state("held", 0.50, mis=2),
        _state("blocked", 0.20),  # its prerequisite (ready_low) is not proficient
        _state("proficient", 0.97),  # not due: left until it is
        _state("due_later", 0.60, due=NOW + timedelta(days=2), s=4.0, last=NOW - timedelta(days=1)),
    ]
    edges = [("ready_low", "blocked")]
    plan = quiz_plan.rank_concepts(states, edges, NOW)
    order = [(c.node_id, c.reason) for c in plan]
    # due first, in DASH order: the recall nearest 0.33 (the most overdue) first
    assert order[:2] == [("due_far", "due"), ("due_near", "due")]
    assert order[2] == ("held", "misconception")
    # the outer fringe in the planner's own order (p descending)
    assert order[3:] == [("ready_high", "ready"), ("due_later", "ready"), ("ready_low", "ready")]
    assert "blocked" not in dict(order) and "proficient" not in dict(order)
    assert plan[2].band == "develop" and plan[2].open_misconceptions == 2


def test_the_plan_is_capped():
    states = [_state(f"n{i:03d}", 0.4) for i in range(params.QUIZ_PLAN_MAX_CONCEPTS + 5)]
    assert len(quiz_plan.rank_concepts(states, [], NOW)) == params.QUIZ_PLAN_MAX_CONCEPTS


# ── quiz_plan: the results (A147) ───────────────────────────────────────────


def test_skill_changes_list_what_moved_quizzed_concept_first():
    changes = quiz_plan.skill_changes(
        {"n": 0.35, "parent": 0.50, "child": 0.60, "still": 0.40},
        {"n": 0.62, "parent": 0.52, "child": 0.60, "still": 0.4004},
        ["n", "parent", "child", "still", "unread"],
    )
    assert [(c.node_id, c.band_before, c.band_after) for c in changes] == [
        ("n", "develop", "develop"),
        ("parent", "develop", "develop"),
    ]


def test_the_next_step_is_review_when_anything_is_due():
    states = [
        _state("due", 0.96, due=NOW - timedelta(hours=2), s=3.0, last=NOW - timedelta(days=3)),
        _state("weak", 0.30),
        _state("weaker", 0.10),
    ]
    step = quiz_plan.next_step(states, [], NOW)
    assert (step.kind, step.due_count, step.learn_node_id) == ("review", 1, "weaker")


def test_the_next_step_is_the_weakest_ready_concept_otherwise():
    states = [_state("a", 0.60), _state("b", 0.20), _state("c", 0.05)]
    # c's prerequisite b is not proficient: c is not ready
    step = quiz_plan.next_step(states, [("b", "c")], NOW)
    assert (step.kind, step.learn_node_id) == ("learn", "b")


def test_the_next_step_is_none_when_nothing_is_left():
    step = quiz_plan.next_step([_state("a", 0.97)], [], NOW)
    assert (step.kind, step.due_count, step.learn_node_id) == ("none", 0, None)


# ── quiz_gates: the gates (A145) ────────────────────────────────────────────


def _mc(correct="B", tags=None, gate=None, **extra):
    options = []
    for label, text in zip("ABCD", ("one", "two", "three", "four")):
        option = {"label": label, "text": text, "correct": label == correct}
        if tags and tags.get(label):
            option["misconception"] = tags[label]
        options.append(option)
    q = {"id": 1, "question": "Which?", "options": options, "question_hash": "h1", **extra}
    if gate:
        q["gate"] = gate
    return q


VERIFIED = {"status": "verified", "alignment": "aligned", "key": "key_agreed"}


def test_alignment_reads_the_concept_check_answer():
    assert quiz_gates.alignment_of("Recursion", "recursion") == quiz_gates.ALIGNED
    assert quiz_gates.alignment_of('"Recursion."', "Recursion") == quiz_gates.ALIGNED
    assert quiz_gates.alignment_of("Loops", "Recursion") == quiz_gates.MISALIGNED
    assert quiz_gates.alignment_of("none", "Recursion") == quiz_gates.MISALIGNED
    assert quiz_gates.alignment_of(None, "Recursion") == quiz_gates.ALIGNMENT_UNVERIFIED


def test_a_conflicting_concept_answer_is_none():
    got = quiz_gates.collect_concepts([("q1", "Loops"), ("q1", "Recursion"), ("q2", "Loops"), ("q2", "loops.")])
    assert got == {"q2": "Loops"}


def test_a_multiple_choice_key_is_compared_by_its_served_letter():
    q = _mc(correct="C")
    assert quiz_gates.key_outcome(q, item_keys.Solved(True, "C")) == item_keys.AGREE
    assert quiz_gates.key_outcome(q, item_keys.Solved(True, "Option B")) == item_keys.DISPUTED
    assert quiz_gates.key_outcome(q, item_keys.Solved(True, "E")) == item_keys.NO_VERDICT
    assert quiz_gates.key_outcome(q, item_keys.Solved(False, "")) == item_keys.UNSOLVED
    assert quiz_gates.key_outcome(q, None) == item_keys.NO_VERDICT


def test_a_written_key_is_compared_by_the_quiz_grader():
    num = {"type": "numeric", "question": "?", "correct_answer": "4/5"}
    assert quiz_gates.key_outcome(num, item_keys.Solved(True, "0.8"), accepted=True, parsed=True) == item_keys.AGREE
    assert quiz_gates.key_outcome(num, item_keys.Solved(True, "0.7"), accepted=False, parsed=True) == item_keys.DISPUTED
    assert quiz_gates.key_outcome(num, item_keys.Solved(True, "eight"), accepted=False, parsed=False) == item_keys.NO_VERDICT
    sym = {"type": "symbolic", "question": "?", "correct_answer": "2x+2"}
    assert quiz_gates.key_outcome(sym, item_keys.Solved(True, "2(x+1)"), accepted=True, parsed=True) == item_keys.AGREE
    assert quiz_gates.key_outcome(sym, item_keys.Solved(True, "x+2"), accepted=False, parsed=True) == item_keys.DISPUTED
    assert quiz_gates.key_outcome(sym, item_keys.Solved(True, "two x"), accepted=False, parsed=False) == item_keys.TO_MATCH
    short = {"type": "short_answer", "question": "?", "correct_answer": "base case"}
    assert quiz_gates.key_outcome(short, item_keys.Solved(True, "the base case"), accepted=False) == item_keys.TO_MATCH


def test_the_key_half_settles_a_match():
    assert quiz_gates.key_of(item_keys.AGREE) == quiz_gates.KEY_AGREED
    assert quiz_gates.key_of(item_keys.TO_MATCH, True) == quiz_gates.KEY_AGREED
    assert quiz_gates.key_of(item_keys.TO_MATCH, False) == quiz_gates.KEY_DISPUTED
    assert quiz_gates.key_of(item_keys.TO_MATCH, None) == quiz_gates.KEY_UNVERIFIED
    assert quiz_gates.key_of(item_keys.UNSOLVED) == quiz_gates.KEY_UNSOLVED
    assert quiz_gates.key_of(item_keys.NO_VERDICT) == quiz_gates.KEY_UNVERIFIED


@pytest.mark.parametrize(
    "alignment, key, grounded, status",
    [
        ("aligned", "key_agreed", True, "verified"),
        ("aligned", "key_agreed", False, "verified"),
        ("misaligned", "key_agreed", True, "dropped"),
        ("aligned", "key_disputed", False, "dropped"),
        ("aligned", "key_unsolved", True, "dropped"),
        ("aligned", "key_unsolved", False, "practice"),
        ("aligned", "key_unverified", True, "practice"),
        ("aligned", "key_not_independent", True, "practice"),
        ("alignment_unverified", "key_agreed", True, "practice"),
        ("misaligned", "key_unverified", False, "dropped"),
    ],
)
def test_the_gate_decision(alignment, key, grounded, status):
    gate = quiz_gates.decide(alignment, key, grounded=grounded)
    assert gate.status == status
    assert gate.stored() == {"status": status, "alignment": alignment, "key": key}


def test_only_a_verified_question_or_one_without_a_gate_is_evidence():
    assert quiz_gates.evidence_exclusion(_mc()) == []  # flags off: unchanged
    assert quiz_gates.evidence_exclusion(_mc(gate=VERIFIED)) == []
    practice = {"status": "practice", "alignment": "aligned", "key": "key_unverified"}
    assert quiz_gates.evidence_exclusion(_mc(gate=practice)) == ["key_unverified"]
    unchecked = {"status": "practice", "alignment": "not_checked", "key": "not_checked"}
    assert quiz_gates.evidence_exclusion(_mc(gate=unchecked)) == ["not_checked", "not_checked"]


# ── quiz_gates: tags and the misconception rules (A144, A146) ───────────────


def test_tags_are_kept_only_on_distractors_and_only_when_named():
    got = quiz_gates.validate_tags(
        ["k_a", "k_b", "", "k_unnamed"], options=4, correct_index=1, allowed={"k_a", "k_b"}
    )
    assert got == ["k_a", None, None, None]
    assert quiz_gates.validate_tags(["k_a"], options=4, correct_index=0, allowed={"k_a"}) == [None] * 4
    assert quiz_gates.validate_tags(None, options=4, correct_index=0, allowed={"k_a"}) == [None] * 4


def test_a_sure_wrong_answer_on_a_tagged_distractor_of_a_verified_question_records_it():
    sure = params.STUDENT_CONFIDENCE_LEVELS["sure"]
    fairly = params.STUDENT_CONFIDENCE_LEVELS["fairly_sure"]
    q = _mc(correct="B", tags={"A": "k_a"}, gate=VERIFIED)
    assert quiz_gates.misconception_to_record(q, "A", sure) == "k_a"
    assert quiz_gates.misconception_to_record(q, "A", fairly) is None  # below MISCONCEPTION_CONFIDENCE
    assert quiz_gates.misconception_to_record(q, "A", None) is None  # no statement
    assert quiz_gates.misconception_to_record(q, "C", sure) is None  # untagged distractor
    assert quiz_gates.misconception_to_record(q, "B", sure) is None  # the right answer
    unverified = _mc(correct="B", tags={"A": "k_a"}, gate={**VERIFIED, "status": "practice"})
    assert quiz_gates.misconception_to_record(unverified, "A", sure) is None
    assert quiz_gates.misconception_to_record(_mc(correct="B", tags={"A": "k_a"}), "A", sure) is None


def test_a_verified_question_lists_its_distractors_tags():
    q = _mc(correct="B", tags={"A": "k_b", "C": "k_a", "D": "k_a"}, gate=VERIFIED)
    assert quiz_gates.keys_listed(q) == ["k_a", "k_b"]
    assert quiz_gates.keys_listed(_mc(correct="B", tags={"A": "k_a"})) == []
