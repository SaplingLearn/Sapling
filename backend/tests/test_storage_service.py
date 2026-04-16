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

        with patch("services.storage_service.httpx.put", return_value=mock_resp):
            from services.storage_service import upload_avatar
            with pytest.raises(HTTPException) as exc:
                upload_avatar("u1", b"pixels", "image/png")
            assert exc.value.status_code == 502

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


class TestDeleteAsset:
    def test_calls_httpx_delete(self):
        with patch("services.storage_service.httpx.delete") as mock_del:
            from services.storage_service import delete_asset
            delete_asset("avatars/u1/avatar.png")

        mock_del.assert_called_once()
        call_url = mock_del.call_args[0][0]
        assert "avatars/u1/avatar.png" in call_url
