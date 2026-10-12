"""Unit coverage for scripts/backfill_summary_docs.py's idempotency guard —
the part most likely to regress silently (re-backfilling a document every
run, duplicating its summary doc)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import backfill_summary_docs as script  # noqa: E402


class TestAlreadyBackfilledDocumentIds:
    def test_excludes_documents_that_already_have_a_summary_doc(self):
        with patch.object(script, "table") as mock_table, \
             patch.object(script, "page_all", return_value=[
                 {"primary_document_id": "doc1"},
                 {"primary_document_id": "doc2"},
             ]):
            result = script._already_backfilled_document_ids()
        mock_table.assert_called_once_with("summary_docs")
        assert result == {"doc1", "doc2"}


class TestMainSkipsAlreadyBackfilled:
    def test_second_run_backfills_nothing(self):
        candidates = [
            {"id": "doc1", "user_id": "u1", "summary": "ciphertext-a"},
            {"id": "doc2", "user_id": "u1", "summary": "ciphertext-b"},
        ]
        with (
            patch.object(script, "_documents_with_summary", return_value=candidates),
            patch.object(script, "_already_backfilled_document_ids", return_value={"doc1", "doc2"}),
            patch.object(script, "create_summary_doc") as mock_create,
            patch("builtins.print"),
        ):
            script.main([])
        mock_create.assert_not_called()
