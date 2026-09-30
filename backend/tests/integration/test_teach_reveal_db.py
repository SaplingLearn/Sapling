"""PKG-14 re-review round, real-DB half of the served reveals (spec §13 A88):
learning_reveals is written at serve time and read by every selection and
grading path; open_posed_items reads the open items off sessions' loop_state
JSON and posttest_poses. The JSON-path filters (loop_state->>current,
loop_state->open), the TTL filter and the timestamp comparisons only mean
something against real PostgREST + Postgres (#397: writes through the app,
reads over psycopg)."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import psycopg
import pytest

pytestmark = pytest.mark.integration

USER = "rich-user-active"


def _now():
    return datetime.now(timezone.utc)


def test_reveals_round_trip_into_revealed_hashes(db_conn):
    from learning.loop_state_store import revealed_hashes
    from learning.reveal_store import record_reveals

    qh = f"it-qh-{uuid.uuid4().hex[:10]}"
    record_reveals(USER, [qh], session_id=None, source="teach")
    rows = db_conn.execute(
        "SELECT kind, question_hash, session_id FROM learning_reveals WHERE user_id = %s",
        (USER,),
    ).fetchall()
    assert [(r["kind"], r["question_hash"], r["session_id"]) for r in rows] == [
        ("reveal", qh, None)
    ]
    assert qh in revealed_hashes(USER)


def test_an_unscanned_marker_floors_only_items_posed_at_or_before_it(db_conn):
    from learning.reveal_store import record_unscanned, unscanned_since

    at = _now().replace(microsecond=123456)
    record_unscanned(USER, session_id="s-it", source="teach", at=at)
    assert unscanned_since(USER, at - timedelta(seconds=1)) is True
    assert unscanned_since(USER, at) is True  # the same instant: at or before
    assert unscanned_since(USER, at + timedelta(microseconds=1)) is False
    assert unscanned_since(USER, None) is True


def test_the_hash_check_constraint(db_conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            "INSERT INTO learning_reveals (user_id, kind, question_hash) VALUES (%s, 'reveal', NULL)",
            (USER,),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            "INSERT INTO learning_reveals (user_id, kind, question_hash) VALUES (%s, 'unscanned', 'q')",
            (USER,),
        )


def test_open_posed_items_reads_the_open_sessions_and_poses(db_conn):
    from db.connection import table
    from routes import learn_loop

    now = _now()
    loop_sid, closed_sid, review_sid = (str(uuid.uuid4()) for _ in range(3))
    active = {"check_item_id": "it-item-a", "first_shown_at": now.timestamp() - 60}
    rows = [
        {
            "id": loop_sid,
            "user_id": USER,
            "mode": "socratic",
            "topic": "t",
            "loop_state": {"current": "qh-a", "steps": {"qh-a": active}},
        },
        {  # ended: its active item is no longer open
            "id": closed_sid,
            "user_id": USER,
            "mode": "socratic",
            "topic": "t",
            "ended_at": now.isoformat(),
            "loop_state": {
                "current": "qh-x",
                "steps": {"qh-x": {"check_item_id": "it-item-x", "first_shown_at": 1.0}},
            },
        },
        {
            "id": review_sid,
            "user_id": USER,
            "mode": "review",
            "topic": "Review",
            "loop_state": {
                "open": {
                    "check:qh-r": {"item_id": "it-item-r", "served_at": now.timestamp()},
                    "fc:card": {"item_id": "card", "served_at": now.timestamp()},
                }
            },
        },
    ]
    for row in rows:  # one insert each: a PostgREST bulk insert needs uniform keys
        table("sessions").insert(row)
    learn_loop._record_poses(
        [
            {
                "user_id": USER,
                "node_id": f"it-node-{uuid.uuid4().hex[:8]}",
                "course_id": "c-it",
                "question_hash": "qh-p",
                "posed_at": now.isoformat(),
                "answered_at": None,
                "claim": None,
                "claimed_at": None,
            },
            {  # expired (A89): never open
                "user_id": USER,
                "node_id": f"it-node-{uuid.uuid4().hex[:8]}",
                "course_id": "c-it",
                "question_hash": "qh-old",
                "posed_at": (now - timedelta(hours=48)).isoformat(),
                "answered_at": None,
                "claim": None,
                "claimed_at": None,
            },
        ]
    )

    class _It:
        def __init__(self, qh, course="c-it"):
            self.question_hash, self.course_id = qh, course

    loaded = {"it-item-a": _It("qh-a"), "it-item-r": _It("qh-r"), "it-item-x": _It("qh-x")}
    with (
        patch("routes.learn_loop.get_check_item", side_effect=lambda i: loaded.get(i)),
        patch(
            "routes.learn_loop.items_by_hash", side_effect=lambda hs: [_It(h) for h in hs]
        ) as by_hash,
    ):
        got = learn_loop.open_posed_items(USER, now=now)
    assert got is not None
    assert sorted(i.question_hash for i, _ in got) == ["qh-a", "qh-p", "qh-r"]
    assert by_hash.call_args.args[0] == ["qh-p"]  # the expired pose is not read


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_client_roles_are_denied(db_conn, role):
    try:
        db_conn.execute(f"SET ROLE {role}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute("SELECT * FROM learning_reveals LIMIT 1")
    finally:
        db_conn.execute("RESET ROLE")
