"""Spec §13 A138 / A139: the student's text from the teach-prompts migration
(20261108184825_learning_teach_prompts.sql) is in the ciphertext oracle, and the
admin report's field on GET /api/admin/analytics/learning-loop. The migration's
tables, CHECKs and privileges are proven on real Postgres in
tests/integration/test_teach_prompts_db.py and test_rls_lockdown_db.py."""

from __future__ import annotations

from unittest.mock import patch


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
