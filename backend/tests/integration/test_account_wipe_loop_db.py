"""The admin account wipe erases the learning loop, real-DB half
(services/account_wipe.py, 20261111030019_learning_account_erase.sql).

The hermetic suite (tests/test_account_wipe.py) checks what the wipe ASKS
PostgREST to delete; this checks what Postgres does with it, where the loop's
grants decide: service_role holds no DELETE on learning_prequestions,
learning_self_explanations, learning_evidence_voids or misconception_attempts,
so a direct delete of any of them would fail here and pass there.

Seeds two fresh students' loop rows over psycopg, wipes one through the app
(PostgREST as service_role), reads back over psycopg (#397).
"""

from __future__ import annotations

import json
import uuid

import pytest

pytestmark = pytest.mark.integration

#: Every learning-loop table holding a student's rows, by the column naming the
#: student (misconception_attempts has none: it hangs off misconceptions).
LOOP_TABLES = (
    "learner_state", "misconceptions", "learning_evidence_voids", "posttest_poses",
    "posttest_skips", "quiz_evidence_claims", "learning_reveals", "check_item_reports",
    "learning_evidence_operations", "ai_tutor_daily_calls", "learning_prequestions",
    "learning_self_explanations",
)


def _seed_loop(db_conn, uid: str) -> None:
    node, event, mc = f"{uid}-node", f"{uid}-nme", f"{uid}-mc"
    session = f"{uid}-sess"
    x = db_conn.execute
    x("INSERT INTO graph_nodes (id, user_id, concept_name) VALUES (%s, %s, 'Recursion')",
      (node, uid))
    x("INSERT INTO node_mastery_events (id, node_id, delta, reason) VALUES (%s, %s, 0.1, 'it')",
      (event, node))
    x("INSERT INTO learner_state (user_id, node_id, p_known) VALUES (%s, %s, 0.5)", (uid, node))
    x("INSERT INTO misconceptions (id, user_id, node_id, wrong_key) VALUES (%s, %s, %s, 'no_base')",
      (mc, uid, node))
    x("INSERT INTO misconception_attempts (misconception_id, course_id) VALUES (%s, 'c')", (mc,))
    x("INSERT INTO learning_evidence_voids (event_id, user_id, node_id, course_id, question_hash, "
      "check_item_id, event_created_at, reason, operation_id) "
      "VALUES (%s, %s, %s, 'c', 'qh', 'item', now(), 'item_retired', %s)",
      (event, uid, node, str(uuid.uuid4())))
    x("INSERT INTO posttest_poses (user_id, node_id, course_id, question_hash, window_days) "
      "VALUES (%s, %s, 'c', 'qh', 7), (%s, %s, 'c', 'qh', 30)", (uid, node, uid, node))
    x("INSERT INTO posttest_skips (user_id, node_id, window_days, course_id, reason) "
      "VALUES (%s, %s, 7, 'c', 'no_items')", (uid, node))
    x("INSERT INTO quiz_evidence_claims (user_id, question_hash, attempt_id) VALUES (%s, 'qh', 'a')",
      (uid,))
    x("INSERT INTO learning_reveals (user_id, kind, question_hash, session_id) "
      "VALUES (%s, 'reveal', 'qh', %s)", (uid, session))
    x("INSERT INTO check_item_reports (user_id, question_hash, course_id, reason, surface) "
      "VALUES (%s, 'qh', 'c', 'unclear', 'loop')", (uid,))
    x("INSERT INTO learning_evidence_operations (operation_id, user_id, input_fingerprint, plan, changes) "
      "VALUES (%s, %s, %s, %s, '[]')", (str(uuid.uuid4()), uid, "0" * 64, json.dumps({})))
    x("INSERT INTO ai_tutor_daily_calls (user_id, day, calls) VALUES (%s, current_date, 3)", (uid,))
    x("INSERT INTO learning_prequestions (user_id, session_id, node_id, question_hash, format, "
      "difficulty, no_idea, posed_at) VALUES (%s, %s, %s, 'qh', 'free', 1, true, now())",
      (uid, session, node))
    x("INSERT INTO learning_self_explanations (id, user_id, session_id, node_id, juncture, prompted_at) "
      "VALUES (%s, %s, %s, %s, 'first_correct', now())", (f"{uid}-se", uid, session, node))


def _counts(db_conn, uid: str) -> dict[str, int]:
    out = {
        t: db_conn.execute(f"SELECT count(*) AS n FROM {t} WHERE user_id = %s", (uid,)).fetchone()["n"]
        for t in LOOP_TABLES
    }
    out["misconception_attempts"] = db_conn.execute(
        "SELECT count(*) AS n FROM misconception_attempts WHERE misconception_id = %s",
        (f"{uid}-mc",),
    ).fetchone()["n"]
    return out


def test_the_wipe_erases_every_loop_row_of_the_student_and_no_one_elses(db_conn, seeded_user):
    from services.account_wipe import wipe_account_data

    me, other = seeded_user(), seeded_user()
    _seed_loop(db_conn, me)
    _seed_loop(db_conn, other)
    full = _counts(db_conn, other)
    assert all(full.values()), full

    counts = wipe_account_data(me)

    assert set(_counts(db_conn, me).values()) == {0}
    assert _counts(db_conn, other) == full
    assert counts["learning_prequestions"] == 1 and counts["learning_self_explanations"] == 1
    assert counts["posttest_poses"] == 2  # two windows, one node: counted as rows
    # A second wipe finds nothing.
    again = wipe_account_data(me)
    assert not any(again.values())


def test_the_erase_rpc_is_service_role_only_and_the_records_stay_append_only(db_conn):
    rows = db_conn.execute(
        "SELECT r.role, has_function_privilege(r.role, 'public.learning_account_erase(text)', "
        "'EXECUTE') AS ok FROM unnest(ARRAY['anon', 'authenticated', 'service_role']) r(role) "
        "WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r.role)"
    ).fetchall()
    if {r["role"] for r in rows} != {"anon", "authenticated", "service_role"}:
        pytest.skip("needs the Supabase roles")
    assert {r["role"]: r["ok"] for r in rows} == {
        "anon": False, "authenticated": False, "service_role": True,
    }
    for t in ("learning_prequestions", "learning_self_explanations"):
        assert db_conn.execute(
            "SELECT has_table_privilege('service_role', %s, 'DELETE') AS ok", (f"public.{t}",)
        ).fetchone()["ok"] is False, t
    with pytest.raises(Exception, match="needs a user id"):
        db_conn.execute("SELECT learning_account_erase('  ')")
