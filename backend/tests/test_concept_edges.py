"""concept_edges agent + the sanitizer that decides what of its answer is written."""

from pydantic_ai import Agent

from agents._providers import model_for
from agents.concept_edges import ConceptEdges, concept_edges_agent
from services.concept_edges import MAX_INCOMING, build_message, ring_depths, sanitize_edges

NAMES = ["Limits", "Derivatives", "Chain Rule", "Integrals", "Fundamental Theorem", "Series"]


def _e(s, t, rel="prerequisite", strength=0.8):
    return {"source": s, "target": t, "relationship_type": rel, "strength": strength}


def test_agent_is_configured():
    assert isinstance(concept_edges_agent, Agent)
    assert concept_edges_agent.output_type is ConceptEdges
    assert model_for("concept_edges").model_name == "claude-haiku-5-5"


def test_strength_is_clamped_not_rejected():
    out = ConceptEdges.model_validate({"edges": [
        {"source": "A", "target": "B", "relationship_type": "related", "strength": 7},
        {"source": "A", "target": "C", "relationship_type": "related", "strength": "x"},
    ]})
    assert [e.strength for e in out.edges] == [1.0, 0.6]


def test_names_resolve_case_and_whitespace_insensitively_to_canonical():
    out = sanitize_edges(NAMES, [_e("  limits ", "DERIVATIVES")])
    assert out == [_e("Limits", "Derivatives")]


def test_unknown_self_and_unproposable_edges_are_dropped():
    out = sanitize_edges(NAMES, [
        _e("Limits", "Topology"),
        _e("Limits", "limits"),
        _e("Limits", "Derivatives", rel="part_of"),
    ])
    assert out == []


def test_cycles_are_refused_strongest_edge_wins():
    out = sanitize_edges(NAMES, [
        _e("Limits", "Derivatives", strength=0.9),
        _e("Derivatives", "Chain Rule", strength=0.8),
        _e("Chain Rule", "Limits", strength=0.5),
    ])
    assert [(e["source"], e["target"]) for e in out] == [("Limits", "Derivatives"), ("Derivatives", "Chain Rule")]


def test_cycle_check_includes_existing_edges():
    out = sanitize_edges(NAMES, [_e("Derivatives", "Limits")], existing=[_e("Limits", "Derivatives", rel="builds_on")])
    assert out == []


def test_shortcut_edges_are_reduced_away():
    out = sanitize_edges(NAMES, [
        _e("Limits", "Derivatives", strength=0.9),
        _e("Derivatives", "Chain Rule", strength=0.9),
        _e("Limits", "Chain Rule", strength=0.6),
    ])
    assert ("Limits", "Chain Rule") not in {(e["source"], e["target"]) for e in out}
    assert len(out) == 2


def test_one_edge_per_pair_directed_beats_related():
    out = sanitize_edges(NAMES, [
        _e("Limits", "Derivatives", rel="related", strength=0.9),
        _e("Derivatives", "Limits", strength=0.5),
    ])
    assert out == [_e("Derivatives", "Limits", strength=0.5)]


def test_incoming_directed_edges_are_capped():
    many = [f"C{i}" for i in range(8)] + ["Hub"]
    out = sanitize_edges(many, [_e(f"C{i}", "Hub", strength=0.9 - i * 0.05) for i in range(8)])
    assert len(out) == MAX_INCOMING
    assert {e["source"] for e in out} == {"C0", "C1", "C2"}


def test_related_is_capped_per_concept():
    names = ["A", "B", "C", "D", "E", "F", "G", "H", "I"]
    out = sanitize_edges(names, [_e("A", x, rel="related") for x in "BCDE"])
    assert len(out) == 2


def test_ring_depths_are_longest_paths_and_ignore_related():
    edges = [_e("Limits", "Derivatives"), _e("Derivatives", "Chain Rule"),
             _e("Limits", "Chain Rule"), _e("Integrals", "Series", rel="related")]
    d = ring_depths(NAMES, edges)
    assert d["Limits"] == 0 and d["Derivatives"] == 1 and d["Chain Rule"] == 2
    assert d["Series"] == 0


def test_build_message_lists_every_concept():
    msg = build_message("MA 123 — Calculus I", NAMES)
    assert "MA 123" in msg and all(f"- {n}" in msg for n in NAMES)
