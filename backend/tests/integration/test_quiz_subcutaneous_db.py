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

pytestmark = pytest.mark.integration

USER_ACTIVE = "rich-user-active"
CONCEPT_NODE = "rich-node-cs-recursion"

#: The function-mode seam's fixed answer key. Kept as a literal so a drift
#: between it and `agents/function_handlers_e2e.py` fails here loudly rather
#: than turning these assertions into whatever the seam happens to return.
E2E_LABELS = ("B", "C", "A")


@pytest.fixture(autouse=True)
def _requires_function_mode():
    if os.getenv("SAPLING_MODEL_MODE") != "function":
        pytest.skip(
            "quiz subcutaneous tests need SAPLING_MODEL_MODE=function "
            "(export it with SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e, "
            "as e2e.yml and the documented flock'd cycle do) — refusing to "
            "call live Gemini from a test"
        )


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


@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard", "adaptive"])
def test_generate_accepts_every_difficulty_the_config_advertises(
    authed_client, db_conn, difficulty
):
    """Including `adaptive` — #540's whole point was that the selector offered
    a value the route 400'd. `/api/quiz/config` is the source of truth for
    what the client may send, so everything it lists must round-trip."""
    advertised = authed_client.get("/api/quiz/config").json()
    assert difficulty in advertised["difficulties"], (
        f"{difficulty} is asserted here but not advertised by /api/quiz/config"
    )

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
    lo, hi = cfg["min"], cfg["max"]

    assert _generate(authed_client, num_questions=lo).status_code == 200
    assert _generate(authed_client, num_questions=hi).status_code == 200
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
        "SELECT question_index, selected_index FROM quiz_responses "
        "WHERE attempt_id = %s ORDER BY question_index",
        (quiz_id,),
    ).fetchall()
    assert [r["question_index"] for r in responses] == [0, 1, 2]

    s = authed_client.post("/api/quiz/submit", json={"quiz_id": quiz_id, "answers": []})
    assert s.status_code == 200, s.text

    row = _attempt_row(db_conn, quiz_id, "score, total, completed_at, answers_json")
    assert row["total"] == 3
    assert row["completed_at"] is not None
    assert row["score"] == s.json()["score"]
    # Submit persists WHAT IT GRADED, reconciled from quiz_responses — not the
    # (here empty) payload.
    assert isinstance(row["answers_json"], str), "answers_json must be ciphertext"


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

    first = authed_client.post("/api/quiz/submit", json={"quiz_id": quiz_id, "answers": []})
    assert first.status_code == 200, first.text
    mastery_after = db_conn.execute(
        "SELECT mastery_score FROM graph_nodes WHERE id = %s", (CONCEPT_NODE,)
    ).fetchone()["mastery_score"]

    replay = authed_client.post("/api/quiz/submit", json={"quiz_id": quiz_id, "answers": []})
    assert replay.status_code == 409, replay.text

    unchanged = db_conn.execute(
        "SELECT mastery_score FROM graph_nodes WHERE id = %s", (CONCEPT_NODE,)
    ).fetchone()["mastery_score"]
    assert unchanged == mastery_after, "the replay moved mastery a second time"


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


def test_another_student_can_neither_answer_nor_submit_this_attempt(
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

    assert _attempt_row(db_conn, quiz_id, "completed_at")["completed_at"] is None
    assert db_conn.execute(
        "SELECT count(*) AS n FROM quiz_responses WHERE attempt_id = %s", (quiz_id,)
    ).fetchone()["n"] == 0


# ── #529 regression guard, real DB ──────────────────────────────────────────


def test_the_adaptive_context_write_actually_lands(authed_client, db_conn):
    """#529's regression guard where it can actually fail. The write was
    swallowed for 51 days because the only tests that exercised it mocked
    `table()`; the constraint it needed had been dropped in 0025.

    Submitting must leave a `quiz_context` row for this (user, concept) — and
    a second submit must UPDATE it rather than 42P10 on the missing UNIQUE.
    """
    from services.quiz_context_service import save_quiz_context

    # The digest itself is an LLM background task, deliberately unregistered
    # in function mode so it can't race the next test's reseed. So this drives
    # the WRITE the bug was in, directly, against the real constraint.
    save_quiz_context(USER_ACTIVE, CONCEPT_NODE, {"weak_areas": ["first"]})
    save_quiz_context(USER_ACTIVE, CONCEPT_NODE, {"weak_areas": ["second"]})

    rows = db_conn.execute(
        "SELECT context_json FROM quiz_context "
        "WHERE user_id = %s AND concept_node_id = %s",
        (USER_ACTIVE, CONCEPT_NODE),
    ).fetchall()
    assert len(rows) == 1, (
        "two writes left more than one row — the (user_id, concept_node_id) "
        "UNIQUE is gone again, which is #529"
    )
