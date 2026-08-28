"""#545 (Workstream G, epic #537): the quiz loop, HTTP in and real Postgres out.

The gate this file closes. Every other quiz integration test either writes its
rows with `table()` and asserts the schema, or GETs one attempt — so the
WRITE paths (`generate`, `answer`, `submit`) were only ever exercised against
a MagicMock. That is precisely the blind spot #545 exists to remove:

  * #529 lived 51 days because the failing write was only ever mocked;
  * #265's column drift is the same shape — a route selecting or writing a
    column the migrations don't have, which a mocked `table()` cannot see;
  * #555 added a brand-new column to the `generate` INSERT, and nothing in
    this lane would have noticed if its migration had not been applied.

So these tests go in through the app's own HTTP surface, with a real session
cookie, and read back through a direct psycopg connection — never through the
same PostgREST layer that made the write, which would only prove the echo.

Requires function mode (`SAPLING_MODEL_MODE=function`), which is how the E2E
lanes run: `agents/function_handlers_e2e.py` pins a deterministic 3-question
quiz whose correct labels are B, C, A. Without it these would call live
Gemini, so the suite refuses rather than quietly billing an API.
"""
import os

import pytest

from agents.function_handlers_e2e import E2E_QUIZ_CORRECT_LABELS

pytestmark = pytest.mark.integration

USER_ACTIVE = "rich-user-active"
CONCEPT_NODE = "rich-node-cs-recursion"

#: The function-mode seam's fixed answer key, IMPORTED from the seam that
#: exports it as the named contract. Re-declaring it as a literal would make a
#: drift surface as "recorded answers must outrank an empty payload" — a
#: failure pointing at the reconciliation logic rather than at the constant
#: that moved.
E2E_LABELS = E2E_QUIZ_CORRECT_LABELS


@pytest.fixture(autouse=True)
def _requires_function_mode():
    """RAISE, never skip — the same rule `_require_local_stack` and
    `_require_local_db_url` follow in this lane's conftest, and for the same
    reason: a silent skip reads as "safe" while the gate reports green having
    run nothing. That is how the #265 drift survived the one lane built to
    catch it. The documented invocation (`RUN_INTEGRATION=1 pytest -m
    integration`) does not set these, so a skip here would quietly disable
    every test in the file.

    Raising still never bills Gemini, which is the actual thing to avoid.
    """
    mode = os.getenv("SAPLING_MODEL_MODE")
    handlers = os.getenv("SAPLING_FUNCTION_HANDLERS")
    if mode != "function" or not handlers:
        raise RuntimeError(
            "quiz subcutaneous tests need SAPLING_MODEL_MODE=function and "
            "SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e (as e2e.yml "
            f"and the documented flock'd cycle set them); got mode={mode!r} "
            f"handlers={handlers!r}. Refusing to skip silently — the gate would "
            "report green having run nothing."
        )


def _advertised_difficulties():
    """Read at collection time, straight from the source of truth the route
    and the client both bind to."""
    from services.quiz_config import quiz_config_payload

    return quiz_config_payload()["difficulties"]


def _generate(client, **overrides):
    body = {
        "user_id": USER_ACTIVE,
        "concept_node_id": CONCEPT_NODE,
        "num_questions": 3,
        "difficulty": "medium",
        "use_shared_context": False,
    }
    body.update(overrides)
    return client.post("/api/quiz/generate", json=body)


#: `rich-node-cs-recursion` in db/seed_local_rich.py. Asserted before use, so
#: a seed change fails loudly instead of silently re-baselining the delta.
SEEDED_MASTERY = 0.25


def _mastery(db_conn) -> float:
    return db_conn.execute(
        "SELECT mastery_score FROM graph_nodes WHERE id = %s", (CONCEPT_NODE,)
    ).fetchone()["mastery_score"]


def _mastery_event_count(db_conn) -> int:
    return db_conn.execute(
        "SELECT count(*) AS n FROM node_mastery_events WHERE node_id = %s",
        (CONCEPT_NODE,),
    ).fetchone()["n"]


def _attempt_row(db_conn, quiz_id, columns="*"):
    return db_conn.execute(
        f"SELECT {columns} FROM quiz_attempts WHERE id = %s", (quiz_id,)
    ).fetchone()


# ── generate ────────────────────────────────────────────────────────────────


def test_generate_writes_a_real_attempt_row_with_ciphertext_questions(
    authed_client, db_conn
):
    """The write path that a mocked `table()` cannot check: every column the
    route sends must actually exist, and `questions_json` must be ciphertext
    at rest."""
    r = _generate(authed_client)
    assert r.status_code == 200, r.text
    quiz_id = r.json()["quiz_id"]

    row = _attempt_row(db_conn, quiz_id, "user_id, concept_node_id, questions_json")
    assert row is not None, "generate returned 200 but wrote no attempt row"
    assert row["user_id"] == USER_ACTIVE
    assert row["concept_node_id"] == CONCEPT_NODE
    # #521: the JSON pair stores ciphertext as a JSONB string scalar. A dict
    # here means encryption regressed to plaintext.
    assert isinstance(row["questions_json"], str)
    assert "recursion" not in row["questions_json"].lower()


def test_generate_default_response_never_reveals_the_correct_option(
    authed_client, db_conn, assert_keyless_projection
):
    """With `include_answer_key` omitted entirely — the shape every real
    caller now gets (see GenerateQuizBody.include_answer_key, #546) —
    nothing anywhere in the response may let a client determine which
    option is correct, and what IS served must be the faithful keyless
    projection of what was stored.

    Grounded against the attempt's REAL stored answer key, decrypted
    straight from Postgres via the same helper the other tests in this file
    use: not a hand-built fixture, and not merely "the field named
    `correct` is absent" (a renamed or restructured leak would slip past a
    check that narrow).

    The assertions themselves live in the `assert_keyless_projection`
    fixture (tests/conftest.py), shared with the hermetic twin in
    tests/test_quiz_answers_c.py so the two lanes cannot drift; its
    docstring carries the non-circularity argument for the hard-coded
    allowlists it uses."""
    from services.encryption import decrypt_json_column

    r = _generate(authed_client)
    assert r.status_code == 200, r.text
    body = r.json()

    row = _attempt_row(db_conn, body["quiz_id"], "questions_json")
    assert row is not None, "generate returned 200 but wrote no attempt row"
    assert_keyless_projection(body, decrypt_json_column(row["questions_json"]))


@pytest.mark.parametrize("difficulty", _advertised_difficulties())
def test_generate_accepts_every_difficulty_the_config_advertises(
    authed_client, db_conn, difficulty
):
    """Including `adaptive` — #540's whole point was that the selector offered
    a value the route 400'd.

    Parametrized FROM the config payload, not from a literal list: a
    hard-coded list only proves the values I happened to think of are
    advertised, never the reverse, so a difficulty added to
    REQUESTED_DIFFICULTIES would ship untested. This way adding one adds a
    test case.
    """
    r = _generate(authed_client, difficulty=difficulty)
    assert r.status_code == 200, r.text
    body = r.json()
    # A resolved difficulty is always concrete, never the word "adaptive".
    assert body["resolved_difficulty"] in {"easy", "medium", "hard"}
    assert _attempt_row(db_conn, body["quiz_id"]) is not None


def test_generate_rejects_counts_outside_the_advertised_bounds(authed_client):
    """The 15-question option 422'd for months while the UI offered it (#540).
    Bounds are asserted against what config advertises, not against literals,
    so widening the cap can't leave this test pinning the old one."""
    cfg = authed_client.get("/api/quiz/config").json()["num_questions"]
    hi = cfg["max"]

    # EVERY advertised option, not just the bounds. `options` is the list the
    # UI actually renders, and it is exactly where #540 lived: "15" sat in
    # that list while the route capped at 10, so the selector offered a value
    # that always 422'd. Checking min/max alone reproduces that bug happily.
    for count in cfg["options"]:
        r = _generate(authed_client, num_questions=count)
        assert r.status_code == 200, (
            f"/api/quiz/config advertises num_questions={count} but generate "
            f"rejected it ({r.status_code}) — this is #540 verbatim: {r.text}"
        )

    assert _generate(authed_client, num_questions=hi + 1).status_code == 422
    assert _generate(authed_client, num_questions=0).status_code == 422


# ── answer → submit ─────────────────────────────────────────────────────────


def test_the_full_loop_generates_answers_submits_and_persists_what_it_graded(
    authed_client, db_conn
):
    """generate → per-question answer → submit, all over HTTP, asserted in
    Postgres. This is the path C made server-authoritative, and the one that
    had no real-DB coverage at all."""
    quiz_id = _generate(authed_client).json()["quiz_id"]

    for index in range(3):
        a = authed_client.post(
            f"/api/quiz/attempts/{quiz_id}/answer",
            json={"question_index": index, "selected_index": 1},
        )
        assert a.status_code == 200, a.text

    responses = db_conn.execute(
        "SELECT question_index, selected_index, is_correct FROM quiz_responses "
        "WHERE attempt_id = %s ORDER BY question_index",
        (quiz_id,),
    ).fetchall()
    assert [r["question_index"] for r in responses] == [0, 1, 2]
    # `is_correct` exists BECAUSE grading moved server-side (#541 C1), and
    # nothing else in this file would notice it being wrong: submit re-derives
    # the score from selected_index plus the stored key and never reads it. So
    # inverting it would poison every response row and every future item
    # statistic while the whole suite stayed green.
    # Index 1 is label B; the seam's key is B, C, A — so only Q1 is correct.
    assert [r["is_correct"] for r in responses] == [True, False, False]

    s = authed_client.post("/api/quiz/submit", json={"quiz_id": quiz_id, "answers": []})
    assert s.status_code == 200, s.text

    row = _attempt_row(db_conn, quiz_id, "score, total, completed_at, answers_json")
    assert row["total"] == 3
    assert row["completed_at"] is not None
    assert row["score"] == s.json()["score"] == 1

    # Submit persists WHAT IT GRADED, reconciled from quiz_responses — not the
    # (here EMPTY) payload. `isinstance(..., str)` alone does not say that:
    # `encrypt_json([])` is a str too, so storing the empty payload instead
    # would pass. Decrypt and count.
    from services.encryption import decrypt_json_column

    assert isinstance(row["answers_json"], str), "answers_json must be ciphertext"
    graded = decrypt_json_column(row["answers_json"])
    assert len(graded) == 3, (
        "submit stored the request payload (empty) instead of the three "
        "responses it actually graded"
    )
    assert {a["selected_label"] for a in graded} == {"B"}


def test_answers_recorded_through_the_endpoint_beat_an_empty_payload(
    authed_client, db_conn
):
    """The reconciliation C added. Answering every question correctly through
    the per-question endpoint and then submitting an EMPTY payload must still
    score 3/3 — the recorded responses are the truth."""
    quiz_id = _generate(authed_client).json()["quiz_id"]

    detail = authed_client.get(f"/api/quiz/attempts/{quiz_id}").json()
    for index, q in enumerate(detail["questions"]):
        correct_index = [o["label"] for o in q["options"]].index(E2E_LABELS[index])
        authed_client.post(
            f"/api/quiz/attempts/{quiz_id}/answer",
            json={"question_index": index, "selected_index": correct_index},
        )

    s = authed_client.post("/api/quiz/submit", json={"quiz_id": quiz_id, "answers": []})
    assert s.status_code == 200, s.text
    assert s.json()["score"] == 3, "recorded answers must outrank an empty payload"

    assert _attempt_row(db_conn, quiz_id, "score")["score"] == 3


def test_a_replayed_submit_is_a_409_and_re_applies_no_mastery(
    authed_client, db_conn
):
    """#129/D: the atomic `completed_at` claim. A double submit must not
    double-count mastery, and the real constraint is what enforces it."""
    quiz_id = _generate(authed_client).json()["quiz_id"]
    authed_client.post(f"/api/quiz/attempts/{quiz_id}/answer",
                       json={"question_index": 0, "selected_index": 1})

    before = _mastery(db_conn)
    assert before == pytest.approx(SEEDED_MASTERY), (
        "the seed moved; this test's arithmetic anchors on it"
    )

    first = authed_client.post("/api/quiz/submit", json={"quiz_id": quiz_id, "answers": []})
    assert first.status_code == 200, first.text

    # ANCHORED, not self-compared. Snapshotting after the first submit and
    # comparing it to itself cannot tell "the replay applied nothing" from
    # "nothing was ever applied" — so a no-op `apply_graph_update`, or a
    # #553-shaped keyspace miss on the node lookup, would leave mastery at the
    # seeded value through both calls and pass while claiming to guard #129.
    # 1 correct (+0.03), 2 wrong (-0.02 each) => -0.01.
    after_first = _mastery(db_conn)
    assert after_first == pytest.approx(SEEDED_MASTERY - 0.01, abs=1e-6), (
        "the first submit did not apply the mastery delta at all"
    )
    events_after_first = _mastery_event_count(db_conn)
    assert events_after_first > 0, "no mastery event was journalled"

    replay = authed_client.post("/api/quiz/submit", json={"quiz_id": quiz_id, "answers": []})
    assert replay.status_code == 409, replay.text

    assert _mastery(db_conn) == pytest.approx(after_first, abs=1e-6), (
        "the replay moved mastery a second time"
    )
    assert _mastery_event_count(db_conn) == events_after_first, (
        "the replay journalled a second mastery event"
    )


# ── abandon ─────────────────────────────────────────────────────────────────


def test_abandon_stamps_the_real_row_and_the_listing_agrees(authed_client, db_conn):
    """#537 G4. The point of the endpoint is that the DATABASE, not one
    browser's localStorage, is what stops offering the attempt — so the stamp
    is read back through psycopg rather than through the PostgREST layer that
    wrote it, and the derived status is read back off the listing."""
    quiz_id = _generate(authed_client).json()["quiz_id"]

    first = authed_client.post(f"/api/quiz/attempts/{quiz_id}/abandon")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "abandoned"

    row = _attempt_row(db_conn, quiz_id, "completed_at, abandoned_at")
    assert row["abandoned_at"] is not None, "the discard never reached the row"
    assert row["completed_at"] is None, (
        "a discard must not complete the attempt — no score, no mastery, no XP"
    )

    # Idempotent: the client fires this and forgets it, so a retry after a
    # dropped response answers with the stamp already stored.
    again = authed_client.post(f"/api/quiz/attempts/{quiz_id}/abandon")
    assert again.status_code == 200, again.text
    assert again.json() == first.json()

    listing = authed_client.get(f"/api/quiz/attempts?user_id={USER_ACTIVE}")
    mine = next(a for a in listing.json()["attempts"] if a["quiz_id"] == quiz_id)
    assert mine["status"] == "abandoned", (
        "the history listing still calls it in_progress, so the resume strip "
        "would offer it again on the next device"
    )


def test_abandoning_a_submitted_attempt_is_a_409(authed_client, db_conn):
    quiz_id = _generate(authed_client).json()["quiz_id"]
    assert authed_client.post(
        "/api/quiz/submit", json={"quiz_id": quiz_id, "answers": []}
    ).status_code == 200

    r = authed_client.post(f"/api/quiz/attempts/{quiz_id}/abandon")
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_ALREADY_COMPLETED"
    assert _attempt_row(db_conn, quiz_id, "abandoned_at")["abandoned_at"] is None


# ── resume + history ────────────────────────────────────────────────────────


def test_resume_returns_the_attempt_without_leaking_the_answer_key(authed_client):
    """D's `_strip_answer_key` is an ALLOWLIST because it previously shipped
    `explanation`, which names the answer in prose. Asserted on the real
    stored shape rather than a fixture."""
    quiz_id = _generate(authed_client).json()["quiz_id"]

    detail = authed_client.get(f"/api/quiz/attempts/{quiz_id}")
    assert detail.status_code == 200, detail.text
    for q in detail.json()["questions"]:
        assert "explanation" not in q
        for opt in q["options"]:
            assert "correct" not in opt, "resume leaked the answer key"


def test_history_lists_the_students_own_completed_attempts(authed_client):
    quiz_id = _generate(authed_client).json()["quiz_id"]
    authed_client.post(f"/api/quiz/attempts/{quiz_id}/answer",
                       json={"question_index": 0, "selected_index": 1})
    authed_client.post("/api/quiz/submit", json={"quiz_id": quiz_id, "answers": []})

    listing = authed_client.get(f"/api/quiz/attempts?user_id={USER_ACTIVE}")
    assert listing.status_code == 200, listing.text

    body = listing.json()
    # `quiz_id`, not `id` — the listing speaks the same key the generate
    # response and the submit body use, so a client never has to translate.
    mine = next(a for a in body["attempts"] if a["quiz_id"] == quiz_id)
    assert mine["status"] == "completed"
    assert mine["total"] == 3
    assert mine["concept_node_id"] == CONCEPT_NODE
    # The listing is the plaintext-scalar reader (#521/#527) — it must carry
    # no question payload, and therefore no answer key.
    assert "questions" not in mine and "questions_json" not in mine


def test_another_student_can_neither_answer_submit_nor_abandon_this_attempt(
    authed_client, other_user_client, db_conn
):
    """The hermetic lane stubs `require_self` to a no-op, so it structurally
    cannot test ownership. This is where an IDOR negative has to live."""
    quiz_id = _generate(authed_client).json()["quiz_id"]

    a = other_user_client.post(
        f"/api/quiz/attempts/{quiz_id}/answer",
        json={"question_index": 0, "selected_index": 1},
    )
    assert a.status_code in (403, 404), a.text

    s = other_user_client.post("/api/quiz/submit", json={"quiz_id": quiz_id, "answers": []})
    assert s.status_code in (403, 404), s.text

    # #537 G4: a discard closes someone's quiz, so it is a write like the other
    # two and needs the same owner check.
    d = other_user_client.post(f"/api/quiz/attempts/{quiz_id}/abandon")
    assert d.status_code in (403, 404), d.text

    row = _attempt_row(db_conn, quiz_id, "completed_at, abandoned_at")
    assert row["completed_at"] is None
    assert row["abandoned_at"] is None
    assert db_conn.execute(
        "SELECT count(*) AS n FROM quiz_responses WHERE attempt_id = %s", (quiz_id,)
    ).fetchone()["n"] == 0


# ── #555's column, actually asserted ────────────────────────────────────────


def test_generate_persists_exam_days_away_when_an_exam_is_upcoming(
    authed_client, db_conn
):
    """The claim this file's docstring makes, made true.

    Nothing else here would notice `20260822090747` going missing, for two
    independent reasons: every exam in the rich seed is in the PAST (the only
    CS one is dated 2025-10-15), so `days_until_next_exam` returns None and
    the column never enters the INSERT at all; and `_insert_attempt`
    deliberately catches the unknown-column failure, retries without the key
    and still returns 200. So the write has to be provoked and then read back
    from Postgres.
    """
    from datetime import date, timedelta

    from db.connection import table

    due = date.today() + timedelta(days=5)
    table("assignments").insert({
        "id": "sub-exam-upcoming",
        "enrollment_id": "rich-enr-active-cs101-f25",
        "category_id": "rich-cat-cs-f25-exams",
        "title": "Final Exam",
        "due_date": due.isoformat(),
        "assignment_type": "exam",
        "source": "manual",
    })

    quiz_id = _generate(authed_client).json()["quiz_id"]

    stored = _attempt_row(db_conn, quiz_id, "exam_days_away")["exam_days_away"]
    assert stored == 5, (
        f"expected exam_days_away=5, got {stored!r}. None means the column was "
        "dropped by _insert_attempt's fallback — i.e. the migration is not "
        "applied here"
    )


def test_a_past_exam_leaves_the_column_null(authed_client, db_conn):
    """The seed's own state, pinned: CS's only exam is in the past, so there
    is nothing upcoming and NULL is the honest answer. Without this, the test
    above could pass against a `days_until_next_exam` that returned a constant.
    """
    quiz_id = _generate(authed_client).json()["quiz_id"]
    assert _attempt_row(db_conn, quiz_id, "exam_days_away")["exam_days_away"] is None


# ── G5: practise the ones you missed ────────────────────────────────────────


def _sat_and_missed(authed_client):
    """Generate, answer every question B, submit. Returns the attempt id.

    The seam's key is B, C, A — so B throughout gets Q1 right and misses Q2
    and Q3, which is the state "practise the ones you missed" starts from.
    """
    quiz_id = _generate(authed_client).json()["quiz_id"]
    for index in range(3):
        a = authed_client.post(
            f"/api/quiz/attempts/{quiz_id}/answer",
            json={"question_index": index, "selected_index": 1},
        )
        assert a.status_code == 200, a.text
    s = authed_client.post("/api/quiz/submit", json={"quiz_id": quiz_id, "answers": []})
    assert s.status_code == 200, s.text
    assert s.json()["score"] == 1, "the seam's answer key moved; this setup assumes B, C, A"
    return quiz_id


def _stored_questions(db_conn, quiz_id):
    from services.encryption import decrypt_json_column

    row = _attempt_row(db_conn, quiz_id, "questions_json")
    return decrypt_json_column(row["questions_json"])


def test_practising_the_missed_questions_re_serves_them_verbatim(
    authed_client, db_conn
):
    """G5 over HTTP with real rows.

    The mocked lane cannot prove the derivation — it hands the route exactly
    the response rows it wants to see. Here `is_correct` was written into
    Postgres by the /answer route and read back by the query under test, so
    "which ones did they miss" is answered by the system, not by a fixture.
    """
    source_id = _sat_and_missed(authed_client)
    source = _stored_questions(db_conn, source_id)
    missed = source[1:]

    r = _generate(authed_client, num_questions=2, source_attempt_id=source_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == {
        "attempt_id": source_id,
        "reserved_count": 2,
        "regenerated_count": 0,
    }
    assert [q["question"] for q in body["questions"]] == [q["question"] for q in missed]

    stored = _stored_questions(db_conn, body["quiz_id"])
    # E5 identity survives the copy — the same items, asked again — while the
    # ids are renumbered, because an id is a position inside one attempt.
    assert [q["question_hash"] for q in stored] == [q["question_hash"] for q in missed]
    assert [q["id"] for q in stored] == [1, 2]
    assert all(q["provenance"]["reserved_from"] == source_id for q in stored)


def test_a_longer_practice_quiz_tops_up_with_generated_questions(
    authed_client, db_conn
):
    """Two recoverable misses, three asked for: the remainder comes from the
    ordinary generation path, and the response says how the quiz was split."""
    source_id = _sat_and_missed(authed_client)

    r = _generate(authed_client, num_questions=3, source_attempt_id=source_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"]["reserved_count"] == 2
    assert body["source"]["regenerated_count"] >= 1
    assert body["delivered_count"] == len(body["questions"])
    stems = [q["question"] for q in body["questions"]]
    assert len(set(stems)) == len(stems), "a re-served item was also regenerated"
