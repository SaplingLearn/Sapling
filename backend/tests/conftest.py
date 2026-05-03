"""
Shared pytest configuration for the Sapling backend test suite.

Adds the backend root to sys.path so all module imports resolve correctly
regardless of where pytest is invoked from.

Also installs an autouse fixture that bypasses session auth for tests so
they can exercise route logic without minting real HMAC tokens. The bypass
is test-only and lives entirely inside conftest.py — production code is
unaffected.
"""
import sys
import os
import pytest

os.environ.setdefault("ENCRYPTION_KEY", "0" * 64)  # 32-byte all-zero key for deterministic tests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _bypass_session_auth(monkeypatch):
    """Stub the auth guard so tests don't need to mint session tokens.

    Tests historically called routes with `user_id` in the body/query/path
    and no session token. After the auth-guard hardening (no query-param
    fallback for identity), routes return 401 without a valid session.
    To keep the existing test contract working, we replace
    `require_self` / `require_admin` / `get_session_user_id` with stubs
    in every place they were imported.
    """
    from services import auth_guard

    def _decode_session_stub(request):
        uid = (
            request.query_params.get("user_id")
            or request.path_params.get("user_id")
            or "user_andres"
        )
        return {"user_id": uid, "exp": 9999999999}

    def _get_session_user_id_stub(request):
        return _decode_session_stub(request)["user_id"]

    def _require_self_stub(user_id, request):
        return None

    def _require_admin_stub(request):
        return None

    def _require_role_stub(role_slug):
        def _checker(request):
            return None
        return _checker

    monkeypatch.setattr(auth_guard, "_decode_session", _decode_session_stub)

    for mod_name in list(sys.modules):
        if not mod_name.startswith("routes."):
            continue
        mod = sys.modules[mod_name]
        if hasattr(mod, "require_self"):
            monkeypatch.setattr(mod, "require_self", _require_self_stub)
        if hasattr(mod, "get_session_user_id"):
            monkeypatch.setattr(mod, "get_session_user_id", _get_session_user_id_stub)
        if hasattr(mod, "require_admin"):
            monkeypatch.setattr(mod, "require_admin", _require_admin_stub)
        if hasattr(mod, "require_role"):
            monkeypatch.setattr(mod, "require_role", _require_role_stub)
