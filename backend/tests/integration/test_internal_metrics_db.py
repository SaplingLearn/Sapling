"""GET /api/internal/metrics against a real Postgres + real PostgREST.

The hermetic suite (`tests/test_internal_metrics_routes.py`) stubs the RPC, so
it can prove the route refuses bad numbers but not that the SQL produces good
ones. Everything that is actually a claim about the database lives here:

- the three windows are trailing, distinct, and NEST, for users who are active
  only in the wider ones;
- anonymous (`user_id` NULL) and blank-actor rows are not users;
- PostgREST hands a BIGINT count back as a JSON number — the route rejects a
  string, so if that ever changed this is where it would surface;
- the function is executable by `service_role` and by nobody holding the anon
  key, which the frontend ships.

Rows go in over raw psycopg (the lane's rule: never assert through the layer
under test); the read goes through the app, exactly as Canopy's poll does.
"""
import time

import pytest

pytestmark = pytest.mark.integration

URL = "/api/internal/metrics"
TOKEN = "itest-canopy-metrics-token-5b1f0c7e9a3d4f68"


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setenv("CANOPY_METRICS_TOKEN", TOKEN)


@pytest.fixture(scope="module", autouse=True)
def _function_is_in_the_schema_cache(db_conn):
    """PostgREST serves /rpc/<name> from a schema cache; a function created
    after it booted is a 404 until it reloads. The migration NOTIFYs, but the
    reload is asynchronous — ask again and wait for it rather than flake."""
    from db.connection import rpc

    db_conn.execute("NOTIFY pgrst, 'reload schema'")
    deadline = time.monotonic() + 15
    while True:
        try:
            rpc("canopy_active_users", {})
            return
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def _event(db_conn, user_id, age, event_type="chat.message_sent", category="usage"):
    """One `events` row, `age` (a Postgres interval literal) before now."""
    db_conn.execute(
        """
        INSERT INTO events (event_type, category, user_id, created_at)
        VALUES (%s, %s, %s, now() - %s::interval)
        """,
        (event_type, category, user_id, age),
    )


def _get(client):
    return client.get(URL, headers={"Authorization": f"Bearer {TOKEN}"})


def test_an_empty_events_table_is_three_real_zeros(client, db_conn):
    assert db_conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"] == 0
    r = _get(client)
    assert r.status_code == 200
    assert r.json() == {"active_users": {"24h": 0, "7d": 0, "30d": 0}}


def test_windows_are_trailing_distinct_and_nested(client, db_conn):
    _event(db_conn, "it-u-today", "1 hour")
    _event(db_conn, "it-u-today", "2 hours")            # same person twice: once
    _event(db_conn, "it-u-today", "20 days")            # …and again further back
    _event(db_conn, "it-u-edge-day", "23 hours 59 minutes", "error.4xx", "error")
    _event(db_conn, "it-u-week", "3 days", "auth.login", "audit")
    _event(db_conn, "it-u-edge-week", "6 days 23 hours", "auth.login", "audit")
    _event(db_conn, "it-u-month", "29 days", "auth.login", "audit")
    _event(db_conn, "it-u-gone", "31 days", "auth.login", "audit")   # no window
    _event(db_conn, None, "1 hour", "error.4xx", "error")            # anonymous
    _event(db_conn, "", "1 hour", "error.4xx", "error")              # blank actor

    r = _get(client)

    assert r.status_code == 200
    body = r.json()
    assert body == {"active_users": {"24h": 2, "7d": 4, "30d": 5}}
    users = body["active_users"]
    assert users["24h"] <= users["7d"] <= users["30d"]
    assert all(type(v) is int for v in users.values())
    # On the wire: bare JSON integers, never "2" or 2.0.
    assert r.text.replace(" ", "") == '{"active_users":{"24h":2,"7d":4,"30d":5}}'


def test_the_30d_count_agrees_with_admin_analytics(client, db_conn):
    """Same source, same "has a user_id" rule — the two dashboards must not
    disagree about how many people used the app this month."""
    from routes.admin_analytics import _resolve_range, _scan_range

    for i in range(7):
        _event(db_conn, f"it-u-{i}", f"{i * 4 + 1} days")
    _event(db_conn, None, "2 days", "error.4xx", "error")

    from_iso, to_iso = _resolve_range(None, None)
    rows, truncated = _scan_range("events", "user_id,created_at", from_iso, to_iso)
    admin_count = len({r["user_id"] for r in rows if r.get("user_id")})

    assert not truncated
    assert _get(client).json()["active_users"]["30d"] == admin_count == 7


def test_only_the_backend_role_may_execute_the_function(db_conn):
    """PostgREST exposes every public function at /rest/v1/rpc/<name>, and the
    frontend ships the anon key — without the REVOKE the counts would be
    readable straight from Supabase, bypassing the route's bearer token."""
    row = db_conn.execute(
        """
        SELECT has_function_privilege('service_role',  'canopy_active_users()', 'EXECUTE') AS service,
               has_function_privilege('anon',          'canopy_active_users()', 'EXECUTE') AS anon,
               has_function_privilege('authenticated', 'canopy_active_users()', 'EXECUTE') AS authed
        """
    ).fetchone()
    assert row == {"service": True, "anon": False, "authed": False}


def test_wrong_token_is_a_401_with_no_counts(client, db_conn):
    _event(db_conn, "it-u-today", "1 hour")
    r = client.get(URL, headers={"Authorization": "Bearer not-the-token"})
    assert r.status_code == 401
    assert "active_users" not in r.text
