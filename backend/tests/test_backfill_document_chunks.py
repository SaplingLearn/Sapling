"""scripts/backfill_document_chunks.py — the recovery path for documents whose
post-upload indexing never landed (#482, #628)."""
import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def backfill(monkeypatch):
    # The script runs `load_dotenv(".env.staging")` at import. Neutralise it so
    # importing it here can never point this process at a live project.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop("scripts.backfill_document_chunks", None)
    module = importlib.import_module("scripts.backfill_document_chunks")
    yield module
    sys.modules.pop("scripts.backfill_document_chunks", None)


def _table_for(docs):
    def _table(name):
        m = MagicMock()
        if name == "documents":
            m.select.side_effect = lambda cols, filters=None, **k: (
                [] if (filters or {}).get("extracted_text") == "is.null" else docs
            )
        elif name == "course_chunks":
            m.select.return_value = []  # nothing indexed yet
        elif name == "course_offerings":
            m.select.return_value = [{"course_id": "course-uuid-1"}]
        elif name == "courses":
            m.select.return_value = [{"course_code": "CAS CS 132"}]
        return m
    return _table


DOC = {
    "id": "doc-0001-aaaa", "file_name": "hw1.pdf", "user_id": "u1",
    "offering_id": "off-1", "extracted_text": "ciphertext", "category": "assignment",
}


def test_zero_indexed_chunks_is_a_failure_not_an_ok(backfill, monkeypatch, capsys):
    """`index_document_chunks` swallows embed errors and returns 0 (a bad or
    over-quota key, or SAPLING_MODEL_MODE=function still exported from an e2e
    cycle). Counting that as `ok` made a run that indexed NOTHING end with
    "Done: 5 ok, 0 failed" — on the script whose whole job is recovery."""
    monkeypatch.setattr(sys, "argv", ["backfill_document_chunks.py"])
    with (
        patch.object(backfill, "table", side_effect=_table_for([DOC])),
        patch.object(backfill, "decrypt_if_present", return_value="plain text"),
        patch.object(backfill, "chunk_for_category", return_value=["chunk one"]),
        patch.object(backfill, "course_relevance", return_value=None),
        patch.object(backfill, "index_document_chunks", return_value=0),
        patch.object(backfill.time, "sleep"),
        pytest.raises(SystemExit) as exit_info,
    ):
        backfill.main()

    out = capsys.readouterr().out
    assert exit_info.value.code == 1
    assert "FAIL" in out
    assert "0 ok" in out and "1 failed" in out


def test_indexed_chunks_count_as_ok(backfill, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["backfill_document_chunks.py"])
    with (
        patch.object(backfill, "table", side_effect=_table_for([DOC])),
        patch.object(backfill, "decrypt_if_present", return_value="plain text"),
        patch.object(backfill, "chunk_for_category", return_value=["chunk one"]),
        patch.object(backfill, "course_relevance", return_value=0.6),
        patch.object(backfill, "index_document_chunks", return_value=1),
        patch.object(backfill.time, "sleep"),
    ):
        backfill.main()

    out = capsys.readouterr().out
    assert "1 chunks indexed" in out
    assert "1 ok" in out and "0 failed" in out
