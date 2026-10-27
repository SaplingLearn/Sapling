"""Per-question mastery attribution, wired through the quiz routes (§3.13).

`test_quiz_attribution.py` pins the pure logic. This file pins the part that
could only break in the route: that a multi-concept quiz pays each concept
separately, that it does so in ONE `apply_graph_update` call, and that the
pre-§3.13 behaviour survives for every quiz whose questions resolve to a
single node.

The one-call property is not a style preference. `apply_graph_update` bumps
the study streak and fires achievement checks whenever it writes any mastery
(graph_service.py:841), so a loop over nodes would count one quiz as N study
events.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _noop_ctx_agent():
    return AsyncMock(
        return_value=SimpleNamespace(output=SimpleNamespace(model_dump=lambda: {}))
    )


# Two questions, each naming a DIFFERENT concept — the case whole-attempt
# scoring got wrong.
MIXED_QUESTIONS = [
    {
        "id": 1,
        "text": "Which organelle makes ATP?",
        "concept_tested": "Mitochondria",
        "options": [{"label": "A", "correct": True}, {"label": "B", "correct": False}],
        "explanation": "A.",
    },
    {
        "id": 2,
        "text": "Where does translation happen?",
        "concept_tested": "Ribosomes",
        "options": [{"label": "C", "correct": False}, {"label": "D", "correct": True}],
        "explanation": "D.",
    },
]

COURSE_NODES = [
    {"id": "n-mito", "concept_name": "Mitochondria", "mastery_score": 0.5},
    {"id": "n-ribo", "concept_name": "Ribosomes", "mastery_score": 0.2},
]


def _factory(*, responses=None, questions=None, launched_from="n-mito"):
    """A table() factory covering submit's reads.

    `responses` stands in for rows recorded through /answer; None means the
    all-at-the-end client, where submit resolves names itself.
    """
    questions = questions if questions is not None else MIXED_QUESTIONS

    def factory(name):
        mock = MagicMock()
        if name == "quiz_attempts":
            mock.select.return_value = [{
                "id": "quiz1",
                "user_id": "user_andres",
                "concept_node_id": launched_from,
                "difficulty": "medium",
                "questions_json": questions,
            }]
        elif name == "quiz_responses":
            mock.select.return_value = responses or []
        elif name == "graph_nodes":
            # submit reads the launched-from node first, then the course's
            # nodes; both are served from the same fixture.
            mock.select.return_value = [
                {
                    "id": "n-mito",
                    "concept_name": "Mitochondria",
                    "mastery_score": 0.5,
                    "course_id": "course1",
                },
                {
                    "id": "n-ribo",
                    "concept_name": "Ribosomes",
                    "mastery_score": 0.2,
                    "course_id": "course1",
                },
            ]
        elif name == "users":
            mock.select.return_value = [{"name": "Andres"}]
        else:
            mock.select.return_value = []
        mock.update.return_value = [{"id": "updated"}]
        return mock

    return factory


def _submit(factory, apply_mock, answers=None):
    with (
        patch("routes.quiz.table", side_effect=factory),
        patch("routes.quiz.apply_graph_update", new=apply_mock),
        patch("routes.quiz.get_quiz_context", return_value={}),
        patch("routes.quiz.quiz_context_agent.run", new=_noop_ctx_agent()),
    ):
        return client.post("/api/quiz/submit", json={
            "quiz_id": "quiz1",
            "answers": answers if answers is not None else [
                {"question_id": 1, "selected_label": "A"},
                {"question_id": 2, "selected_label": "C"},
            ],
        })


class TestPerNodeAttribution:
    def test_a_mixed_quiz_pays_each_concept_separately(self):
        """One right, one wrong, on two different concepts."""
        apply_mock = MagicMock()

        r = _submit(_factory(), apply_mock)

        assert r.status_code == 200
        args, kwargs = apply_mock.call_args
        updated = {u["concept_name"]: u for u in args[1]["updated_nodes"]}

        assert set(updated) == {"Mitochondria", "Ribosomes"}
        assert updated["Mitochondria"]["mastery_delta"] > 0, "answered correctly"
        assert updated["Ribosomes"]["mastery_delta"] < 0, "answered incorrectly"

    def test_everything_lands_in_one_apply_graph_update_call(self):
        """A loop would bump the streak once per concept (graph_service:841)."""
        apply_mock = MagicMock()

        _submit(_factory(), apply_mock)

        apply_mock.assert_called_once()

    def test_each_node_gets_its_own_event_type(self):
        apply_mock = MagicMock()

        _submit(_factory(), apply_mock)

        updated = {u["concept_name"]: u for u in apply_mock.call_args[0][1]["updated_nodes"]}
        assert updated["Mitochondria"]["event_type"] == "quiz_correct"
        assert updated["Ribosomes"]["event_type"] == "quiz_confusion"

    def test_reason_reports_the_per_node_tally_not_the_attempt_score(self):
        apply_mock = MagicMock()

        _submit(_factory(), apply_mock)

        reasons = {u["concept_name"]: u["reason"] for u in
                   apply_mock.call_args[0][1]["updated_nodes"]}
        assert reasons["Mitochondria"] == "Quiz: 1/1 correct"
        assert reasons["Ribosomes"] == "Quiz: 0/1 correct"

    def test_recorded_responses_supply_the_node_without_re_resolving(self):
        """Questions answered through /answer already carry their node."""
        apply_mock = MagicMock()
        responses = [
            {"question_index": 0, "selected_index": 0, "concept_node_id": "n-mito"},
            {"question_index": 1, "selected_index": 0, "concept_node_id": "n-ribo"},
        ]

        r = _submit(_factory(responses=responses), apply_mock)

        assert r.status_code == 200
        updated = {u["concept_name"] for u in apply_mock.call_args[0][1]["updated_nodes"]}
        assert updated == {"Mitochondria", "Ribosomes"}

    def test_the_abstract_course_id_is_still_passed(self):
        apply_mock = MagicMock()

        _submit(_factory(), apply_mock)

        assert apply_mock.call_args[1]["course_id"] == "course1"


class TestBackwardCompatibility:
    """A single-concept quiz must score exactly as it did before §3.13."""

    SINGLE = [
        {
            "id": 1,
            "text": "Q1",
            "concept_tested": "Mitochondria",
            "options": [{"label": "A", "correct": True}, {"label": "B", "correct": False}],
            "explanation": "A.",
        },
        {
            "id": 2,
            "text": "Q2",
            "concept_tested": "Mitochondria",
            "options": [{"label": "C", "correct": True}, {"label": "D", "correct": False}],
            "explanation": "C.",
        },
    ]

    def test_single_concept_quiz_produces_one_updated_node(self):
        apply_mock = MagicMock()

        r = _submit(
            _factory(questions=self.SINGLE),
            apply_mock,
            answers=[
                {"question_id": 1, "selected_label": "A"},
                {"question_id": 2, "selected_label": "C"},
            ],
        )

        assert r.status_code == 200
        updated = apply_mock.call_args[0][1]["updated_nodes"]
        assert len(updated) == 1
        assert updated[0]["concept_name"] == "Mitochondria"
        assert updated[0]["reason"] == "Quiz: 2/2 correct"

    def test_questions_with_no_concept_fall_back_to_the_attempts_node(self):
        """Pre-§3.13 questions carry no `concept_tested` at all."""
        apply_mock = MagicMock()
        bare = [{**q, "concept_tested": None} for q in MIXED_QUESTIONS]

        r = _submit(_factory(questions=bare), apply_mock)

        assert r.status_code == 200
        updated = apply_mock.call_args[0][1]["updated_nodes"]
        assert len(updated) == 1, "all credit lands on the launched-from concept"
        assert updated[0]["concept_name"] == "Mitochondria"

    def test_a_name_matching_nothing_falls_back_rather_than_paying_nobody(self):
        apply_mock = MagicMock()
        unknown = [{**q, "concept_tested": "Golgi Apparatus"} for q in MIXED_QUESTIONS]

        r = _submit(_factory(questions=unknown), apply_mock)

        assert r.status_code == 200
        updated = apply_mock.call_args[0][1]["updated_nodes"]
        assert len(updated) == 1
        assert updated[0]["concept_name"] == "Mitochondria"

    def test_attempt_level_mastery_pair_tracks_the_launched_from_node(self):
        """§3.13 step 5: quiz_attempts.mastery_before/after is one pair and
        keeps meaning the attempt's own concept."""
        apply_mock = MagicMock()
        apply_mock.return_value = [
            {"concept": "Ribosomes", "before": 0.2, "after": 0.1},
            {"concept": "Mitochondria", "before": 0.5, "after": 0.53},
        ]

        r = _submit(_factory(), apply_mock)

        data = r.json()
        assert data["mastery_before"] == 0.5
        assert data["mastery_after"] == 0.53, "the Ribosomes change must not win"
