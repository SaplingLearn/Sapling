"""PKG-10 fix round (F5) real-DB half: `learning.misconceptions.record` is ONE
atomic statement (`misconception_record`, INSERT … ON CONFLICT on the open-row
partial unique index). A MagicMock suite cannot show that concurrent records
of one key keep one open row and lose no increment, nor that the function is
exposed to the backend through PostgREST's rpc."""

import threading
import uuid

import pytest

pytestmark = pytest.mark.integration

USER = "rich-user-active"


def _node(db_conn) -> str:
    row = db_conn.execute(
        "SELECT id FROM graph_nodes WHERE user_id = %s ORDER BY id LIMIT 1", (USER,)
    ).fetchone()
    if row is None:
        pytest.skip("rich seed has no graph node for the active user")
    return row["id"]


def test_concurrent_records_keep_one_open_row_and_every_increment(db_conn):
    from learning.misconceptions import record

    node = _node(db_conn)
    key = f"it_{uuid.uuid4().hex[:12]}"
    threads = [
        threading.Thread(target=record, args=(USER, node, None, key, "answer text"))
        for _ in range(8)
    ]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        rows = db_conn.execute(
            "SELECT count, evidence_text FROM misconceptions "
            "WHERE user_id = %s AND node_id = %s AND wrong_key = %s AND resolved_at IS NULL",
            (USER, node, key),
        ).fetchall()
        assert len(rows) == 1 and rows[0]["count"] == 8
        assert "answer text" not in (rows[0]["evidence_text"] or ""), "stored as ciphertext"
    finally:
        db_conn.execute("DELETE FROM misconceptions WHERE wrong_key = %s", (key,))


def test_a_resolved_row_never_blocks_a_new_open_one(db_conn):
    from learning.misconceptions import RESOLVED_BY_ISOMORPH, record, resolve

    node = _node(db_conn)
    key = f"it_{uuid.uuid4().hex[:12]}"
    try:
        assert record(USER, node, None, key, "x")["count"] == 1
        # spec §13 A127's resolve: the keys, and the isomorph whose correct,
        # unassisted answer closes them (any item but the one recorded on)
        (closed,) = resolve(USER, node, [key], by_item="it-isomorph-item")
        assert closed["wrong_key"] == key
        # the row records why it closed (A123's CHECK alone refused this value)
        reasons = db_conn.execute(
            "SELECT resolved_reason FROM misconceptions "
            "WHERE user_id = %s AND node_id = %s AND wrong_key = %s AND resolved_at IS NOT NULL",
            (USER, node, key),
        ).fetchall()
        assert [r["resolved_reason"] for r in reasons] == [RESOLVED_BY_ISOMORPH]
        assert record(USER, node, None, key, "y")["count"] == 1
    finally:
        db_conn.execute("DELETE FROM misconceptions WHERE wrong_key = %s", (key,))


def test_the_resolved_reason_check_admits_the_two_closures_and_nothing_else(db_conn):
    """20261108110805 widened A123's CHECK by its body: A123's and A127's
    reasons (and NULL, an open row) are admitted, any other value is refused,
    and exactly one CHECK names the column."""
    import psycopg

    from learning.evidence_void import MISCONCEPTION_VOID_REASON
    from learning.misconceptions import RESOLVED_BY_ISOMORPH, record

    node = _node(db_conn)
    key = f"it_{uuid.uuid4().hex[:12]}"
    update = "UPDATE misconceptions SET resolved_reason = %s WHERE wrong_key = %s"
    try:
        assert record(USER, node, None, key, "x")["count"] == 1
        for reason in (MISCONCEPTION_VOID_REASON, RESOLVED_BY_ISOMORPH, None):
            db_conn.execute(update, (reason, key))
        with pytest.raises(psycopg.errors.CheckViolation):
            db_conn.execute(update, ("closed_for_another_reason", key))
        checks = db_conn.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'public.misconceptions'::regclass AND contype = 'c' "
            "AND position('resolved_reason' in pg_get_constraintdef(oid)) > 0"
        ).fetchall()
        assert [c["conname"] for c in checks] == ["misconceptions_resolved_reason_check"]
    finally:
        db_conn.execute("DELETE FROM misconceptions WHERE wrong_key = %s", (key,))
