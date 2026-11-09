"""#116 (plan phase 2): the Gradescope sync on the Postgres job queue.

Hermetic; the browser/HTTP layer (`_establish_connection`,
`gradescope_service.list_assignments`) and `table()` are mocked, and
`gradescope_syncs` is an in-memory fake that applies the same filters
PostgREST would (eq / in / is.null, and the `counts->>owner` JSON paths).
Pins:
  * flag OFF: the sync route answers as before for every outcome, status and
    body (nothing staged, the login + scrape + writes run in the request);
  * flag ON: a `gradescope.sync` job is enqueued with ONLY the staged row's id
    (never credentials), the route waits on the row and answers through the
    same outcome -> response mapping; 202 pending past the wait, 504 only when
    the row cannot be read;
  * staging or enqueue failure, or no worker picking the job up, syncs inline
    — once: only the request holding the take-back token runs it, and every
    other watcher answers with the outcome it records;
  * the worker fences its writes on an owner token, re-checks the course link
    before writing, and records typed outcomes;
  * an active sync is abandoned only when its job is not alive;
  * GET /sync/{course}/status answers like the POST once the sync ends.
What the SQL does with the rows (one active sync per enrollment, the CHECKs,
the stage CAS, RLS bucket E) is pinned against real Postgres in
tests/integration/test_gradescope_syncs_db.py.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from routes import gradescope as gsr
from services import gradescope_jobs as gj
from services import gradescope_service as gs
from services import jobs, request_limits
from tests.split_patches import patch_gradescope

client = TestClient(app)
RID = "rid-00000001"


@pytest.fixture(autouse=True)
def _clear_rate_state():
    request_limits._rate_state.clear()
    yield
    request_limits._rate_state.clear()


def _iso(seconds_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


# ── an in-memory gradescope_syncs ───────────────────────────────────────────


class FakeTable:
    """Rows + the PostgREST filters the module sends. Thread-safe, so two
    requests can race on it."""

    def __init__(self, rows=(), *, unique_active=False):
        self.rows = {str(r["id"]): dict(r) for r in rows}
        self.lock = threading.Lock()
        self.unique_active = unique_active
        self.n = 0
        self.updates: list[tuple[dict, dict]] = []

    @staticmethod
    def _value(row, key):
        if "->>" in key:
            col, _, sub = key.partition("->>")
            obj = row.get(col)
            return obj.get(sub) if isinstance(obj, dict) else None
        return row.get(key)

    def _match(self, row, filters):
        for key, cond in (filters or {}).items():
            op, _, val = cond.partition(".")
            actual = self._value(row, key)
            if op == "eq":
                ok = actual is not None and str(actual) == val
            elif op == "in":
                ok = actual is not None and str(actual) in val.strip("()").split(",")
            elif op == "is":
                ok = actual is None
            else:
                raise AssertionError(f"unsupported filter {key}={cond}")
            if not ok:
                return False
        return True

    def insert(self, row):
        with self.lock:
            if self.unique_active and row.get("stage") in ("queued", "running") and any(
                r["user_id"] == row["user_id"] and r["enrollment_id"] == row["enrollment_id"]
                and r["stage"] in ("queued", "running") for r in self.rows.values()
            ):
                raise RuntimeError("23505 duplicate key gradescope_syncs_active_key")
            self.n += 1
            new = {"id": f"s{self.n}", "counts": None, "error_code": None, "job_id": None,
                   "created_at": _iso(), "updated_at": _iso(), **row}
            self.rows[new["id"]] = new
            return [dict(new)]

    def select(self, columns="*", filters=None, limit=None, order=None, **_kw):
        with self.lock:
            out = [dict(r) for r in self.rows.values() if self._match(r, filters)]
        if order and order.startswith("created_at.desc"):
            out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return out[:limit] if limit else out

    def update(self, data, filters, prefer_return_minimal=False):
        with self.lock:
            self.updates.append((dict(data), dict(filters)))
            hit = [r for r in self.rows.values() if self._match(r, filters)]
            for r in hit:
                r.update(data)
                r["updated_at"] = _iso()
            return [] if prefer_return_minimal else [dict(r) for r in hit]


_LINK = {"id": "link-1", "enrollment_id": "enr-1", "gradescope_course_id": "gs-course"}


def _gj_tables(syncs: FakeTable, *, job=None, links=None):
    """`gj.table` by name: the fake syncs, a jobs table answering `job`, and
    the course links the worker re-checks."""
    jobs_t = MagicMock(name="jobs")
    jobs_t.select.return_value = [job] if job else []
    links_t = FakeTable([_LINK] if links is None else links)
    tables = {"gradescope_syncs": syncs, "jobs": jobs_t, "gradescope_course_links": links_t}
    return lambda name: tables[name]


# ── route fixtures ──────────────────────────────────────────────────────────


def _route_tables(incoming_existing=None):
    tables = {name: MagicMock(name=name) for name in (
        "assignments", "gradebook_categories", "gradescope_course_links", "gradescope_credentials",
    )}
    existing = incoming_existing if incoming_existing is not None else [
        {"id": "saved", "gradescope_assignment_id": "existing"}]
    tables["assignments"].select.return_value = existing
    tables["assignments"].select_with_count.return_value = (existing, len(existing))
    cats = [{"id": "cat", "name": "Homework"}]
    tables["gradebook_categories"].select.return_value = cats
    tables["gradebook_categories"].select_with_count.return_value = (cats, 1)
    tables["gradescope_course_links"].select.return_value = [dict(_LINK)]
    return tables


_INCOMING = [
    {"id": "new", "name": "Homework 1", "points_earned": 9, "points_possible": 10},
    {"id": "existing", "name": "Exam"},
    {"id": "", "name": "unavailable"},
]
_INLINE_JSON = {"inserted": 1, "updated": 1, "skipped": 1, "failed": 0}


def _creds():
    return gsr.StoredCreds(auth_mode="cookies", gradescope_session="sess",
                           updated_at="v1", needs_reauth=False)


_REAL = object()  # `load_creds=_REAL`: run the real _load_creds


def _post(tables, *, connect=None, incoming=_INCOMING, extra=(), load_creds=None, http=client):
    """POST /sync with the DB and the Gradescope layer mocked. `connect` is
    the _establish_connection mock (a MagicMock by default)."""
    connect = connect or MagicMock(name="_establish_connection")
    if load_creds is _REAL:
        creds_patch = contextlib.nullcontext()
    elif load_creds is None:
        creds_patch = patch_gradescope("_load_creds", return_value=_creds())
    else:
        creds_patch = load_creds
    with (
        patch_gradescope("table", side_effect=lambda name: tables[name]),
        patch_gradescope("_all_enrollments_for", return_value=["enr-1"]),
        creds_patch,
        patch_gradescope("_establish_connection", connect),
        patch.object(gs, "list_assignments", return_value=incoming),
    ):
        for p in extra:
            p.start()
        try:
            r = http.post("/api/gradescope/sync/c1",
                          params={"user_id": "u1", "semester": "Fall 2025"},
                          headers={"X-Request-ID": RID})
        finally:
            for p in reversed(extra):
                p.stop()
    return r, connect


# ── should_queue ────────────────────────────────────────────────────────────


def test_should_queue_follows_the_flag_for_the_student():
    with patch.object(gj, "flag_on", return_value=False) as flag:
        assert gj.should_queue("u1") is False
    flag.assert_called_once_with("jobs_queue", "u1")
    with patch.object(gj, "flag_on", return_value=True):
        assert gj.should_queue("u1") is True


def test_should_queue_reads_a_flag_store_error_as_off():
    with patch.object(gj, "flag_on", side_effect=RuntimeError("store down")):
        assert gj.should_queue("u1") is False


# ── flag OFF: today's behaviour, status and body ────────────────────────────


def test_flag_off_syncs_inline_and_stages_nothing():
    tables = _route_tables()
    with (
        patch.object(gj, "flag_on", return_value=False) as flag,
        patch.object(gj, "stage_sync") as stage,
        patch.object(jobs, "enqueue") as enq,
    ):
        r, connect = _post(tables)
    assert r.status_code == 200
    assert r.json() == _INLINE_JSON
    flag.assert_called_once_with("jobs_queue", "u1")
    stage.assert_not_called()
    enq.assert_not_called()
    connect.assert_called_once()  # the login ran in the request
    # The outcome is recorded where it always was, and the link is stamped.
    state = tables["gradescope_credentials"].update.call_args.args[0]
    assert state["last_sync_error"] is None and state["needs_reauth"] is False
    assert "last_synced_at" in state and "last_attempt_at" in state
    tables["gradescope_course_links"].update.assert_called_once()
    assert tables["gradescope_course_links"].update.call_args.kwargs["filters"] == {"id": "eq.link-1"}


def _typed(status_code, code, message):
    return status_code, {"detail": message, "error": {"code": code, "message": message,
                                                       "request_id": RID},
                         "request_id": RID}


def _plain(status_code, detail):
    return status_code, {"detail": detail, "request_id": RID}


@pytest.mark.parametrize("case,expected", [
    ("not_connected", _typed(404, "gradescope_not_connected", "No Gradescope credentials saved")),
    ("auth", _typed(409, "gradescope_reauth_required",
                    "Your Gradescope session has expired or was signed out.")),
    ("auth_blank", _typed(409, "gradescope_reauth_required",
                          "Gradescope rejected the saved credentials. Reconnect Gradescope.")),
    ("fetch", _plain(502, "Failed to list assignments for course gs-course: boom")),
    ("write", _plain(502, "No assignments could be saved. Please retry; if this continues, "
                          "contact support.")),
    ("creds_unreadable", _plain(500, "Stored credentials could not be read.")),
    ("creds_incomplete", _plain(500, "Password-mode creds missing email/password")),
    ("crash", _plain(500, "Internal server error.")),
])
def test_flag_off_answers_are_unchanged_for_every_outcome(case, expected):
    """The inline route answers through `response_for_outcome` now; every
    status and body is pinned to what it answered before (#116 review)."""
    tables = _route_tables()
    connect = MagicMock(name="_establish_connection")
    load_creds = None
    incoming = _INCOMING
    extra = [patch.object(gj, "flag_on", return_value=False)]
    if case == "not_connected":
        load_creds = patch_gradescope("_load_creds", return_value=None)
    elif case == "auth":
        connect.side_effect = gs.GradescopeAuthError(
            "Your Gradescope session has expired or was signed out.")
    elif case == "auth_blank":
        connect.side_effect = gs.GradescopeAuthError("")
    elif case == "fetch":
        extra.append(patch.object(gs, "list_assignments", side_effect=gs.GradescopeFetchError(
            "Failed to list assignments for course gs-course: boom")))
    elif case == "write":
        tables["assignments"].insert.side_effect = RuntimeError("write failed")
        incoming = [{"id": "new"}]
    elif case == "creds_unreadable":
        tables["gradescope_credentials"].select.return_value = [{
            "auth_mode": "password", "email_encrypted": "not-ciphertext",
            "password_encrypted": "x", "updated_at": "v1", "needs_reauth": False}]
        load_creds = _REAL
    elif case == "creds_incomplete":
        load_creds = patch_gradescope("_load_creds", return_value=gsr.StoredCreds(
            auth_mode="password", email=None, password=None))
        # The real _establish_connection (it refused these before the sync
        # body classified them itself); no login is ever attempted.
        connect = MagicMock(wraps=gsr._establish_connection)
        extra.append(patch.object(gs, "login", side_effect=AssertionError("no login")))
    elif case == "crash":
        tables["gradebook_categories"].select.side_effect = RuntimeError("PostgREST down")
        tables["gradebook_categories"].select_with_count.side_effect = RuntimeError("down")
    http = TestClient(app, raise_server_exceptions=False) if case == "crash" else client
    r, _ = _post(tables, connect=connect, incoming=incoming, extra=extra,
                 load_creds=load_creds, http=http)
    status, body = expected
    assert r.status_code == status
    assert r.json() == body
    if case in ("creds_unreadable", "creds_incomplete", "not_connected"):
        tables["gradescope_credentials"].update.assert_not_called()


def test_flag_off_rejected_credentials_are_marked_stale_on_their_version():
    tables = _route_tables()
    connect = MagicMock(side_effect=gs.GradescopeAuthError("Session expired"))
    with patch.object(gj, "flag_on", return_value=False):
        r, _ = _post(tables, connect=connect)
    assert r.status_code == 409
    state = tables["gradescope_credentials"].update.call_args
    assert state.args[0]["needs_reauth"] is True
    assert state.args[0]["last_sync_error"] == "auth_failed"
    assert state.kwargs["filters"] == {"user_id": "eq.u1", "updated_at": "eq.v1"}


def test_the_link_changed_answer_is_the_routes_unlinked_answer():
    tables = _route_tables()
    tables["gradescope_course_links"].select.return_value = []
    r, _ = _post(tables, extra=[patch.object(gj, "flag_on", return_value=False)])
    assert r.status_code == 400
    assert r.json()["detail"] == gj.NO_LINK_MESSAGE
    with pytest.raises(HTTPException) as exc:
        gsr.response_for_outcome(gj.SyncOutcome.failed(gj.ERR_LINK_CHANGED))
    assert (exc.value.status_code, exc.value.detail) == (400, gj.NO_LINK_MESSAGE)


# ── flag ON: the request enqueues and relays the outcome ────────────────────


def _queued(row_sequence, *, staged=gj.Staged(id="s1", fresh=True), enqueue=None):
    """Patches for a flag-on request whose status polls return `row_sequence`
    (the last one repeats)."""
    seq = list(row_sequence)

    def _read(_sync_id):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return [
        patch.object(gj, "flag_on", return_value=True),
        patch.object(gj, "stage_sync", MagicMock(return_value=staged)),
        patch.object(jobs, "enqueue", enqueue or MagicMock(return_value={"id": "j1", "inserted": True})),
        patch.object(gj, "table"),  # enqueue_sync's job_id write
        patch.object(gj, "read_status", side_effect=_read),
        patch.object(gj, "POLL_INTERVAL_SECONDS", 0.0),
    ]


def test_flag_on_enqueues_ids_only_and_returns_the_workers_counts():
    tables = _route_tables()
    enq = MagicMock(return_value={"id": "j1", "inserted": True})
    done = {"id": "s1", "stage": "done", "error_code": None, "job_id": "j1",
            "counts": {"inserted": 3, "updated": 2, "skipped": 1, "failed": 0}}
    patches = _queued([{"id": "s1", "stage": "running", "job_id": "j1"}, done], enqueue=enq)
    stage = patches[1]
    r, connect = _post(tables, extra=patches)
    assert r.status_code == 200
    assert r.json() == {"inserted": 3, "updated": 2, "skipped": 1, "failed": 0}
    connect.assert_not_called()  # no Gradescope login in the request
    tables["assignments"].insert.assert_not_called()
    tables["gradescope_credentials"].update.assert_not_called()
    enq.assert_called_once_with("gradescope.sync", {"sync_id": "s1"},
                                dedupe_key="gradescope.sync:s1")
    payload = enq.call_args.args[1]
    assert set(payload) == {"sync_id"}  # never a password, cookie or email
    assert stage.new.call_args.kwargs == {
        "user_id": "u1", "enrollment_id": "enr-1", "link_id": "link-1",
        "gradescope_course_id": "gs-course"}


def test_flag_on_attaching_to_a_sync_in_flight_enqueues_nothing():
    tables = _route_tables()
    enq = MagicMock()
    done = {"id": "s0", "stage": "done", "counts": {"inserted": 1, "updated": 0,
                                                    "skipped": 0, "failed": 0}}
    r, _ = _post(tables, extra=_queued([done], staged=gj.Staged(id="s0", fresh=False),
                                       enqueue=enq))
    assert r.status_code == 200 and r.json()["inserted"] == 1
    enq.assert_not_called()


@pytest.mark.parametrize("code,status,error_code,detail", [
    ("not_connected", 404, "gradescope_not_connected", "No Gradescope credentials saved"),
    ("auth_failed", 409, "gradescope_reauth_required",
     "Gradescope rejected the saved credentials. Reconnect Gradescope."),
    ("fetch_failed", 502, None, "Couldn't reach Gradescope. Please retry shortly."),
    ("write_failed", 502, None,
     "No assignments could be saved. Please retry; if this continues, contact support."),
    ("creds_unreadable", 500, None, "Stored credentials could not be read."),
    ("creds_incomplete", 500, None, "Password-mode creds missing email/password"),
    ("link_changed", 400, None, "No Gradescope course is linked to this Sapling course"),
    ("internal_error", 500, None, "Internal server error."),
    ("worker_failed", 502, None, "Gradescope sync failed. Please retry."),
    ("abandoned", 502, None, "Gradescope sync failed. Please retry."),
])
def test_flag_on_failures_answer_like_the_inline_route(code, status, error_code, detail):
    tables = _route_tables()
    failed = {"id": "s1", "stage": "failed", "error_code": code}
    r, connect = _post(tables, extra=_queued([failed]))
    assert r.status_code == status
    body = r.json()
    assert body["detail"] == detail
    if error_code:
        assert body["error"]["code"] == error_code
    connect.assert_not_called()


def test_flag_on_a_sync_past_the_wait_is_a_202_that_keeps_running():
    tables = _route_tables()
    running = {"id": "s1", "stage": "running", "job_id": None}
    patches = _queued([running]) + [patch.object(gj, "SYNC_MAX_WAIT_SECONDS", 0.0)]
    r, _ = _post(tables, extra=patches)
    assert r.status_code == 202
    assert r.json() == {"pending": True, "sync_id": "s1", "stage": "running",
                        "detail": gj.TIMEOUT_MESSAGE}


def test_flag_on_an_unreadable_row_ends_in_the_504_never_a_500():
    tables = _route_tables()
    patches = _queued([{}])[:4] + [
        patch.object(gj, "read_status", side_effect=RuntimeError("PostgREST down")),
        patch.object(gj, "POLL_INTERVAL_SECONDS", 0.0),
        patch.object(gj, "_MAX_DB_ERRORS", 3),
    ]
    r, connect = _post(tables, extra=patches)
    assert r.status_code == 504
    assert r.json()["detail"] == gj.TIMEOUT_MESSAGE
    connect.assert_not_called()


def test_flag_on_staging_failure_syncs_inline():
    tables = _route_tables()
    with (
        patch.object(gj, "flag_on", return_value=True),
        patch.object(gj, "stage_sync", side_effect=RuntimeError("42P01 no such table")),
        patch.object(jobs, "enqueue") as enq,
    ):
        r, connect = _post(tables)
    assert r.status_code == 200 and r.json() == _INLINE_JSON
    connect.assert_called_once()
    enq.assert_not_called()


def _on_fake(syncs, *, job=None, enqueue=None, grace=0.0, poll=0.0, max_wait=5.0):
    return [
        patch.object(gj, "flag_on", return_value=True),
        patch.object(gj, "table", side_effect=_gj_tables(syncs, job=job)),
        patch.object(jobs, "enqueue", enqueue or MagicMock(return_value={"id": "j1"})),
        patch.object(gj, "PICKUP_GRACE_SECONDS", grace),
        patch.object(gj, "POLL_INTERVAL_SECONDS", poll),
        patch.object(gj, "SYNC_MAX_WAIT_SECONDS", max_wait),
    ]


def test_flag_on_enqueue_failure_takes_the_sync_back_runs_it_and_records_it():
    tables = _route_tables()
    syncs = FakeTable(unique_active=True)
    patches = _on_fake(syncs, enqueue=MagicMock(side_effect=RuntimeError("PostgREST down")))
    r, connect = _post(tables, extra=patches)
    assert r.status_code == 200 and r.json() == _INLINE_JSON
    connect.assert_called_once()
    row = syncs.rows["s1"]
    assert row["stage"] == "done" and row["counts"] == _INLINE_JSON
    # The take-back carried this request's token, and the outcome was a CAS on it.
    take, finish = syncs.updates[0], syncs.updates[-1]
    token = take[0]["counts"]["inline_owner"]
    assert take == ({"stage": "inline", "counts": {"inline_owner": token}},
                    {"id": "eq.s1", "stage": "eq.queued"})
    assert finish[1] == {"id": "eq.s1", "stage": "eq.inline", "counts->>inline_owner": f"eq.{token}"}


def test_flag_on_no_worker_within_the_grace_syncs_inline_and_records_it():
    tables = _route_tables()
    syncs = FakeTable(unique_active=True)
    r, connect = _post(tables, extra=_on_fake(syncs, job={"status": "queued"}))
    assert r.status_code == 200 and r.json() == _INLINE_JSON
    connect.assert_called_once()
    assert syncs.rows["s1"]["stage"] == "done"


def test_flag_on_an_inline_failure_is_recorded_with_its_code_and_answered_by_code():
    tables = _route_tables()
    syncs = FakeTable(unique_active=True)
    connect = MagicMock(side_effect=gs.GradescopeAuthError("Session expired"))
    r, _ = _post(tables, connect=connect, extra=_on_fake(syncs, job={"status": "queued"}))
    # Every watcher of a staged sync answers from its code (the row holds no
    # Gradescope text), so the request that ran it answers the same way.
    assert r.status_code == 409
    assert r.json()["detail"] == "Gradescope rejected the saved credentials. Reconnect Gradescope."
    assert syncs.rows["s1"]["stage"] == "failed"
    assert syncs.rows["s1"]["error_code"] == "auth_failed"


def test_flag_on_an_inline_crash_is_recorded_and_still_a_500():
    tables = _route_tables()
    tables["gradebook_categories"].select.side_effect = RuntimeError("PostgREST down")
    tables["gradebook_categories"].select_with_count.side_effect = RuntimeError("down")
    syncs = FakeTable(unique_active=True)
    r, _ = _post(tables, extra=_on_fake(syncs, job={"status": "queued"}),
                 http=TestClient(app, raise_server_exceptions=False))
    assert r.status_code == 500
    assert r.json() == {"detail": "Internal server error.", "request_id": RID}
    assert syncs.rows["s1"]["error_code"] == "internal_error"


# ── two requests, one sync, no worker ───────────────────────────────────────


def test_two_requests_on_one_sync_run_it_once_and_answer_alike():
    """A second click attaches to the first click's staged sync. With no
    worker, exactly one of them wins the take-back and runs the sync (one
    login, one last_sync_* write); the other waits for the outcome it
    records and answers with it."""
    tables = _route_tables()
    syncs = FakeTable(unique_active=True)
    logins = []

    def _slow_login(_creds):
        logins.append(1)
        time.sleep(0.3)  # long enough for the other request to see `inline`
        return MagicMock()

    results: dict[str, object] = {}
    kwargs = dict(user_id="u1", enrollment_id="enr-1", link_id="link-1",
                  gradescope_course_id="gs-course")

    def _request(name):
        results[name] = gsr.sync_via_queue(**kwargs)

    with (
        patch.object(gj, "table", side_effect=_gj_tables(syncs, job={"status": "queued"})),
        patch.object(jobs, "enqueue", return_value={"id": "j1"}),
        patch.object(gj, "PICKUP_GRACE_SECONDS", 0.1),
        patch.object(gj, "POLL_INTERVAL_SECONDS", 0.02),
        patch.object(gj, "SYNC_MAX_WAIT_SECONDS", 5.0),
        patch_gradescope("table", side_effect=lambda name: tables[name]),
        patch_gradescope("_load_creds", return_value=_creds()),
        patch_gradescope("_establish_connection", side_effect=_slow_login),
        patch.object(gs, "list_assignments", return_value=_INCOMING),
    ):
        threads = [threading.Thread(target=_request, args=(n,)) for n in ("a", "b")]
        for t in threads:
            t.start()
            time.sleep(0.02)
        for t in threads:
            t.join(10)
    assert len(logins) == 1
    assert results["a"] == results["b"] == _INLINE_JSON
    assert len(syncs.rows) == 1  # the second request attached
    # Only the run's owner wrote the sync outcome onto gradescope_credentials.
    assert tables["gradescope_credentials"].update.call_count == 1


def test_the_loser_of_the_take_back_never_runs_the_sync():
    """A watcher that sees another request's `inline` row waits for its
    outcome: no login, no last_sync_error, the recorded answer."""
    row = {"id": "s1", "stage": "inline", "counts": {"inline_owner": "someone-else"}}
    done = {"id": "s1", "stage": "failed", "error_code": "fetch_failed"}
    tables = _route_tables()
    patches = _queued([row, row, done], staged=gj.Staged(id="s1", fresh=False)) + [
        patch.object(gj, "PICKUP_GRACE_SECONDS", 0.0)]
    r, connect = _post(tables, extra=patches)
    assert r.status_code == 502
    assert r.json()["detail"] == "Couldn't reach Gradescope. Please retry shortly."
    connect.assert_not_called()
    tables["gradescope_credentials"].update.assert_not_called()


# ── wait_for_sync ───────────────────────────────────────────────────────────


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _wait(rows, **kw):
    seq = list(rows)

    def _read(_id):
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(item, Exception):
            raise item
        return item

    clock = _Clock()
    with patch.object(gj, "read_status", side_effect=_read):
        return gj.wait_for_sync("s1", token="tok", sleep=clock.sleep, clock=clock, poll=1.0, **kw)


def test_wait_returns_the_terminal_row():
    w = _wait([{"stage": "queued"}, {"stage": "running"}, {"stage": "done", "counts": {}}])
    assert w.kind == "done"


def test_wait_takes_back_a_sync_no_worker_claimed_with_its_token():
    with patch.object(gj, "take_back", return_value=True) as back:
        w = _wait([{"stage": "queued"}], grace=5)
    assert w.kind == "inline"
    back.assert_called_once_with("s1", "tok")


def test_wait_recognises_its_own_take_back_after_a_lost_answer():
    w = _wait([{"stage": "inline", "counts": {"inline_owner": "tok"}}])
    assert w.kind == "inline"


def test_wait_adopts_another_requests_inline_outcome():
    other = {"stage": "inline", "counts": {"inline_owner": "other"}}
    w = _wait([other] * 4 + [{"stage": "done", "counts": {"inserted": 2}}])
    assert w.kind == "done" and w.row["counts"] == {"inserted": 2}


def test_wait_keeps_waiting_when_the_worker_won_the_take_back_race():
    with patch.object(gj, "take_back", return_value=False):
        w = _wait([{"stage": "queued"}] * 7 + [{"stage": "running"}, {"stage": "done"}], grace=5)
    assert w.kind == "done"


def test_wait_fails_a_running_sync_whose_job_died():
    running = {"stage": "running", "job_id": "j1", "counts": {"owner": "w#1"}}
    with (
        patch.object(gj, "job_status", return_value="dead") as status,
        patch.object(gj, "fail_if_running", return_value=True) as fail,
    ):
        w = _wait([running] * 11 + [{"stage": "failed", "error_code": "worker_failed"}])
    status.assert_called_with("s1", "j1")
    fail.assert_called_once_with("s1", "w#1", "worker_failed")
    assert w.kind == "failed" and w.row["error_code"] == "worker_failed"


def test_wait_reports_a_vanished_row_as_a_failure():
    w = _wait([None])
    assert w.kind == "failed" and w.row["error_code"] == "worker_failed"


def test_wait_ends_pending_past_the_max_wait():
    w = _wait([{"stage": "running"}], max_wait=30)
    assert w.kind == "pending"


def test_wait_retries_a_transient_read_error_on_the_next_poll():
    blip = RuntimeError("PostgREST blip")
    w = _wait([blip, blip, {"stage": "running"}, blip, {"stage": "done"}])
    assert w.kind == "done"


@pytest.mark.parametrize("target", ["take_back", "job_status", "fail_if_running"])
def test_wait_retries_a_transient_error_in_any_step(target):
    side = {"take_back": [RuntimeError("blip"), True]}.get(target)
    rows = {
        "take_back": [{"stage": "queued"}],
        "job_status": [{"stage": "running", "job_id": "j1"}] * 25 + [{"stage": "done"}],
        "fail_if_running": [{"stage": "running", "job_id": "j1"}] * 25 + [{"stage": "done"}],
    }[target]
    patches = [patch.object(gj, target, side_effect=side or RuntimeError("blip"))]
    if target == "fail_if_running":
        patches.append(patch.object(gj, "job_status", return_value="dead"))
    for p in patches:
        p.start()
    try:
        w = _wait(rows, grace=0)
    finally:
        for p in reversed(patches):
            p.stop()
    assert w.kind == ("inline" if target == "take_back" else "done")


def test_wait_gives_up_with_timeout_after_consecutive_errors():
    with patch.object(gj, "_MAX_DB_ERRORS", 4):
        w = _wait([RuntimeError("down")], max_wait=1000)
    assert w.kind == "timeout"


def test_a_successful_poll_resets_the_error_budget():
    blip = RuntimeError("blip")
    rows = [blip, blip, {"stage": "running"}] * 4 + [{"stage": "done"}]
    with patch.object(gj, "_MAX_DB_ERRORS", 3):
        w = _wait(rows, max_wait=1000)
    assert w.kind == "done"


# ── staging: attach, or replace an abandoned sync ───────────────────────────

_STAGE_KW = dict(user_id="u1", enrollment_id="enr-1", link_id="link-1",
                 gradescope_course_id="gs-course")


def test_stage_sync_inserts_a_queued_row_with_ids_only():
    syncs = FakeTable(unique_active=True)
    with patch.object(gj, "table", side_effect=_gj_tables(syncs)):
        assert gj.stage_sync(**_STAGE_KW) == gj.Staged(id="s1", fresh=True)
    row = syncs.rows["s1"]
    assert {k: row[k] for k in (*_STAGE_KW, "stage")} == {**_STAGE_KW, "stage": "queued"}


def _active(stage, *, updated_ago, job_id="j0", created_ago=10_000):
    return {"id": "s0", "user_id": "u1", "enrollment_id": "enr-1", "stage": stage,
            "job_id": job_id, "updated_at": _iso(updated_ago), "created_at": _iso(created_ago)}


@pytest.mark.parametrize("stage,updated_ago,job,abandoned", [
    # A running sync whose worker still holds the lease: never failed, however
    # old the row (the old rule judged by created_at alone).
    ("running", 5_000, {"status": "running", "locked_at": _iso(10)}, False),
    ("running", 5_000, {"status": "failed", "locked_at": None}, False),  # retry pending
    ("running", 5, {"status": "dead"}, True),
    ("running", 5, {"status": "succeeded"}, True),  # finished without recording
    ("running", 5, None, True),  # no job at all
    ("running", 5, {"status": "running", "locked_at": _iso(10_000)}, True),  # lease ran out
    ("queued", 5, None, False),  # just staged, still being enqueued
    ("queued", 5_000, None, True),  # the stager died before enqueueing
    ("queued", 5_000, {"status": "queued"}, False),  # waiting: the watch takes it back
    ("queued", 5_000, {"status": "running", "locked_at": _iso(1)}, False),  # being claimed
])
def test_stage_sync_judges_abandonment_by_the_jobs_liveness(stage, updated_ago, job, abandoned):
    syncs = FakeTable([_active(stage, updated_ago=updated_ago)], unique_active=True)
    with patch.object(gj, "table", side_effect=_gj_tables(syncs, job=job)):
        staged = gj.stage_sync(**_STAGE_KW)
    if abandoned:
        assert staged == gj.Staged(id="s1", fresh=True)
        assert syncs.rows["s0"]["stage"] == "failed"
        assert syncs.rows["s0"]["error_code"] == "abandoned"
    else:
        assert staged == gj.Staged(id="s0", fresh=False)
        assert syncs.rows["s0"]["stage"] == stage
        assert syncs.updates == []


def test_stage_sync_looks_the_job_up_by_dedupe_key_when_no_job_id_was_recorded():
    syncs = FakeTable([_active("running", updated_ago=5, job_id=None)], unique_active=True)
    jobs_t = MagicMock()
    jobs_t.select.return_value = [{"status": "running", "locked_at": _iso(1)}]
    tables = {"gradescope_syncs": syncs, "jobs": jobs_t}
    with patch.object(gj, "table", side_effect=lambda n: tables[n]):
        assert gj.stage_sync(**_STAGE_KW) == gj.Staged(id="s0", fresh=False)
    assert jobs_t.select.call_args.kwargs["filters"] == {"dedupe_key": "eq.gradescope.sync:s0"}


def test_stage_sync_attaches_when_the_liveness_lookup_fails():
    syncs = FakeTable([_active("running", updated_ago=5_000)], unique_active=True)
    jobs_t = MagicMock()
    jobs_t.select.side_effect = RuntimeError("PostgREST down")
    tables = {"gradescope_syncs": syncs, "jobs": jobs_t}
    with patch.object(gj, "table", side_effect=lambda n: tables[n]):
        assert gj.stage_sync(**_STAGE_KW) == gj.Staged(id="s0", fresh=False)
    assert syncs.rows["s0"]["stage"] == "running"


def test_stage_sync_fails_an_abandoned_row_only_as_it_was_judged():
    """The abandon write is a CAS on the stage AND updated_at it was judged at."""
    syncs = FakeTable([_active("running", updated_ago=5)], unique_active=True)
    with patch.object(gj, "table", side_effect=_gj_tables(syncs, job={"status": "dead"})):
        gj.stage_sync(**_STAGE_KW)
    data, filters = syncs.updates[0]
    assert data == {"stage": "failed", "error_code": "abandoned", "counts": None}
    assert set(filters) == {"id", "stage", "updated_at"}
    assert filters["stage"] == "eq.running"


def test_stage_sync_reraises_an_insert_error_that_is_not_a_conflict():
    t = MagicMock()
    t.return_value.insert.side_effect = RuntimeError("PostgREST down")
    t.return_value.select.return_value = []
    with patch.object(gj, "table", t), pytest.raises(RuntimeError):
        gj.stage_sync(**_STAGE_KW)


def test_take_back_is_a_compare_and_swap_on_queued_carrying_the_token():
    syncs = FakeTable([{"id": "s1", "stage": "running"}])
    with patch.object(gj, "table", side_effect=_gj_tables(syncs)):
        assert gj.take_back("s1", "tok") is False
        syncs.rows["s1"]["stage"] = "queued"
        assert gj.take_back("s1", "tok") is True
        assert gj.take_back("s1", "other") is False  # already taken
    assert syncs.rows["s1"]["counts"] == {"inline_owner": "tok"}


def test_finish_inline_only_records_on_the_holders_row():
    syncs = FakeTable([{"id": "s1", "stage": "inline", "counts": {"inline_owner": "tok"}}])
    with patch.object(gj, "table", side_effect=_gj_tables(syncs)):
        assert gj.finish_inline("s1", "other", gj.SyncOutcome.failed("fetch_failed")) is False
        assert gj.finish_inline("s1", "tok", gj.SyncOutcome.done(
            inserted=1, updated=0, skipped=0, failed=0)) is True
    assert syncs.rows["s1"]["stage"] == "done"
    assert syncs.rows["s1"]["counts"] == {"inserted": 1, "updated": 0, "skipped": 0, "failed": 0}


def test_finish_inline_never_raises():
    t = MagicMock()
    t.return_value.update.side_effect = RuntimeError("down")
    with patch.object(gj, "table", t):
        assert gj.finish_inline("s1", "tok", gj.SyncOutcome.failed("x")) is False


# ── worker side ─────────────────────────────────────────────────────────────


def test_the_worker_loads_the_gradescope_sync_handler():
    from worker.__main__ import HANDLER_MODULES, load_handlers

    assert "services.gradescope_jobs" in HANDLER_MODULES
    assert "gradescope.sync" in load_handlers()
    assert jobs.get_handler("gradescope.sync") is gj._run_gradescope_sync_job


@pytest.mark.parametrize("payload", [{}, {"sync_id": ""}, {"sync_id": 7}, None])
def test_handler_refuses_a_payload_without_a_sync_id(payload):
    with pytest.raises(jobs.PermanentJobError):
        gj._run_gradescope_sync_job(payload)


_ROW = {"id": "s1", "user_id": "u1", "enrollment_id": "enr-1", "link_id": "link-1",
        "gradescope_course_id": "gs-course"}
_DONE = gj.SyncOutcome.done(inserted=1, updated=1, skipped=1, failed=0)


def _job(locked_by="w1", attempt=1):
    return jobs.Job(id="j1", type="gradescope.sync", payload={}, attempt=attempt,
                    max_attempts=5, locked_by=locked_by)


def _handle(stage, *, run=None, row_exists=True, counts=None, links=None, job=None):
    syncs = FakeTable([{**_ROW, "stage": stage, "counts": counts}] if row_exists else [])
    run = run or MagicMock(return_value=_DONE)
    current = job or _job()
    with (
        patch.object(gj, "table", side_effect=_gj_tables(syncs, links=links)),
        patch_gradescope("_run_linked_sync", run),
        patch.object(jobs, "current_job", lambda: current, create=True),
    ):
        gj._run_gradescope_sync_job({"sync_id": "s1"})
    return run, syncs


def test_handler_claims_with_its_owner_token_runs_the_sync_and_stores_the_counts():
    run, syncs = _handle("queued")
    assert run.call_args.args == ("u1", "gs-course", "enr-1", "link-1")
    assert callable(run.call_args.kwargs["still_linked"])
    claim, finish = syncs.updates
    assert claim == ({"stage": "running", "counts": {"owner": "w1#1"}},
                     {"id": "eq.s1", "stage": "eq.queued"})
    assert finish == ({"stage": "done", "error_code": None, "counts": _INLINE_JSON},
                      {"id": "eq.s1", "stage": "eq.running", "counts->>owner": "eq.w1#1"})
    assert syncs.rows["s1"]["counts"] == _INLINE_JSON


def test_handler_without_a_current_job_still_fences_on_a_unique_token():
    syncs = FakeTable([{**_ROW, "stage": "queued"}])
    with (
        patch.object(gj, "table", side_effect=_gj_tables(syncs)),
        patch_gradescope("_run_linked_sync", MagicMock(return_value=_DONE)),
        patch.object(jobs, "current_job", lambda: None, create=True),
    ):
        gj._run_gradescope_sync_job({"sync_id": "s1"})
    owner = syncs.updates[0][0]["counts"]["owner"]
    assert owner.startswith("direct#")
    assert syncs.updates[1][1]["counts->>owner"] == f"eq.{owner}"


def test_handler_does_nothing_when_the_request_took_the_sync_back_first():
    syncs = FakeTable([{**_ROW, "stage": "queued"}])
    run = MagicMock()

    def _select(*a, **kw):  # the request's take-back lands between read and swap
        out = FakeTable.select(syncs, *a, **kw)
        syncs.rows["s1"]["stage"] = "inline"
        return out

    with (
        patch.object(gj, "table", side_effect=_gj_tables(syncs)),
        patch.object(syncs, "select", side_effect=_select),
        patch_gradescope("_run_linked_sync", run),
    ):
        gj._run_gradescope_sync_job({"sync_id": "s1"})
    run.assert_not_called()
    assert syncs.rows["s1"]["stage"] == "inline"


@pytest.mark.parametrize("stage", ["done", "failed", "inline"])
def test_handler_is_a_no_op_on_a_finished_sync(stage):
    run, syncs = _handle(stage)
    run.assert_not_called()
    assert syncs.updates == []


def test_handler_is_a_no_op_when_the_row_is_gone():
    run, syncs = _handle("queued", row_exists=False)
    run.assert_not_called()
    assert syncs.updates == []


def test_a_redelivered_job_takes_the_running_sync_over_from_the_previous_owner():
    run, syncs = _handle("running", counts={"owner": "w0#1"}, job=_job("w1", 2))
    run.assert_called_once()
    takeover = syncs.updates[0]
    assert takeover == ({"stage": "running", "counts": {"owner": "w1#2"}},
                        {"id": "eq.s1", "stage": "eq.running", "counts->>owner": "eq.w0#1"})
    assert syncs.rows["s1"]["stage"] == "done"


def test_a_stale_attempts_late_outcome_is_refused():
    """The attempt is superseded mid-run (a re-delivery took the row over):
    its terminal write finds another owner and records nothing."""
    syncs = FakeTable([{**_ROW, "stage": "queued"}])

    def _superseded_run(*_a, **_kw):
        syncs.rows["s1"]["counts"] = {"owner": "w9#2"}
        return gj.SyncOutcome.failed("fetch_failed")

    with (
        patch.object(gj, "table", side_effect=_gj_tables(syncs)),
        patch_gradescope("_run_linked_sync", side_effect=_superseded_run),
    ):
        gj._run_gradescope_sync_job({"sync_id": "s1"})
    assert syncs.rows["s1"]["stage"] == "running"
    assert syncs.rows["s1"]["counts"] == {"owner": "w9#2"}


@pytest.mark.parametrize("outcome,code", [
    (gj.SyncOutcome.failed("not_connected"), "not_connected"),
    (gj.SyncOutcome.failed("auth_failed", "Session expired"), "auth_failed"),
    (gj.SyncOutcome.failed("write_failed"), "write_failed"),
    (gj.SyncOutcome.failed("fetch_failed", "boom"), "fetch_failed"),
    (gj.SyncOutcome.failed("creds_unreadable"), "creds_unreadable"),
    (RuntimeError("PostgREST blip"), "internal_error"),
])
def test_handler_records_each_typed_outcome_as_its_code(outcome, code):
    run = MagicMock(side_effect=outcome) if isinstance(outcome, Exception) else MagicMock(
        return_value=outcome)
    _, syncs = _handle("queued", run=run)
    assert syncs.rows["s1"]["stage"] == "failed"
    assert syncs.rows["s1"]["error_code"] == code
    assert syncs.rows["s1"]["counts"] is None  # no Gradescope text, no owner left behind


@pytest.mark.parametrize("links", [
    [],  # unlinked
    [{**_LINK, "gradescope_course_id": "another-course"}],  # re-pointed
    [{**_LINK, "enrollment_id": "enr-other"}],
])
def test_handler_aborts_as_link_changed_when_the_link_is_gone_before_it_starts(links):
    run, syncs = _handle("queued", links=links)
    run.assert_not_called()  # no login for a link that is gone
    assert syncs.rows["s1"]["error_code"] == "link_changed"


def test_a_link_removed_mid_sync_writes_nothing():
    """The link is re-checked right before the first write: removed while the
    scrape ran -> link_changed, no assignment written, no last_sync_* write."""
    route_tables = _route_tables()
    syncs = FakeTable([{**_ROW, "stage": "queued"}])
    links = FakeTable([_LINK])
    tables = {"gradescope_syncs": syncs, "jobs": MagicMock(), "gradescope_course_links": links}

    def _scrape(_conn, _course):
        links.rows.clear()  # the student unlinks while Gradescope is scraped
        return _INCOMING

    with (
        patch.object(gj, "table", side_effect=lambda n: tables[n]),
        patch_gradescope("table", side_effect=lambda name: route_tables[name]),
        patch_gradescope("_load_creds", return_value=_creds()),
        patch_gradescope("_establish_connection", MagicMock()),
        patch.object(gs, "list_assignments", side_effect=_scrape),
    ):
        gj._run_gradescope_sync_job({"sync_id": "s1"})
    assert syncs.rows["s1"]["error_code"] == "link_changed"
    route_tables["assignments"].insert.assert_not_called()
    route_tables["assignments"].update.assert_not_called()
    route_tables["gradescope_credentials"].update.assert_not_called()
    route_tables["gradescope_course_links"].update.assert_not_called()


def test_handler_raises_so_the_queue_retries_when_the_row_is_unreadable():
    t = MagicMock()
    t.return_value.select.side_effect = RuntimeError("PostgREST down")
    with patch.object(gj, "table", t), pytest.raises(RuntimeError):
        gj._run_gradescope_sync_job({"sync_id": "s1"})


def test_worker_run_uses_stored_credentials_and_records_the_outcome_where_inline_does():
    """End to end through the REAL sync body in the worker: credentials come
    from gradescope_credentials (decrypted), the scrape is mocked at the
    Gradescope layer, the gradebook is written, last_sync_* is recorded on
    gradescope_credentials and the counts land on the staged row."""
    from services.encryption import encrypt

    route_tables = _route_tables()
    route_tables["gradescope_credentials"].select.return_value = [{
        "auth_mode": "cookies", "email_encrypted": None, "password_encrypted": None,
        "cookies_encrypted": encrypt(json.dumps({"_gradescope_session": "sess",
                                                  "signed_token": "tok"})),
        "updated_at": "2026-11-08T00:00:00+00:00", "needs_reauth": False,
    }]
    syncs = FakeTable([{**_ROW, "stage": "queued"}])
    conn = MagicMock()
    with (
        patch_gradescope("table", side_effect=lambda name: route_tables[name]),
        patch.object(gj, "table", side_effect=_gj_tables(syncs)),
        patch.object(gs, "login_with_cookies", return_value=conn) as login,
        patch.object(gs, "login") as password_login,
        patch.object(gs, "list_assignments", return_value=_INCOMING) as scrape,
    ):
        gj._run_gradescope_sync_job({"sync_id": "s1"})
    login.assert_called_once_with(signed_token="tok", gradescope_session="sess")
    password_login.assert_not_called()
    scrape.assert_called_once_with(conn, "gs-course")
    conn.session.close.assert_called_once()
    route_tables["assignments"].insert.assert_called_once()
    state = route_tables["gradescope_credentials"].update.call_args.args[0]
    assert state["last_sync_error"] is None and "last_synced_at" in state
    assert route_tables["gradescope_course_links"].update.call_args.kwargs["filters"] == {
        "id": "eq.link-1"}
    assert syncs.rows["s1"]["stage"] == "done" and syncs.rows["s1"]["counts"] == _INLINE_JSON


def test_worker_run_records_rejected_stored_credentials_like_inline():
    route_tables = _route_tables()
    syncs = FakeTable([{**_ROW, "stage": "queued"}])
    with (
        patch_gradescope("table", side_effect=lambda name: route_tables[name]),
        patch_gradescope("_load_creds", return_value=_creds()),
        patch_gradescope("_establish_connection",
              side_effect=gs.GradescopeAuthError("Session expired")),
        patch.object(gj, "table", side_effect=_gj_tables(syncs)),
    ):
        gj._run_gradescope_sync_job({"sync_id": "s1"})
    state = route_tables["gradescope_credentials"].update.call_args
    assert state.args[0]["needs_reauth"] is True
    assert state.args[0]["last_sync_error"] == "auth_failed"
    assert state.kwargs["filters"] == {"user_id": "eq.u1", "updated_at": "eq.v1"}
    assert syncs.rows["s1"]["stage"] == "failed"
    assert syncs.rows["s1"]["error_code"] == "auth_failed"


# ── GET /sync/{course}/status ───────────────────────────────────────────────


def _status(rows, *, enrollments=("enr-1",), require_self=None):
    syncs = FakeTable(rows)
    with (
        patch_gradescope("_all_enrollments_for", return_value=list(enrollments)),
        patch.object(gj, "table", side_effect=_gj_tables(syncs)),
        patch_gradescope("require_self", require_self or MagicMock()),
    ):
        return client.get("/api/gradescope/sync/c1/status",
                          params={"user_id": "u1", "semester": "Fall 2025"},
                          headers={"X-Request-ID": RID})


def _sync_row(stage, *, sid="s1", user="u1", enrollment="enr-1", ago=0, **extra):
    return {"id": sid, "user_id": user, "enrollment_id": enrollment, "stage": stage,
            "created_at": _iso(ago), "updated_at": _iso(ago), **extra}


def test_status_is_404_when_the_course_has_no_staged_sync():
    r = _status([])
    assert r.status_code == 404


def test_status_is_404_for_a_course_the_student_is_not_enrolled_in():
    """Cross-user: another student's course resolves to none of the caller's
    enrollments, so their sync rows are never read."""
    r = _status([_sync_row("done", user="u2", counts={"inserted": 9})], enrollments=())
    assert r.status_code == 404
    assert "inserted" not in r.text


def test_status_never_returns_another_students_sync():
    r = _status([_sync_row("done", user="u2", counts={"inserted": 9})])
    assert r.status_code == 404


def test_status_checks_the_session_first():
    guard = MagicMock(side_effect=HTTPException(403, "Forbidden"))
    r = _status([_sync_row("done", counts=_INLINE_JSON)], require_self=guard)
    assert r.status_code == 403
    guard.assert_called_once()


@pytest.mark.parametrize("stage", ["queued", "running", "inline"])
def test_status_is_202_while_the_sync_runs(stage):
    r = _status([_sync_row(stage)])
    assert r.status_code == 202
    assert r.json()["pending"] is True and r.json()["stage"] == stage


def test_status_answers_the_latest_finished_sync_like_the_post():
    r = _status([_sync_row("done", ago=60, sid="old", counts={"inserted": 9}),
                 _sync_row("done", counts=_INLINE_JSON)])
    assert r.status_code == 200 and r.json() == _INLINE_JSON


def test_status_answers_a_failed_sync_with_the_same_typed_error():
    r = _status([_sync_row("failed", error_code="auth_failed")])
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "gradescope_reauth_required"


def test_status_reports_an_abandoned_inline_run_as_failed():
    r = _status([_sync_row("inline", ago=gj.INLINE_STALE_SECONDS + 60)])
    assert r.status_code == 502
    assert r.json()["detail"] == "Gradescope sync failed. Please retry."


def test_stage_sync_retries_when_the_conflicting_sync_ended_before_the_read():
    t = MagicMock()
    t.return_value.insert.side_effect = [RuntimeError("23505"), [{"id": "s2"}]]
    t.return_value.select.return_value = []  # the active sync finished meanwhile
    with patch.object(gj, "table", t):
        assert gj.stage_sync(**_STAGE_KW) == gj.Staged(id="s2", fresh=True)
