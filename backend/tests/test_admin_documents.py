"""/api/admin/documents — the "visible to admins" half of #482.

A failed index used to be a WARNING in a background thread behind a
healthy-looking documents row. These endpoints list what is stuck and let an
operator force one document back through the shared entry point.
"""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import routes.admin_documents as admin_documents
from main import app
from services.document_indexing import IndexOutcome

client = TestClient(app)
BASE = "/api/admin/documents"

STUCK = {
    "id": "doc-1", "file_name": "hw4.pdf", "category": "assignment",
    "offering_id": "off-1", "created_at": "2026-09-20T10:00:00Z",
    "index_status": "failed", "index_attempts": 3, "index_error": "ClientError",
    "index_chunk_count": 0, "index_leased_at": None,
}


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(admin_documents, "require_admin", lambda request: None)


@pytest.fixture
def listed(monkeypatch):
    seen = {}

    def fake_page_all(handle, columns="*", *, filters=None, order):
        seen.update(columns=columns, filters=filters, order=order)
        return iter([dict(STUCK)])

    monkeypatch.setattr(admin_documents, "page_all", fake_page_all)
    monkeypatch.setattr(admin_documents, "table", lambda name: object())
    return seen


@pytest.fixture
def exists(monkeypatch):
    class _T:
        def select(self, *a, **k):
            return [{"id": "doc-1"}]
    monkeypatch.setattr(admin_documents, "table", lambda name: _T())


def _deny(request):
    raise HTTPException(status_code=403, detail="Admin access required")


# ── gating ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("method,path", [
    ("get", f"{BASE}/unindexed"),
    ("post", f"{BASE}/doc-1/reindex"),
])
def test_both_endpoints_are_admin_only(monkeypatch, method, path):
    monkeypatch.setattr(admin_documents, "require_admin", _deny)
    called = []
    monkeypatch.setattr(admin_documents, "index_document",
                        lambda *a, **k: called.append(1))

    assert getattr(client, method)(path).status_code == 403
    assert called == []


# ── the stuck list ──────────────────────────────────────────────────────────


def test_lists_documents_that_did_not_finish(admin, listed):
    body = client.get(f"{BASE}/unindexed").json()

    assert body["count"] == 1
    row = body["documents"][0]
    assert row["id"] == "doc-1"
    assert row["index_status"] == "failed"
    assert row["index_error"] == "ClientError"
    assert body["max_attempts"] == 3


def test_an_exhausted_document_is_flagged(admin, listed):
    """Attempts at the budget means the sweeper will never retry it again —
    the one thing an operator most needs to see."""
    row = client.get(f"{BASE}/unindexed").json()["documents"][0]
    assert row["exhausted"] is True


def test_only_unfinished_live_documents_are_read(admin, listed):
    client.get(f"{BASE}/unindexed")

    assert listed["filters"]["index_status"] == "in.(pending,indexing,partial,failed)"
    assert listed["filters"]["deleted_at"] == "is.null"


def test_no_encrypted_or_content_column_is_read(admin, listed):
    """The ops list has no business carrying document content. Selecting it
    would also decrypt nothing and ship ciphertext to the browser."""
    client.get(f"{BASE}/unindexed")

    columns = listed["columns"]
    for col in ("extracted_text", "summary", "concept_notes", "flashcards", "*"):
        assert col not in columns.split(","), col


def test_the_list_is_paged_past_postgrest_max_rows(admin, monkeypatch):
    """PostgREST answers past max_rows with a 206, which raise_for_status lets
    through — an unpaged read would silently truncate the list."""
    used = []
    monkeypatch.setattr(admin_documents, "page_all",
                        lambda *a, **k: used.append(1) or iter([]))
    monkeypatch.setattr(admin_documents, "table", lambda name: object())

    client.get(f"{BASE}/unindexed")

    assert used == [1]


# ── forced re-index ─────────────────────────────────────────────────────────


def test_reindex_forces_the_document_and_reports_the_outcome(admin, exists,
                                                             monkeypatch):
    seen = {}

    def fake_index(doc_id, **kw):
        seen.update(doc=doc_id, **kw)
        return IndexOutcome("indexed", 31)

    monkeypatch.setattr(admin_documents, "index_document", fake_index)

    r = client.post(f"{BASE}/doc-1/reindex")

    assert r.status_code == 200
    assert seen == {"doc": "doc-1", "force": True}
    assert r.json() == {"document_id": "doc-1", "status": "indexed",
                        "chunk_count": 31, "error": None}


def test_reindex_of_a_live_lease_is_a_conflict(admin, exists, monkeypatch):
    """force never takes a row that is being indexed right now; the operator
    needs to hear that rather than read it as success."""
    monkeypatch.setattr(admin_documents, "index_document",
                        lambda doc_id, **kw: IndexOutcome("indexing"))

    assert client.post(f"{BASE}/doc-1/reindex").status_code == 409


def test_reindex_of_an_unknown_document_is_404(admin, monkeypatch):
    class _T:
        def select(self, *a, **k):
            return []
    monkeypatch.setattr(admin_documents, "table", lambda name: _T())
    called = []
    monkeypatch.setattr(admin_documents, "index_document",
                        lambda *a, **k: called.append(1))

    assert client.post(f"{BASE}/nope/reindex").status_code == 404
    assert called == []


def test_a_failed_reindex_is_still_a_200_with_its_outcome(admin, exists,
                                                          monkeypatch):
    """The request succeeded; the document did not index. The body says which,
    so an operator can see the error class without reading logs."""
    monkeypatch.setattr(admin_documents, "index_document",
                        lambda doc_id, **kw: IndexOutcome("failed", 0, "no_extracted_text"))

    r = client.post(f"{BASE}/doc-1/reindex")

    assert r.status_code == 200
    assert r.json()["error"] == "no_extracted_text"


def test_the_list_pages_over_a_total_order(admin, listed):
    """Review round 2: page_all's offset paging needs a unique tiebreaker, or
    rows sharing a created_at can be skipped or repeated across pages."""
    client.get(f"{BASE}/unindexed")
    assert listed["order"] == "created_at.desc,id"
