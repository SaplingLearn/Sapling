"""W7 generation emit — sanitize + wire attach (docs/learning-loop/w7-generation-emit.md)."""

from agents.quiz import QuizQuestion
from services.quiz.interaction import sanitize_interaction
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


def test_wire_attaches_sort_on_short_answer():
    q = QuizQuestion(
        question="Sort each organism.",
        type="short_answer",
        difficulty="medium",
        options=[],
        accepted_answers=["Prokaryote=e-coli;Eukaryote=yeast"],
        correct_answer="Prokaryote=e-coli;Eukaryote=yeast",
        explanation="Cell type.",
        concept="Cells",
        interaction={
            "kind": "sort",
            "buckets": ["Prokaryote", "Eukaryote"],
            "items": [
                {"id": "e-coli", "label": "E. coli"},
                {"id": "yeast", "label": "Yeast"},
            ],
        },
    )
    wire = _agent_question_to_wire(q, 1)
    assert wire is not None
    assert wire["type"] == "short_answer"
    assert wire["interaction"]["kind"] == "sort"


def test_wire_drops_bad_interaction_without_dropping_item():
    q = QuizQuestion(
        question="Name the organelle.",
        type="short_answer",
        difficulty="easy",
        options=[],
        accepted_answers=["mitochondria"],
        correct_answer="mitochondria",
        explanation="Powerhouse.",
        concept="Cells",
        interaction={"kind": "sort", "buckets": ["one"], "items": []},
    )
    wire = _agent_question_to_wire(q, 2)
    assert wire is not None
    assert "interaction" not in wire
