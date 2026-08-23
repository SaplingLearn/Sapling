"""
Workstream C of the pre-revamp quiz repair batch (#541, epic #537):
server-authoritative grading.

- C1: POST /api/quiz/attempts/{attempt_id}/answer grades one question
  server-side; owner-checked; 409 after completion; idempotent on
  (attempt_id, question_index) — re-answering returns the FIRST recorded
  response (no revision; the revamp decides if that changes).
- C2: responses persist individually in quiz_responses (plaintext
  analytics scalars; nothing free-text).
- C3: include_answer_key on generate (default flipped false #546 — the
  #537 client already grades via /attempts/{id}/answer and has sent
  `include_answer_key: false` on every generate since it shipped;
  explicit true is still accepted-but-logged for one release) — when
  false, the response strips per-option `correct` booleans while the
  stored questions_json keeps them for grading.
- C4: submit prefers recorded quiz_responses and falls back to the
  payload per question; the atomic completed_at claim (PR #464) stays.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from main import app
from agents.quiz import Quiz, QuizQuestion

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
    {
        "id": 2,
        "question": "Q2?",
        "options": [
            {"label": "A", "text": "a2", "correct": True},
            {"label": "B", "text": "b2", "correct": False},
        ],
        "explanation": "A is right.",
        "concept_tested": "Loops",
        "difficulty": "medium",
    },
]


class _ResponsesTable:
    """In-memory quiz_responses double enforcing the UNIQUE."""

    def __init__(self):
        self.rows: list[dict] = []

    def select(self, columns="*", filters=None, order=None, **_):
        filters = filters or {}
        out = self.rows
        for key, expr in filters.items():
            val = expr.split(".", 1)[1] if isinstance(expr, str) else expr
            out = [r for r in out if str(r.get(key)) == str(val)]
        if order and "question_index" in order:
            out = sorted(out, key=lambda r: r["question_index"])
        return list(out)

    def insert(self, payload):
        for r in self.rows:
            if (
                r["attempt_id"] == payload["attempt_id"]
                and r["question_index"] == payload["question_index"]
            ):
                raise RuntimeError('duplicate key value violates unique constraint "quiz_responses_attempt_question_key" (23505)')
        self.rows.append(dict(payload))
        return [dict(payload)]


def _tables(*, completed_at=None, responses: "_ResponsesTable | None" = None):
    responses = responses or _ResponsesTable()

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
                "questions_json": QUESTIONS,
                "completed_at": completed_at,
            }]
            mock.update.return_value = [{"id": "quiz1"}]
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

    return factory, responses


def _answer(body_extra=None, attempt_id="quiz1"):
    return client.post(f"/api/quiz/attempts/{attempt_id}/answer", json={
        "question_index": 0,
        "selected_index": 1,
        **(body_extra or {}),
    })


# ── C1: per-question answer endpoint ────────────────────────────────────────


class TestAnswerEndpoint:
    def test_grades_and_persists_a_response(self):
        factory, responses = _tables()
        with patch("routes.quiz.table", side_effect=factory):
            r = _answer({"time_ms": 4200, "confidence": 0.8})
        assert r.status_code == 200
        data = r.json()
        assert data["is_correct"] is True          # option index 1 is "B", correct
        assert data["correct_index"] == 1
        assert data["explanation"] == "B is right."
        # next_question is question 2, without the answer key.
        nq = data["next_question"]
        assert nq["id"] == 2
        assert all("correct" not in o for o in nq["options"])
        # Persisted plaintext scalars (C2).
        assert len(responses.rows) == 1
        row = responses.rows[0]
        assert row["attempt_id"] == "quiz1"
        assert row["question_index"] == 0
        assert row["selected_index"] == 1
        assert row["is_correct"] is True
        assert row["time_ms"] == 4200
        assert row["confidence"] == 0.8

    def test_last_question_has_no_next(self):
        factory, _ = _tables()
        with patch("routes.quiz.table", side_effect=factory):
            r = _answer({"question_index": 1, "selected_index": 1})
        assert r.status_code == 200
        data = r.json()
        assert data["is_correct"] is False
        assert data["correct_index"] == 0
        assert data["next_question"] is None

    def test_reanswer_returns_first_recorded_response(self):
        factory, responses = _tables()
        with patch("routes.quiz.table", side_effect=factory):
            first = _answer({"selected_index": 1})
            second = _answer({"selected_index": 0})   # tries to revise → no
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["is_correct"] is True    # the FIRST answer's grade
        assert second.json()["recorded"] is False     # nothing new was written
        assert len(responses.rows) == 1
        assert responses.rows[0]["selected_index"] == 1

    def test_completed_attempt_409s(self):
        factory, _ = _tables(completed_at="2026-08-12T00:00:00Z")
        with patch("routes.quiz.table", side_effect=factory):
            r = _answer()
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_ALREADY_COMPLETED"

    def test_unknown_attempt_404s(self):
        def factory(name):
            mock = MagicMock()
            mock.select.return_value = []
            return mock

        with patch("routes.quiz.table", side_effect=factory):
            r = _answer(attempt_id="nope")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_NOT_FOUND"

    def test_bad_indexes_400(self):
        factory, _ = _tables()
        with patch("routes.quiz.table", side_effect=factory):
            r_q = _answer({"question_index": 9})
            r_o = _answer({"selected_index": 9})
        for r in (r_q, r_o):
            assert r.status_code == 400
            assert r.json()["error"]["code"] == "QUIZ_QUESTION_INVALID"

    def test_response_echoes_the_wire_question_id(self):
        """Wire question ids are 1-based; question_index is 0-based. Echoing
        the id the client displayed makes an off-by-one visible instead of
        silently grading the wrong question (which idempotency then locks in)."""
        factory, _ = _tables()
        with patch("routes.quiz.table", side_effect=factory):
            r = _answer({"question_index": 0, "selected_index": 1})
        assert r.status_code == 200
        data = r.json()
        assert data["question_index"] == 0
        assert data["question_id"] == 1   # QUESTIONS[0]["id"]

    def test_question_id_mismatch_is_rejected(self):
        """A client may send the wire id it displayed alongside the index;
        when both are present they must agree, so passing the 1-based id as
        the 0-based index fails loudly instead of grading question 2."""
        factory, responses = _tables()
        with patch("routes.quiz.table", side_effect=factory):
            r = _answer({"question_index": 1, "selected_index": 0, "question_id": 1})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "QUIZ_QUESTION_INVALID"
        assert responses.rows == []


# ── C3: include_answer_key ──────────────────────────────────────────────────


def _generate_factory():
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

    return factory, captured


def _fake_quiz():
    return Quiz(questions=[
        QuizQuestion(
            question="Q?", type="multiple_choice", difficulty="easy",
            options=["w", "x", "y", "z"], correct_answer="x",
            explanation="ok", concept="Loops",
        ),
    ])


class TestIncludeAnswerKey:
    def _post(self, extra):
        return client.post("/api/quiz/generate", json={
            "user_id": "user_andres",
            "concept_node_id": "node1",
            "num_questions": 1,
            "difficulty": "easy",
            "use_shared_context": False,
            **extra,
        })

    def test_default_now_strips_the_key(self, caplog):
        """#546: the default flipped false tonight. Omitting the field
        entirely — what the #537 client actually does before it started
        sending the flag explicitly, and what any future caller that
        doesn't know about the flag gets — must no longer leak the answer
        key, and must not log the deprecation breadcrumb (that only fires
        for a caller that explicitly opts back in)."""
        factory, _ = _generate_factory()
        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.quiz_agent.run",
                  new=AsyncMock(return_value=SimpleNamespace(output=_fake_quiz()))),
        ):
            with caplog.at_level("INFO", logger="routes.quiz"):
                r = self._post({})
        assert r.status_code == 200
        q = r.json()["questions"][0]
        assert all("correct" not in o for o in q["options"])
        # Filtered by logger name (M6): caplog's handler captures every
        # propagating logger, not just ours, so an unfiltered scan could
        # pass by coincidence off an unrelated log line rather than
        # actually proving routes.quiz stayed silent.
        ours = [rec for rec in caplog.records if rec.name == "routes.quiz"]
        assert not any("answer key" in rec.message for rec in ours), (
            "the keyless default path must not log the deprecated-key breadcrumb"
        )

    def test_default_response_is_the_keyless_projection_of_the_real_stored_key(self):
        """Grounded against the SAME encrypted questions_json a real
        Postgres row would hold (round-tripped through the real
        encrypt_json/decrypt_json_column, not a hand-built fixture):
        confirms a real answer key actually exists in storage, then pins
        the served shape against a HARD-CODED expectation written HERE —
        not imported from routes.quiz's own `_strip_answer_key`/
        `_KEYLESS_*_KEYS`. Diffing the response against the very function
        that produced it is circular: it can't catch a leak (or an
        accidental widening of that allowlist) introduced inside the
        projection itself, since both sides would move together. The
        recursive key-name walk at the end is a heuristic backstop only —
        it catches a leak that names itself obviously, nothing more; the
        hard-coded key-set assertions above it are the actual anchor."""
        from services.encryption import decrypt_json_column

        factory, captured = _generate_factory()
        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.quiz_agent.run",
                  new=AsyncMock(return_value=SimpleNamespace(output=_fake_quiz()))),
        ):
            r = self._post({})
        assert r.status_code == 200
        body = r.json()
        served = body["questions"]

        stored = decrypt_json_column(captured["payload"]["questions_json"])
        assert any(o.get("correct") for o in stored[0]["options"]), (
            "the fixture must actually mark an option correct, or the "
            "grounding above is vacuous"
        )

        # Non-circular anchor: this allowlist is a literal written in the
        # test, not imported from routes.quiz — so a leak, or an
        # accidental widening of the route's own allowlist, fails THIS
        # assertion instead of passing by construction because both sides
        # moved together.
        allowed_question_keys = {"id", "question", "concept_tested", "difficulty", "options"}
        for q in served:
            leaked = set(q.keys()) - allowed_question_keys
            assert not leaked, f"generate response question carries unexpected key(s): {leaked}"
            for opt in q["options"]:
                assert set(opt.keys()) == {"label", "text"}, (
                    f"generate response option carries unexpected key(s): "
                    f"{set(opt.keys()) - {'label', 'text'}}"
                )

        # Heuristic backstop: walk the WHOLE response, not just `questions`
        # — a sibling top-level field (e.g. an `answer_key`) would sail
        # past a walk scoped only to the questions list.
        def _walk(node, path=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    lowered = k.lower()
                    assert not any(
                        tok in lowered
                        for tok in ("correct", "answer", "explanation", "solution")
                    ), f"generate response leaks the answer key via key {path}.{k!r}"
                    _walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, item in enumerate(node):
                    _walk(item, f"{path}[{i}]")

        _walk(body)

    def test_explicit_true_keeps_the_key_and_logs(self, caplog):
        """The flag stays accepted-but-logged for one release: an explicit
        `include_answer_key: true` still gets the full answer key, and
        every such response leaves a deprecation breadcrumb so usage of
        the opt-in path is observable before it's deleted outright."""
        factory, _ = _generate_factory()
        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.quiz_agent.run",
                  new=AsyncMock(return_value=SimpleNamespace(output=_fake_quiz()))),
        ):
            with caplog.at_level("INFO", logger="routes.quiz"):
                r = self._post({"include_answer_key": True})
        assert r.status_code == 200
        q = r.json()["questions"][0]
        assert any(o.get("correct") for o in q["options"])
        ours = [rec for rec in caplog.records if rec.name == "routes.quiz"]
        assert any("answer key" in rec.message for rec in ours), (
            "every keyed response must leave a deprecation breadcrumb (#546)"
        )

    def test_false_strips_the_key_from_response_but_not_storage(self):
        from services.encryption import decrypt_json_column

        factory, captured = _generate_factory()
        with (
            patch("routes.quiz.table", side_effect=factory),
            patch("routes.quiz.quiz_agent.run",
                  new=AsyncMock(return_value=SimpleNamespace(output=_fake_quiz()))),
        ):
            r = self._post({"include_answer_key": False})
        assert r.status_code == 200
        q = r.json()["questions"][0]
        assert all("correct" not in o for o in q["options"])
        # Storage keeps the key — grading stays server-side.
        stored = decrypt_json_column(captured["payload"]["questions_json"])
        assert any(o.get("correct") for o in stored[0]["options"])


# ── C4: submit reconciles recorded responses with the payload ───────────────


class TestSubmitReconciliation:
    def _submit_mocks(self, responses):
        factory, _ = _tables(responses=responses)
        return (
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
        )

    def test_persisted_answers_match_what_was_graded(self):
        """answers_json is the attempt's record of what the student answered
        — it must be the RECONCILED set, not the raw payload. A recorded-only
        submit (answers: []) previously stored an empty answer set beside a
        full score; a contradicting payload answer was stored despite losing
        to the recorded response."""
        from services.encryption import decrypt_json_column

        responses = _ResponsesTable()
        responses.insert({
            "attempt_id": "quiz1", "question_index": 0,
            "selected_index": 1, "is_correct": True,
        })
        update_calls: list = []
        factory, _ = _tables(responses=responses)

        def capturing(name):
            t = factory(name)
            if name == "quiz_attempts":
                def _update(data, filters=None):
                    update_calls.append(data)
                    return [{"id": "quiz1"}]
                t.update.side_effect = _update
            return t

        with (
            patch("routes.quiz.table", side_effect=capturing),
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
                # Question 1 answered via C1 (B, correct) — the payload's
                # contradicting "A" must not reach storage. Question 2 has
                # no recorded response, so its payload answer is authoritative.
                "answers": [
                    {"question_id": 1, "selected_label": "A"},
                    {"question_id": 2, "selected_label": "A"},
                ],
            })

        assert r.status_code == 200
        stored = [d for d in update_calls if "answers_json" in d]
        assert len(stored) == 1
        answers = decrypt_json_column(stored[0]["answers_json"])
        by_qid = {str(a["question_id"]): a["selected_label"] for a in answers}
        assert by_qid["1"] == "B", "stored answer must be the graded (recorded) one"
        assert by_qid["2"] == "A"

    def test_recorded_only_submit_persists_the_recorded_answers(self):
        from services.encryption import decrypt_json_column

        responses = _ResponsesTable()
        responses.insert({
            "attempt_id": "quiz1", "question_index": 0,
            "selected_index": 1, "is_correct": True,
        })
        responses.insert({
            "attempt_id": "quiz1", "question_index": 1,
            "selected_index": 0, "is_correct": True,
        })
        update_calls: list = []
        factory, _ = _tables(responses=responses)

        def capturing(name):
            t = factory(name)
            if name == "quiz_attempts":
                def _update(data, filters=None):
                    update_calls.append(data)
                    return [{"id": "quiz1"}]
                t.update.side_effect = _update
            return t

        with (
            patch("routes.quiz.table", side_effect=capturing),
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
                "quiz_id": "quiz1", "answers": [],
            })

        assert r.status_code == 200
        assert r.json()["score"] == 2
        stored = [d for d in update_calls if "answers_json" in d][0]
        answers = decrypt_json_column(stored["answers_json"])
        assert len(answers) == 2, (
            "a perfect score with an empty stored answer set is a contradictory "
            "attempt record"
        )
        assert {a["selected_label"] for a in answers} == {"B", "A"}

    def test_mixed_case_prefers_recorded_and_falls_back_to_payload(self):
        responses = _ResponsesTable()
        # Question 1 (index 0) was answered through C1: correct (B).
        responses.insert({
            "attempt_id": "quiz1", "question_index": 0,
            "selected_index": 1, "is_correct": True,
        })
        mocks = self._submit_mocks(responses)
        with mocks[0], mocks[1], mocks[2], mocks[3], mocks[4]:
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [
                    # Payload CONTRADICTS the recorded response for q1 —
                    # the recorded one wins.
                    {"question_id": 1, "selected_label": "A"},
                    # q2 exists only in the payload: falls back (A = correct).
                    {"question_id": 2, "selected_label": "A"},
                ],
            })
        assert r.status_code == 200
        data = r.json()
        assert data["score"] == 2
        flags = {res["question_id"]: res["correct"] for res in data["results"]}
        assert flags["1"] is True   # recorded response, not the payload's A
        assert flags["2"] is True   # payload fallback

    def test_recorded_only_submit_needs_no_payload_answers(self):
        responses = _ResponsesTable()
        responses.insert({
            "attempt_id": "quiz1", "question_index": 0,
            "selected_index": 1, "is_correct": True,
        })
        responses.insert({
            "attempt_id": "quiz1", "question_index": 1,
            "selected_index": 1, "is_correct": False,
        })
        mocks = self._submit_mocks(responses)
        with mocks[0], mocks[1], mocks[2], mocks[3], mocks[4]:
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1", "answers": [],
            })
        assert r.status_code == 200
        assert r.json()["score"] == 1
