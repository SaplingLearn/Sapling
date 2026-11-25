"""W7 generation emit — sanitize + wire attach (docs/learning-loop/w7-generation-emit.md)."""

from agents.quiz import QuizQuestion
from services.quiz.interaction import attach_interaction, sanitize_interaction
from services.quiz.wire import _agent_question_to_wire


def test_sanitize_sort_and_reject_junk():
    ok = sanitize_interaction({
        "kind": "sort",
        "buckets": ["Prokaryote", "Eukaryote"],
        "items": [
            {"id": "e-coli", "label": "E. coli"},
            {"id": "yeast", "label": "Yeast"},
        ],
    })
    assert ok is not None
    assert ok["kind"] == "sort"
    assert len(ok["buckets"]) == 2
    assert sanitize_interaction({"kind": "sort", "buckets": ["only"], "items": []}) is None
    assert sanitize_interaction({"kind": "unknown"}) is None
    assert sanitize_interaction(None) is None


def test_sanitize_connect_match_and_map():
    match = sanitize_interaction({
        "kind": "connect",
        "left": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "right": [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}],
    })
    assert match is not None and "left" in match
    mapped = sanitize_interaction({
        "kind": "connect",
        "mode": "map",
        "nodes": [
            {"id": "a", "label": "A"},
            {"id": "b", "label": "B"},
            {"id": "c", "label": "C"},
        ],
    })
    assert mapped is not None and mapped.get("mode") == "map"


def test_sanitize_remaining_kit_kinds():
    assert sanitize_interaction({
        "kind": "label",
        "spots": [{"id": "s1", "label": "S1"}, {"id": "s2", "label": "S2"}],
        "labels": [{"id": "l1", "label": "L1"}, {"id": "l2", "label": "L2"}],
    })["kind"] == "label"
    assert sanitize_interaction({
        "kind": "sequence",
        "steps": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
    })["kind"] == "sequence"
    assert sanitize_interaction({
        "kind": "build",
        "slots": [{"id": "s", "label": "Slot"}],
        "parts": [{"id": "p1", "label": "P1"}, {"id": "p2", "label": "P2"}],
    })["kind"] == "build"
    assert sanitize_interaction({
        "kind": "compare",
        "left": {"id": "l", "label": "Left"},
        "right": {"id": "r", "label": "Right"},
        "options": [{"id": "only-l", "label": "Only left"}, {"id": "both", "label": "Both"}],
    })["kind"] == "compare"
    assert sanitize_interaction({
        "kind": "dialogue",
        "role": "Peer",
        "open": "Hi?",
        "follow": "And then?",
    })["kind"] == "dialogue"
    assert sanitize_interaction({"kind": "explain"})["kind"] == "explain"
    assert sanitize_interaction({
        "kind": "highlight",
        "passages": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
    })["kind"] == "highlight"
    assert sanitize_interaction({"kind": "calculate"})["kind"] == "calculate"
    assert sanitize_interaction({
        "kind": "position",
        "markers": [{"id": "m1", "label": "M1"}, {"id": "m2", "label": "M2"}],
        "stops": [{"id": "s1", "label": "S1"}, {"id": "s2", "label": "S2"}],
    })["kind"] == "position"
    assert sanitize_interaction({
        "kind": "rank",
        "items": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
    })["kind"] == "rank"


def test_attach_sort_on_short_answer_wire():
    q = QuizQuestion(
        question="Sort each organism.",
        type="short_answer",
        difficulty="medium",
        options=[],
        accepted_answers=["Prokaryote=e-coli;Eukaryote=yeast"],
        correct_answer="Prokaryote=e-coli;Eukaryote=yeast",
        explanation="Cell type.",
        concept="Cells",
    )
    wire = _agent_question_to_wire(q, 1)
    assert wire is not None
    attach_interaction(wire, {
        "kind": "sort",
        "buckets": ["Prokaryote", "Eukaryote"],
        "items": [
            {"id": "e-coli", "label": "E. coli"},
            {"id": "yeast", "label": "Yeast"},
        ],
    })
    assert wire["interaction"]["kind"] == "sort"


def test_attach_drops_bad_interaction_without_dropping_item():
    q = QuizQuestion(
        question="Name the organelle.",
        type="short_answer",
        difficulty="easy",
        options=[],
        accepted_answers=["mitochondria"],
        correct_answer="mitochondria",
        explanation="Powerhouse.",
        concept="Cells",
    )
    wire = _agent_question_to_wire(q, 2)
    assert wire is not None
    attach_interaction(wire, {"kind": "sort", "buckets": ["one"], "items": []})
    assert "interaction" not in wire


def test_planned_question_returns_kit_for_wire_attach():
    import json

    from agents.quiz_planned import PlannedQuestion, PlannedQuiz, planned_kit
    from learning import quiz_plan
    from services import quiz_learning as ql

    plan = ql.GenerationPlan(
        specs=[quiz_plan.QuestionSpec(1, "medium"), quiz_plan.QuestionSpec(2, "medium")],
        keys=(),
        p_known=0.4,
        source=quiz_plan.difficulty_source("medium"),
    )
    kit = {
        "kind": "sort",
        "buckets": ["Prok", "Euk"],
        "items": [
            {"id": "e-coli", "label": "E. coli"},
            {"id": "yeast", "label": "Yeast"},
        ],
    }
    sort_item = PlannedQuestion(
        slot=1,
        question="Sort the cells.",
        type="short_answer",
        correct_answer="Prok=e-coli;Euk=yeast",
        explanation="By domain.",
    )
    plain_item = PlannedQuestion(
        slot=2, question="Name the domain of yeast.", type="short_answer",
        correct_answer="Eukaryote", explanation="Yeast has a nucleus.",
    )
    # The kit rides the quiz as two flat scalars (output-schema budget), not
    # the question.
    quiz = PlannedQuiz(questions=[sort_item, plain_item], kit_slot=1, kit=json.dumps(kit))
    out = ql.planned_question(sort_item, plan, set(), "Cells", kit=planned_kit(quiz, sort_item))
    assert out is not None
    q, spec, _tags, raw = out
    assert spec.slot == 1
    wire = _agent_question_to_wire(q, 1)
    assert wire is not None
    attach_interaction(wire, raw)
    assert wire["interaction"]["kind"] == "sort"

    other = ql.planned_question(plain_item, plan, set(), "Cells", kit=planned_kit(quiz, plain_item))
    assert other is not None and other[3] is None


def test_planned_kit_fails_closed():
    from agents.quiz import Quiz
    from agents.quiz_planned import PlannedQuestion, PlannedQuiz, planned_kit

    item = PlannedQuestion(
        slot=1, question="Sort.", type="short_answer", correct_answer="a", explanation="b",
    )
    assert planned_kit(PlannedQuiz(questions=[item]), item) is None  # no kit
    for junk in ("not json", "[1, 2]", '"sort"', "   "):
        assert planned_kit(PlannedQuiz(questions=[item], kit_slot=1, kit=junk), item) is None
    # A plain (flag-off) quiz has no kit.
    plain = Quiz(questions=[QuizQuestion(
        question="Q?", type="short_answer", difficulty="medium", correct_answer="a",
        explanation="b", concept="C",
    )])
    assert planned_kit(plain, plain.questions[0]) is None


def test_the_planned_schema_carries_the_kit_as_flat_quiz_scalars():
    """The kit must not come back as a nested or free-form object on the
    question (tests/test_agent_output_schemas.py budget; Claude strict JSON)."""
    from agents.quiz_planned import PlannedQuiz

    schema = PlannedQuiz.model_json_schema()
    assert schema["properties"]["kit_slot"]["type"] == "integer"
    assert schema["properties"]["kit"]["type"] == "string"
    assert "interaction" not in schema["$defs"]["PlannedQuestion"]["properties"]


def test_keyless_projection_serves_the_sanitized_kit():
    """The student answers ON the kit, so the keyless projection (generate,
    the next question, resume) must carry it — re-sanitized, short_answer
    only. quiz-kit.spec.ts never mounted Sort while the allowlist dropped it."""
    from services.quiz.wire import _strip_answer_key

    sort = {
        "kind": "sort",
        "buckets": ["Prokaryote", "Eukaryote"],
        "items": [{"id": "ecoli", "label": "E. coli"}, {"id": "yeast", "label": "Yeast"}],
    }
    stored = [
        {"id": 1, "question": "Sort them.", "type": "short_answer", "options": [],
         "correct_answer": "Prokaryote=ecoli;Eukaryote=yeast",
         "interaction": {**sort, "answer": "Prokaryote=ecoli;Eukaryote=yeast"}},
        {"id": 2, "question": "Name it.", "type": "short_answer", "options": [],
         "correct_answer": "x", "interaction": {"kind": "sort", "buckets": ["one"], "items": []}},
        {"id": 3, "question": "Pick.", "type": "multiple_choice",
         "options": [{"label": "A", "text": "a", "correct": True}], "interaction": sort},
    ]
    kit, junk, mc = _strip_answer_key(stored)
    assert kit["interaction"] == sort
    assert "correct_answer" not in kit
    assert "interaction" not in junk
    assert "interaction" not in mc
