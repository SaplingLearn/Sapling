"""A deleted session's teach-prompt text and a deleted node's loop rows go,
real-DB half (PR #866 C8/C9; 20261118195124_learning_session_node_erase.sql).

The hermetic suites (tests/test_learn_session_ownership.py,
tests/test_graph_delete_node_loop_rows.py) check what the app ASKS for; this
checks what Postgres does with it, where the grants decide: service_role
holds no UPDATE on learning_prequestions and no DELETE on either teach-prompt
table, so only the two SECURITY DEFINER functions can clear them, and the
relaxed CHECKs must allow the cleared state for an erased row only.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _seed(db_conn, uid: str) -> None:
    x = db_conn.execute
    for session, node in (("s1", "n1"), ("s1", "n2"), ("s2", "n1")):
        x("INSERT INTO learning_prequestions (user_id, session_id, node_id, question_hash, format, "
          "difficulty, no_idea, guess_json, posed_at) VALUES (%s, %s, %s, 'qh', 'free', 1, false, "
          "'enc-guess', now())", (uid, f"{uid}-{session}", f"{uid}-{node}"))
        x("INSERT INTO learning_self_explanations (id, user_id, session_id, node_id, juncture, "
          "prompted_at, status, closed_at, reply_text, reply_chars) VALUES (%s, %s, %s, %s, "
          "'first_correct', now(), 'replied', now(), 'enc-reply', 9)",
          (f"{uid}-{session}-{node}", uid, f"{uid}-{session}", f"{uid}-{node}"))


def _texts(db_conn, uid: str) -> dict:
    pq = db_conn.execute(
        "SELECT session_id, node_id, guess_json, no_idea, text_erased_at IS NOT NULL AS erased "
        "FROM learning_prequestions WHERE user_id = %s ORDER BY 1, 2", (uid,)).fetchall()
    se = db_conn.execute(
        "SELECT session_id, node_id, reply_text, status, reply_chars, "
        "text_erased_at IS NOT NULL AS erased FROM learning_self_explanations "
        "WHERE user_id = %s ORDER BY 1, 2", (uid,)).fetchall()
    return {"pq": [dict(r) for r in pq], "se": [dict(r) for r in se]}


def test_the_session_erase_clears_one_sessions_text_and_keeps_the_rows(db_conn, seeded_user):
    from db.connection import rpc

    me, other = seeded_user(), seeded_user()
    _seed(db_conn, me)
    _seed(db_conn, other)
    before_other = _texts(db_conn, other)

    out = rpc("learning_session_text_erase", {"p_user_id": me, "p_session_id": f"{me}-s1"})

    assert out == {"learning_prequestions": 2, "learning_self_explanations": 2}
    texts = _texts(db_conn, me)
    for kind, column in (("pq", "guess_json"), ("se", "reply_text")):
        for row in texts[kind]:
            gone = row["session_id"] == f"{me}-s1"
            assert row["erased"] is gone and (row[column] is None) is gone, row
    # the release record and the report's columns stay (A76, the admin report)
    assert all(r["no_idea"] is False for r in texts["pq"])
    assert all(r["status"] == "replied" and r["reply_chars"] == 9 for r in texts["se"])
    assert _texts(db_conn, other) == before_other
    again = rpc("learning_session_text_erase", {"p_user_id": me, "p_session_id": f"{me}-s1"})
    assert again == {"learning_prequestions": 0, "learning_self_explanations": 0}


def test_the_node_erase_deletes_one_nodes_rows_only(db_conn, seeded_user):
    from db.connection import rpc

    me, other = seeded_user(), seeded_user()
    _seed(db_conn, me)
    _seed(db_conn, other)

    out = rpc("learning_node_erase", {"p_user_id": me, "p_node_id": f"{me}-n1"})

    assert out == {"learning_prequestions": 2, "learning_self_explanations": 2}
    texts = _texts(db_conn, me)
    assert {r["node_id"] for r in texts["pq"] + texts["se"]} == {f"{me}-n2"}
    assert len(_texts(db_conn, other)["pq"]) == 3


def test_the_cleared_state_is_allowed_only_for_an_erased_row(db_conn, seeded_user):
    import psycopg

    me = seeded_user()
    _seed(db_conn, me)
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute("UPDATE learning_prequestions SET guess_json = NULL WHERE user_id = %s", (me,))
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute("UPDATE learning_self_explanations SET reply_text = NULL WHERE user_id = %s", (me,))


def test_both_functions_are_service_role_only_and_the_records_stay_append_only(db_conn):
    for fn in ("learning_session_text_erase(text, text)", "learning_node_erase(text, text)"):
        rows = db_conn.execute(
            "SELECT r.role, has_function_privilege(r.role, %s, 'EXECUTE') AS ok "
            "FROM unnest(ARRAY['anon', 'authenticated', 'service_role']) r(role) "
            "WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r.role)", (f"public.{fn}",)
        ).fetchall()
        if {r["role"] for r in rows} != {"anon", "authenticated", "service_role"}:
            pytest.skip("needs the Supabase roles")
        assert {r["role"]: r["ok"] for r in rows} == {
            "anon": False, "authenticated": False, "service_role": True,
        }, fn
    for t, priv in (("learning_prequestions", "UPDATE"), ("learning_prequestions", "DELETE"),
                    ("learning_self_explanations", "DELETE")):
        assert db_conn.execute(
            "SELECT has_table_privilege('service_role', %s, %s) AS ok", (f"public.{t}", priv)
        ).fetchone()["ok"] is False, (t, priv)
    with pytest.raises(Exception, match="needs a user id"):
        db_conn.execute("SELECT learning_node_erase('u', '  ')")
