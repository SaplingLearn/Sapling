"""PKG-14 (spec §13 A87) real-DB half: the post-test pose store and its claim.

The claim is ONE conditional PostgREST UPDATE on `posttest_poses`
(`answered_at=is.null` and `or=(claim.is.null,claimed_at.lt.<stale>)`) whose
returned representation decides who grades. A mocked table() cannot tell whether
PostgREST parses that `or=` list (a timestamp value inside it), whether the
update returns the row it changed, or whether two concurrent submissions really
exclude each other — and a fake modelled as a POP has hidden a claim bug before
(#482). So every property is proven here against the local stack (#397 seam:
writes through the app's helpers, raw reads via psycopg).

Run inside the B6 flock'd cycle: `RUN_INTEGRATION=1 venv/bin/python -m pytest
tests/integration/test_posttest_claim_db.py -m integration -q`.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration

USER = "rich-user-active"
COURSE = "rich-course-cs101"


def _open_pose(qh: str = "qh-posttest-it") -> str:
    """Record one open pose through the route's own writer; returns its node id."""
    from routes.learn_loop import _record_poses

    node = f"it-node-{uuid.uuid4().hex[:10]}"
    _record_poses(
        [
            {
                "user_id": USER,
                "node_id": node,
                "course_id": COURSE,
                "question_hash": qh,
                "posed_at": datetime.now(timezone.utc).isoformat(),
                "answered_at": None,
                "claim": None,
                "claimed_at": None,
            }
        ]
    )
    return node


def _row(db_conn, node: str) -> dict:
    return db_conn.execute(
        "SELECT question_hash, answered_at, claim, claimed_at FROM posttest_poses "
        "WHERE user_id = %s AND node_id = %s",
        (USER, node),
    ).fetchone()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_the_pose_table_is_reachable_through_postgrest_and_backend_only(db_conn):
    from routes.learn_loop import _read_poses

    node = _open_pose()
    assert _read_poses(USER, COURSE)[node]["question_hash"] == "qh-posttest-it"
    rls = db_conn.execute(
        "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.posttest_poses'::regclass"
    ).fetchone()
    assert rls["relrowsecurity"] is True
    grants = db_conn.execute(
        "SELECT grantee FROM information_schema.role_table_grants "
        "WHERE table_name = 'posttest_poses' AND grantee IN ('anon', 'authenticated')"
    ).fetchall()
    assert grants == [], "posttest_poses must be backend-only (A87)"


def test_a_claim_is_taken_once(db_conn):
    from routes.learn_loop import _claim_pose

    node = _open_pose()
    now = _now()
    assert _claim_pose(USER, node, "qh-posttest-it", "c1", now) is True
    assert _claim_pose(USER, node, "qh-posttest-it", "c2", now) is False
    assert _row(db_conn, node)["claim"] == "c1"


def test_a_claim_names_the_posed_item_only(db_conn):
    from routes.learn_loop import _claim_pose

    node = _open_pose()
    assert _claim_pose(USER, node, "qh-some-other-item", "c1", _now()) is False
    assert _row(db_conn, node)["claim"] is None


def test_a_fresh_claim_is_not_taken_over(db_conn):
    from learning.params import LOOP_GRADING_CLAIM_STALE_S
    from routes.learn_loop import _claim_pose

    node = _open_pose()
    now = _now()
    assert _claim_pose(USER, node, "qh-posttest-it", "c1", now - timedelta(seconds=LOOP_GRADING_CLAIM_STALE_S - 5))
    assert _claim_pose(USER, node, "qh-posttest-it", "c2", now) is False
    assert _row(db_conn, node)["claim"] == "c1"


def test_a_stale_claim_is_taken_over_after_the_lease(db_conn):
    """A crash mid-grade leaves a claim behind; after LOOP_GRADING_CLAIM_STALE_S
    the next submission takes it over (the `or=(…,claimed_at.lt.<stale>)` arm)."""
    from learning.params import LOOP_GRADING_CLAIM_STALE_S
    from routes.learn_loop import _claim_pose

    node = _open_pose()
    now = _now()
    assert _claim_pose(USER, node, "qh-posttest-it", "c1", now - timedelta(seconds=LOOP_GRADING_CLAIM_STALE_S + 5))
    assert _claim_pose(USER, node, "qh-posttest-it", "c2", now) is True
    assert _row(db_conn, node)["claim"] == "c2"


def test_release_on_error_frees_the_pose_for_the_next_submission(db_conn):
    """A refusal, an outage or an error releases the claim (answered stays NULL)."""
    from routes.learn_loop import _claim_pose, _settle_pose

    node = _open_pose()
    now = _now()
    assert _claim_pose(USER, node, "qh-posttest-it", "c1", now)
    _settle_pose(USER, node, "c1", answered=None)
    row = _row(db_conn, node)
    assert (row["claim"], row["claimed_at"], row["answered_at"]) == (None, None, None)
    assert _claim_pose(USER, node, "qh-posttest-it", "c2", now) is True


def test_an_answered_pose_is_never_graded_again(db_conn):
    """The one flush marks it answered; no later claim — fresh or stale-looking —
    can take it (the `answered_at=is.null` filter)."""
    from learning.params import LOOP_GRADING_CLAIM_STALE_S
    from routes.learn_loop import _claim_pose, _settle_pose

    node = _open_pose()
    now = _now()
    assert _claim_pose(USER, node, "qh-posttest-it", "c1", now)
    _settle_pose(USER, node, "c1", answered=now)
    row = _row(db_conn, node)
    assert row["answered_at"] is not None and row["claim"] is None
    assert _claim_pose(USER, node, "qh-posttest-it", "c2", now) is False
    later = now + timedelta(seconds=LOOP_GRADING_CLAIM_STALE_S * 10)
    assert _claim_pose(USER, node, "qh-posttest-it", "c3", later) is False


def test_settling_with_someone_elses_claim_changes_nothing(db_conn):
    from routes.learn_loop import _claim_pose, _settle_pose

    node = _open_pose()
    now = _now()
    assert _claim_pose(USER, node, "qh-posttest-it", "c1", now)
    _settle_pose(USER, node, "not-mine", answered=now)
    row = _row(db_conn, node)
    assert (row["claim"], row["answered_at"]) == ("c1", None)


def test_concurrent_submissions_grade_once(db_conn):
    """Many simultaneous submissions (separate HTTP requests to PostgREST, as
    separate backend processes would send): exactly one claim wins."""
    from routes.learn_loop import _claim_pose

    node = _open_pose()
    now = _now()
    wins: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def submit(i: int) -> None:
        try:
            barrier.wait(timeout=10)
            if _claim_pose(USER, node, "qh-posttest-it", f"c{i}", now):
                wins.append(f"c{i}")
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    assert len(wins) == 1, wins
    assert _row(db_conn, node)["claim"] == wins[0]


def test_a_repeat_record_replaces_the_pose_once_answered(db_conn):
    """An answered node is posed again only when due again (A87): the upsert on
    (user_id, node_id) replaces the row and the new pose is claimable."""
    from routes.learn_loop import _claim_pose, _record_poses, _settle_pose

    node = _open_pose()
    now = _now()
    assert _claim_pose(USER, node, "qh-posttest-it", "c1", now)
    _settle_pose(USER, node, "c1", answered=now)
    _record_poses(
        [
            {
                "user_id": USER,
                "node_id": node,
                "course_id": COURSE,
                "question_hash": "qh-posttest-it-2",
                "posed_at": now.isoformat(),
                "answered_at": None,
                "claim": None,
                "claimed_at": None,
            }
        ]
    )
    count = db_conn.execute(
        "SELECT count(*)::int AS n FROM posttest_poses WHERE user_id = %s AND node_id = %s", (USER, node)
    ).fetchone()
    assert count["n"] == 1
    assert _claim_pose(USER, node, "qh-posttest-it-2", "c2", now) is True
