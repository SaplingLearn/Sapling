"""#116 (plan phase 2): the Gradescope sync on the Postgres job queue.

Hermetic; the browser/HTTP layer (`_establish_connection`,
`gradescope_service.list_assignments`) and `table()` are mocked. Pins:
  * flag OFF: the sync route behaves exactly as before (nothing staged,
    nothing enqueued, the login + scrape + writes run in the request);
  * flag ON: a `gradescope.sync` job is enqueued with ONLY the staged row's id
    (never credentials), the route waits on the row and answers with the
    inline route's JSON / status codes for every outcome;
  * staging or enqueue failure, or no worker picking the job up, syncs inline;
  * the worker handler validates its payload, races the request on the stage,
    runs the SAME sync body (which records last_sync_* on
    gradescope_credentials) and stores counts / a fixed error code.
What the SQL does with the rows (one active sync per enrollment, the CHECKs,
the stage CAS, RLS bucket E) is pinned against real Postgres in
tests/integration/test_gradescope_syncs_db.py.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from services import gradescope_jobs as gj
from services import gradescope_service as gs
from services import jobs, request_limits

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_rate_state():
    request_limits._rate_state.clear()
    yield
    request_limits._rate_state.clear()


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
    tables["gradescope_course_links"].select.return_value = [
        {"id": "link-1", "enrollment_id": "enr-1", "gradescope_course_id": "gs-course"},
    ]
    return tables


_INCOMING = [
    {"id": "new", "name": "Homework 1", "points_earned": 9, "points_possible": 10},
    {"id": "existing", "name": "Exam"},
    {"id": "", "name": "unavailable"},
]
_INLINE_JSON = {"inserted": 1, "updated": 1, "skipped": 1, "failed": 0}


def _post(tables, *, connect=None, incoming=_INCOMING, extra=()):
    """POST /sync with the DB and the Gradescope layer mocked. `connect` is
    the _establish_connection mock (a MagicMock by default)."""
    connect = connect or MagicMock(name="_establish_connection")
    with (
        patch("routes.gradescope.table", side_effect=lambda name: tables[name]),
        patch("routes.gradescope._all_enrollments_for", return_value=["enr-1"]),
        patch("routes.gradescope._load_creds", return_value=MagicMock(needs_reauth=False)),
        patch("routes.gradescope._establish_connection", connect),
        patch.object(gs, "list_assignments", return_value=incoming),
    ):
        for p in extra:
            p.start()
        try:
            r = client.post("/api/gradescope/sync/c1", params={"user_id": "u1", "semester": "Fall 2025"})
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


# ── flag OFF: today's behaviour ─────────────────────────────────────────────


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


def test_flag_off_write_failure_keeps_the_same_502_detail():
    tables = _route_tables()
    tables["assignments"].insert.side_effect = RuntimeError("write failed")
    with patch.object(gj, "flag_on", return_value=False):
        r, _ = _post(tables, incoming=[{"id": "new"}])
    assert r.status_code == 502
    assert r.json()["detail"] == (
        "No assignments could be saved. Please retry; if this continues, contact support.")


# ── flag ON: the request enqueues and relays the worker's outcome ───────────


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
    ("worker_failed", 502, None, "Gradescope sync failed. Please retry."),
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


def test_flag_on_a_sync_past_the_wait_is_a_504_that_keeps_running():
    tables = _route_tables()
    running = {"id": "s1", "stage": "running", "job_id": None}
    patches = _queued([running]) + [patch.object(gj, "SYNC_MAX_WAIT_SECONDS", 0.0)]
    r, _ = _post(tables, extra=patches)
    assert r.status_code == 504
    assert r.json()["detail"] == gj.TIMEOUT_MESSAGE


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


def test_flag_on_enqueue_failure_takes_the_sync_back_and_runs_it_inline():
    tables = _route_tables()
    with (
        patch.object(gj, "flag_on", return_value=True),
        patch.object(gj, "stage_sync", return_value=gj.Staged(id="s1", fresh=True)),
        patch.object(jobs, "enqueue", side_effect=RuntimeError("PostgREST down")),
        patch.object(gj, "take_back", return_value=True) as back,
        patch.object(gj, "read_status") as read,
    ):
        r, connect = _post(tables)
    assert r.status_code == 200 and r.json() == _INLINE_JSON
    back.assert_called_once_with("s1")
    read.assert_not_called()
    connect.assert_called_once()


def test_flag_on_no_worker_within_the_grace_syncs_inline():
    tables = _route_tables()
    queued = {"id": "s1", "stage": "queued", "job_id": "j1"}
    patches = _queued([queued]) + [
        patch.object(gj, "PICKUP_GRACE_SECONDS", 0.0),
        patch.object(gj, "take_back", return_value=True),
    ]
    r, connect = _post(tables, extra=patches)
    assert r.status_code == 200 and r.json() == _INLINE_JSON
    connect.assert_called_once()


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
    clock = _Clock()
    with patch.object(gj, "read_status", side_effect=lambda _id: seq.pop(0) if len(seq) > 1 else seq[0]):
        return gj.wait_for_sync("s1", sleep=clock.sleep, clock=clock, poll=1.0, **kw)


def test_wait_returns_the_terminal_row():
    w = _wait([{"stage": "queued"}, {"stage": "running"}, {"stage": "done", "counts": {}}])
    assert w.kind == "done"


def test_wait_takes_back_a_sync_no_worker_claimed():
    with patch.object(gj, "take_back", return_value=True) as back:
        w = _wait([{"stage": "queued"}], grace=5)
    assert w.kind == "inline"
    back.assert_called_once_with("s1")


def test_wait_keeps_waiting_when_the_worker_won_the_take_back_race():
    with patch.object(gj, "take_back", return_value=False):
        w = _wait([{"stage": "queued"}] * 7 + [{"stage": "running"}, {"stage": "done"}], grace=5)
    assert w.kind == "done"


def test_wait_fails_a_running_sync_whose_job_died():
    running = {"stage": "running", "job_id": "j1"}
    with (
        patch.object(gj, "job_status", return_value="dead") as status,
        patch.object(gj, "fail_if_running", return_value=True) as fail,
    ):
        w = _wait([running] * 11 + [{"stage": "failed", "error_code": "worker_failed"}])
    status.assert_called_with("j1")
    fail.assert_called_once_with("s1", "worker_failed")
    assert w.kind == "failed" and w.row["error_code"] == "worker_failed"


def test_wait_reports_a_vanished_row_as_a_failure():
    w = _wait([None])
    assert w.kind == "failed" and w.row["error_code"] == "worker_failed"


def test_wait_times_out():
    w = _wait([{"stage": "running"}], max_wait=30)
    assert w.kind == "timeout"


# ── staging ─────────────────────────────────────────────────────────────────

_STAGE_KW = dict(user_id="u1", enrollment_id="enr-1", link_id="link-1",
                 gradescope_course_id="gs-course")


def test_stage_sync_inserts_a_queued_row_with_ids_only():
    t = MagicMock()
    t.return_value.insert.return_value = [{"id": "s1"}]
    with patch.object(gj, "table", t):
        assert gj.stage_sync(**_STAGE_KW) == gj.Staged(id="s1", fresh=True)
    t.assert_any_call("gradescope_syncs")
    row = t.return_value.insert.call_args.args[0]
    assert row == {**_STAGE_KW, "stage": "queued"}


def test_stage_sync_attaches_to_a_sync_of_the_course_in_flight():
    from datetime import datetime, timezone

    t = MagicMock()
    t.return_value.insert.side_effect = RuntimeError("23505 gradescope_syncs_active_key")
    t.return_value.select.return_value = [
        {"id": "s0", "stage": "running", "created_at": datetime.now(timezone.utc).isoformat()}]
    with patch.object(gj, "table", t):
        assert gj.stage_sync(**_STAGE_KW) == gj.Staged(id="s0", fresh=False)
    t.return_value.update.assert_not_called()
    assert t.return_value.select.call_args.kwargs["filters"] == {
        "user_id": "eq.u1", "enrollment_id": "eq.enr-1", "stage": "in.(queued,running)"}


def test_stage_sync_fails_an_abandoned_sync_and_starts_a_new_one():
    t = MagicMock()
    t.return_value.insert.side_effect = [RuntimeError("23505"), [{"id": "s2"}]]
    t.return_value.select.return_value = [
        {"id": "s0", "stage": "queued", "created_at": "2020-01-01T00:00:00+00:00"}]
    with patch.object(gj, "table", t):
        assert gj.stage_sync(**_STAGE_KW) == gj.Staged(id="s2", fresh=True)
    data = t.return_value.update.call_args.args[0]
    assert data == {"stage": "failed", "error_code": "worker_failed"}
    assert t.return_value.update.call_args.kwargs["filters"] == {"id": "eq.s0", "stage": "eq.queued"}


def test_stage_sync_reraises_an_insert_error_that_is_not_a_conflict():
    t = MagicMock()
    t.return_value.insert.side_effect = RuntimeError("PostgREST down")
    t.return_value.select.return_value = []
    with patch.object(gj, "table", t), pytest.raises(RuntimeError):
        gj.stage_sync(**_STAGE_KW)


def test_take_back_is_a_compare_and_swap_on_queued():
    t = MagicMock()
    t.return_value.update.return_value = []
    with patch.object(gj, "table", t):
        assert gj.take_back("s1") is False
    assert t.return_value.update.call_args.args[0] == {"stage": "inline"}
    assert t.return_value.update.call_args.kwargs["filters"] == {"id": "eq.s1", "stage": "eq.queued"}


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


def _handle(stage, *, sync=None, cas_wins=True, row_exists=True):
    t = MagicMock()
    t.return_value.select.return_value = [{**_ROW, "stage": stage}] if row_exists else []
    t.return_value.update.side_effect = (
        lambda data, filters: [data] if cas_wins or "stage" not in filters else [])
    sync = sync or MagicMock(return_value=dict(_INLINE_JSON))
    with patch.object(gj, "table", t), patch("routes.gradescope._sync_linked_course", sync):
        gj._run_gradescope_sync_job({"sync_id": "s1"})
    writes = [(c.args[0], c.kwargs["filters"]) for c in t.return_value.update.call_args_list]
    return sync, writes


def test_handler_claims_runs_the_inline_sync_and_stores_the_counts():
    sync, writes = _handle("queued")
    sync.assert_called_once_with("u1", "gs-course", "enr-1", "link-1")
    assert writes[0] == ({"stage": "running"}, {"id": "eq.s1", "stage": "eq.queued"})
    assert writes[-1] == ({"stage": "done", "error_code": None, "counts": _INLINE_JSON},
                          {"id": "eq.s1"})


def test_handler_does_nothing_when_the_request_took_the_sync_back_first():
    sync, writes = _handle("queued", cas_wins=False)
    sync.assert_not_called()
    assert len(writes) == 1


@pytest.mark.parametrize("stage", ["done", "failed", "inline"])
def test_handler_is_a_no_op_on_a_finished_sync(stage):
    sync, writes = _handle(stage)
    sync.assert_not_called()
    assert writes == []


def test_handler_is_a_no_op_when_the_row_is_gone():
    sync, writes = _handle("queued", row_exists=False)
    sync.assert_not_called()
    assert writes == []


def test_handler_reruns_a_redelivered_running_sync():
    sync, writes = _handle("running")
    sync.assert_called_once()
    assert writes == [({"stage": "done", "error_code": None, "counts": _INLINE_JSON},
                       {"id": "eq.s1"})]


def _json_response(status):
    from routes.gradescope import _gs_error

    return _gs_error(status, "x", "y")


@pytest.mark.parametrize("outcome,code", [
    (lambda: _json_response(404), "not_connected"),
    (lambda: _json_response(409), "auth_failed"),
    (HTTPException(502, "No assignments could be saved. Please retry; if this continues, contact support."),
     "write_failed"),
    (HTTPException(502, "Couldn't reach Gradescope. Please retry shortly."), "fetch_failed"),
    (HTTPException(500, "Stored credentials could not be read."), "creds_unreadable"),
    (RuntimeError("PostgREST blip"), "worker_failed"),
])
def test_handler_records_each_sync_outcome_as_a_fixed_code(outcome, code):
    if isinstance(outcome, Exception):
        sync = MagicMock(side_effect=outcome)
    else:
        sync = MagicMock(return_value=outcome())
    _, writes = _handle("queued", sync=sync)
    assert writes[-1] == ({"stage": "failed", "error_code": code}, {"id": "eq.s1"})


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
    sync_table = MagicMock()
    sync_table.select.return_value = [{**_ROW, "stage": "queued"}]
    sync_table.update.side_effect = lambda data, filters: [data]
    conn = MagicMock()
    with (
        patch("routes.gradescope.table", side_effect=lambda name: route_tables[name]),
        patch.object(gj, "table", return_value=sync_table),
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
    assert sync_table.update.call_args.args[0] == {
        "stage": "done", "error_code": None, "counts": _INLINE_JSON}


def test_worker_run_records_rejected_stored_credentials_like_inline():
    route_tables = _route_tables()
    sync_table = MagicMock()
    sync_table.select.return_value = [{**_ROW, "stage": "queued"}]
    sync_table.update.side_effect = lambda data, filters: [data]
    creds = MagicMock(updated_at="v1", needs_reauth=False)
    with (
        patch("routes.gradescope.table", side_effect=lambda name: route_tables[name]),
        patch("routes.gradescope._load_creds", return_value=creds),
        patch("routes.gradescope._establish_connection",
              side_effect=gs.GradescopeAuthError("Session expired")),
        patch.object(gj, "table", return_value=sync_table),
    ):
        gj._run_gradescope_sync_job({"sync_id": "s1"})
    state = route_tables["gradescope_credentials"].update.call_args
    assert state.args[0]["needs_reauth"] is True
    assert state.args[0]["last_sync_error"] == "auth_failed"
    assert state.kwargs["filters"] == {"user_id": "eq.u1", "updated_at": "eq.v1"}
    assert sync_table.update.call_args.args[0] == {"stage": "failed", "error_code": "auth_failed"}
