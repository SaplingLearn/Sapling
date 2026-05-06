"""
Unit tests for services/storage_service.py

Tests cover:
  - _validate_upload rejects unsupported content types
  - _validate_upload rejects files exceeding size limit
  - upload_avatar constructs correct path and returns public URL
  - upload_cosmetic_asset constructs correct path
  - delete_asset calls correct endpoint
"""
import asyncio

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException


class TestValidateUpload:
    def test_rejects_unsupported_type(self):
        from services.storage_service import _validate_upload
        with pytest.raises(HTTPException) as exc:
            _validate_upload(b"data", "application/pdf")
        assert exc.value.status_code == 415

    def test_rejects_oversized_file(self):
        from services.storage_service import _validate_upload
        big = b"x" * (6 * 1024 * 1024)
        with pytest.raises(HTTPException) as exc:
            _validate_upload(big, "image/png")
        assert exc.value.status_code == 413

    def test_accepts_valid_upload(self):
        from services.storage_service import _validate_upload
        _validate_upload(b"valid", "image/png")

    def test_accepts_all_allowed_types(self):
        from services.storage_service import _validate_upload
        for ct in ["image/jpeg", "image/png", "image/webp", "image/gif"]:
            _validate_upload(b"data", ct)


class TestUploadAvatar:
    def test_returns_public_url(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("services.storage_service.httpx.put", return_value=mock_resp):
            from services.storage_service import upload_avatar
            url = upload_avatar("u1", b"pixels", "image/png")

        assert "avatars/u1/avatar.png" in url
        assert "/public/" in url

    def test_raises_on_failure(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = ""

        with patch("services.storage_service.httpx.put", return_value=mock_resp):
            from services.storage_service import upload_avatar
            with pytest.raises(HTTPException) as exc:
                upload_avatar("u1", b"pixels", "image/png")
            assert exc.value.status_code == 502

    def test_surfaces_supabase_body_on_failure(self):
        """The HTTPException detail must include the upstream Supabase
        status + body so frontend toasts and Logfire spans become
        actionable instead of black-box. PR #86 contract."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = '{"statusCode":"404","error":"Bucket not found"}'

        with patch("services.storage_service.httpx.put", return_value=mock_resp):
            from services.storage_service import upload_avatar
            with pytest.raises(HTTPException) as exc:
                upload_avatar("u1", b"pixels", "image/png")

        detail = exc.value.detail
        assert "Supabase 404" in detail
        assert "Bucket not found" in detail
        # Service-role key must NEVER leak into the response body.
        assert "Bearer" not in detail
        assert "apikey" not in detail

    def test_failure_with_empty_body_falls_back_gracefully(self):
        """When Supabase returns no body (rare but possible on 5xx), the
        detail must still be a complete sentence — not 'Supabase 502: '."""
        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_resp.text = ""

        with patch("services.storage_service.httpx.put", return_value=mock_resp):
            from services.storage_service import upload_avatar
            with pytest.raises(HTTPException) as exc:
                upload_avatar("u1", b"pixels", "image/png")

        assert "no body" in exc.value.detail

    def test_jpeg_extension(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("services.storage_service.httpx.put", return_value=mock_resp):
            from services.storage_service import upload_avatar
            url = upload_avatar("u1", b"pixels", "image/jpeg")

        assert "avatar.jpg" in url


class TestUploadCosmeticAsset:
    def test_returns_public_url(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201

        with patch("services.storage_service.httpx.put", return_value=mock_resp):
            from services.storage_service import upload_cosmetic_asset
            url = upload_cosmetic_asset("cos_1", b"pixels", "image/webp")

        assert "cosmetics/cos_1.webp" in url

    def test_surfaces_supabase_body_on_failure(self):
        """Parity with upload_avatar — admin-side cosmetic uploads must
        also surface the upstream Supabase error so failures aren't a
        black box. PR #86 contract."""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = '{"statusCode":"403","error":"new row violates row-level security"}'

        with patch("services.storage_service.httpx.put", return_value=mock_resp):
            from services.storage_service import upload_cosmetic_asset
            with pytest.raises(HTTPException) as exc:
                upload_cosmetic_asset("cos_1", b"pixels", "image/png")

        detail = exc.value.detail
        assert "Supabase 403" in detail
        assert "row-level security" in detail
        # Service-role key must NEVER leak into the response body.
        assert "Bearer" not in detail
        assert "apikey" not in detail


def _patch_async_client(*, status_code=200, body_text="", raises=None):
    """Patch `httpx.AsyncClient` to return a stubbed response (or
    raise) without doing a real network call. Returns the patcher so
    tests can inspect the recorded `post(...)` call args.

    `httpx.AsyncClient` is used inside an `async with` block, so the
    mock has to behave as an async context manager. The `post` method
    is itself awaitable. AsyncMock handles both shapes when set on
    the right attributes.
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = body_text

    client_instance = MagicMock()
    client_instance.__aenter__ = AsyncMock(return_value=client_instance)
    client_instance.__aexit__ = AsyncMock(return_value=None)
    if raises is not None:
        client_instance.post = AsyncMock(side_effect=raises)
    else:
        client_instance.post = AsyncMock(return_value=resp)

    # AsyncClient(timeout=...) -> client_instance. The constructor is
    # called synchronously, so a MagicMock side effect is correct.
    cls_mock = MagicMock(return_value=client_instance)
    return patch("services.storage_service.httpx.AsyncClient", cls_mock), client_instance


class TestEnsureBucketExists:
    """Pin the startup bootstrap behavior. Backend lifespan calls this
    on app boot so new Supabase environments self-create the avatars
    bucket — fixes the underlying cause of issue #75 (bucket missing,
    every avatar upload returned 502 'Bucket not found')."""

    KW = dict(public=True, file_size_limit=5_242_880, allowed_mime_types=["image/png"])

    def test_creates_bucket_when_missing(self):
        patcher, client = _patch_async_client(status_code=200)
        with patcher:
            from services.storage_service import ensure_bucket_exists
            asyncio.run(ensure_bucket_exists("avatars", **self.KW))

        # Verify the API contract: POST to .../storage/v1/bucket with
        # the expected body shape.
        assert client.post.called
        call_args = client.post.call_args
        assert call_args.args[0].endswith("/storage/v1/bucket")
        body = call_args.kwargs["json"]
        assert body["id"] == "avatars"
        assert body["name"] == "avatars"
        assert body["public"] is True
        assert body["file_size_limit"] == 5_242_880
        assert body["allowed_mime_types"] == ["image/png"]

    def test_idempotent_on_409_already_exists(self):
        """Re-running on an already-created bucket must not raise."""
        patcher, _ = _patch_async_client(
            status_code=409, body_text='{"statusCode":"409","error":"Duplicate"}',
        )
        with patcher:
            from services.storage_service import ensure_bucket_exists
            asyncio.run(ensure_bucket_exists("avatars", **self.KW))

    def test_logs_warning_on_unexpected_status(self):
        """Other 4xx/5xx are non-fatal — startup should not block on
        Supabase availability."""
        patcher, _ = _patch_async_client(status_code=500, body_text="Internal Server Error")
        with patcher:
            from services.storage_service import ensure_bucket_exists
            asyncio.run(ensure_bucket_exists("avatars", **self.KW))

    def test_swallows_network_exception(self):
        """A transient network error (DNS, connection refused) must
        not crash startup."""
        patcher, _ = _patch_async_client(raises=Exception("connection refused"))
        with patcher:
            from services.storage_service import ensure_bucket_exists
            asyncio.run(ensure_bucket_exists("avatars", **self.KW))

    def test_skips_when_credentials_missing(self):
        """If SUPABASE_URL or service key is unset, log + skip without
        crashing or making a network call. Lets the backend still
        start in tests / partial-config environments."""
        with patch("services.storage_service.SUPABASE_URL", ""), \
             patch("services.storage_service.httpx.AsyncClient") as ac:
            from services.storage_service import ensure_bucket_exists
            asyncio.run(ensure_bucket_exists("avatars", **self.KW))
        ac.assert_not_called()


class TestLifespanWiresEnsureBucketExists:
    """Pin that the FastAPI lifespan actually calls
    ensure_bucket_exists on app boot. Without this, a future refactor
    that drops the call from `_lifespan` wouldn't fail any test —
    we'd silently regress to the original "bucket-doesn't-exist"
    bug from issue #75."""

    def test_lifespan_invokes_ensure_bucket_exists_with_avatars_settings(self):
        from unittest.mock import AsyncMock

        # Patch in main.py's namespace because the import is hoisted
        # to module-level there. AsyncMock so `await` inside the
        # lifespan resolves cleanly.
        with patch("main.ensure_bucket_exists", new=AsyncMock()) as m:
            from fastapi.testclient import TestClient
            from main import app
            with TestClient(app):
                # Entering the context triggers the lifespan startup.
                pass

        m.assert_called_once()
        # Verify the lifespan passes the avatars-specific settings the
        # bucket actually needs: public for unauthenticated <img src>
        # reads, MAX_AVATAR_SIZE for the size cap, and the same MIME
        # types the route's _validate_upload allows.
        from config import MAX_AVATAR_SIZE, STORAGE_BUCKET
        from services.storage_service import ALLOWED_CONTENT_TYPES
        args = m.call_args
        assert args.args[0] == STORAGE_BUCKET
        assert args.kwargs["public"] is True
        assert args.kwargs["file_size_limit"] == MAX_AVATAR_SIZE
        assert set(args.kwargs["allowed_mime_types"]) == ALLOWED_CONTENT_TYPES


class TestDeleteAsset:
    def test_calls_httpx_delete(self):
        with patch("services.storage_service.httpx.delete") as mock_del:
            from services.storage_service import delete_asset
            delete_asset("avatars/u1/avatar.png")

        mock_del.assert_called_once()
        call_url = mock_del.call_args[0][0]
        assert "avatars/u1/avatar.png" in call_url
