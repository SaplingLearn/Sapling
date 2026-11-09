"""#117: replica-safe lazy tutor sessions (20261109024225_tutor_pending_sessions.sql)
against real Postgres.

SQL only (no app imports): tests/test_tutor_sessions_store.py pins what the
app does with the answers; this pins the SQL — the atomic materialisation,
the tombstones, the TTL/cap bounds and that the store is service-only.
"""
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration

_MIGRATION = (Path(__file__).resolve().parents[2] / "db" / "migrations"
              / "20261109024225_tutor_pending_sessions.sql")

USER, OTHER = "rich-user-active", "rich-user-second"
TTL, TOMB, CAP = 43200, 600, 2000


def _stash(conn, sid, *, user=USER, offering="", cap=CAP):
    conn.execute(
        "SELECT public.stash_tutor_session(%s, %s, 'socratic', 'Recursion', 'c1', %s, "
        "true, 'ENC:greeting', '{\"new_nodes\": []}'::jsonb, %s, %s, %s)",
        (sid, user, offering, TTL, TOMB, cap),
    )


def _materialize(conn, sid, user=USER) -> dict:
    return conn.execute(
        "SELECT * FROM public.materialize_tutor_session(%s, %s, %s, %s)",
        (sid, user, TTL, TOMB),
    ).fetchone()


def _discard(conn, sid, reason, *, only_if_pending, user=USER) -> bool:
    return conn.execute(
        "SELECT public.discard_tutor_session(%s, %s, %s, %s, %s) AS was_pending",
        (sid, user, reason, only_if_pending, TTL),
    ).fetchone()["was_pending"]


def _state(conn, sid):
    row = conn.execute("SELECT state FROM public.tutor_pending_sessions WHERE session_id = %s",
                       (sid,)).fetchone()
    return None if row is None else row["state"]


def test_first_turn_writes_the_row_and_greeting_once(db_conn):
    _stash(db_conn, "tps-1")
    assert _materialize(db_conn, "tps-1", OTHER)["outcome"] == "foreign"
    got = _materialize(db_conn, "tps-1")
    assert (got["outcome"], got["session_mode"], got["session_topic"]) == (
        "materialized", "socratic", "Recursion")
    assert _materialize(db_conn, "tps-1")["outcome"] == "none"  # the loser of a race
    s = db_conn.execute("SELECT user_id, mode, topic, offering_id, ended_at FROM public.sessions "
                        "WHERE id = 'tps-1'").fetchone()
    assert (s["user_id"], s["topic"], s["offering_id"], s["ended_at"]) == (
        USER, "Recursion", None, None)
    msgs = db_conn.execute("SELECT role, content FROM public.messages "
                           "WHERE session_id = 'tps-1'").fetchall()
    assert [(m["role"], m["content"]) for m in msgs] == [("assistant", "ENC:greeting")]
    assert _state(db_conn, "tps-1") is None


def test_an_ended_pending_session_is_a_tombstone_for_its_owner_only(db_conn):
    _stash(db_conn, "tps-2")
    assert _discard(db_conn, "tps-2", "ended", only_if_pending=True) is True
    assert _materialize(db_conn, "tps-2")["outcome"] == "ended"
    assert _materialize(db_conn, "tps-2", OTHER)["outcome"] == "none"
    row = db_conn.execute("SELECT topic, assistant_reply FROM public.tutor_pending_sessions "
                          "WHERE session_id = 'tps-2'").fetchone()
    assert row == {"topic": None, "assistant_reply": None}, "a tombstone keeps no content"
    assert db_conn.execute("SELECT count(*) AS n FROM public.sessions WHERE id = 'tps-2'"
                           ).fetchone()["n"] == 0


def test_end_of_a_live_session_leaves_no_tombstone_but_delete_does(db_conn):
    _stash(db_conn, "tps-3")
    _materialize(db_conn, "tps-3")
    assert _discard(db_conn, "tps-3", "ended", only_if_pending=True) is False
    assert _state(db_conn, "tps-3") is None
    assert _discard(db_conn, "tps-3", "deleted", only_if_pending=False) is False
    assert _state(db_conn, "tps-3") == "deleted"


def test_expired_pending_sessions_answer_none_and_are_swept(db_conn):
    _stash(db_conn, "tps-4")
    db_conn.execute("UPDATE public.tutor_pending_sessions "
                    "SET stashed_at = now() - interval '13 hours' WHERE session_id = 'tps-4'")
    assert _materialize(db_conn, "tps-4")["outcome"] == "none"
    assert _discard(db_conn, "tps-4", "ended", only_if_pending=True) is False
    _stash(db_conn, "tps-5")
    assert _state(db_conn, "tps-4") is None, "the next stash sweeps it"


def test_the_cap_evicts_the_oldest_pending_session(db_conn):
    for sid in ("tps-c1", "tps-c2", "tps-c3"):
        _stash(db_conn, sid, cap=2)
    left = db_conn.execute("SELECT session_id FROM public.tutor_pending_sessions "
                           "WHERE state = 'pending' ORDER BY 1").fetchall()
    assert [r["session_id"] for r in left] == ["tps-c2", "tps-c3"]


def test_the_store_is_service_only(db_conn):
    with db_conn.transaction() as tx:
        db_conn.execute("SET LOCAL ROLE authenticated")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute("SELECT count(*) FROM public.tutor_pending_sessions")
        raise psycopg.Rollback(tx)
    with db_conn.transaction() as tx:
        db_conn.execute("SET LOCAL ROLE authenticated")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute("SELECT * FROM public.materialize_tutor_session('x', 'y', 1, 1)")
        raise psycopg.Rollback(tx)


def test_the_migration_is_safe_to_apply_again(db_conn):
    _stash(db_conn, "tps-again")
    with db_conn.transaction() as tx:
        db_conn.execute(_MIGRATION.read_text())
        assert _state(db_conn, "tps-again") == "pending"
        raise psycopg.Rollback(tx)
