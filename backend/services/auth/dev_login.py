"""The environment gate and TTL bounds of ``POST /api/auth/test-login`` (#381;
#118, moved from ``routes/auth.py``)."""
# The module (not just its constants) so the gate reads the LIVE APP_ENV
# instead of an import-time snapshot. See _test_auth_enabled below.
import config

# ── Test-only session minting (#381) ──────────────────────────────────────────
# The APP_ENVs in which POST /api/auth/test-login exists at all.
#
# DELIBERATELY NARROWER than config.IS_LOCAL ({local, development, dev, test}).
# This endpoint mints a valid session for an ARBITRARY user id with no credential
# whatsoever, so its blast radius is "full account takeover of every account" if
# it is ever reachable. `development`/`dev` are plausible values for a real
# shared deploy's APP_ENV, and IS_LOCAL is used for unrelated, far less dangerous
# relaxations (unsigned OAuth-state fallback, SESSION_SECRET strength check), so
# widening later by reusing IS_LOCAL would silently arm this too. `local` is the
# developer's own machine and `test` is the pytest/CI harness; nothing else.
TEST_AUTH_ENVS = frozenset({"local", "test"})

TEST_LOGIN_DEFAULT_TTL_SECONDS = 3600
TEST_LOGIN_MAX_TTL_SECONDS = 86400


def _test_auth_enabled() -> bool:
    """Whether POST /api/auth/test-login is available in this environment.

    Evaluated per REQUEST off the live `config` module attribute — never captured
    at import time. That makes the gate monkeypatchable (so the 404-under-
    production behaviour is actually testable) and means no import-ordering
    accident can freeze it in the open position.
    """
    return (getattr(config, "APP_ENV", "") or "").strip().lower() in TEST_AUTH_ENVS
