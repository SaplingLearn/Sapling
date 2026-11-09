"""The quiz in the learning system on the real database (learning-loop spec
§13 A143, A146, A147): what a MagicMock suite cannot show.

- A quiz misconception goes into the real `misconception_record` under the
  item id `quiz:<question_hash>` (a text column, no foreign key), with its
  supporting attempt; A127's "recorded on another item" filter then lets a
  DIFFERENT quiz question or a check item close it, never the same question.
- `exposure_before`'s journal reads (an owner-scoped embed on
  node_mastery_events, the prequestion releases) run through PostgREST.
- The concept plan and the results block read the real tables.
"""

import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.integration

USER = "rich-user-active"


def _node(db_conn) -> str:
    row = db_conn.execute(
        "SELECT id FROM graph_nodes WHERE user_id = %s ORDER BY id LIMIT 1",
        (USER,),
    ).fetchone()
    if row is None:
        pytest.skip("rich seed has no graph node for the active user")
    return row["id"]


def test_a_quiz_misconception_is_recorded_under_its_quiz_item_and_closed_only_by_another(db_conn):
    from learning.misconceptions import resolve
    from services.quiz_learning import _record, quiz_item_id

    node = _node(db_conn)
    key = f"it_{uuid.uuid4().hex[:12]}"
    question = {
        "question_hash": "itquizhash01",
        "options": [
            {"label": "A", "text": "the tempting one", "correct": False, "misconception": key},
            {"label": "B", "text": "the key", "correct": True},
        ],
    }
    from learning.misconceptions import record

    try:
        assert _record(USER, node, question, {"selected": "A"}, key, "it-req", record) == [key]
        row = db_conn.execute(
            "SELECT m.check_item_id, m.count, m.evidence_text, a.question_hash, a.check_item_id AS a_item "
            "FROM misconceptions m JOIN misconception_attempts a ON a.misconception_id = m.id "
            "WHERE m.user_id = %s AND m.wrong_key = %s",
            (USER, key),
        ).fetchone()
        assert row["check_item_id"] == quiz_item_id("itquizhash01") == row["a_item"]
        assert row["question_hash"] == "itquizhash01" and row["count"] == 1
        assert "the tempting one" not in (row["evidence_text"] or ""), "stored as ciphertext"
        # the same question is no isomorph: nothing closes
        assert resolve(USER, node, [key], by_item=quiz_item_id("itquizhash01")) == []
        # another quiz question is
        closed = resolve(USER, node, [key], by_item=quiz_item_id("itquizhash02"))
        assert [r["wrong_key"] for r in closed] == [key]
        reason = db_conn.execute(
            "SELECT resolved_reason FROM misconceptions WHERE user_id = %s AND wrong_key = %s",
            (USER, key),
        ).fetchone()
        assert reason["resolved_reason"] == "correct_unassisted_isomorph"
    finally:
        db_conn.execute("DELETE FROM misconceptions WHERE wrong_key = %s", (key,))


def test_the_journal_reads_before_a_submit_run_on_postgrest(db_conn):
    from services.quiz_learning import exposure_before

    node = _node(db_conn)
    got = exposure_before(USER, node, ["no-such-hash"], datetime.now(timezone.utc))
    assert got is not None, "the embed read and the prequestion read both answered"
    assert got.seen == frozenset()


def test_the_plan_and_the_results_read_the_real_tables(db_conn):
    from services.quiz_learning import concept_plan, results_block, skill_snapshot

    node = _node(db_conn)
    course = db_conn.execute("SELECT course_id FROM graph_nodes WHERE id = %s", (node,)).fetchone()["course_id"]
    plan = concept_plan(USER)
    assert plan, "the active student has concepts to propose"
    assert {c["reason"] for c in plan} <= {"due", "misconception", "ready"}
    before = skill_snapshot(USER, node)
    assert before is not None and before.order[0] == node
    block = results_block(USER, {"id": node, "course_id": course, "concept_name": "x"}, before)
    assert block is not None
    assert block["next_step"] in ("review", "learn", "none")
    assert block["changes"] == []  # nothing was written between the two reads
