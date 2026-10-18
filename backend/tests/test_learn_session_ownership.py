"""Tutor routes must check that the session belongs to the caller.

`require_self(body.user_id, request)` only proves the caller IS
`body.user_id`; it says nothing about `body.session_id`. Before this fix a
student holding another student's session UUID could, on /chat,
/chat/stream, /action and /mode-switch, load that student's decrypted
history into the model context and append messages to their session, and
on /end-session close it out (and write its summary).

Every route that takes a session id now goes through
`services.tutor_sessions.require_session_owner` first. It answers 404, not 403, for
a session that is missing OR owned by someone else, so ids can't be probed.
"""
import threading
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from tests.agent_run_fakes import run_result

client = TestClient(app)

OWNER = "user_owner"
INTRUDER = "user_intruder"
SESSION = "sess-owned-by-owner"


class _Tables:
    """Hermetic `table()` factory that records what each route touched.

    `sessions` answers with one row owned by `session_owner` (or nothing,
    for the missing-session case). `messages` reads return one encrypted-
    looking row so a history load is observable.
    """

    def __init__(self, session_owner: str | None = OWNER):
        self.session_owner = session_owner
        self.mocks: dict[str, MagicMock] = {}

    def __call__(self, name):
        if name in self.mocks:
            return self.mocks[name]
        m = MagicMock()
        if name == "sessions":
            m.select.return_value = (
                [{
                    "id": SESSION,
                    "user_id": self.session_owner,
                    "offering_id": "off1",
                    "topic": "Recursion",
                    "mode": "socratic",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "ended_at": None,
                }]
                if self.session_owner
                else []
            )
        elif name == "messages":
            m.select.return_value = [
                {"id": "m1", "role": "user", "content": "secret question",
                 "created_at": "2026-01-01T00:00:01+00:00", "graph_update_json": None},
            ]
        else:
            m.select.return_value = []
        m.insert.return_value = []
        m.upsert.return_value = []
        m.update.return_value = []
        m.delete.return_value = []
        self.mocks[name] = m
        return m

    def touched(self, name: str, method: str) -> bool:
        m = self.mocks.get(name)
        return bool(m and getattr(m, method).called)


def _agent():
    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("A tutor reply."))
    return agent


# Each route as (label, callable(user_id) -> response). Bodies are the
# smallest valid shape each route accepts.
def _chat(uid, sid=SESSION):
    return client.post("/api/learn/chat", json={
        "session_id": sid, "user_id": uid, "message": "hi", "mode": "socratic",
    })


def _chat_stream(uid, sid=SESSION):
    return client.post("/api/learn/chat/stream", json={
        "session_id": sid, "user_id": uid, "message": "hi", "mode": "socratic",
    })


def _action(uid, sid=SESSION):
    return client.post("/api/learn/action", json={
        "session_id": sid, "user_id": uid, "action_type": "hint", "mode": "socratic",
    })


def _mode_switch(uid, sid=SESSION):
    return client.post("/api/learn/mode-switch", json={
        "session_id": sid, "user_id": uid, "new_mode": "expository",
    })


def _end_session(uid, sid=SESSION):
    return client.post("/api/learn/end-session", json={"session_id": sid, "user_id": uid})


def _rename(uid, sid=SESSION):
    return client.patch(f"/api/learn/sessions/{sid}", json={"user_id": uid, "topic": "New"})


def _delete(uid, sid=SESSION):
    return client.delete(f"/api/learn/sessions/{sid}?user_id={uid}")


def _resume(uid, sid=SESSION):
    # The conftest auth stub reads the session user off ?user_id=.
    return client.get(f"/api/learn/sessions/{sid}/resume?user_id={uid}")


ROUTES = [
    ("chat", _chat),
    ("chat_stream", _chat_stream),
    ("action", _action),
    ("mode_switch", _mode_switch),
    ("end_session", _end_session),
    ("rename", _rename),
    ("resume", _resume),
]


@pytest.fixture
def harness():
    """Patch every side-effect seam a tutor route can reach."""
    tables = _Tables()
    agent = _agent()
    stream = MagicMock(name="stream_agent_turn")
    with (
        patch("routes.learn.table", side_effect=tables),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("routes.learn.stream_agent_turn", stream),
        patch("routes.learn.get_display_name", return_value="Owner Person"),
        patch("routes.learn.events_service.log_event") as log_event,
        patch("routes.learn.award_xp_safe") as award,
        patch("routes.learn.touch_streak_safe") as streak,
        patch("routes.learn.offering_course_id", return_value="c1"),
    ):
        yield {
            "tables": tables, "agent": agent, "stream": stream,
            "log_event": log_event, "award": award, "streak": streak,
        }


def _assert_nothing_happened(h):
    t = h["tables"]
    assert not t.touched("messages", "select"), "must not load another student's history"
    assert not t.touched("messages", "insert"), "must not write into another student's session"
    assert not t.touched("messages", "delete")
    assert not t.touched("sessions", "update")
    assert not t.touched("sessions", "delete")
    assert not t.touched("sessions", "insert")
    assert not t.touched("sessions", "upsert")
    assert not h["agent"].run.called, "no model call on someone else's session"
    assert not h["stream"].called, "no streamed model call on someone else's session"
    # The request middleware's own `error.4xx` row is expected; any product
    # event (session.*, chat.*) would mean the route ran past the guard.
    product_events = [
        c.args[0] for c in h["log_event"].call_args_list
        if not str(c.args[0]).startswith("error.")
    ]
    assert product_events == [], f"no product events for a rejected request: {product_events}"
    assert not h["award"].called
    assert not h["streak"].called


# ── Another student's materialised session ───────────────────────────────────

@pytest.mark.parametrize("label,call", ROUTES, ids=[r[0] for r in ROUTES])
def test_other_students_session_is_404_and_inert(harness, label, call):
    r = call(INTRUDER)
    assert r.status_code == 404, f"{label}: {r.status_code} {r.text}"
    _assert_nothing_happened(harness)


def test_delete_of_another_students_session_is_a_noop_200(harness):
    """Delete stays idempotent (#709 review): a foreign id is a no-op 200 that
    deletes nothing and does not reveal whether the session exists."""
    r = _delete(INTRUDER)
    assert r.status_code == 200 and r.json() == {"deleted": True}, r.text
    _assert_nothing_happened(harness)


def test_delete_of_a_missing_session_is_a_noop_200():
    """A second delete of the same session (another tab, a double click) succeeds."""
    tables = _Tables(session_owner=None)
    with patch("routes.learn.table", side_effect=tables):
        r = _delete(OWNER, "no-such-session")
    assert r.status_code == 200 and r.json() == {"deleted": True}, r.text
    assert not tables.touched("messages", "delete")
    assert not tables.touched("sessions", "delete")


@pytest.mark.parametrize("label,call", ROUTES, ids=[r[0] for r in ROUTES])
def test_missing_session_is_404(label, call):
    tables = _Tables(session_owner=None)
    with patch("routes.learn.table", side_effect=tables), \
         patch("routes.learn.agent_for_mode", return_value=_agent()) as afm:
        r = call(OWNER, "no-such-session")
    assert r.status_code == 404, f"{label}: {r.status_code} {r.text}"
    assert not tables.touched("messages", "select")
    assert not tables.touched("messages", "insert")
    assert not afm.return_value.run.called


def test_missing_and_foreign_are_indistinguishable(harness):
    """Same status AND same body, so a 404 can't tell an attacker whether
    the id exists."""
    foreign = _chat(INTRUDER)
    with patch("routes.learn.table", side_effect=_Tables(session_owner=None)):
        missing = _chat(OWNER, "no-such-session")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["detail"] == missing.json()["detail"]


# ── The owner still works ────────────────────────────────────────────────────

def test_owner_chat_works(harness):
    r = _chat(OWNER)
    assert r.status_code == 200, r.text
    assert r.json()["reply"] == "A tutor reply."
    assert harness["tables"].touched("messages", "select")
    assert harness["tables"].touched("messages", "insert")
    harness["agent"].run.assert_called_once()


def test_owner_chat_stream_works(harness):
    async def fake_stream(**kwargs):
        from services.agent_events import SaplingEvent
        kwargs["on_complete"]("Hi", {}, [])
        yield SaplingEvent(type="done", step="reply", message="Complete.",
                           data={"reply": "Hi", "graph_update": {}, "mastery_changes": []})

    with patch("routes.learn.stream_agent_turn", fake_stream):
        r = _chat_stream(OWNER)
    assert r.status_code == 200, r.text
    assert "text/event-stream" in r.headers["content-type"]
    assert harness["tables"].touched("messages", "select")
    assert harness["tables"].touched("messages", "insert")


def test_owner_action_works(harness):
    r = _action(OWNER)
    assert r.status_code == 200, r.text
    assert r.json()["reply"] == "A tutor reply."
    harness["agent"].run.assert_called_once()


def test_owner_mode_switch_works(harness):
    r = _mode_switch(OWNER)
    assert r.status_code == 200, r.text
    assert "Recursion" in r.json()["reply"]
    assert harness["tables"].touched("messages", "insert")


def test_owner_end_session_works(harness):
    r = _end_session(OWNER)
    assert r.status_code == 200, r.text
    assert "summary" in r.json()
    assert harness["tables"].touched("sessions", "update")
    harness["award"].assert_called_once()


def test_owner_rename_works(harness):
    r = _rename(OWNER)
    assert r.status_code == 200, r.text
    assert harness["tables"].touched("sessions", "update")


def test_owner_delete_works(harness):
    r = _delete(OWNER)
    assert r.status_code == 200, r.text
    assert harness["tables"].touched("messages", "delete")
    assert harness["tables"].touched("sessions", "delete")


def test_owner_resume_works(harness):
    r = _resume(OWNER)
    assert r.status_code == 200, r.text
    assert r.json()["session"]["id"] == SESSION
    assert r.json()["messages"][0]["content"] == "secret question"


# ── Still-pending lazy sessions ──────────────────────────────────────────────

PENDING = "sess-pending"


@pytest.fixture
def pending_for_owner():
    from routes.learn import PENDING_SESSIONS
    PENDING_SESSIONS[PENDING] = {
        "user_id": OWNER,
        "mode": "socratic",
        "topic": "Pending topic",
        "course_id": "c1",
        "offering_id": "off1",
        "assistant_reply": "Welcome!",
        "graph_update": {},
    }
    yield PENDING_SESSIONS
    PENDING_SESSIONS.pop(PENDING, None)


@pytest.mark.parametrize("label,call", ROUTES, ids=[r[0] for r in ROUTES])
def test_other_students_pending_session_is_404_and_left_intact(
    harness, pending_for_owner, label, call
):
    """A pending session is accepted only for the user PENDING_SESSIONS
    recorded. The intruder gets the same 404 as a foreign materialised
    session, and the owner's pending entry is NOT consumed (before the fix
    _consume_pending popped it before checking, so a probe destroyed it)."""
    # No DB row exists yet for a pending session.
    harness["tables"].session_owner = None
    r = call(INTRUDER, PENDING)
    assert r.status_code == 404, f"{label}: {r.status_code} {r.text}"
    assert PENDING in pending_for_owner, "a rejected probe must not consume the pending session"
    assert pending_for_owner[PENDING]["topic"] == "Pending topic"
    _assert_nothing_happened(harness)


def test_owner_pending_session_materialises_on_chat(harness, pending_for_owner):
    harness["tables"].session_owner = None  # row not inserted yet
    r = _chat(OWNER, PENDING)
    assert r.status_code == 200, r.text
    assert PENDING not in pending_for_owner, "first chat turn materialises the session"
    write = harness["tables"].mocks["sessions"].upsert.call_args
    assert write.args[0]["id"] == PENDING and write.args[0]["user_id"] == OWNER
    # Idempotent: a retry after a lost response must not hit a duplicate PK.
    assert write.kwargs == {"on_conflict": "id", "ignore_duplicates": True}
    harness["agent"].run.assert_called_once()


@pytest.mark.parametrize(
    "call", [_end_session, _rename, _delete, _resume],
    ids=["end_session", "rename", "delete", "resume"],
)
def test_owner_pending_session_management_works(harness, pending_for_owner, call):
    harness["tables"].session_owner = None
    r = call(OWNER, PENDING)
    assert r.status_code == 200, r.text


# ── The helper itself ────────────────────────────────────────────────────────

class TestRequireSessionOwner:
    def test_owner_passes(self):
        from services.tutor_sessions import require_session_owner
        with patch("services.tutor_sessions.table", side_effect=_Tables()):
            require_session_owner(SESSION, OWNER)

    @pytest.mark.parametrize("uid", [INTRUDER, "", None])
    def test_non_owner_raises_404(self, uid):
        from fastapi import HTTPException
        from services.tutor_sessions import require_session_owner
        with patch("services.tutor_sessions.table", side_effect=_Tables()):
            with pytest.raises(HTTPException) as exc:
                require_session_owner(SESSION, uid)
        assert exc.value.status_code == 404

    def test_owner_row_with_null_user_id_is_404(self):
        """A row whose user_id is NULL belongs to nobody — never match it
        against a falsy caller id."""
        from fastapi import HTTPException
        from services.tutor_sessions import require_session_owner
        tables = _Tables()
        tables("sessions").select.return_value = [{"user_id": None}]
        with patch("services.tutor_sessions.table", side_effect=tables):
            with pytest.raises(HTTPException) as exc:
                require_session_owner(SESSION, None)
        assert exc.value.status_code == 404

    def test_pending_owner_passes_without_db_read(self, pending_for_owner):
        from services.tutor_sessions import require_session_owner
        tables = _Tables(session_owner=None)
        with patch("services.tutor_sessions.table", side_effect=tables):
            require_session_owner(PENDING, OWNER)
        assert not tables.touched("sessions", "select")

    def test_reads_sessions_user_id_by_id(self):
        from services.tutor_sessions import require_session_owner
        tables = _Tables()
        with patch("services.tutor_sessions.table", side_effect=tables):
            require_session_owner(SESSION, OWNER)
        call = tables.mocks["sessions"].select.call_args
        assert call.args[0] == "user_id"
        assert call.kwargs["filters"] == {"id": f"eq.{SESSION}"}


# ── Concurrent materialisation of one pending session ────────────────────────
#
# CodeRabbit on #709: /mode-switch is a sync route, so FastAPI runs it in the
# threadpool and two of the owner's requests for one pending session can
# overlap. The loser must not return from `_ensure_session_ready` until the
# winner has inserted the `sessions` row and the initial assistant message;
# otherwise its own `save_message` hits the `messages.session_id` foreign key
# before the row exists.
#
# Threads are sequenced with events, never sleeps: the winner parks inside
# the `sessions` row write until the test releases it, and the test releases it only
# once the loser has either finished (the bug) or reached the per-session
# lock (the fix). Every wait carries a timeout so a regression fails instead
# of hanging the suite.

RACE = "sess-race"
_WAIT = 5  # seconds; a failure bound only, never a synchronisation point


def _race_payload():
    return {
        "user_id": OWNER, "mode": "socratic", "topic": "Race topic",
        "course_id": "c1", "offering_id": "off1",
        "assistant_reply": "Welcome!", "graph_update": {},
    }


@pytest.fixture
def race_pending():
    from routes.learn import PENDING_SESSIONS
    PENDING_SESSIONS[RACE] = _race_payload()
    yield PENDING_SESSIONS
    PENDING_SESSIONS.pop(RACE, None)


def _lock_registry() -> dict:
    from services import tutor_sessions
    return getattr(tutor_sessions, "_MATERIALIZATION_LOCKS", {})


def _observed_lock(on_loser_arrival):
    """Wrap `materialization_lock` so the test learns when the loser thread
    has reached it. ``create=True`` on the patch keeps this test runnable
    against code that has no lock at all (the regression it pins)."""
    from routes import learn

    real_lock = getattr(learn, "materialization_lock", None)

    @contextmanager
    def lock(session_id):
        if threading.current_thread().name == "loser":
            on_loser_arrival()
        with real_lock(session_id):
            yield

    return lock


def _fk_tables(row_inserted, *, sessions_insert):
    """`_Tables` whose `messages.insert` records a foreign-key violation when
    the session row is not there yet. The row write is hooked on both
    `insert` and `upsert` so the test also runs against the pre-fix code."""
    tables = _Tables(session_owner=None)  # no row until the winner inserts it
    tables("sessions").insert.side_effect = sessions_insert
    tables("sessions").upsert.side_effect = (
        lambda row, *a, **kw: sessions_insert(row)
    )
    violations: list[str] = []

    def messages_insert(row):
        if not row_inserted.is_set():
            violations.append(row["content"])
        return []

    tables("messages").insert.side_effect = messages_insert
    return tables, violations


def _mode_switch_like(session_id, errors):
    """The two steps /mode-switch takes after the ownership check."""
    from routes import learn

    def run():
        try:
            learn._ensure_session_ready(session_id, OWNER)
            learn.save_message(session_id, "assistant", "Switching modes.")
        except Exception as e:  # surfaced to the test thread below
            errors.append(e)

    return run


def test_losing_request_waits_for_the_winner_to_materialise_the_session(race_pending):
    from services.tutor_sessions import session_owned_by

    insert_started = threading.Event()
    release_insert = threading.Event()
    row_inserted = threading.Event()
    loser_progress = threading.Event()

    def sessions_insert(row):
        insert_started.set()
        assert release_insert.wait(_WAIT), "test never released the winner"
        row_inserted.set()
        return []

    tables, violations = _fk_tables(row_inserted, sessions_insert=sessions_insert)
    winner_errors: list = []
    loser_errors: list = []
    loser_body = _mode_switch_like(RACE, loser_errors)

    def loser_run():
        try:
            loser_body()
        finally:
            loser_progress.set()

    with (
        patch("routes.learn.table", side_effect=tables),
        patch("services.tutor_sessions.table", side_effect=tables),
        patch("routes.learn.events_service.log_event") as log_event,
        patch(
            "routes.learn.materialization_lock",
            _observed_lock(loser_progress.set),
            create=True,
        ),
    ):
        winner = threading.Thread(
            target=_mode_switch_like(RACE, winner_errors), name="winner"
        )
        winner.start()
        assert insert_started.wait(_WAIT), "winner never reached the sessions row write"
        # Mid-materialisation the session must still read as the owner's,
        # or a concurrent request's ownership check would 404 in the gap.
        owned_mid_flight = session_owned_by(RACE, OWNER)

        loser = threading.Thread(target=loser_run, name="loser")
        loser.start()
        # Loser has either finished (no lock: the bug) or reached the lock.
        assert loser_progress.wait(_WAIT), "loser never made progress"
        release_insert.set()
        winner.join(_WAIT)
        loser.join(_WAIT)

    assert not winner.is_alive() and not loser.is_alive(), "a request hung"
    assert winner_errors == [] and loser_errors == []
    assert violations == [], (
        f"messages written before the session row existed: {violations}"
    )
    tables.mocks["sessions"].upsert.assert_called_once()
    written = [c.args[0]["content"] for c in tables.mocks["messages"].insert.call_args_list]
    assert len(written) == 3, written  # greeting + each request's own reply
    log_event.assert_called_once()  # one session.started
    assert owned_mid_flight, "pending session vanished before its row existed"
    assert RACE not in race_pending
    assert _lock_registry() == {}, "per-session lock leaked"


def test_failed_materialisation_stays_pending_and_does_not_hang_waiters(race_pending):
    """The winner's insert fails while the loser waits: the loser must not
    hang, the session must not be reported ready, and the loser retries the
    materialisation itself."""

    insert_started = threading.Event()
    release_insert = threading.Event()
    row_inserted = threading.Event()
    loser_progress = threading.Event()
    attempts: list[int] = []

    def sessions_insert(row):
        attempts.append(1)
        if len(attempts) == 1:
            insert_started.set()
            assert release_insert.wait(_WAIT)
            raise RuntimeError("db unavailable")
        row_inserted.set()
        return []

    tables, violations = _fk_tables(row_inserted, sessions_insert=sessions_insert)
    winner_errors: list = []
    loser_errors: list = []
    loser_body = _mode_switch_like(RACE, loser_errors)

    def loser_run():
        try:
            loser_body()
        finally:
            loser_progress.set()

    with (
        patch("routes.learn.table", side_effect=tables),
        patch("routes.learn.events_service.log_event"),
        patch("routes.learn.materialization_lock", _observed_lock(loser_progress.set)),
    ):
        winner = threading.Thread(
            target=_mode_switch_like(RACE, winner_errors), name="winner"
        )
        winner.start()
        assert insert_started.wait(_WAIT)
        loser = threading.Thread(target=loser_run, name="loser")
        loser.start()
        assert loser_progress.wait(_WAIT)
        release_insert.set()
        winner.join(_WAIT)
        loser.join(_WAIT)

    assert not winner.is_alive() and not loser.is_alive(), "a waiter hung"
    assert [type(e) for e in winner_errors] == [RuntimeError]
    assert loser_errors == []
    assert violations == []
    assert len(attempts) == 2, "the waiter retries the failed materialisation"
    assert RACE not in race_pending
    assert _lock_registry() == {}


def test_failure_after_the_row_insert_retries_without_a_duplicate_row(race_pending):
    """If the greeting write fails after the row went in, the entry stays
    pending (the session is not ready: its greeting is missing) and the next
    request writes only the greeting, not a second `sessions` row."""
    from routes import learn

    tables = _Tables(session_owner=None)
    tables("messages").insert.side_effect = [RuntimeError("write failed"), []]
    with (
        patch("routes.learn.table", side_effect=tables),
        patch("routes.learn.events_service.log_event") as log_event,
    ):
        with pytest.raises(RuntimeError):
            learn._ensure_session_ready(RACE, OWNER)
        assert RACE in race_pending, "a failed materialisation is not 'ready'"
        learn._ensure_session_ready(RACE, OWNER)

    tables.mocks["sessions"].upsert.assert_called_once()
    assert tables.mocks["messages"].insert.call_count == 2
    log_event.assert_called_once()
    assert RACE not in race_pending
    assert _lock_registry() == {}


def test_ready_session_takes_no_lock():
    """Fast path: a session that is no longer pending never touches the
    per-session lock registry."""
    from routes import learn

    tables = _Tables()
    lock = MagicMock(side_effect=AssertionError("lock taken for a ready session"))
    with (
        patch("routes.learn.table", side_effect=tables),
        patch("routes.learn.materialization_lock", lock),
    ):
        learn._ensure_session_ready(SESSION, OWNER)
    assert not lock.called
    assert not tables.touched("sessions", "upsert")
    assert not tables.touched("messages", "insert")


# ── Idempotent row write (a committed insert whose response was lost) ────────

class _CommittedButRaised(Exception):
    """Stands in for an httpx timeout after PostgREST committed the row."""


def test_row_committed_but_response_lost_retries_cleanly(race_pending):
    """PostgREST commits the `sessions` row, then the client fails (timeout,
    dropped response). The retry must succeed and leave exactly one row; a
    plain INSERT would hit the duplicate PK on every retry, wedging the
    session until the process restarts."""
    from routes import learn

    db_rows: dict[str, dict] = {}
    tables = _Tables(session_owner=None)

    def insert(row):  # a real INSERT: duplicate PK is an error
        if row["id"] in db_rows:
            raise RuntimeError("duplicate key value violates sessions_pkey")
        db_rows[row["id"]] = row
        return [row]

    calls: list[int] = []

    def upsert(row, on_conflict="id", *, ignore_duplicates=False):
        calls.append(1)
        if row[on_conflict] in db_rows:
            if not ignore_duplicates:
                raise RuntimeError("duplicate key value violates sessions_pkey")
        else:
            db_rows[row[on_conflict]] = row
        if len(calls) == 1:
            raise _CommittedButRaised("read timeout")  # committed, then lost
        return []

    tables("sessions").insert.side_effect = insert
    tables("sessions").upsert.side_effect = upsert
    with (
        patch("routes.learn.table", side_effect=tables),
        patch("routes.learn.events_service.log_event") as log_event,
    ):
        with pytest.raises(_CommittedButRaised):
            learn._ensure_session_ready(RACE, OWNER)
        assert RACE in race_pending, "still pending: the greeting was never written"
        learn._ensure_session_ready(RACE, OWNER)

    assert list(db_rows) == [RACE], "the row exists exactly once"
    assert RACE not in race_pending
    tables.mocks["messages"].insert.assert_called_once()  # the greeting, once
    log_event.assert_called_once()  # session.started, once
    assert _lock_registry() == {}


# ── Management routes on a session whose row may already exist ───────────────
#
# A materialisation that wrote the row and then failed (on the greeting, say)
# leaves the entry pending with `_row_may_exist`. end / rename / delete must
# then act on the DB as well as on memory.

@pytest.fixture
def half_materialised(race_pending):
    race_pending[RACE].update(_row_may_exist=True, _row_written=True)
    return race_pending


def _owner_row_tables(harness):
    harness["tables"].session_owner = OWNER  # the row did land
    return harness["tables"]


def test_end_session_of_a_half_materialised_session_ends_the_row(harness, half_materialised):
    tables = _owner_row_tables(harness)
    r = _end_session(OWNER, RACE)
    assert r.status_code == 200, r.text
    assert RACE not in half_materialised
    updates = [c.args[0] for c in tables.mocks["sessions"].update.call_args_list]
    assert any("ended_at" in u for u in updates), "ended_at must be set on the real row"


def test_end_session_whose_attempted_row_never_landed_is_200(harness, half_materialised):
    harness["tables"].session_owner = None  # the write never committed
    r = _end_session(OWNER, RACE)
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["time_spent_minutes"] == 0
    assert RACE not in half_materialised


def test_rename_of_a_half_materialised_session_renames_the_row(harness, half_materialised):
    tables = _owner_row_tables(harness)
    r = _rename(OWNER, RACE)
    assert r.status_code == 200, r.text
    assert half_materialised[RACE]["topic"] == "New", "the retry writes the new name"
    update = tables.mocks["sessions"].update.call_args
    assert update.args[0] == {"topic": "New"}
    assert update.kwargs["filters"] == {"id": f"eq.{RACE}"}


def test_delete_of_a_half_materialised_session_deletes_the_row(harness, half_materialised):
    tables = _owner_row_tables(harness)
    r = _delete(OWNER, RACE)
    assert r.status_code == 200, r.text
    assert RACE not in half_materialised
    assert tables.mocks["sessions"].delete.call_args.args[0] == {"id": f"eq.{RACE}"}
    assert tables.mocks["messages"].delete.call_args.args[0] == {"session_id": f"eq.{RACE}"}


@pytest.mark.parametrize(
    "call", [_end_session, _rename, _delete], ids=["end_session", "rename", "delete"]
)
def test_never_attempted_pending_session_touches_no_rows(harness, race_pending, call):
    harness["tables"].session_owner = None
    r = call(OWNER, RACE)
    assert r.status_code == 200, r.text
    for method in ("update", "delete", "insert", "upsert"):
        assert not harness["tables"].touched("sessions", method), method
    assert not harness["tables"].touched("messages", "delete")


# ── Async routes materialise off the event loop ──────────────────────────────

ASYNC_ROUTES = [("chat", _chat), ("chat_stream", _chat_stream), ("action", _action)]


@pytest.mark.parametrize("label,call", ASYNC_ROUTES, ids=[r[0] for r in ASYNC_ROUTES])
def test_async_routes_materialise_in_the_threadpool(harness, race_pending, label, call):
    """The slow path takes a blocking lock and makes sync network writes; on
    the event-loop thread it would freeze every request on the worker. The
    route body (where the ownership check runs) is on the loop; the row
    write must happen on some other thread."""
    from services.tutor_sessions import require_session_owner as real_check

    threads: dict[str, threading.Thread] = {}

    def check(session_id, user_id):
        threads["loop"] = threading.current_thread()
        return real_check(session_id, user_id)

    def upsert(row, *a, **kw):
        threads["write"] = threading.current_thread()
        return []

    harness["tables"].session_owner = None
    harness["tables"]("sessions").upsert.side_effect = upsert
    harness["tables"]("sessions").insert.side_effect = upsert  # pre-upsert code
    with patch("routes.learn.require_session_owner", side_effect=check):
        call(OWNER, RACE)
    assert RACE not in race_pending, f"{label}: session not materialised"
    assert threads["write"] is not threads["loop"], (
        f"{label}: materialisation ran on the event-loop thread"
    )


@pytest.mark.parametrize("label,call", ASYNC_ROUTES, ids=[r[0] for r in ASYNC_ROUTES])
def test_async_routes_skip_the_threadpool_for_a_ready_session(harness, label, call):
    hop = MagicMock(side_effect=AssertionError("threadpool hop for a ready session"))
    with patch("routes.learn.run_in_threadpool", hop):
        call(OWNER)
    assert not hop.called


# ── Resume racing a concurrent pop ───────────────────────────────────────────

def test_resume_survives_the_pending_entry_vanishing_mid_request(harness):
    """`in` saw the entry, then a concurrent first turn popped it before the
    read: the route must fall through to the DB row, not KeyError into a 500."""

    class _PoppedBetween(dict):
        def __contains__(self, key):
            return True  # the membership test ran before the pop

    with patch("routes.learn.PENDING_SESSIONS", _PoppedBetween()):
        r = _resume(OWNER)
    assert r.status_code == 200, r.text
    assert r.json()["session"]["id"] == SESSION
