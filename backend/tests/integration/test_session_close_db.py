"""PKG-09 real-DB half: the session-close writes against local Supabase (#397 seam —
writes through the app layer, raw reads via psycopg).

`db.connection.table().insert_ignore_duplicates` (PostgREST
`Prefer: resolution=ignore-duplicates`, ON CONFLICT DO NOTHING) is a shared-file
addition PKG-09 relies on for the A11 insert-if-missing; a MagicMock suite cannot
tell whether PostgREST honours the header. Also pins `store_close`'s conditional
write (`close_json=is.null`) and that both close columns land as ciphertext."""

import uuid

import pytest

pytestmark = pytest.mark.integration

USER = "rich-user-active"


def _row(db_conn, sid):
    return db_conn.execute(
        "SELECT mode, topic, close_json, close_phase FROM sessions WHERE id = %s", (sid,)
    ).fetchone()


def test_insert_ignore_duplicates_never_overwrites(db_conn):
    from db.connection import table

    sid = str(uuid.uuid4())
    table("sessions").insert({"id": sid, "user_id": USER, "mode": "socratic", "topic": "First"})
    again = table("sessions").insert_ignore_duplicates(
        {"id": sid, "user_id": USER, "mode": "expository", "topic": "Second"}, on_conflict="id"
    )
    assert again == []
    row = _row(db_conn, sid)
    assert (row["mode"], row["topic"]) == ("socratic", "First")


def test_ensure_session_row_inserts_once_and_store_close_writes_once(db_conn):
    from learning.session_close import CloseRecord, ensure_session_row, store_close

    sid = str(uuid.uuid4())
    defaults = {"mode": "socratic", "topic": "Recursion"}
    assert ensure_session_row(sid, USER, defaults) is True
    assert ensure_session_row(sid, USER, {"mode": "expository", "topic": "Other"}) is True
    assert _row(db_conn, sid)["topic"] == "Recursion"

    rec = CloseRecord(
        summary="S.",
        self_eval="Q?",
        if_then="",
        concepts=[],
        misconceptions=[],
        model_written=False,
    )
    assert store_close(sid, USER, rec, "teach", row_defaults=None) is True
    first = _row(db_conn, sid)
    assert first["close_phase"] == "teach" and "S." not in (first["close_json"] or "")
    assert (
        store_close(sid, USER, rec.model_copy(update={"summary": "T."}), "close", row_defaults=None)
        is False
    )
    assert _row(db_conn, sid)["close_json"] == first["close_json"]  # never overwritten
