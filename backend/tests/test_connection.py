"""Tests for db/connection.py's Supabase Storage wrapper."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import db.connection as dbconn
from db.connection import storage_create_signed_url, storage_delete, storage_upload


class TestStorageUpload:
    def test_posts_bytes_with_content_type_and_upsert_header(self):
        fake_client = MagicMock()
        fake_client.post.return_value.raise_for_status.return_value = None
        with patch.object(dbconn, "_client", fake_client):
            storage_upload("document-originals", "doc1/notes.pdf", b"%PDF-1.4 x", "application/pdf")

        fake_client.post.assert_called_once()
        args, kwargs = fake_client.post.call_args
        assert args[0] == f"{dbconn.SUPABASE_URL}/storage/v1/object/document-originals/doc1/notes.pdf"
        assert kwargs["content"] == b"%PDF-1.4 x"
        assert kwargs["headers"]["Content-Type"] == "application/pdf"
        assert kwargs["headers"]["x-upsert"] == "true"

    def test_raises_on_http_error(self):
        fake_client = MagicMock()
        fake_client.post.return_value.raise_for_status.side_effect = RuntimeError("500")
        with patch.object(dbconn, "_client", fake_client):
            try:
                storage_upload("document-originals", "doc1/notes.pdf", b"x", "application/pdf")
            except RuntimeError:
                pass
            else:
                raise AssertionError("expected storage_upload to propagate the error")


class TestStorageDelete:
    def test_deletes_the_object(self):
        fake_client = MagicMock()
        fake_client.request.return_value.raise_for_status.return_value = None
        with patch.object(dbconn, "_client", fake_client):
            storage_delete("document-originals", "doc1/notes.pdf")

        fake_client.request.assert_called_once()
        args, kwargs = fake_client.request.call_args
        assert args[0] == "DELETE"
        assert args[1] == f"{dbconn.SUPABASE_URL}/storage/v1/object/document-originals/doc1/notes.pdf"

    def test_sends_a_body_so_storage_does_not_reject_the_delete(self):
        """The regression guard for a bug a mock could not see.

        `_client` sets `Content-Type: application/json` on every request, and
        Storage's Fastify layer rejects a bodiless request carrying that header
        ("Body cannot be empty when content-type is set to 'application/json'").
        So a plain `_client.delete(url)` 400s for every object that exists, and
        since the only caller swallows the error best-effort, each deleted
        document silently leaked its original file. The previous version of
        this test asserted that exact bodiless call, which is how a fully
        mocked suite stayed green against a call shape the real server always
        refused — only the live e2e logscan oracle caught it.
        """
        fake_client = MagicMock()
        fake_client.request.return_value.raise_for_status.return_value = None
        with patch.object(dbconn, "_client", fake_client):
            storage_delete("document-originals", "doc1/notes.pdf")

        _, kwargs = fake_client.request.call_args
        assert kwargs.get("json") == {}, "DELETE must carry a body, or Storage 400s it"


class TestStorageCreateSignedUrl:
    def test_returns_a_full_url(self):
        fake_client = MagicMock()
        fake_client.post.return_value.raise_for_status.return_value = None
        fake_client.post.return_value.json.return_value = {
            "signedURL": "/object/sign/document-originals/doc1/notes.pdf?token=abc"
        }
        with patch.object(dbconn, "_client", fake_client):
            url = storage_create_signed_url("document-originals", "doc1/notes.pdf", expires_in=300)

        assert url == f"{dbconn.SUPABASE_URL}/storage/v1/object/sign/document-originals/doc1/notes.pdf?token=abc"
        args, kwargs = fake_client.post.call_args
        assert args[0] == f"{dbconn.SUPABASE_URL}/storage/v1/object/sign/document-originals/doc1/notes.pdf"
        assert kwargs["json"] == {"expiresIn": 300}
