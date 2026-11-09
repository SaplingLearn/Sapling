"""
#760 (state-machine audit, workstream D): the quiz attempt lifecycle.

- Submit validates its pure preconditions BEFORE the completed_at claim, and
  once it has claimed, the score always lands: a grading/score-write failure
  releases the claim, and a graph/mastery failure is logged + emitted without
  failing the submit. Before this, either raised AFTER the claim and stranded
  the attempt completed-but-scoreless: every retry 409'd and no XP was paid.
- The abandon sweep exempts attempts with recent answer activity (the same
  liveness rule `_attempt_status` applies), and the history list derives its
  status with that activity so it agrees with GET /attempts/{id}.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from main import app
from tests.db_fakes import with_async_twins
from tests.quiz_patches import patch_quiz
import pytest

# #117: a sync PostgREST call reached on the event loop raises here.
pytestmark = pytest.mark.usefixtures("no_sync_db_on_loop")

client = TestClient(app, raise_server_exceptions=False)


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

NODE = {"id": "node1", "concept_name": "Loops", "mastery_score": 0.5, "course_id": "course1"}


def _ago(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


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
        "created_at": _ago(hours=1),
    }
    row.update(overrides)
    return row


def _submit_factory(*, nodes, update_calls, score_write_error=None):
    def factory(name):
        mock = MagicMock()
        if name == "quiz_attempts":
            mock.select.return_value = [_attempt_row()]

            def _update(data, filters=None, **kw):
                update_calls.append((data, filters))
                if score_write_error is not None and "score" in data:
                    raise score_write_error
                return [{"id": "quiz1"}]
            mock.update.side_effect = _update
        elif name == "graph_nodes":
            mock.select.return_value = nodes
        else:
            mock.select.return_value = []
            mock.update.return_value = []
        return mock

    return factory


def _ctx_patches():
    return (
        patch_quiz("get_quiz_context", return_value={}),
        patch(
            "services.quiz.submission.quiz_context_agent.run",
            new=AsyncMock(return_value=SimpleNamespace(
                output=SimpleNamespace(model_dump=lambda: {})
            )),
        ),
        patch_quiz("save_quiz_context"),
    )


def _submit():
    return client.post("/api/quiz/submit", json={
        "quiz_id": "quiz1",
        "answers": [{"question_id": 1, "selected_label": "B"}],
    })


class TestSubmitValidatesBeforeClaiming:
    def test_a_missing_concept_404s_without_claiming_the_attempt(self):
        update_calls: list = []
        apply_mock = MagicMock()
        a, b, c = _ctx_patches()
        with (
            patch_quiz("table",
                  side_effect=_submit_factory(nodes=[], update_calls=update_calls)),
            patch_quiz("apply_graph_update", new=apply_mock),
            a, b, c,
        ):
            r = _submit()

        assert r.status_code == 404
        assert r.json()["error"]["code"] == "QUIZ_CONCEPT_NOT_FOUND"
        assert update_calls == [], (
            "a precondition that 404s after the claim strands the attempt "
            "completed-but-scoreless — every retry then 409s"
        )
        apply_mock.assert_not_called()


class TestTheScoreAlwaysLands:
    def test_a_graph_failure_still_scores_and_is_countable(self):
        update_calls: list = []
        a, b, c = _ctx_patches()
        with (
            patch_quiz("table",
                  side_effect=_submit_factory(nodes=[NODE], update_calls=update_calls)),
            patch_quiz("apply_graph_update",
                  new=MagicMock(side_effect=RuntimeError("graph down"))),
            patch("services.events_service.log_event") as log_event,
            patch_quiz("award_xp_safe") as award,
            a, b, c,
        ):
            r = _submit()

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["score"] == 1 and body["total"] == 1
        # Mastery did not move, so it is not reported as if it had.
        assert body["mastery_after"] == body["mastery_before"] == 0.5
        scored = [d for d, _ in update_calls if "score" in d]
        assert scored and scored[0]["score"] == 1
        # No fabricated history snapshot for a graph write that never happened.
        assert not [d for d, _ in update_calls if "mastery_after" in d]
        events = [c.args[0] for c in log_event.call_args_list if c.args]
        assert "quiz.mastery_write_failed" in events
        assert "quiz.completed" in events
        award.assert_called_once()

    def test_a_failed_score_write_releases_the_claim(self):
        update_calls: list = []
        apply_mock = MagicMock()
        a, b, c = _ctx_patches()
        with (
            patch_quiz("table", side_effect=_submit_factory(
                nodes=[NODE], update_calls=update_calls,
                score_write_error=RuntimeError("PostgREST down"),
            )),
            patch_quiz("apply_graph_update", new=apply_mock),
            a, b, c,
        ):
            r = _submit()

        assert r.status_code == 500
        apply_mock.assert_not_called()
        claim_data, _ = update_calls[0]
        stamp = claim_data["completed_at"]
        assert stamp
        release = [(d, f) for d, f in update_calls if d == {"completed_at": None}]
        assert len(release) == 1, "the claim must be handed back for a retry"
        _, filters = release[0]
        # Only the row THIS request closed, and only while still unscored.
        assert filters["id"] == "eq.quiz1"
        assert filters["completed_at"] == f"eq.{stamp}"
        assert filters["score"] == "is.null"


# ── sweep + history agree with the liveness rule ────────────────────────────


def _sweep_factory(*, stale_ids, recent_responses, update_calls, select_calls=None):
    def factory(name):
        mock = MagicMock()
        if name == "quiz_attempts":
            def _select(columns="*", filters=None, **kw):
                if select_calls is not None:
                    select_calls.append(filters)
                return [{"id": i} for i in stale_ids]
            mock.select.side_effect = _select

            def _update(data, filters=None, **kw):
                update_calls.append((data, filters, kw))
                return []
            mock.update.side_effect = _update
        elif name == "quiz_responses":
            def _rselect(columns="*", filters=None, **kw):
                return recent_responses
            mock.select.side_effect = _rselect
        return mock

    return factory


class TestSweepExemptsLiveAttempts:
    def test_an_old_attempt_answered_recently_is_not_swept(self):
        from routes.quiz import _sweep_abandoned

        update_calls: list = []
        with patch_quiz("table", side_effect=_sweep_factory(
            stale_ids=["old-dead", "old-live"],
            recent_responses=[{"attempt_id": "old-live", "answered_at": _ago(minutes=5)}],
            update_calls=update_calls,
        )):
            _sweep_abandoned("user_andres")

        assert len(update_calls) == 1
        data, filters, kw = update_calls[0]
        assert "abandoned_at" in data
        assert filters["id"] == "in.(old-dead)"
        # The conditional filters still arbitrate the write itself.
        assert filters["completed_at"] == "is.null"
        assert filters["abandoned_at"] == "is.null"
        assert filters["created_at"].startswith("lt.")
        assert kw.get("prefer_return_minimal") is True

    def test_nothing_stale_writes_nothing(self):
        from routes.quiz import _sweep_abandoned

        update_calls: list = []
        with patch_quiz("table", side_effect=_sweep_factory(
            stale_ids=[], recent_responses=[], update_calls=update_calls,
        )):
            _sweep_abandoned("user_andres")
        assert update_calls == []

    def test_every_stale_attempt_live_writes_nothing(self):
        from routes.quiz import _sweep_abandoned

        update_calls: list = []
        with patch_quiz("table", side_effect=_sweep_factory(
            stale_ids=["a"],
            recent_responses=[{"attempt_id": "a", "answered_at": _ago(minutes=1)}],
            update_calls=update_calls,
        )):
            _sweep_abandoned("user_andres")
        assert update_calls == []

    def test_an_unreadable_activity_check_sweeps_nothing(self):
        """Fail safe: if liveness can't be read, stamping would close a quiz
        the student may be in the middle of. Wait for the next read."""
        from routes.quiz import _sweep_abandoned

        update_calls: list = []

        def factory(name):
            mock = _sweep_factory(
                stale_ids=["a"], recent_responses=[], update_calls=update_calls,
            )(name)
            if name == "quiz_responses":
                mock.select.side_effect = RuntimeError("down")
            return mock

        with patch_quiz("table", side_effect=factory):
            _sweep_abandoned("user_andres")
        assert update_calls == []


class TestHistoryStatusMatchesGetAttempt:
    def test_an_old_but_recently_answered_attempt_lists_as_in_progress(self):
        old_live = _attempt_row(id="old-live", created_at=_ago(days=3))
        responses = [{"attempt_id": "old-live", "answered_at": _ago(minutes=3)}]

        def factory(name):
            mock = MagicMock()
            if name == "quiz_attempts":
                # The sweep's candidate read: the live attempt is stale by
                # created_at, and must survive because of its activity.
                mock.select.side_effect = lambda columns="*", filters=None, **kw: (
                    [{"id": "old-live"}] if columns == "id" else [old_live]
                )
                mock.update.return_value = []
                mock.select_with_count.return_value = ([old_live], 1)
            elif name == "quiz_responses":
                mock.select.return_value = responses
            elif name == "graph_nodes":
                mock.select.return_value = [NODE]
            else:
                mock.select.return_value = []
            return mock

        with patch_quiz("table", side_effect=with_async_twins(factory)):
            listed = client.get("/api/quiz/attempts", params={"user_id": "user_andres"})
            single = client.get("/api/quiz/attempts/old-live")

        assert listed.status_code == 200, listed.text
        assert listed.json()["attempts"][0]["status"] == "in_progress"
        assert single.json()["status"] == "in_progress"
