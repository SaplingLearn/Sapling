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
            hx.put.return_value.status_code = 200
            r = client.post("/api/issue-reports/screenshot", files=_png())
        assert r.status_code == 200
        path = r.json()["path"]
        # Path is scoped under the authenticated user_id (conftest stub: user_andres).
        assert path.startswith("user_andres/")
        assert path.endswith(".png")
        hx.put.assert_called_once()

    def test_supabase_failure_returns_502_not_500(self):
        # When Supabase Storage rejects the upload (e.g. bucket missing /
        # RLS denied), the endpoint maps it to a 502 with the truncated
        # upstream body — never a generic 500. (#231 review fix.)
        with patch("routes.feedback.httpx") as hx:
            hx.put.return_value.status_code = 404
            hx.put.return_value.text = '{"statusCode":"404","error":"Bucket not found"}'
            r = client.post("/api/issue-reports/screenshot", files=_png())
        assert r.status_code == 502
        detail = r.json()["detail"]
        # Upstream status + body are surfaced for debuggability...
        assert "404" in detail
        assert "Bucket not found" in detail
        # ...but the service-role key (in headers) and upload URL must not leak.
        assert "Authorization" not in detail
        assert "storage/v1/object" not in detail
        hx.put.assert_called_once()
