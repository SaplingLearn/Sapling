"""G5 (#537): "practise the ones you missed" re-serves the missed questions.

Before this, the only thing the route could do with "I got these three
wrong" was generate three NEW questions and label the result honestly
("Focused on what you missed" — contract R-5). The student never saw the
question they actually missed again, which is the one thing spaced
practice is for.

E5 gave every stored question a stable identity (`question_hash`), so the
missed items can now be found in the source attempt and handed back
verbatim — no model call, no paraphrase, same item. These tests pin the
three outcomes that must stay distinguishable to the client: re-served
everything, re-served some, re-served nothing.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agents.quiz import Quiz, QuizQuestion
from main import app
from routes.quiz import CourseMaterial
from services.encryption import decrypt_json_column, encrypt_json
from services.quiz_identity import question_hash
from services.quiz_reserve import missed_question_hashes, recover_questions

client = TestClient(app)

NODE = {"id": "node1", "user_id": "user_andres", "course_id": "course1",
        "concept_name": "Recursion", "mastery_score": 0.5}

SOURCE_ID = "attempt-source"


def _stored(stem, qid=1, opts=("alpha", "beta", "gamma", "delta")):
    """One question in the shape `quiz_attempts.questions_json` holds."""
    return {
        "id": qid,
        "question": stem,
        "options": [
            {"label": label, "text": text, "correct": i == 0}
            for i, (label, text) in enumerate(zip("ABCDEF", opts))
        ],
        "explanation": f"because {stem}",
        "concept_tested": "Recursion",
        "difficulty": "easy",
        "question_hash": question_hash(stem, opts),
        "provenance": {
            "prompt_version": "quiz/v1",
            "chunk_ids": ["chunk-a"],
            "rag_grounded": True,
            "catalog": False,
            "model": "gemini-2.5-flash-lite",
        },
    }


def _agent_question(stem):
    opts = ["fresh-a", "fresh-b", "fresh-c", "fresh-d"]
    return QuizQuestion(
        question=stem, type="multiple_choice", difficulty="easy",
        options=opts, correct_answer=opts[0],
        explanation="freshly written", concept="Recursion",
    )


def _attempt(questions, *, completed=True, user_id="user_andres"):
    row = {
        "id": SOURCE_ID,
        "user_id": user_id,
        "concept_node_id": "node1",
        "difficulty": "easy",
        "questions_json": encrypt_json(questions),
        "created_at": "2026-08-22T10:00:00+00:00",
    }
    row["completed_at"] = "2026-08-22T10:10:00+00:00" if completed else None
    return row


def _factory(captured, *, attempts=(), responses=()):
    def factory(name):
        mock = MagicMock()
        mock.insert.return_value = []
        if name == "graph_nodes":
            mock.select.return_value = [NODE]
        elif name == "quiz_attempts":
            mock.select.return_value = list(attempts)

            def _capture(payload):
                captured["row"] = payload
                return [{"id": payload["id"]}]

            mock.insert.side_effect = _capture
        elif name == "quiz_responses":
            mock.select.return_value = list(responses)
        else:
            mock.select.return_value = []
        return mock
    return factory


def _generate(
    *,
    generated=(),
    attempts=(),
    responses=(),
    body_extra=None,
    num_questions=2,
    agent_side_effect=None,
):
    """Drive POST /generate, returning (response, stored_row, agent_mock)."""
    captured: dict = {}
    # `Quiz` requires at least one question, so a run that must never happen
    # gets a loudly-named sentinel rather than an empty output: an unexpected
    # agent call then shows up in the assertions instead of raising here.
    result = SimpleNamespace(
        output=Quiz(questions=list(generated) or [_agent_question("UNEXPECTED")]),
        response=SimpleNamespace(model_name="gemini-2.5-flash-lite"),
    )
    agent_run = AsyncMock(
        return_value=result,
        **({"side_effect": agent_side_effect} if agent_side_effect else {}),
    )
    factory = _factory(captured, attempts=attempts, responses=responses)
    with (
        patch("routes.quiz.table", side_effect=factory),
        patch("services.quiz_reserve.table", side_effect=factory),
        patch("routes.quiz.quiz_agent.run", new=agent_run),
        patch("routes.quiz._course_material", return_value=CourseMaterial()),
        patch("routes.quiz.recent_question_identities", return_value=[]),
        patch("routes.quiz.days_until_next_exam", return_value=None),
    ):
        r = client.post("/api/quiz/generate", json={
            "user_id": "user_andres",
            "concept_node_id": "node1",
            "num_questions": num_questions,
            "difficulty": "easy",
            "use_shared_context": False,
            **(body_extra or {}),
        })
    return r, captured.get("row"), agent_run


def _stored_questions(row):
    return decrypt_json_column(row["questions_json"])


# ── services/quiz_reserve.py ────────────────────────────────────────────────


def test_missed_hashes_come_back_in_the_order_they_were_asked():
    """The rows arrive in whatever order PostgREST hands them over; the
    practice quiz should follow the quiz the student actually sat."""
    questions = [_stored("Q1", 1), _stored("Q2", 2), _stored("Q3", 3)]
    rows = [{"question_index": 2}, {"question_index": 0}]

    def factory(name):
        m = MagicMock()
        m.select.return_value = rows
        return m

    with patch("services.quiz_reserve.table", side_effect=factory):
        hashes = missed_question_hashes(SOURCE_ID, questions)
    assert hashes == [questions[0]["question_hash"], questions[2]["question_hash"]]


def test_missed_hashes_ignore_indexes_that_are_not_in_the_attempt():
    """A response row pointing past the stored questions (a truncated
    re-write, a hand-edited row) must not index-error the whole practice."""
    questions = [_stored("Q1", 1)]

    def factory(name):
        m = MagicMock()
        m.select.return_value = [{"question_index": 7}, {"question_index": None},
                                 {"question_index": 0}]
        return m

    with patch("services.quiz_reserve.table", side_effect=factory):
        hashes = missed_question_hashes(SOURCE_ID, questions)
    assert hashes == [questions[0]["question_hash"]]


def test_missed_hashes_degrade_to_nothing_when_the_read_fails():
    def factory(name):
        m = MagicMock()
        m.select.side_effect = RuntimeError("PostgREST down")
        return m

    with patch("services.quiz_reserve.table", side_effect=factory):
        assert missed_question_hashes(SOURCE_ID, [_stored("Q1", 1)]) == []


def test_recovered_questions_are_verbatim_copies():
    """Same item, including the identity and the provenance of the
    generation that wrote it — that is what makes E5 identity survive
    across attempts. Copies, not aliases: the caller renumbers `id`."""
    source = [_stored("Q1", 1), _stored("Q2", 2)]
    got = recover_questions(source, [source[1]["question_hash"]])
    assert got == [source[1]]
    assert got[0] is not source[1]
    got[0]["id"] = 99
    got[0]["options"][0]["text"] = "mutated"
    assert source[1]["id"] == 2
    assert source[1]["options"][0]["text"] == "alpha"


def test_recovered_questions_follow_the_requested_order_and_dedupe():
    source = [_stored("Q1", 1), _stored("Q2", 2)]
    order = [source[1]["question_hash"], source[0]["question_hash"],
             source[1]["question_hash"]]
    assert [q["question"] for q in recover_questions(source, order)] == ["Q2", "Q1"]


def test_unknown_hashes_recover_nothing():
    """A hash the source attempt never held is not an error — it is simply
    not recoverable, and the caller regenerates that slot."""
    source = [_stored("Q1", 1)]
    assert recover_questions(source, ["deadbeefdeadbeef"]) == []


# ── the route: re-served everything ─────────────────────────────────────────


def test_full_reserve_makes_no_model_call():
    source_questions = [_stored("Q1", 1), _stored("Q2", 2), _stored("Q3", 3)]
    r, row, agent = _generate(
        attempts=[_attempt(source_questions)],
        responses=[{"question_index": 0}, {"question_index": 2}],
        num_questions=2,
        body_extra={"source_attempt_id": SOURCE_ID},
    )
    assert r.status_code == 200, r.text
    agent.assert_not_awaited()
    body = r.json()
    assert body["source"] == {
        "attempt_id": SOURCE_ID,
        "reserved_count": 2,
        "regenerated_count": 0,
    }
    assert body["delivered_count"] == 2
    assert [q["question"] for q in body["questions"]] == ["Q1", "Q3"]


def test_reserved_questions_keep_their_identity_and_take_new_positions():
    """`question_hash` is the item; `id` is only its position WITHIN an
    attempt (the /answer route validates question_id against it), so the
    identity carries over and the id is renumbered."""
    source_questions = [_stored("Q1", 1), _stored("Q2", 2), _stored("Q3", 3)]
    r, row, _ = _generate(
        attempts=[_attempt(source_questions)],
        responses=[{"question_index": 1}, {"question_index": 2}],
        num_questions=2,
        body_extra={"source_attempt_id": SOURCE_ID},
    )
    assert r.status_code == 200, r.text
    stored = _stored_questions(row)
    assert [q["question_hash"] for q in stored] == [
        source_questions[1]["question_hash"], source_questions[2]["question_hash"],
    ]
    assert [q["id"] for q in stored] == [1, 2]
    assert [q["provenance"]["model"] for q in stored] == ["gemini-2.5-flash-lite"] * 2
    assert all(q["provenance"]["reserved_from"] == SOURCE_ID for q in stored)


def test_reserved_questions_are_stripped_for_the_client_like_generated_ones():
    source_questions = [_stored("Q1", 1)]
    r, _, _ = _generate(
        attempts=[_attempt(source_questions)],
        responses=[{"question_index": 0}],
        num_questions=1,
        body_extra={"source_attempt_id": SOURCE_ID},
    )
    assert r.status_code == 200, r.text
    (question,) = r.json()["questions"]
    assert "question_hash" not in question
    assert "provenance" not in question
    # The keyed default still ships the answer key it always did.
    assert question["options"][0]["correct"] is True


def test_keyless_projection_also_strips_the_reserved_internals():
    source_questions = [_stored("Q1", 1)]
    r, _, _ = _generate(
        attempts=[_attempt(source_questions)],
        responses=[{"question_index": 0}],
        num_questions=1,
        body_extra={"source_attempt_id": SOURCE_ID, "include_answer_key": False},
    )
    assert r.status_code == 200, r.text
    (question,) = r.json()["questions"]
    assert set(question) == {"id", "question", "concept_tested", "difficulty", "options"}
    assert all(set(o) == {"label", "text"} for o in question["options"])


def test_explicit_hashes_win_over_the_recorded_responses():
    """The client may name the items itself; unknown ones are ignored
    rather than rejected, and count as "not recoverable"."""
    source_questions = [_stored("Q1", 1), _stored("Q2", 2)]
    r, _, agent = _generate(
        attempts=[_attempt(source_questions)],
        responses=[{"question_index": 0}],
        num_questions=1,
        body_extra={
            "source_attempt_id": SOURCE_ID,
            "missed_question_hashes": [
                source_questions[1]["question_hash"], "0000000000000000",
            ],
        },
    )
    assert r.status_code == 200, r.text
    agent.assert_not_awaited()
    assert [q["question"] for q in r.json()["questions"]] == ["Q2"]


# ── the route: re-served some ───────────────────────────────────────────────


def test_short_recovery_generates_only_the_remainder():
    source_questions = [_stored("Q1", 1)]
    r, row, agent = _generate(
        generated=[_agent_question("New A"), _agent_question("New B")],
        attempts=[_attempt(source_questions)],
        responses=[{"question_index": 0}],
        num_questions=3,
        body_extra={"source_attempt_id": SOURCE_ID},
    )
    assert r.status_code == 200, r.text
    agent.assert_awaited_once()
    prompt = agent.call_args[0][0]
    assert "Generate 2 easy questions" in prompt
    body = r.json()
    assert body["source"] == {
        "attempt_id": SOURCE_ID,
        "reserved_count": 1,
        "regenerated_count": 2,
    }
    assert [q["question"] for q in body["questions"]] == ["Q1", "New A", "New B"]
    assert [q["id"] for q in _stored_questions(row)] == [1, 2, 3]


def test_a_regenerated_repeat_of_a_reserved_question_is_dropped():
    """The do-not-repeat block should prevent it; if the model does it
    anyway, the student must not see the same item twice in one quiz."""
    source_questions = [_stored("Q1", 1, opts=("fresh-a", "fresh-b", "fresh-c", "fresh-d"))]
    r, _, _ = _generate(
        generated=[_agent_question("Q1"), _agent_question("New B")],
        attempts=[_attempt(source_questions)],
        responses=[{"question_index": 0}],
        num_questions=3,
        body_extra={"source_attempt_id": SOURCE_ID},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [q["question"] for q in body["questions"]] == ["Q1", "New B"]
    assert body["source"]["reserved_count"] == 1
    assert body["source"]["regenerated_count"] == 1
    assert body["delivered_count"] == 2


def test_a_failed_remainder_still_serves_what_was_recovered():
    source_questions = [_stored("Q1", 1)]
    r, _, _ = _generate(
        attempts=[_attempt(source_questions)],
        responses=[{"question_index": 0}],
        num_questions=3,
        body_extra={"source_attempt_id": SOURCE_ID},
        agent_side_effect=RuntimeError("Gemini is having a day"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == {
        "attempt_id": SOURCE_ID,
        "reserved_count": 1,
        "regenerated_count": 0,
    }
    assert body["delivered_count"] == 1
    assert body["requested_count"] == 3


def test_a_failed_generation_with_nothing_recovered_still_502s():
    r, _, _ = _generate(
        attempts=[_attempt([_stored("Q1", 1)])],
        responses=[],
        num_questions=3,
        body_extra={"source_attempt_id": SOURCE_ID},
        agent_side_effect=RuntimeError("Gemini is having a day"),
    )
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "QUIZ_GENERATION_FAILED"


# ── the route: re-served nothing ────────────────────────────────────────────


def test_nothing_recoverable_falls_back_to_plain_generation():
    """An attempt graded entirely through /submit records no
    `quiz_responses` rows, so there is nothing to re-serve. The response
    says so — reserved_count 0 — and the client keeps the old wording."""
    r, _, agent = _generate(
        generated=[_agent_question("New A"), _agent_question("New B")],
        attempts=[_attempt([_stored("Q1", 1)])],
        responses=[],
        num_questions=2,
        body_extra={"source_attempt_id": SOURCE_ID},
    )
    assert r.status_code == 200, r.text
    agent.assert_awaited_once()
    body = r.json()
    assert body["source"] == {
        "attempt_id": SOURCE_ID,
        "reserved_count": 0,
        "regenerated_count": 2,
    }


def test_a_plain_generate_carries_no_source_block():
    r, _, agent = _generate(
        generated=[_agent_question("New A"), _agent_question("New B")],
        num_questions=2,
    )
    assert r.status_code == 200, r.text
    agent.assert_awaited_once()
    assert "source" not in r.json()


# ── the route: refusals ─────────────────────────────────────────────────────


def test_unknown_source_attempt_404s():
    r, _, agent = _generate(attempts=[], body_extra={"source_attempt_id": SOURCE_ID})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_NOT_FOUND"
    agent.assert_not_awaited()


def test_someone_elses_attempt_403s():
    r, _, agent = _generate(
        attempts=[_attempt([_stored("Q1", 1)], user_id="user_someone_else")],
        body_extra={"source_attempt_id": SOURCE_ID},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "QUIZ_NOT_AUTHORIZED"
    agent.assert_not_awaited()


def test_an_unfinished_source_attempt_is_refused():
    """There is nothing to practise from a quiz still being sat, and
    "practise the ones you missed" is only reachable from the results
    screen — so this is a malformed request, not a state to work around."""
    r, _, agent = _generate(
        attempts=[_attempt([_stored("Q1", 1)], completed=False)],
        body_extra={"source_attempt_id": SOURCE_ID},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "QUIZ_VALIDATION_ERROR"
    agent.assert_not_awaited()


def test_more_hashes_than_a_quiz_can_hold_is_a_validation_error():
    r, _, _ = _generate(
        attempts=[_attempt([_stored("Q1", 1)])],
        body_extra={
            "source_attempt_id": SOURCE_ID,
            "missed_question_hashes": [f"{i:016x}" for i in range(11)],
        },
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "QUIZ_VALIDATION_ERROR"


# ── the route: guards and measurement ───────────────────────────────────────


def test_the_daily_spend_cap_does_not_block_a_pure_reserve():
    """The cap exists to stop LLM spend. Re-serving questions the student
    has already been served spends nothing, so a capped student can still
    practise what they missed."""
    source_questions = [_stored("Q1", 1)]
    with patch("routes.quiz._daily_spend_exceeded", return_value=True):
        r, _, agent = _generate(
            attempts=[_attempt(source_questions)],
            responses=[{"question_index": 0}],
            num_questions=1,
            body_extra={"source_attempt_id": SOURCE_ID},
        )
    assert r.status_code == 200, r.text
    agent.assert_not_awaited()


def test_the_daily_spend_cap_still_blocks_a_generated_remainder():
    source_questions = [_stored("Q1", 1)]
    with patch("routes.quiz._daily_spend_exceeded", return_value=True):
        r, _, agent = _generate(
            attempts=[_attempt(source_questions)],
            responses=[{"question_index": 0}],
            num_questions=3,
            body_extra={"source_attempt_id": SOURCE_ID},
        )
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "QUIZ_DAILY_LIMIT_REACHED"
    agent.assert_not_awaited()


def test_quiz_started_records_what_was_reserved(sink):
    from services import events_service

    source_questions = [_stored("Q1", 1)]
    r, _, _ = _generate(
        generated=[_agent_question("New A")],
        attempts=[_attempt(source_questions)],
        responses=[{"question_index": 0}],
        num_questions=2,
        body_extra={"source_attempt_id": SOURCE_ID},
    )
    assert r.status_code == 200, r.text
    events_service.flush_now()
    started = [e for e in sink if e["event_type"] == "quiz.started"]
    assert len(started) == 1
    payload = started[0]["payload"]
    assert payload["reserved_count"] == 1
    assert payload["regenerated_count"] == 1


def test_nothing_recoverable_from_a_completed_attempt_is_reported(sink):
    """F5: zero recovered from an attempt this student definitely completed
    is the silent-empty shape — the re-serve degraded to generation and
    nobody would otherwise know."""
    from services import events_service

    def probe(name):
        m = MagicMock()
        m.select.return_value = [{"id": SOURCE_ID}]
        return m

    with patch("services.tool_signals.table", side_effect=probe):
        r, _, _ = _generate(
            generated=[_agent_question("New A")],
            attempts=[_attempt([_stored("Q1", 1)])],
            responses=[],
            num_questions=1,
            body_extra={"source_attempt_id": SOURCE_ID},
        )
    assert r.status_code == 200, r.text
    events_service.flush_now()
    empties = [e for e in sink if e["event_type"] == "quiz.tool_empty"]
    assert len(empties) == 1
    assert empties[0]["payload"]["source_attempt_id"] == SOURCE_ID


@pytest.mark.parametrize("hashes", [None, []])
def test_omitted_hashes_are_derived_from_the_recorded_responses(hashes):
    source_questions = [_stored("Q1", 1), _stored("Q2", 2)]
    extra = {"source_attempt_id": SOURCE_ID}
    if hashes is not None:
        extra["missed_question_hashes"] = hashes
    r, _, agent = _generate(
        attempts=[_attempt(source_questions)],
        responses=[{"question_index": 1}],
        num_questions=1,
        body_extra=extra,
    )
    assert r.status_code == 200, r.text
    agent.assert_not_awaited()
    assert [q["question"] for q in r.json()["questions"]] == ["Q2"]
