"""PKG-14 review fix round (owner decision 1, spec §13 A93), real-DB half of the
HELP LEDGER: the 'help' / 'posed' rows on learning_reveals, their CHECK
constraints, the max-help floor, the ungraded-posed scan window, and the floor
re-read inside a grading claim against real Postgres (a MagicMock suite sees
the filter dicts, never what PostgREST does with them). Writes through the app
helpers; reads back over psycopg (#397). Run inside the B6 cycle."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import psycopg
import pytest

pytestmark = pytest.mark.integration

USER = "rich-user-active"


def _qh() -> str:
    return f"it-help-{uuid.uuid4().hex[:12]}"


def test_help_rows_round_trip_into_the_max_help_floor(db_conn):
    from learning import help_ledger
    from learning.params import RUNG_NO_CREDIT_MIN
    from learning.reveal_store import record_reveals

    qh = _qh()
    assert help_ledger.max_help(USER, qh) == 0
    help_ledger.record_help(USER, qh, 2, source="loop", session_id="s-a")
    help_ledger.record_help(USER, qh, 3, source="review")
    assert help_ledger.max_help(USER, qh) == 3
    record_reveals(USER, [qh], session_id=None, source="teach")
    assert help_ledger.max_help(USER, qh) == RUNG_NO_CREDIT_MIN
    help_ledger.record_help(USER, qh, 6, source="loop", session_id="s-b")
    assert help_ledger.max_help(USER, qh) == 6
    rows = db_conn.execute(
        "SELECT kind, rung, source FROM learning_reveals WHERE user_id = %s AND question_hash = %s "
        "ORDER BY at",
        (USER, qh),
    ).fetchall()
    assert [(r["kind"], r["rung"]) for r in rows] == [("help", 2), ("help", 3), ("reveal", None), ("help", 6)]


@pytest.mark.parametrize(
    "kind,qh,rung,graded",
    [
        ("help", "q", None, None),  # help without a rung
        ("posed", "q", 2, None),  # a rung on a non-help row
        ("help", "q", 9, None),  # above LADDER_MAX_RUNG
        ("unscanned", "q", None, None),  # an unscanned marker names no item
        ("reveal", None, None, None),  # a reveal names one
        ("help", "q", 2, "now()"),  # graded_at only on a posed row
    ],
)
def test_the_ledger_constraints(db_conn, kind, qh, rung, graded):
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            "INSERT INTO learning_reveals (user_id, kind, question_hash, rung, graded_at) "
            f"VALUES (%s, %s, %s, %s, {graded or 'NULL'})",
            (USER, kind, qh, rung),
        )


def test_posed_rows_leave_the_scan_window_once_graded(db_conn):
    from learning import help_ledger

    a, b = _qh(), _qh()
    help_ledger.record_posed(USER, a, source="probe", session_id="s1")
    help_ledger.record_posed(USER, b, source="loop", session_id="s2")
    help_ledger.record_posed(USER, a, source="review")  # re-posed elsewhere
    window = dict(help_ledger.ungraded_posed(USER, 50))
    assert a in window and b in window
    first = help_ledger.earliest_open_pose(USER, a)
    assert first is not None and first <= datetime.now(timezone.utc)
    help_ledger.mark_graded(USER, a)
    window = dict(help_ledger.ungraded_posed(USER, 50))
    assert a not in window and b in window
    assert help_ledger.earliest_open_pose(USER, a) is None
    n = db_conn.execute(
        "SELECT count(*)::int AS n FROM learning_reveals WHERE user_id = %s AND question_hash = %s "
        "AND graded_at IS NOT NULL",
        (USER, a),
    ).fetchone()
    assert n["n"] == 2  # every ungraded posed row of the item is closed


def test_the_floor_is_reread_inside_the_claim(db_conn):
    """The two-session laundering case against real SQL: item open in session B
    (graded, floor read 0), H6 recorded in session A while B's grade ran — the
    re-read right before B's write raises B's Evidence to H6."""
    from learning import help_ledger
    from learning.params import RUNG_NO_CREDIT_MIN
    from routes import learn_loop

    qh = _qh()
    item = SimpleNamespace(question_hash=qh)
    help_ledger.record_posed(USER, qh, source="loop", session_id="s-b")
    assert learn_loop._reveal_floor(USER, item, None) == 0
    pending = [{"question_hash": qh, "max_rung": 0, "assisted": False}]
    help_ledger.record_help(USER, qh, 6, source="loop", session_id="s-a")  # concurrently, in A
    assert learn_loop._refloor(pending, USER, item, None, 0) == 6
    assert pending[0]["max_rung"] == 6 and pending[0]["max_rung"] >= RUNG_NO_CREDIT_MIN
