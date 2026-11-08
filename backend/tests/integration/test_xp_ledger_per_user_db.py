"""xp_events idempotency is per student — against the real constraint.

The hermetic twin (tests/test_xp_ledger_per_user_key.py) replays the migration
DDL into a fake; this asserts what Postgres actually enforces after the
migration chain: two students paid for the same badge get two rows, and one
student paid twice still gets one. Writes go through award_xp (PostgREST);
reads come back over raw psycopg (#397).
"""
import pytest

from tests.integration.conftest import USER_ACTIVE, USER_SECOND

pytestmark = pytest.mark.integration

BADGE = "itest-shared-badge"


def _award(user_id):
    from services.xp_service import award_xp
    return award_xp(
        user_id, "achievement_unlocked",
        source_type="achievement", source_id=BADGE, amount=40,
    )


def test_two_students_earning_one_badge_are_both_paid(db_conn):
    first, second = _award(USER_ACTIVE), _award(USER_SECOND)
    assert (first.awarded, first.duplicate) == (40, False)
    assert (second.awarded, second.duplicate) == (40, False)
    rows = db_conn.execute(
        "SELECT user_id, amount FROM xp_events WHERE source_id = %s ORDER BY user_id",
        (BADGE,),
    ).fetchall()
    assert [(r["user_id"], r["amount"]) for r in rows] == sorted(
        [(USER_ACTIVE, 40), (USER_SECOND, 40)]
    )


def test_one_student_is_still_paid_once(db_conn):
    _award(USER_ACTIVE)
    again = _award(USER_ACTIVE)
    assert (again.awarded, again.duplicate) == (0, True)
    count = db_conn.execute(
        "SELECT count(*) AS n FROM xp_events WHERE source_id = %s AND user_id = %s",
        (BADGE, USER_ACTIVE),
    ).fetchone()["n"]
    assert count == 1
