"""scripts/backfill_document_index_status.py — tells the truth about each
document that predates #482, once.

The migration defaults every existing row to 'skipped', deliberately inert, so
the sweeper cannot claim a historical row before anything has said what is
actually true of it. This script says it, from what is really in
course_chunks — no embedding, no re-classification.
"""
import importlib
import sys

import pytest

MAX = 3


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop("scripts.backfill_document_index_status", None)
    module = importlib.import_module("scripts.backfill_document_index_status")
    yield module
    sys.modules.pop("scripts.backfill_document_index_status", None)


# ── the rule ────────────────────────────────────────────────────────────────


def test_a_document_with_chunks_is_indexed(mod):
    assert mod.derive(has_text=True, chunk_count=31) == {
        "index_status": "indexed", "index_chunk_count": 31}


def test_a_document_with_text_but_no_chunks_is_pending(mod):
    """The sweeper will pick it up."""
    assert mod.derive(has_text=True, chunk_count=0) == {"index_status": "pending"}


def test_a_document_without_text_is_terminally_failed(mod):
    """Prod has two. Visible as failed, and spent so the sweeper never tries."""
    assert mod.derive(has_text=False, chunk_count=0) == {
        "index_status": "failed", "index_error": "no_extracted_text",
        "index_attempts": MAX}


def test_chunks_win_over_missing_text(mod):
    """Chunks are what retrieval serves; if they exist, the document IS
    indexed, whatever happened to its source text since."""
    assert mod.derive(has_text=False, chunk_count=4)["index_status"] == "indexed"


# ── the run ─────────────────────────────────────────────────────────────────


class _Handle:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def update(self, data, filters, *, prefer_return_minimal=False):
        self.db.writes.append((dict(data), dict(filters)))
        return []


class FakeDB:
    def __init__(self, with_text, without_text, chunk_doc_ids):
        self.with_text = with_text
        self.without_text = without_text
        self.chunk_doc_ids = chunk_doc_ids
        self.reads: list[tuple[str, str, dict]] = []
        self.writes: list[tuple[dict, dict]] = []

    def table(self, name):
        return _Handle(self, name)

    def page_all(self, handle, columns="*", *, filters=None, order):
        self.reads.append((handle.name, columns, dict(filters or {})))
        if handle.name == "course_chunks":
            return iter({"doc_id": d} for d in self.chunk_doc_ids)
        if (filters or {}).get("extracted_text") == "not.is.null":
            return iter({"id": d} for d in self.with_text)
        return iter({"id": d} for d in self.without_text)


@pytest.fixture
def prod_like(mod, monkeypatch):
    """Prod as measured 2026-09-21: 5 indexed practice exams, 2 with no text."""
    db = FakeDB(
        with_text=["e1", "e2", "e3", "e4", "e5"],
        without_text=["n1", "n2"],
        chunk_doc_ids=["e1"] * 7 + ["e2"] * 6 + ["e3"] * 6 + ["e4"] * 6 + ["e5"] * 6,
    )
    monkeypatch.setattr(mod, "page_all", db.page_all)
    monkeypatch.setattr(mod, "table", db.table)
    return db


def test_dry_run_is_the_default_and_writes_nothing(mod, prod_like):
    summary = mod.main([])
    assert prod_like.writes == []
    assert summary == {"indexed": 5, "pending": 0, "failed": 2}


def test_apply_reaches_the_measured_prod_outcome(mod, prod_like):
    summary = mod.main(["--apply"])

    assert summary == {"indexed": 5, "pending": 0, "failed": 2}
    by_status = {}
    for data, _ in prod_like.writes:
        by_status.setdefault(data["index_status"], 0)
        by_status[data["index_status"]] += 1
    assert by_status == {"indexed": 5, "failed": 2}


def test_only_never_attempted_default_rows_are_touched(mod, prod_like):
    """A status the new code wrote must never be clobbered — including function
    mode's DESIGNED 'skipped', which spent an attempt (index_attempts=1) and so
    is told apart from the migration default (0)."""
    mod.main(["--apply"])

    doc_reads = [f for name, _, f in prod_like.reads if name == "documents"]
    for filters in doc_reads:
        assert filters["index_status"] == "eq.skipped"
        assert filters["index_attempts"] == "eq.0"
        assert filters["deleted_at"] == "is.null"
    for _, filters in prod_like.writes:
        assert filters["index_status"] == "eq.skipped"
        assert filters["index_attempts"] == "eq.0"


def test_it_never_reads_document_text(mod, prod_like):
    """Presence is a filter, not a read: pulling every document's ciphertext to
    test it for null would be the whole table's text over the wire."""
    mod.main([])
    for name, columns, _ in prod_like.reads:
        if name == "documents":
            assert columns == "id"


def test_catalog_chunks_are_not_counted(mod, prod_like):
    mod.main([])
    (chunk_filters,) = [f for name, _, f in prod_like.reads if name == "course_chunks"]
    assert chunk_filters["doc_id"] == "not.is.null"
    assert chunk_filters["category"] == "neq.catalog"


def test_a_second_run_finds_nothing(mod, monkeypatch):
    """Idempotent by construction: the first run moved every row off the
    default, and the filters only ever match the default."""
    db = FakeDB(with_text=[], without_text=[], chunk_doc_ids=[])
    monkeypatch.setattr(mod, "page_all", db.page_all)
    monkeypatch.setattr(mod, "table", db.table)

    assert mod.main(["--apply"]) == {"indexed": 0, "pending": 0, "failed": 0}
    assert db.writes == []
