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

class TestExamProximityReachesGeneration:
    """The service being right is half of it; the other half is that its
    answer actually reaches the model AND the attempt row. Both are one
    keyword away from being silently dropped."""

    def _generate(self, days, agent_run):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock
        from fastapi.testclient import TestClient

        from agents.quiz import Quiz, QuizQuestion
        from main import app

        quiz = Quiz(questions=[QuizQuestion(
            question="Q?", type="multiple_choice", difficulty="easy",
            options=["a", "b", "c", "d"], correct_answer="a",
            explanation="x", concept="X",
        )])
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
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from agents.quiz import Quiz, QuizQuestion

        run = AsyncMock(return_value=SimpleNamespace(output=Quiz(questions=[
            QuizQuestion(question="Q?", type="multiple_choice", difficulty="easy",
                         options=["a", "b", "c", "d"], correct_answer="a",
                         explanation="x", concept="X")])))
        msg, attempt = self._generate(3, run)

        assert "next exam in this course is in 3 days" in msg
        assert attempt["exam_days_away"] == 3

    def test_an_exam_today_says_TODAY(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from agents.quiz import Quiz, QuizQuestion

        run = AsyncMock(return_value=SimpleNamespace(output=Quiz(questions=[
            QuizQuestion(question="Q?", type="multiple_choice", difficulty="easy",
                         options=["a", "b", "c", "d"], correct_answer="a",
                         explanation="x", concept="X")])))
        msg, attempt = self._generate(0, run)

        assert "next exam in this course is TODAY" in msg
        # 0 must survive to the row: `if exam_days_away:` would drop exam day,
        # the single most actionable value the feature produces.
        assert attempt["exam_days_away"] == 0

    def test_unknown_proximity_adds_nothing_and_omits_the_column(self):
        """'next exam: unknown' is prompt tokens spent to say nothing, and
        omitting the key (rather than sending null) keeps generation working
        on an environment that took this code before the migration."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from agents.quiz import Quiz, QuizQuestion

        run = AsyncMock(return_value=SimpleNamespace(output=Quiz(questions=[
            QuizQuestion(question="Q?", type="multiple_choice", difficulty="easy",
                         options=["a", "b", "c", "d"], correct_answer="a",
                         explanation="x", concept="X")])))
        msg, attempt = self._generate(None, run)

        assert "next exam" not in msg
        assert "exam_days_away" not in attempt
