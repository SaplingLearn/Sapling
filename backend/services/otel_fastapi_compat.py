"""Compatibility guard for otel FastAPI instrumentation on FastAPI >= 0.138.

The bug
-------
`opentelemetry.instrumentation.fastapi._get_route_details(scope)` walks
`app.routes` looking for the route a request matched, and reads `.path` off
each candidate:

    if match == Match.FULL:
        try:
            route = starlette_route.path
        except AttributeError:
            # routes added via host routing won't have a path attribute
            route = scope.get("path")
        break
    if match == Match.PARTIAL:
        route = starlette_route.path      # <-- no guard

From FastAPI 0.138, `app.include_router(...)` leaves `_IncludedRouter`
objects in `app.routes`, and those have no `.path`. The FULL branch already
tolerates a path-less route; the PARTIAL branch does not.

A PARTIAL match is precisely what a **wrong-method request** produces — the
path matches, the method does not. So every 405 raised `AttributeError` out
of the instrumentation middleware instead of returning 405.

That is not a test-only concern: staging and production install the same
hash-pinned lock (fastapi 0.138.0, opentelemetry-instrumentation-fastapi
0.63b1), so a 405 on the deployed API became a 500.

Why patch rather than upgrade
-----------------------------
There is nothing to upgrade to: the unguarded line is present in every
released `opentelemetry-instrumentation-fastapi` through 0.65b0 (checked
against the published wheels). Pinning FastAPI back below 0.138 to dodge it
would trade a one-line shim for a framework downgrade.

Why this was invisible locally
------------------------------
The dev venv runs older resolved dependencies than `requirements.lock`
(fastapi 0.136 / starlette 1.0 at the time of writing), and pre-0.138
FastAPI puts no `_IncludedRouter` in `app.routes`. The full suite was green
locally and red in CI on exactly one test. Reproduced at the locked versions
in a scratch environment before fixing.

Remove this module when a released otel version guards the PARTIAL branch;
`tests/test_otel_fastapi_compat.py` pins the behaviour until then.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


def _guard(original: Callable) -> Callable:
    """Wrap otel's route resolver so a path-less route degrades instead of raising.

    Only `AttributeError` is absorbed, and the fallback (`scope["path"]`) is
    the one otel's own FULL-match branch already uses for host-routed routes
    — this applies an existing behaviour to the branch that missed it rather
    than inventing a new one. Any other exception is a real defect and stays
    visible.
    """

    def _get_route_details_guarded(scope):
        try:
            return original(scope)
        except AttributeError:
            # A route object with no `.path` (FastAPI >= 0.138's
            # `_IncludedRouter`). The concrete path is a worse span name than
            # the route template, but it is vastly better than a 500.
            return scope.get("path")

    _get_route_details_guarded._sapling_guarded = True  # type: ignore[attr-defined]
    _get_route_details_guarded._sapling_original = original  # type: ignore[attr-defined]
    return _get_route_details_guarded


def install_route_details_guard() -> bool:
    """Install the guard. Idempotent; returns True if it is in place.

    Never raises: this runs at import time in `main.py`, and a failure to
    install observability compatibility must not stop the app from booting.
    """
    try:
        import opentelemetry.instrumentation.fastapi as otel_fastapi
    except Exception:  # pragma: no cover - otel is a hard dep in practice
        logger.debug("otel fastapi instrumentation not importable; guard skipped")
        return False

    current = getattr(otel_fastapi, "_get_route_details", None)
    if current is None:  # pragma: no cover - upstream renamed it
        logger.warning(
            "otel fastapi: _get_route_details is gone; the 405 guard no longer "
            "applies — re-check whether the upstream bug is fixed"
        )
        return False
    if getattr(current, "_sapling_guarded", False):
        # Already wrapped. Wrapping again would stack a redundant layer per
        # import, which matters in test runs that re-import main.
        return True

    otel_fastapi._get_route_details = _guard(current)
    return True
