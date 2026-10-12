"""Route tests for /api/summary-docs.

Uses the autouse `_bypass_session_auth` fixture from conftest.py (same
pattern as tests/test_notes_routes.py) — user_id resolves to whatever the
query/path/body carries, defaulting to "user_andres".
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app)


_DOC = {
    "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
    "content": {"type": "doc", "content": []}, "created_at": "t0", "updated_at": "t0",
    "sources": [], "pending_suggestions": [],
}


class TestGetSummaryDoc:
    def test_returns_doc(self, client):
        with patch("routes.summary_docs.get_summary_doc", return_value=_DOC):
            r = client.get("/api/summary-docs/sd1?user_id=u1")
        assert r.status_code == 200
        assert r.json()["id"] == "sd1"

    def test_404_when_not_found(self, client):
        with patch("routes.summary_docs.get_summary_doc", return_value=None):
            r = client.get("/api/summary-docs/sd1?user_id=u1")
        assert r.status_code == 404


class TestUpdateContent:
    def test_autosaves_content(self, client):
        new_content = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hi"}]}]}
        with patch("routes.summary_docs.update_content", return_value={**_DOC, "content": new_content}) as mock_update:
            r = client.patch("/api/summary-docs/sd1", json={"user_id": "u1", "content": new_content})
        assert r.status_code == 200
        mock_update.assert_called_once_with("sd1", "u1", new_content)

    def test_404_when_not_owned(self, client):
        with patch("routes.summary_docs.update_content", return_value=None):
            r = client.patch("/api/summary-docs/sd1", json={"user_id": "u1", "content": {"type": "doc", "content": []}})
        assert r.status_code == 404


class TestSources:
    def test_add_source(self, client):
        with patch("routes.summary_docs.add_source", return_value=_DOC):
            r = client.post("/api/summary-docs/sd1/sources", json={"user_id": "u1", "document_id": "doc2"})
        assert r.status_code == 200

    def test_add_source_404_when_not_owned(self, client):
        with patch("routes.summary_docs.add_source", return_value=None):
            r = client.post("/api/summary-docs/sd1/sources", json={"user_id": "u1", "document_id": "doc2"})
        assert r.status_code == 404

    def test_remove_source(self, client):
        with patch("routes.summary_docs.remove_source", return_value=_DOC):
            r = client.delete("/api/summary-docs/sd1/sources/doc2?user_id=u1")
        assert r.status_code == 200

    def test_remove_source_refuses_the_primary(self, client):
        with patch("routes.summary_docs.remove_source", return_value="primary"):
            r = client.delete("/api/summary-docs/sd1/sources/doc1?user_id=u1")
        assert r.status_code == 400

    def test_remove_source_404_when_not_owned(self, client):
        with patch("routes.summary_docs.remove_source", return_value=None):
            r = client.delete("/api/summary-docs/sd1/sources/doc2?user_id=u1")
        assert r.status_code == 404


class TestVersions:
    def test_list_versions(self, client):
        versions = [{"id": "v1", "trigger": "initial", "created_at": "t0", "preview": "Hi."}]
        with patch("routes.summary_docs.list_versions", return_value=versions):
            r = client.get("/api/summary-docs/sd1/versions?user_id=u1")
        assert r.status_code == 200
        assert r.json() == {"versions": versions}

    def test_list_versions_404_when_not_owned(self, client):
        with patch("routes.summary_docs.list_versions", return_value=None):
            r = client.get("/api/summary-docs/sd1/versions?user_id=u1")
        assert r.status_code == 404

    def test_restore_version(self, client):
        with patch("routes.summary_docs.restore_version", return_value=_DOC):
            r = client.post("/api/summary-docs/sd1/versions/v1/restore", json={"user_id": "u1"})
        assert r.status_code == 200

    def test_restore_version_404(self, client):
        with patch("routes.summary_docs.restore_version", return_value=None):
            r = client.post("/api/summary-docs/sd1/versions/v1/restore", json={"user_id": "u1"})
        assert r.status_code == 404
