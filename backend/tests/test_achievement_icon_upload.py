"""Achievement icon upload — server-side format and dimension validation."""
import base64
import struct
import zlib

import pytest
from fastapi import HTTPException


def _png(width: int, height: int) -> bytes:
    """A minimal but structurally valid PNG with the given dimensions."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


SQUARE_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"></svg>'
TALL_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 128"></svg>'


class TestValidateIcon:
    def test_accepts_a_512_square_png(self):
        from services.storage_service import validate_icon
        validate_icon(_png(512, 512), "image/png")

    def test_rejects_the_wrong_dimensions(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException) as exc:
            validate_icon(_png(256, 256), "image/png")
        assert exc.value.status_code == 400
        assert "512" in exc.value.detail

    def test_rejects_a_non_square_png(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException):
            validate_icon(_png(512, 256), "image/png")

    def test_rejects_an_unsupported_content_type(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException) as exc:
            validate_icon(_png(512, 512), "image/gif")
        assert exc.value.status_code == 400

    def test_rejects_an_oversized_file(self):
        from services.storage_service import validate_icon
        payload = _png(512, 512) + b"\x00" * (512 * 1024)
        with pytest.raises(HTTPException) as exc:
            validate_icon(payload, "image/png")
        assert "512 KB" in exc.value.detail

    def test_accepts_a_square_svg(self):
        from services.storage_service import validate_icon
        validate_icon(SQUARE_SVG, "image/svg+xml")

    def test_rejects_a_non_square_svg(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException):
            validate_icon(TALL_SVG, "image/svg+xml")

    def test_rejects_an_svg_with_no_viewbox(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException):
            validate_icon(b"<svg></svg>", "image/svg+xml")

    def test_rejects_a_truncated_png(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException):
            validate_icon(b"\x89PNG\r\n\x1a\n", "image/png")


class TestUploadRoute:
    def test_stores_the_icon_and_patches_the_row(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app)
        payload = base64.b64encode(_png(512, 512)).decode()
        with patch("routes.admin.require_admin"), \
             patch("routes.admin.get_session_user_id", return_value="admin1"), \
             patch("routes.admin.upload_achievement_icon",
                   return_value="https://cdn/icons/a1.png") as up, \
             patch("routes.admin.table") as t, \
             patch("routes.admin.log_admin_action"):
            t.return_value.update.return_value = []
            r = client.post("/api/admin/achievements/a1/icon",
                            json={"file_base64": payload, "content_type": "image/png"})
        assert r.status_code == 200
        assert r.json()["icon_url"] == "https://cdn/icons/a1.png"
        up.assert_called_once()
