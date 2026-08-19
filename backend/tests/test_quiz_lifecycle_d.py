"""
Workstream D of the pre-revamp quiz repair batch (#542, epic #537):
attempt lifecycle.

- D1: submit persists mastery_before / mastery_after on the attempt row.
- D2: status is DERIVED (completed_at → completed, abandoned_at →
  abandoned, else in_progress); a lazy per-user TTL sweep stamps
  abandoned_at; GET /api/quiz/attempts/{id} returns resume state —
  questions WITHOUT the answer key, plus recorded responses.
- D3: the quizzes_completed achievement stat counts completed attempts
  only (an abandoned generate no longer advances quizzes_10).
- D4: GET /api/quiz/attempts — paginated history for the signed-in user.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


QUESTIONS = [
    {
        "id": 1,
        "question": "Q1?",
        "options": [
            {"label": "A", "text": "a1", "correct": False},
            {"label": "B", "text": "b1", "correct": True},
        ],
        "explanation": "B is right.",
        "concept_tested": "Loops",
        "difficulty": "medium",
    },
]


def _recent() -> str:
    """A created_at inside the abandon TTL — relative, so the suite doesn't
    rot as wall-clock time passes the fixture date."""
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def _attempt_row(**overrides) -> dict:
    row = {
        "id": "quiz1",
        "user_id": "user_andres",
        "concept_node_id": "node1",
        "difficulty": "medium",
        "questions_json": QUESTIONS,
        "score": None,
        "total": None,
        "completed_at": None,
        "abandoned_at": None,
        "mastery_before": None,
        "mastery_after": None,
        "created_at": _recent(),
    }
    row.update(overrides)
    return row


# ── D1: mastery snapshot persisted at submit ────────────────────────────────


class TestMasterySnapshotPersisted:
    def test_submit_writes_mastery_before_and_after(self):
        update_calls: list = []

        def factory(name):
            mock = MagicMock()
            if name == "quiz_attempts":
                mock.select.return_value = [_attempt_row()]

                def _update(data, filters=None):
                    update_calls.append(data)
                    return [{"id": "quiz1"}]
                mock.update.side_effect = _update
            elif name == "graph_nodes":
                mock.select.return_value = [{
                    "mastery_score": 0.5,
                    "concept_name": "Loops",
                    "course_id": "course1",
                }]
            else:
                mock.select.return_value = []
                mock.update.return_value = []
            return mock

        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.apply_graph_update"),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch(
                "routes.quiz.quiz_context_agent.run",
                new=AsyncMock(return_value=SimpleNamespace(
                    output=SimpleNamespace(model_dump=lambda: {})
                )),
            ),
            patch("routes.quiz.save_quiz_context"),
        ):
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "B"}],
            })

        assert r.status_code == 200
        final = [d for d in update_calls if "score" in d]
        assert len(final) == 1
        row = final[0]
        assert row["mastery_before"] == 0.5
        assert row["mastery_after"] == r.json()["mastery_after"]

    def test_snapshot_records_what_the_graph_actually_wrote(self):
        """apply_graph_update owns the write (it clamps and resolves by
        concept name); persisting submit's local prediction instead would
        let history show progression the graph never took."""
        update_calls: list = []

        def factory(name):
            mock = MagicMock()
            if name == "quiz_attempts":
                mock.select.return_value = [_attempt_row()]

                def _update(data, filters=None, **kw):
                    update_calls.append(data)
                    return [{"id": "quiz1"}]
                mock.update.side_effect = _update
            elif name == "graph_nodes":
                mock.select.return_value = [{
                    "mastery_score": 0.5,
                    "concept_name": "Loops",
                    "course_id": "course1",
                }]
            else:
                mock.select.return_value = []
                mock.update.return_value = []
            return mock

        # The graph clamped to 0.9 rather than the 0.53 submit predicted.
        applied = MagicMock(return_value=[
            {"concept": "Loops", "before": 0.5, "after": 0.9},
        ])
        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.apply_graph_update", new=applied),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch(
                "routes.quiz.quiz_context_agent.run",
                new=AsyncMock(return_value=SimpleNamespace(
                    output=SimpleNamespace(model_dump=lambda: {})
                )),
            ),
            patch("routes.quiz.save_quiz_context"),
        ):
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "B"}],
            })

        assert r.status_code == 200
        stored = [d for d in update_calls if "score" in d][0]
        assert stored["mastery_after"] == 0.9
        assert r.json()["mastery_after"] == 0.9


# ── D2: derived status + resume ─────────────────────────────────────────────


class TestAttemptResume:
    def _factory(self, attempt, responses=None):
        def factory(name):
            mock = MagicMock()
            if name == "quiz_attempts":
                mock.select.return_value = [attempt] if attempt else []
            elif name == "quiz_responses":
                mock.select.return_value = responses or []
            else:
                mock.select.return_value = []
            return mock

        return factory

    def test_resume_never_ships_the_explanation(self):
        """The explanation names the correct option in prose ("B is
        right."), so shipping it on resume hands over the answer key in a
        different field — the exact hole C3/D2 exist to close."""
        with patch("routes.quiz.table",
                   side_effect=self._factory(_attempt_row())):
            r = client.get("/api/quiz/attempts/quiz1")
        assert r.status_code == 200
        body = r.text
        assert "B is right." not in body
        for q in r.json()["questions"]:
            assert "explanation" not in q

    def test_resume_refuses_unrecognised_stored_shapes(self):
        """_strip_answer_key only understands the current wire shape. A
        legacy/foreign row (e.g. the seed's {"q":..., "a": "Av = λv"})
        must NOT be passed through with its answer intact and an empty
        options list — refuse the resume instead."""
        legacy = _attempt_row(questions_json=[
            {"q": "What defines an eigenvalue?", "a": "Av = lambda v"},
        ])
        with patch("routes.quiz.table", side_effect=self._factory(legacy)):
            r = client.get("/api/quiz/attempts/quiz1")
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_NOT_RESUMABLE"
        assert "Av = lambda v" not in r.text

    def test_abandoned_attempt_is_not_resumable(self):
        """A swept attempt must stop being offered — the config comment
        promises exactly this, and serving its questions while /answer and
        /submit still accept them makes the TTL enforce nothing."""
        abandoned = _attempt_row(abandoned_at="2026-08-12T01:00:00+00:00")
        with patch("routes.quiz.table", side_effect=self._factory(abandoned)):
            r = client.get("/api/quiz/attempts/quiz1")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "abandoned"
        assert data["questions"] == [], "an abandoned attempt must not serve questions"
        assert data["resumable"] is False

    def test_resume_returns_keyless_questions_and_responses(self):
        responses = [{
            "attempt_id": "quiz1", "question_index": 0,
            "selected_index": 1, "is_correct": True,
            "time_ms": 900, "confidence": None,
            "answered_at": "2026-08-12T00:01:00+00:00",
        }]
        with patch("routes.quiz.table",
                   side_effect=self._factory(_attempt_row(), responses)):
            r = client.get("/api/quiz/attempts/quiz1")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "in_progress"
        assert data["quiz_id"] == "quiz1"
        # The key must never ride along on a resume payload.
        for q in data["questions"]:
            assert all("correct" not in o for o in q["options"])
        assert data["responses"][0]["question_index"] == 0
        assert data["responses"][0]["is_correct"] is True

    def test_status_derivations(self):
        cases = [
            (_attempt_row(completed_at="2026-08-12T01:00:00+00:00",
                          score=1, total=1), "completed"),
            (_attempt_row(abandoned_at="2026-08-12T01:00:00+00:00"), "abandoned"),
            (_attempt_row(), "in_progress"),
        ]
        for attempt, expected in cases:
            with patch("routes.quiz.table", side_effect=self._factory(attempt)):
                r = client.get("/api/quiz/attempts/quiz1")
            assert r.status_code == 200
            assert r.json()["status"] == expected

    def test_unknown_attempt_404s(self):
        with patch("routes.quiz.table", side_effect=self._factory(None)):
            r = client.get("/api/quiz/attempts/nope")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_NOT_FOUND"


class TestAbandonedIsEnforced:
    """The abandoned state has to bite on the WRITE paths too, or it's a
    label: /answer and /submit both accepted swept attempts and paid out
    mastery, XP and achievements."""

    def _factory(self, attempt, responses=None):
        def factory(name):
            mock = MagicMock()
            if name == "quiz_attempts":
                mock.select.return_value = [attempt]
                mock.update.return_value = []
            elif name == "quiz_responses":
                mock.select.return_value = responses or []
            elif name == "graph_nodes":
                mock.select.return_value = [{
                    "mastery_score": 0.5, "concept_name": "Loops",
                    "course_id": "course1",
                }]
            else:
                mock.select.return_value = []
                mock.update.return_value = []
            return mock

        return factory

    def test_answer_on_an_abandoned_attempt_409s(self):
        abandoned = _attempt_row(abandoned_at="2026-08-12T01:00:00+00:00")
        with patch("routes.quiz.table", side_effect=self._factory(abandoned)):
            r = client.post("/api/quiz/attempts/quiz1/answer", json={
                "question_index": 0, "selected_index": 1,
            })
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_ABANDONED"

    def test_submit_of_an_abandoned_attempt_409s_and_writes_nothing(self):
        abandoned = _attempt_row(abandoned_at="2026-08-12T01:00:00+00:00")
        apply_mock = MagicMock()
        with (
            patch("routes.quiz.table", side_effect=self._factory(abandoned)),
            patch("routes.quiz.apply_graph_update", new=apply_mock),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.save_quiz_context"),
        ):
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "B"}],
            })
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_ABANDONED"
        apply_mock.assert_not_called()


# ── D2: lazy TTL sweep ──────────────────────────────────────────────────────


class TestAbandonSweep:
    def test_sweep_marks_stale_in_progress_attempts(self):
        """The per-user sweep stamps abandoned_at on in-progress rows older
        than the TTL — conditional update filters arbitrate, not app code."""
        from routes.quiz import _sweep_abandoned
        from services.quiz_config import QUIZ_ATTEMPT_ABANDON_TTL_HOURS

        update_calls = []

        def factory(name):
            mock = MagicMock()
            if name == "quiz_attempts":
                def _update(data, filters=None, *, prefer_return_minimal=False):
                    update_calls.append((data, filters, prefer_return_minimal))
                    return []
                mock.update.side_effect = _update
            return mock

        with patch("routes.quiz.table", side_effect=factory):
            _sweep_abandoned("user_andres")

        assert len(update_calls) == 1
        data, filters, minimal = update_calls[0]
        assert "abandoned_at" in data
        # A write triggered by a GET must not drag every swept row (with
        # its encrypted blobs) back over the wire.
        assert minimal is True
        assert filters["user_id"] == "eq.user_andres"
        assert filters["completed_at"] == "is.null"
        assert filters["abandoned_at"] == "is.null"
        cutoff_expr = filters["created_at"]
        assert cutoff_expr.startswith("lt.")
        cutoff = datetime.fromisoformat(cutoff_expr[3:])
        expected = datetime.now(timezone.utc) - timedelta(
            hours=QUIZ_ATTEMPT_ABANDON_TTL_HOURS
        )
        assert abs((cutoff - expected).total_seconds()) < 60

    def test_recent_answer_activity_keeps_an_attempt_alive(self):
        """An attempt generated long ago but answered minutes ago is being
        worked on — sweeping it by created_at alone would strand the
        responses already recorded against it."""
        from routes.quiz import _attempt_status

        old_attempt = _attempt_row(
            created_at=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        )
        assert _attempt_status(old_attempt) == "abandoned"
        assert _attempt_status(
            old_attempt,
            last_activity_at=(
                datetime.now(timezone.utc) - timedelta(minutes=2)
            ).isoformat(),
        ) == "in_progress"

    def test_naive_created_at_does_not_explode(self):
        """A timezone-naive timestamp (out-of-band write) parses fine and
        then raises TypeError on the aware comparison — past the
        ValueError guard."""
        from routes.quiz import _attempt_status

        naive = _attempt_row(created_at="2020-01-01T00:00:00")
        assert _attempt_status(naive) in {"abandoned", "in_progress"}

    def test_unparseable_created_at_does_not_explode(self):
        from routes.quiz import _attempt_status

        assert _attempt_status(_attempt_row(created_at="not-a-date")) == "in_progress"


# ── D3: achievements count completed attempts only ──────────────────────────


class TestAchievementCountsCompletedOnly:
    def test_quizzes_completed_stat_requires_a_recorded_score(self):
        """completed_at is stamped by the atomic claim BEFORE grading, so
        filtering on it alone still counts attempts that were never scored
        (e.g. the graph read 404s after the claim). The evidence a quiz was
        really finished is a persisted score — the same signal
        agents/tools/quiz_history.py treats as completion."""
        from services import achievement_service

        captured = {}

        def _fake_table(name):
            mock = MagicMock()

            def _select(columns="*", filters=None, **kw):
                captured["table"] = name
                captured["filters"] = filters
                return []
            mock.select.side_effect = _select
            return mock

        with patch("services.achievement_service.table", side_effect=_fake_table):
            achievement_service.get_user_stat("u1", "quizzes_completed")

        assert captured["table"] == "quiz_attempts"
        filters = captured["filters"]
        assert filters["completed_at"] == "not.is.null", (
            "an abandoned generate must not advance quizzes_10 (#542 D3)"
        )
        assert filters["score"] == "not.is.null", (
            "a claimed-but-never-graded attempt must not advance quizzes_10"
        )


# ── D4: paginated history ───────────────────────────────────────────────────


class TestAttemptHistory:
    def test_history_lists_the_sessions_users_attempts(self):
        attempts = [
            _attempt_row(id="q-new", completed_at="2026-08-12T02:00:00+00:00",
                         score=2, total=3, mastery_before=0.5,
                         mastery_after=0.55,
                         created_at="2026-08-12T01:59:00+00:00"),
            _attempt_row(id="q-old", abandoned_at="2026-08-11T00:10:00+00:00",
                         created_at="2026-08-11T00:00:00+00:00"),
        ]

        selected = {}

        def factory(name):
            mock = MagicMock()
            if name == "quiz_attempts":
                def _swc(columns="*", filters=None, order=None, limit=None, offset=None):
                    selected["columns"] = columns
                    return attempts, 2
                mock.select_with_count.side_effect = _swc
                mock.update.return_value = []
            elif name == "graph_nodes":
                mock.select.return_value = [{
                    "id": "node1", "concept_name": "Loops",
                    "course_id": "course1",
                }]
            else:
                mock.select.return_value = []
            return mock

        with patch("routes.quiz.table", side_effect=factory):
            r = client.get("/api/quiz/attempts", params={"user_id": "user_andres"})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2
        first = data["attempts"][0]
        assert first["quiz_id"] == "q-new"
        assert first["status"] == "completed"
        assert first["concept_name"] == "Loops"
        assert first["course_id"] == "course1"
        assert first["score"] == 2
        assert first["total"] == 3
        assert first["difficulty"] == "medium"
        assert first["mastery_delta"] == 0.05
        assert first["created_at"] == attempts[0]["created_at"]
        second = data["attempts"][1]
        assert second["status"] == "abandoned"
        assert second["mastery_delta"] is None
        # No question payloads (and therefore no keys) on the history list.
        # Asserted against the SELECTED COLUMNS, not the mocked rows: the
        # rows above happen to carry questions_json, so `"questions" not in
        # first` alone would pass even if the route echoed them.
        assert "questions" not in first
        assert "questions_json" not in first
        assert "questions_json" not in selected["columns"], (
            "history must not even fetch the question payloads"
        )

    def test_offset_is_clamped_at_the_top(self):
        """An arbitrarily large offset is stringified into PostgREST's
        offset param and Postgres rejects it as bigint-out-of-range —
        a 500 where an empty page is the honest answer."""
        captured = {}

        def factory(name):
            mock = MagicMock()
            if name == "quiz_attempts":
                def _swc(columns="*", filters=None, order=None, limit=None, offset=None):
                    captured["offset"] = offset
                    return [], 0
                mock.select_with_count.side_effect = _swc
                mock.update.return_value = []
            else:
                mock.select.return_value = []
            return mock

        with patch("routes.quiz.table", side_effect=factory):
            r = client.get("/api/quiz/attempts", params={
                "user_id": "user_andres", "offset": 99999999999999999999,
            })
        assert r.status_code == 200
        assert captured["offset"] < 2**31

    def test_pagination_order_has_a_unique_tiebreaker(self):
        """Rows sharing a created_at need a stable secondary sort or they
        can repeat/vanish across page boundaries (the created_at,id
        precedent in gamification.py)."""
        captured = {}

        def factory(name):
            mock = MagicMock()
            if name == "quiz_attempts":
                def _swc(columns="*", filters=None, order=None, limit=None, offset=None):
                    captured["order"] = order
                    return [], 0
                mock.select_with_count.side_effect = _swc
                mock.update.return_value = []
            else:
                mock.select.return_value = []
            return mock

        with patch("routes.quiz.table", side_effect=factory):
            client.get("/api/quiz/attempts", params={"user_id": "user_andres"})
        assert "id" in captured["order"]
