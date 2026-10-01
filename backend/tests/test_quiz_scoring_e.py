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


# ── E1: mastery model — PKG-14b deleted the flat-delta seam (spec §11.2); the
#    options write-up #543 asked for stays as the record of what was weighed ──


class TestMasteryModelSeam:
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


# ── PKG-11: learning loop — evidence instead of the flat delta ──────────────
#
# Fixture questions carry the STORED wire shape (`question` + option `text`,
# routes/quiz.py::_agent_question_to_wire). Q1 carries a stored
# question_hash (post-E5 row); Q2 does not (pre-E5 row) so the recompute
# branch of wire_question_hash is exercised too.

LOOP_QUESTIONS = [
    {
        "id": 1,
        "question": "What does a for-loop do?",
        "options": [
            {"label": "A", "text": "iterates", "correct": True},
            {"label": "B", "text": "allocates", "correct": False},
        ],
        "explanation": "A.",
        "question_hash": "deadbeefdeadbeef",
    },
    {
        "id": 2,
        "question": "What is a function?",
        "options": [
            {"label": "C", "text": "a loop", "correct": False},
            {"label": "D", "text": "a reusable block", "correct": True},
        ],
        "explanation": "D.",
    },
]


# Every table() the legacy submit_quiz opens for this fixture, in order:
# attempt load, the atomic completed_at claim, the quiz_responses read, the concept
# node, the snapshot write, the quiz-context node read. Recorded against the
# pre-series route (base a1a416b) by the PKG-11 review; the flag-off path must
# not add a table to it.
LEGACY_SUBMIT_TABLES = [
    "quiz_attempts", "quiz_attempts", "quiz_responses",
    "graph_nodes", "quiz_attempts", "graph_nodes",
]


def _loop_table(questions=LOOP_QUESTIONS, tables: list | None = None):
    def factory(name):
        if tables is not None:
            tables.append(name)
        mock = MagicMock()
        if name == "quiz_attempts":
            mock.select.return_value = [{
                "id": "quiz1",
                "user_id": "user_andres",
                "concept_node_id": "node1",
                "difficulty": "medium",
                "questions_json": questions,
            }]
        elif name == "graph_nodes":
            mock.select.return_value = [{
                "mastery_score": 0.5,
                "concept_name": "Loops",
                "course_id": "course1",
            }]
        elif name == "quiz_evidence_claims":
            # spec §13 A100: every hash is fresh — the insert claims it
            mock.insert_ignore_duplicates.side_effect = lambda rows, on_conflict=None: list(rows)
            mock.update.return_value = []
            return mock
        else:
            mock.select.return_value = []
        mock.update.return_value = [{"id": "updated"}]
        return mock
    return factory


def _noop_ctx_agent():
    return AsyncMock(
        return_value=SimpleNamespace(output=SimpleNamespace(model_dump=lambda: {}))
    )


def _submit_one_right_one_wrong(*, apply_mock: MagicMock, tables: list | None = None):
    """PKG-14b: there is no gate and no legacy delta path to pick."""
    ctx_run = _noop_ctx_agent()
    with (
        patch("routes.quiz.table", side_effect=_loop_table(tables=tables)),
        patch("routes.quiz.apply_graph_update", new=apply_mock),
        patch("routes.quiz.get_quiz_context", return_value={}),
        patch("routes.quiz.quiz_context_agent.run", new=ctx_run),
        patch("routes.quiz.save_quiz_context"),
    ):
        r = client.post("/api/quiz/submit", json={
            "quiz_id": "quiz1",
            "answers": [
                {"question_id": 1, "selected_label": "A"},   # correct
                {"question_id": 2, "selected_label": "C"},   # wrong
            ],
        })
    return r, ctx_run


class TestLearningLoopEvidencePath:
    def test_submit_opens_exactly_the_legacy_tables(self):
        """PKG-14b: evidence is the only path; it opens no table beyond the
        ones the pre-series route opened (LEGACY_SUBMIT_TABLES) — the graph
        writes are apply_graph_update's."""
        tables: list = []
        r, _ = _submit_one_right_one_wrong(
            apply_mock=MagicMock(return_value=[{"before": 0.5, "after": 0.6}]), tables=tables,
        )
        assert r.status_code == 200, r.text
        # owner decision 2 (A94, A100): plus ONE claim of the attempt's hashes (the
        # farm guard), right after the concept node read
        expected = list(LEGACY_SUBMIT_TABLES)
        expected.insert(expected.index("graph_nodes") + 1, "quiz_evidence_claims")
        assert tables == expected

    def test_gate_on_submits_one_evidence_per_question(self):
        from services.quiz_identity import question_hash

        apply_mock = MagicMock(return_value=[
            {"before": 0.5, "after": 0.58},
            {"before": 0.58, "after": 0.51},
        ])
        r, _ = _submit_one_right_one_wrong(
            apply_mock=apply_mock,
        )
        assert r.status_code == 200, r.text
        apply_mock.assert_called_once()
        args, kwargs = apply_mock.call_args
        assert args[0] == "user_andres"
        assert kwargs["course_id"] == "course1"
        payload = args[1]
        assert set(payload) == {"evidence"}, "no updated_nodes on the loop path"
        ev = payload["evidence"]
        assert len(ev) == 2
        for e in ev:
            assert set(e) == {
                "node_id", "channel", "correct", "question_hash",
                "check_item_id", "session_id",
            }
            assert e["node_id"] == "node1"
            assert e["channel"] == "mc"
            assert e["check_item_id"] is None and e["session_id"] is None
        assert [e["correct"] for e in ev] == [True, False]
        assert ev[0]["question_hash"] == "deadbeefdeadbeef"          # stored hash trusted
        assert ev[1]["question_hash"] == question_hash(                # recomputed
            "What is a function?", ["a loop", "a reusable block"],
        )

    def test_gate_on_snapshot_spans_first_before_to_last_after(self):
        apply_mock = MagicMock(return_value=[
            {"before": 0.5, "after": 0.58},
            {"before": 0.58, "after": 0.51},
        ])
        r, _ = _submit_one_right_one_wrong(
            apply_mock=apply_mock,
        )
        data = r.json()
        assert data["mastery_before"] == pytest.approx(0.5)
        assert data["mastery_after"] == pytest.approx(0.51)

    def test_gate_on_unrecognisable_return_reports_no_change(self):
        apply_mock = MagicMock(return_value=[])
        r, _ = _submit_one_right_one_wrong(
            apply_mock=apply_mock,
        )
        data = r.json()
        assert data["mastery_before"] == pytest.approx(0.5)
        assert data["mastery_after"] == pytest.approx(0.5)

    def test_gate_on_keeps_the_quiz_context_background_update(self):
        apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.6}])
        r, ctx_run = _submit_one_right_one_wrong(
            apply_mock=apply_mock,
        )
        assert r.status_code == 200
        assert ctx_run.call_count == 1, "quiz_context update must still run on the loop path"

    def test_gate_on_hash_is_none_when_the_stored_item_has_no_identity(self):
        legacy_shape = [{
            "id": 1,
            "text": "no stem key, no option text",
            "options": [{"label": "A", "correct": True}, {"label": "B", "correct": False}],
            "explanation": "A.",
        }]
        apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.6}])
        ctx_run = _noop_ctx_agent()
        with (
            patch("routes.quiz.table", side_effect=_loop_table(legacy_shape)),
            patch("routes.quiz.apply_graph_update", new=apply_mock),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.quiz_context_agent.run", new=ctx_run),
            patch("routes.quiz.save_quiz_context"),
        ):
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "A"}],
            })
        assert r.status_code == 200
        ev = apply_mock.call_args[0][1]["evidence"]
        assert ev == [{
            "node_id": "node1", "channel": "mc", "correct": True,
            "question_hash": None, "check_item_id": None, "session_id": None,
        }]

    def test_gate_on_evidence_validates_as_pkg03_evidence(self):
        """The route sends plain dicts; apply_graph_update validates them with
        learning.evidence.Evidence before any write (HANDOFF-03). A quiz answer
        is unassisted, rung 0, full weight, and carries no grader confidence."""
        from learning.evidence import Evidence

        apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.6}])
        _submit_one_right_one_wrong(apply_mock=apply_mock)
        evs = [Evidence.model_validate(e) for e in apply_mock.call_args[0][1]["evidence"]]
        assert [(e.channel, e.correct) for e in evs] == [("mc", True), ("mc", False)]
        for e in evs:
            assert (e.assisted, e.max_rung, e.idk, e.same_session_recheck) == (False, 0, False, False)
            assert e.weight == 1.0 and e.confidence is None
