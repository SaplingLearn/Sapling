"""scripts/backfill_document_shareability.py — must store the confidence too.

The #630 backfill runs the classifier to fill `documents.shareability` for rows
classified before #630, and kept only `.shareability` — discarding the
confidence it had in hand. But `decide_visibility` reads a missing confidence as
PRIVATE, so every row this script wrote re-indexes private: a document it
judged course material could never be re-shared by a re-index (#482 review).
It now stores `shareability_confidence` beside the answer, the same pair the
live upload stores.
"""
import importlib
import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop("scripts.backfill_document_shareability", None)
    module = importlib.import_module("scripts.backfill_document_shareability")
    yield module
    sys.modules.pop("scripts.backfill_document_shareability", None)


def _run(mod, monkeypatch, *, text, classified, offering_id="off-1"):
    doc = {"id": "doc-1", "file_name": "notes.pdf", "user_id": "u1",
           "offering_id": offering_id, "extracted_text": "ciphertext",
           "category": "lecture_notes", "shareability": None}
    updates = []
    handle = MagicMock()
    handle.update.side_effect = lambda data, filters, **k: updates.append(dict(data))

    monkeypatch.setattr(mod, "page_all", lambda *a, **k: iter([dict(doc)]))
    monkeypatch.setattr(mod, "table", lambda name: handle)
    monkeypatch.setattr(mod, "decrypt_if_present", lambda v: text)
    monkeypatch.setattr(mod, "_classify", lambda t: classified)
    monkeypatch.setattr(mod, "_course_code", lambda off: None)
    monkeypatch.setattr(sys, "argv", ["backfill_document_shareability.py", "--apply"])

    mod.main()
    return updates


def test_course_material_is_stored_with_its_confidence(mod, monkeypatch):
    updates = _run(mod, monkeypatch, text="x" * 200,
                   classified=("course_material", 0.87))

    assert updates == [{"shareability": "course_material",
                        "shareability_confidence": 0.87}]


def test_a_private_answer_is_stored_with_its_confidence(mod, monkeypatch):
    updates = _run(mod, monkeypatch, text="x" * 200,
                   classified=("completed_work", 0.93), offering_id="")

    assert updates == [{"shareability": "completed_work",
                        "shareability_confidence": 0.93}]


def test_unreadable_text_stores_no_confidence(mod, monkeypatch):
    """Nothing was classified, so there is no confidence to store — and None
    resolves private, the right answer for a document nobody could read."""
    updates = _run(mod, monkeypatch, text="too short", classified=("unused", 1.0),
                   offering_id="")

    assert updates == [{"shareability": "personal_notes",
                        "shareability_confidence": None}]


def test_classify_returns_the_models_confidence(mod, monkeypatch):
    output = MagicMock(shareability="course_material", confidence=0.71)
    monkeypatch.setattr(mod, "run_agent_sync", lambda coro: MagicMock(output=output))
    monkeypatch.setattr(mod.classifier_agent, "run", lambda *a, **k: None)

    assert mod._classify("some text") == ("course_material", 0.71)
