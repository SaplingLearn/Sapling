"""#537 G4: `POST /api/quiz/attempts/{id}/abandon` — a real discard.

Why the route exists is told once, in `routes/quiz.py::abandon_attempt`.

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
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

# The attempt-row shape is the D-workstream's (#542) and is single-sourced
# there: two byte-identical copies drifted apart the moment either route grew
# a column. `tests/` is on sys.path during collection, so this is the module
# pytest already imported, not a second copy of it.
from test_quiz_lifecycle_d import _attempt_row

client = TestClient(app)


STAMP = "2026-08-23T02:00:00+00:00"


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
    """A `quiz_attempts` stand-in whose READS AND WRITES honour their filters.

    A MagicMock returning a constant cannot tell "the claim won" from "the
    claim was refused", which is the only thing the idempotency and the
    concurrent-submit branches turn on — so the arbitration is modelled here
    rather than asserted against a canned return value. Timestamps compare as
    ISO strings, which sort correctly while they share an offset (they do:
    everything here is written UTC by the route).

    The filters are honoured on `select` too. A fake that hands the stored row
    back whatever it was asked for cannot fail when a route drops or
    mis-builds an `id=eq.` / `user_id=eq.` filter — the reads would keep
    answering, and the ownership and lost-claim branches would all be pinned
    against a row nobody actually asked for.

    `prefer_return_minimal` is modelled because the real `table().update`
    returns `[]` in that mode (`db/connection.py`): a claim refactored to
    minimal reads as LOST on every request, and a fake that ignores the kwarg
    would let that land green.
    """

    def __init__(self, row: dict | None):
        self.row = row
        #: (data, filters, kwargs) per update — kwargs so the claim can be
        #: pinned as a representation read, not a minimal one.
        self.updates: list[tuple[dict, dict, dict]] = []
        #: (columns, filters) per select, in call order.
        self.selects: list[tuple[str, dict]] = []

    def _rows(self, filters=None) -> list[dict]:
        filters = filters or {}
        if self.row is None:
            return []
        if not all(_matches(self.row, c, e) for c, e in filters.items()):
            return []
        return [dict(self.row)]

    def select(self, columns="*", filters=None, **kw):
        self.selects.append((columns, dict(filters or {})))
        return self._rows(filters)

    def select_with_count(self, columns="*", filters=None, **kw):
        self.selects.append((columns, dict(filters or {})))
        rows = self._rows(filters)
        return rows, len(rows)

    def update(self, data, filters=None, *, prefer_return_minimal=False, **kw):
        filters = filters or {}
        self.updates.append((dict(data), dict(filters), {
            "prefer_return_minimal": prefer_return_minimal, **kw,
        }))
        if not self._rows(filters):
            return []
        self.row.update(data)
        return [] if prefer_return_minimal else [dict(self.row)]


def _factory(attempts: _Attempts):
    def factory(name):
        if name == "quiz_attempts":
            return attempts
        mock = MagicMock()
        mock.select.return_value = []
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
        _, filters, kwargs = attempts.updates[0]
        assert filters["id"] == "eq.quiz1"
        assert filters["completed_at"] == "is.null"
        assert filters["abandoned_at"] == "is.null"
        # The claim's RETURNED ROWS are the arbitration — `[]` means another
        # request won it. `prefer_return_minimal` makes the real client return
        # `[]` unconditionally (db/connection.py), which would read as "lost"
        # on every single discard.
        assert kwargs["prefer_return_minimal"] is False

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

    def test_a_row_that_vanished_under_the_claim_404s_rather_than_faking_a_stamp(self):
        """Merge-gate review (D2). The lost-claim branch used to read the row
        back as `(rows or [{}])[0]` and then answer
        `{"status": "abandoned", "abandoned_at": <now>}` — a success built out
        of an empty dict and a timestamp NOTHING EVER WROTE. A row that is
        gone by the re-read is the 404 the top of the route already reports."""
        attempts = _Attempts(_attempt_row())
        real_update = attempts.update

        def _deleted_under_the_claim(data, filters=None, **kw):
            attempts.row = None
            return real_update(data, filters, **kw)

        attempts.update = _deleted_under_the_claim

        with patch("routes.quiz.table", side_effect=_factory(attempts)):
            r = client.post("/api/quiz/attempts/quiz1/abandon")

        assert r.status_code == 404, r.text
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_NOT_FOUND"

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
        # …and the row came back because the LISTING ASKED FOR IT, scoped to
        # the signed-in student. Without this the fake would hand the row to
        # any query at all and the status above would be pinned on a read
        # nobody made.
        columns, filters = attempts.selects[-1]
        assert filters == {"user_id": "eq.user_andres"}
        assert "abandoned_at" in columns, (
            "the derived status is computed from the projection — dropping "
            "abandoned_at here reads every discarded attempt as in_progress"
        )

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

    def test_submitting_an_abandoned_attempt_409s(self):
        attempts = _Attempts(_attempt_row())
        apply_mock = MagicMock()

        with (
            patch("routes.quiz.table", side_effect=_factory(attempts)),
            patch("routes.quiz.apply_graph_update", new=apply_mock),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.save_quiz_context"),
        ):
            client.post("/api/quiz/attempts/quiz1/abandon")
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "B"}],
            })

        assert r.status_code == 409
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_ABANDONED"
        apply_mock.assert_not_called()


class TestSubmitAndAbandonCannotBothWin:
    """Review round 1 (M3). G4 makes this interleaving reachable from the UI:
    a quiz open mid-question in one tab, Discard pressed in another.

    Submit's claim used to filter on `completed_at IS NULL` alone, with
    `_refuse_if_abandoned` as a non-atomic PRE-READ in front of it — so a
    stamp written in the window between the two slipped through and the row
    ended up completed AND abandoned. Benign today (the derived status reads
    `completed`) but asymmetric: abandon's claim already required both nulls.
    """

    def test_a_discard_landing_mid_submit_is_refused_by_the_claim(self):
        attempts = _Attempts(_attempt_row())
        apply_mock = MagicMock()
        real_select = attempts.select

        def _discarded_after_the_pre_read(columns="*", filters=None, **kw):
            rows = real_select(columns, filters, **kw)
            # The concurrent Discard lands here — after submit has read the
            # row and decided it is open, before the claim runs. This is the
            # exact window `_refuse_if_abandoned` cannot cover.
            attempts.row["abandoned_at"] = STAMP
            attempts.select = real_select
            return rows

        attempts.select = _discarded_after_the_pre_read

        with (
            patch("routes.quiz.table", side_effect=_factory(attempts)),
            patch("routes.quiz.apply_graph_update", new=apply_mock),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.save_quiz_context"),
        ):
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "B"}],
            })

        # Asserted FIRST so a regression names the actual defect: with the
        # old single-null filter the claim wins and the request sails past
        # this point, failing later on something unrelated.
        assert attempts.row["completed_at"] is None, (
            "the claim let a submit complete a row the student had discarded"
        )
        apply_mock.assert_not_called()
        assert r.status_code == 409
        # The 409 must say why. "Already submitted" would be a lie the client
        # acts on — it maps this code to its own copy (quiz-errors.spec.ts).
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_ABANDONED"

    def test_the_ordinary_double_submit_still_reads_as_already_completed(self):
        """The re-read must not relabel the case it was always for."""
        attempts = _Attempts(_attempt_row())
        apply_mock = MagicMock()
        real_select = attempts.select

        def _submitted_after_the_pre_read(columns="*", filters=None, **kw):
            rows = real_select(columns, filters, **kw)
            attempts.row["completed_at"] = STAMP
            attempts.select = real_select
            return rows

        attempts.select = _submitted_after_the_pre_read

        with (
            patch("routes.quiz.table", side_effect=_factory(attempts)),
            patch("routes.quiz.apply_graph_update", new=apply_mock),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.save_quiz_context"),
        ):
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "B"}],
            })

        assert r.status_code == 409
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_ALREADY_COMPLETED"
        apply_mock.assert_not_called()

    def test_a_row_that_vanished_under_the_claim_404s(self):
        """Merge-gate review (D3). `(rows or [{}])[0]` made
        `_refuse_if_abandoned({})` a no-op and reported ALREADY_COMPLETED for
        an attempt that is simply gone."""
        attempts = _Attempts(_attempt_row())
        apply_mock = MagicMock()
        real_update = attempts.update

        def _deleted_under_the_claim(data, filters=None, **kw):
            attempts.row = None
            return real_update(data, filters, **kw)

        attempts.update = _deleted_under_the_claim

        with (
            patch("routes.quiz.table", side_effect=_factory(attempts)),
            patch("routes.quiz.apply_graph_update", new=apply_mock),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.save_quiz_context"),
        ):
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "B"}],
            })

        assert r.status_code == 404, r.text
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_NOT_FOUND"
        apply_mock.assert_not_called()

    def test_a_failing_re_read_still_answers_409_rather_than_500(self):
        """Merge-gate review (D3). Losing the claim used to be an INFALLIBLE
        409 — no further I/O between the refusal and the response. G4 put a
        SELECT in that window to tell "already submitted" from "you discarded
        this", and a transient PostgREST failure there must degrade to the
        answer the caller would have got before, not to a 500 on an ordinary
        double-click."""
        attempts = _Attempts(_attempt_row())
        apply_mock = MagicMock()
        real_select = attempts.select
        real_update = attempts.update

        def _submitted_under_the_claim(data, filters=None, **kw):
            attempts.row["completed_at"] = STAMP
            return real_update(data, filters, **kw)

        def _select_that_falls_over(columns="*", filters=None, **kw):
            if "abandoned_at" in columns and "questions_json" not in columns:
                raise RuntimeError("PostgREST said 503")
            return real_select(columns, filters, **kw)

        attempts.update = _submitted_under_the_claim
        attempts.select = _select_that_falls_over

        with (
            patch("routes.quiz.table", side_effect=_factory(attempts)),
            patch("routes.quiz.apply_graph_update", new=apply_mock),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.save_quiz_context"),
        ):
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "B"}],
            })

        assert r.status_code == 409, r.text
        assert r.json()["error"]["code"] == "QUIZ_ATTEMPT_ALREADY_COMPLETED"
        apply_mock.assert_not_called()
