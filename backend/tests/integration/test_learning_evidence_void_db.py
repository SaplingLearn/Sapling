"""Spec §13 A123, real-DB half: void evidence and the reversible quarantine,
against the SQL of migration 20261108072715_learning_evidence_void.sql.

- a staff retire voids every student's evidence graded against the item (one
  append-only void row per evidence id; the journal untouched) and recomputes
  their state through the single graph writer: every learner_state row and
  graph mirror equals what the same history WITHOUT that item's evidence
  writes (a second student answers it, at the same observation times);
- a re-run writes nothing (no version moves); a void of an item staff have not
  retired is refused;
- the race: a grade whose commit is in flight (its transaction open, the
  item's shared lock held) when staff retire the item makes the decision wait,
  and the sweep then voids its row — no non-void row is left; a grade arriving
  after the decision is refused and writes nothing;
- a misconception every attempt of which was graded against the retired item
  is closed (reason 'evidence_void'); one with another live attempt stays
  open; an attempt recorded after the retire is refused;
- the void record is append-only and backend-only.

Writes go through the app (apply_graph_update, the item_reports functions,
check_item_service.retire_course_item, misconceptions.record); independent
psycopg reads assert the result (#397). The race holds the app's OWN commit
plan open on a psycopg transaction — PostgREST commits each call, so no other
way interleaves a decision with an uncommitted grade. Run inside the flock'd
local-stack cycle with RUN_INTEGRATION=1."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.integration.conftest import COURSE_CS, USER_ACTIVE, USER_SECOND
from tests.integration.test_learning_goals_db import _node

pytestmark = pytest.mark.integration

STATE_COLUMNS = (
    "p_known", "n_strong_unassisted", "streak_unassisted", "max_streak_unassisted", "opps",
    "fsrs_d", "fsrs_s", "fsrs_last_review_at", "fsrs_due_at", "last_evidence_at", "updated_at",
)
T0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=60)


def _qh(label: str) -> str:
    return f"it-void-{label}-{uuid.uuid4().hex[:10]}"


def _graph(owner: str) -> dict[str, str]:
    """Three concepts on a prerequisite chain a → b → c, owned by `owner`."""
    from db.connection import table

    nodes = {k: _node(f"Void {k}", owner=owner) for k in ("a", "b", "c")}
    for prereq, dependent in (("a", "b"), ("b", "c")):
        table("graph_edges").insert({
            "user_id": owner, "source_node_id": nodes[prereq], "target_node_id": nodes[dependent],
            "relationship_type": "prerequisite",
        })
    return nodes


def _history(bad: str, good: str) -> list[tuple[int, str, str, bool]]:
    """(hours after T0, concept, item hash, correct) — the bad item's grades
    sit between valid ones, on a concept whose neighbours they propagate to."""
    return [
        (1, "b", good, True),
        (5, "b", bad, True),  # propagates to a (correct → its prerequisite)
        (30, "a", good + "-2", False),  # propagates to b (incorrect → its dependent)
        (80, "b", bad, False),  # the same broken item, re-asked: void too
        (200, "c", good + "-3", True),
    ]


def _grade(owner: str, nodes: dict, hours: int, concept: str, qh: str, correct: bool):
    from services.graph_service import apply_graph_update

    return apply_graph_update(owner, {"evidence": [{
        "node_id": nodes[concept], "channel": "free_response", "correct": correct,
        "session_id": f"it-void-session-{owner}", "question_hash": qh, "check_item_id": f"ci-{qh}",
        "observed_at": (T0 + timedelta(hours=hours)).isoformat(),
    }]}, COURSE_CS)


def _states(db_conn, owner: str, nodes: dict) -> dict:
    out = {}
    for key, node in nodes.items():
        row = db_conn.execute(
            f"SELECT {','.join(STATE_COLUMNS)}, evidence_version FROM learner_state "
            "WHERE user_id = %s AND node_id = %s", (owner, node),
        ).fetchone()
        mirror = db_conn.execute(
            "SELECT mastery_score, mastery_tier FROM graph_nodes WHERE id = %s", (node,)
        ).fetchone()
        out[key] = (row, mirror)
    return out


def _retire(qh: str):
    from learning.item_reports import decide
    from services.check_item_service import retire_course_item

    decide(COURSE_CS, qh, "retired", reviewed_by=None)
    return retire_course_item(COURSE_CS, qh)


def test_a_staff_retire_voids_the_items_evidence_and_recomputes_a_history_without_it(db_conn):
    bad, good = _qh("bad"), _qh("good")
    mine, reference = _graph(USER_ACTIVE), _graph(USER_SECOND)
    for hours, concept, qh, correct in _history(bad, good):
        _grade(USER_ACTIVE, mine, hours, concept, qh, correct)
        if qh != bad:  # the reference never answered the broken item
            _grade(USER_SECOND, reference, hours, concept, qh, correct)
    journal = db_conn.execute(
        "SELECT * FROM node_mastery_events WHERE node_id = ANY(%s) ORDER BY id", (list(mine.values()),)
    ).fetchall()
    assert all(r["retention"] == 0.9 and r["propagated_to"] is not None for r in journal)

    outcome = _retire(bad)
    assert (outcome.students, outcome.voided) == (1, 2)

    assert db_conn.execute(  # append-only: the journal is exactly as written
        "SELECT * FROM node_mastery_events WHERE node_id = ANY(%s) ORDER BY id", (list(mine.values()),)
    ).fetchall() == journal
    voids = db_conn.execute(
        "SELECT v.*, e.question_hash AS graded FROM learning_evidence_voids v "
        "JOIN node_mastery_events e ON e.id = v.event_id WHERE v.user_id = %s", (USER_ACTIVE,),
    ).fetchall()
    assert len(voids) == 2 and {v["graded"] for v in voids} == {bad}
    assert {v["reason"] for v in voids} == {"item_retired"} and len({v["operation_id"] for v in voids}) == 1
    got, want = _states(db_conn, USER_ACTIVE, mine), _states(db_conn, USER_SECOND, reference)
    for key in mine:
        (row, mirror), (ref_row, ref_mirror) = got[key], want[key]
        assert {c: row[c] for c in STATE_COLUMNS} == {c: ref_row[c] for c in STATE_COLUMNS}, key
        assert mirror == ref_mirror, key


def test_re_running_a_void_writes_nothing_and_an_unretired_item_is_refused(db_conn):
    from learning.evidence_transaction import EvidenceVoidRefused, void_pending
    from services.graph_service import apply_graph_update

    bad, good = _qh("bad"), _qh("good")
    mine = _graph(USER_ACTIVE)
    for hours, concept, qh, correct in _history(bad, good):
        _grade(USER_ACTIVE, mine, hours, concept, qh, correct)
    with pytest.raises(EvidenceVoidRefused):  # quarantined, reported or nothing: no void
        apply_graph_update(USER_ACTIVE, {"void_evidence": {"question_hash": bad}}, COURSE_CS)
    assert db_conn.execute("SELECT count(*) AS n FROM learning_evidence_voids").fetchone()["n"] == 0

    _retire(bad)
    before = _states(db_conn, USER_ACTIVE, mine)
    assert void_pending(COURSE_CS, bad) == {}
    again = _retire(bad)  # the admin retires again: nothing pending, nothing written
    assert (again.students, again.voided) == (0, 0)
    apply_graph_update(USER_ACTIVE, {"void_evidence": {"question_hash": bad}}, COURSE_CS)
    assert _states(db_conn, USER_ACTIVE, mine) == before  # versions included: nothing moved


def test_a_retire_while_a_grade_is_in_flight_leaves_no_non_void_row(db_conn, monkeypatch):
    """The grade's commit runs to its end inside an open transaction (the
    item's SHARED lock held); staff retire the item meanwhile: the decision
    WAITS for it. Once both commit, the sweep voids the row. A grade arriving
    after the decision is refused under the same lock and writes nothing."""
    import os

    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb

    from learning import evidence_transaction as tx
    from learning.evidence_transaction import EvidenceItemRetired
    from learning.item_reports import decide
    from services.check_item_service import retire_course_item

    qh = _qh("race")
    mine = _graph(USER_ACTIVE)
    held = psycopg.connect(os.environ["SUPABASE_DB_URL"].strip(), row_factory=dict_row)
    decided: dict = {}
    real = tx.rpc

    def decider():
        started = time.monotonic()
        decide(COURSE_CS, qh, "retired", reviewed_by=None)
        decided["after"] = time.monotonic() - started

    def in_flight(name, args):
        if name != "learning_evidence_commit":
            return real(name, args)
        call = ", ".join(f"{k} := %({k})s" for k in args)
        values = {k: Jsonb(v) if isinstance(v, (dict, list)) else v for k, v in args.items()}
        out = held.execute(f"SELECT {name}({call}) AS out", values).fetchone()["out"]
        thread = threading.Thread(target=decider)
        thread.start()
        time.sleep(1.0)
        assert "after" not in decided, "the retire did not wait for the grade in flight"
        held.commit()
        thread.join(10)
        return out

    monkeypatch.setattr(tx, "rpc", in_flight)
    _grade(USER_ACTIVE, mine, 1, "b", qh, True)
    monkeypatch.setattr(tx, "rpc", real)
    held.close()
    assert decided["after"] >= 0.9
    retire_course_item(COURSE_CS, qh)
    left = db_conn.execute(
        "SELECT count(*) AS n FROM node_mastery_events e JOIN graph_nodes g ON g.id = e.node_id "
        "WHERE g.course_id = %s AND e.question_hash = %s "
        "AND NOT EXISTS (SELECT 1 FROM learning_evidence_voids v WHERE v.event_id = e.id)",
        (COURSE_CS, qh),
    ).fetchone()["n"]
    assert left == 0
    rows = db_conn.execute("SELECT count(*) AS n FROM node_mastery_events").fetchone()["n"]
    with pytest.raises(EvidenceItemRetired):
        _grade(USER_ACTIVE, mine, 2, "a", qh, True)
    assert db_conn.execute("SELECT count(*) AS n FROM node_mastery_events").fetchone()["n"] == rows


def test_a_misconception_whose_only_support_is_void_is_closed(db_conn):
    from learning.misconceptions import record

    bad, good = _qh("bad"), _qh("good")
    mine = _graph(USER_ACTIVE)
    _grade(USER_ACTIVE, mine, 1, "c", bad, False)
    _grade(USER_ACTIVE, mine, 2, "c", good, False)
    record(USER_ACTIVE, mine["c"], f"ci-{bad}", "k_only_bad", None, question_hash=bad)
    record(USER_ACTIVE, mine["c"], f"ci-{bad}", "k_mixed", None, question_hash=bad)
    record(USER_ACTIVE, mine["c"], f"ci-{good}", "k_mixed", None, question_hash=good)
    _retire(bad)
    assert record(USER_ACTIVE, mine["c"], f"ci-{bad}", "k_after", None, question_hash=bad) == {}
    rows = {
        r["wrong_key"]: (r["resolved_at"] is not None, r["resolved_reason"])
        for r in db_conn.execute(
            "SELECT wrong_key, resolved_at, resolved_reason FROM misconceptions WHERE user_id = %s",
            (USER_ACTIVE,),
        ).fetchall()
    }
    assert rows == {"k_only_bad": (True, "evidence_void"), "k_mixed": (False, None)}
    attempts = db_conn.execute("SELECT count(*) AS n FROM misconception_attempts").fetchone()["n"]
    assert attempts == 3  # one per increment; the refused attempt recorded nothing


def test_the_void_record_is_append_only_and_backend_only(db_conn):
    import psycopg

    bad = _qh("bad")
    mine = _graph(USER_ACTIVE)
    _grade(USER_ACTIVE, mine, 1, "a", bad, True)
    _retire(bad)
    with pytest.raises(psycopg.errors.RaiseException):
        db_conn.execute("UPDATE learning_evidence_voids SET reason = 'item_retired'")
    for name in ("learning_evidence_voids", "misconception_attempts"):
        row = db_conn.execute(
            "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass", (f"public.{name}",)
        ).fetchone()
        assert row["relrowsecurity"] is True
        for role in ("anon", "authenticated"):
            assert db_conn.execute(
                "SELECT has_table_privilege(%s, %s, 'SELECT') AS ok", (role, f"public.{name}")
            ).fetchone()["ok"] is False
    # 20261108115157: the backend holds SELECT and INSERT only on both records.
    # Supabase's default privileges grant service_role ALL on a new table, so
    # the A123 GRANT alone left UPDATE, DELETE and TRUNCATE in place.
    for name in ("learning_evidence_voids", "misconception_attempts"):
        for privilege, allowed in (
            ("SELECT", True), ("INSERT", True),
            ("UPDATE", False), ("DELETE", False), ("TRUNCATE", False),
        ):
            assert db_conn.execute(
                "SELECT has_table_privilege('service_role', %s, %s) AS ok",
                (f"public.{name}", privilege),
            ).fetchone()["ok"] is allowed, (name, privilege)
    for fn in (
        "learning_evidence_void_pending(text,text)",
        "learning_evidence_void_snapshot(text,text,text)",
        "learning_evidence_void_commit(text,text,text,uuid,jsonb)",
    ):
        for role in ("anon", "authenticated"):
            assert db_conn.execute(
                "SELECT has_function_privilege(%s, %s, 'EXECUTE') AS ok", (role, fn)
            ).fetchone()["ok"] is False
