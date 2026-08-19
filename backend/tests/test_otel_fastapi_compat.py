"""The 405 crash: FastAPI 0.138 + opentelemetry-instrumentation-fastapi.

`app.include_router(...)` puts `_IncludedRouter` objects in `app.routes` from
FastAPI 0.138 onward. otel's route-detail resolver reads `.path` off each
candidate route; the FULL-match branch guards that read with
`except AttributeError`, but the PARTIAL-match branch does not — and a
PARTIAL match is exactly what a wrong-method request produces.

So every 405 raised `AttributeError` out of the instrumentation middleware
instead of returning 405. Not a test-only problem: it is what the deployed
app does, since staging/prod install the same hash-pinned lock.

Verified against the LOCKED versions (fastapi 0.138.0, starlette 1.3.1,
opentelemetry-instrumentation-fastapi 0.63b1) in a scratch env, because the
dev venv runs older deps and cannot reproduce it. Present in every released
otel version through 0.65b0, so there is nothing to upgrade to.
"""

from services import otel_fastapi_compat as compat


def test_guard_is_installed_at_import_time():
    """main.py installs it before instrumenting; importing the app is enough."""
    import main  # noqa: F401

    import opentelemetry.instrumentation.fastapi as otel_fastapi

    assert getattr(otel_fastapi._get_route_details, "_sapling_guarded", False)


def test_guard_falls_back_to_the_scope_path_on_attribute_error():
    """The fallback is the SAME one otel's FULL-match branch already uses for
    host-routed routes — this is not inventing a new behaviour, it is
    applying the existing one to the branch that was missed."""
    calls = []

    def _boom(scope):
        calls.append(scope)
        raise AttributeError("'_IncludedRouter' object has no attribute 'path'")

    guarded = compat._guard(_boom)
    assert guarded({"path": "/api/quiz/submit"}) == "/api/quiz/submit"
    assert len(calls) == 1


def test_guard_passes_through_a_normal_resolution():
    guarded = compat._guard(lambda scope: "/api/quiz/{quiz_id}")
    assert guarded({"path": "/api/quiz/abc"}) == "/api/quiz/{quiz_id}"


def test_guard_does_not_swallow_other_errors():
    """Only AttributeError. A KeyError or TypeError from the resolver is a
    real defect and must stay visible."""
    def _boom(scope):
        raise KeyError("something else")

    guarded = compat._guard(_boom)
    try:
        guarded({"path": "/x"})
    except KeyError:
        return
    raise AssertionError("KeyError should propagate")


def test_install_is_idempotent():
    """Called at import; a second call must not wrap the wrapper (which would
    stack a fallback layer per import in test runs)."""
    import opentelemetry.instrumentation.fastapi as otel_fastapi

    compat.install_route_details_guard()
    first = otel_fastapi._get_route_details
    compat.install_route_details_guard()
    assert otel_fastapi._get_route_details is first


def test_method_not_allowed_returns_405_not_a_crash():
    """End-to-end at whatever versions are installed. Under the locked
    fastapi this fails without the guard; under older fastapi it passes
    either way — which is precisely why CI caught it and the dev venv did
    not."""
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    r = client.get("/api/quiz/submit")  # POST-only route
    assert r.status_code == 405
