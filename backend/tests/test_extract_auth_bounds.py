"""
Regression tests for #182: /api/extract/pdf and /api/extract/image were
unauthenticated, unbounded, unthrottled OCR endpoints. They now require an
authenticated session (401), cap upload size (413), and rate-limit per user
(429).

Each negative test fails on pre-fix code (no auth, no size cap, no limiter).
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
import services.request_limits as request_limits

client = TestClient(app)


def _pdf_files():
    # Fresh dict per request — the upload stream is consumed on read.
    return {"file": ("doc.pdf", b"%PDF-1.4 hello world", "application/pdf")}


def _png_files():
    return {"file": ("img.png", b"\x89PNG\r\n\x1a\n payload", "image/png")}


class TestExtractRequiresAuth:
    def test_pdf_unauthenticated_returns_401(self):
        from services import auth_guard

        with patch("routes.extract.get_session_user_id", auth_guard._real_get_session_user_id), \
             patch.object(auth_guard, "_decode_session", auth_guard._real_decode_session):
            r = client.post("/api/extract/pdf", files=_pdf_files())
        assert r.status_code == 401

    def test_image_unauthenticated_returns_401(self):
        from services import auth_guard

        with patch("routes.extract.get_session_user_id", auth_guard._real_get_session_user_id), \
             patch.object(auth_guard, "_decode_session", auth_guard._real_decode_session):
            r = client.post("/api/extract/image", files=_png_files())
        assert r.status_code == 401


class TestExtractSizeBound:
    def test_oversize_pdf_returns_413(self, monkeypatch):
        request_limits._rate_state.clear()
        # Shrink the cap so we don't have to ship 20 MB in a test.
        monkeypatch.setattr("routes.extract.MAX_OCR_BYTES", 100)
        with patch("routes.extract.extract_text_from_pdf_native", return_value=("x" * 100, 1)):
            files = {"file": ("doc.pdf", b"P" * 200, "application/pdf")}
            r = client.post("/api/extract/pdf", files=files)
        assert r.status_code == 413


class TestExtractRateLimit:
    def test_pdf_rate_limited_after_threshold(self, monkeypatch):
        request_limits._rate_state.clear()
        monkeypatch.setattr("routes.extract._OCR_RATE_LIMIT", 2)
        with patch("routes.extract.extract_text_from_pdf_native", return_value=("x" * 100, 1)):
            r1 = client.post("/api/extract/pdf", files=_pdf_files())
            r2 = client.post("/api/extract/pdf", files=_pdf_files())
            r3 = client.post("/api/extract/pdf", files=_pdf_files())
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 429
        # Retry budget is conveyed in the detail (the app's global exception
        # handler strips HTTPException headers).
        assert "Retry in" in r3.json()["detail"]
