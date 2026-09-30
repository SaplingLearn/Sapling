"""PKG-14 half B's additions to the real-DB post-test pose tests (spec §13 A87,
A89). Half A's tests/integration/test_posttest_poses_db.py owns the claim's
single winner, the stale/NULL-claimed_at takeover, answered-never-claimable, the
taken-over-claim close, the re-pose upsert, the TTL and the role denial; this
module adds only what it does not cover, against the same route helpers
(`_record_poses`, `_claim_pose`, `_answer_pose`, `_release_pose`) — writes
through the app layer, reads back over psycopg (#397):

- the claim names the posed item only (a different question_hash never claims);
- release on an error frees the pose for the next submission;
- a release never reopens an answered pose, and a foreign claim releases nothing;
- the WHOLE grade cycle under concurrency — 8 submitters each claim then close
  (`_answer_pose`), as the route does — answers the pose exactly once.

Run inside the B6 flock'd cycle with RUN_INTEGRATION=1.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.integration

USER = "rich-user-active"
COURSE = "it-course-posttest-b"
QH = "qh-posttest-b"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _open_pose() -> str:
    from routes.learn_loop import _record_poses

    node = f"it-node-{uuid.uuid4().hex[:10]}"
    _record_poses(
        [
            {
                "user_id": USER,
                "node_id": node,
                "course_id": COURSE,
                "question_hash": QH,
                "posed_at": _now().isoformat(),
                "answered_at": None,
                "claim": None,
                "claimed_at": None,
            }
        ]
    )
    return node


def _row(db_conn, node: str) -> dict:
    return db_conn.execute(
        "SELECT answered_at, claim, claimed_at FROM posttest_poses WHERE user_id = %s AND node_id = %s",
        (USER, node),
    ).fetchone()


def test_a_claim_names_the_posed_item_only(db_conn):
    from routes.learn_loop import _claim_pose

    node = _open_pose()
    assert _claim_pose(USER, node, "qh-some-other-item", "c1", _now()) is None
    assert _row(db_conn, node)["claim"] is None


def test_release_on_error_frees_the_pose_for_the_next_submission(db_conn):
    """A refusal, an outage or an error grades nothing: the claim is released
    (answered stays NULL) and the next submission can claim it at once."""
    from routes.learn_loop import _claim_pose, _release_pose

    node = _open_pose()
    now = _now()
    assert _claim_pose(USER, node, QH, "c1", now) is not None
    _release_pose(USER, node, "c1")
    row = _row(db_conn, node)
    assert (row["claim"], row["claimed_at"], row["answered_at"]) == (None, None, None)
    assert _claim_pose(USER, node, QH, "c2", now) is not None


def test_a_release_never_reopens_an_answered_pose(db_conn):
    from routes.learn_loop import _answer_pose, _claim_pose, _release_pose

    node = _open_pose()
    now = _now()
    assert _claim_pose(USER, node, QH, "c1", now) is not None
    assert _answer_pose(USER, node, "c1", now) is True
    answered = _row(db_conn, node)["answered_at"]
    _release_pose(USER, node, "c1")
    assert _row(db_conn, node)["answered_at"] == answered
    assert _claim_pose(USER, node, QH, "c2", now) is None


def test_a_foreign_claim_releases_nothing(db_conn):
    from routes.learn_loop import _claim_pose, _release_pose

    node = _open_pose()
    assert _claim_pose(USER, node, QH, "c1", _now()) is not None
    _release_pose(USER, node, "not-mine")
    assert _row(db_conn, node)["claim"] == "c1"


def test_concurrent_submissions_answer_the_pose_once(db_conn):
    """The route's grade cycle — claim, then close the pose before the one flush
    — run by 8 simultaneous submitters (separate PostgREST requests, as separate
    backend processes would send): exactly one closes it; nobody else may flush."""
    from routes.learn_loop import _answer_pose, _claim_pose

    node = _open_pose()
    now = _now()
    closed: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def submit(i: int) -> None:
        claim = f"c{i}"
        try:
            barrier.wait(timeout=10)
            if _claim_pose(USER, node, QH, claim, now) is not None and _answer_pose(USER, node, claim, now):
                with lock:
                    closed.append(claim)
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    assert len(closed) == 1, closed
    row = _row(db_conn, node)
    assert row["answered_at"] is not None and row["claim"] is None
