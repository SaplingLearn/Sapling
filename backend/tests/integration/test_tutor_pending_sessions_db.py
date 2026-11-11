"""#117: replica-safe lazy tutor sessions (20261109024225_tutor_pending_sessions.sql)
against real Postgres.

SQL only (no app imports): tests/test_tutor_sessions_store.py pins what the
app does with the answers; this pins the SQL — the atomic materialisation,
the tombstones, the TTL/cap bounds and that the store is service-only.
"""
import json
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration

_MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"
_MIGRATION = _MIGRATIONS / "20261109024225_tutor_pending_sessions.sql"
#: #117 part 3: learning-loop sessions carry their starting loop document.
_LOOP_MIGRATION = _MIGRATIONS / "20261111030007_tutor_pending_loop_state.sql"

USER, OTHER = "rich-user-active", "rich-user-second"
TTL, TOMB, CAP = 43200, 600, 2000


def _stash(conn, sid, *, user=USER, offering="", cap=CAP, loop_state=None):
    if loop_state is None:  # the 12-argument call a tutor session (and the old app) makes
        conn.execute(
            "SELECT public.stash_tutor_session(%s, %s, 'socratic', 'Recursion', 'c1', %s, "
            "true, 'ENC:greeting', '{\"new_nodes\": []}'::jsonb, %s, %s, %s)",
            (sid, user, offering, TTL, TOMB, cap),
        )
        return
    conn.execute(
        "SELECT public.stash_tutor_session(%s, %s, 'socratic', 'Recursion', 'c1', %s, "
        "true, 'ENC:greeting', NULL, %s, %s, %s, %s::jsonb)",
        (sid, user, offering, TTL, TOMB, cap, json.dumps(loop_state)),
    )


def _materialize(conn, sid, user=USER, created_at=None) -> dict:
    return conn.execute(
        "SELECT * FROM public.materialize_tutor_session(%s, %s, %s, %s, %s)",
        (sid, user, TTL, TOMB, created_at),
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


def test_the_greeting_takes_the_apps_timestamp(db_conn):
    """The app stamps the greeting on the clock its next (user) row uses, so
    DB/app clock skew can never sort the user's message before it."""
    from datetime import datetime, timedelta, timezone

    stamp = datetime.now(timezone.utc) - timedelta(minutes=5)  # an app clock behind the DB
    _stash(db_conn, "tps-ts")
    assert _materialize(db_conn, "tps-ts", created_at=stamp)["outcome"] == "materialized"
    got = db_conn.execute("SELECT created_at FROM public.messages "
                          "WHERE session_id = 'tps-ts'").fetchone()["created_at"]
    assert got == stamp
    _stash(db_conn, "tps-ts2")  # NULL: the DB clock, as before
    _materialize(db_conn, "tps-ts2")
    assert db_conn.execute("SELECT created_at FROM public.messages "
                           "WHERE session_id = 'tps-ts2'").fetchone()["created_at"] is not None


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
            db_conn.execute("SELECT * FROM public.materialize_tutor_session('x', 'y', 1, 1, now())")
        raise psycopg.Rollback(tx)


def test_the_migration_is_safe_to_apply_again(db_conn):
    _stash(db_conn, "tps-again")
    with db_conn.transaction() as tx:
        db_conn.execute(_MIGRATION.read_text())
        assert _state(db_conn, "tps-again") == "pending"
        raise psycopg.Rollback(tx)


# ── learning-loop sessions (20261111030007_tutor_pending_loop_state.sql) ──


def test_a_loop_session_materialises_with_its_starting_document(db_conn):
    doc = {"phase": "teach", "origin": "quiz_ask", "concept": "n1",
           "plan": {"approved": ["n1"], "cursor": 0}, "goal": {"text_encrypted": "ENC:g"}}
    _stash(db_conn, "tps-loop", offering="rich-off-cs101-f25", loop_state=doc)
    assert _materialize(db_conn, "tps-loop")["outcome"] == "materialized"
    row = db_conn.execute("SELECT loop_state, loop_state_rev, offering_id FROM public.sessions "
                          "WHERE id = 'tps-loop'").fetchone()
    assert (row["loop_state"], row["loop_state_rev"], row["offering_id"]) == (
        doc, 0, "rich-off-cs101-f25")


def test_a_tutor_session_and_an_empty_loop_document_get_the_column_default(db_conn):
    _stash(db_conn, "tps-tutor")
    _stash(db_conn, "tps-probe", loop_state={})
    assert db_conn.execute("SELECT loop_state FROM public.tutor_pending_sessions "
                           "WHERE session_id = 'tps-tutor'").fetchone()["loop_state"] is None
    for sid in ("tps-tutor", "tps-probe"):
        assert _materialize(db_conn, sid)["outcome"] == "materialized"
        assert db_conn.execute("SELECT loop_state FROM public.sessions WHERE id = %s",
                               (sid,)).fetchone()["loop_state"] == {}


def test_a_tombstone_keeps_no_loop_document(db_conn):
    _stash(db_conn, "tps-loop-end", loop_state={"phase": "probe", "goal": {"text_encrypted": "x"}})
    assert _discard(db_conn, "tps-loop-end", "ended", only_if_pending=True) is True
    assert db_conn.execute("SELECT loop_state FROM public.tutor_pending_sessions "
                           "WHERE session_id = 'tps-loop-end'").fetchone()["loop_state"] is None


def test_a_loop_document_must_be_an_object(db_conn):
    with db_conn.transaction() as tx:
        with pytest.raises(psycopg.errors.CheckViolation):
            _stash(db_conn, "tps-bad", loop_state=["not", "an", "object"])
        raise psycopg.Rollback(tx)


def test_one_stash_function_so_a_call_by_name_is_never_ambiguous(db_conn):
    """PostgREST calls by argument name: the old 12-argument function was
    replaced, not overloaded, and its 12 names still resolve (the 13th has a
    default), so the previous release keeps working during a deploy."""
    rows = db_conn.execute(
        "SELECT pg_get_function_identity_arguments(p.oid) AS args FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.proname = 'stash_tutor_session'").fetchall()
    assert len(rows) == 1 and rows[0]["args"].endswith("p_loop_state jsonb")
    db_conn.execute(
        "SELECT public.stash_tutor_session(p_session_id => 'tps-named', p_user_id => %s, "
        "p_mode => 'socratic', p_topic => 'T', p_course_id => 'c1', p_offering_id => '', "
        "p_use_shared_context => true, p_assistant_reply => 'ENC:g', p_graph_update => NULL, "
        "p_ttl_seconds => %s, p_tombstone_ttl_seconds => %s, p_max_entries => %s)",
        (USER, TTL, TOMB, CAP))
    assert _state(db_conn, "tps-named") == "pending"


def test_the_loop_migration_is_safe_to_apply_again(db_conn):
    _stash(db_conn, "tps-loop-again", loop_state={"phase": "probe"})
    with db_conn.transaction() as tx:
        db_conn.execute(_LOOP_MIGRATION.read_text())
        assert _materialize(db_conn, "tps-loop-again")["outcome"] == "materialized"
        assert db_conn.execute("SELECT loop_state FROM public.sessions WHERE id = 'tps-loop-again'"
                               ).fetchone()["loop_state"] == {"phase": "probe"}
        raise psycopg.Rollback(tx)


def test_the_loop_functions_stay_service_only(db_conn):
    with db_conn.transaction() as tx:
        db_conn.execute("SET LOCAL ROLE authenticated")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute("SELECT public.stash_tutor_session('x', 'y', 'm', 't', 'c', '', true, "
                            "'g', NULL, 1, 1, 1, '{}'::jsonb)")
        raise psycopg.Rollback(tx)
