"""
Regression tests for #199:
- newsletter.subscribe must not leak raw exception text to the client.
- careers.apply must bound resume size/type and validate basic inputs.

These assert the security properties that fail on pre-fix code (raw exception
text echoed back; unbounded/untyped uploads accepted).
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

INTERNAL = "SECRET_DB_INTERNALS: connection refused at 10.0.0.5 table=newsletter_emails"

# Minimal valid form for /api/careers/apply.
VALID_FORM = {
    "position": "Software Engineer",
    "full_name": "Ada Lovelace",
    "email": "ada@example.com",
    "linkedin_url": "https://www.linkedin.com/in/ada",
}


class TestNewsletterErrorLeak:
    def test_db_error_returns_generic_message_not_raw_exception(self):
        with patch("routes.newsletter.table") as t:
            t.return_value.upsert.side_effect = Exception(INTERNAL)
            r = client.post("/api/newsletter/subscribe", json={"email": "x@example.com"})

        assert r.status_code == 500
        detail = r.json().get("detail", "")
        # Pre-fix: detail == str(e) and contains INTERNAL. Post-fix: generic.
        assert INTERNAL not in detail
        assert "10.0.0.5" not in detail
        assert detail == "Could not process subscription. Please try again later."


class TestCareersUploadBounds:
    def test_oversize_resume_rejected_413(self):
        big = b"%PDF-" + b"0" * (5 * 1024 * 1024 + 1)
        with patch("routes.careers.httpx") as hx, patch("routes.careers.table") as t:
            t.return_value.insert.return_value = [{"id": "app1"}]
            r = client.post(
                "/api/careers/apply",
                data=VALID_FORM,
                files={"resume": ("resume.pdf", big, "application/pdf")},
            )
        # Pre-fix accepted it (200, unbounded read + upload); fix returns 413
        # and never reaches the storage upload.
        assert r.status_code == 413
        hx.put.assert_not_called()

    def test_wrong_content_type_rejected_415(self):
        with patch("routes.careers.httpx") as hx, patch("routes.careers.table") as t:
            t.return_value.insert.return_value = [{"id": "app1"}]
            r = client.post(
                "/api/careers/apply",
                data=VALID_FORM,
                files={"resume": ("resume.exe", b"MZ\x90\x00", "application/octet-stream")},
            )
        assert r.status_code == 415
        hx.put.assert_not_called()

    def test_invalid_email_rejected_422(self):
        with patch("routes.careers.httpx"), patch("routes.careers.table") as t:
            t.return_value.insert.return_value = [{"id": "app1"}]
            r = client.post(
                "/api/careers/apply",
                data={**VALID_FORM, "email": "not-an-email"},
            )
        assert r.status_code == 422

    def test_valid_application_succeeds(self):
        with patch("routes.careers.httpx") as hx, patch("routes.careers.table") as t:
            hx.put.return_value.raise_for_status.return_value = None
            t.return_value.insert.return_value = [{"id": "app1"}]
            r = client.post(
                "/api/careers/apply",
                data=VALID_FORM,
                files={"resume": ("resume.pdf", b"%PDF-1.4 small", "application/pdf")},
            )
        assert r.status_code == 200
        assert r.json() == {"ok": True, "id": "app1"}
