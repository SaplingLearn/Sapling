"""Uvicorn's access log keeps the path, never the query string (services/access_log.py)."""

from __future__ import annotations

import asyncio
import io
import logging

import pytest

from services import access_log


@pytest.fixture
def access_output():
    """Capture what uvicorn.access emits, formatted as uvicorn formats it."""
    logger = logging.getLogger(access_log.ACCESS_LOGGER)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    old_level, old_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = old_propagate


def test_main_installs_the_filter():
    import main  # noqa: F401

    logger = logging.getLogger(access_log.ACCESS_LOGGER)
    assert any(isinstance(f, access_log.StripQueryStringFilter) for f in logger.filters)


def test_install_is_idempotent():
    access_log.install()
    access_log.install()
    logger = logging.getLogger(access_log.ACCESS_LOGGER)
    assert sum(isinstance(f, access_log.StripQueryStringFilter) for f in logger.filters) == 1


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/notes/search?q=my+private+essay", "/api/notes/search"),
        ("/api/x?a=1#frag", "/api/x"),
        ("/api/health", "/api/health"),
    ],
)
def test_uvicorn_shaped_record_loses_its_query(access_output, path, expected):
    access_log.install()
    # Exactly uvicorn's call (protocols/http/h11_impl.py, httptools_impl.py).
    logging.getLogger(access_log.ACCESS_LOGGER).info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", path, "1.1", 200,
    )
    line = access_output.getvalue()
    assert f'"GET {expected} HTTP/1.1" 200' in line
    assert "essay" not in line and "?" not in line


def test_real_uvicorn_request_logs_no_query(access_output):
    """A real request through uvicorn's h11 protocol: the access line it
    writes carries the path only."""
    import httpx
    import uvicorn

    access_log.install()

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def run():
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_config=None,
                                access_log=True, http="h11", lifespan="off")
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve())
        while not server.started:  # noqa: ASYNC110 — uvicorn exposes a flag, not an event
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        async with httpx.AsyncClient() as client:
            r = await client.get(f"http://127.0.0.1:{port}/api/search?q=STUDENT_SECRET_TERM")
            assert r.status_code == 200
        server.should_exit = True
        await task

    asyncio.run(run())
    line = access_output.getvalue()
    assert "/api/search" in line
    assert "STUDENT_SECRET_TERM" not in line and "?" not in line
