"""Tutor routes must check that the session belongs to the caller.

`require_self(body.user_id, request)` only proves the caller IS
`body.user_id`; it says nothing about `body.session_id`. Before this fix a
student holding another student's session UUID could, on /chat,
/chat/stream, /action and /mode-switch, load that student's decrypted
history into the model context and append messages to their session, and
on /end-session close it out (and write its summary).

Every route that takes a session id now goes through
`routes.learn._require_session_owner` first. It answers 404, not 403, for
a session that is missing OR owned by someone else, so ids can't be probed.
"""
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
    inserted = harness["tables"].mocks["sessions"].insert.call_args.args[0]
    assert inserted["id"] == PENDING and inserted["user_id"] == OWNER
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
        from routes.learn import _require_session_owner
        with patch("routes.learn.table", side_effect=_Tables()):
            _require_session_owner(SESSION, OWNER)

    @pytest.mark.parametrize("uid", [INTRUDER, "", None])
    def test_non_owner_raises_404(self, uid):
        from fastapi import HTTPException
        from routes.learn import _require_session_owner
        with patch("routes.learn.table", side_effect=_Tables()):
            with pytest.raises(HTTPException) as exc:
                _require_session_owner(SESSION, uid)
        assert exc.value.status_code == 404

    def test_owner_row_with_null_user_id_is_404(self):
        """A row whose user_id is NULL belongs to nobody — never match it
        against a falsy caller id."""
        from fastapi import HTTPException
        from routes.learn import _require_session_owner
        tables = _Tables()
        tables("sessions").select.return_value = [{"user_id": None}]
        with patch("routes.learn.table", side_effect=tables):
            with pytest.raises(HTTPException) as exc:
                _require_session_owner(SESSION, None)
        assert exc.value.status_code == 404

    def test_pending_owner_passes_without_db_read(self, pending_for_owner):
        from routes.learn import _require_session_owner
        tables = _Tables(session_owner=None)
        with patch("routes.learn.table", side_effect=tables):
            _require_session_owner(PENDING, OWNER)
        assert not tables.touched("sessions", "select")

    def test_reads_sessions_user_id_by_id(self):
        from routes.learn import _require_session_owner
        tables = _Tables()
        with patch("routes.learn.table", side_effect=tables):
            _require_session_owner(SESSION, OWNER)
        call = tables.mocks["sessions"].select.call_args
        assert call.args[0] == "user_id"
        assert call.kwargs["filters"] == {"id": f"eq.{SESSION}"}


def test_a_lost_pop_race_does_not_materialise_the_session_twice():
    """CodeRabbit on #709: two concurrent owner requests both read the pending
    payload; only the one whose pop returns it inserts the session row."""

    class _LostRace(dict):
        def pop(self, key, default=None):  # the other request popped it first
            super().pop(key, default)
            return default

    pending = _LostRace(
        {"s-race": {"user_id": OWNER, "mode": "socratic", "topic": "t",
                    "assistant_reply": "hi", "graph_update": {}}}
    )
    tables = _Tables()
    from routes import learn

    with patch("routes.learn.table", side_effect=tables), \
         patch("routes.learn.PENDING_SESSIONS", pending):
        learn._consume_pending("s-race", OWNER)
    assert not tables.touched("sessions", "insert")
    assert not tables.touched("messages", "insert")
