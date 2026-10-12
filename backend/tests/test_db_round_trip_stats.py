"""Per-request PostgREST round-trip accounting (perf plan B6).

`db.connection` counts every PostgREST call made while a request's stats
list is installed, and RequestIDMiddleware appends `db=N/Xms` to its log
line. The hermetic fixture swaps `_client` for a MagicMock, so these build a
real client over a mock transport with the production hooks and limits.
"""

import asyncio
import logging

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from db import connection
from services.request_context import RequestIDMiddleware


def _client():
    return connection._make_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    )


def test_counts_round_trips_while_stats_are_installed():
    client = _client()
    stats, token = connection.start_db_stats()
    try:
        client.get("http://supabase.test/rest/v1/users")
        client.post("http://supabase.test/rest/v1/users", json={})
    finally:
        connection.stop_db_stats(token)
    assert stats[0] == 2
    assert stats[1] >= 0.0


def test_no_stats_installed_is_a_no_op():
    # Background threads and scripts make calls outside any request.
    assert _client().get("http://supabase.test/rest/v1/users").status_code == 200


def test_threads_share_the_requests_counter():
    # Sync routes run in a threadpool and async ones offload to
    # asyncio.to_thread; both copy the context, so they must increment the
    # SAME list the middleware installed.
    client = _client()
    stats, token = connection.start_db_stats()
    try:
        asyncio.run(asyncio.to_thread(client.get, "http://supabase.test/rest/v1/x"))
    finally:
        connection.stop_db_stats(token)
    assert stats[0] == 1


def test_client_keeps_connections_warm():
    # httpx's default keepalive_expiry is 5s, which at current traffic meant
    # a fresh TLS handshake to Supabase on most requests' first query.
    pool = connection._make_client()._transport._pool
    assert pool._keepalive_expiry >= 30


def test_request_log_line_carries_the_db_count(monkeypatch, caplog):
    client = _client()
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/probe")
    def probe():
        client.get("http://supabase.test/rest/v1/a")
        client.get("http://supabase.test/rest/v1/b")
        return {"ok": True}

    with caplog.at_level(logging.INFO, logger="sapling.request"):
        assert TestClient(app).get("/probe").status_code == 200
    line = next(r.getMessage() for r in caplog.records if "/probe" in r.getMessage())
    assert " db=2/" in line
