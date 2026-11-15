"""The browser origins the backend's CORS middleware admits (main.py).

The deployed frontends reach the API same-origin through their /api rewrite,
so CORS only matters for a browser calling the API origin directly. A
credentialed allowlist entry lets that origin read every response with the
student's cookie attached, so a localhost origin belongs only on a backend
that runs locally: on a deployed one, anything listening on a visitor's
localhost:3000 (another dev server, a malicious local page) could read their
Sapling data.
"""

from __future__ import annotations

from collections.abc import Iterable

# The local dev frontend (`next dev` on PORT 3000), admitted only on a local
# or test backend.
LOCAL_DEV_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")

# APP_ENV values that mean "this backend runs on a developer's machine or in
# a test harness" — the same set as routes/auth.py TEST_AUTH_ENVS.
LOCAL_APP_ENVS = frozenset({"local", "test"})

PUBLIC_SITE_ORIGINS = ("https://saplinglearn.com", "https://www.saplinglearn.com")


def allowed_origins(frontend_url: str, app_env: str, extra: Iterable[str] = ()) -> list[str]:
    """The sorted, de-duplicated CORS allowlist for this deployment.

    ``frontend_url`` is the configured FRONTEND_URL (always admitted, even when
    it is itself a localhost URL — that is the operator's explicit choice);
    ``extra`` is the CORS_ORIGINS list. Localhost dev origins are added only
    when ``app_env`` is local/test.
    """
    origins = {(frontend_url or "").strip().rstrip("/"), *PUBLIC_SITE_ORIGINS}
    origins.update(o.strip().rstrip("/") for o in extra)
    if (app_env or "").strip().lower() in LOCAL_APP_ENVS:
        origins.update(LOCAL_DEV_ORIGINS)
    origins.discard("")
    return sorted(origins)
