"""#555 (Workstream H3, epic #537): how close is the next exam?

`assignments.due_date` is plaintext and indexed, and nothing anywhere computed
"exam in N days" — so a quiz taken the night before a midterm was generated
exactly like one taken in week two.

DATES ONLY. No grade values enter any prompt: the audit flags that the current
ToS and privacy policy don't clearly cover that, and this feature does not need
it. `points_earned`/`points_possible` are encrypted anyway; nothing here reads
or decrypts them.
"""
from datetime import date, timedelta
from unittest.mock import patch

from services.exam_proximity import days_until_next_exam, is_exam


def _due(days_from_today: int) -> str:
    return (date(2026, 8, 22) + timedelta(days=days_from_today)).isoformat()


class TestIsExam:
    """The heuristic is EXTRACTED from routes/study_guide.py, not re-written —
    a second copy would drift, which is #557's whole lesson one workstream
    earlier."""

    def test_assignment_type_exam_counts(self):
        assert is_exam({"assignment_type": "Exam", "title": "Week 4 review"})

    def test_title_keywords_count(self):
        for title in ["Midterm 1", "Final Exam", "Pop QUIZ", "unit exam"]:
            assert is_exam({"assignment_type": "homework", "title": title}), title

    def test_ordinary_work_does_not(self):
        assert not is_exam({"assignment_type": "homework", "title": "Problem set 3"})

    def test_missing_fields_do_not_raise(self):
        assert not is_exam({})
        assert not is_exam({"assignment_type": None, "title": None})


class TestDaysUntilNextExam:
    def _run(self, rows, offerings=("off-1",), today=date(2026, 8, 22)):
        with (
            patch("services.exam_proximity.user_offering_ids_for_course",
                  return_value=list(offerings)),
            patch("services.exam_proximity._enrollment_ids", return_value=["enr-1"]),
            patch("services.exam_proximity.table") as t,
            patch("services.exam_proximity._today", return_value=today),
        ):
            t.return_value.select.return_value = rows
            return days_until_next_exam("u1", "course-1")

    def test_returns_days_to_the_soonest_future_exam(self):
        rows = [
            {"title": "Final Exam", "assignment_type": "exam", "due_date": _due(30)},
            {"title": "Midterm", "assignment_type": "exam", "due_date": _due(3)},
        ]
        assert self._run(rows) == 3

    def test_ignores_non_exams(self):
        rows = [
            {"title": "Problem set", "assignment_type": "homework", "due_date": _due(1)},
            {"title": "Midterm", "assignment_type": "exam", "due_date": _due(9)},
        ]
        assert self._run(rows) == 9

    def test_a_past_exam_is_not_upcoming(self):
        rows = [{"title": "Midterm", "assignment_type": "exam", "due_date": _due(-2)}]
        assert self._run(rows) is None

    def test_an_exam_today_is_zero_not_none(self):
        """Zero is the most actionable value this feature produces; returning
        None for it would silently drop the exact case it exists for."""
        rows = [{"title": "Final", "assignment_type": "exam", "due_date": _due(0)}]
        assert self._run(rows) == 0

    def test_no_exams_is_none(self):
        assert self._run([]) is None

    def test_unparseable_due_dates_are_skipped_not_fatal(self):
        rows = [
            {"title": "Midterm", "assignment_type": "exam", "due_date": "not-a-date"},
            {"title": "Final", "assignment_type": "exam", "due_date": None},
            {"title": "Quiz 2", "assignment_type": "exam", "due_date": _due(5)},
        ]
        assert self._run(rows) == 5

    def test_no_enrollments_short_circuits_without_reading_assignments(self):
        with (
            patch("services.exam_proximity.user_offering_ids_for_course", return_value=[]),
            patch("services.exam_proximity.table") as t,
        ):
            assert days_until_next_exam("u1", "course-1") is None
        t.assert_not_called()

    def test_never_raises(self):
        """It runs on the quiz generation request path. One optional prompt
        line is not worth failing a generation over."""
        with patch("services.exam_proximity.user_offering_ids_for_course",
                   side_effect=RuntimeError("db down")):
            assert days_until_next_exam("u1", "course-1") is None

    def test_no_course_is_none(self):
        assert days_until_next_exam("u1", None) is None


# ── wiring into generation (#555) ───────────────────────────────────────────


def _agent_run():
    """A quiz_agent.run stand-in returning one valid question."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from agents.quiz import Quiz, QuizQuestion

    return AsyncMock(return_value=SimpleNamespace(output=Quiz(questions=[
        QuizQuestion(question="Q?", type="multiple_choice", difficulty="easy",
                     options=["a", "b", "c", "d"], correct_answer="a",
                     explanation="x", concept="X")])))


class TestExamProximityReachesGeneration:
    """The service being right is half of it; the other half is that its
    answer actually reaches the model AND the attempt row. Both are one
    keyword away from being silently dropped."""

    def _generate(self, days, agent_run):
        from unittest.mock import MagicMock
        from fastapi.testclient import TestClient

        from main import app

        inserted: list = []

        def factory(name):
            m = MagicMock()
            m.select.return_value = (
                [{"id": "node1", "user_id": "user_andres", "course_id": "c1",
                  "concept_name": "Recursion", "mastery_score": 0.5}]
                if name == "graph_nodes" else []
            )
            m.insert.side_effect = lambda row, *a, **k: inserted.append((name, row)) or []
            return m

        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.days_until_next_exam", return_value=days),
            patch("routes.quiz.recent_question_identities", return_value=[]),
            patch("routes.quiz.quiz_agent.run", new=agent_run),
        ):
            r = TestClient(app).post("/api/quiz/generate", json={
                "user_id": "user_andres", "concept_node_id": "node1",
                "num_questions": 1, "difficulty": "easy",
                "use_shared_context": False,
            })
        assert r.status_code == 200, r.text
        attempt = next(row for name, row in inserted if name == "quiz_attempts")
        return agent_run.call_args[0][0], attempt

    def test_a_near_exam_reaches_the_prompt_and_the_attempt_row(self):
        msg, attempt = self._generate(3, _agent_run())

        assert "next exam in this course is in 3 days" in msg
        assert attempt["exam_days_away"] == 3

    def test_an_exam_today_says_TODAY(self):
        msg, attempt = self._generate(0, _agent_run())

        assert "next exam in this course is TODAY" in msg
        # 0 must survive to the row: `if exam_days_away:` would drop exam day,
        # the single most actionable value the feature produces.
        assert attempt["exam_days_away"] == 0

    def test_unknown_proximity_adds_nothing_and_omits_the_column(self):
        """'next exam: unknown' is prompt tokens spent to say nothing, and
        omitting the key (rather than sending null) keeps generation working
        on an environment that took this code before the migration."""
        msg, attempt = self._generate(None, _agent_run())

        assert "next exam" not in msg
        assert "exam_days_away" not in attempt


# ── review findings: strictness, horizon, pre-migration insert ──────────────


class TestStrictnessOnTheDecisionPath:
    """`is_exam` drives a user-visible LIST, where a false positive costs one
    extra row. `is_exam_strict` drives a PROMPT and a stored analytics column,
    where a false positive poisons the question the column exists to answer."""

    def test_a_weekly_quiz_is_not_an_exam_deadline(self):
        from services.exam_proximity import is_exam, is_exam_strict

        row = {"assignment_type": "homework", "title": "Quiz 4"}
        assert is_exam(row), "the picker still lists it"
        assert not is_exam_strict(row), (
            "a course with weekly quizzes would otherwise have an 'exam' "
            "within a week all semester, making the treatment group for "
            "'do deadline-aware quizzes perform differently' meaningless"
        )

    def test_a_final_draft_is_not_a_final(self):
        from services.exam_proximity import is_exam_strict

        assert not is_exam_strict(
            {"assignment_type": "homework", "title": "Final draft - essay 2"}
        )

    def test_a_real_exam_still_counts_both_ways(self):
        from services.exam_proximity import is_exam, is_exam_strict

        for row in (
            {"assignment_type": "exam", "title": "Week 4"},
            {"assignment_type": "homework", "title": "Midterm 2"},
            {"assignment_type": "homework", "title": "Final Exam"},
        ):
            assert is_exam(row) and is_exam_strict(row), row


class TestPromptHorizon:
    """A final dated 87 days out would otherwise put 'there is an exam coming'
    on every quiz for the whole semester — no proximity signal at all, and it
    steers week-two practice toward exam-style questions."""

    def test_a_distant_exam_is_stored_but_not_prompted(self):
        from services.exam_proximity import PROMPT_HORIZON_DAYS

        far = PROMPT_HORIZON_DAYS + 30
        msg, attempt = TestExamProximityReachesGeneration()._generate(far, _agent_run())

        assert "next exam" not in msg
        # The COLUMN is not clamped: the analytics want the real distance.
        assert attempt["exam_days_away"] == far

    def test_an_exam_on_the_horizon_boundary_is_still_prompted(self):
        from services.exam_proximity import PROMPT_HORIZON_DAYS

        msg, _ = TestExamProximityReachesGeneration()._generate(
            PROMPT_HORIZON_DAYS, _agent_run()
        )
        assert f"in {PROMPT_HORIZON_DAYS} days" in msg


def test_the_attempt_insert_survives_a_schema_without_the_column():
    """Pre-migration (or before PostgREST reloads its schema cache) the column
    is unknown and the insert 400s — and it strikes exactly the students who
    HAVE an upcoming exam, so it looks like a random partial outage. It would
    land after the agent already ran and was billed: quiz lost, no attempt
    row, no failure event, no rate-limit refund. Retry without the key."""
    from unittest.mock import MagicMock, patch as _patch

    from routes.quiz import _insert_attempt

    calls: list = []
    tbl = MagicMock()

    def _insert(row):
        calls.append(row)
        if "exam_days_away" in row:
            raise RuntimeError("PGRST204: column not found")
        return []

    tbl.insert.side_effect = _insert
    with _patch("routes.quiz.table", return_value=tbl):
        _insert_attempt({"id": "q1", "user_id": "u1", "exam_days_away": 3})

    assert len(calls) == 2
    assert "exam_days_away" not in calls[1]
    assert calls[1]["id"] == "q1"


def test_an_insert_failure_unrelated_to_the_column_still_raises():
    """The retry must not become a blanket swallow — a genuine write failure
    has to keep surfacing."""
    from unittest.mock import MagicMock, patch as _patch

    import pytest as _pytest

    from routes.quiz import _insert_attempt

    tbl = MagicMock()
    tbl.insert.side_effect = RuntimeError("connection refused")
    with _patch("routes.quiz.table", return_value=tbl):
        with _pytest.raises(RuntimeError):
            _insert_attempt({"id": "q1", "user_id": "u1"})
