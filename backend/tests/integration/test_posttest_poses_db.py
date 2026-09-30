"""PKG-14 re-review round, real-DB half of the post-test pose (spec §13 A87,
A89): the claim is ONE conditional PostgREST UPDATE, so its or-filter, its
ISO-Z stale cutoff, the TTL filter and the concurrent single-winner property
can only be shown against real Postgres — a MagicMock suite sees the filter
dict, never what PostgREST does with it. Writes go through the route helpers
(the app layer); assertions read back over psycopg (#397)."""

import threading
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

pytestmark = pytest.mark.integration

USER = "rich-user-active"
COURSE = "it-course-posttest"


def _now():
    return datetime.now(timezone.utc)


def _open_pose(node, *, qh="q1", posed=None):
    from routes import learn_loop

    learn_loop._record_poses(
        [
            {
                "user_id": USER,
                "node_id": node,
                "course_id": COURSE,
                "question_hash": qh,
                "posed_at": (posed or _now()).isoformat(),
                "answered_at": None,
                "claim": None,
                "claimed_at": None,
            }
        ]
    )


def _row(db_conn, node):
    return db_conn.execute(
        "SELECT question_hash, posed_at, answered_at, claim, claimed_at "
        "FROM posttest_poses WHERE user_id = %s AND node_id = %s",
        (USER, node),
    ).fetchone()


def _node():
    return f"it-node-{uuid.uuid4().hex[:10]}"


def test_concurrent_claims_have_exactly_one_winner(db_conn):
    from routes import learn_loop

    node = _node()
    _open_pose(node)
    now = _now()
    wins, lock = [], threading.Lock()

    def claim(c):
        row = learn_loop._claim_pose(USER, node, "q1", c, now)
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
    from routes import learn_loop

    node = _node()
    _open_pose(node)
    now = _now().replace(microsecond=654321)  # the cutoff carries microseconds
    fresh = now - timedelta(seconds=LOOP_GRADING_CLAIM_STALE_S) + timedelta(microseconds=5)
    db_conn.execute(
        "UPDATE posttest_poses SET claim = 'held', claimed_at = %s WHERE node_id = %s",
        (fresh, node),
    )
    assert learn_loop._claim_pose(USER, node, "q1", "late", now) is None
    stale = now - timedelta(seconds=LOOP_GRADING_CLAIM_STALE_S) - timedelta(microseconds=5)
    db_conn.execute("UPDATE posttest_poses SET claimed_at = %s WHERE node_id = %s", (stale, node))
    assert learn_loop._claim_pose(USER, node, "q1", "taker", now) is not None
    assert _row(db_conn, node)["claim"] == "taker"


def test_a_claim_with_no_claimed_at_is_claimable(db_conn):
    """m10: a claim string with a NULL claimed_at (a torn write) never wedges."""
    from routes import learn_loop

    node = _node()
    _open_pose(node)
    db_conn.execute(
        "UPDATE posttest_poses SET claim = 'torn', claimed_at = NULL WHERE node_id = %s", (node,)
    )
    assert learn_loop._claim_pose(USER, node, "q1", "mine", _now()) is not None


def test_an_answered_pose_is_never_claimable_and_never_reopened(db_conn):
    from routes import learn_loop

    node = _node()
    _open_pose(node)
    now = _now()
    assert learn_loop._claim_pose(USER, node, "q1", "a", now) is not None
    assert learn_loop._answer_pose(USER, node, "a", now) is True
    learn_loop._release_pose(USER, node, "a")  # a late release never reopens it
    row = _row(db_conn, node)
    assert row["answered_at"] is not None and row["claim"] is None
    far = now + timedelta(hours=1)
    assert learn_loop._claim_pose(USER, node, "q1", "b", far) is None


def test_a_taken_over_claim_cannot_close_the_pose(db_conn):
    """m1: the claim is re-validated before the flush."""
    from learning.params import LOOP_GRADING_CLAIM_STALE_S
    from routes import learn_loop

    node = _node()
    _open_pose(node)
    now = _now()
    assert learn_loop._claim_pose(USER, node, "q1", "slow", now) is not None
    later = now + timedelta(seconds=LOOP_GRADING_CLAIM_STALE_S + 1)
    assert learn_loop._claim_pose(USER, node, "q1", "fast", later) is not None
    assert learn_loop._answer_pose(USER, node, "slow", later) is False
    assert learn_loop._answer_pose(USER, node, "fast", later) is True


def test_the_upsert_reopens_a_node_with_a_new_item(db_conn):
    from routes import learn_loop

    node = _node()
    _open_pose(node)
    now = _now()
    learn_loop._claim_pose(USER, node, "q1", "a", now)
    learn_loop._answer_pose(USER, node, "a", now)
    _open_pose(node, qh="q2")
    row = _row(db_conn, node)
    assert row["question_hash"] == "q2" and row["answered_at"] is None and row["claim"] is None
    count = db_conn.execute(
        "SELECT count(*) AS n FROM posttest_poses WHERE user_id = %s AND node_id = %s", (USER, node)
    ).fetchone()["n"]
    assert count == 1


def test_an_expired_pose_is_void(db_conn):
    """A89: POSTTEST_POSE_TTL_HOURS after posed_at the pose cannot be claimed."""
    from learning.params import POSTTEST_POSE_TTL_HOURS
    from routes import learn_loop

    now = _now()
    old, young = _node(), _node()
    _open_pose(old, posed=now - timedelta(hours=POSTTEST_POSE_TTL_HOURS, seconds=1))
    _open_pose(young, posed=now - timedelta(hours=POSTTEST_POSE_TTL_HOURS - 1))
    assert learn_loop._claim_pose(USER, old, "q1", "x", now) is None
    assert learn_loop._claim_pose(USER, young, "q1", "y", now) is not None
    assert _row(db_conn, old)["claim"] is None


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_client_roles_are_denied(db_conn, role):
    try:
        db_conn.execute(f"SET ROLE {role}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute("SELECT * FROM posttest_poses LIMIT 1")
    finally:
        db_conn.execute("RESET ROLE")
