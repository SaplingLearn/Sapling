"""
Regression tests for GET /api/gemini-test (main.gemini_test) auth.

Issue #198: the endpoint had no auth and made a real, billable `call_gemini`
round-trip on every hit, so anonymous callers could burn Gemini quota and use
the `{"ok": ...}` response as an oracle for whether the API key is valid. It is
now gated behind `require_admin`.

The autouse `_bypass_session_auth` fixture in conftest.py stubs the auth guard
so the admin-path test reaches the handler without minting tokens; the
unauthenticated test restores the real guard to assert the 401.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


class TestGeminiTestAuth:
    def test_unauthenticated_returns_401_and_makes_no_llm_call(self):
        # Restore the real guard so a request with no cookie/token => 401,
        # undoing the autouse bypass from conftest. require_admin calls
        # get_session_user_id first, which raises 401 before any role lookup.
        from services import auth_guard

        with patch.object(
            auth_guard, "require_admin", auth_guard._real_require_admin
        ), patch.object(
            auth_guard, "get_session_user_id", auth_guard._real_get_session_user_id
        ), patch.object(
            auth_guard, "_decode_session", auth_guard._real_decode_session
        ), patch("services.gemini_service.call_gemini") as call_gemini:
            r = client.get("/api/gemini-test")

        # Pre-fix this returned 200 with {"ok": ...}; the fix makes it 401 and,
        # critically, the LLM is never called for an anonymous request.
        assert r.status_code == 401
        call_gemini.assert_not_called()

    def test_admin_reaches_handler(self):
        # Autouse bypass stubs require_admin to a no-op, so an admin-equivalent
        # request reaches the handler. Mock the LLM so the test is hermetic.
        with patch("services.gemini_service.call_gemini", return_value="Gemini OK"):
            r = client.get("/api/gemini-test")

        assert r.status_code == 200
        assert r.json() == {"ok": True, "reply": "Gemini OK"}
