"""PKG-14 re-review round, real-DB half of the post-test pose (spec §13 A87,
A89): the claim is ONE conditional PostgREST UPDATE, so its or-filter, its
ISO-Z stale cutoff, the TTL filter and the concurrent single-winner property
can only be shown against real Postgres — a MagicMock suite sees the filter
dict, never what PostgREST does with it. Writes go through the route helpers
(the app layer); assertions read back over psycopg (#397). Since A112 a node
has one pose row per fixed follow-up window."""

import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from learning.params import POSTTEST_WINDOWS_DAYS
import services.loop.posttest_poses

pytestmark = pytest.mark.integration

USER = "rich-user-active"
COURSE = "it-course-posttest"
W1, W2 = POSTTEST_WINDOWS_DAYS


def _now():
    return datetime.now(timezone.utc)


def _open_pose(node, *, qh="q1", posed=None, window=W1):
    """Open (or renew) a pose with the row /posttest/start writes
    (`learn_loop._new_pose`). Every answer column is NULL in it, so a renewal
    resets the outcome as the route's does (A89/A93, A112). A row without them
    keeps the old outcome on the upsert, and the outcome CHECK refuses it."""

    at = posed or _now()
    choice = SimpleNamespace(item=SimpleNamespace(question_hash=qh), match="none", source="reserve")
    span = SimpleNamespace(first_id=None, first_at=at - timedelta(days=window), last_at=at - timedelta(days=1))
    services.loop.posttest_poses._record_poses([services.loop.posttest_poses._new_pose(USER, COURSE, node, window, choice, span, at)])


def _row(db_conn, node, window=W1):
    return db_conn.execute(
        "SELECT question_hash, posed_at, answered_at, claim, claimed_at, correct, max_rung "
        "FROM posttest_poses WHERE user_id = %s AND node_id = %s AND window_days = %s",
        (USER, node, window),
    ).fetchone()


def _node():
    return f"it-node-{uuid.uuid4().hex[:10]}"


def test_concurrent_claims_have_exactly_one_winner(db_conn):

    node = _node()
    _open_pose(node)
    now = _now()
    wins, lock = [], threading.Lock()

    def claim(c):
        row = services.loop.posttest_poses._claim_pose(USER, node, "q1", c, now)
        if row is not None:
            with lock:
                wins.append(c)

    threads = [threading.Thread(target=claim, args=(f"c-{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1
    assert _row(db_conn, node)["claim"] == wins[0]


def test_the_or_filter_takes_over_only_a_stale_claim_with_iso_z_microseconds(db_conn):
    from learning.params import LOOP_GRADING_CLAIM_STALE_S

    node = _node()
    _open_pose(node)
    now = _now().replace(microsecond=654321)  # the cutoff carries microseconds
    fresh = now - timedelta(seconds=LOOP_GRADING_CLAIM_STALE_S) + timedelta(microseconds=5)
    db_conn.execute(
        "UPDATE posttest_poses SET claim = 'held', claimed_at = %s WHERE node_id = %s",
        (fresh, node),
    )
    assert services.loop.posttest_poses._claim_pose(USER, node, "q1", "late", now) is None
    stale = now - timedelta(seconds=LOOP_GRADING_CLAIM_STALE_S) - timedelta(microseconds=5)
    db_conn.execute("UPDATE posttest_poses SET claimed_at = %s WHERE node_id = %s", (stale, node))
    assert services.loop.posttest_poses._claim_pose(USER, node, "q1", "taker", now) is not None
    assert _row(db_conn, node)["claim"] == "taker"


def test_a_claim_with_no_claimed_at_is_claimable(db_conn):
    """m10: a claim string with a NULL claimed_at (a torn write) never wedges."""

    node = _node()
    _open_pose(node)
    db_conn.execute(
        "UPDATE posttest_poses SET claim = 'torn', claimed_at = NULL WHERE node_id = %s", (node,)
    )
    assert services.loop.posttest_poses._claim_pose(USER, node, "q1", "mine", _now()) is not None


def test_an_answered_pose_is_never_claimable_and_never_reopened(db_conn):

    node = _node()
    _open_pose(node)
    now = _now()
    assert services.loop.posttest_poses._claim_pose(USER, node, "q1", "a", now) is not None
    assert services.loop.posttest_poses._answer_pose(USER, node, "a", now, correct=True, max_rung=0) is True
    services.loop.posttest_poses._release_pose(USER, node, "a")  # a late release never reopens it
    row = _row(db_conn, node)
    assert row["answered_at"] is not None and row["claim"] is None
    assert row["correct"] is True and row["max_rung"] == 0  # A112: the outcome, in the same write
    far = now + timedelta(hours=1)
    assert services.loop.posttest_poses._claim_pose(USER, node, "q1", "b", far) is None


def test_a_taken_over_claim_cannot_close_the_pose(db_conn):
    """m1: the claim is re-validated before the flush."""
    from learning.params import LOOP_GRADING_CLAIM_STALE_S

    node = _node()
    _open_pose(node)
    now = _now()
    assert services.loop.posttest_poses._claim_pose(USER, node, "q1", "slow", now) is not None
    later = now + timedelta(seconds=LOOP_GRADING_CLAIM_STALE_S + 1)
    assert services.loop.posttest_poses._claim_pose(USER, node, "q1", "fast", later) is not None
    assert services.loop.posttest_poses._answer_pose(USER, node, "slow", later, correct=True, max_rung=0) is False
    assert services.loop.posttest_poses._answer_pose(USER, node, "fast", later, correct=True, max_rung=0) is True


def test_the_upsert_renews_a_window_and_a_new_window_is_its_own_row(db_conn):
    """A112: one row per (student, node, window) — a re-pose in a window renews
    that row (A89/A93); the next window adds a row and leaves the first alone."""

    node = _node()
    _open_pose(node)
    now = _now()
    services.loop.posttest_poses._claim_pose(USER, node, "q1", "a", now)
    services.loop.posttest_poses._answer_pose(USER, node, "a", now, correct=False, max_rung=0)
    _open_pose(node, qh="q2")  # the same window again: replaces the row
    row = _row(db_conn, node)
    assert row["question_hash"] == "q2" and row["answered_at"] is None and row["claim"] is None
    assert row["correct"] is None and row["max_rung"] is None  # a renewal resets the outcome
    _open_pose(node, qh="q3", window=W2)
    windows = db_conn.execute(
        "SELECT window_days FROM posttest_poses WHERE user_id = %s AND node_id = %s "
        "ORDER BY window_days",
        (USER, node),
    ).fetchall()
    assert [r["window_days"] for r in windows] == [W1, W2]


def test_a_claim_names_the_open_window_only(db_conn):
    """A112: the same item bound into a later window (A93) — the expired row of
    the first window is never claimed or closed by the answer to the second."""
    from learning.params import POSTTEST_POSE_TTL_HOURS

    node = _node()
    now = _now()
    _open_pose(node, posed=now - timedelta(hours=POSTTEST_POSE_TTL_HOURS + 1))  # expired
    _open_pose(node, window=W2)
    assert services.loop.posttest_poses._claim_pose(USER, node, "q1", "c", now) is not None
    assert services.loop.posttest_poses._answer_pose(USER, node, "c", now, correct=True, max_rung=0) is True
    assert _row(db_conn, node, W2)["answered_at"] is not None
    first = _row(db_conn, node, W1)
    assert first["answered_at"] is None and first["claim"] is None and first["correct"] is None


def test_an_outcome_needs_an_answered_pose(db_conn):
    """The A112 CHECK: `correct`/`max_rung` both or neither, only once answered."""
    node = _node()
    _open_pose(node)
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            "UPDATE posttest_poses SET correct = true, max_rung = 0 WHERE node_id = %s", (node,)
        )


def test_the_windows_migration_is_idempotent_and_keys_by_window(db_conn):
    from tests.integration.conftest import _require_local_db_url

    url = (os.getenv("SUPABASE_DB_URL") or "").strip()
    _require_local_db_url(url)
    (mig,) = sorted(
        (Path(__file__).resolve().parents[2] / "db" / "migrations").glob(
            "*_learning_posttest_windows.sql"
        )
    )
    key = (
        "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint "
        "WHERE conrelid = 'public.posttest_poses'::regclass AND contype = 'p'"
    )
    assert db_conn.execute(key).fetchone()["def"] == "PRIMARY KEY (user_id, node_id, window_days)"
    from psycopg.rows import dict_row

    with psycopg.connect(url, row_factory=dict_row) as conn:
        try:
            conn.execute(mig.read_text(encoding="utf-8"))
            assert conn.execute(key).fetchone()["def"] == (
                "PRIMARY KEY (user_id, node_id, window_days)"
            )
        finally:
            conn.rollback()


def test_an_expired_pose_is_void(db_conn):
    """A89: POSTTEST_POSE_TTL_HOURS after posed_at the pose cannot be claimed."""
    from learning.params import POSTTEST_POSE_TTL_HOURS

    now = _now()
    old, young = _node(), _node()
    _open_pose(old, posed=now - timedelta(hours=POSTTEST_POSE_TTL_HOURS, seconds=1))
    _open_pose(young, posed=now - timedelta(hours=POSTTEST_POSE_TTL_HOURS - 1))
    assert services.loop.posttest_poses._claim_pose(USER, old, "q1", "x", now) is None
    assert services.loop.posttest_poses._claim_pose(USER, young, "q1", "y", now) is not None
    assert _row(db_conn, old)["claim"] is None


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_client_roles_are_denied(db_conn, role):
    try:
        db_conn.execute(f"SET ROLE {role}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute("SELECT * FROM posttest_poses LIMIT 1")
    finally:
        db_conn.execute("RESET ROLE")
