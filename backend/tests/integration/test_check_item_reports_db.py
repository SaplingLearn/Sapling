"""Spec §13 A113 (GitHub #695) and A123, real-DB half: the report and review
functions of migrations 20261108041639_learning_item_quality.sql and
20261108072715_learning_evidence_void.sql against real Postgres — a MagicMock
suite sees the RPC arguments, never what the database decides.

- a (student, question_hash) is recorded once: a repeat is not a first report
  and never counts twice;
- the ITEM_REPORT_QUARANTINE_MIN_REPORTERS-th distinct reporter QUARANTINES
  the course item (A123: never retires it) — and of several reporters racing
  (threads behind a barrier) EXACTLY ONE is told it quarantined it (the
  per-item advisory lock + the database's count);
- the quarantine is A124's HOLD: the database writes `reports_threshold` onto
  every stored row of the course item in the decision's transaction (another
  course's row with the same hash untouched), so every student read drops it
  (list_items / get_check_item) while the admin read keeps it; a later write
  of a row — a rewrite of its flags, a re-draft of the question — cannot drop
  it (the trigger), and a re-draft racing the decision is held either way;
- a staff approval lifts it (the rows are served again, a forged code is
  stripped), and reports newer than it count afresh; a staff retire holds
  every row (`staff_retired`) and is final (an approval never un-retires it);
- the A113 signature (`check_item_report`) still answers a stale backend and
  never retires anything;
- loop_state_store.reported_hashes reads back exactly the student's reports;
- both tables are backend-only (RLS on, no anon/authenticated grant).

Writes through the app helpers (PostgREST rpc/table); reads back over psycopg
(#397). Run inside the flock'd local-stack cycle with RUN_INTEGRATION=1."""

from __future__ import annotations

import os
import threading
import time
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
    assert (first.first, first.reporters, first.quarantine) == (True, 1, False)
    assert (again.first, again.reporters, again.quarantine) == (False, 1, False)
    rows = db_conn.execute(
        "SELECT reason, surface FROM check_item_reports WHERE user_id = %s AND question_hash = %s",
        (user, qh),
    ).fetchall()
    assert rows == [{"reason": "wrong_answer", "surface": "loop"}]  # the first reason stands


def test_the_threshold_quarantines_once_sequentially(db_conn, seeded_user):
    from learning.params import ITEM_REPORT_QUARANTINE_MIN_REPORTERS

    qh = _qh()
    users = [seeded_user() for _ in range(ITEM_REPORT_QUARANTINE_MIN_REPORTERS + 1)]
    outcomes = [_report(u, qh) for u in users]
    assert [o.quarantine for o in outcomes] == [
        n + 1 == ITEM_REPORT_QUARANTINE_MIN_REPORTERS for n in range(len(users))
    ]
    assert _review(db_conn, qh) == {"status": "quarantined", "decided_by": "reports"}


def test_racing_reporters_quarantine_the_item_exactly_once(db_conn, seeded_user):
    qh = _qh()
    users = [seeded_user() for _ in range(6)]
    outcomes = _race(users, qh)
    assert sum(o.quarantine for o in outcomes) == 1
    assert all(o.first for o in outcomes)
    assert sorted(o.reporters for o in outcomes) == list(range(1, len(users) + 1))
    assert _review(db_conn, qh) == {"status": "quarantined", "decided_by": "reports"}


def _item(qh: str, concept: str, *, course: str = COURSE, flags=None) -> str:
    """One stored check item of the course item (course, qh), its text
    encrypted as the app writes it."""
    from db.connection import table
    from services.encryption import encrypt_if_present, encrypt_json

    rid = str(uuid.uuid4())
    table("check_items").insert({
        "id": rid, "course_id": course, "concept_key": concept, "format": "free", "difficulty": 2,
        "prompt": encrypt_if_present(f"Hold fixture {qh} {concept}?"),
        "question_hash": qh,
        "reference_answer": encrypt_if_present("Synthetic fixture. Final answer: fixture."),
        "final_answer": encrypt_if_present("fixture"),
        "rubric_json": encrypt_json([{"id": "r1", "text": "a"}, {"id": "r2", "text": "b"}]),
        "common_wrong_json": encrypt_json([{"key": "w", "text": "a wrong reason"}]),
        "lint_flags": flags,
    })
    return rid


def _flags(db_conn, rid: str):
    return db_conn.execute("SELECT lint_flags FROM check_items WHERE id = %s", (rid,)).fetchone()["lint_flags"]


def _quarantine(seeded_user, qh: str) -> None:
    from learning.params import ITEM_REPORT_QUARANTINE_MIN_REPORTERS

    users = [seeded_user() for _ in range(ITEM_REPORT_QUARANTINE_MIN_REPORTERS)]
    assert [_report(u, qh).quarantine for u in users][-1] is True


def test_a_quarantine_holds_every_row_of_the_course_item_until_an_approval(db_conn, seeded_user):
    from learning.item_reports import decide
    from services.check_item_service import get_check_item, list_items, store_lint_flags

    qh, admin = _qh(), seeded_user()
    linted = _item(qh, "hold-a", flags=["negative_stem"])
    unlinted = _item(qh, "hold-b")  # never linted: NULL
    elsewhere = _item(qh, "hold-a", course="it-other-course", flags=[])
    assert [i.id for i in list_items(COURSE, "hold-a")] == [linted]
    _quarantine(seeded_user, qh)
    assert _flags(db_conn, linted) == ["negative_stem", "reports_threshold"]
    assert _flags(db_conn, unlinted) == ["reports_threshold"]
    assert _flags(db_conn, elsewhere) == []  # another course's question is not this one
    # every student read drops it; the admin read keeps it
    assert list_items(COURSE, "hold-a") == [] and get_check_item(linted) is None
    assert get_check_item(linted, include_held=True).id == linted
    # a later write cannot drop the hold (a re-lint that read it before the quarantine)
    store_lint_flags(["correct_longest"], [linted])
    assert _flags(db_conn, linted) == ["correct_longest", "reports_threshold"]
    # a re-draft of the question under another concept is stored held
    redraft = _item(qh, "hold-c", flags=[])
    assert _flags(db_conn, redraft) == ["reports_threshold"]
    approval = decide(COURSE, qh, "approved", reviewed_by=admin)
    assert (approval.previous, approval.applied) == ("quarantined", True)
    assert _flags(db_conn, linted) == ["correct_longest"] and _flags(db_conn, redraft) == []
    assert [i.id for i in list_items(COURSE, "hold-a")] == [linted]  # served again
    # a forged hold is stripped (only the decision record says quarantined)
    store_lint_flags(["reports_threshold"], [linted])
    assert _flags(db_conn, linted) == []


def test_a_redraft_racing_the_quarantine_is_held_either_way(db_conn, seeded_user):
    """The insert joins the course item under its lock SHARED, the decision
    holds it EXCLUSIVELY: whichever commits first, the new row ends held."""
    import psycopg
    from psycopg.rows import dict_row

    from learning.params import ITEM_REPORT_QUARANTINE_MIN_REPORTERS
    from tests.integration.conftest import _require_local_db_url

    url = os.environ["SUPABASE_DB_URL"]
    _require_local_db_url(url)
    # (a) the decision in flight (uncommitted), then the re-draft: it waits, then reads the decision
    qh = _qh()
    reporters = [seeded_user() for _ in range(ITEM_REPORT_QUARANTINE_MIN_REPORTERS)]
    for u in reporters[:-1]:
        _report(u, qh)
    with psycopg.connect(url, row_factory=dict_row) as decision:
        out = decision.execute(
            "SELECT * FROM check_item_report_quarantine(%s,%s,%s,'unclear','loop',%s)",
            (reporters[-1], COURSE, qh, ITEM_REPORT_QUARANTINE_MIN_REPORTERS),
        ).fetchone()
        assert out["quarantine"] is True
        made: dict = {}
        thread = threading.Thread(target=lambda: made.setdefault("id", _item(qh, "race-a", flags=[])))
        thread.start()
        time.sleep(1.0)
        assert thread.is_alive()  # waiting on the item lock
        decision.commit()
    thread.join(15)
    assert _flags(db_conn, made["id"]) == ["reports_threshold"]
    # (b) the re-draft in flight (uncommitted), then the decision: it waits, then holds the row
    qh = _qh()
    reporters = [seeded_user() for _ in range(ITEM_REPORT_QUARANTINE_MIN_REPORTERS)]
    for u in reporters[:-1]:
        _report(u, qh)
    rid = str(uuid.uuid4())
    with psycopg.connect(url, row_factory=dict_row) as redraft:
        redraft.execute(
            "INSERT INTO check_items (id, course_id, concept_key, format, difficulty, prompt, "
            "reference_answer, rubric_json, common_wrong_json, question_hash, lint_flags) "
            "VALUES (%s,%s,'race-b','free',2,'p','r','[]','[]',%s,%s)",
            (rid, COURSE, qh, ["negative_stem"]),
        )
        decided: dict = {}
        thread = threading.Thread(target=lambda: decided.setdefault("out", _report(reporters[-1], qh)))
        thread.start()
        time.sleep(1.0)
        assert thread.is_alive()  # the decision waits for the insert in flight
        redraft.commit()
    thread.join(15)
    assert decided["out"].quarantine is True
    assert _flags(db_conn, rid) == ["negative_stem", "reports_threshold"]


def test_an_approval_restores_a_quarantine_restarts_the_count_and_never_unretires(db_conn, seeded_user):
    from learning.item_reports import decide
    from learning.params import ITEM_REPORT_QUARANTINE_MIN_REPORTERS

    qh = _qh()
    admin = seeded_user()
    row = _item(qh, "restart")
    first = [seeded_user() for _ in range(ITEM_REPORT_QUARANTINE_MIN_REPORTERS)]
    assert [_report(u, qh).quarantine for u in first][-1] is True
    assert _flags(db_conn, row) == ["reports_threshold"]  # never served while quarantined
    approval = decide(COURSE, qh, "approved", reviewed_by=admin)
    assert (approval.previous, approval.applied) == ("quarantined", True)
    assert _flags(db_conn, row) == []  # restored
    stamped = db_conn.execute(
        "SELECT approved_at FROM check_item_reviews WHERE course_id = %s AND question_hash = %s",
        (COURSE, qh),
    ).fetchone()
    assert stamped["approved_at"] is not None
    later = [seeded_user() for _ in range(ITEM_REPORT_QUARANTINE_MIN_REPORTERS)]
    outcomes = [_report(u, qh) for u in later]
    # the reports before the approval no longer count toward a quarantine
    assert [o.reporters for o in outcomes] == list(range(1, ITEM_REPORT_QUARANTINE_MIN_REPORTERS + 1))
    assert outcomes[-1].quarantine is True
    assert decide(COURSE, qh, "retired", reviewed_by=admin).applied is True
    refused = decide(COURSE, qh, "approved", reviewed_by=admin)
    assert (refused.previous, refused.applied) == ("retired", False)
    assert _review(db_conn, qh) == {"status": "retired", "decided_by": "admin"}
    assert _flags(db_conn, row) == ["staff_retired"]  # held until the void and the delete


def test_the_a113_signature_never_retires(db_conn, seeded_user):
    """A backend deployed before A123 still calls check_item_report: the same
    report, a quarantine at the threshold — and `retire` always false."""
    from db.connection import rpc

    qh = _qh()
    rows = [
        rpc("check_item_report", {
            "p_user_id": seeded_user(), "p_course_id": COURSE, "p_question_hash": qh,
            "p_reason": "unclear", "p_surface": "loop", "p_min_reporters": 2,
        })[0]
        for _ in range(2)
    ]
    assert [r["retire"] for r in rows] == [False, False]
    assert _review(db_conn, qh) == {"status": "quarantined", "decided_by": "reports"}


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
        "check_item_report_quarantine(text,text,text,text,text,integer)",
        "check_item_review_decide(text,text,text,text)",
        "check_item_hold_flags(text[],text)",
    ):
        for role in ("anon", "authenticated"):
            grant = db_conn.execute(
                "SELECT has_function_privilege(%s, %s, 'EXECUTE') AS ok", (role, fn)
            ).fetchone()
            assert grant["ok"] is False
