"""xp_events idempotency is per student — against the real constraint.

The hermetic twin (tests/test_xp_ledger_per_user_key.py) replays the migration
DDL into a fake; this asserts what Postgres actually enforces after the
migration chain: two students paid for the same badge get two rows, and one
student paid twice still gets one. Writes go through award_xp (PostgREST);
reads come back over raw psycopg (#397).

The last two tests run the migration file itself against a rebuilt
pre-migration shape (rolled back afterwards): its defensive drop loops on a
drifted environment, and its refusal of duplicate (user_id, key) pairs. The
hermetic replay cannot see either.
"""
import pathlib

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


# ── the migration itself, on a drifted environment ─────────────────────────
#
# The stack already ran the migration, so these rebuild a PRE-migration shape
# inside a transaction that is always rolled back (force_rollback): nothing
# here outlives the test, even on failure. The migration is idempotent DDL, so
# re-running its file is exactly what `db.migrate` would do on that shape.

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "20261108063442_xp_events_per_user_idempotency.sql"
)
NEW = "xp_events_user_id_idempotency_key_key"


def _pre_migration_shape(db_conn):
    db_conn.execute("DELETE FROM xp_events")
    db_conn.execute(f"ALTER TABLE xp_events DROP CONSTRAINT IF EXISTS {NEW}")


def _user_blind_unique_indexes(db_conn) -> list[str]:
    """Every unique index on xp_events keyed on idempotency_key ALONE —
    constraint-backed or bare."""
    return [r["name"] for r in db_conn.execute(
        """
        SELECT i.indexrelid::regclass::text AS name
        FROM pg_index i
        JOIN pg_attribute a
          ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
        WHERE i.indrelid = 'xp_events'::regclass
          AND i.indisunique AND i.indnkeyatts = 1
          AND a.attname = 'idempotency_key'
        """
    ).fetchall()]


def test_the_migration_drops_every_user_blind_unique_key_however_named(db_conn):
    with db_conn.transaction(force_rollback=True):
        _pre_migration_shape(db_conn)
        # The original constraint, a drifted one under another name, and a
        # bare unique index: the static DROP only knows the first.
        db_conn.execute(
            "ALTER TABLE xp_events ADD CONSTRAINT xp_events_idempotency_key_key"
            " UNIQUE (idempotency_key)")
        db_conn.execute(
            "ALTER TABLE xp_events ADD CONSTRAINT itest_drifted_key_unique"
            " UNIQUE (idempotency_key)")
        db_conn.execute(
            "CREATE UNIQUE INDEX itest_drifted_key_idx ON xp_events (idempotency_key)")
        assert len(_user_blind_unique_indexes(db_conn)) == 3

        db_conn.execute(MIGRATION.read_text())

        assert _user_blind_unique_indexes(db_conn) == []
        assert db_conn.execute(
            "SELECT 1 FROM pg_constraint WHERE conname = %s"
            " AND conrelid = 'xp_events'::regclass", (NEW,),
        ).fetchone()
        for user_id in (USER_ACTIVE, USER_SECOND):   # two students, one key
            db_conn.execute(
                "INSERT INTO xp_events (user_id, rule_key, amount, idempotency_key)"
                " VALUES (%s, 'achievement_unlocked', 40, 'itest:shared')", (user_id,))

        db_conn.execute(MIGRATION.read_text())        # idempotent on its own result
        assert _user_blind_unique_indexes(db_conn) == []


def test_the_migration_refuses_duplicate_pairs_instead_of_deleting_them(db_conn):
    import psycopg

    with pytest.raises(psycopg.errors.RaiseException, match="duplicate"):
        with db_conn.transaction(force_rollback=True):
            _pre_migration_shape(db_conn)
            db_conn.execute("ALTER TABLE xp_events DROP CONSTRAINT IF EXISTS"
                            " xp_events_idempotency_key_key")
            for _ in range(2):
                db_conn.execute(
                    "INSERT INTO xp_events (user_id, rule_key, amount, idempotency_key)"
                    " VALUES (%s, 'quiz_completed', 30, 'itest:dup')", (USER_ACTIVE,))
            db_conn.execute(MIGRATION.read_text())
