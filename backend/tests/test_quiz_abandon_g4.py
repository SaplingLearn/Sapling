"""#537 G4: `POST /api/quiz/attempts/{id}/abandon` — a real discard.

Until this route existed, "Discard" on the resume strip was a localStorage
flag (`lib/quiz/session.ts::dismissAttempt`): the row stayed `in_progress`
until D2's 24h sweep found it, so the strip came back on the student's phone,
in a second tab, and in this browser as soon as the key was cleared. The
endpoint lets the client write the same `abandoned_at` stamp the sweep writes,
which is what makes a discard cross devices.

The contract pinned here:

  * 200 stamps `abandoned_at` and reports the DERIVED status;
  * a second call is a 200 no-op with the same body (retry after a dropped
    response must not be an error) and writes nothing a second time;
  * a completed attempt 409s — discarding a submitted quiz would erase
    nothing, and the client's idea of the state was wrong;
  * an unknown attempt 404s, and another student's attempt 403s before any
    write is attempted;
  * the derived status the read paths report flips to `abandoned`, which is
    what the resume strip filters on.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

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

STAMP = "2026-08-23T02:00:00+00:00"


def _recent() -> str:
    """A created_at inside the abandon TTL, relative so the suite can't rot."""
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


def _matches(row: dict, column: str, expression: str) -> bool:
    """The subset of PostgREST filter grammar these routes use, applied to one
    row. Enough for the conditional claim AND for D2's lazy sweep, which runs
    on the read paths in the middle of these tests."""
    value = row.get(column)
    if expression == "is.null":
        return value is None
    if expression.startswith("eq."):
        return str(value) == expression[3:]
    if expression.startswith("lt."):
        if value is None:
            return False
        return str(value) < expression[3:]
    if expression.startswith("not.in.("):
        return str(value) not in set(expression[8:-1].split(","))
    raise AssertionError(f"unmodelled PostgREST filter: {column}={expression!r}")


class _Attempts:
    """A `quiz_attempts` stand-in whose UPDATE honours its filters.

    A MagicMock returning a constant cannot tell "the claim won" from "the
    claim was refused", which is the only thing the idempotency and the
    concurrent-submit branches turn on — so the arbitration is modelled here
    rather than asserted against a canned return value. Timestamps compare as
    ISO strings, which sort correctly while they share an offset (they do:
    everything here is written UTC by the route).
    """

    def __init__(self, row: dict | None):
        self.row = row
        self.updates: list[tuple[dict, dict]] = []

    def select(self, columns="*", filters=None, **kw):
        return [dict(self.row)] if self.row else []

    def select_with_count(self, columns="*", filters=None, **kw):
        rows = [dict(self.row)] if self.row else []
        return rows, len(rows)

    def update(self, data, filters=None, **kw):
        filters = filters or {}
        self.updates.append((dict(data), dict(filters)))
        if self.row is None:
            return []
        if not all(_matches(self.row, c, e) for c, e in filters.items()):
            return []
        self.row.update(data)
        return [dict(self.row)]


def _factory(attempts: _Attempts, responses=None):
    def factory(name):
        if name == "quiz_attempts":
            return attempts
        mock = MagicMock()
        mock.select.return_value = responses or []
        mock.update.return_value = []
        mock.select_with_count.return_value = ([], 0)
        return mock

    return factory


# ── the happy path ──────────────────────────────────────────────────────────


class TestAbandon:
    def test_stamps_abandoned_at_and_reports_the_derived_status(self):
        attempts = _Attempts(_attempt_row())

        with patch("routes.quiz.table", side_effect=_factory(attempts)):
            r = client.post("/api/quiz/attempts/quiz1/abandon")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["quiz_id"] == "quiz1"
        assert body["status"] == "abandoned"
        assert body["abandoned_at"] == attempts.row["abandoned_at"]
        assert attempts.row["abandoned_at"] is not None
        assert attempts.row["completed_at"] is None, (
            "a discard must not complete the attempt — no score, no mastery, no XP"
        )

    def test_the_claim_is_conditional_on_the_attempt_still_being_open(self):
        """Same idiom as submit's `completed_at IS NULL` claim: the FILTERS
        arbitrate, so a concurrent submit and abandon cannot both win."""
        attempts = _Attempts(_attempt_row())

        with patch("routes.quiz.table", side_effect=_factory(attempts)):
            client.post("/api/quiz/attempts/quiz1/abandon")

        assert len(attempts.updates) == 1
        _, filters = attempts.updates[0]
        assert filters["id"] == "eq.quiz1"
        assert filters["completed_at"] == "is.null"
        assert filters["abandoned_at"] == "is.null"

    def test_a_second_abandon_is_a_200_no_op_with_the_same_body(self):
        """A retry after a dropped response is free. The client fires this
        and forgets it; making the retry an error would put a red toast on a
        discard that already worked."""
        attempts = _Attempts(_attempt_row())

        with patch("routes.quiz.table", side_effect=_factory(attempts)):
            first = client.post("/api/quiz/attempts/quiz1/abandon")
            second = client.post("/api/quiz/attempts/quiz1/abandon")

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert second.json() == first.json()
        assert len(attempts.updates) == 1, (
            "the second call re-stamped a row that was already abandoned"
        )

    def test_an_attempt_swept_by_the_ttl_reports_the_sweeps_own_stamp(self):
        """The sweep and the button write the same column, so a discard of an
        already-swept row answers with the stamp that is actually stored — not
        a fresh one that would pretend the student closed it just now."""
        attempts = _Attempts(_attempt_row(abandoned_at=STAMP))

        with patch("routes.quiz.table", side_effect=_factory(attempts)):
            r = client.post("/api/quiz/attempts/quiz1/abandon")

        assert r.status_code == 200, r.text
        assert r.json()["abandoned_at"] == STAMP
        assert attempts.updates == []


# ── the refusals ────────────────────────────────────────────────────────────


class TestAbandonRefusals:
    def test_a_completed_attempt_409s_and_is_not_stamped(self):
        attempts = _Attempts(
            _attempt_row(completed_at="2026-08-23T01:00:00+00:00", score=1, total=1)
        )

        with patch("routes.quiz.table", side_effect=_factory(attempts)):
            r = client.post("/api/quiz/attempts/quiz1/abandon")

        assert r.status_code == 409
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_ALREADY_COMPLETED"
        assert attempts.row["abandoned_at"] is None
        assert attempts.updates == []

    def test_a_submit_that_wins_the_race_turns_the_abandon_into_a_409(self):
        """The pre-read said in_progress, the conditional update disagreed.
        Reporting 200 there would tell the client it discarded a quiz that had
        just been scored — so the loser re-reads and answers with the state
        that actually landed."""
        attempts = _Attempts(_attempt_row())
        real_update = attempts.update

        def _update_after_a_concurrent_submit(data, filters=None, **kw):
            attempts.row["completed_at"] = "2026-08-23T01:00:00+00:00"
            return real_update(data, filters, **kw)

        attempts.update = _update_after_a_concurrent_submit

        with patch("routes.quiz.table", side_effect=_factory(attempts)):
            r = client.post("/api/quiz/attempts/quiz1/abandon")

        assert r.status_code == 409
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_ALREADY_COMPLETED"
        assert attempts.row["abandoned_at"] is None

    def test_an_unknown_attempt_404s(self):
        attempts = _Attempts(None)

        with patch("routes.quiz.table", side_effect=_factory(attempts)):
            r = client.post("/api/quiz/attempts/nope/abandon")

        assert r.status_code == 404
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_NOT_FOUND"

    def test_another_students_attempt_403s_before_anything_is_written(self):
        """The lane stubs `require_self` to a no-op, so the REAL guard is
        restored for this one case — otherwise the ownership check on a brand
        new write route is structurally untestable here."""
        from services.auth_guard import _real_require_self

        attempts = _Attempts(_attempt_row(user_id="someone_else"))

        with (
            patch("routes.quiz.table", side_effect=_factory(attempts)),
            patch("routes.quiz.require_self", _real_require_self),
            patch("services.auth_guard.get_session_user_id", return_value="user_andres"),
        ):
            r = client.post("/api/quiz/attempts/quiz1/abandon")

        assert r.status_code == 403
        assert attempts.row["abandoned_at"] is None
        assert attempts.updates == []


# ── what the read paths say afterwards ──────────────────────────────────────


class TestAbandonIsVisibleToTheReadPaths:
    """The point of the endpoint: the strip drops the attempt because the
    SERVER says so, on a reload and on any other device — not because this
    browser is hiding it."""

    def test_the_resume_read_stops_offering_the_attempt(self):
        attempts = _Attempts(_attempt_row())

        with patch("routes.quiz.table", side_effect=_factory(attempts)):
            before = client.get("/api/quiz/attempts/quiz1")
            assert before.json()["resumable"] is True

            client.post("/api/quiz/attempts/quiz1/abandon")
            after = client.get("/api/quiz/attempts/quiz1")

        assert after.status_code == 200
        assert after.json()["status"] == "abandoned"
        assert after.json()["resumable"] is False
        assert after.json()["questions"] == []

    def test_the_history_listing_reports_abandoned_not_in_progress(self):
        """`GET /attempts` is HISTORY (D4) and deliberately still lists the
        row — what changes is its status, which is exactly what the resume
        strip filters on (`useQuizHome::discoverResumable`)."""
        attempts = _Attempts(_attempt_row())

        with patch("routes.quiz.table", side_effect=_factory(attempts)):
            client.post("/api/quiz/attempts/quiz1/abandon")
            listing = client.get(
                "/api/quiz/attempts", params={"user_id": "user_andres"}
            )

        assert listing.status_code == 200
        rows = listing.json()["attempts"]
        assert [a["quiz_id"] for a in rows] == ["quiz1"]
        assert rows[0]["status"] == "abandoned"

    def test_answering_an_abandoned_attempt_409s(self):
        """The discard has to bite on the write paths too, or it is a label."""
        attempts = _Attempts(_attempt_row())

        with patch("routes.quiz.table", side_effect=_factory(attempts)):
            client.post("/api/quiz/attempts/quiz1/abandon")
            r = client.post(
                "/api/quiz/attempts/quiz1/answer",
                json={"question_index": 0, "selected_index": 1},
            )

        assert r.status_code == 409
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_ABANDONED"
