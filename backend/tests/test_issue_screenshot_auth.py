"""
Regression tests for #231 Phase 2a: POST /api/issue-reports/screenshot.

This endpoint moves issue-report screenshot uploads off the frontend's public
anon-key storage client and onto an auth-gated, service-role backend upload so
the issues-media-files bucket can be made private. The negative tests assert it
requires auth (401) and bounds type (415) / size (413); all fail on pre-fix code
(the endpoint didn't exist → 404).
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _png(nbytes: int = 16):
    return {"file": ("shot.png", b"\x89PNG\r\n\x1a\n" + b"0" * nbytes, "image/png")}


class TestIssueScreenshotUpload:
    def test_unauthenticated_returns_401(self):
        from services import auth_guard

        with patch("routes.feedback.get_session_user_id", auth_guard._real_get_session_user_id), \
             patch.object(auth_guard, "_decode_session", auth_guard._real_decode_session):
            r = client.post("/api/issue-reports/screenshot", files=_png())
        assert r.status_code == 401

    def test_wrong_content_type_returns_415(self):
        with patch("routes.feedback.httpx") as hx:
            r = client.post(
                "/api/issue-reports/screenshot",
                files={"file": ("notes.txt", b"hello", "text/plain")},
            )
        assert r.status_code == 415
        hx.put.assert_not_called()

    def test_oversize_returns_413(self, monkeypatch):
        monkeypatch.setattr("routes.feedback.MAX_SCREENSHOT_BYTES", 100)
        with patch("routes.feedback.httpx") as hx:
            r = client.post("/api/issue-reports/screenshot", files=_png(nbytes=200))
        assert r.status_code == 413
        hx.put.assert_not_called()

    def test_valid_upload_returns_path_scoped_to_user(self):
        with patch("routes.feedback.httpx") as hx:
            hx.put.return_value.raise_for_status.return_value = None
            r = client.post("/api/issue-reports/screenshot", files=_png())
        assert r.status_code == 200
        path = r.json()["path"]
        # Path is scoped under the authenticated user_id (conftest stub: user_andres).
        assert path.startswith("user_andres/")
        assert path.endswith(".png")
        hx.put.assert_called_once()
