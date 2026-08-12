"""
Workstream A of the pre-revamp quiz repair batch (#540, epic #537).

Covers:
- GET /api/quiz/config — single source of truth for selector options
- POST /api/quiz/generate accepts difficulty='adaptive' (A1)
- resolved_difficulty / requested_difficulty echo what generation chose
- Stable error envelope { error: { code, message, detail?, request_id } }
  on every quiz-route 4xx/5xx, with the legacy `detail` key kept so the
  current QuizPanel client keeps working (A3)
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from main import app
from agents.quiz import Quiz, QuizQuestion

client = TestClient(app)


def _question(difficulty: str, n: int = 1) -> QuizQuestion:
    return QuizQuestion(
        question=f"Q{n}?",
        type="multiple_choice",
        difficulty=difficulty,
        options=[f"a{n}", f"b{n}", f"c{n}", f"d{n}"],
        correct_answer=f"a{n}",
        explanation="x",
        concept="X",
    )


def _quiz(*difficulties: str) -> Quiz:
    return Quiz(questions=[_question(d, i + 1) for i, d in enumerate(difficulties)])


def _generate_table_factory():
    def factory(name):
        mock = MagicMock()
        if name == "graph_nodes":
            mock.select.return_value = [{
                "id": "node1",
                "course_id": "course1",
                "concept_name": "Loops",
                "mastery_score": 0.5,
            }]
        elif name == "quiz_attempts":
            mock.insert.return_value = [{"id": "quiz-generated"}]
        else:
            mock.select.return_value = []
            mock.insert.return_value = []
        return mock

    return factory


def _generate(body_extra: dict) -> object:
    return client.post("/api/quiz/generate", json={
        "user_id": "user_andres",
        "concept_node_id": "node1",
        "num_questions": 3,
        "use_shared_context": False,
        **body_extra,
    })


# ── GET /api/quiz/config (A2) ────────────────────────────────────────────────


class TestQuizConfigEndpoint:
    """One source of truth: the client builds its selectors from this payload
    and can never again offer a value the route rejects."""

    def test_config_returns_selector_options(self):
        r = client.get("/api/quiz/config")
        assert r.status_code == 200
        data = r.json()
        nq = data["num_questions"]
        assert isinstance(nq["min"], int)
        assert isinstance(nq["max"], int)
        assert isinstance(nq["options"], list) and nq["options"]
        assert all(nq["min"] <= v <= nq["max"] for v in nq["options"])
        assert data["difficulties"] == ["easy", "medium", "hard", "adaptive"]
        assert data["question_types"] == ["mcq"]

    def test_config_matches_pydantic_model_bounds(self):
        """The Pydantic cap and the config endpoint must read the same named
        constant — if they drift this fails."""
        from models import GenerateQuizBody

        field = GenerateQuizBody.model_fields["num_questions"]
        ge = next(m.ge for m in field.metadata if hasattr(m, "ge"))
        le = next(m.le for m in field.metadata if hasattr(m, "le"))
        data = client.get("/api/quiz/config").json()
        assert data["num_questions"]["min"] == ge
        assert data["num_questions"]["max"] == le

    def test_config_matches_named_constants(self):
        from services.quiz_config import (
            QUIZ_MIN_QUESTIONS,
            QUIZ_MAX_QUESTIONS,
            QUIZ_NUM_QUESTION_OPTIONS,
        )

        data = client.get("/api/quiz/config").json()
        assert data["num_questions"]["min"] == QUIZ_MIN_QUESTIONS
        assert data["num_questions"]["max"] == QUIZ_MAX_QUESTIONS
        assert data["num_questions"]["options"] == list(QUIZ_NUM_QUESTION_OPTIONS)


# ── difficulty='adaptive' (A1) ───────────────────────────────────────────────


class TestGenerateAdaptiveDifficulty:
    def test_adaptive_generates_and_echoes_resolved_difficulty(self):
        run_mock = AsyncMock(
            return_value=SimpleNamespace(output=_quiz("medium", "hard", "hard"))
        )
        captured = {}

        def factory(name):
            mock = MagicMock()
            if name == "graph_nodes":
                mock.select.return_value = [{
                    "id": "node1",
                    "course_id": "course1",
                    "concept_name": "Loops",
                    "mastery_score": 0.5,
                }]
            elif name == "quiz_attempts":
                def _capture(payload):
                    captured["payload"] = payload
                    return [{"id": payload["id"]}]
                mock.insert.side_effect = _capture
            else:
                mock.select.return_value = []
            return mock

        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.quiz_agent.run", new=run_mock),
        ):
            r = _generate({"difficulty": "adaptive"})

        assert r.status_code == 200
        data = r.json()
        assert data["requested_difficulty"] == "adaptive"
        # Mode of (medium, hard, hard) → hard.
        assert data["resolved_difficulty"] == "hard"
        # Per-question difficulty stays on each wire question.
        assert [q["difficulty"] for q in data["questions"]] == [
            "medium", "hard", "hard",
        ]
        # The attempt row records what the student asked for.
        assert captured["payload"]["difficulty"] == "adaptive"

    def test_adaptive_routing_message_instructs_agent(self):
        """The agent must be told to pick the mix itself — and that every
        emitted question still carries a concrete difficulty."""
        run_mock = AsyncMock(
            return_value=SimpleNamespace(output=_quiz("easy", "medium", "medium"))
        )
        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch("routes.quiz.quiz_agent.run", new=run_mock),
        ):
            r = _generate({"difficulty": "adaptive"})
        assert r.status_code == 200
        msg = run_mock.call_args[0][0]
        assert "adaptive" in msg.lower()
        # The literal string 'adaptive' must not be requested as a
        # per-question difficulty value (the output schema is concrete).
        assert "3 adaptive questions" not in msg

    def test_concrete_request_also_reports_resolved_difficulty(self):
        """Even a concrete request echoes what generation actually chose —
        the agent may legitimately shift the mix ±1 step."""
        run_mock = AsyncMock(
            return_value=SimpleNamespace(output=_quiz("easy", "easy", "medium"))
        )
        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch("routes.quiz.quiz_agent.run", new=run_mock),
        ):
            r = _generate({"difficulty": "medium"})
        assert r.status_code == 200
        data = r.json()
        assert data["requested_difficulty"] == "medium"
        assert data["resolved_difficulty"] == "easy"

    def test_resolved_difficulty_tie_breaks_harder(self):
        from routes.quiz import _resolved_difficulty

        assert _resolved_difficulty([{"difficulty": "easy"},
                                     {"difficulty": "hard"}]) == "hard"
        assert _resolved_difficulty([{"difficulty": "medium"}]) == "medium"
        assert _resolved_difficulty([{"difficulty": "easy"},
                                     {"difficulty": "easy"},
                                     {"difficulty": "medium"}]) == "easy"
        # Unknown/missing difficulty values are ignored, not fatal.
        assert _resolved_difficulty([{}]) == "medium"


# ── Stable error envelope (A3) ───────────────────────────────────────────────


def _assert_envelope(r, status: int, code: str):
    assert r.status_code == status
    body = r.json()
    err = body["error"]
    assert err["code"] == code
    assert isinstance(err["message"], str) and err["message"]
    # request_id rides in the payload for support, not inside message.
    assert "request_id" in err
    assert err["request_id"] not in err["message"]
    # Legacy key kept so the current client's `data?.detail` reads work.
    assert "detail" in body
    return body


class TestQuizErrorEnvelope:
    def test_invalid_difficulty_400(self):
        agent_run = AsyncMock()
        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch("routes.quiz.quiz_agent.run", new=agent_run),
        ):
            r = _generate({"difficulty": "impossible"})
        _assert_envelope(r, 400, "QUIZ_DIFFICULTY_INVALID")
        agent_run.assert_not_called()

    def test_concept_not_found_404(self):
        def factory(name):
            mock = MagicMock()
            mock.select.return_value = []
            return mock

        with patch("routes.quiz.table", side_effect=factory):
            r = _generate({"difficulty": "easy"})
        _assert_envelope(r, 404, "QUIZ_CONCEPT_NOT_FOUND")

    def test_attempt_not_found_404(self):
        with patch("routes.quiz.table") as t:
            t.return_value.select.return_value = []
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "missing", "answers": [],
            })
        _assert_envelope(r, 404, "QUIZ_ATTEMPT_NOT_FOUND")

    def test_already_completed_409(self):
        def factory(name):
            mock = MagicMock()
            if name == "quiz_attempts":
                mock.select.return_value = [{
                    "id": "quiz1",
                    "user_id": "user_andres",
                    "concept_node_id": "node1",
                    "difficulty": "medium",
                    "questions_json": [],
                    "completed_at": "2026-08-01T12:00:00",
                }]
            else:
                mock.select.return_value = []
            return mock

        with patch("routes.quiz.table", side_effect=factory):
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1", "answers": [],
            })
        _assert_envelope(r, 409, "QUIZ_ATTEMPT_ALREADY_COMPLETED")

    def test_count_out_of_range_422(self):
        r = _generate({"difficulty": "medium", "num_questions": 15})
        body = _assert_envelope(r, 422, "QUIZ_COUNT_OUT_OF_RANGE")
        # Pydantic's machine-readable errors stay available under detail.
        assert isinstance(body["detail"], list)

    def test_generation_failure_502(self):
        with (
            patch("routes.quiz.table", side_effect=_generate_table_factory()),
            patch(
                "routes.quiz.quiz_agent.run",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            r = _generate({"difficulty": "easy"})
        _assert_envelope(r, 502, "QUIZ_GENERATION_FAILED")

    def test_non_quiz_routes_keep_legacy_shape(self):
        """The envelope is scoped to /api/quiz/*; everything else keeps the
        plain {detail, request_id} contract."""
        r = client.get("/api/does-not-exist")
        assert r.status_code == 404
        assert "error" not in r.json()

    def test_error_codes_are_a_single_enum(self):
        from services.quiz_errors import QuizErrorCode

        values = {c.value for c in QuizErrorCode}
        for expected in (
            "QUIZ_DIFFICULTY_INVALID",
            "QUIZ_COUNT_OUT_OF_RANGE",
            "QUIZ_GENERATION_FAILED",
            "QUIZ_ATTEMPT_ALREADY_COMPLETED",
            "QUIZ_ATTEMPT_NOT_FOUND",
            "QUIZ_CONCEPT_NOT_FOUND",
        ):
            assert expected in values
