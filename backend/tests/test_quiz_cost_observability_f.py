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

    def test_a_failed_generation_does_not_burn_the_budget(self):
        """The slot is claimed before the model runs, so a backend failure
        would otherwise spend the student's quota — eight 502s in two
        minutes locking them out for five, with a message telling them
        they generated too many quizzes. They received none."""
        from services.quiz_config import QUIZ_GENERATE_RATE_LIMIT

        failing = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch("routes.quiz.table", side_effect=_factory()),
            patch("routes.quiz.quiz_agent.run", new=failing),
        ):
            for _ in range(QUIZ_GENERATE_RATE_LIMIT + 2):
                r = _generate()
                assert r.status_code == 502, (
                    "a failed generation must not consume the rate-limit slot"
                )

        # …and the budget is still intact for a request that can succeed.
        with (
            patch("routes.quiz.table", side_effect=_factory()),
            patch("routes.quiz.quiz_agent.run",
                  new=AsyncMock(return_value=SimpleNamespace(output=_quiz()))),
        ):
            assert _generate().status_code == 200

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


class TestGenerateRateLimitIsEnvOverridable:
    """#537: the two guard constants read the environment; defaults intact.

    `request_limits._rate_state` is module-level, so a whole Playwright run
    shares ONE window that only a backend restart clears — and the redesigned
    quiz lane needs more generations than any human would. The E2E stacks
    raise the limit through the environment; production sets nothing and must
    keep the shipped defaults.
    """

    @staticmethod
    def _reloaded():
        """Re-import services.quiz_config against the current environment.

        `importlib.reload` mutates the module in place, so every caller must
        restore it (see `_restore`) or later tests inherit the override.
        """
        import importlib

        from services import quiz_config

        return importlib.reload(quiz_config)

    @classmethod
    def _restore(cls):
        cls._reloaded()

    def test_defaults_hold_when_unset(self, monkeypatch):
        monkeypatch.delenv("QUIZ_GENERATE_RATE_LIMIT", raising=False)
        monkeypatch.delenv("QUIZ_GENERATE_RATE_WINDOW_SEC", raising=False)
        try:
            cfg = self._reloaded()
            assert cfg.QUIZ_GENERATE_RATE_LIMIT == 8
            assert cfg.QUIZ_GENERATE_RATE_WINDOW_SEC == 300
        finally:
            monkeypatch.undo()
            self._restore()

    def test_an_override_is_honoured(self, monkeypatch):
        monkeypatch.setenv("QUIZ_GENERATE_RATE_LIMIT", "1000")
        monkeypatch.setenv("QUIZ_GENERATE_RATE_WINDOW_SEC", "60")
        try:
            cfg = self._reloaded()
            assert cfg.QUIZ_GENERATE_RATE_LIMIT == 1000
            assert cfg.QUIZ_GENERATE_RATE_WINDOW_SEC == 60
        finally:
            monkeypatch.undo()
            self._restore()

    def test_a_junk_override_falls_back_to_the_default(self, monkeypatch):
        """Fail-safe, not fail-fast: a stray value must neither disable the
        guard (limit=0 would 429 everyone, a negative window never expires)
        nor stop the app from booting."""
        for bad in ("", "   ", "eight", "0", "-5", "3.5"):
            monkeypatch.setenv("QUIZ_GENERATE_RATE_LIMIT", bad)
            monkeypatch.setenv("QUIZ_GENERATE_RATE_WINDOW_SEC", bad)
            try:
                cfg = self._reloaded()
                assert cfg.QUIZ_GENERATE_RATE_LIMIT == 8, bad
                assert cfg.QUIZ_GENERATE_RATE_WINDOW_SEC == 300, bad
            finally:
                monkeypatch.undo()
                self._restore()

    def test_the_route_still_enforces_whatever_was_resolved(self):
        """The env seam moves the NUMBER, never the behaviour: the route binds
        the value at its own import and still 429s one call past it."""
        from routes import quiz as quiz_route
        from services.quiz_config import QUIZ_GENERATE_RATE_LIMIT

        assert quiz_route.QUIZ_GENERATE_RATE_LIMIT == QUIZ_GENERATE_RATE_LIMIT
        run = AsyncMock(return_value=SimpleNamespace(output=_quiz()))
        with (
            patch("routes.quiz.table", side_effect=_factory()),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            for _ in range(quiz_route.QUIZ_GENERATE_RATE_LIMIT):
                assert _generate().status_code == 200
            assert _generate().status_code == 429


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

    def test_spend_sum_is_not_truncated_by_the_postgrest_page_cap(self):
        """PostgREST caps a response at max_rows (1000) and answers with
        206 — a 2xx — so an unpaged select silently truncates. Summing that
        page plateaus below the ceiling, and the guard can never trip for
        the runaway user it exists to stop."""
        from services.quiz_config import QUIZ_DAILY_SPEND_CAP_USD

        # Sized so ONE page is not enough: 1000 rows × $0.0015 = $1.50,
        # under the $2.00 cap, while all 1500 rows = $2.25, over it. A
        # reader that trusts a single truncated response concludes the
        # user is fine; a paging reader catches them.
        per_row = 0.0015
        rows = [{"cost_usd": per_row} for _ in range(1500)]
        pages: list[tuple[int, int]] = []

        def factory(name):
            mock = MagicMock()
            if name == "llm_usage":
                def _select(columns="*", filters=None, limit=None, offset=None, **kw):
                    page_limit = min(limit or 1000, 1000)
                    start = offset or 0
                    pages.append((start, page_limit))
                    return rows[start:start + page_limit]
                mock.select.side_effect = _select
            elif name == "graph_nodes":
                mock.select.return_value = [{
                    "id": "node1", "course_id": "course1",
                    "concept_name": "Loops", "mastery_score": 0.5,
                }]
            else:
                mock.select.return_value = []
                mock.insert.return_value = [{"id": "q"}]
            return mock

        run = AsyncMock(return_value=SimpleNamespace(output=_quiz()))
        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            r = _generate()

        assert len(pages) > 1, "the spend read must page, not trust one response"
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "QUIZ_DAILY_LIMIT_REACHED"
        run.assert_not_called()
        assert 1500 * per_row > QUIZ_DAILY_SPEND_CAP_USD  # the premise

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

    def test_a_partial_quiz_survives_a_top_up_timeout(self):
        """The timeout must not throw away questions we already have.
        Cancelling the whole generation raises CancelledError — a
        BaseException — straight past #543's serve-what-we-have handler,
        turning a valid 3-question quiz into a 502."""
        import asyncio as _asyncio

        from agents.quiz import Quiz, QuizQuestion

        def _mk(n, correct=True):
            return QuizQuestion(
                question=f"Q{n}?", type="multiple_choice", difficulty="easy",
                options=[f"a{n}", f"b{n}", f"c{n}", f"d{n}"],
                correct_answer=f"a{n}" if correct else "NOPE",
                explanation="x", concept="Loops",
            )

        # 3 good, 3 drifted → drop rate high enough to trigger the top-up.
        first = Quiz(questions=[_mk(1), _mk(2), _mk(3),
                                _mk(4, False), _mk(5, False), _mk(6, False)])
        calls = {"n": 0}

        async def _run(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return SimpleNamespace(output=first)
            await _asyncio.sleep(3600)   # the top-up hangs

        with (
            patch("routes.quiz.table", side_effect=_factory()),
            patch("routes.quiz.quiz_agent.run", new=_run),
            patch("routes.quiz.QUIZ_GENERATION_TIMEOUT_SEC", 0.2),
        ):
            r = client.post("/api/quiz/generate", json={
                "user_id": "user_andres",
                "concept_node_id": "node1",
                "num_questions": 6,
                "difficulty": "easy",
                "use_shared_context": False,
            })

        assert r.status_code == 200, (
            "a completed partial generation must be served, not discarded"
        )
        assert r.json()["delivered_count"] == 3
        assert calls["n"] == 2  # the top-up was attempted and timed out

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
