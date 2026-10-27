"""Pins the roadmap's ordering, freshness, and readiness rules.

These are the part of the feature most likely to be subtly wrong, and the
part no E2E journey can really interrogate — a Playwright test can see that
topics rendered, not that a prerequisite cycle degraded gracefully or that
the "why?" panel's arithmetic closes. Hence an exhaustive unit suite over
pure functions (`services/roadmap.py` takes rows, not a database).

Spec: .plans/course-study-roadmap-spec.md §3.1, §3.2, §3.6, §3.7.
"""
from datetime import date

import pytest

from services.roadmap import (
    FRESHNESS_FLOOR,
    build_hierarchy,
    freshness,
    order_roadmap,
    readiness,
    start_here_id,
    subtopic_readiness,
    topic_summary,
    topological_order,
)

TODAY = date(2026, 10, 27)


def node(nid, name, *, mastery=0.0, created="2026-01-01"):
    return {
        "id": nid,
        "concept_name": name,
        "mastery_score": mastery,
        "created_at": created,
    }


def edge(source, target, rel="part_of"):
    return {"source_node_id": source, "target_node_id": target, "relationship_type": rel}


# ── Hierarchy (§3.1) ────────────────────────────────────────────────────────


class TestBuildHierarchy:
    def test_part_of_children_become_subtopics(self):
        nodes = [node("t1", "Cell Structure"), node("c1", "Mitochondria")]
        result = build_hierarchy(nodes, [edge("c1", "t1")])

        assert len(result["topics"]) == 1
        assert result["topics"][0]["node"]["id"] == "t1"
        assert [s["id"] for s in result["topics"][0]["subtopics"]] == ["c1"]
        assert result["unfiled"] == []

    def test_ungrouped_concepts_are_unfiled_not_dropped(self):
        """§3.1: no concept may become invisible for lack of grouping."""
        nodes = [node("t1", "Topic"), node("c1", "Child"), node("x1", "Orphan")]
        result = build_hierarchy(nodes, [edge("c1", "t1")])

        assert [n["id"] for n in result["unfiled"]] == ["x1"]

    def test_everything_unfiled_when_no_part_of_edges_exist(self):
        """The common case on a freshly extracted graph."""
        nodes = [node("a", "A"), node("b", "B")]
        result = build_hierarchy(nodes, [edge("a", "b", rel="related")])

        assert result["topics"] == []
        assert len(result["unfiled"]) == 2

    def test_child_of_two_parents_is_filed_once(self):
        """A duplicated subtopic would be counted twice by readiness."""
        nodes = [node("t1", "T1"), node("t2", "T2"), node("c1", "Shared")]
        result = build_hierarchy(nodes, [edge("c1", "t1"), edge("c1", "t2")])

        filed = [s["id"] for t in result["topics"] for s in t["subtopics"]]
        assert filed == ["c1"]

    def test_edge_pointing_at_a_missing_node_is_ignored(self):
        nodes = [node("t1", "T1")]
        result = build_hierarchy(nodes, [edge("ghost", "t1")])

        assert result["topics"] == []
        assert [n["id"] for n in result["unfiled"]] == ["t1"]

    def test_self_edge_does_not_make_a_node_its_own_parent(self):
        nodes = [node("a", "A")]
        result = build_hierarchy(nodes, [edge("a", "a")])

        assert result["topics"] == []
        assert len(result["unfiled"]) == 1


# ── Ordering (§3.2) ─────────────────────────────────────────────────────────


class TestTopologicalOrder:
    def test_prerequisite_comes_first(self):
        nodes = [node("b", "Second"), node("a", "First")]
        ordered, cycles = topological_order(nodes, [edge("a", "b", rel="prerequisite")])

        assert [n["id"] for n in ordered] == ["a", "b"]
        assert cycles == set()

    def test_builds_on_orders_too(self):
        nodes = [node("b", "B"), node("a", "A")]
        ordered, _ = topological_order(nodes, [edge("a", "b", rel="builds_on")])

        assert [n["id"] for n in ordered] == ["a", "b"]

    def test_related_edges_impose_no_order(self):
        """`related` is symmetric — it carries no sequencing claim."""
        nodes = [node("b", "B", created="2026-01-02"), node("a", "A", created="2026-01-01")]
        ordered, _ = topological_order(nodes, [edge("b", "a", rel="related")])

        assert [n["id"] for n in ordered] == ["a", "b"]  # tie-break only

    def test_tie_break_is_created_at_then_name(self):
        nodes = [
            node("z", "Alpha", created="2026-03-01"),
            node("y", "Beta", created="2026-01-01"),
            node("x", "Alpha", created="2026-01-01"),
        ]
        ordered, _ = topological_order(nodes, [])

        assert [n["id"] for n in ordered] == ["x", "y", "z"]

    def test_missing_created_at_does_not_raise(self):
        nodes = [{"id": "a", "concept_name": "A"}, node("b", "B")]
        ordered, _ = topological_order(nodes, [])

        assert len(ordered) == 2

    def test_cycle_is_reported_not_raised(self):
        """A model-authored graph will eventually contain A->B->A."""
        nodes = [node("a", "A"), node("b", "B")]
        edges = [edge("a", "b", rel="prerequisite"), edge("b", "a", rel="prerequisite")]

        ordered, cycles = topological_order(nodes, edges)

        assert cycles == {"a", "b"}
        assert len(ordered) == 2, "every node must still be rendered"

    def test_partial_cycle_keeps_the_acyclic_part_ordered(self):
        nodes = [node("a", "A"), node("b", "B"), node("c", "C")]
        edges = [
            edge("a", "b", rel="prerequisite"),
            edge("b", "c", rel="prerequisite"),
            edge("c", "b", rel="prerequisite"),
        ]

        ordered, cycles = topological_order(nodes, edges)

        assert ordered[0]["id"] == "a"
        assert cycles == {"b", "c"}

    def test_duplicate_pair_across_both_edge_types_counts_once(self):
        """prerequisite + builds_on on the same pair must not double indegree."""
        nodes = [node("a", "A"), node("b", "B")]
        edges = [edge("a", "b", rel="prerequisite"), edge("a", "b", rel="builds_on")]

        ordered, cycles = topological_order(nodes, edges)

        assert [n["id"] for n in ordered] == ["a", "b"]
        assert cycles == set()

    def test_order_is_stable_across_input_permutations(self):
        """A list that reshuffles between visits loses the student's place."""
        nodes = [node("a", "A"), node("b", "B"), node("c", "C")]
        edges = [edge("a", "c", rel="prerequisite")]

        first, _ = topological_order(nodes, edges)
        second, _ = topological_order(list(reversed(nodes)), edges)

        assert [n["id"] for n in first] == [n["id"] for n in second]

    def test_empty_input(self):
        assert topological_order([], []) == ([], set())


class TestOrderRoadmap:
    def test_orders_topics_and_their_subtopics(self):
        nodes = [
            node("t2", "Second Topic"),
            node("t1", "First Topic"),
            node("s3", "Third Sub"),
            node("s2", "Second Sub"),
            node("s1", "First Sub"),
        ]
        edges = [
            edge("s1", "t1"),
            edge("s2", "t1"),
            edge("s3", "t2"),
            edge("t1", "t2", rel="prerequisite"),
            edge("s1", "s2", rel="prerequisite"),
        ]

        result = order_roadmap(build_hierarchy(nodes, edges), edges)

        assert [t["node"]["id"] for t in result["topics"]] == ["t1", "t2"]
        assert [s["id"] for s in result["topics"][0]["subtopics"]] == ["s1", "s2"]

    def test_collects_cycle_ids_from_every_level(self):
        nodes = [node("t1", "T"), node("s1", "S1"), node("s2", "S2")]
        edges = [
            edge("s1", "t1"),
            edge("s2", "t1"),
            edge("s1", "s2", rel="prerequisite"),
            edge("s2", "s1", rel="prerequisite"),
        ]

        result = order_roadmap(build_hierarchy(nodes, edges), edges)

        assert result["cycle_node_ids"] == {"s1", "s2"}


class TestStartHere:
    def test_points_at_the_first_unmastered_topic(self):
        topics = [
            {"node": node("t1", "Done"), "subtopics": [node("s1", "S", mastery=0.9)]},
            {"node": node("t2", "Next"), "subtopics": [node("s2", "S", mastery=0.2)]},
        ]
        assert start_here_id(topics) == "t2"

    def test_none_when_everything_is_mastered(self):
        topics = [{"node": node("t1", "Done"), "subtopics": [node("s1", "S", mastery=0.8)]}]
        assert start_here_id(topics) is None

    def test_childless_topic_is_judged_on_itself(self):
        """`build_hierarchy` cannot produce this shape (a node with no
        `part_of` children is unfiled, not a topic), but `start_here_id` is
        called on caller-assembled lists too — so it must not divide by an
        empty subtopic list."""
        topics = [{"node": node("t1", "Lonely", mastery=0.1), "subtopics": []}]
        assert start_here_id(topics) == "t1"


# ── Freshness (§3.7) ────────────────────────────────────────────────────────


class TestFreshness:
    def test_no_exam_means_no_decay(self):
        """A student with no exam is not told their knowledge rots on a
        schedule we invented."""
        factor, stale = freshness("2026-01-01", None, today=TODAY)

        assert factor == 1.0
        assert stale is False

    def test_never_answered_correctly_is_not_discounted(self):
        """mastery is already 0; discounting again double-counts the same
        absence of evidence."""
        factor, stale = freshness(None, "2026-11-05", today=TODAY)

        assert factor == 1.0
        assert stale is False

    def test_proved_today_is_fully_fresh(self):
        factor, stale = freshness(TODAY, date(2026, 11, 5), today=TODAY)

        assert factor == 1.0
        assert stale is False

    def test_half_stale_hits_the_threshold(self):
        """d/D == 0.5 — last proved as long ago as half the time remaining."""
        # exam in 10 days, last correct 5 days ago
        factor, stale = freshness(date(2026, 10, 22), date(2026, 11, 6), today=TODAY)

        assert factor == pytest.approx(1.0 - (1.0 - FRESHNESS_FLOOR) * 0.5)
        assert stale is True

    def test_long_cold_clamps_to_the_floor(self):
        factor, stale = freshness(date(2026, 1, 1), date(2026, 11, 5), today=TODAY)

        assert factor == FRESHNESS_FLOOR
        assert stale is True

    def test_is_exam_relative_not_absolute(self):
        """The same subtopic is stale for Friday and fresh for June (§3.7)."""
        last = date(2026, 10, 7)  # 20 days cold

        near, near_stale = freshness(last, date(2026, 11, 5), today=TODAY)  # 9 days out
        far, far_stale = freshness(last, date(2027, 6, 1), today=TODAY)  # far out

        assert near < far
        assert near_stale is True
        assert far_stale is False

    def test_exam_today_does_not_divide_by_zero(self):
        factor, _ = freshness(date(2026, 10, 20), TODAY, today=TODAY)

        assert factor == FRESHNESS_FLOOR

    def test_exam_in_the_past_still_returns_a_valid_factor(self):
        factor, _ = freshness(date(2026, 10, 20), date(2026, 10, 1), today=TODAY)

        assert FRESHNESS_FLOOR <= factor <= 1.0

    def test_future_last_correct_does_not_exceed_one(self):
        """Clock skew between the DB and the app must not inflate readiness."""
        factor, _ = freshness(date(2026, 11, 1), date(2026, 12, 1), today=TODAY)

        assert factor == 1.0

    @pytest.mark.parametrize(
        "value",
        ["2026-10-20", "2026-10-20T14:30:00+00:00", "2026-10-20T14:30:00Z", date(2026, 10, 20)],
    )
    def test_accepts_the_date_shapes_postgrest_and_tests_both_emit(self, value):
        factor, _ = freshness(value, date(2026, 11, 5), today=TODAY)

        assert factor < 1.0

    def test_unparseable_date_degrades_to_fresh_rather_than_raising(self):
        factor, stale = freshness("not a date", date(2026, 11, 5), today=TODAY)

        assert factor == 1.0
        assert stale is False


# ── Readiness (§3.6) ────────────────────────────────────────────────────────


class TestReadiness:
    def test_weighted_mean_of_mastery_times_freshness(self):
        rows = [
            subtopic_readiness(node("a", "A", mastery=1.0)),
            subtopic_readiness(node("b", "B", mastery=0.0)),
        ]
        assert readiness(rows) == pytest.approx(0.5)

    def test_weights_shift_the_result(self):
        rows = [
            subtopic_readiness(node("a", "A", mastery=1.0), weight=3.0),
            subtopic_readiness(node("b", "B", mastery=0.0), weight=1.0),
        ]
        assert readiness(rows) == pytest.approx(0.75)

    def test_staleness_reduces_readiness_without_touching_mastery(self):
        """§3.5/§11: the stored number is untouched; only the ring moves."""
        n = node("a", "A", mastery=1.0)
        row = subtopic_readiness(
            n, last_correct_at=date(2026, 1, 1), exam_date=date(2026, 11, 5), today=TODAY
        )

        assert row["contribution"] == pytest.approx(FRESHNESS_FLOOR)
        assert n["mastery_score"] == 1.0, "mastery_score must never be mutated here"

    def test_empty_scope_is_zero_not_one(self):
        """Claiming readiness for an empty scope is the worst lie available."""
        assert readiness([]) == 0.0

    def test_zero_total_weight_does_not_divide_by_zero(self):
        rows = [subtopic_readiness(node("a", "A", mastery=1.0), weight=0.0)]

        assert readiness(rows) == 0.0

    def test_breakdown_rows_reproduce_the_overall_figure(self):
        """The 'why?' panel can never print a number the formula didn't make."""
        rows = [
            subtopic_readiness(node("a", "A", mastery=0.8), weight=2.0),
            subtopic_readiness(node("b", "B", mastery=0.3), weight=1.0),
        ]
        total = sum(r["contribution"] for r in rows) / sum(r["weight"] for r in rows)

        assert readiness(rows) == pytest.approx(total)

    def test_missing_mastery_score_reads_as_zero(self):
        row = subtopic_readiness({"id": "a", "concept_name": "A"})

        assert row["mastery"] == 0.0
        assert row["contribution"] == 0.0

    def test_tier_is_derived_when_the_row_lacks_one(self):
        row = subtopic_readiness(node("a", "A", mastery=0.8))

        assert row["tier"] == "mastered"

    def test_stored_tier_wins_over_the_derived_one(self):
        n = node("a", "A", mastery=0.8)
        n["mastery_tier"] = "learning"

        assert subtopic_readiness(n)["tier"] == "learning"


class TestTopicSummary:
    def test_reports_counts_not_averages(self):
        rows = [
            subtopic_readiness(node("a", "A", mastery=0.9)),
            subtopic_readiness(node("b", "B", mastery=0.5)),
            subtopic_readiness(node("c", "C", mastery=0.0)),
        ]
        summary = topic_summary(rows)

        assert summary["total"] == 3
        assert summary["mastered"] == 1
        assert summary["started"] == 2

    def test_counts_stale_subtopics(self):
        rows = [
            subtopic_readiness(
                node("a", "A", mastery=0.9),
                last_correct_at=date(2026, 1, 1),
                exam_date=date(2026, 11, 5),
                today=TODAY,
            ),
            subtopic_readiness(node("b", "B", mastery=0.9)),
        ]

        assert topic_summary(rows)["stale"] == 1

    def test_empty_topic(self):
        summary = topic_summary([])

        assert summary == {
            "total": 0,
            "mastered": 0,
            "stale": 0,
            "started": 0,
            "readiness": 0.0,
        }
