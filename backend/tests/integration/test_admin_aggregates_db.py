"""The admin aggregates against real Postgres (wave 3, #116/#115):
jobs_overview() (20261109023347) and db_scope_divergences() (20261109023455).

SQL only (no app imports): the hermetic suite (tests/test_admin_jobs.py,
tests/test_db_scope_report.py) pins how the routes read the answers and that
the SQL path reports what the old scan reported; this pins the SQL itself.
"""
import json

import pytest

pytestmark = pytest.mark.integration

_EVENTS = ["db.rls_shadow_divergence", "db.unscoped_query", "db.rls_denied"]


# ── jobs_overview ───────────────────────────────────────────────────────────


def test_jobs_overview_counts_every_type_and_status(db_conn):
    db_conn.execute("DELETE FROM public.jobs WHERE type LIKE 'w3t.%'")
    for type_, status, age in [
        ("w3t.a", "queued", "3 hours"), ("w3t.a", "queued", "1 hour"),
        ("w3t.a", "running", "2 hours"), ("w3t.b", "dead", "1 day"),
    ]:
        db_conn.execute(
            "INSERT INTO public.jobs (type, status, created_at) "
            "VALUES (%s, %s, now() - %s::interval)", (type_, status, age))
    rows = db_conn.execute(
        "SELECT type, status, n, oldest_created_at < now() - interval '170 minutes' AS old "
        "FROM public.jobs_overview() WHERE type LIKE 'w3t.%' ORDER BY type, status"
    ).fetchall()
    assert [(r["type"], r["status"], r["n"]) for r in rows] == [
        ("w3t.a", "queued", 2), ("w3t.a", "running", 1), ("w3t.b", "dead", 1)]
    assert rows[0]["old"] is True  # the OLDEST queued row's age
    db_conn.execute("DELETE FROM public.jobs WHERE type LIKE 'w3t.%'")


# ── db_scope_divergences ────────────────────────────────────────────────────


def _event(conn, event_type, payload, *, user=None, rid=None, ago="1 minute"):
    conn.execute(
        "INSERT INTO public.events (event_type, category, user_id, request_id, payload, "
        "created_at) VALUES (%s, 'system', %s, %s, %s::jsonb, now() - %s::interval)",
        (event_type, user, rid, json.dumps(payload), ago))


def _groups(conn):
    return conn.execute(
        "SELECT k, n, users, request_ids FROM public.db_scope_divergences("
        "now() - interval '1 hour', now(), %s) ORDER BY n DESC, k::text", (_EVENTS,)
    ).fetchall()


def test_db_scope_divergences_groups_by_the_raw_key(db_conn):
    db_conn.execute("DELETE FROM public.events WHERE event_type = ANY(%s)", (_EVENTS,))
    div = {"table": "notes", "route": "/r", "kind": "fewer_rows", "method": "GET",
           "op": "select", "service_count": 2, "scoped_count": 1}
    _event(db_conn, "db.rls_shadow_divergence", div, user="u1", rid="a", ago="5 minutes")
    _event(db_conn, "db.rls_shadow_divergence", {**div, "service_count": 9},
           user="u2", rid="b", ago="4 minutes")
    _event(db_conn, "db.rls_shadow_divergence", div, user="u2", rid="c", ago="3 minutes")
    _event(db_conn, "db.rls_shadow_divergence", div, user="", rid="c", ago="2 minutes")
    _event(db_conn, "db.rls_shadow_divergence", div, rid="d", ago="1 minute")
    # Legacy rows: no kind, so the counts are part of the key; `error` stands
    # in for a missing `status` key, but not for a present one.
    _event(db_conn, "db.rls_shadow_divergence", {"table": "t", "service_count": 1,
                                                 "scoped_count": 3})
    _event(db_conn, "db.rls_shadow_divergence", {"table": "t", "error": "403"})
    _event(db_conn, "db.rls_denied", {"table": "t", "status": None, "error": "x"})
    # Out of scope: another event type, and one outside the window.
    _event(db_conn, "quiz.started", div)
    _event(db_conn, "db.unscoped_query", div, ago="2 hours")

    rows = _groups(db_conn)
    top = rows[0]
    assert top["k"] == ["db.rls_shadow_divergence", "fewer_rows", None, "GET", "/r", "notes",
                        "select", None, None, None, None]
    assert top["n"] == 5  # the differing service_count does NOT split a kinded group
    assert sorted(top["users"]) == ["u1", "u2"]  # NULL and '' are not users
    assert [r["id"] for r in top["request_ids"]] == ["d", "c", "b"]  # newest 3, distinct
    keys = [r["k"] for r in rows[1:]]
    assert ["db.rls_shadow_divergence", None, None, None, None, "t", None, None, None, 1, 3] in keys
    assert ["db.rls_shadow_divergence", None, None, None, None, "t", None, "403", None,
            None, None] in keys
    assert ["db.rls_denied", None, None, None, None, "t", None, None, None, None, None] in keys
    assert sum(r["n"] for r in rows) == 8
    db_conn.execute("DELETE FROM public.events WHERE event_type = ANY(%s)", (_EVENTS,))


def test_db_scope_divergences_is_empty_for_an_empty_window(db_conn):
    db_conn.execute("DELETE FROM public.events WHERE event_type = ANY(%s)", (_EVENTS,))
    assert _groups(db_conn) == []
