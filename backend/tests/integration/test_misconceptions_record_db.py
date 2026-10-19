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
    from learning.misconceptions import record, resolve

    node = _node(db_conn)
    key = f"it_{uuid.uuid4().hex[:12]}"
    try:
        assert record(USER, node, None, key, "x")["count"] == 1
        assert resolve(USER, node, key) == 1
        assert record(USER, node, None, key, "y")["count"] == 1
    finally:
        db_conn.execute("DELETE FROM misconceptions WHERE wrong_key = %s", (key,))
