"""PR #866 Z11: every reader that hands a document row to `source_chunks` reads
the share screen's STORED verdict (`documents.share_block_reason`).

services/share_screen.py: a stored reason always wins, so loosening a rule
never publishes a document an earlier screen kept private. A row read without
the column carries no stored reason, and only a fresh screen of the text
decides — so the nightly drafting backfill could draft class-wide items from a
document the screen held at upload (injected instructions, a student's graded
answers) once a rule was narrowed. One column list, `SOURCE_DOCUMENT_COLUMNS`,
is what every such reader selects."""

from __future__ import annotations

import importlib
import sys

import pytest

from services import check_item_service as svc
from services import chunk_visibility
from services.encryption import bind, encrypt_if_present

#: A rule code the screen stored at upload; the text itself passes a fresh
#: screen (the rule was narrowed since).
_STORED_BLOCK = "ai_directed_text:override"


def _held_upload() -> dict:
    """A course-material upload the share screen held at upload, unindexed."""
    row = {
        "id": "doc-1",
        "user_id": "u1",
        "offering_id": "off-1",
        "shareability": "course_material",
        "shareability_confidence": 0.97,
        "share_block_reason": _STORED_BLOCK,
        "index_status": "failed",
        "deleted_at": None,
    }
    row["extracted_text"] = encrypt_if_present(
        "Gradient descent moves each parameter by the learning rate times its gradient.",
        bind=bind("documents", "extracted_text", row),
    )
    return row


class _Documents:
    """`documents` as PostgREST serves it: each read returns the selected
    columns only, and records which ones it was asked for."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.columns: list[str] = []

    def _project(self, columns: str) -> list[dict]:
        self.columns.append(columns)
        names = columns.split(",")
        return [{c: r.get(c) for c in names} for r in self.rows]

    def select(self, columns, filters=None, order=None, limit=None):
        return self._project(columns)

    def select_with_count(self, columns, filters=None, order=None, limit=None, offset=None):
        rows = self._project(columns) if not offset else []
        return rows, len(rows)


@pytest.fixture
def backfill(monkeypatch):
    """scripts/backfill_check_items.py, its load_dotenv(".env.staging")
    neutralised (tests/test_learning_check_items.py's fixture)."""
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop("scripts.backfill_check_items", None)
    module = importlib.import_module("scripts.backfill_check_items")
    yield module
    sys.modules.pop("scripts.backfill_check_items", None)


@pytest.fixture
def consenting_uploader(monkeypatch):
    """The uploader shares class context, and the document has no chunks
    (its indexing failed): only the screen can keep it out of the pool."""
    monkeypatch.setattr(chunk_visibility, "visibility_for", lambda _uid: chunk_visibility.SHARED)
    monkeypatch.setattr(svc, "chunks_for_document", lambda _doc_id: [])


def test_the_drafting_backfill_honours_a_block_stored_at_upload(backfill, consenting_uploader, monkeypatch):
    docs = _Documents([_held_upload()])
    monkeypatch.setattr(backfill, "table", lambda name: docs)

    rows = backfill._source_documents(["off-1"])

    assert [svc.source_chunks(row) for row in rows] == [[]]  # never an item source
    assert docs.columns == [svc.SOURCE_DOCUMENT_COLUMNS]


def test_the_key_backfill_and_the_upload_read_the_same_columns(consenting_uploader, monkeypatch):
    docs = _Documents([_held_upload()])
    monkeypatch.setattr(svc, "table", lambda name: docs)

    rows = svc._source_rows(["doc-1"])
    assert [svc.source_chunks(row) for row in rows] == [[]]
    svc._generate_for_document(
        "doc-1", user_id="u1", course_id="c-1", concept_names=["Learning rate"], flex=True
    )

    assert docs.columns == [svc.SOURCE_DOCUMENT_COLUMNS] * 2
    assert {"share_block_reason", "index_status"} <= set(svc.SOURCE_DOCUMENT_COLUMNS.split(","))
