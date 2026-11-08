"""The ``db_user_scope`` shadow report (#115, docs/security/db-user-scope-rollout.md):
db/scope_report.py, its feeds in db/scope.py + db/connection.py, and the admin
``GET /api/admin/analytics/db-scope`` view.

Hermetic: the wire is test_db_user_scope's recording fake for the shared httpx
client, and requests run through a small app carrying the real
RequestIDMiddleware (route template, method, request id, session subject).

What is pinned:

* every would-be denial in shadow is ONE structured WARNING line carrying the
  route TEMPLATE, HTTP method, table/rpc, operation, kind, status/code and the
  request id, and is counted; never row contents or the raw path;
* the kinds: fewer/more rows, different ids, a scoped error (status + PostgREST
  code), a write naming another user's ``user_id``;
* writes are never executed twice; what is known about them is tallied;
* the read-only rpc allowlist is shadowed, every other rpc is not;
* flag ``off``: none of it runs (no tally, no line, no route-template work);
* the admin report merges the process tally with the ``events`` table.
"""
from __future__ import annotations

import logging

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import db.connection as dbconn
from db import scope as db_scope
from db import scope_report
from db import user_jwt
from db.connection import rpc, table
from services import auth_guard, request_context
from tests.test_db_user_scope import ANON, FLAG_ENV, OCT_JWK, Wire, _app, _cookie

SECRET_MARKER = "row-content-that-must-never-be-logged"


@pytest.fixture
def wire(monkeypatch):
    w = Wire()
    monkeypatch.setattr(dbconn, "_client", w.client)
    return w


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    user_jwt.clear_token_cache()
    scope_report.reset()
    monkeypatch.delenv(FLAG_ENV, raising=False)
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    monkeypatch.setenv(user_jwt.ANON_KEY_ENV, ANON)
    db_scope._warned.clear()
    # The real session decoder (the conftest stubs it), so the subject is
    # whatever the cookie says.
    monkeypatch.setattr(auth_guard, "_decode_session", auth_guard._real_decode_session)
    monkeypatch.setattr(auth_guard, "get_session_user_id", auth_guard._real_get_session_user_id)
    yield
    scope_report.reset()
    user_jwt.clear_token_cache()


@pytest.fixture
def events(monkeypatch):
    seen: list[tuple[str, dict, str | None, str | None]] = []
    monkeypatch.setattr(
        db_scope, "_emit",
        lambda event, *, user_id, payload, request_id=None: seen.append(
            (event, payload, user_id, request_id)),
    )
    return seen


@pytest.fixture
def inline_shadow(monkeypatch):
    monkeypatch.setattr(dbconn, "_submit_shadow", lambda fn, *args: fn(*args))
    monkeypatch.setattr(db_scope.random, "random", lambda: 0.0)


def _scoped(headers) -> bool:
    return bool(headers) and "Bearer ey" in str(headers)


def _lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.getMessage().startswith(scope_report.LOG_TOKEN)]


def _note_app(handler, method="get"):
    """A route with a path parameter, so the template differs from the path."""
    return _app(handler, path="/notes/{note_id}", method=method)


# ── Reads: one line per divergence, with everything needed to act on it ─────


def test_shadow_read_divergence_is_one_structured_line_and_counted(
        wire, monkeypatch, inline_shadow, events, caplog):
    monkeypatch.setenv(FLAG_ENV, "shadow")
    wire.rows = lambda verb, url, headers: (
        [{"id": "n1", "body": SECRET_MARKER}] if _scoped(headers)
        else [{"id": "n1", "body": SECRET_MARKER}, {"id": "n2", "body": SECRET_MARKER}])

    def handler(note_id: str):
        return {"rows": table("notes").select("id,body", filters={"id": f"eq.{note_id}"})}

    with caplog.at_level(logging.DEBUG, logger="sapling.db_scope"):
        r = _note_app(handler).get("/notes/abc-123", cookies=_cookie("user_1"),
                                   headers={"X-Request-ID": "req-12345678"})
    assert r.status_code == 200 and len(r.json()["rows"]) == 2  # the service answer

    (line,) = _lines(caplog)
    assert line == ("db_user_scope.divergence event=db.rls_shadow_divergence kind=fewer_rows "
                    "mode=shadow method=GET route=/notes/{note_id} target=notes op=select "
                    "status=- code=- service_rows=2 scoped_rows=1 request_id=req-12345678 "
                    "user=user_1")
    assert all(r.levelno == logging.WARNING for r in caplog.records
               if r.getMessage().startswith(scope_report.LOG_TOKEN))
    assert SECRET_MARKER not in caplog.text and "abc-123" not in caplog.text
    (event, payload, user_id, request_id), = events
    assert event == "db.rls_shadow_divergence" and user_id == "user_1"
    assert request_id == "req-12345678"
    assert SECRET_MARKER not in str(payload) and "abc-123" not in str(payload)

    snap = scope_report.snapshot()
    (row,) = snap["divergences"]
    assert row["count"] == 1 and row["kind"] == "fewer_rows" and row["route"] == "/notes/{note_id}"
    assert row["method"] == "GET" and row["target"] == "notes" and row["op"] == "select"
    assert row["last_request_id"] == "req-12345678"
    assert snap["shadow_reads"] == {"sampled": 1, "compared": 1, "diverged": 1}


@pytest.mark.parametrize("service,scoped,kind", [
    ([{"id": "a"}], [{"id": "a"}, {"id": "b"}], "more_rows"),
    ([{"id": "a"}], [{"id": "b"}], "different_ids"),
])
def test_shadow_read_kinds(wire, monkeypatch, inline_shadow, events, service, scoped, kind):
    monkeypatch.setenv(FLAG_ENV, "shadow")
    wire.rows = lambda verb, url, headers: scoped if _scoped(headers) else service
    _app(lambda: table("notes").select("id")).get("/probe", cookies=_cookie("u1"))
    assert [p["kind"] for _, p, _, _ in events] == [kind]


def test_shadow_scoped_error_carries_status_and_postgrest_code(
        wire, monkeypatch, inline_shadow, events, caplog):
    monkeypatch.setenv(FLAG_ENV, "shadow")
    wire.status = lambda verb, url, headers: 403 if _scoped(headers) else 200
    wire.rows = lambda verb, url, headers: (
        {"code": "42501", "message": f"permission denied {SECRET_MARKER}"} if _scoped(headers)
        else [{"id": "n1"}])
    with caplog.at_level(logging.WARNING, logger="sapling.db_scope"):
        r = _app(lambda: table("notes").select("id")).get("/probe", cookies=_cookie("u1"))
    assert r.status_code == 200
    (line,) = _lines(caplog)
    assert "kind=error" in line and "status=403" in line and "code=42501" in line
    assert SECRET_MARKER not in caplog.text
    (_, payload, _, _), = events
    assert payload["status"] == 403 and payload["code"] == "42501" and payload["error"] == "403"
    assert payload["scoped_count"] == -1


def test_shadow_agreement_is_counted_but_silent(wire, monkeypatch, inline_shadow, events, caplog):
    monkeypatch.setenv(FLAG_ENV, "shadow")
    wire.rows = lambda verb, url, headers: [{"id": "n1"}]
    with caplog.at_level(logging.DEBUG, logger="sapling.db_scope"):
        _app(lambda: table("notes").select("id")).get("/probe", cookies=_cookie("u1"))
    assert _lines(caplog) == [] and events == []
    snap = scope_report.snapshot()
    assert snap["divergences"] == [] and snap["shadow_reads"]["agreed"] == 1


def test_shadow_busy_pool_is_counted_as_skipped(wire, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "shadow")
    monkeypatch.setattr(db_scope.random, "random", lambda: 0.0)
    monkeypatch.setattr(dbconn._shadow_slots, "acquire", lambda blocking=True: False)
    _app(lambda: table("notes").select("id")).get("/probe", cookies=_cookie("u1"))
    assert scope_report.snapshot()["shadow_reads"] == {"skipped_busy": 1}


def test_shadow_transport_failure_is_not_a_divergence(wire, monkeypatch, inline_shadow, events):
    monkeypatch.setenv(FLAG_ENV, "shadow")
    real_get = wire.client.get.side_effect

    def _get(*args, **kwargs):
        if _scoped(kwargs.get("headers")):
            raise ConnectionError("blackholed")
        return real_get(*args, **kwargs)
    wire.client.get.side_effect = _get
    _app(lambda: table("notes").select("id")).get("/probe", cookies=_cookie("u1"))
    assert events == []
    assert scope_report.snapshot()["shadow_reads"] == {"transport_error": 1, "sampled": 1}


# ── Writes: never executed twice; record what is known without running them ─


def test_shadow_write_naming_another_user_is_a_would_be_denial(wire, monkeypatch, events, caplog):
    monkeypatch.setenv(FLAG_ENV, "shadow")

    def handler(note_id: str):
        table("notes").insert({"user_id": "someone_else", "body": SECRET_MARKER})
        table("notes").update({"body": SECRET_MARKER}, {"user_id": "eq.someone_else"})
        table("notes").delete({"id": f"eq.{note_id}", "user_id": "eq.someone_else"})
        table("notes").upsert([{"user_id": "u1"}, {"user_id": "someone_else"}])
        return {}

    with caplog.at_level(logging.WARNING, logger="sapling.db_scope"):
        r = _note_app(handler, method="post").post("/notes/n9", cookies=_cookie("u1"))
    assert r.status_code == 200
    assert len(wire.for_table("notes")) == 4  # each write ran exactly once
    assert wire.scoped() == []                # ... as service, never re-run scoped
    lines = _lines(caplog)
    assert [ln.split(" op=")[1].split(" ")[0] for ln in lines] == ["insert", "update", "delete", "upsert"]
    assert all("kind=write_other_user" in ln and "method=POST" in ln
               and "route=/notes/{note_id}" in ln for ln in lines)
    assert SECRET_MARKER not in caplog.text and "someone_else" not in caplog.text
    assert [p["kind"] for _, p, _, _ in events] == ["write_other_user"] * 4


def test_shadow_own_writes_and_rpc_are_inventoried_not_logged(wire, monkeypatch, events, caplog):
    monkeypatch.setenv(FLAG_ENV, "shadow")

    def handler():
        table("notes").insert({"user_id": "u1"})
        table("notes").update({"a": 1}, {"user_id": "eq.u1"})
        table("notes").insert({"user_id": "u1"})
        rpc("apply_mastery_delta", {"p_user_id": "u1"})
        return {}

    with caplog.at_level(logging.WARNING, logger="sapling.db_scope"):
        _app(handler, method="post").post("/probe", cookies=_cookie("u1"))
    assert _lines(caplog) == [] and events == []
    assert len(wire.calls) == 4 and wire.scoped() == []
    writes = {(w["target"], w["op"]): w["count"]
              for w in scope_report.snapshot()["unverified_writes"]}
    assert writes == {("notes", "insert"): 2, ("notes", "update"): 1,
                      ("rpc/apply_mastery_delta", "rpc"): 1}


def test_read_only_rpc_is_shadowed_and_reported(wire, monkeypatch, inline_shadow, events, caplog):
    """match_course_chunks (STABLE, read-only): RLS filters after the ANN scan,
    so shadow measures the recall loss plan §6.3 worries about."""
    monkeypatch.setenv(FLAG_ENV, "shadow")
    wire.rows = lambda verb, url, headers: (
        [{"id": "c1"}] if _scoped(headers) else [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}])

    def handler():
        return {"rows": rpc("match_course_chunks", {"match_count": 3})}

    with caplog.at_level(logging.WARNING, logger="sapling.db_scope"):
        r = _app(handler, method="post").post("/probe", cookies=_cookie("u1"))
    assert len(r.json()["rows"]) == 3
    service, scoped = wire.calls
    assert scoped[0] == "post" and scoped[2]["json"] == {"match_count": 3}
    (line,) = _lines(caplog)
    assert "target=rpc/match_course_chunks op=rpc" in line and "kind=fewer_rows" in line
    assert scope_report.snapshot()["unverified_writes"] == []


# ── Unscoped and enforce feed the same tally ────────────────────────────────


def test_unscoped_query_in_shadow_is_one_line_every_time(wire, monkeypatch, events, caplog):
    monkeypatch.setenv(FLAG_ENV, "shadow")

    def handler():
        table("notes").select("id")
        table("notes").select("id")
        return {}

    with caplog.at_level(logging.WARNING, logger="sapling.db_scope"):
        _app(handler).get("/probe")  # no session
    lines = _lines(caplog)
    assert len(lines) == 2 and all("kind=no_subject mode=shadow method=GET route=/probe "
                                   "target=notes" in ln for ln in lines)
    (row,) = scope_report.snapshot()["divergences"]
    assert row["event"] == "db.unscoped_query" and row["count"] == 2


def test_enforce_denial_is_counted_with_code_and_op(wire, monkeypatch, events, caplog):
    monkeypatch.setenv(FLAG_ENV, "enforce")
    wire.status = lambda verb, url, headers: 403 if _scoped(headers) else 200
    wire.rows = lambda verb, url, headers: {"code": "42501"} if _scoped(headers) else []

    def handler():
        table("notes").insert({"a": 1})
        return {}

    with caplog.at_level(logging.WARNING, logger="sapling.db_scope"):
        r = _app(handler, method="post").post("/probe", cookies=_cookie("u1"))
    assert r.status_code == 404
    (line,) = _lines(caplog)
    assert ("event=db.rls_denied kind=denied mode=enforce method=POST route=/probe "
            "target=notes op=insert status=403 code=42501") in line
    (_, payload, user_id, _), = events
    assert payload["code"] == "42501" and payload["op"] == "insert" and user_id == "u1"


# ── Flag off: none of this runs ─────────────────────────────────────────────


def test_flag_off_adds_no_report_work(wire, monkeypatch, events, caplog):
    """Under off every verb (reads, writes, both rpc kinds) must not reach the
    tally, the logger, the route-template resolver or the request-id lookup:
    the shadow gate returns on the memoized mode before any of it."""
    monkeypatch.setenv(FLAG_ENV, "off")
    monkeypatch.setattr(db_scope.random, "random", lambda: 0.0)

    def _boom(*_a, **_k):
        raise AssertionError("shadow report work with the flag off")
    for name in ("record", "note_write", "note_shadow"):
        monkeypatch.setattr(scope_report, name, _boom)
    monkeypatch.setattr(dbconn, "_submit_shadow", _boom)

    def handler(request: Request):
        # Installed inside the request: the middleware's own access log may
        # use these, the DB path must not.
        monkeypatch.setattr(request_context, "current_route_template", _boom)
        monkeypatch.setattr(request_context, "current_method", _boom)
        t = table("notes")
        t.select("id")
        t.select_with_count("id")
        t.insert({"user_id": "someone_else"})
        t.update({"a": 1}, {"user_id": "eq.someone_else"})
        t.upsert({"user_id": "someone_else"})
        t.delete({"user_id": "eq.someone_else"})
        rpc("apply_mastery_delta", {})
        rpc("match_course_chunks", {})
        return {"ok": True}

    with caplog.at_level(logging.DEBUG, logger="sapling.db_scope"):
        r = _app(handler, method="post").post("/probe", cookies=_cookie("u1"))
    assert r.status_code == 200, r.text
    assert len(wire.calls) == 8 and wire.scoped() == []
    assert events == []
    assert [r for r in caplog.records if r.name.startswith("sapling.db")] == []


def test_flag_off_snapshot_stays_empty(wire, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "off")
    _app(lambda: table("notes").select("id")).get("/probe", cookies=_cookie("u1"))
    snap = scope_report.snapshot()
    assert snap["divergences"] == [] and snap["unverified_writes"] == []
    assert snap["shadow_reads"] == {}


# ── Tally bounds ────────────────────────────────────────────────────────────


def test_tally_is_bounded(monkeypatch):
    monkeypatch.setattr(scope_report, "MAX_KEYS", 2)
    for i in range(4):
        scope_report.record(event="e", kind="k", mode="shadow", method="GET",
                            route=f"/r{i}", target="t", op="select")
    snap = scope_report.snapshot()
    assert snap["divergence_keys"] == 2 and snap["dropped_keys"] == 2


def test_log_fields_cannot_break_the_line():
    line = scope_report.format_line({"event": "e", "kind": "k", "route": "/a b\nc", "target": None})
    assert "\n" not in line and "route=/a_b_c" in line and "target=-" in line


# ── The admin report ────────────────────────────────────────────────────────


class _Events:
    def __init__(self, rows):
        self.rows = rows
        self.filters = None

    def select_with_count(self, columns="*", filters=None, order=None, limit=None, offset=None):
        self.filters = filters
        rows = self.rows[offset or 0:][: limit or None]
        return rows, len(self.rows)


def _ev(event_type, payload, user="u1", rid="r1", at="2026-11-08T10:00:00+00:00"):
    return {"event_type": event_type, "user_id": user, "request_id": rid,
            "payload": payload, "created_at": at}


def test_admin_db_scope_report_groups_events_and_includes_the_process_tally(monkeypatch):
    import main
    import routes.admin_analytics as analytics

    div = {"table": "notes", "route": "/api/notes/{note_id}", "kind": "fewer_rows",
           "method": "GET", "op": "select", "service_count": 2, "scoped_count": 1}
    store = _Events([
        _ev("db.rls_shadow_divergence", div, user="u1", rid="r1"),
        _ev("db.rls_shadow_divergence", div, user="u2", rid="r2"),
        _ev("db.rls_shadow_divergence", div, user="u2", rid="r3", at="2026-11-08T11:00:00+00:00"),
        # A pre-report row (no kind/method): still grouped, kind derived.
        _ev("db.rls_shadow_divergence", {"table": "notes", "route": "/x", "service_count": 1,
                                         "scoped_count": -1, "error": "403"}),
        _ev("db.unscoped_query", {"table": "courses", "route": "/api/x", "mode": "shadow"}, user=None),
    ])
    monkeypatch.setattr(analytics, "table", lambda name: store)
    scope_report.record(event="db.rls_shadow_divergence", kind="fewer_rows", mode="shadow",
                        method="GET", route="/api/notes/{note_id}", target="notes", op="select")

    r = TestClient(main.app).get("/api/admin/analytics/db-scope", params={"hours": 6, "limit": 10})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "private"
    body = r.json()
    assert body["window"]["hours"] == 6 and body["total"] == 5 and body["truncated"] is False
    top = body["top"][0]
    assert (top["event"], top["kind"], top["route"], top["target"], top["method"], top["op"]) == (
        "db.rls_shadow_divergence", "fewer_rows", "/api/notes/{note_id}", "notes", "GET", "select")
    assert top["count"] == 3 and top["users"] == 2
    assert top["last_seen"] == "2026-11-08T11:00:00+00:00"
    assert sorted(top["sample_request_ids"]) == ["r1", "r2", "r3"]
    legacy = next(t for t in body["top"] if t["route"] == "/x")
    assert legacy["kind"] == "error" and legacy["status"] == "403"
    assert body["process"]["divergences"][0]["count"] == 1
    # Only the three db_user_scope events are scanned.
    assert "db.rls_denied" in store.filters["event_type"]


def test_admin_db_scope_report_is_admin_only(monkeypatch):
    import main
    from fastapi import HTTPException

    def _deny(request):
        raise HTTPException(status_code=403, detail="Admin only")
    monkeypatch.setattr(auth_guard, "require_admin", _deny)
    import routes.admin_analytics as analytics
    monkeypatch.setattr(analytics, "require_admin", _deny)
    r = TestClient(main.app).get("/api/admin/analytics/db-scope")
    assert r.status_code == 403
