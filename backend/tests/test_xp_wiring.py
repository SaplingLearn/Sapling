"""XP is awarded from the routes that earn it, and never breaks them."""
from unittest.mock import patch

from services.xp_service import idempotency_key


class TestIdempotencyKeys:
    def test_quiz_key_is_scoped_to_the_attempt(self):
        assert idempotency_key("quiz_completed", "quiz", "attempt-1") == \
               "quiz_completed:quiz:attempt-1"

    def test_document_key_is_scoped_to_the_document(self):
        assert idempotency_key("document_uploaded", "document", "doc-1") == \
               "document_uploaded:document:doc-1"


class TestSafety:
    def test_a_broken_ledger_does_not_raise(self):
        with patch("services.xp_service.table", side_effect=RuntimeError("db down")):
            from services.xp_service import award_xp_safe
            assert award_xp_safe("u1", "quiz_completed",
                                 source_type="quiz", source_id="q1") is None
