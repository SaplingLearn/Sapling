"""Spec §13 A113 (GitHub #695), real-DB half: the report and review functions
of migration 20261108041639_learning_item_quality.sql against real Postgres —
a MagicMock suite sees the RPC arguments, never what the database decides.

- a (student, question_hash) is recorded once: a repeat is not a first report
  and never counts twice;
- the ITEM_REPORT_RETIRE_MIN_REPORTERS-th distinct reporter retires the course
  item — and of several reporters racing (threads behind a barrier) EXACTLY ONE
  is told to retire it (the per-item advisory lock + the database's count);
- a report newer than an admin's approval counts afresh, and an approval never
  un-retires a retired item;
- loop_state_store.reported_hashes reads back exactly the student's reports;
- both tables are backend-only (RLS on, no anon/authenticated grant).

Writes through the app helpers (PostgREST rpc/table); reads back over psycopg
(#397). Run inside the flock'd local-stack cycle with RUN_INTEGRATION=1."""

from __future__ import annotations

import threading
import uuid

import pytest

pytestmark = pytest.mark.integration

COURSE = "rich-course-cs101"


def _qh() -> str:
    return f"it-report-{uuid.uuid4().hex[:12]}"


def _report(user: str, qh: str, reason: str = "wrong_answer"):
    from learning.item_reports import record_report

    return record_report(user, COURSE, qh, reason=reason, surface="loop")


def _race(users: list[str], qh: str):
    barrier = threading.Barrier(len(users))
    results: list = [None] * len(users)

    def run(i: int) -> None:
        barrier.wait()
        try:
            results[i] = _report(users[i], qh)
        except BaseException as exc:  # noqa: BLE001 — surfaced below
            results[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(users))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for r in results:
        if isinstance(r, BaseException):
            raise r
    return results


def _review(db_conn, qh: str):
    return db_conn.execute(
        "SELECT status, decided_by FROM check_item_reviews WHERE course_id = %s AND question_hash = %s",
        (COURSE, qh),
    ).fetchone()


def test_a_report_is_recorded_once(db_conn, seeded_user):
    user, qh = seeded_user(), _qh()
    first = _report(user, qh)
    again = _report(user, qh, reason="unclear")
    assert (first.first, first.reporters, first.retire) == (True, 1, False)
    assert (again.first, again.reporters, again.retire) == (False, 1, False)
    rows = db_conn.execute(
        "SELECT reason, surface FROM check_item_reports WHERE user_id = %s AND question_hash = %s",
        (user, qh),
    ).fetchall()
    assert rows == [{"reason": "wrong_answer", "surface": "loop"}]  # the first reason stands


def test_the_threshold_retires_once_sequentially(db_conn, seeded_user):
    from learning.params import ITEM_REPORT_RETIRE_MIN_REPORTERS

    qh = _qh()
    users = [seeded_user() for _ in range(ITEM_REPORT_RETIRE_MIN_REPORTERS + 1)]
    outcomes = [_report(u, qh) for u in users]
    assert [o.retire for o in outcomes] == [
        n + 1 == ITEM_REPORT_RETIRE_MIN_REPORTERS for n in range(len(users))
    ]
    assert _review(db_conn, qh) == {"status": "retired", "decided_by": "reports"}


def test_racing_reporters_retire_the_item_exactly_once(db_conn, seeded_user):
    qh = _qh()
    users = [seeded_user() for _ in range(6)]
    outcomes = _race(users, qh)
    assert sum(o.retire for o in outcomes) == 1
    assert all(o.first for o in outcomes)
    assert sorted(o.reporters for o in outcomes) == list(range(1, len(users) + 1))
    assert _review(db_conn, qh) == {"status": "retired", "decided_by": "reports"}


def test_an_approval_restarts_the_count_and_never_unretires(db_conn, seeded_user):
    from learning.item_reports import decide
    from learning.params import ITEM_REPORT_RETIRE_MIN_REPORTERS

    qh = _qh()
    admin = seeded_user()
    first = seeded_user()
    assert _report(first, qh).retire is False
    assert decide(COURSE, qh, "approved", reviewed_by=admin).applied is True
    later = [seeded_user() for _ in range(ITEM_REPORT_RETIRE_MIN_REPORTERS)]
    outcomes = [_report(u, qh) for u in later]
    # the report before the approval no longer counts toward retirement
    assert [o.reporters for o in outcomes] == list(range(1, ITEM_REPORT_RETIRE_MIN_REPORTERS + 1))
    assert outcomes[-1].retire is True
    refused = decide(COURSE, qh, "approved", reviewed_by=admin)
    assert (refused.previous, refused.applied) == ("retired", False)
    assert _review(db_conn, qh)["status"] == "retired"


def test_reported_hashes_reads_the_students_own_reports(seeded_user):
    from learning.loop_state_store import reported_hashes

    mine, theirs = seeded_user(), seeded_user()
    a, b = _qh(), _qh()
    _report(mine, a)
    _report(theirs, b)
    assert reported_hashes(mine) == {a}


def test_the_tables_are_backend_only(db_conn):
    for name in ("check_item_reports", "check_item_reviews"):
        row = db_conn.execute(
            "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass", (f"public.{name}",)
        ).fetchone()
        assert row["relrowsecurity"] is True
        for role in ("anon", "authenticated"):
            grant = db_conn.execute(
                "SELECT has_table_privilege(%s, %s, 'SELECT') AS ok", (role, f"public.{name}")
            ).fetchone()
            assert grant["ok"] is False
    for fn in (
        "check_item_report(text,text,text,text,text,integer)",
        "check_item_review_decide(text,text,text,text)",
    ):
        for role in ("anon", "authenticated"):
            grant = db_conn.execute(
                "SELECT has_function_privilege(%s, %s, 'EXECUTE') AS ok", (role, fn)
            ).fetchone()
            assert grant["ok"] is False
