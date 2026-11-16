"""Grading a check answer (services/study_guides/answers.py).

The store, the concept-node read and the graph write are replaced where the
module looks them up. The stand-in for `store.arecord_answer` keeps the rule
the real one enforces: a block's first answer is written, a later one is not.
The graph stand-in takes graded evidence only (learning-loop PKG-14b: the real
`apply_graph_update` refuses the legacy keys) and moves the score a fixed STEP,
standing in for BKT.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from learning.evidence import Evidence
from learning.params import BKT_PROFICIENT
from models.study_guide import (
    CheckBlock,
    CheckOption,
    GuideContent,
    KeyTerm,
    KeyTermsBlock,
    Section,
)
from services import events_service
from services.quiz.identity import question_hash, wire_question_hash
from services.study_guides import answers
from services.study_guides.signals import concept_key
from services.study_guides.errors import GuideInvalid, GuideNotFound
from services.study_guides.store import GuideRow

ME = "user_answers_me"
OFFERING = "off-cs-f26"
COURSE = "course-cs"
MADE_AT = "2026-10-01T12:00:00+00:00"
#: How far the graph stand-in moves a score per graded answer.
STEP = 0.04
#: The concept nodes of the student's tree.
NODE_IDS = {"Loops": "node-loops", "Recursion": "node-recursion"}


def _check(item_id: str, concept: str | None, **over) -> CheckBlock:
    fields = dict(
        id=item_id, question="How many passes?",
        options=[CheckOption(id="a", text="3"), CheckOption(id="b", text="4"),
                 CheckOption(id="c", text="5")],
        correct_id="b", explain_correct="Four values pass.",
        explain_incorrect="List the values, then count them.", concept=concept,
    )
    return CheckBlock(**{**fields, **over})


def _guide() -> GuideRow:
    terms = KeyTermsBlock(id="s1-i1", title="Key terms", terms=[
        KeyTerm(term="Loop", definition="Repeats a block."),
        KeyTerm(term="Branch", definition="Chooses a block."),
    ])
    content = GuideContent(title="Control flow", sections=[
        Section(id="s1", title="Loops", concept="Loops", status="written", items=[
            terms,
            _check("s1-i2", "loops"),                       # the tree spells it "Loops"
            _check("s1-i3", "Pointers"),                    # not in the tree
            _check("s1-i4", None),                          # tests no concept
            _check("s1-i5", "Loops", correct_id=None),      # stored without an answer
        ]),
    ])
    return GuideRow(
        id="g1", user_id=ME, offering_id=OFFERING, exam_id=None, scope_kind="course",
        goal="practice", depth="standard", use_history=True, status="ready", format=2,
        content=content, material_ids=[], read_sections=[], answers={}, feedback=None,
        saved_at=None, generating_at=None, generated_at=MADE_AT, created_at=MADE_AT,
        updated_at=MADE_AT,
    )


@pytest.fixture
def world(monkeypatch, sink):
    """One guide, a tree with "Loops" at 0.5, and a graph that applies the
    evidence it is given. `graph` holds every `apply_graph_update` call."""
    box = {"answered": {}, "graph": [], "scores": {"Loops": 0.5, "Recursion": 0.1},
           "graph_error": None, "events": sink}

    async def aload_guide(user_id, guide_id):
        if (user_id, guide_id) != (ME, "g1"):
            raise GuideNotFound("Study guide not found.")
        return _guide()

    async def arecord_answer(guide, block_id, answer):
        if block_id in box["answered"]:
            return False
        box["answered"][block_id] = answer
        return True

    async def aconcept_node(user_id, course_id, concept):
        assert (user_id, course_id) == (ME, COURSE)
        return next((
            {"id": NODE_IDS[name], "concept_name": name, "mastery_score": score}
            for name, score in box["scores"].items()
            if concept_key(name) == concept_key(concept)
        ), None)

    def apply_graph_update(user_id, graph_update, course_id=None, *, defer=None):
        if box["graph_error"]:
            raise box["graph_error"]
        box["graph"].append({"user_id": user_id, "update": graph_update,
                             "course_id": course_id, "defer": defer})
        if "updated_nodes" in graph_update:
            raise ValueError("updated_nodes is no longer accepted (PKG-14b): pass evidence")
        names = {node_id: name for name, node_id in NODE_IDS.items()}
        changes = []
        for ev in graph_update["evidence"]:
            name = names[ev["node_id"]]
            before = box["scores"][name]
            after = min(1.0, max(0.0, before + (STEP if ev["correct"] else -STEP)))
            box["scores"][name] = after
            changes.append({"concept": name, "before": before, "after": after})
        return changes

    monkeypatch.setattr(answers.store, "aload_guide", aload_guide)
    monkeypatch.setattr(answers.store, "arecord_answer", arecord_answer)
    monkeypatch.setattr(answers.signals, "aconcept_node", aconcept_node)
    monkeypatch.setattr(answers, "academics",
                        SimpleNamespace(offering_course_id=lambda offering_id: COURSE))
    monkeypatch.setattr(answers.graph_service, "apply_graph_update", apply_graph_update)
    return box


def _answer(block_id: str, option_id: str, *, user_id: str = ME, defer=None):
    return asyncio.run(answers.aanswer_check(user_id, "g1", block_id, option_id, defer=defer))


def _evidence(world) -> dict:
    (call,) = world["graph"]
    assert set(call["update"]) == {"evidence"}  # never a legacy flat delta
    (ev,) = call["update"]["evidence"]
    return ev


def _events(world) -> list[dict]:
    events_service.flush_now()
    return [e for e in world["events"] if e["event_type"] == "study_guide.check_answered"]


# ── The first answer ──────────────────────────────────────────────────────────


def test_a_correct_first_answer_writes_one_mc_evidence_as_a_quiz_question_does(world):
    def defer(task):
        return None

    out = _answer("s1-i2", "b", defer=defer)
    assert (out.correct, out.correct_id, out.counted) == (True, "b", True)
    assert out.explanation == "Four values pass."

    (call,) = world["graph"]
    assert (call["user_id"], call["course_id"], call["defer"]) == (ME, COURSE, defer)
    ev = _evidence(world)
    # On the tree's own node ("Loops"), not the guide's spelling ("loops"),
    # in the shape services/quiz/submission.py::_quiz_evidence writes.
    assert ev == {
        "node_id": "node-loops",
        "channel": "mc",
        "correct": True,
        "question_hash": question_hash("How many passes?", ["3", "4", "5"]),
        "check_item_id": None,
        "session_id": None,
    }
    Evidence.model_validate(ev)  # what apply_graph_update parses it as


def test_the_evidence_names_the_question_by_the_quizs_identity(world):
    _answer("s1-i2", "b")
    assert _evidence(world)["question_hash"] == wire_question_hash({
        "question": "How many passes?", "options": ["3", "4", "5"],
    })


def test_a_wrong_first_answer_writes_incorrect_evidence_and_gives_the_nudge(world):
    out = _answer("s1-i2", "a")
    assert (out.correct, out.correct_id, out.counted) == (False, "b", True)
    assert out.explanation == "List the values, then count them."
    ev = _evidence(world)
    assert (ev["node_id"], ev["channel"], ev["correct"]) == ("node-loops", "mc", False)
    assert world["scores"]["Loops"] == pytest.approx(0.5 - STEP)


def test_the_mastery_change_reports_tiers_before_and_after(world):
    world["scores"]["Loops"] = BKT_PROFICIENT - STEP / 2  # one correct answer short
    out = _answer("s1-i2", "b")
    assert out.mastery.model_dump() == {"concept": "Loops", "before": "learning", "after": "mastered"}


def test_a_change_inside_one_tier_is_still_reported(world):
    out = _answer("s1-i2", "b")
    assert out.mastery.model_dump() == {"concept": "Loops", "before": "learning", "after": "learning"}


def test_before_is_the_tier_the_student_was_shown_not_the_estimates_prior(world, monkeypatch):
    """A node with no learner_state starts the update at the BKT prior, which
    can sit in another tier than the stored mastery the map showed. The
    reported move starts from what the student saw."""
    world["scores"]["Loops"] = 0.25  # shown as struggling
    monkeypatch.setattr(
        answers.graph_service, "apply_graph_update",
        lambda *a, **k: [{"concept": "Loops", "before": 0.35, "after": 0.2}],  # prior in "learning"
    )
    out = _answer("s1-i2", "a")
    assert out.mastery.model_dump() == {"concept": "Loops", "before": "struggling", "after": "struggling"}


def test_a_graph_that_moves_nothing_reports_no_change(world, monkeypatch):
    monkeypatch.setattr(answers.graph_service, "apply_graph_update", lambda *a, **k: [])
    out = _answer("s1-i2", "b")
    assert (out.correct, out.counted, out.mastery) == (True, True, None)


# ── A repeat answer ───────────────────────────────────────────────────────────


def test_a_repeat_answer_is_graded_but_does_not_count_or_move_mastery(world):
    first = _answer("s1-i2", "a")
    again = _answer("s1-i2", "b")
    assert (first.counted, again.counted) == (True, False)
    assert (again.correct, again.correct_id, again.explanation) == (True, "b", "Four values pass.")
    assert again.mastery is None
    assert len(world["graph"]) == 1
    assert world["answered"]["s1-i2"].model_dump() == {"option_id": "a", "correct": False}


# ── Answers that move nothing ─────────────────────────────────────────────────


def test_a_concept_the_tree_lacks_records_the_answer_without_a_mastery_write(world):
    out = _answer("s1-i3", "b")
    assert (out.correct, out.counted, out.mastery) == (True, True, None)
    assert "s1-i3" in world["answered"] and world["graph"] == []


def test_a_check_with_no_concept_records_the_answer_without_a_mastery_write(world):
    out = _answer("s1-i4", "c")
    assert (out.correct, out.counted, out.mastery) == (False, True, None)
    assert "s1-i4" in world["answered"] and world["graph"] == []


def test_a_failed_mastery_write_does_not_fail_the_answer(world, caplog):
    world["graph_error"] = RuntimeError("graph is down")
    out = _answer("s1-i2", "b")
    assert (out.correct, out.counted, out.mastery) == (True, True, None)
    assert "s1-i2" in world["answered"]
    # One warning line naming the error's type, and no traceback (the E2E
    # log scan fails on any).
    (record,) = [r for r in caplog.records if "mastery" in r.getMessage()]
    assert record.levelname == "WARNING" and record.exc_info is None
    assert "RuntimeError" in record.getMessage() and "graph is down" not in record.getMessage()


# ── Refusals ──────────────────────────────────────────────────────────────────


def test_an_option_the_question_does_not_have_is_invalid_and_nothing_is_recorded(world):
    with pytest.raises(GuideInvalid):
        _answer("s1-i2", "d")
    assert world["answered"] == {} and world["graph"] == [] and _events(world) == []


@pytest.mark.parametrize("block_id", ["s1-i1", "s1", "s9-i9", "s1-i5"])
def test_a_block_that_is_not_a_gradable_check_is_not_found(world, block_id):
    """A key-terms block, a section id, an id the guide does not have, and a
    check stored without its answer."""
    with pytest.raises(GuideNotFound):
        _answer(block_id, "a")
    assert world["answered"] == {} and world["graph"] == []


def test_someone_elses_guide_is_not_found(world):
    with pytest.raises(GuideNotFound):
        _answer("s1-i2", "b", user_id="user_other")
    assert world["answered"] == {} and world["graph"] == []


# ── The event ─────────────────────────────────────────────────────────────────


def test_each_answer_emits_ids_and_outcome_only(world):
    _answer("s1-i2", "a")
    _answer("s1-i2", "b")
    first, again = _events(world)
    assert (first["category"], first["user_id"]) == ("usage", ME)
    assert first["payload"] == {
        "guide_id": "g1", "block_id": "s1-i2", "correct": False, "counted": True,
    }
    assert again["payload"] == {
        "guide_id": "g1", "block_id": "s1-i2", "correct": True, "counted": False,
    }
