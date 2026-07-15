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
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("ENCRYPTION_KEY", "0" * 64)  # 32-byte all-zero key for deterministic tests
# Tests run as local mode so validate_config() (invoked by the one test that
# enters the FastAPI lifespan) doesn't reject the short dummy SESSION_SECRET the
# CI env supplies. Production defaults APP_ENV=production (strict). #174.
os.environ.setdefault("APP_ENV", "test")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "e2e_staging: opt-in HTTP E2E against the REAL staging DB (writes a throwaway "
        "fixture). Bypasses the hermetic DB + auth fixtures; skipped unless RUN_STAGING_E2E=1.",
    )


@pytest.fixture(autouse=True)
def _clear_lru_caches():
    """#98: reset the per-process lru_caches around every test so one test's
    mocked DB state can't leak into another via a cached read."""
    from services import academics, course_context_service
    academics.clear_academics_caches()
    course_context_service.clear_course_context_cache()
    yield
    academics.clear_academics_caches()
    course_context_service.clear_course_context_cache()


@pytest.fixture(autouse=True)
def _hermetic_supabase_client(request, monkeypatch):
    """Hermetic safety net (#210): no test may make a real Supabase call.

    Every db access ultimately flows through `db.connection._client` (the single
    persistent httpx.Client behind SupabaseTable). Routes/services that call
    `db.connection.table()` directly — e.g. `apply_graph_update` inside the
    document-upload legacy pipeline — would otherwise escape a test's per-route
    `table` mock and hit the network (the whole `test_documents_routes` module
    was failing/quarantined for exactly this reason). Replace that client with a
    stub returning benign empty responses. Tests that need specific db data still
    patch their own `table`/service reference; this only catches what escapes.

    The opt-in `e2e_staging` test is the one exception: it intentionally talks to
    the real staging DB, so we leave the live client in place for it.
    """
    if request.node.get_closest_marker("e2e_staging"):
        return
    import db.connection as dbconn

    def _empty_response(*_args, **_kwargs):
        resp = MagicMock(name="supabase_response")
        resp.raise_for_status.return_value = None
        resp.json.return_value = []
        resp.headers = {}
        return resp

    fake_client = MagicMock(name="hermetic_supabase_client")
    for verb in ("get", "post", "patch", "delete"):
        getattr(fake_client, verb).side_effect = _empty_response
    monkeypatch.setattr(dbconn, "_client", fake_client)


@pytest.fixture(autouse=True)
def _bypass_session_auth(request, monkeypatch):
    """Stub the auth guard so tests don't need to mint session tokens.

    Tests historically called routes with `user_id` in the body/query/path
    and no session token. After the auth-guard hardening (no query-param
    fallback for identity), routes return 401 without a valid session.
    To keep the existing test contract working, we replace
    `require_self` / `require_admin` / `get_session_user_id` with stubs
    in every place they were imported.

    The opt-in `e2e_staging` test exercises the REAL auth path (it mints valid
    HMAC sessions and asserts 401 without one), so we leave the guard intact for it.
    """
    if request.node.get_closest_marker("e2e_staging"):
        return
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

    auth_guard._real_decode_session = auth_guard._decode_session
    auth_guard._real_require_self = auth_guard.require_self
    auth_guard._real_get_session_user_id = auth_guard.get_session_user_id
    auth_guard._real_require_admin = auth_guard.require_admin
    auth_guard._real_require_role = auth_guard.require_role

    monkeypatch.setattr(auth_guard, "_decode_session", _decode_session_stub)
    monkeypatch.setattr(auth_guard, "require_self", _require_self_stub)
    monkeypatch.setattr(auth_guard, "get_session_user_id", _get_session_user_id_stub)
    monkeypatch.setattr(auth_guard, "require_admin", _require_admin_stub)
    monkeypatch.setattr(auth_guard, "require_role", _require_role_stub)

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
