"""
Shared pytest configuration for the Sapling backend test suite.

Adds the backend root to sys.path so all module imports resolve correctly
regardless of where pytest is invoked from.

Also installs an autouse fixture that bypasses session auth for tests so
they can exercise route logic without minting real HMAC tokens. The bypass
is test-only and lives entirely inside conftest.py — production code is
unaffected.

Two autouse hermetic guards keep the default lane offline: no test may reach
real Supabase (`_hermetic_supabase_client`, #210) or a real model
(`_hermetic_llm_transport`, #379). The `e2e_staging`, `integration` and
`live_llm` markers are the documented opt-outs.
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
    config.addinivalue_line(
        "markers",
        "integration: opt-in tests against the REAL local Supabase stack (needs the "
        "stack up + RUN_INTEGRATION=1). Bypasses the hermetic DB + auth fixtures.",
    )
    config.addinivalue_line(
        "markers",
        "live_llm: this test deliberately calls a REAL model (billable). Bypasses the "
        "hermetic LLM fixture; pair it with a skipif so it only runs when a key is set.",
    )


@pytest.fixture(autouse=True)
def _clear_rate_limit_state():
    """#544: services/request_limits keeps its sliding windows in a
    process-global dict, so one test's burst of requests would throttle
    every later test that hits the same route as the same user. Same
    reasoning as the lru_cache reset below."""
    from services import request_limits

    request_limits._rate_state.clear()
    yield
    request_limits._rate_state.clear()


@pytest.fixture(autouse=True)
def _clear_lru_caches():
    """#98: reset the per-process lru_caches around every test so one test's
    mocked DB state can't leak into another via a cached read."""
    from services import academics, course_context_service, growth
    academics.clear_academics_caches()
    course_context_service.clear_course_context_cache()
    growth.clear_growth_cache()
    yield
    academics.clear_academics_caches()
    course_context_service.clear_course_context_cache()
    growth.clear_growth_cache()


@pytest.fixture(autouse=True)
def _reset_events_service():
    """#118/#116: reset the observability queue, drop-counter, and one-time
    pricing-warning state around every test, so a queued row, a tripped
    overflow counter, or a shrunk test queue can't leak into the next test."""
    from services import events_service
    events_service.reset_for_tests()
    yield
    events_service.reset_for_tests()


@pytest.fixture
def sink():
    """Collect events the code under test enqueues, instead of hitting the DB.

    Shared because two suites (`test_tool_signals_f5.py`,
    `test_quiz_tool_instrumentation.py`) had byte-for-byte copies of it, and
    the copies had already drifted: one drained the worker queue on teardown
    and the other didn't, so a row enqueued but not flushed by a test could
    surface in the NEXT test's list. The post-yield `flush_now()` is the
    load-bearing half — keep it.

    Yields the list of enqueued rows. A test that asserts on rows still calls
    `events_service.flush_now()` itself first: enqueueing is asynchronous, so
    the list is only complete after a drain.
    """
    from unittest.mock import MagicMock, patch

    from services import events_service

    events_service.reset_for_tests()
    rows: list[dict] = []

    def _capture(name):
        m = MagicMock()
        m.insert.side_effect = lambda payload: rows.extend(
            payload if isinstance(payload, list) else [payload]
        )
        return m

    with patch("services.events_service.table", side_effect=_capture):
        yield rows
        events_service.flush_now()


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
    if request.node.get_closest_marker("e2e_staging") or request.node.get_closest_marker("integration"):
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


class UnstubbedLLMEgress(RuntimeError):
    """Raised by `_hermetic_llm_transport` when a test reaches the LLM network."""


# Every google-genai call — unary, streaming, sync, async, plus the File API's
# upload/download side channels — bottoms out in one of these BaseApiClient
# methods. We patch the CLASS, not an instance: clients are built in several
# places (services/rag_service.py's module-level client, and the pydantic-ai
# GoogleProviders that agents/_providers.py builds per event loop), so
# instance-level patching would miss whichever client
# was already constructed. Names are probed with hasattr so a google-genai bump
# that drops a private helper degrades gracefully instead of erroring.
_GENAI_EGRESS_METHODS = (
    # Public transport entry points (stable across google-genai majors).
    "request", "request_streamed", "async_request", "async_request_streamed",
    # Lower-level chokepoints, in case a public wrapper is ever bypassed.
    "_request", "_request_once", "_async_request", "_async_request_once",
    # File API paths that skip the request pipeline and drive httpx directly.
    "upload_file", "async_upload_file", "download_file", "async_download_file",
    "_upload_fd", "_async_upload_fd",
)
# If these ever stop existing the guard has silently become a no-op, which is
# worse than no guard at all — fail loudly instead.
_GENAI_REQUIRED_METHODS = ("request", "async_request")


@pytest.fixture(autouse=True)
def _hermetic_llm_transport(request, monkeypatch):
    """Hermetic safety net (#379): no test may make a real LLM call.

    The sibling `_hermetic_supabase_client` guarantees the default lane never
    touches Supabase; this is the same guarantee for Gemini. Without it, a
    forgotten `patch(...)` plus a `GEMINI_API_KEY` in the environment (CI sets a
    dummy one, dev machines have a real one) turns a unit test into a real,
    billable network call — silently, since a passing test looks identical
    either way. Rather than stub agent logic, we cut the wire underneath it:
    the google-genai transport class raises instead of dialling out, so an
    unstubbed call path fails with a pointed error naming the escape hatch.

    The opt-in lanes are the exceptions: `e2e_staging` and `integration` talk to
    real infrastructure, and `live_llm` marks the handful of tests (see
    test_ocr_pipeline.py) that deliberately exercise a live model.
    """
    if (
        request.node.get_closest_marker("e2e_staging")
        or request.node.get_closest_marker("integration")
        or request.node.get_closest_marker("live_llm")
    ):
        return
    from google.genai import _api_client as genai_api_client

    def _blocked(*_args, **_kwargs):
        raise UnstubbedLLMEgress(
            "unstubbed LLM egress: this test reached the google-genai transport "
            "(google.genai._api_client.BaseApiClient) and would have made a real, "
            "billable model call. Patch the service/agent seam the code path uses "
            "(e.g. <agent>.run, services.rag_service._client), or mark the "
            "test @pytest.mark.live_llm if the live call is intentional."
        )

    # Lets tests assert the guard is installed without invoking it.
    _blocked._sapling_llm_guard = True

    patched = []
    for name in _GENAI_EGRESS_METHODS:
        if hasattr(genai_api_client.BaseApiClient, name):
            monkeypatch.setattr(genai_api_client.BaseApiClient, name, _blocked)
            patched.append(name)

    missing = [n for n in _GENAI_REQUIRED_METHODS if n not in patched]
    if missing:  # pragma: no cover - only trips on a google-genai API change
        raise RuntimeError(
            f"hermetic LLM guard could not patch {missing} on "
            "google.genai._api_client.BaseApiClient — the installed google-genai "
            "moved its transport seam. Update _GENAI_EGRESS_METHODS in "
            "tests/conftest.py; do not leave the suite unguarded."
        )


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
    if request.node.get_closest_marker("e2e_staging") or request.node.get_closest_marker("integration"):
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
