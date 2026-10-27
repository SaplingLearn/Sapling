"""GET /api/roadmap/{course_id} — shape, scoping, caching.

`test_roadmap_service.py` pins the arithmetic. This file pins what only the
route can get wrong: that it refuses another user's course, that a
cross-course edge cannot drag a foreign concept into the ordering, that the
caching headers stay private, and that the empty-graph state is reported
rather than inferred.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

USER = "user_andres"
COURSE = "course1"


def node(nid, name, *, mastery=0.0, course=COURSE, created="2026-01-01"):
    return {
        "id": nid,
        "concept_name": name,
        "mastery_score": mastery,
        "mastery_tier": None,
        "times_studied": 0,
        "last_studied_at": None,
        "color": "#4FA574",
        "course_id": course,
        "created_at": created,
    }


def edge(source, target, rel="part_of"):
    return {
        "source_node_id": source,
        "target_node_id": target,
        "relationship_type": rel,
        "strength": 0.5,
    }


def _factory(*, nodes=None, edges=None, exams=None, responses=None, offerings=("off1",)):
    """table() factory covering the roadmap route's reads."""

    def factory(name):
        mock = MagicMock()
        if name == "graph_nodes":
            mock.select.return_value = nodes if nodes is not None else []
        elif name == "graph_edges":
            mock.select.return_value = edges or []
        elif name == "course_offerings":
            mock.select.return_value = [{"id": o} for o in offerings]
        elif name == "enrollments":
            mock.select.return_value = [
                {"id": "enr1", "offering_id": o} for o in offerings
            ]
        elif name == "assignments":
            mock.select.return_value = exams or []
        elif name == "quiz_attempts":
            mock.select.return_value = [{"id": "att1"}] if responses else []
        elif name == "quiz_responses":
            mock.select.return_value = responses or []
        else:
            mock.select.return_value = []
        return mock

    return factory


def _get(factory, path=f"/api/roadmap/{COURSE}?user_id={USER}", headers=None):
    with (
        patch("routes.roadmap.table", side_effect=factory),
        patch("services.academics.table", side_effect=factory),
        patch("routes.roadmap.require_self"),
    ):
        return client.get(path, headers=headers or {})


class TestPayloadShape:
    def test_groups_subtopics_under_their_topic(self):
        r = _get(_factory(
            nodes=[node("t1", "Cell Structure"), node("s1", "Mitochondria")],
            edges=[edge("s1", "t1")],
        ))

        assert r.status_code == 200
        data = r.json()
        assert len(data["topics"]) == 1
        assert data["topics"][0]["concept_name"] == "Cell Structure"
        assert [s["concept_name"] for s in data["topics"][0]["subtopics"]] == ["Mitochondria"]

    def test_ungrouped_concepts_are_reported_as_unfiled(self):
        r = _get(_factory(nodes=[node("x1", "Orphan")]))

        data = r.json()
        assert data["topics"] == []
        assert [u["concept_name"] for u in data["unfiled"]] == ["Orphan"]

    def test_needs_structure_is_explicit_not_inferred(self):
        """§3.16: the flat-list state is a state, not an error the client
        has to deduce from an empty array."""
        r = _get(_factory(nodes=[node("x1", "Orphan")]))

        assert r.json()["needs_structure"] is True

    def test_needs_structure_is_false_when_the_course_is_empty(self):
        r = _get(_factory(nodes=[]))

        data = r.json()
        assert data["needs_structure"] is False
        assert data["topics"] == []

    def test_topic_summary_reports_counts(self):
        r = _get(_factory(
            nodes=[
                node("t1", "Topic"),
                node("s1", "Known", mastery=0.9),
                node("s2", "Unknown", mastery=0.0),
            ],
            edges=[edge("s1", "t1"), edge("s2", "t1")],
        ))

        summary = r.json()["topics"][0]["summary"]
        assert summary["total"] == 2
        assert summary["mastered"] == 1

    def test_unfiled_concepts_count_toward_readiness(self):
        """Excluding them would let the ring read 100% with a third of the
        course sitting ungrouped below it."""
        r = _get(_factory(
            nodes=[
                node("t1", "Topic"),
                node("s1", "Known", mastery=1.0),
                node("x1", "Ungrouped", mastery=0.0),
            ],
            edges=[edge("s1", "t1")],
        ))

        assert r.json()["readiness"] < 1.0

    def test_start_here_points_at_the_first_unmastered_topic(self):
        r = _get(_factory(
            nodes=[node("t1", "Topic"), node("s1", "Sub", mastery=0.1)],
            edges=[edge("s1", "t1")],
        ))

        data = r.json()
        assert data["start_here_topic_id"] == "t1"
        assert data["start_here_unfiled"] is False

    def test_start_here_falls_back_to_unfiled_work(self):
        """Regression, found against the live seed: one mastered topic plus
        untouched unfiled concepts must not report "nothing to start" while
        readiness is well under 100%."""
        r = _get(_factory(
            nodes=[
                node("t1", "Topic"),
                node("s1", "Sub", mastery=0.9),
                node("x1", "Untouched", mastery=0.0),
            ],
            edges=[edge("s1", "t1")],
        ))

        data = r.json()
        assert data["start_here_topic_id"] is None
        assert data["start_here_unfiled"] is True
        assert data["readiness"] < 1.0


class TestScoping:
    def test_a_cross_course_edge_cannot_pull_in_a_foreign_concept(self):
        """graph_edges has no course_id, so the route filters on BOTH
        endpoints being in this course's node set."""
        r = _get(_factory(
            nodes=[node("t1", "Topic"), node("s1", "Mine")],
            edges=[edge("s1", "t1"), edge("foreign", "t1")],
        ))

        subs = r.json()["topics"][0]["subtopics"]
        assert [s["concept_name"] for s in subs] == ["Mine"]

    def test_require_self_guards_the_route(self):
        with (
            patch("routes.roadmap.table", side_effect=_factory()),
            patch("routes.roadmap.require_self", side_effect=AssertionError("guarded")),
        ):
            try:
                client.get(f"/api/roadmap/{COURSE}?user_id=someone_else")
            except AssertionError as exc:
                assert "guarded" in str(exc)
            else:
                raise AssertionError("require_self was not called")


class TestExams:
    EXAMS = [
        {"id": "e2", "title": "Final", "due_date": "2026-12-16",
         "assignment_type": "exam", "enrollment_id": "enr1"},
        {"id": "e1", "title": "Midterm 2", "due_date": "2026-11-05",
         "assignment_type": "exam", "enrollment_id": "enr1"},
    ]

    def test_exams_are_returned_soonest_first(self):
        r = _get(_factory(nodes=[node("x1", "A")], exams=self.EXAMS))

        assert [e["id"] for e in r.json()["exams"]] == ["e1", "e2"]

    def test_an_undated_exam_is_dropped(self):
        """An exam you can't date can't anchor freshness or be chosen."""
        exams = self.EXAMS + [{
            "id": "e3", "title": "TBD", "due_date": None,
            "assignment_type": "exam", "enrollment_id": "enr1",
        }]
        r = _get(_factory(nodes=[node("x1", "A")], exams=exams))

        assert "e3" not in [e["id"] for e in r.json()["exams"]]

    def test_an_unknown_exam_id_degrades_to_course_readiness(self):
        r = _get(
            _factory(nodes=[node("x1", "A")], exams=self.EXAMS),
            path=f"/api/roadmap/{COURSE}?user_id={USER}&exam_id=nope",
        )

        assert r.status_code == 200
        assert r.json()["selected_exam"] is None

    def test_no_enrollment_means_no_exams_not_an_error(self):
        r = _get(_factory(nodes=[node("x1", "A")], offerings=()))

        assert r.status_code == 200
        assert r.json()["exams"] == []


class TestCaching:
    def test_cache_control_is_private(self):
        """These payloads are user-scoped and app-decrypted — a shared proxy
        must never hold them."""
        r = _get(_factory(nodes=[node("x1", "A")]))

        assert "private" in r.headers["cache-control"]
        assert "public" not in r.headers["cache-control"]

    def test_etag_is_returned_and_honoured(self):
        factory = _factory(nodes=[node("x1", "A")])
        first = _get(factory)
        etag = first.headers["etag"]

        second = _get(factory, headers={"If-None-Match": etag})

        assert second.status_code == 304

    def test_etag_changes_when_the_graph_changes(self):
        one = _get(_factory(nodes=[node("x1", "A")]))
        two = _get(_factory(nodes=[node("x1", "A"), node("x2", "B")]))

        assert one.headers["etag"] != two.headers["etag"]


class TestReadinessBreakdown:
    def test_factors_reproduce_the_overall_figure(self):
        factory = _factory(
            nodes=[
                node("t1", "Topic"),
                node("s1", "Known", mastery=0.8),
                node("s2", "Partial", mastery=0.4),
            ],
            edges=[edge("s1", "t1"), edge("s2", "t1")],
        )
        r = _get(factory, path=f"/api/roadmap/{COURSE}/readiness?user_id={USER}")

        assert r.status_code == 200
        data = r.json()
        total_w = sum(f["weight"] for f in data["factors"])
        total_c = sum(f["contribution"] for f in data["factors"])
        assert data["readiness"] == (total_c / total_w)

    def test_unfiled_concepts_appear_as_their_own_factor_row(self):
        factory = _factory(
            nodes=[node("t1", "Topic"), node("s1", "Sub"), node("x1", "Loose")],
            edges=[edge("s1", "t1")],
        )
        r = _get(factory, path=f"/api/roadmap/{COURSE}/readiness?user_id={USER}")

        names = [f["concept_name"] for f in r.json()["factors"]]
        assert "Unfiled concepts" in names
