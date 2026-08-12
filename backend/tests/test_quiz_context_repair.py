"""
Workstream B of the pre-revamp quiz repair batch (#529, epic #537).

The adaptive-context write has been dead since migration 0025 dropped
quiz_context's UNIQUE (user_id, concept_node_id): the upsert 42P10s and
routes/quiz.py swallowed it (`except Exception: pass`). These tests pin:

- B2: save_quiz_context targets exactly the restored constraint's columns.
- B3: the background context update is loud on failure — ERROR log +
  `quiz.context_write_failed` analytics event + re-raise in local/test
  envs so a regression fails CI instead of going quiet for months. The
  one deliberate quiet path is the E2E function-mode seam's
  UnregisteredHandlerError (quiz_context stays unregistered by design).
- B4: the read side consumes the FULL QuizContext shape — before this
  fix `_coerce_summary` returned only `notes` and silently dropped
  weak_areas / common_mistakes / questions_seen_summary (and its list
  fallback looked for `common_errors`, which QuizContext never writes).

The real-DB constraint restore + ciphertext round-trip lives in
tests/integration/test_quiz_context_repair_db.py.
"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from main import app
from agents._providers import UnregisteredHandlerError
from agents.quiz_context import QuizContext

client = TestClient(app)


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
]


def _submit_factory():
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
        else:
            mock.select.return_value = []
        mock.update.return_value = [{"id": "updated"}]
        return mock

    return factory


def _ok_ctx_agent():
    return AsyncMock(
        return_value=SimpleNamespace(output=SimpleNamespace(model_dump=lambda: {}))
    )


def _submit():
    return client.post("/api/quiz/submit", json={
        "quiz_id": "quiz1",
        "answers": [{"question_id": 1, "selected_label": "A"}],
    })


# ── B2: the upsert target is pinned to the restored constraint ──────────────


class TestSaveQuizContextUpsertTarget:
    def test_upserts_on_user_id_concept_node_id(self):
        from services.quiz_context_service import save_quiz_context

        captured = {}
        fake = MagicMock()

        def _upsert(payload, on_conflict=None):
            captured["payload"] = payload
            captured["on_conflict"] = on_conflict
            return [payload]

        fake.upsert.side_effect = _upsert
        with patch("services.quiz_context_service.table", return_value=fake):
            save_quiz_context("u1", "n1", {"weak_areas": ["x"]})

        # Must match the UNIQUE restored by the #529 repair migration
        # (quiz_context_user_concept_key) column-for-column.
        assert captured["on_conflict"] == "user_id,concept_node_id"
        # #521: ciphertext at rest.
        assert isinstance(captured["payload"]["context_json"], str)


# ── B3: failures are loud ───────────────────────────────────────────────────


class TestContextWriteFailureSurfaces:
    def test_write_failure_emits_event_and_reraises_in_test_env(self):
        """conftest sets APP_ENV=test → config.IS_LOCAL is True → the
        background task re-raises, so this exact regression class fails
        CI instead of passing silently for months (#529)."""
        events = []
        with (
            patch("routes.quiz.table", side_effect=_submit_factory()),
            patch("routes.quiz.apply_graph_update"),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.quiz_context_agent.run", new=_ok_ctx_agent()),
            patch(
                "routes.quiz.save_quiz_context",
                side_effect=RuntimeError("42P10: no unique constraint"),
            ),
            patch(
                "routes.quiz.events_service.log_event",
                side_effect=lambda *a, **k: events.append((a, k)),
            ),
        ):
            with pytest.raises(RuntimeError, match="42P10"):
                _submit()

        failed = [
            (a, k) for a, k in events if a and a[0] == "quiz.context_write_failed"
        ]
        assert len(failed) == 1, (
            "a quiz-context write failure must emit quiz.context_write_failed "
            "so it shows up in admin analytics"
        )
        _, kwargs = failed[0]
        assert kwargs.get("category") == "error"
        assert kwargs.get("user_id") == "user_andres"
        payload = kwargs.get("payload") or {}
        assert payload.get("quiz_id") == "quiz1"
        assert payload.get("concept_node_id") == "node1"

    def test_write_failure_does_not_break_submit_in_production(self, caplog):
        """In production the response already went out; the task logs at
        ERROR (with traceback) + emits the event, but must not raise."""
        import config

        events = []
        with (
            patch("routes.quiz.table", side_effect=_submit_factory()),
            patch("routes.quiz.apply_graph_update"),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.quiz_context_agent.run", new=_ok_ctx_agent()),
            patch(
                "routes.quiz.save_quiz_context",
                side_effect=RuntimeError("boom"),
            ),
            patch(
                "routes.quiz.events_service.log_event",
                side_effect=lambda *a, **k: events.append((a, k)),
            ),
            patch.object(config, "IS_LOCAL", False),
        ):
            with caplog.at_level("ERROR", logger="routes.quiz"):
                r = _submit()

        assert r.status_code == 200
        assert any(a[0] == "quiz.context_write_failed" for a, _ in events)
        assert any(
            "context update failed" in rec.message and rec.exc_info
            for rec in caplog.records
        ), "the failure must be logged at ERROR with the traceback"

    def test_unregistered_seam_handler_is_quiet_by_design(self, caplog):
        """E2E function mode leaves quiz_context deliberately unregistered
        (agents/function_handlers_e2e.py) — that fail-fast is the seam
        working, not a bug: one WARNING, no traceback, no analytics event,
        no re-raise (a raise would put tracebacks in .e2e/backend.log and
        turn the logscan oracle red on every quiz journey)."""
        events = []
        with (
            patch("routes.quiz.table", side_effect=_submit_factory()),
            patch("routes.quiz.apply_graph_update"),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch(
                "routes.quiz.quiz_context_agent.run",
                new=AsyncMock(
                    side_effect=UnregisteredHandlerError(
                        "no function-mode handler registered for task 'quiz_context'"
                    )
                ),
            ),
            patch("routes.quiz.save_quiz_context") as save_mock,
            patch(
                "routes.quiz.events_service.log_event",
                side_effect=lambda *a, **k: events.append((a, k)),
            ),
        ):
            with caplog.at_level("WARNING", logger="routes.quiz"):
                r = _submit()

        assert r.status_code == 200
        save_mock.assert_not_called()
        assert not any(a[0] == "quiz.context_write_failed" for a, _ in events)
        warnings = [
            rec for rec in caplog.records
            if rec.levelname == "WARNING" and "unregistered" in rec.message.lower()
        ]
        assert warnings, "the seam skip should leave one WARNING breadcrumb"
        assert all(not rec.exc_info for rec in warnings), (
            "no traceback — the logscan oracle treats tracebacks as findings"
        )


# ── B4: the read side consumes the whole QuizContext shape ──────────────────


class TestCoerceSummaryConsumesQuizContext:
    def test_full_quiz_context_shape_survives_coercion(self):
        from agents.tools.quiz_history import _coerce_summary

        ctx = QuizContext(
            weak_areas=["recursion base case"],
            common_mistakes=["off-by-one in loop bounds"],
            questions_seen_summary="loops and recursion basics",
            recommended_difficulty="hard",
            notes="solid on iteration",
        )
        s = _coerce_summary(ctx.model_dump())
        assert s is not None
        for fragment in (
            "recursion base case",
            "off-by-one in loop bounds",
            "loops and recursion basics",
            "solid on iteration",
        ):
            assert fragment in s, f"digest dropped: {fragment!r}"

    def test_legacy_shapes_still_coerce(self):
        from agents.tools.quiz_history import _coerce_summary

        assert _coerce_summary("plain digest") == "plain digest"
        assert _coerce_summary({"summary": "s"}) == "s"
        assert _coerce_summary({"notes": "n"}) == "n"
        assert (
            "wrong base case"
            in _coerce_summary({"misconceptions": ["wrong base case"]})
        )
        assert _coerce_summary(None) is None
        assert _coerce_summary({}) is None

    def test_encrypted_context_row_reaches_the_agent_tool_summary(self):
        """The full read wire: a ciphertext context_json row (what
        save_quiz_context writes, #521) decrypts inside
        read_recent_quiz_attempts and its digest lands in the
        QuizHistory.summary the quiz agent consumes."""
        import asyncio

        from agents.tools.quiz_history import read_recent_quiz_attempts
        from services.encryption import encrypt_json

        stored = QuizContext(
            weak_areas=["recursion base case"],
            common_mistakes=["off-by-one in loop bounds"],
            questions_seen_summary="loops and recursion basics",
            recommended_difficulty="hard",
            notes="solid on iteration",
        ).model_dump()

        def factory(name):
            mock = MagicMock()
            if name == "quiz_context":
                mock.select.return_value = [
                    {"context_json": encrypt_json(stored)}
                ]
            else:
                mock.select.return_value = []
            return mock

        with patch("agents.tools.quiz_history.table", side_effect=factory):
            history = asyncio.run(read_recent_quiz_attempts("u1", "n1"))

        assert history.summary is not None
        for fragment in (
            "recursion base case",
            "off-by-one in loop bounds",
            "loops and recursion basics",
        ):
            assert fragment in history.summary
