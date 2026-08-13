"""
Workstream F of the pre-revamp quiz repair batch (#544, epic #537):
cost, abuse, observability.

- F1: per-user rate limit on generate + a daily LLM spend guard.
  Generation is an unbounded LLM call behind a button; nothing stopped a
  loop.
- F2: explicit timeout on the agent call, mapped to a 502 taxonomy
  rather than one generic code.
- F3: quiz.generation_failed events so backend failures reach admin
  analytics (quiz.context_write_failed landed with #529/B3).
- F4: ownership + active-semester scoping on ?concept= deep links.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from main import app
from agents.quiz import Quiz, QuizQuestion

client = TestClient(app)


def _quiz():
    return Quiz(questions=[
        QuizQuestion(
            question="Q?", type="multiple_choice", difficulty="easy",
            options=["a", "b", "c", "d"], correct_answer="a",
            explanation="x", concept="Loops",
        ),
    ])


def _factory(*, spend_rows=None):
    def factory(name):
        mock = MagicMock()
        if name == "graph_nodes":
            mock.select.return_value = [{
                "id": "node1", "course_id": "course1",
                "concept_name": "Loops", "mastery_score": 0.5,
            }]
        elif name == "quiz_attempts":
            mock.insert.return_value = [{"id": "quiz-generated"}]
        elif name == "llm_usage":
            mock.select.return_value = spend_rows if spend_rows is not None else []
        else:
            mock.select.return_value = []
            mock.insert.return_value = []
        return mock

    return factory


def _generate(user_id="user_andres"):
    return client.post("/api/quiz/generate", json={
        "user_id": user_id,
        "concept_node_id": "node1",
        "num_questions": 1,
        "difficulty": "easy",
        "use_shared_context": False,
    })


# ── F1: rate limit + spend guard ────────────────────────────────────────────


class TestGenerateRateLimit:
    def test_burst_past_the_limit_is_rejected(self):
        from services.quiz_config import (
            QUIZ_GENERATE_RATE_LIMIT,
            QUIZ_GENERATE_RATE_WINDOW_SEC,
        )

        assert QUIZ_GENERATE_RATE_WINDOW_SEC > 0
        run = AsyncMock(return_value=SimpleNamespace(output=_quiz()))
        with (
            patch("routes.quiz.table", side_effect=_factory()),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            allowed = [_generate() for _ in range(QUIZ_GENERATE_RATE_LIMIT)]
            blocked = _generate()

        assert all(r.status_code == 200 for r in allowed)
        assert blocked.status_code == 429
        body = blocked.json()
        assert body["error"]["code"] == "QUIZ_RATE_LIMITED"
        assert "Retry-After" in blocked.headers
        # The blocked request must not have reached the model.
        assert run.call_count == QUIZ_GENERATE_RATE_LIMIT

    def test_limit_is_per_user(self):
        run = AsyncMock(return_value=SimpleNamespace(output=_quiz()))
        from services.quiz_config import QUIZ_GENERATE_RATE_LIMIT

        with (
            patch("routes.quiz.table", side_effect=_factory()),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            for _ in range(QUIZ_GENERATE_RATE_LIMIT):
                _generate("user_andres")
            # A different user starts with a fresh window. require_self is
            # stubbed per-request from the body's user_id in conftest.
            other = _generate("user_beatriz")
        assert other.status_code == 200


class TestDailySpendGuard:
    def test_over_budget_user_is_refused_before_the_model_runs(self):
        from services.quiz_config import QUIZ_DAILY_SPEND_CAP_USD

        spent = [{"cost_usd": QUIZ_DAILY_SPEND_CAP_USD + 1.0}]
        run = AsyncMock(return_value=SimpleNamespace(output=_quiz()))
        with (
            patch("routes.quiz.table", side_effect=_factory(spend_rows=spent)),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            r = _generate()
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "QUIZ_DAILY_LIMIT_REACHED"
        run.assert_not_called()

    def test_under_budget_passes(self):
        from services.quiz_config import QUIZ_DAILY_SPEND_CAP_USD

        spent = [{"cost_usd": QUIZ_DAILY_SPEND_CAP_USD / 2}]
        run = AsyncMock(return_value=SimpleNamespace(output=_quiz()))
        with (
            patch("routes.quiz.table", side_effect=_factory(spend_rows=spent)),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            r = _generate()
        assert r.status_code == 200

    def test_spend_lookup_failure_never_blocks_a_quiz(self):
        """The guard is a cost control, not a correctness gate — if the
        usage table is unreachable we let the quiz through rather than
        failing closed on every student."""
        def factory(name):
            mock = MagicMock()
            if name == "graph_nodes":
                mock.select.return_value = [{
                    "id": "node1", "course_id": "course1",
                    "concept_name": "Loops", "mastery_score": 0.5,
                }]
            elif name == "llm_usage":
                mock.select.side_effect = RuntimeError("db down")
            else:
                mock.select.return_value = []
                mock.insert.return_value = [{"id": "q"}]
            return mock

        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.quiz_agent.run",
                  new=AsyncMock(return_value=SimpleNamespace(output=_quiz()))),
        ):
            r = _generate()
        assert r.status_code == 200


# ── F2: timeout → its own 502 code ──────────────────────────────────────────


class TestGenerationTimeout:
    def test_agent_timeout_maps_to_its_own_code(self):
        from services.quiz_config import QUIZ_GENERATION_TIMEOUT_SEC

        assert QUIZ_GENERATION_TIMEOUT_SEC > 0

        async def _never(*a, **k):
            await asyncio.sleep(3600)

        with (
            patch("routes.quiz.table", side_effect=_factory()),
            patch("routes.quiz.quiz_agent.run", new=_never),
            patch("routes.quiz.QUIZ_GENERATION_TIMEOUT_SEC", 0.05),
        ):
            r = _generate()
        assert r.status_code == 502
        assert r.json()["error"]["code"] == "QUIZ_GENERATION_TIMEOUT"

    def test_ordinary_failure_keeps_the_generic_code(self):
        with (
            patch("routes.quiz.table", side_effect=_factory()),
            patch("routes.quiz.quiz_agent.run",
                  new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            r = _generate()
        assert r.status_code == 502
        assert r.json()["error"]["code"] == "QUIZ_GENERATION_FAILED"


# ── F3: failure events reach admin analytics ────────────────────────────────


class TestGenerationFailureEvent:
    def test_generation_failure_emits_an_event(self):
        events = []
        with (
            patch("routes.quiz.table", side_effect=_factory()),
            patch("routes.quiz.quiz_agent.run",
                  new=AsyncMock(side_effect=RuntimeError("boom"))),
            patch("routes.quiz.events_service.log_event",
                  side_effect=lambda *a, **k: events.append((a, k))),
        ):
            r = _generate()
        assert r.status_code == 502
        failed = [(a, k) for a, k in events if a and a[0] == "quiz.generation_failed"]
        assert len(failed) == 1, (
            "a generation failure must be visible in admin analytics, not just logs"
        )
        _, kwargs = failed[0]
        assert kwargs["category"] == "error"
        assert kwargs["user_id"] == "user_andres"
        payload = kwargs["payload"]
        assert payload["concept_node_id"] == "node1"
        assert payload["reason"] == "agent_error"

    def test_event_is_in_the_pinned_taxonomy(self):
        from services import events_service

        assert "quiz.generation_failed" in events_service.EVENT_TAXONOMY

    def test_rate_limit_rejection_is_not_an_error_event(self):
        """A throttled student isn't a backend failure — it must not
        pollute the error feed."""
        from services.quiz_config import QUIZ_GENERATE_RATE_LIMIT

        events = []
        with (
            patch("routes.quiz.table", side_effect=_factory()),
            patch("routes.quiz.quiz_agent.run",
                  new=AsyncMock(return_value=SimpleNamespace(output=_quiz()))),
            patch("routes.quiz.events_service.log_event",
                  side_effect=lambda *a, **k: events.append((a, k))),
        ):
            for _ in range(QUIZ_GENERATE_RATE_LIMIT + 1):
                _generate()
        assert not [a for a, _ in events if a and a[0] == "quiz.generation_failed"]


# ── F4: ownership + semester scoping on deep links ──────────────────────────


class TestConceptScoping:
    """`?concept=` deep links hand the route an arbitrary node id. The
    owner-scoped read is the gate: a node belonging to someone else, or to
    a course the student isn't enrolled in, must 404 before the agent runs
    — no content leak, no mastery write."""

    def _scoped_select(self, *, owned_by="user_andres", course_id="course1"):
        def _select(columns="*", filters=None, **_):
            filters = filters or {}
            if filters.get("id") != "eq.node_x":
                return []
            if filters.get("user_id") not in (None, f"eq.{owned_by}"):
                return []
            return [{
                "id": "node_x", "user_id": owned_by, "course_id": course_id,
                "concept_name": "Someone Else's Concept", "mastery_score": 0.4,
            }]

        return _select

    def _post(self, user_id):
        return client.post("/api/quiz/generate", json={
            "user_id": user_id, "concept_node_id": "node_x",
            "num_questions": 1, "difficulty": "easy",
            "use_shared_context": False,
        })

    def test_foreign_concept_404s_before_the_agent_runs(self):
        run = AsyncMock()

        def factory(name):
            mock = MagicMock()
            if name == "graph_nodes":
                mock.select.side_effect = self._scoped_select(owned_by="user_beatriz")
            else:
                mock.select.return_value = []
            return mock

        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            r = self._post("user_andres")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "QUIZ_CONCEPT_NOT_FOUND"
        run.assert_not_called()

    def test_own_concept_from_a_past_semester_still_generates(self):
        """Scoping is by OWNERSHIP, not by active semester: a student
        revising last term's concept is legitimate. Pinning this stops a
        future 'scope to active semester' change from silently breaking
        revision — if that becomes desired it needs its own decision."""
        run = AsyncMock(return_value=SimpleNamespace(output=_quiz()))

        def factory(name):
            mock = MagicMock()
            if name == "graph_nodes":
                mock.select.side_effect = self._scoped_select(course_id="old-course")
            elif name == "quiz_attempts":
                mock.insert.return_value = [{"id": "q"}]
            else:
                mock.select.return_value = []
            return mock

        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            r = self._post("user_andres")
        assert r.status_code == 200
        run.assert_called_once()
