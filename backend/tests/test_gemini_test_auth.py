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
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


class TestGeminiTestAuth:
    def test_unauthenticated_returns_401_and_makes_no_llm_call(self):
        # Restore the real guard so a request with no cookie/token => 401,
        # undoing the autouse bypass from conftest. require_admin calls
        # get_session_user_id first, which raises 401 before any role lookup.
        from services import auth_guard

        probe = AsyncMock()
        with patch.object(
            auth_guard, "require_admin", auth_guard._real_require_admin
        ), patch.object(
            auth_guard, "get_session_user_id", auth_guard._real_get_session_user_id
        ), patch.object(
            auth_guard, "_decode_session", auth_guard._real_decode_session
        ), patch("agents.health.health_probe_agent.run", new=probe):
            r = client.get("/api/gemini-test")

        # Pre-fix this returned 200 with {"ok": ...}; the fix makes it 401 and,
        # critically, the LLM is never called for an anonymous request.
        assert r.status_code == 401
        probe.assert_not_called()

    def test_admin_reaches_handler(self):
        # Autouse bypass stubs require_admin to a no-op, so an admin-equivalent
        # request reaches the handler. Mock the probe agent so the test is hermetic.
        probe = AsyncMock(return_value=SimpleNamespace(output="Gemini OK"))
        with patch("agents.health.health_probe_agent.run", new=probe):
            r = client.get("/api/gemini-test")

        assert r.status_code == 200
        assert r.json() == {"ok": True, "reply": "Gemini OK"}

    def test_admin_probe_failure_returns_ok_false(self):
        # Autouse bypass reaches the handler; when the probe raises, the endpoint
        # surfaces the error as {"ok": False, "error": ...} and still returns 200.
        probe = AsyncMock(side_effect=RuntimeError("bad key"))
        with patch("agents.health.health_probe_agent.run", new=probe):
            r = client.get("/api/gemini-test")

        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert "bad key" in body["error"]
