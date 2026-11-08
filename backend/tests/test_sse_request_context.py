"""Do the request contextvars survive into an SSE generator body? (#761)

`RequestIDMiddleware` is a `BaseHTTPMiddleware`. Its dispatch sets the
request-id, DNT/GPC and request-view contextvars, and RESETS them once
`call_next` hands back the response — which, for a streamed response, is
when the headers go out, long before the body has finished. The tutor's SSE
generators (routes/learn.py) do most of their work after that point: usage
rows, `chat.message_sent`, the PostHog mirror (which drops events captured
during a DNT/GPC request).

The question this file settles: do those reads see the request's values, or
the defaults? Starlette runs the downstream app — and with it the streaming
body — in a child task created inside dispatch, AFTER the vars were set. A
task copies the context at creation, so the child's copy is unaffected by the
parent's later reset. These tests pin that, deliberately reading only after
the middleware's dispatch has fully returned (its finally has run), and also
from the worker thread `stream_agent_turn` now runs `on_complete` in.
"""
import asyncio

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sse_starlette.sse import EventSourceResponse

from services.request_context import (
    RequestIDMiddleware,
    current_request_id,
    current_session_user,
    request_has_privacy_signal,
)


def _snapshot() -> dict:
    return {
        "privacy": request_has_privacy_signal(),
        "request_id": current_request_id(),
        "user": current_session_user(),
    }


def _app(seen: dict) -> FastAPI:
    dispatch_done = asyncio.Event()

    class _Probe(RequestIDMiddleware):
        async def dispatch(self, request, call_next):
            try:
                return await super().dispatch(request, call_next)
            finally:
                # Runs after RequestIDMiddleware.dispatch's own finally — the
                # vars have been reset in THIS (the middleware's) context.
                seen["middleware_after"] = _snapshot()
                dispatch_done.set()

    app = FastAPI()
    app.add_middleware(_Probe)

    @app.post("/stream")
    async def stream(request: Request):
        request.state.user_id = "user_probe"

        async def gen():
            yield {"event": "message", "data": "first"}
            # Only read once the middleware has returned and reset its vars.
            await asyncio.wait_for(dispatch_done.wait(), timeout=5)
            seen["generator"] = _snapshot()
            seen["thread"] = await asyncio.to_thread(_snapshot)
            yield {"event": "message", "data": "second"}

        return EventSourceResponse(gen())

    return app


def _run(headers: dict) -> dict:
    seen: dict = {}
    with TestClient(_app(seen)) as client:
        r = client.post("/stream", headers=headers)
        assert r.status_code == 200
        assert "second" in r.text
    return seen


def test_privacy_signal_survives_into_the_sse_generator_after_dispatch_returns():
    seen = _run({"DNT": "1", "X-Request-ID": "rid-probe-0001"})

    # The middleware's own context really was reset...
    assert seen["middleware_after"]["privacy"] is False
    assert seen["middleware_after"]["request_id"] is None
    # ...but the generator (the downstream task's copy) still sees the request.
    assert seen["generator"] == {
        "privacy": True, "request_id": "rid-probe-0001", "user": "user_probe",
    }
    # And so does a worker thread hopped to from the generator (`to_thread`
    # copies the context) — where on_complete now runs.
    assert seen["thread"] == seen["generator"]


def test_no_privacy_signal_reads_false_in_the_generator():
    seen = _run({"Sec-GPC": "0"})
    assert seen["generator"]["privacy"] is False
    assert seen["generator"]["request_id"]  # minted by the middleware
