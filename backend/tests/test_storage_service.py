"""
Unit tests for services/storage_service.py

Tests cover:
  - _validate_upload rejects unsupported content types
  - _validate_upload rejects files exceeding size limit
  - upload_avatar constructs correct path and returns public URL
  - upload_cosmetic_asset constructs correct path
  - delete_asset calls correct endpoint
"""
import pytest
from unittest.mock import patch, MagicMock
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


class TestEnsureBucketExists:
    """Pin the startup bootstrap behavior. Backend lifespan calls this
    on app boot so new Supabase environments self-create the avatars
    bucket — fixes the underlying cause of issue #75 (bucket missing,
    every avatar upload returned 502 'Bucket not found')."""

    KW = dict(public=True, file_size_limit=5_242_880, allowed_mime_types=["image/png"])

    def _resp(self, status_code, text=""):
        m = MagicMock()
        m.status_code = status_code
        m.text = text
        return m

    def test_creates_bucket_when_missing(self):
        post = self._resp(200)
        with patch("services.storage_service.httpx.post", return_value=post) as p:
            from services.storage_service import ensure_bucket_exists
            ensure_bucket_exists("avatars", **self.KW)
        # Verify the API contract: POST to .../storage/v1/bucket with
        # the expected body shape.
        assert p.called
        call_args = p.call_args
        assert call_args.args[0].endswith("/storage/v1/bucket")
        body = call_args.kwargs["json"]
        assert body["id"] == "avatars"
        assert body["name"] == "avatars"
        assert body["public"] is True
        assert body["file_size_limit"] == 5_242_880
        assert body["allowed_mime_types"] == ["image/png"]

    def test_idempotent_on_409_already_exists(self):
        """Re-running on an already-created bucket must not raise."""
        post = self._resp(409, '{"statusCode":"409","error":"Duplicate"}')
        with patch("services.storage_service.httpx.post", return_value=post):
            from services.storage_service import ensure_bucket_exists
            # Should not raise.
            ensure_bucket_exists("avatars", **self.KW)

    def test_logs_warning_on_unexpected_status(self):
        """Other 4xx/5xx are non-fatal — startup should not block on
        Supabase availability."""
        post = self._resp(500, "Internal Server Error")
        with patch("services.storage_service.httpx.post", return_value=post):
            from services.storage_service import ensure_bucket_exists
            ensure_bucket_exists("avatars", **self.KW)

    def test_swallows_network_exception(self):
        """A transient network error (DNS, connection refused) must
        not crash startup."""
        with patch(
            "services.storage_service.httpx.post",
            side_effect=Exception("connection refused"),
        ):
            from services.storage_service import ensure_bucket_exists
            ensure_bucket_exists("avatars", **self.KW)

    def test_skips_when_credentials_missing(self):
        """If SUPABASE_URL or service key is unset, log + skip without
        crashing or making a network call. Lets the backend still
        start in tests / partial-config environments."""
        with patch("services.storage_service.SUPABASE_URL", ""), \
             patch("services.storage_service.httpx.post") as p:
            from services.storage_service import ensure_bucket_exists
            ensure_bucket_exists("avatars", **self.KW)
        p.assert_not_called()


class TestDeleteAsset:
    def test_calls_httpx_delete(self):
        with patch("services.storage_service.httpx.delete") as mock_del:
            from services.storage_service import delete_asset
            delete_asset("avatars/u1/avatar.png")

        mock_del.assert_called_once()
        call_url = mock_del.call_args[0][0]
        assert "avatars/u1/avatar.png" in call_url
