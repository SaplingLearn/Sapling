"""Spec §13 A126, real-DB half: the SQL of 20261108093359_learning_posttest_outcomes.sql.

The `posttest_anchors` function (each concept's FIRST graded evidence time,
keyset-paged), the skip record, the display stamp, the answer's telemetry and
the CHECK constraints can only be shown against real Postgres — a MagicMock
suite sees the filter dict and the RPC name, never what PostgREST and plpgsql
do with them. Writes go through the app layer (routes/learn_loop.py helpers,
learning/posttest_store.py); raw SQL only seeds the journal rows a graded
answer would have written and reads back over psycopg (#397)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from learning.params import POSTTEST_POSE_TTL_HOURS, POSTTEST_WINDOWS_DAYS

pytestmark = pytest.mark.integration

USER = "rich-user-active"
OTHER = "rich-user-second"
COURSE = "rich-course-cs101"
W1, W2 = POSTTEST_WINDOWS_DAYS
T0 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


def _now():
    return datetime.now(timezone.utc)


def _node(db_conn, user=USER, *, course=COURSE) -> str:
    node = f"it-a126-{uuid.uuid4().hex[:10]}"
    db_conn.execute(
        "INSERT INTO graph_nodes (id, user_id, course_id, concept_name) VALUES (%s, %s, %s, %s)",
        (node, user, course, f"A126 concept {node}"),
    )
    return node


def _event(db_conn, node, at, *, event_type="evidence", qh=None):
    db_conn.execute(
        "INSERT INTO node_mastery_events (node_id, delta, event_type, question_hash, created_at) "
        "VALUES (%s, 0, %s, %s, %s)",
        (node, event_type, qh, at),
    )


def _anchors(user=None, **kw) -> dict[str, dict]:
    from learning.posttest_store import posttest_anchors

    rows, truncated = posttest_anchors(user_id=user, **kw)
    assert truncated is False
    return {r["node_id"]: r for r in rows}


def _at(raw) -> datetime:
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


# ── posttest_anchors ─────────────────────────────────────────────────────────


def test_an_anchor_is_the_nodes_first_evidence_time(db_conn):
    a, b = _node(db_conn), _node(db_conn)
    no_course = _node(db_conn, course=None)
    theirs = _node(db_conn, OTHER)
    _event(db_conn, a, T0 - timedelta(days=3), event_type="mastery")  # not evidence: never an anchor
    _event(db_conn, a, T0 + timedelta(days=2), qh="q-late")
    _event(db_conn, a, T0, qh="q-first")
    _event(db_conn, b, T0 + timedelta(days=1))
    _event(db_conn, no_course, T0)  # a node with no course is never posed
    _event(db_conn, theirs, T0)
    mine = _anchors(USER)
    assert _at(mine[a]["anchor_at"]) == T0
    assert _at(mine[b]["anchor_at"]) == T0 + timedelta(days=1)
    assert mine[a]["course_id"] == COURSE and mine[a]["user_id"] == USER
    assert mine[a]["concept_name"] == f"A126 concept {a}"
    assert no_course not in mine and theirs not in mine
    everyone = _anchors()
    assert {a, b, theirs} <= set(everyone) and no_course not in everyone


def _evidence_id(db_conn, node, at, *, qh) -> str:
    return db_conn.execute(
        "INSERT INTO node_mastery_events (node_id, delta, event_type, question_hash, created_at) "
        "VALUES (%s, 0, 'evidence', %s, %s) RETURNING id",
        (node, qh, at),
    ).fetchone()["id"]


def _void(db_conn, event_id, node, at):
    """The void record's row for a journal row (spec §13 A123), as the single
    graph writer's void transaction writes it (raw SQL: the seed half)."""
    db_conn.execute(
        "INSERT INTO learning_evidence_voids (event_id, user_id, node_id, course_id, question_hash, "
        "check_item_id, event_created_at, reason, operation_id) "
        "VALUES (%s, %s, %s, %s, 'q-retired', 'item-retired', %s, 'item_retired', %s)",
        (event_id, USER, node, COURSE, at, str(uuid.uuid4())),
    )


def test_a_void_row_never_anchors(db_conn):
    """20261108105254 (A123 × A126): a row the void record names is no evidence,
    so a concept's anchor is its first VALID evidence — evidence_spans' rule —
    in the student branch and in the all-students branch, and a concept whose
    every row is void has no anchor."""
    node, all_void = _node(db_conn), _node(db_conn)
    _void(db_conn, _evidence_id(db_conn, node, T0, qh="q-retired"), node, T0)
    _event(db_conn, node, T0 + timedelta(days=1), qh="q-fine")
    _void(db_conn, _evidence_id(db_conn, all_void, T0, qh="q-retired"), all_void, T0)
    mine = _anchors(USER)
    assert _at(mine[node]["anchor_at"]) == T0 + timedelta(days=1)
    assert all_void not in mine
    everyone = _anchors()
    assert _at(everyone[node]["anchor_at"]) == T0 + timedelta(days=1)
    assert all_void not in everyone


def test_the_anchor_range_is_inclusive(db_conn):
    inside, edge, outside = _node(db_conn), _node(db_conn), _node(db_conn)
    _event(db_conn, inside, T0 + timedelta(hours=1))
    _event(db_conn, edge, T0)
    _event(db_conn, outside, T0 - timedelta(microseconds=1))
    found = _anchors(USER, anchor_from=T0, anchor_to=T0 + timedelta(days=1))
    assert inside in found and edge in found and outside not in found
    # the all-students branch filters the same way
    found = _anchors(anchor_from=T0, anchor_to=T0 + timedelta(days=1))
    assert inside in found and edge in found and outside not in found


def test_the_keyset_pages_cover_every_node_once(db_conn, monkeypatch):
    from learning import posttest_store

    nodes = sorted(_node(db_conn) for _ in range(5))
    for node in nodes:
        _event(db_conn, node, T0)
    monkeypatch.setattr(posttest_store, "_ANCHORS_PAGE", 2)
    rows, _ = posttest_store.posttest_anchors(user_id=USER)
    ids = [r["node_id"] for r in rows]
    assert ids == sorted(ids) and len(ids) == len(set(ids))
    assert set(nodes) <= set(ids)


def test_the_page_size_is_clamped_to_postgrest_max_rows(db_conn):
    for _ in range(3):
        _event(db_conn, _node(db_conn), T0)
    from db.connection import rpc

    args = {"p_user_id": USER, "p_anchor_from": None, "p_anchor_to": None, "p_after_node_id": None}
    assert len(rpc("posttest_anchors", {**args, "p_limit": 0})) == 1  # at least one
    assert len(rpc("posttest_anchors", {**args, "p_limit": 10**6})) <= 1000


# ── the skip record ──────────────────────────────────────────────────────────


def _skip(node, reason, window=W1):
    return {"user_id": USER, "node_id": node, "course_id": COURSE, "window_days": window,
            "reason": reason, "skipped_at": _now().isoformat()}


def test_a_skip_is_one_row_per_window_with_the_latest_reason(db_conn):
    from routes import learn_loop

    node = _node(db_conn)
    learn_loop._record_skips([_skip(node, "exhausted")])
    learn_loop._record_skips([_skip(node, "reported"), _skip(node, "no_items", W2)])
    rows = db_conn.execute(
        "SELECT window_days, reason FROM posttest_skips WHERE user_id = %s AND node_id = %s "
        "ORDER BY window_days",
        (USER, node),
    ).fetchall()
    assert [(r["window_days"], r["reason"]) for r in rows] == [(W1, "reported"), (W2, "no_items")]


def test_an_unknown_skip_reason_is_refused_and_never_fails_the_start(db_conn):
    from routes import learn_loop

    node = _node(db_conn)
    learn_loop._record_skips([_skip(node, "bored")])  # the CHECK refuses it; the helper logs
    assert db_conn.execute(
        "SELECT count(*) AS n FROM posttest_skips WHERE node_id = %s", (node,)
    ).fetchone()["n"] == 0


# ── the display stamp and the answer's telemetry ─────────────────────────────


def _open_pose(node, *, qh="q1", posed=None, window=W1):
    """Open (or renew) a pose with the row /posttest/start writes
    (`learn_loop._new_pose`): every answer column NULL, the outcome (A112) as
    well as what the answer reports (A126), so a renewal resets them all."""
    from routes import learn_loop

    at = posed or _now()
    choice = SimpleNamespace(
        item=SimpleNamespace(question_hash=qh), match="difficulty", source="reserve"
    )
    span = SimpleNamespace(first_id=None, first_at=at - timedelta(days=window), last_at=at - timedelta(days=1))
    learn_loop._record_poses([learn_loop._new_pose(USER, COURSE, node, window, choice, span, at)])


def _pose(db_conn, node, window=W1):
    return db_conn.execute(
        "SELECT * FROM posttest_poses WHERE user_id = %s AND node_id = %s AND window_days = %s",
        (USER, node, window),
    ).fetchone()


def test_the_first_display_is_stamped_once(db_conn):
    from routes import learn_loop

    node = _node(db_conn)
    _open_pose(node)
    first = _now()
    assert learn_loop._stamp_served(USER, node, "q1", first) is True
    assert learn_loop._stamp_served(USER, node, "q1", first + timedelta(minutes=5)) is False
    assert _pose(db_conn, node)["served_at"] == first
    assert learn_loop._stamp_served(USER, node, "another-item", first) is False


def test_an_expired_or_answered_pose_is_never_stamped(db_conn):
    from routes import learn_loop

    now = _now()
    old, done = _node(db_conn), _node(db_conn)
    _open_pose(old, posed=now - timedelta(hours=POSTTEST_POSE_TTL_HOURS, seconds=1))
    _open_pose(done)
    assert learn_loop._claim_pose(USER, done, "q1", "c", now) is not None
    assert learn_loop._answer_pose(USER, done, "c", now, correct=True, max_rung=0) is True
    assert learn_loop._stamp_served(USER, old, "q1", now) is False
    assert learn_loop._stamp_served(USER, done, "q1", now) is False


def test_the_answer_records_its_latency_and_visibility(db_conn):
    from routes import learn_loop

    node = _node(db_conn)
    _open_pose(node)
    now = _now()
    learn_loop._stamp_served(USER, node, "q1", now - timedelta(seconds=40))
    assert learn_loop._claim_pose(USER, node, "q1", "c", now) is not None
    assert learn_loop._answer_pose(
        USER, node, "c", now, correct=False, max_rung=0, latency_s=40.0, hidden_count=2, hidden_s=7.5
    ) is True
    row = _pose(db_conn, node)
    assert (row["answer_latency_s"], row["hidden_count"], row["hidden_s"]) == (40.0, 2, 7.5)
    assert (row["item_match"], row["item_source"]) == ("difficulty", "reserve")
    _open_pose(node, qh="q2")  # a renewal resets every answer column (A89/A93)
    row = _pose(db_conn, node)
    assert row["served_at"] is None and row["answer_latency_s"] is None and row["hidden_count"] is None


@pytest.mark.parametrize(
    "assignment",
    [
        "hidden_count = 1, hidden_s = 1",  # telemetry on an unanswered pose
        "item_match = 'close'",
        "item_source = 'anywhere'",
    ],
)
def test_the_checks_refuse_an_impossible_open_pose(db_conn, assignment):
    node = _node(db_conn)
    _open_pose(node)
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(f"UPDATE posttest_poses SET {assignment} WHERE node_id = %s", (node,))


@pytest.mark.parametrize(
    "assignment",
    [
        "hidden_count = 1",  # both or neither
        "hidden_s = -1, hidden_count = 0",
        "answer_latency_s = 3",  # a latency needs the display it is measured from
        "answer_latency_s = -1, served_at = now()",
    ],
)
def test_the_checks_refuse_impossible_answer_telemetry(db_conn, assignment):
    from routes import learn_loop

    node = _node(db_conn)
    _open_pose(node)
    now = _now()
    assert learn_loop._claim_pose(USER, node, "q1", "c", now) is not None
    assert learn_loop._answer_pose(USER, node, "c", now, correct=True, max_rung=0) is True
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(f"UPDATE posttest_poses SET {assignment} WHERE node_id = %s", (node,))


# ── the migration ────────────────────────────────────────────────────────────


def test_the_migration_is_idempotent(db_conn):
    from tests.integration.conftest import _require_local_db_url

    url = (os.getenv("SUPABASE_DB_URL") or "").strip()
    _require_local_db_url(url)
    (mig,) = sorted(
        (Path(__file__).resolve().parents[2] / "db" / "migrations").glob(
            "*_learning_posttest_outcomes.sql"
        )
    )
    from psycopg.rows import dict_row

    with psycopg.connect(url, row_factory=dict_row) as conn:
        try:
            conn.execute(mig.read_text(encoding="utf-8"))
            conn.execute(mig.read_text(encoding="utf-8"))
        finally:
            conn.rollback()


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_client_roles_are_denied(db_conn, role):
    try:
        db_conn.execute(f"SET ROLE {role}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute("SELECT * FROM posttest_skips LIMIT 1")
    finally:
        db_conn.execute("RESET ROLE")
    try:
        db_conn.execute(f"SET ROLE {role}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute("SELECT * FROM posttest_anchors(NULL, NULL, NULL, NULL, 1)")
    finally:
        db_conn.execute("RESET ROLE")
