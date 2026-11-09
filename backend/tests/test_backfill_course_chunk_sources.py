"""scripts/backfill_course_chunk_sources.py — #758's one-off for rows that
predate the source ledger: record what live documents still produce, THEN
withdraw what deleted documents left behind."""
import importlib
import sys

import pytest

from services.encryption import encrypt_if_present
from services.rag_service import chunk_id

TEXT = "Gradient descent minimises a loss function step by step. " * 40


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop("scripts.backfill_course_chunk_sources", None)
    module = importlib.import_module("scripts.backfill_course_chunk_sources")
    yield module
    sys.modules.pop("scripts.backfill_course_chunk_sources", None)


@pytest.fixture
def world(mod, monkeypatch):
    docs = {
        False: [{"id": "live-1", "user_id": "u2", "offering_id": "off-1",
                 "extracted_text": encrypt_if_present(TEXT)}],
        True: [{"id": "gone-1", "user_id": "u1", "offering_id": "off-1",
                "extracted_text": encrypt_if_present(TEXT)}],
    }
    calls = []
    monkeypatch.setattr(mod, "_docs", lambda *, deleted: iter(docs[deleted]))
    monkeypatch.setattr(mod, "_course_code", lambda off, cache: "CAS CS 132")
    # Every derived id exists.
    monkeypatch.setattr(mod, "_existing", lambda ids: ids)
    monkeypatch.setattr(mod, "record_sources",
                        lambda ids, doc_id: calls.append(("record", doc_id, len(ids))))
    monkeypatch.setattr(mod, "withdraw_document_chunks",
                        lambda doc_id, user_id: calls.append(("withdraw", doc_id, user_id))
                        or {"chunks_deleted": 1})
    return calls


def test_derive_covers_both_namespaces(mod):
    ids = mod.derive_ids("one short passage.", "CAS CS 132", "u1")
    assert chunk_id("CAS CS 132", "one short passage.") in ids
    assert chunk_id("CAS CS 132", "one short passage.",
                    visibility="private", uploader_id="u1") in ids


def test_dry_run_is_the_default_and_writes_nothing(mod, world):
    summary = mod.main([])

    assert world == []
    assert summary["live_docs"] == 1 and summary["deleted_docs"] == 1


def test_live_sources_are_recorded_before_anything_is_withdrawn(mod, world):
    """Withdrawing first would delete shared text a live document still
    produces, because nothing would yet say that it does."""
    summary = mod.main(["--apply"])

    kinds = [c[0] for c in world]
    assert kinds == ["record", "record", "withdraw"]
    assert world[0][1] == "live-1"
    assert world[-1] == ("withdraw", "gone-1", "u1")
    assert summary["chunks_deleted"] == 1
