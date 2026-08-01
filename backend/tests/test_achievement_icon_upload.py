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


def _webp(width: int, height: int, variant: str) -> bytes:
    """A minimal but structurally valid WebP container for the given variant.

    Builds real RIFF/WEBP container bytes (not a mock) so the test pins the
    actual byte offsets `_webp_dimensions` reads, per variant:
      - VP8X: 24-bit LE width-1/height-1 at chunk-data offset 4..10
      - "VP8 ": 14-bit width/height at chunk-data offset 6..10
      - VP8L: packed 14-bit width-1/height-1 in a uint32 at chunk-data offset 1..5
    """
    if variant == "VP8X":
        payload = (
            b"\x00" + b"\x00\x00\x00"
            + (width - 1).to_bytes(3, "little")
            + (height - 1).to_bytes(3, "little")
        )
        fourcc = b"VP8X"
    elif variant == "VP8 ":
        payload = (
            b"\x00\x00\x00" + b"\x9d\x01\x2a"
            + struct.pack("<H", width & 0x3FFF)
            + struct.pack("<H", height & 0x3FFF)
        )
        fourcc = b"VP8 "
    elif variant == "VP8L":
        bits = ((width - 1) & 0x3FFF) | (((height - 1) & 0x3FFF) << 14)
        payload = b"\x2f" + struct.pack("<I", bits) + b"\x00" * 5
        fourcc = b"VP8L"
    else:
        raise ValueError(variant)
    chunk = fourcc + struct.pack("<I", len(payload)) + payload
    riff_size = 4 + len(chunk)  # "WEBP" + chunk
    return b"RIFF" + struct.pack("<I", riff_size) + b"WEBP" + chunk


SQUARE_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"></svg>'
TALL_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 128"></svg>'

# A square viewBox planted in a comment ahead of the real (non-square) root
# <svg> element. A naive "search the whole document for viewBox=" parser
# picks up the decoy; only reading the root element's own attributes rejects it.
COMMENT_DECOY_SVG = b'<!-- viewBox="0 0 1 1" --><svg viewBox="0 0 999 100"></svg>'

# A square viewBox on a nested <symbol> (no viewBox on the actual root <svg>).
# Same bypass shape: the decoy appears first in the raw text, ahead of/instead
# of the root element's real (missing) viewBox.
NESTED_DECOY_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg">'
    b'<symbol viewBox="0 0 1 1"></symbol>'
    b'<svg viewBox="0 0 999 100"></svg>'
    b'</svg>'
)


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

    def test_rejects_an_svg_with_a_comment_decoy_viewbox(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException):
            validate_icon(COMMENT_DECOY_SVG, "image/svg+xml")

    def test_rejects_an_svg_with_a_nested_element_decoy_viewbox(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException):
            validate_icon(NESTED_DECOY_SVG, "image/svg+xml")

    @pytest.mark.parametrize("variant", ["VP8X", "VP8 ", "VP8L"])
    def test_accepts_a_512_square_webp(self, variant):
        from services.storage_service import validate_icon
        validate_icon(_webp(512, 512, variant), "image/webp")

    def test_rejects_the_wrong_webp_dimensions(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException) as exc:
            validate_icon(_webp(256, 256, "VP8X"), "image/webp")
        assert exc.value.status_code == 400
        assert "512" in exc.value.detail

    def test_rejects_a_truncated_webp(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException):
            validate_icon(_webp(512, 512, "VP8X")[:20], "image/webp")


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
