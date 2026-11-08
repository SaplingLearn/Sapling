"""Spec §13 A138 / A139, real-DB half: `learning_prequestions` and
`learning_self_explanations` (migration 20261108184825_learning_teach_prompts.sql)
on the local stack.

- the tables are backend-only and the backend holds only what it uses;
- the migration's SQL runs again, in a rolled-back transaction, unchanged;
- the app's own writers round-trip through PostgREST: a guess (encrypted; a
  retried answer inserts nothing new; "no idea" stores none), a served prompt
  closed with its reply (encrypted, its length) — read back via psycopg (#397);
- the CHECKs refuse a replied row without its reply and a guess beside "no idea";
- A76 across sessions reads the stored prequestion: a class-mate of its item
  graded later is a re-check.

Run inside the flock'd local-stack cycle with RUN_INTEGRATION=1."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.integration.conftest import _require_local_db_url

pytestmark = pytest.mark.integration

MIGRATION = next((Path(__file__).resolve().parents[2] / "db" / "migrations").glob("*_learning_teach_prompts.sql"))
USER = "rich-user-loop"  # seeded by db.seed_local_rich


def _privilege(conn, role: str, table: str, privilege: str) -> bool:
    return conn.execute(
        "SELECT has_table_privilege(%s, %s, %s) AS ok", (role, f"public.{table}", privilege)
    ).fetchone()["ok"]


def test_the_tables_are_backend_only_with_only_the_privileges_the_backend_uses(db_conn):
    expected = {
        "learning_prequestions": {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False, "TRUNCATE": False},
        "learning_self_explanations": {"SELECT": True, "INSERT": True, "UPDATE": True, "DELETE": False,
                                       "TRUNCATE": False},
    }
    for table, privileges in expected.items():
        row = db_conn.execute(
            "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass", (f"public.{table}",)
        ).fetchone()
        assert row["relrowsecurity"] is True, table
        for role in ("anon", "authenticated"):
            assert _privilege(db_conn, role, table, "SELECT") is False, (role, table)
        for privilege, allowed in privileges.items():
            assert _privilege(db_conn, "service_role", table, privilege) is allowed, (table, privilege)


def test_the_migration_runs_again_unchanged(db_conn):
    import psycopg
    from psycopg.rows import dict_row

    def shape(conn):
        return conn.execute(
            "SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name IN ('learning_prequestions', 'learning_self_explanations') "
            "ORDER BY table_name, column_name"
        ).fetchall()

    before = shape(db_conn)
    assert len(before) == 26
    url = (os.getenv("SUPABASE_DB_URL") or "").strip()
    _require_local_db_url(url)
    with psycopg.connect(url, row_factory=dict_row) as conn:
        try:
            conn.execute(MIGRATION.read_text(encoding="utf-8"))
            assert shape(conn) == before
        finally:
            conn.rollback()


def _item(fmt="mc_reason", difficulty=1):
    return MagicMock(id="it-item-1", question_hash=f"it-qh-{uuid.uuid4().hex[:8]}", format=fmt, difficulty=difficulty)


def test_a_guess_round_trips_encrypted_once_and_no_idea_stores_none(db_conn):
    from learning import prequestion_store as store
    from services.encryption import decrypt_json

    session = f"it-session-{uuid.uuid4().hex[:8]}"
    posed = datetime.now(timezone.utc) - timedelta(minutes=1)
    item = _item()
    for _ in range(2):  # a retried answer request inserts nothing new
        store.store_answer(user_id=USER, session_id=session, course_id="rich-course-cs101", node_id="it-node-1",
                           item=item, no_idea=False, guess={"option": "A", "reason": "it chains"}, posed_at=posed)
    store.store_answer(user_id=USER, session_id=session, course_id="rich-course-cs101", node_id="it-node-2",
                       item=_item("free", 2), no_idea=True, guess=None, posed_at=posed)
    rows = db_conn.execute(
        "SELECT node_id, no_idea, guess_json, format, difficulty FROM learning_prequestions "
        "WHERE session_id = %s ORDER BY node_id",
        (session,),
    ).fetchall()
    assert [(r["node_id"], r["no_idea"], r["format"], r["difficulty"]) for r in rows] == [
        ("it-node-1", False, "mc_reason", 1),
        ("it-node-2", True, "free", 2),
    ]
    assert "it chains" not in rows[0]["guess_json"]
    assert decrypt_json(rows[0]["guess_json"]) == {"option": "A", "reason": "it chains"}
    assert rows[1]["guess_json"] is None
    got = store.releases(USER, "it-node-1", since=posed - timedelta(hours=1))
    assert [r["shape"] for r in got] == [("mc_reason", 1)]
    assert store.evidence_since(USER, "it-node-1", posed) is False


def test_a_guess_beside_no_idea_is_refused(db_conn):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            "INSERT INTO learning_prequestions (user_id, session_id, node_id, question_hash, format, difficulty, "
            "no_idea, guess_json, posed_at) VALUES (%s, 'it-s', 'it-n', 'it-q', 'free', 1, true, 'x', now())",
            (USER,),
        )


def test_a_prompt_closes_with_its_reply_encrypted_and_its_length(db_conn):
    import psycopg

    from learning import self_explain_store as store
    from services.encryption import decrypt_if_present

    pid = uuid.uuid4().hex
    prompt = {"id": pid, "node_id": "it-node-1", "juncture": "worked_example", "question_hash": "it-q",
              "rung": 4, "prompted_at": datetime.now(timezone.utc).timestamp()}
    store.record_prompt(prompt, user_id=USER, session_id="it-session", course_id=None)
    row = db_conn.execute("SELECT status, closed_at, reply_text FROM learning_self_explanations WHERE id = %s",
                          (pid,)).fetchone()
    assert row == {"status": "open", "closed_at": None, "reply_text": None}
    store.close_prompt(prompt, user_id=USER, session_id="it-session", course_id=None,
                       reply="Each step halves it.", closed_at=datetime.now(timezone.utc))
    row = db_conn.execute(
        "SELECT status, reply_text, reply_chars, juncture, rung FROM learning_self_explanations WHERE id = %s", (pid,)
    ).fetchone()
    assert row["status"] == "replied" and row["reply_chars"] == len("Each step halves it.")
    assert row["juncture"] == "worked_example" and row["rung"] == 4
    assert "halves" not in row["reply_text"] and decrypt_if_present(row["reply_text"]) == "Each step halves it."
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute("UPDATE learning_self_explanations SET reply_text = NULL WHERE id = %s", (pid,))


def test_a_class_mate_graded_after_a_stored_prequestion_is_a_recheck(db_conn):
    from learning import prequestion_store as store
    from learning.misconceptions import recheck_after_release

    node = f"it-node-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    store.store_answer(user_id=USER, session_id=f"it-s-{node}", course_id=None, node_id=node,
                       item=_item("free", 1), no_idea=True, guess=None, posed_at=now - timedelta(minutes=2))
    mate = MagicMock(question_hash="other", format="free", difficulty=1)
    other = MagicMock(question_hash="other", format="teachback", difficulty=3)
    assert recheck_after_release(USER, node, {}, now=now, item=mate) is True
    # no evidence on the node since: the next item after it, whatever its class
    assert recheck_after_release(USER, node, {}, now=now, item=other) is True
    later = now + timedelta(hours=25)  # outside RECHECK_RELEASE_WINDOW_HOURS
    assert recheck_after_release(USER, node, {}, now=later, item=mate) is False
