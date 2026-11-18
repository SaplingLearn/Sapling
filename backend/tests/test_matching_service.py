"""services/matching_service.find_study_matches: the study-partner scorer behind
GET /api/social/.../matches. A pure function over member graphs."""

import json
import os
import subprocess
import sys
from pathlib import Path

from services.matching_service import find_study_matches


def _node(concept, mastery, subject="CS"):
    return {"concept_name": concept, "mastery_score": mastery, "subject": subject}


def _member(uid, name, nodes):
    return {"user_id": uid, "name": name, "graph": {"nodes": nodes}}


def test_unknown_user_gets_no_matches():
    assert find_study_matches("ghost", [_member("a", "A", [_node("x", 0.5)])]) == []


def test_never_matches_you_with_yourself():
    me = _member("me", "Me", [_node("x", 0.9)])
    assert find_study_matches("me", [me]) == []


def test_classifies_teach_learn_and_shared_struggles():
    me = _member("me", "Me", [_node("recursion", 0.9), _node("graphs", 0.2), _node("dp", 0.1)])
    them = _member("t", "Taylor", [_node("recursion", 0.3), _node("graphs", 0.8), _node("dp", 0.2)])
    [m] = find_study_matches("me", [me, them])

    assert m["partner"] == {"id": "t", "name": "Taylor"}
    assert [t["concept"] for t in m["you_can_teach"]] == ["recursion"]
    assert [t["concept"] for t in m["they_can_teach"]] == ["graphs"]
    assert [t["concept"] for t in m["shared_struggles"]] == ["dp"]
    assert m["summary"] == (
        "Both studying CS; Taylor can help you with graphs; "
        "you can help them with recursion; you can tackle dp together."
    )
    assert 18 <= m["compatibility_score"] <= 92


def test_mastery_on_a_0_to_100_scale_is_normalized():
    me = _member("me", "Me", [_node("x", 90)])
    them = _member("t", "T", [_node("x", 20)])
    [m] = find_study_matches("me", [me, them])
    assert m["you_can_teach"] == [{"concept": "x", "your_mastery": 0.9, "their_mastery": 0.2}]


def test_missing_mastery_counts_as_zero():
    me = _member("me", "Me", [_node("x", None)])
    them = _member("t", "T", [_node("x", 0.9)])
    [m] = find_study_matches("me", [me, them])
    assert m["they_can_teach"][0]["your_mastery"] == 0.0


def test_subject_roots_are_ignored():
    root = {"concept_name": "CS", "mastery_score": 0.0, "subject": "CS", "is_subject_root": True}
    me = _member("me", "Me", [root, _node("x", 0.9)])
    them = _member("t", "T", [dict(root), _node("x", 0.1)])
    [m] = find_study_matches("me", [me, them])
    assert [t["concept"] for t in m["you_can_teach"]] == ["x"]
    assert m["shared_struggles"] == []


def test_score_is_clamped_and_results_sorted_best_first():
    me = _member("me", "Me", [_node(f"c{i}", 0.9, "CS") for i in range(6)])
    strong_fit = _member("a", "A", [_node(f"c{i}", 0.1, "CS") for i in range(6)])
    no_overlap = _member("b", "B", [_node("other", 0.5, "Art")])
    results = find_study_matches("me", [me, no_overlap, strong_fit])

    assert [r["partner"]["id"] for r in results] == ["a", "b"]
    assert results[0]["compatibility_score"] <= 92
    assert results[1]["compatibility_score"] == 18  # floor
    assert results[1]["summary"] == "Overlapping study areas with complementary knowledge."
    assert len(results[0]["you_can_teach"]) == 5  # capped


def test_shared_struggles_are_weakest_first_and_capped():
    masteries = {"a": 0.4, "b": 0.0, "c": 0.3, "d": 0.1, "e": 0.2, "f": 0.45, "g": 0.05}
    me = _member("me", "Me", [_node(k, v) for k, v in masteries.items()])
    them = _member("t", "T", [_node(k, v) for k, v in masteries.items()])
    [m] = find_study_matches("me", [me, them])
    assert [s["concept"] for s in m["shared_struggles"]] == ["b", "g", "d", "e", "c"]


def test_result_does_not_depend_on_the_process_hash_seed():
    """Concepts used to be walked in set order, which Python randomizes per
    process for strings: two workers could keep different struggles and name a
    different concept in the summary for the same graphs."""
    script = (
        "import json\n"
        "from services.matching_service import find_study_matches\n"
        "names = [f'concept-{i}' for i in range(12)]\n"
        "me = {'user_id': 'me', 'name': 'Me', 'graph': {'nodes': ["
        "{'concept_name': n, 'mastery_score': 0.2, 'subject': 'CS'} for n in names]}}\n"
        "them = {'user_id': 't', 'name': 'T', 'graph': {'nodes': ["
        "{'concept_name': n, 'mastery_score': 0.2, 'subject': 'CS'} for n in names]}}\n"
        "print(json.dumps(find_study_matches('me', [me, them])))\n"
    )
    backend = Path(__file__).resolve().parent.parent
    outputs = set()
    for seed in ("1", "2", "3", "4"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run(
            [sys.executable, "-c", script], cwd=backend, env=env,
            capture_output=True, text=True, check=True,
        ).stdout
        outputs.add(out)
        json.loads(out)
    assert len(outputs) == 1
