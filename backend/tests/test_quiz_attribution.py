"""Pins per-question mastery attribution (study roadmap §3.13).

The rule this suite most cares about is the one that is easy to "improve"
into a bug: a question whose concept matches nothing must NOT be fuzzily
credited to something nearby. An honest NULL is recoverable; mastery
silently moving on a concept the student was never asked about is not.
"""
from services.quiz_attribution import (
    group_responses,
    resolve_node_id,
    unattributed_count,
)

NODES = [
    {"id": "n-photo", "concept_name": "Photosynthesis"},
    {"id": "n-krebs", "concept_name": "Krebs Cycle"},
    {"id": "n-atp", "concept_name": "ATP Synthase"},
]


def response(node_id, correct=True):
    return {"concept_node_id": node_id, "is_correct": correct}


class TestResolveNodeId:
    def test_exact_name_matches(self):
        assert resolve_node_id("Krebs Cycle", NODES) == ("n-krebs", True)

    def test_casing_drift_matches(self):
        """LLM output casing is not stable; `_normalize_concept` case-folds."""
        assert resolve_node_id("krebs cycle", NODES) == ("n-krebs", True)

    def test_whitespace_drift_matches(self):
        assert resolve_node_id("  Krebs   Cycle ", NODES) == ("n-krebs", True)

    def test_unknown_name_does_not_fuzzy_match(self):
        """'Krebs' is close to 'Krebs Cycle' and must still miss."""
        node_id, matched = resolve_node_id("Krebs", NODES)

        assert matched is False
        assert node_id is None

    def test_miss_falls_back_to_the_attempts_node(self):
        node_id, matched = resolve_node_id("Unknown", NODES, fallback_node_id="n-photo")

        assert node_id == "n-photo"
        assert matched is False, "a fallback is a guess and must be reported as a miss"

    def test_empty_name_falls_back_without_matching(self):
        for value in (None, "", "   "):
            assert resolve_node_id(value, NODES, fallback_node_id="n-atp") == ("n-atp", False)

    def test_no_nodes_at_all(self):
        assert resolve_node_id("Photosynthesis", []) == (None, False)

    def test_node_missing_a_name_is_skipped_not_crashed(self):
        nodes = [{"id": "broken"}, {"id": "n-photo", "concept_name": "Photosynthesis"}]

        assert resolve_node_id("Photosynthesis", nodes) == ("n-photo", True)


class TestGroupResponses:
    def test_splits_credit_across_nodes(self):
        grouped = group_responses([
            response("n-photo", True),
            response("n-photo", False),
            response("n-krebs", True),
        ])

        assert grouped == {
            "n-photo": {"correct": 1, "total": 2},
            "n-krebs": {"correct": 1, "total": 1},
        }

    def test_unattributed_rows_fall_back_when_a_fallback_exists(self):
        grouped = group_responses(
            [response(None, True), response("n-krebs", True)],
            fallback_node_id="n-photo",
        )

        assert grouped["n-photo"] == {"correct": 1, "total": 1}

    def test_unattributed_rows_are_dropped_without_a_fallback(self):
        """Moving no mastery beats inflating whichever node is nearby."""
        grouped = group_responses([response(None, True), response("n-krebs", True)])

        assert grouped == {"n-krebs": {"correct": 1, "total": 1}}

    def test_all_questions_on_one_node_reproduces_whole_attempt_behaviour(self):
        """The migration path: a single-concept quiz must score as before."""
        grouped = group_responses([response("n-photo", True) for _ in range(5)])

        assert grouped == {"n-photo": {"correct": 5, "total": 5}}

    def test_ordering_follows_first_appearance(self):
        grouped = group_responses([
            response("n-krebs"), response("n-photo"), response("n-krebs"),
        ])

        assert list(grouped) == ["n-krebs", "n-photo"]

    def test_empty_input(self):
        assert group_responses([]) == {}


class TestUnattributedCount:
    def test_counts_rows_with_no_node(self):
        rows = [response("n-photo"), response(None), response(None)]

        assert unattributed_count(rows) == 2

    def test_zero_when_everything_resolved(self):
        assert unattributed_count([response("n-photo")]) == 0
