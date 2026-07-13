"""
Unit tests for routes/quiz.py

Covers:
- Mastery score update formula (scoring math)
- POST /api/quiz/submit — answer grading and result shape
- POST /api/quiz/submit — 404 when quiz not found
- POST /api/quiz/generate — agent success path (quiz_agent.run mocked)
- POST /api/quiz/generate — agent failure degrades to 502
"""
import pytest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from main import app
from agents.quiz import Quiz, QuizQuestion

client = TestClient(app)


def _noop_ctx_agent():
    """AsyncMock for quiz_context_agent.run to neutralize the post-submit
    background context update in tests. The real run_agent_sync drives it; the
    fake output.model_dump() yields an empty context."""
    return AsyncMock(
        return_value=SimpleNamespace(output=SimpleNamespace(model_dump=lambda: {}))
    )


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
        # Mastery writes now route through apply_graph_update (the sanctioned
        # graph path) instead of a direct graph_nodes.update.
        patch("routes.quiz.apply_graph_update"),
        patch("routes.quiz.get_quiz_context", return_value={}),
        patch("routes.quiz.quiz_context_agent.run", new=_noop_ctx_agent()),
        # Also neutralize the persistence side of the background update so these
        # submit tests don't do a hidden (mocked-table) write or swallow errors.
        patch("routes.quiz.save_quiz_context"),
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
            with patch("routes.quiz.apply_graph_update"):
                with patch("routes.quiz.get_quiz_context", return_value={}):
                    with patch("routes.quiz.quiz_context_agent.run", new=_noop_ctx_agent()):
                        r = client.post("/api/quiz/submit", json={
                            "quiz_id": "quiz1",
                            "answers": [
                                {"question_id": 1, "selected_label": "A"},
                                {"question_id": 2, "selected_label": "D"},
                            ],
                        })

        assert r.status_code == 200
        assert r.json()["score"] == 2


# ── Cross-user node ownership (IDOR regression, issue #157) ─────────────────


class TestQuizNodeOwnership:
    """User A must not be able to generate or submit a quiz against a
    concept node owned by user B. Both paths must 404 (not 200) so an
    attacker can't read a victim's concept content nor corrupt the
    victim's mastery fields.

    The graph_nodes table is owner-scoped: a SELECT scoped to a user_id
    that doesn't own the node returns no rows. The factory below models
    real DB behaviour — an *unscoped* read (the bug) still leaks B's node,
    so these tests fail on unscoped code and pass only once the route
    filters every node read by the caller's user_id.
    """

    NODE_OWNER = "user_beatriz"   # victim B owns the node
    ATTACKER = "user_andres"      # attacker A

    def _node_row(self) -> dict:
        return {
            "id": "node_b",
            "user_id": self.NODE_OWNER,
            "course_id": "course1",
            "concept_name": "Beatriz Secret Concept",
            "mastery_score": 0.5,
            "times_studied": 3,
            "mastery_events": [],
        }

    def _ownership_aware_graph_select(self, columns="*", filters=None, **_):
        """Faithfully model DB row-filtering for the victim's node.

        The row comes back when the query matches by id and EITHER no
        user_id scope is applied (the *buggy* unscoped read, which leaks
        B's node to anyone) OR the scope names the owner. A scope naming
        a non-owner (the attacker) returns nothing — so unscoped code
        leaks/writes (test fails) and only owner-scoped reads 404 for A.
        """
        filters = filters or {}
        if filters.get("id") != "eq.node_b":
            return []
        user_filter = filters.get("user_id")
        if user_filter is None or user_filter == f"eq.{self.NODE_OWNER}":
            return [self._node_row()]
        return []

    def test_generate_against_foreign_node_returns_404(self):
        """A POSTs /generate with B's concept_node_id but A's user_id.
        The owner-scoped node read misses → 404, before any quiz_attempts
        row is created and before the agent ever runs."""
        def factory(name):
            mock = MagicMock()
            if name == "graph_nodes":
                mock.select.side_effect = self._ownership_aware_graph_select
            else:
                mock.select.return_value = []
                mock.insert.return_value = []
            return mock

        agent_run = AsyncMock()
        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.quiz_agent.run", new=agent_run),
        ):
            r = client.post("/api/quiz/generate", json={
                "user_id": self.ATTACKER,
                "concept_node_id": "node_b",
                "num_questions": 1,
                "difficulty": "easy",
                "use_shared_context": False,
            })

        assert r.status_code == 404
        # The agent must never run for a foreign node — no content leak.
        agent_run.assert_not_called()

    def test_submit_against_foreign_node_returns_404_and_writes_nothing(self):
        """A owns the quiz_attempts row (so require_self passes), but the
        attempt's concept_node_id points at B's node. The owner-scoped
        node read (using the attempt's user_id == A) misses → 404, and no
        graph_nodes.update fires, so B's mastery stays intact."""
        update_calls: list = []

        def factory(name):
            mock = MagicMock()
            if name == "quiz_attempts":
                mock.select.return_value = [{
                    "id": "quiz_a",
                    "user_id": self.ATTACKER,        # attempt belongs to A
                    "concept_node_id": "node_b",     # but targets B's node
                    "difficulty": "medium",
                    "questions_json": SAMPLE_QUESTIONS,
                }]
                mock.update.return_value = []
            elif name == "graph_nodes":
                mock.select.side_effect = self._ownership_aware_graph_select
                mock.update.side_effect = lambda *a, **k: update_calls.append((a, k)) or []
            else:
                mock.select.return_value = []
                mock.update.return_value = []
            return mock

        apply_mock = MagicMock()
        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.apply_graph_update", new=apply_mock),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.quiz_context_agent.run", new=_noop_ctx_agent()),
        ):
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz_a",
                "answers": [
                    {"question_id": 1, "selected_label": "A"},
                    {"question_id": 2, "selected_label": "D"},
                ],
            })

        assert r.status_code == 404
        # No mastery write to the victim's node (or any node) occurred — neither
        # a direct graph_nodes.update nor the sanctioned apply_graph_update path.
        assert update_calls == [], (
            "submit_quiz wrote to graph_nodes for a foreign concept node — "
            "IDOR regression (issue #157)."
        )
        apply_mock.assert_not_called()


# ── POST /api/quiz/generate — difficulty enum (0025 CHECK) ──────────────────


class TestGenerateQuizDifficultyEnum:
    """quiz_attempts.difficulty is CHECK-constrained to easy|medium|hard
    (0025). The route rejects drift with a 400 before running the agent or
    writing an attempt row."""

    def test_invalid_difficulty_returns_400(self):
        agent_run = AsyncMock()
        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch("routes.quiz.quiz_agent.run", new=agent_run),
        ):
            r = client.post("/api/quiz/generate", json={
                "user_id": "user_andres",
                "concept_node_id": "node1",
                "num_questions": 1,
                "difficulty": "impossible",  # not in the CHECK set
                "use_shared_context": False,
            })
        assert r.status_code == 400
        # The agent must not run for an invalid difficulty.
        agent_run.assert_not_called()

    def test_valid_difficulty_passes_validation(self):
        from types import SimpleNamespace
        fake_quiz = Quiz(questions=[
            QuizQuestion(
                question="Q?", type="multiple_choice", difficulty="hard",
                options=["a", "b", "c", "d"], correct_answer="a",
                explanation="x", concept="X",
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
                "difficulty": "hard",
                "use_shared_context": False,
            })
        assert r.status_code == 200


# ── POST /api/quiz/submit — mastery routes through apply_graph_update ────────


class TestSubmitQuizMasteryWrite:
    """0023 dropped graph_nodes.mastery_events; submit_quiz must NOT touch
    that column. Mastery writes route through apply_graph_update (the
    sanctioned graph path), keyed by concept_name + the abstract course id."""

    def test_mastery_write_routes_through_apply_graph_update(self):
        apply_mock = MagicMock()

        def factory(name):
            mock = MagicMock()
            if name == "quiz_attempts":
                mock.select.return_value = [{
                    "id": "quiz1",
                    "user_id": "user_andres",
                    "concept_node_id": "node1",
                    "difficulty": "medium",
                    "questions_json": SAMPLE_QUESTIONS,
                }]
            elif name == "graph_nodes":
                mock.select.return_value = [{
                    "mastery_score": 0.5,
                    "concept_name": "Loops",
                    "course_id": "course1",
                }]
            elif name == "users":
                mock.select.return_value = [{"name": "Andres"}]
            else:
                mock.select.return_value = []
            mock.update.return_value = []
            return mock

        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.apply_graph_update", new=apply_mock),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.quiz_context_agent.run", new=_noop_ctx_agent()),
        ):
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [
                    {"question_id": 1, "selected_label": "A"},
                    {"question_id": 2, "selected_label": "D"},
                ],
            })

        assert r.status_code == 200
        apply_mock.assert_called_once()
        args, kwargs = apply_mock.call_args
        # user_id first, abstract course id passed (graph keys on abstract).
        assert args[0] == "user_andres"
        assert kwargs["course_id"] == "course1"
        updated = args[1]["updated_nodes"]
        assert len(updated) == 1
        assert updated[0]["concept_name"] == "Loops"
        # Perfect score → positive mastery delta.
        assert updated[0]["mastery_delta"] > 0
        # The response still reports before/after.
        data = r.json()
        assert data["mastery_after"] > data["mastery_before"]


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

    def test_short_answer_type_is_rejected_at_schema_layer(self):
        """short_answer was dropped from QuizQuestionType in refactor #2
        because the frontend has no UI for free-text answers and
        submit_quiz grades by option-label lookup. Constructing a
        QuizQuestion with type='short_answer' must raise a Pydantic
        validation error — not silently produce an ungradable item.
        """
        from pydantic import ValidationError
        try:
            QuizQuestion(
                question="Define a closure.",
                type="short_answer",  # type: ignore[arg-type]
                difficulty="medium",
                options=["a", "b", "c", "d"],
                correct_answer="a",
                explanation="x",
                concept="Closures",
            )
        except ValidationError:
            pass
        else:
            raise AssertionError(
                "Short-answer regression: QuizQuestion accepted "
                "type='short_answer'. The Literal must stay MCQ-only "
                "until real short-answer grading exists."
            )

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


class TestQuizContextUpdate:
    """#145: the post-submit background task runs quiz_context_agent and persists
    its model_dump() dict via save_quiz_context — no raw Gemini call."""

    def test_saves_agent_model_dump(self):
        from agents.quiz_context import QuizContext

        ctx = QuizContext(
            weak_areas=["recursion base case"],
            common_mistakes=["off-by-one"],
            questions_seen_summary="loops and recursion",
            recommended_difficulty="hard",
            notes="solid on iteration",
        )
        run = AsyncMock(return_value=SimpleNamespace(output=ctx))
        saved = {}

        def _save(uid, node_id, context):
            saved["ctx"] = context

        with (
            patch("routes.quiz.table", side_effect=_make_table(None)),
            patch("routes.quiz.apply_graph_update"),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.quiz_context_agent.run", new=run),
            patch("routes.quiz.save_quiz_context", side_effect=_save),
        ):
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "A"}],
            })

        assert r.status_code == 200
        run.assert_called_once()
        # The background task saved exactly the agent output's model_dump().
        assert saved["ctx"] == ctx.model_dump()
        assert saved["ctx"]["recommended_difficulty"] == "hard"


class TestQuizAgentDegrade:
    """When the agent trips, the route degrades to HTTP 502 (the raw-Gemini
    legacy fallback was retired in #145 — no second LLM path)."""

    def test_degrades_on_usage_limit_exceeded(self):
        from pydantic_ai.exceptions import UsageLimitExceeded

        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch(
                "routes.quiz.quiz_agent.run",
                new=AsyncMock(side_effect=UsageLimitExceeded("token cap")),
            ),
        ):
            r = client.post("/api/quiz/generate", json={
                "user_id": "user_andres",
                "concept_node_id": "node1",
                "num_questions": 1,
                "difficulty": "easy",
                "use_shared_context": False,
            })
        assert r.status_code == 502

    def test_degrades_on_unexpected_exception(self):
        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch(
                "routes.quiz.quiz_agent.run",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            r = client.post("/api/quiz/generate", json={
                "user_id": "user_andres",
                "concept_node_id": "node1",
                "num_questions": 1,
                "difficulty": "easy",
                "use_shared_context": False,
            })
        assert r.status_code == 502

    def test_degrades_when_all_questions_drift(self):
        """Agent succeeds but every question fails wire-format validation ->
        _quiz_via_agent raises RuntimeError -> bare-Exception catch -> 502."""
        drift_quiz = Quiz(questions=[
            QuizQuestion(
                question=f"Q{i}?",
                type="multiple_choice",
                difficulty="easy",
                options=["a", "b", "c", "d"],
                correct_answer="MISMATCH",  # not in options
                explanation="x",
                concept="X",
            )
            for i in range(3)
        ])
        agent_run_mock = AsyncMock(return_value=SimpleNamespace(output=drift_quiz))
        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch("routes.quiz.quiz_agent.run", new=agent_run_mock),
        ):
            r = client.post("/api/quiz/generate", json={
                "user_id": "user_andres",
                "concept_node_id": "node1",
                "num_questions": 3,
                "difficulty": "easy",
                "use_shared_context": False,
            })
        assert r.status_code == 502
        agent_run_mock.assert_called_once()  # the agent path was actually tried


# ── Wire-format contract: pinned by tests so silent drift can't recur ───────

class TestQuizWireFormatContract:
    """Pin the invariant `_agent_question_to_wire` enforces: every emitted
    question has exactly one correct option, and the correct option's text
    matches the agent's `correct_answer`. Drift cases (LLM emits a
    correct_answer not in options) drop the question rather than silently
    mis-marking it.
    """

    def test_well_formed_question_passes_through(self):
        from agents.quiz import QuizQuestion
        from routes.quiz import _agent_question_to_wire

        q = QuizQuestion(
            question="What is 2 + 2?",
            type="multiple_choice",
            difficulty="easy",
            options=["3", "4", "5", "6"],
            correct_answer="4",
            explanation="Basic arithmetic.",
            concept="Arithmetic",
        )
        wire = _agent_question_to_wire(q, qid=1)
        assert wire is not None
        # Exactly one option flagged correct.
        correct = [o for o in wire["options"] if o["correct"]]
        assert len(correct) == 1, f"expected 1 correct, got {len(correct)}"
        # The correct option's text matches the canonical answer verbatim.
        assert correct[0]["text"] == q.correct_answer
        # Labels are A, B, C, D in order.
        assert [o["label"] for o in wire["options"]] == ["A", "B", "C", "D"]

    def test_correct_answer_not_in_options_drops_question(self):
        """Generation drift: the agent's `correct_answer` doesn't appear
        in `options`. The wrapper returns None; the caller filters it out.
        Silent first-option-correct fallback must NOT happen.
        """
        from agents.quiz import QuizQuestion
        from routes.quiz import _agent_question_to_wire

        q = QuizQuestion(
            question="What is 2 + 2?",
            type="multiple_choice",
            difficulty="easy",
            options=["3", "5", "6", "7"],   # 4 is missing
            correct_answer="4",
            explanation="Basic arithmetic.",
            concept="Arithmetic",
        )
        wire = _agent_question_to_wire(q, qid=1)
        assert wire is None, (
            "Silent fallback regression: the wrapper must not mark an "
            "arbitrary option correct when the agent's correct_answer "
            "isn't present verbatim — drop the question instead."
        )

    def test_whitespace_only_difference_still_matches(self):
        """The wrapper trims whitespace before comparing — minor LLM
        whitespace drift shouldn't drop the question."""
        from agents.quiz import QuizQuestion
        from routes.quiz import _agent_question_to_wire

        q = QuizQuestion(
            question="What is 2 + 2?",
            type="multiple_choice",
            difficulty="easy",
            options=["3", "  4  ", "5", "6"],
            correct_answer="4",
            explanation="Basic arithmetic.",
            concept="Arithmetic",
        )
        wire = _agent_question_to_wire(q, qid=1)
        assert wire is not None
        correct = [o for o in wire["options"] if o["correct"]]
        assert len(correct) == 1
        # The matched option preserves its original (whitespace-padded)
        # text — the trim is only used for comparison.
        assert correct[0]["text"].strip() == "4"


# ── Per-request model_pref (Fast/Smart toggle, mirrors chat tutor) ──────────

class TestQuizModelPref:
    """Pin the per-request fast/smart toggle introduced after PR #73's
    chat-tutor model toggle landed on main. Both routes now expose the
    same body field; this class locks the dispatch contract end-to-end.
    """

    def _fake_quiz(self):
        return Quiz(questions=[
            QuizQuestion(
                question="What is 2 + 2?",
                type="multiple_choice",
                difficulty="easy",
                options=["3", "4", "5", "6"],
                correct_answer="4",
                explanation="Basic arithmetic.",
                concept="Arithmetic",
            ),
        ])

    def _post(self, body_extra: dict):
        return client.post("/api/quiz/generate", json={
            "user_id": "user_andres",
            "concept_node_id": "node1",
            "num_questions": 1,
            "difficulty": "easy",
            "use_shared_context": False,
            **body_extra,
        })

    def test_smart_pref_overrides_agent_model(self):
        """model_pref='smart' → agent.run is called with model=GoogleModel('gemini-2.5-pro')."""
        run_mock = AsyncMock(return_value=SimpleNamespace(output=self._fake_quiz()))
        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch("routes.quiz.quiz_agent.run", new=run_mock),
        ):
            r = self._post({"model_pref": "smart"})
        assert r.status_code == 200
        assert run_mock.call_count == 1
        kwargs = run_mock.call_args.kwargs
        assert "model" in kwargs, "smart pref must pass an explicit model override"
        assert kwargs["model"].model_name == "gemini-2.5-pro"

    def test_fast_pref_overrides_agent_model(self):
        """model_pref='fast' → agent.run is called with model=GoogleModel('gemini-2.5-flash-lite')."""
        run_mock = AsyncMock(return_value=SimpleNamespace(output=self._fake_quiz()))
        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch("routes.quiz.quiz_agent.run", new=run_mock),
        ):
            r = self._post({"model_pref": "fast"})
        assert r.status_code == 200
        kwargs = run_mock.call_args.kwargs
        assert "model" in kwargs
        assert kwargs["model"].model_name == "gemini-2.5-flash-lite"

    def test_no_pref_falls_through_to_agent_default(self):
        """No model_pref → agent.run gets NO model kwarg, falls back to model_for('quiz')."""
        run_mock = AsyncMock(return_value=SimpleNamespace(output=self._fake_quiz()))
        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch("routes.quiz.quiz_agent.run", new=run_mock),
        ):
            r = self._post({})  # no model_pref
        assert r.status_code == 200
        kwargs = run_mock.call_args.kwargs
        assert "model" not in kwargs, (
            "Without model_pref, the route must NOT inject a model override — "
            "the agent's task-default (model_for('quiz')) should win."
        )

    def test_unknown_pref_falls_through_to_agent_default(self):
        """An unrecognized preference (e.g. legacy clients sending 'auto')
        falls through to the agent default rather than raising. Pydantic
        validation already restricts the body type to fast|smart|None,
        but we double-belt at the resolver layer."""
        from routes.quiz import _resolve_model_pref
        assert _resolve_model_pref(None) is None
        assert _resolve_model_pref("") is None
        assert _resolve_model_pref("auto") is None  # not in the map
