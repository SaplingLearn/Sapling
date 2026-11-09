"""Spec §13 A138 / A139: the migration that stores an answered prequestion and
a served self-explanation prompt (20261108184825_learning_teach_prompts.sql) —
new tables only, the student's text only in encrypted columns, backend-only
with the backend holding only what it uses — and the admin report's field on
GET /api/admin/analytics/learning-loop. The real-Postgres proof is
tests/integration/test_teach_prompts_db.py."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
MIG_DIR = BACKEND / "db" / "migrations"


def _body() -> str:
    (path,) = sorted(MIG_DIR.glob("*_learning_teach_prompts.sql"))
    assert re.fullmatch(r"\d{14}_learning_teach_prompts\.sql", path.name)
    return "\n".join(ln for ln in path.read_text().splitlines() if not ln.lstrip().startswith("--"))


def test_new_tables_only_and_nothing_else_changes():
    body = _body().upper()
    assert body.count("CREATE TABLE IF NOT EXISTS") == 2
    for forbidden in ("DROP TABLE", "DROP COLUMN", "RENAME", "ALTER COLUMN", "UPDATE LEARNING", "UPDATE PUBLIC",
                      "DELETE FROM", "CREATE OR REPLACE FUNCTION", "ADD COLUMN"):
        assert forbidden not in body, forbidden
    assert re.findall(r"\bUPDATE\b", body) == ["UPDATE"], "only the self-explanation table's GRANT"


def test_one_answered_prequestion_per_student_session_and_concept():
    body = _body()
    assert "UNIQUE (user_id, session_id, node_id)" in body
    assert "CHECK (no_idea = (guess_json IS NULL))" in body
    assert "user_id       text        NOT NULL REFERENCES users(id) ON DELETE CASCADE" in body


def test_a_prompt_row_closes_only_as_replied_or_skipped_and_a_reply_carries_its_length():
    body = _body()
    assert "CHECK (status IN ('open', 'replied', 'skipped'))" in body
    assert "CHECK ((status = 'replied') = (reply_text IS NOT NULL))" in body
    assert "CHECK ((status = 'replied') = (reply_chars IS NOT NULL))" in body
    assert "CHECK (juncture IN ('worked_example', 'released_solution', 'first_correct'))" in body


def test_backend_only_with_only_the_privileges_it_uses():
    body = _body()
    for table in ("learning_prequestions", "learning_self_explanations"):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" in body
        assert f"REVOKE ALL ON TABLE {table} FROM PUBLIC;" in body
        assert f"REVOKE ALL ON TABLE {table} FROM service_role;" in body
    assert "GRANT SELECT, INSERT ON TABLE learning_prequestions TO service_role;" in body
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE learning_self_explanations TO service_role;" in body
    assert "NOTIFY pgrst, 'reload schema';" in body


def test_the_student_text_columns_are_in_the_ciphertext_oracle():
    from e2e_oracles.gather import _CIPHERTEXT_MANIFEST

    assert ("learning_prequestions", "id", "guess_json") in _CIPHERTEXT_MANIFEST
    assert ("learning_self_explanations", "id", "reply_text") in _CIPHERTEXT_MANIFEST


# ── the admin report's field (A139) ────────────────────────────────────────


def test_the_admin_field_reads_the_prompts_never_the_reply_and_survives_a_failed_read():
    from services.admin.analytics import learning_loop as aa  # spec §13 A149

    prompts = [{"id": "p1", "user_id": "u1", "node_id": "n1", "question_hash": "q1", "juncture": "worked_example",
                "prompted_at": "2026-11-08T10:00:00+00:00", "status": "replied", "reply_chars": 12}]
    valid = [{"node_id": "n1", "question_hash": "q2", "created_at": "2026-11-08T10:05:00+00:00",
              "correct": True, "assisted": False, "max_rung": 0}]
    with patch.object(aa, "_scan_range", return_value=(prompts, False)) as scan:
        report = aa._self_explanation(valid, "2026-11-01T00:00:00+00:00", "2026-11-09T00:00:00+00:00")
    table_name, columns = scan.call_args.args[:2]
    assert table_name == "learning_self_explanations" and "reply_text" not in columns.split(",")
    assert scan.call_args.kwargs["time_column"] == "prompted_at"
    assert report.shown == 1 and report.reply_rate == 1.0 and report.reply_chars.median == 12
    assert report.next_item.replied.unassisted == 1 and report.next_item.replied.n == 1
    with patch.object(aa, "_scan_range", side_effect=RuntimeError("down")):
        assert aa._self_explanation(valid, "a", "b") is None


def test_the_learning_loop_report_carries_the_field():
    from routes.admin_analytics import LearningLoopKpis

    assert "self_explanation" in LearningLoopKpis.model_fields
    assert LearningLoopKpis.model_fields["self_explanation"].default is None
