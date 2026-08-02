"""Hermetic tests for the #400 pure judges."""

from e2e_oracles.judges import (
    ciphertext_findings,
    count_findings,
    graph_findings,
    orphan_findings,
)

COURSES = {"c-cs", "c-math"}
DB_NODES = [
    {"id": "n1", "course_id": "c-cs"},
    {"id": "n2", "course_id": "c-cs"},
    {"id": "n3", "course_id": "c-math"},
]
DB_EDGES = [
    {"source_node_id": "n1", "target_node_id": "n2", "relationship_type": "prerequisite"},
    {"source_node_id": "n1", "target_node_id": "ghost", "relationship_type": "related"},
]


def _correct_payload():
    nodes = [{"id": n["id"]} for n in DB_NODES]
    nodes += [{"id": "subject_root__c-cs"}, {"id": "subject_root__c-math"}]
    edges = [{"id": "e1"}]  # the one drawable db edge (n1->n2)
    edges += [
        {"id": "subject_edge__subject_root__c-cs__n1"},
        {"id": "subject_edge__subject_root__c-cs__n2"},
        {"id": "subject_edge__subject_root__c-math__n3"},
    ]
    return {"nodes": nodes, "edges": edges, "stats": {}}


def test_correct_payload_yields_no_findings():
    assert graph_findings(_correct_payload(), DB_NODES, DB_EDGES, COURSES) == []


def test_355_shape_duplicate_root_and_spokes_all_reported():
    p = _correct_payload()
    p["nodes"].append({"id": "subject_root__c-cs"})  # dup hub
    p["edges"] += [
        {"id": "subject_edge__subject_root__c-cs__n1"},
        {"id": "subject_edge__subject_root__c-cs__n2"},
    ]
    fs = graph_findings(p, DB_NODES, DB_EDGES, COURSES)
    summaries = " | ".join(f.summary for f in fs)
    assert "subject_root__c-cs" in summaries          # dup id named
    assert any("node count" in f.summary.lower() for f in fs)
    assert any("edge count" in f.summary.lower() for f in fs)
    assert all(f.oracle == "graph" for f in fs)


def test_missing_subject_root_reported():
    p = _correct_payload()
    p["nodes"] = [n for n in p["nodes"] if n["id"] != "subject_root__c-math"]
    fs = graph_findings(p, DB_NODES, DB_EDGES, COURSES)
    assert any("subject_root__c-math" in f.summary for f in fs)


def test_ciphertext_judge_flags_plaintext_and_passes_real_ciphertext():
    from services.encryption import decrypt, encrypt

    rows = [("row1", encrypt("hello")), ("row2", "just plaintext"), ("row3", {"a": 1})]
    fs = ciphertext_findings("notes", "body", rows, decrypt)
    assert len(fs) == 2
    pks = {f.evidence["pk"] for f in fs}
    assert pks == {"row2", "row3"}
    # Raw value must be truncated in evidence, never full
    assert all(len(str(f.evidence.get("value_prefix", ""))) <= 32 for f in fs)


def test_count_judge():
    assert count_findings("documents", 3, 3) == []
    (f,) = count_findings("documents", 4, 3)
    assert "documents" in f.summary and f.evidence == {"api_count": 4, "db_count": 3}


def test_orphan_judge():
    assert orphan_findings("graph_edges→graph_nodes", []) == []
    (f,) = orphan_findings("graph_edges→graph_nodes", ["e-9"])
    assert "graph_edges" in f.summary and f.evidence["sample_ids"] == ["e-9"]
