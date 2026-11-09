"""routes/documents.py's CRUD handlers on the async DB seam (#117; wave 4 of
docs/design/async-db-client.md §4.1).

GET /user/{id}, DELETE /doc/{id} and PATCH /doc/{id} are `async def` over the
`a*` twins (the offering->course resolve and the chunk withdrawal hop to a
worker thread); the two upload routes validate the user on the seam too. End
to end over the REAL ``SupabaseTable`` onto an ``httpx.MockTransport`` (the
``wire`` fixture: ``no_sync_db_on_loop`` on, and no sync PostgREST request may
leave from an event-loop thread), with ``async_db_client`` off and on.
"""
from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import routes.documents as documents_routes
from tests.doc_patches import patch_documents
from main import app
from tests.test_async_handlers_off_loop import Wire, wire  # noqa: F401 (fixture)

client = TestClient(app)


def test_crud_handlers_are_async_and_the_scans_stay_sync():
    for name in ("list_documents", "delete_document", "update_document",
                 "upload_document", "upload_document_sync"):
        assert inspect.iscoroutinefunction(getattr(documents_routes, name)), name
    # The scans drive an agent through run_agent_sync: plain def.
    for name in ("scan_document_concepts", "scan_course_concepts"):
        assert not inspect.iscoroutinefunction(getattr(documents_routes, name)), name


def _mode(w: Wire, mode: str, native: set[tuple[str, str]]) -> None:
    if mode == "on":
        assert native <= set(w.native)
    else:
        assert w.native == []
        assert native <= {(m, n) for m, n, _ in w.calls}


@pytest.mark.parametrize("async_mode", ["off", "on"])
def test_list_documents(wire, monkeypatch, async_mode):  # noqa: F811
    monkeypatch.setenv("SAPLING_FLAG_ASYNC_DB_CLIENT", async_mode)
    wire.rows[("GET", "users")] = [{"id": "u1"}]
    wire.rows[("GET", "documents")] = [
        {"id": "d1", "offering_id": "off-1", "summary": "s", "concept_notes": None},
        {"id": "d2", "offering_id": "off-1", "summary": None, "concept_notes": None},
    ]
    with patch_documents("offering_course_id", return_value="c1") as resolve:
        r = client.get("/api/documents/user/u1")
    assert r.status_code == 200, r.text
    assert [d["course_id"] for d in r.json()["documents"]] == ["c1", "c1"]
    resolve.assert_called_once_with("off-1")
    _mode(wire, async_mode, {("GET", "users"), ("GET", "documents")})


@pytest.mark.parametrize("async_mode", ["off", "on"])
def test_delete_document(wire, monkeypatch, async_mode):  # noqa: F811
    monkeypatch.setenv("SAPLING_FLAG_ASYNC_DB_CLIENT", async_mode)
    wire.rows[("GET", "users")] = [{"id": "u1"}]
    wire.rows[("GET", "documents")] = [{"id": "d1"}]
    with patch("services.chunk_visibility.withdraw_document_chunks") as withdraw:
        r = client.delete("/api/documents/doc/d1?user_id=u1")
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": True}
    withdraw.assert_called_once_with("d1", "u1")
    _mode(wire, async_mode, {("GET", "users"), ("GET", "documents"), ("PATCH", "documents")})


@pytest.mark.parametrize("async_mode", ["off", "on"])
def test_update_document(wire, monkeypatch, async_mode):  # noqa: F811
    monkeypatch.setenv("SAPLING_FLAG_ASYNC_DB_CLIENT", async_mode)
    wire.rows[("GET", "users")] = [{"id": "u1"}]
    wire.rows[("GET", "documents")] = [{"id": "d1"}]
    wire.rows[("PATCH", "documents")] = [{"id": "d1", "category": "slides"}]
    r = client.patch("/api/documents/doc/d1", json={"category": "slides", "user_id": "u1"})
    assert r.status_code == 200, r.text
    assert r.json() == {"id": "d1", "category": "slides"}
    _mode(wire, async_mode, {("GET", "users"), ("GET", "documents"), ("PATCH", "documents")})


def test_an_unknown_user_is_still_refused(wire):  # noqa: F811
    wire.rows[("GET", "users")] = []
    r = client.get("/api/documents/user/u1")
    assert r.status_code == 403
    assert not any(n == "documents" for _m, n, _ in wire.calls)


def test_a_foreign_document_is_404_and_nothing_is_written(wire):  # noqa: F811
    wire.rows[("GET", "users")] = [{"id": "u1"}]
    wire.rows[("GET", "documents")] = []
    r = client.patch("/api/documents/doc/d1", json={"category": "slides", "user_id": "u1"})
    assert r.status_code == 404
    assert not any(m == "PATCH" for m, _n, _ in wire.calls)
