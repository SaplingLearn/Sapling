"""
Unit tests for routes/quiz.py

Covers:
- Mastery score update formula (scoring math)
- POST /api/quiz/submit — answer grading and result shape
- POST /api/quiz/submit — 404 when quiz not found
- POST /api/quiz/generate — agent success path (quiz_agent.run mocked)
- POST /api/quiz/generate — agent failure falls back to legacy
"""
import pytest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from main import app
from agents.quiz import Quiz, QuizQuestion

client = TestClient(app)


# ── Scoring formula (pure logic, no HTTP) ────────────────────────────────────

class TestMasteryScoreFormula:
    """
    The formula in submit_quiz:
        mastery_after = clamp(mastery_before + (correct * 0.03) - (wrong * 0.02), 0.0, 1.0)
    """

    def _calc(self, before: float, correct: int, total: int) -> float:
        wrong = total - correct
        return max(0.0, min(1.0, before + (correct * 0.03) - (wrong * 0.02)))

    def test_perfect_score_increases_mastery(self):
        assert self._calc(0.5, 5, 5) == pytest.approx(0.5 + 0.15)

    def test_zero_score_decreases_mastery(self):
        assert self._calc(0.5, 0, 5) == pytest.approx(0.5 - 0.10)

    def test_partial_score(self):
        # 3 correct (+0.09), 2 wrong (-0.04)
        assert self._calc(0.5, 3, 5) == pytest.approx(0.55)

    def test_mastery_clamped_at_1(self):
        assert self._calc(0.95, 5, 5) == 1.0

    def test_mastery_clamped_at_0(self):
        assert self._calc(0.05, 0, 5) == 0.0

    def test_mastery_unchanged_when_score_balances_out(self):
        # e.g. 2 correct (+0.06) vs 3 wrong (-0.06) ≈ no change
        assert self._calc(0.5, 2, 5) == pytest.approx(0.5)


# ── POST /api/quiz/submit ────────────────────────────────────────────────────

SAMPLE_QUESTIONS = [
    {
        "id": 1,
        "text": "What does a for-loop do?",
        "options": [
            {"label": "A", "correct": True},
            {"label": "B", "correct": False},
        ],
        "explanation": "A is correct.",
    },
    {
        "id": 2,
        "text": "What is a function?",
        "options": [
            {"label": "C", "correct": False},
            {"label": "D", "correct": True},
        ],
        "explanation": "D is correct.",
    },
]


def _make_table(questions=None):
    """Return a table factory with sane defaults for quiz submission tests."""
    q = questions or SAMPLE_QUESTIONS

    def factory(name):
        mock = MagicMock()
        if name == "quiz_attempts":
            mock.select.return_value = [{
                "id": "quiz1",
                "user_id": "user_andres",
                "concept_node_id": "node1",
                "difficulty": "medium",
                "questions_json": q,
            }]
        elif name == "graph_nodes":
            mock.select.return_value = [{"mastery_score": 0.5, "times_studied": 2, "concept_name": "Loops"}]
        elif name == "users":
            mock.select.return_value = [{"name": "Andres"}]
        else:
            mock.select.return_value = []
        mock.update.return_value = []
        return mock

    return factory


@contextmanager
def _submit_quiz_mocks(questions=None):
    with (
        patch("routes.quiz.table", side_effect=_make_table(questions)),
        patch("routes.quiz.update_streak"),
        patch("routes.quiz.get_quiz_context", return_value={}),
        patch("routes.quiz.call_gemini_json", return_value={}),
    ):
        yield


class TestSubmitQuiz:
    def test_all_correct_returns_full_score(self):
        with _submit_quiz_mocks():
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [
                    {"question_id": 1, "selected_label": "A"},
                    {"question_id": 2, "selected_label": "D"},
                ],
            })
        assert r.status_code == 200
        data = r.json()
        assert data["score"] == 2
        assert data["total"] == 2

    def test_all_wrong_returns_zero_score(self):
        with _submit_quiz_mocks():
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [
                    {"question_id": 1, "selected_label": "B"},
                    {"question_id": 2, "selected_label": "C"},
                ],
            })
        assert r.status_code == 200
        assert r.json()["score"] == 0

    def test_result_shape_contains_required_fields(self):
        with _submit_quiz_mocks():
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "A"}],
            })
        data = r.json()
        assert "score" in data
        assert "total" in data
        assert "mastery_before" in data
        assert "mastery_after" in data
        assert "results" in data

    def test_each_result_has_correct_flag(self):
        with _submit_quiz_mocks():
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [
                    {"question_id": 1, "selected_label": "A"},  # correct
                    {"question_id": 2, "selected_label": "C"},  # wrong
                ],
            })
        results = r.json()["results"]
        correct_flags = {str(res["question_id"]): res["correct"] for res in results}
        assert correct_flags["1"] is True
        assert correct_flags["2"] is False

    def test_mastery_after_is_higher_on_perfect_score(self):
        with _submit_quiz_mocks():
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [
                    {"question_id": 1, "selected_label": "A"},
                    {"question_id": 2, "selected_label": "D"},
                ],
            })
        data = r.json()
        assert data["mastery_after"] > data["mastery_before"]

    def test_mastery_after_is_lower_on_zero_score(self):
        with _submit_quiz_mocks():
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [
                    {"question_id": 1, "selected_label": "B"},
                    {"question_id": 2, "selected_label": "C"},
                ],
            })
        data = r.json()
        assert data["mastery_after"] < data["mastery_before"]

    def test_returns_404_for_nonexistent_quiz(self):
        with patch("routes.quiz.table") as t:
            t.return_value.select.return_value = []
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "does-not-exist",
                "answers": [],
            })
        assert r.status_code == 404

    def test_questions_json_as_string_is_parsed(self):
        """quiz_attempts.questions_json can arrive as a JSON string from the DB."""
        import json as _json

        def factory(name):
            mock = MagicMock()
            if name == "quiz_attempts":
                mock.select.return_value = [{
                    "id": "quiz1",
                    "user_id": "user_andres",
                    "concept_node_id": "node1",
                    "difficulty": "medium",
                    "questions_json": _json.dumps(SAMPLE_QUESTIONS),  # serialised string
                }]
            elif name == "graph_nodes":
                mock.select.return_value = [{"mastery_score": 0.5, "times_studied": 0, "concept_name": "Loops"}]
            elif name == "users":
                mock.select.return_value = [{"name": "Andres"}]
            else:
                mock.select.return_value = []
            mock.update.return_value = []
            return mock

        with patch("routes.quiz.table", side_effect=factory):
            with patch("routes.quiz.update_streak"):
                with patch("routes.quiz.get_quiz_context", return_value={}):
                    with patch("routes.quiz.call_gemini_json", return_value={}):
                        r = client.post("/api/quiz/submit", json={
                            "quiz_id": "quiz1",
                            "answers": [
                                {"question_id": 1, "selected_label": "A"},
                                {"question_id": 2, "selected_label": "D"},
                            ],
                        })

        assert r.status_code == 200
        assert r.json()["score"] == 2


# ── POST /api/quiz/generate ──────────────────────────────────────────────────


def _generate_table_factory(*, course_id: str = "course1", concept_name: str = "Loops"):
    """Return a table factory that satisfies generate_quiz's DB reads."""

    def factory(name):
        mock = MagicMock()
        if name == "graph_nodes":
            mock.select.return_value = [{
                "id": "node1",
                "course_id": course_id,
                "concept_name": concept_name,
                "mastery_score": 0.5,
            }]
        elif name == "quiz_attempts":
            mock.insert.return_value = [{"id": "quiz-generated"}]
        else:
            mock.select.return_value = []
            mock.insert.return_value = []
        return mock

    return factory


class TestQuizAgentSuccess:
    """Happy path: quiz_agent.run returns a Quiz, route persists + responds."""

    def test_returns_agent_output_in_legacy_wire_shape(self):
        fake_quiz = Quiz(questions=[
            QuizQuestion(
                question="What is 2+2?",
                type="multiple_choice",
                difficulty="easy",
                options=["3", "4", "5", "6"],
                correct_answer="4",
                explanation="Basic arithmetic.",
                concept="Arithmetic",
            ),
        ])
        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch(
                "routes.quiz.quiz_agent.run",
                new=AsyncMock(return_value=SimpleNamespace(output=fake_quiz)),
            ),
        ):
            r = client.post("/api/quiz/generate", json={
                "user_id": "user_andres",
                "concept_node_id": "node1",
                "num_questions": 1,
                "difficulty": "easy",
                "use_shared_context": False,
            })

        assert r.status_code == 200
        data = r.json()
        assert "quiz_id" in data
        assert isinstance(data["questions"], list)
        assert len(data["questions"]) == 1

        q = data["questions"][0]
        # Wire format must match the legacy shape submit_quiz expects.
        assert q["id"] == 1
        assert q["question"] == "What is 2+2?"
        assert q["explanation"] == "Basic arithmetic."
        assert q["concept_tested"] == "Arithmetic"
        assert q["difficulty"] == "easy"
        assert isinstance(q["options"], list)
        assert len(q["options"]) == 4
        # Each option has label/text/correct.
        labels = [o["label"] for o in q["options"]]
        assert labels == ["A", "B", "C", "D"]
        # Exactly one correct option, and it's the one whose text == "4".
        correct = [o for o in q["options"] if o["correct"]]
        assert len(correct) == 1
        assert correct[0]["text"] == "4"

    def test_short_answer_question_keeps_grading_compatibility(self):
        """short_answer questions get a synthetic options list so submit_quiz
        (which assumes options[].correct exists) keeps grading."""
        fake_quiz = Quiz(questions=[
            QuizQuestion(
                question="Define a closure.",
                type="short_answer",
                difficulty="medium",
                options=[],
                correct_answer="A function bundled with its surrounding state.",
                explanation="Lexical scope retention.",
                concept="Closures",
            ),
        ])
        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch(
                "routes.quiz.quiz_agent.run",
                new=AsyncMock(return_value=SimpleNamespace(output=fake_quiz)),
            ),
        ):
            r = client.post("/api/quiz/generate", json={
                "user_id": "user_andres",
                "concept_node_id": "node1",
                "num_questions": 1,
                "difficulty": "medium",
                "use_shared_context": False,
            })

        assert r.status_code == 200
        q = r.json()["questions"][0]
        assert len(q["options"]) == 1
        assert q["options"][0]["correct"] is True
        assert q["options"][0]["label"] == "A"

    def test_persists_to_quiz_attempts_table(self):
        fake_quiz = Quiz(questions=[
            QuizQuestion(
                question="Q?",
                type="multiple_choice",
                difficulty="easy",
                options=["a", "b", "c", "d"],
                correct_answer="a",
                explanation="ok",
                concept="X",
            ),
        ])
        # Capture the insert call so we can assert what's stored.
        captured = {}

        def factory(name):
            mock = MagicMock()
            if name == "graph_nodes":
                mock.select.return_value = [{
                    "id": "node1",
                    "course_id": "course1",
                    "concept_name": "X",
                    "mastery_score": 0.5,
                }]
            elif name == "quiz_attempts":
                def _capture(payload):
                    captured["payload"] = payload
                    return [{"id": payload["id"]}]
                mock.insert.side_effect = _capture
            return mock

        with (
            patch("routes.quiz.table", side_effect=factory),
            patch(
                "routes.quiz.quiz_agent.run",
                new=AsyncMock(return_value=SimpleNamespace(output=fake_quiz)),
            ),
        ):
            r = client.post("/api/quiz/generate", json={
                "user_id": "user_andres",
                "concept_node_id": "node1",
                "num_questions": 1,
                "difficulty": "easy",
                "use_shared_context": False,
            })

        assert r.status_code == 200
        # quiz_attempts row stores the same legacy-shape questions list.
        payload = captured["payload"]
        assert payload["user_id"] == "user_andres"
        assert payload["concept_node_id"] == "node1"
        assert payload["difficulty"] == "easy"
        assert isinstance(payload["questions_json"], list)
        assert payload["questions_json"][0]["id"] == 1


class TestQuizAgentFallback:
    """When the agent trips, the route runs the legacy generation pipeline."""

    def _legacy_response(self):
        # The legacy-shape question that the original quiz_generation prompt
        # produces: id, question, options[{label,text,correct}], etc.
        return {
            "questions": [
                {
                    "id": 1,
                    "question": "Legacy fallback question?",
                    "options": [
                        {"label": "A", "text": "wrong", "correct": False},
                        {"label": "B", "text": "right", "correct": True},
                    ],
                    "explanation": "Because.",
                    "concept_tested": "Loops",
                    "difficulty": "easy",
                },
            ]
        }

    def _patch_legacy_dependencies(self):
        """Patch every dep _legacy_generate_quiz reaches for besides table()."""
        return (
            patch(
                "routes.quiz.get_graph",
                return_value={"nodes": [], "edges": []},
            ),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch(
                "routes.quiz.call_gemini_json",
                return_value=self._legacy_response(),
            ),
        )

    def test_falls_back_to_legacy_on_usage_limit_exceeded(self):
        from pydantic_ai.exceptions import UsageLimitExceeded

        get_graph_p, get_ctx_p, gemini_p = self._patch_legacy_dependencies()
        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch(
                "routes.quiz.quiz_agent.run",
                new=AsyncMock(
                    side_effect=UsageLimitExceeded("token cap"),
                ),
            ),
            get_graph_p as _get_graph,
            get_ctx_p as _get_ctx,
            gemini_p as gemini_mock,
        ):
            r = client.post("/api/quiz/generate", json={
                "user_id": "user_andres",
                "concept_node_id": "node1",
                "num_questions": 1,
                "difficulty": "easy",
                "use_shared_context": False,
            })

        assert r.status_code == 200
        gemini_mock.assert_called_once()  # legacy path actually ran
        q = r.json()["questions"][0]
        assert q["question"] == "Legacy fallback question?"
        # Wire format from legacy is preserved verbatim (it already matches).
        assert q["options"][1]["correct"] is True

    def test_falls_back_to_legacy_on_unexpected_exception(self):
        get_graph_p, get_ctx_p, gemini_p = self._patch_legacy_dependencies()
        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch(
                "routes.quiz.quiz_agent.run",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            get_graph_p,
            get_ctx_p,
            gemini_p as gemini_mock,
        ):
            r = client.post("/api/quiz/generate", json={
                "user_id": "user_andres",
                "concept_node_id": "node1",
                "num_questions": 1,
                "difficulty": "easy",
                "use_shared_context": False,
            })

        assert r.status_code == 200
        gemini_mock.assert_called_once()
        assert r.json()["questions"][0]["question"] == "Legacy fallback question?"
