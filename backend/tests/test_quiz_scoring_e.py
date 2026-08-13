"""
Workstream E of the pre-revamp quiz repair batch (#543, epic #537):
scoring and generation correctness.

- E1: the mastery-delta constants live in a named config with a
  pedagogy docstring. THE NUMBERS DO NOT CHANGE in this PR — the seam
  lands, the revamp decides. The #393 journey's pinned +0.09 must stay
  exactly reproducible.
- E2: generation never silently short-changes a quiz — the response
  reports requested_count vs delivered_count, and a high drop rate
  triggers one bounded top-up retry. All-dropped stays a 502.
- E3: wire-format validation — at least 2 options, no duplicate option
  text, exactly one correct option, no duplicate question stems.
- E4: concurrency — double-submit, double-answer on one index,
  generate-while-generating for the same concept.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from agents.quiz import Quiz, QuizQuestion

client = TestClient(app)


def _q(question="Q?", options=("a", "b", "c", "d"), correct="a", difficulty="easy"):
    return QuizQuestion(
        question=question,
        type="multiple_choice",
        difficulty=difficulty,
        options=list(options),
        correct_answer=correct,
        explanation="x",
        concept="Loops",
    )


def _generate_factory():
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


def _generate(num_questions=3):
    return client.post("/api/quiz/generate", json={
        "user_id": "user_andres",
        "concept_node_id": "node1",
        "num_questions": num_questions,
        "difficulty": "easy",
        "use_shared_context": False,
    })


# ── E1: mastery model is a configurable seam (behaviour unchanged) ──────────


class TestMasteryModelSeam:
    def test_constants_are_named_and_unchanged(self):
        from services.quiz_config import (
            MASTERY_DELTA_PER_CORRECT,
            MASTERY_DELTA_PER_WRONG,
        )

        # Pinned: #543 lands the seam only. Changing these changes the
        # #393 journey's asserted +0.09 and must be a deliberate, separate
        # decision (see docs/quiz-mastery-model.md).
        assert MASTERY_DELTA_PER_CORRECT == 0.03
        assert MASTERY_DELTA_PER_WRONG == 0.02

    def test_mastery_delta_matches_the_pinned_journey_value(self):
        from services.quiz_config import mastery_after

        # frontend/e2e/quiz.spec.ts: 3 correct of 3 → +0.09 exactly.
        assert mastery_after(0.25, score=3, total=3) == pytest.approx(0.34)
        assert mastery_after(0.25, score=3, total=3) - 0.25 == pytest.approx(0.09)

    def test_clamped_to_unit_interval(self):
        from services.quiz_config import mastery_after

        assert mastery_after(0.99, score=5, total=5) == 1.0
        assert mastery_after(0.01, score=0, total=5) == 0.0

    def test_wrong_answers_subtract(self):
        from services.quiz_config import mastery_after

        # 2 correct (+0.06), 3 wrong (-0.06) → net zero.
        assert mastery_after(0.5, score=2, total=5) == pytest.approx(0.5)

    def test_options_writeup_exists(self):
        """E1 asks for the trade-offs to be written down for the revamp,
        not decided here."""
        from pathlib import Path

        doc = Path(__file__).resolve().parents[2] / "docs" / "quiz-mastery-model.md"
        assert doc.exists(), "the mastery-model options write-up is missing"
        text = doc.read_text()
        assert "0.03" in text and "0.02" in text
        assert "#393" in text, "the write-up must flag the pinned journey value"


# ── E2: honest counts + bounded top-up ──────────────────────────────────────


class TestDeliveredCount:
    def test_response_reports_requested_and_delivered(self):
        good = Quiz(questions=[_q(f"Q{i}?") for i in range(3)])
        with (
            patch("routes.quiz.table", side_effect=_generate_factory()),
            patch("routes.quiz.quiz_agent.run",
                  new=AsyncMock(return_value=SimpleNamespace(output=good))),
        ):
            r = _generate(num_questions=3)
        assert r.status_code == 200
        data = r.json()
        assert data["requested_count"] == 3
        assert data["delivered_count"] == 3

    def test_drops_are_reported_not_hidden(self):
        """Two of three questions drift (correct_answer not among options).
        The client must be able to say something honest instead of silently
        receiving a shorter quiz."""
        drifted = Quiz(questions=[
            _q("Q1?"),
            _q("Q2?", correct="NOT-AN-OPTION"),
            _q("Q3?", correct="NOT-AN-OPTION"),
        ])
        topped_up = Quiz(questions=[_q("Q4?"), _q("Q5?")])
        run = AsyncMock(side_effect=[
            SimpleNamespace(output=drifted),
            SimpleNamespace(output=topped_up),
        ])
        with (
            patch("routes.quiz.table", side_effect=_generate_factory()),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            r = _generate(num_questions=3)
        assert r.status_code == 200
        data = r.json()
        assert data["requested_count"] == 3
        # One survivor + two from the single top-up run.
        assert data["delivered_count"] == 3
        assert len(data["questions"]) == 3
        # Ids stay 1-based and contiguous across the top-up boundary.
        assert [q["id"] for q in data["questions"]] == [1, 2, 3]
        assert run.call_count == 2, "exactly one bounded top-up retry"

    def test_top_up_is_bounded_to_one_retry(self):
        """If the top-up also drifts, we serve what we have — never loop."""
        drifted = Quiz(questions=[
            _q("Q1?"),
            _q("Q2?", correct="NOPE"),
            _q("Q3?", correct="NOPE"),
        ])
        also_drifted = Quiz(questions=[_q("Q4?", correct="NOPE")])
        run = AsyncMock(side_effect=[
            SimpleNamespace(output=drifted),
            SimpleNamespace(output=also_drifted),
        ])
        with (
            patch("routes.quiz.table", side_effect=_generate_factory()),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            r = _generate(num_questions=3)
        assert r.status_code == 200
        data = r.json()
        assert data["delivered_count"] == 1
        assert data["requested_count"] == 3
        assert run.call_count == 2

    def test_no_top_up_when_the_drop_rate_is_low(self):
        """One drop out of five isn't worth a second LLM call."""
        mostly_good = Quiz(questions=[
            _q("Q1?"), _q("Q2?"), _q("Q3?"), _q("Q4?"),
            _q("Q5?", correct="NOPE"),
        ])
        run = AsyncMock(return_value=SimpleNamespace(output=mostly_good))
        with (
            patch("routes.quiz.table", side_effect=_generate_factory()),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            r = _generate(num_questions=5)
        assert r.status_code == 200
        assert r.json()["delivered_count"] == 4
        assert run.call_count == 1

    def test_no_top_up_when_the_agent_simply_returns_fewer(self):
        """A short-but-clean generation is NOT a drift failure. The agent's
        schema lets it return any count (the E2E seam always returns 3
        while the UI asks for 5), so keying the retry on requested-minus-
        delivered fires a second full generation on ordinary requests —
        doubling latency and tokens for nothing."""
        short_but_clean = Quiz(questions=[_q("Q1?"), _q("Q2?"), _q("Q3?")])
        run = AsyncMock(return_value=SimpleNamespace(output=short_but_clean))
        with (
            patch("routes.quiz.table", side_effect=_generate_factory()),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            r = _generate(num_questions=5)
        assert r.status_code == 200
        assert r.json()["delivered_count"] == 3
        assert run.call_count == 1, (
            "nothing was dropped — a top-up here is pure waste"
        )

    def test_top_up_prompt_lists_the_stems_already_asked(self):
        """'different from the ones already asked' is unactionable unless
        the model is told what they were — otherwise a deterministic model
        regenerates the same stems and the dedupe discards the whole run."""
        drifted = Quiz(questions=[
            _q("What is a loop?"),
            _q("Q2?", correct="NOPE"),
            _q("Q3?", correct="NOPE"),
        ])
        topped = Quiz(questions=[_q("What is recursion?", options=("w", "x", "y", "z"), correct="w")])
        run = AsyncMock(side_effect=[
            SimpleNamespace(output=drifted),
            SimpleNamespace(output=topped),
        ])
        with (
            patch("routes.quiz.table", side_effect=_generate_factory()),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            r = _generate(num_questions=3)
        assert r.status_code == 200
        assert run.call_count == 2
        topup_msg = run.call_args_list[1][0][0]
        assert "What is a loop?" in topup_msg, (
            "the top-up must name the stems it has to avoid"
        )

    def test_top_up_gets_its_own_bounded_budget(self):
        """Reusing the first run's usage_limits hands the retry a fresh
        ORCHESTRATOR_LIMITS, doubling the per-request cost ceiling."""
        from agents import ORCHESTRATOR_LIMITS

        drifted = Quiz(questions=[
            _q("Q1?"), _q("Q2?", correct="NOPE"), _q("Q3?", correct="NOPE"),
        ])
        topped = Quiz(questions=[_q("Q4?"), _q("Q5?")])
        run = AsyncMock(side_effect=[
            SimpleNamespace(output=drifted),
            SimpleNamespace(output=topped),
        ])
        with (
            patch("routes.quiz.table", side_effect=_generate_factory()),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            _generate(num_questions=3)
        first_limits = run.call_args_list[0].kwargs["usage_limits"]
        topup_limits = run.call_args_list[1].kwargs["usage_limits"]
        assert first_limits is ORCHESTRATOR_LIMITS
        assert topup_limits is not ORCHESTRATOR_LIMITS
        assert (
            topup_limits.total_tokens_limit
            < ORCHESTRATOR_LIMITS.total_tokens_limit
        ), "the retry must not double the request's cost backstop"

    def test_total_drift_gets_the_retry_too(self):
        """Total drift is the case a retry most obviously helps — a
        `wire_questions and ...` guard made it the ONE case that never
        retried, sending the student straight to a 502."""
        nothing_valid = Quiz(questions=[
            _q("Q1?", correct="NOPE"), _q("Q2?", correct="NOPE"),
        ])
        recovered = Quiz(questions=[_q("Q3?"), _q("Q4?")])
        run = AsyncMock(side_effect=[
            SimpleNamespace(output=nothing_valid),
            SimpleNamespace(output=recovered),
        ])
        with (
            patch("routes.quiz.table", side_effect=_generate_factory()),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            r = _generate(num_questions=2)
        assert r.status_code == 200
        assert r.json()["delivered_count"] == 2
        assert run.call_count == 2

    def test_all_dropped_after_the_retry_still_502s(self):
        nothing_valid = Quiz(questions=[
            _q("Q1?", correct="NOPE"), _q("Q2?", correct="NOPE"),
        ])
        run = AsyncMock(return_value=SimpleNamespace(output=nothing_valid))
        with (
            patch("routes.quiz.table", side_effect=_generate_factory()),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            r = _generate(num_questions=2)
        assert r.status_code == 502
        assert r.json()["error"]["code"] == "QUIZ_GENERATION_FAILED"
        assert run.call_count == 2, "one bounded retry, then give up"

    def test_failed_top_up_logs_without_a_traceback(self, caplog):
        """The recovery path deliberately SUCCEEDS, so it must not emit a
        traceback — the E2E logscan oracle reports those as findings (same
        rule the quiz_context handler follows)."""
        drifted = Quiz(questions=[
            _q("Q1?"), _q("Q2?", correct="NOPE"), _q("Q3?", correct="NOPE"),
        ])
        run = AsyncMock(side_effect=[
            SimpleNamespace(output=drifted),
            RuntimeError("top-up blew up"),
        ])
        with (
            patch("routes.quiz.table", side_effect=_generate_factory()),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            with caplog.at_level("WARNING", logger="routes.quiz"):
                r = _generate(num_questions=3)
        assert r.status_code == 200
        assert r.json()["delivered_count"] == 1
        topup_logs = [rec for rec in caplog.records if "top-up" in rec.message]
        assert topup_logs
        assert all(not rec.exc_info for rec in topup_logs)


# ── E3: wire-format validation ──────────────────────────────────────────────


class TestWireValidation:
    def test_duplicate_option_text_is_dropped(self):
        """Two identical options make the item unanswerable — the student
        can pick the 'same' answer and be wrong."""
        from routes.quiz import _agent_question_to_wire

        q = _q(options=("a", "a", "b", "c"), correct="b")
        assert _agent_question_to_wire(q, 1) is None

    def test_case_distinct_options_are_kept(self):
        """Grading matches correct_answer case-SENSITIVELY, so options that
        differ only by case are distinct and gradable — a concept quiz on
        `list` vs `List` is a real question, not a malformed one. The
        duplicate check must use the same comparison grading does."""
        from routes.quiz import _agent_question_to_wire

        q = _q(options=("list", "List", "tuple", "Tuple"), correct="List")
        wire = _agent_question_to_wire(q, 1)
        assert wire is not None
        correct = [o for o in wire["options"] if o["correct"]]
        assert len(correct) == 1
        assert correct[0]["text"] == "List"

    def test_too_few_options_is_dropped(self):
        from routes.quiz import _validate_wire_question

        wire = {
            "id": 1,
            "question": "Q?",
            "options": [{"label": "A", "text": "a", "correct": True}],
            "explanation": "x",
        }
        assert _validate_wire_question(wire) is False

    def test_exactly_one_correct_option_required(self):
        from routes.quiz import _validate_wire_question

        two_correct = {
            "id": 1,
            "question": "Q?",
            "options": [
                {"label": "A", "text": "a", "correct": True},
                {"label": "B", "text": "b", "correct": True},
            ],
            "explanation": "x",
        }
        none_correct = {
            "id": 2,
            "question": "Q?",
            "options": [
                {"label": "A", "text": "a", "correct": False},
                {"label": "B", "text": "b", "correct": False},
            ],
            "explanation": "x",
        }
        assert _validate_wire_question(two_correct) is False
        assert _validate_wire_question(none_correct) is False

    def test_duplicate_stems_within_one_attempt_are_dropped(self):
        """The same question twice is padding, not a quiz."""
        dupes = Quiz(questions=[
            _q("What is a loop?"),
            _q("What is a loop?", options=("w", "x", "y", "z"), correct="w"),
            _q("What is recursion?", options=("1", "2", "3", "4"), correct="1"),
        ])
        run = AsyncMock(return_value=SimpleNamespace(output=dupes))
        with (
            patch("routes.quiz.table", side_effect=_generate_factory()),
            patch("routes.quiz.quiz_agent.run", new=run),
        ):
            r = _generate(num_questions=3)
        assert r.status_code == 200
        stems = [q["question"] for q in r.json()["questions"]]
        assert len(stems) == len(set(stems)), "duplicate stems reached the client"
        assert len(stems) == 2


# ── E4: concurrency ─────────────────────────────────────────────────────────


class TestConcurrency:
    def test_double_answer_on_one_index_records_once(self):
        """The real race: BOTH requests see an empty table (the pre-read
        happens before either insert), so the second insert is the one the
        UNIQUE rejects. The route must re-read and return the winner
        rather than 500ing.

        The fake models that interleaving directly — its select returns
        empty until an insert has actually landed AND the caller has been
        through its pre-read once, which is what makes the second insert
        collide instead of being short-circuited by the existing-row
        branch."""
        rows: list[dict] = []
        state = {"selects": 0, "insert_attempts": 0}

        class _Responses:
            def select(self, columns="*", filters=None, order=None, **_):
                state["selects"] += 1
                # First TWO reads see nothing: both requests raced past
                # the idempotency pre-read before either wrote.
                if state["selects"] <= 2:
                    return []
                return [dict(r) for r in rows]

            def insert(self, payload):
                state["insert_attempts"] += 1
                for r in rows:
                    if r["question_index"] == payload["question_index"]:
                        raise RuntimeError(
                            'duplicate key value violates unique constraint '
                            '"quiz_responses_attempt_question_key" (23505)'
                        )
                rows.append(dict(payload))
                return [dict(payload)]

        responses = _Responses()

        def factory(name):
            if name == "quiz_responses":
                return responses
            mock = MagicMock()
            if name == "quiz_attempts":
                mock.select.return_value = [{
                    "id": "quiz1",
                    "user_id": "user_andres",
                    "concept_node_id": "node1",
                    "difficulty": "medium",
                    "completed_at": None,
                    "questions_json": [{
                        "id": 1,
                        "question": "Q1?",
                        "options": [
                            {"label": "A", "text": "a", "correct": False},
                            {"label": "B", "text": "b", "correct": True},
                        ],
                        "explanation": "B.",
                    }],
                }]
            else:
                mock.select.return_value = []
            return mock

        payload = {"question_index": 0, "selected_index": 1}
        with patch("routes.quiz.table", side_effect=factory):
            first = client.post("/api/quiz/attempts/quiz1/answer", json=payload)
            second = client.post("/api/quiz/attempts/quiz1/answer", json=payload)

        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["recorded"] is True
        assert second.json()["recorded"] is False
        assert len(rows) == 1
        # The point of the test: the loser really did attempt an insert and
        # got the UNIQUE violation, rather than being filtered by the
        # pre-read (which would leave the race handler unexercised).
        assert state["insert_attempts"] == 2
        # Both answers graded identically off the winning row.
        assert second.json()["is_correct"] == first.json()["is_correct"]

    def test_concurrent_generate_for_one_concept_creates_distinct_attempts(self):
        """Two generates for the same concept must not collide on an id or
        overwrite each other's attempt row."""
        inserted: list[dict] = []

        def factory(name):
            mock = MagicMock()
            if name == "graph_nodes":
                mock.select.return_value = [{
                    "id": "node1", "course_id": "course1",
                    "concept_name": "Loops", "mastery_score": 0.5,
                }]
            elif name == "quiz_attempts":
                def _insert(payload):
                    inserted.append(payload)
                    return [{"id": payload["id"]}]
                mock.insert.side_effect = _insert
            else:
                mock.select.return_value = []
            return mock

        good = Quiz(questions=[_q()])
        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.quiz_agent.run",
                  new=AsyncMock(return_value=SimpleNamespace(output=good))),
        ):
            r1 = _generate(num_questions=1)
            r2 = _generate(num_questions=1)

        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["quiz_id"] != r2.json()["quiz_id"]
        assert len({row["id"] for row in inserted}) == 2
