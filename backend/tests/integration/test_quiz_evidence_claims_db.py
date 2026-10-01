"""PKG-14 final fix round (spec §13 A99, A100), real-DB half: the quiz evidence
claim (migration 20261001060408_learning_quiz_evidence_claims.sql) and the
quiz-ask help row against real Postgres — a MagicMock suite sees the filter
dicts and the Prefer header, never what PostgREST and Postgres do with them.

- a fresh (student, hash) is claimed by exactly one submit, sequentially AND
  under concurrency (8 threads, the INSERT ... ON CONFLICT DO NOTHING);
- a claim inside the rolling window is never renewed; a stale one (older than
  QUIZ_EVIDENCE_WINDOW_HOURS) is renewed by exactly one of 8 concurrent
  submitters (the conditional UPDATE, READ COMMITTED's re-check);
- the claim is per student;
- the table is backend-only (RLS on, no anon/authenticated grant);
- the quiz-ask help row (source 'quiz', RUNG_NO_CREDIT_MIN) passes the ledger's
  CHECK constraints and `max_help_many` reads it back as the floor.

Writes through the app helpers; reads back (and back-dates a claim) over
psycopg (#397). Written for the B6 flock'd cycle (RUN_INTEGRATION=1); listed
in docs/superpowers/plans/learning-loop/tools/pkg14b-b6-cycle.sh."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration

USER = "rich-user-active"
OTHER = "rich-user-new"


def _qh() -> str:
    return f"it-quiz-{uuid.uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _claim(user: str, attempt: str, hashes: list[str], now: datetime | None = None) -> set[str]:
    from routes.quiz import _claim_quiz_evidence

    return _claim_quiz_evidence(user, attempt, hashes, now or _now())


def _race(hashes: list[str], n: int = 8) -> list[set[str]]:
    barrier = threading.Barrier(n)
    results: list[set[str] | BaseException] = [set()] * n

    def run(i: int) -> None:
        barrier.wait()
        try:
            results[i] = _claim(USER, f"attempt-{i}", hashes)
        except BaseException as exc:  # noqa: BLE001 — surfaced below
            results[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for r in results:
        if isinstance(r, BaseException):
            raise r
    return results  # type: ignore[return-value]


def test_a_fresh_hash_is_claimed_once(db_conn):
    a, b = _qh(), _qh()
    assert _claim(USER, "attempt-1", [a, b]) == {a, b}
    assert _claim(USER, "attempt-2", [a, b]) == set()
    rows = db_conn.execute(
        "SELECT question_hash, attempt_id FROM quiz_evidence_claims WHERE user_id = %s "
        "AND question_hash = ANY(%s) ORDER BY question_hash",
        (USER, [a, b]),
    ).fetchall()
    assert {r["attempt_id"] for r in rows} == {"attempt-1"} and len(rows) == 2


def test_concurrent_submits_sharing_a_hash_claim_it_exactly_once(db_conn):
    hashes = [_qh(), _qh(), _qh()]
    results = _race(hashes)
    for qh in hashes:
        assert sum(qh in r for r in results) == 1, qh


def test_a_claim_inside_the_window_holds_and_a_stale_one_is_renewed_once(db_conn):
    from routes.quiz import QUIZ_EVIDENCE_WINDOW_HOURS

    held, stale = _qh(), _qh()
    assert _claim(USER, "attempt-0", [held, stale]) == {held, stale}
    db_conn.execute(
        "UPDATE quiz_evidence_claims SET claimed_at = %s WHERE user_id = %s AND question_hash = %s",
        (_now() - timedelta(hours=QUIZ_EVIDENCE_WINDOW_HOURS - 1), USER, held),
    )
    db_conn.execute(
        "UPDATE quiz_evidence_claims SET claimed_at = %s WHERE user_id = %s AND question_hash = %s",
        (_now() - timedelta(hours=QUIZ_EVIDENCE_WINDOW_HOURS + 1), USER, stale),
    )
    results = _race([held, stale])
    assert sum(held in r for r in results) == 0
    assert sum(stale in r for r in results) == 1
    row = db_conn.execute(
        "SELECT claimed_at FROM quiz_evidence_claims WHERE user_id = %s AND question_hash = %s",
        (USER, stale),
    ).fetchone()
    assert row["claimed_at"] > _now() - timedelta(minutes=5)


def test_the_claim_is_per_student(db_conn):
    qh = _qh()
    assert _claim(USER, "attempt-a", [qh]) == {qh}
    assert _claim(OTHER, "attempt-b", [qh]) == {qh}


def test_the_claims_table_is_backend_only(db_conn):
    row = db_conn.execute(
        "SELECT relrowsecurity FROM pg_class WHERE relname = 'quiz_evidence_claims'"
    ).fetchone()
    assert row["relrowsecurity"] is True
    for role in ("anon", "authenticated"):
        exists = db_conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        if not exists:
            continue
        grant = db_conn.execute(
            "SELECT has_table_privilege(%s, 'quiz_evidence_claims', 'SELECT') AS ok", (role,)
        ).fetchone()
        assert grant["ok"] is False, role


def test_the_quiz_ask_help_row_is_a_valid_ledger_row_and_floors_the_quiz(db_conn):
    from learning import help_ledger
    from learning.params import RUNG_NO_CREDIT_MIN
    from services.quiz_ask import QUIZ_ASK_HELP_RUNG, QUIZ_ASK_SOURCE

    asked, other = _qh(), _qh()
    help_ledger.record_help(USER, asked, QUIZ_ASK_HELP_RUNG, source=QUIZ_ASK_SOURCE, session_id="s-quiz")
    row = db_conn.execute(
        "SELECT kind, rung, source, session_id FROM learning_reveals WHERE user_id = %s "
        "AND question_hash = %s",
        (USER, asked),
    ).fetchone()
    assert (row["kind"], row["rung"], row["source"], row["session_id"]) == (
        "help",
        RUNG_NO_CREDIT_MIN,
        "quiz",
        "s-quiz",
    )
    assert help_ledger.max_help_many(USER, [asked, other]) == {asked: RUNG_NO_CREDIT_MIN, other: 0}
    assert help_ledger.max_help_many(OTHER, [asked]) == {asked: 0}
