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
    from agents.quiz_planned import PlannedQuestion
    from learning import quiz_plan
    from services import quiz_learning as ql

    plan = ql.GenerationPlan(
        specs=[quiz_plan.QuestionSpec(1, "medium")],
        keys=(),
        p_known=0.4,
        source=quiz_plan.difficulty_source("medium"),
    )
    planned = PlannedQuestion(
        slot=1,
        question="Sort the cells.",
        type="short_answer",
        correct_answer="Prok=e-coli;Euk=yeast",
        explanation="By domain.",
        interaction={
            "kind": "sort",
            "buckets": ["Prok", "Euk"],
            "items": [
                {"id": "e-coli", "label": "E. coli"},
                {"id": "yeast", "label": "Yeast"},
            ],
        },
    )
    out = ql.planned_question(planned, plan, set(), "Cells")
    assert out is not None
    q, spec, _tags, kit = out
    assert spec.slot == 1
    wire = _agent_question_to_wire(q, 1)
    assert wire is not None
    attach_interaction(wire, kit)
    assert wire["interaction"]["kind"] == "sort"
