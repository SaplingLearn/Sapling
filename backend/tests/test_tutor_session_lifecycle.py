"""Tutor session lifecycle (#761): pending -> live -> ended, plus discards.

Pins the state machine routes/learn.py + services/tutor_sessions.py enforce:

* /end-session closes a session at most once (conditional on
  ``ended_at IS NULL``); only the closing call awards XP, emits
  ``session.ended`` and runs the session_* achievements. A repeat returns
  the stored summary and changes nothing.
* Turns (/chat, /chat/stream, /action, /mode-switch) on an ended session
  answer 409 with the typed code ``SESSION_ENDED``.
* /mode-switch persists ``sessions.mode``.
* PENDING_SESSIONS is bounded (TTL + size cap) and a discard leaves a
  tombstone, so a turn racing end/delete gets 409/404 instead of writing
  messages for a session row that will never exist.
* A ``turn_id`` makes a turn's writes idempotent and lets a re-send of an
  already-persisted turn replay instead of running twice.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import routes.learn as learn
from main import app
from services import tutor_sessions
from services.encryption import encrypt_if_present, encrypt_json
from tests.agent_run_fakes import run_result
from tests.db_fakes import with_async_twins
from tests.split_patches import patch_tutor

#: #117 wave 3: a sync PostgREST call on the event loop raises here.
pytestmark = pytest.mark.usefixtures("no_sync_db_on_loop")


client = TestClient(app)

USER = "user_life"
SESSION = "sess-life"
STARTED = "2026-01-01T10:00:00+00:00"
ENDED = "2026-01-01T10:45:00+00:00"


class _Tables:
    """Hermetic table() factory with a mutable sessions row."""

    def __init__(self, *, ended_at=None, row=True, close_wins=True, summary_json=None):
        self.row = (
            {
                "id": SESSION, "user_id": USER, "offering_id": None,
                "topic": "Recursion", "mode": "socratic",
                "started_at": STARTED, "ended_at": ended_at,
                "summary_json": summary_json,
            }
            if row else None
        )
        self.close_wins = close_wins
        self.message_rows: list[dict] = []
        self.mocks: dict[str, MagicMock] = {}

    def __call__(self, name):
        if name in self.mocks:
            return self.mocks[name]
        m = MagicMock(name=f"table({name})")
        if name == "sessions":
            m.select.side_effect = lambda *a, **k: [dict(self.row)] if self.row else []

            def update(data, filters, **_k):
                if "ended_at" in data:
                    return [{"id": SESSION}] if self.close_wins else []
                return [{"id": SESSION}]

            m.update.side_effect = update
        elif name == "messages":
            m.select.side_effect = lambda *a, **k: list(self.message_rows)
        else:
            m.select.return_value = []
        for meth in ("insert", "upsert", "delete"):
            getattr(m, meth).return_value = []
        self.mocks[name] = m
        return m

    def called(self, name: str, method: str) -> bool:
        m = self.mocks.get(name)
        return bool(m and getattr(m, method).called)


@pytest.fixture
def h():
    tables = _Tables()
    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("A tutor reply."))
    with (
        patch_tutor("table", side_effect=with_async_twins(lambda n: tables(n))),
        patch_tutor("agent_for_mode", return_value=agent),
        patch_tutor("get_display_name", return_value="Life Student"),
        patch("services.events_service.log_event") as log_event,
        patch_tutor("award_xp_safe") as award,
        patch_tutor("touch_streak_safe") as streak,
        patch_tutor("offering_course_id", return_value=""),
        patch("services.achievement_service.check_achievements", return_value=[]) as ach,
    ):
        yield {
            "tables": tables, "agent": agent, "log_event": log_event,
            "award": award, "streak": streak, "ach": ach,
        }
    learn.PENDING_SESSIONS.pop(SESSION, None)


def _end():
    return client.post("/api/learn/end-session", json={"session_id": SESSION, "user_id": USER})


def _events(h, name):
    return [c for c in h["log_event"].call_args_list if c.args and c.args[0] == name]


# ── end-session: at most one close ───────────────────────────────────────────

def test_end_is_conditional_on_the_session_being_open(h):
    r = _end()
    assert r.status_code == 200, r.text
    update = h["tables"].mocks["sessions"].update
    end_call = next(c for c in update.call_args_list if "ended_at" in c.args[0])
    assert end_call.kwargs["filters"] == {"id": f"eq.{SESSION}", "ended_at": "is.null"}
    h["award"].assert_called_once()
    assert len(_events(h, "session.ended")) == 1
    assert h["ach"].called


def test_repeat_end_awards_nothing_and_returns_the_stored_summary(h):
    stored = {
        "concepts_covered": ["Recursion"], "mastery_changes": [],
        "new_connections": [], "time_spent_minutes": 45, "recommended_next": [],
    }
    h["tables"].row.update(ended_at=ENDED, summary_json=encrypt_json(stored))
    h["tables"].close_wins = False

    r = _end()

    assert r.status_code == 200, r.text
    assert r.json() == {"summary": stored, "achievements_earned": []}
    h["award"].assert_not_called()
    h["streak"].assert_not_called()
    h["ach"].assert_not_called()
    assert _events(h, "session.ended") == []
    writes = [c.args[0] for c in h["tables"].mocks["sessions"].update.call_args_list]
    assert not any("summary_json" in w for w in writes), "a repeat must not rewrite the summary"


def test_repeat_end_before_the_summary_landed_recomputes_from_stored_ended_at(h):
    """The closing call writes summary_json AFTER ended_at; a repeat in that
    gap recomputes — up to the STORED ended_at, not 'now' — and writes nothing."""
    h["tables"].row.update(ended_at=ENDED, summary_json=None)
    h["tables"].close_wins = False
    r = _end()
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["time_spent_minutes"] == 45
    h["award"].assert_not_called()


def test_ending_a_pending_session_twice_is_idempotent_and_turns_then_409(h):
    h["tables"].row = None  # pending: no row yet
    tutor_sessions.stash_pending(SESSION, {
        "user_id": USER, "mode": "socratic", "topic": "T", "offering_id": None,
        "assistant_reply": "Hi!", "graph_update": {},
    })
    first, second = _end(), _end()
    assert first.status_code == 200 and second.status_code == 200, second.text
    assert first.json()["summary"] == second.json()["summary"]
    h["award"].assert_not_called()

    r = client.post("/api/learn/chat", json={
        "session_id": SESSION, "user_id": USER, "message": "hi",
    })
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "SESSION_ENDED"
    assert not h["agent"].run.called
    assert not h["tables"].called("messages", "insert")


# ── turns on an ended session → 409 SESSION_ENDED ────────────────────────────

TURNS = [
    ("chat", "/api/learn/chat", {"message": "hi"}),
    ("chat_stream", "/api/learn/chat/stream", {"message": "hi"}),
    ("action", "/api/learn/action", {"action_type": "hint"}),
    ("mode_switch", "/api/learn/mode-switch", {"new_mode": "expository"}),
]


@pytest.mark.parametrize("label,path,extra", TURNS, ids=[t[0] for t in TURNS])
def test_turns_on_an_ended_session_answer_409(h, label, path, extra):
    h["tables"].row["ended_at"] = ENDED
    r = client.post(path, json={"session_id": SESSION, "user_id": USER, **extra})
    assert r.status_code == 409, f"{label}: {r.status_code} {r.text}"
    body = r.json()
    assert body["error"]["code"] == "SESSION_ENDED"
    assert body["detail"] == tutor_sessions.SESSION_ENDED_MESSAGE  # legacy key kept
    assert not h["agent"].run.called
    assert not h["tables"].called("messages", "insert")
    assert not h["tables"].called("messages", "upsert")
    writes = [c.args[0] for c in h["tables"].mocks["sessions"].update.call_args_list]
    assert not any("mode" in w for w in writes)


# ── mode-switch persists the mode ────────────────────────────────────────────

def test_mode_switch_persists_sessions_mode(h):
    r = client.post("/api/learn/mode-switch", json={
        "session_id": SESSION, "user_id": USER, "new_mode": "teachback",
    })
    assert r.status_code == 200, r.text
    update = h["tables"].mocks["sessions"].update
    mode_call = next(c for c in update.call_args_list if "mode" in c.args[0])
    assert mode_call.args[0] == {"mode": "teachback"}
    assert mode_call.kwargs["filters"] == {"id": f"eq.{SESSION}", "ended_at": "is.null"}


def test_mode_switch_refuses_an_unknown_mode_before_writing(h):
    r = client.post("/api/learn/mode-switch", json={
        "session_id": SESSION, "user_id": USER, "new_mode": "freestyle",
    })
    assert r.status_code == 422
    assert not h["tables"].called("sessions", "update")
    assert not h["tables"].called("messages", "insert")


# ── PENDING_SESSIONS bounds ─────────────────────────────────────────────────

@pytest.fixture
def clean_pending():
    saved = dict(tutor_sessions.PENDING_SESSIONS)
    tutor_sessions.PENDING_SESSIONS.clear()
    yield tutor_sessions.PENDING_SESSIONS
    tutor_sessions.PENDING_SESSIONS.clear()
    tutor_sessions.PENDING_SESSIONS.update(saved)


def test_pending_entries_expire_after_the_ttl(clean_pending, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(tutor_sessions, "_now", lambda: clock[0])
    tutor_sessions.stash_pending("old", {"user_id": "u"})
    clock[0] += tutor_sessions.PENDING_TTL_SECONDS + 1
    tutor_sessions.stash_pending("new", {"user_id": "u"})
    assert list(clean_pending) == ["new"]


def test_pending_entries_are_capped_oldest_first(clean_pending, monkeypatch):
    monkeypatch.setattr(tutor_sessions, "PENDING_MAX_ENTRIES", 3)
    for sid in ("a", "b", "c", "d", "e"):
        tutor_sessions.stash_pending(sid, {"user_id": "u"})
    assert list(clean_pending) == ["c", "d", "e"]


def test_tombstones_expire(monkeypatch):
    clock = [5000.0]
    monkeypatch.setattr(tutor_sessions, "_now", lambda: clock[0])
    tutor_sessions.discard_pending("gone", user_id="u", reason="deleted")
    assert tutor_sessions.discarded_reason("gone", "u") == "deleted"
    assert tutor_sessions.discarded_reason("gone", "someone-else") is None
    clock[0] += tutor_sessions.DISCARD_TOMBSTONE_TTL_SECONDS + 1
    assert tutor_sessions.discarded_reason("gone", "u") is None


# ── a turn racing end/delete of a pending session ───────────────────────────

@pytest.mark.parametrize("reason,status", [("ended", 409), ("deleted", 404)])
def test_turn_racing_a_discard_does_not_write_for_a_missing_row(h, reason, status):
    """The turn's ownership check sees the pending entry; the discard lands
    before materialisation. Before #761 the turn then took the 'not pending,
    so the row exists' fast path and wrote messages for a row that never
    would exist (an FK failure → 500)."""
    h["tables"].row = None
    tutor_sessions.stash_pending(SESSION, {
        "user_id": USER, "mode": "socratic", "topic": "T", "offering_id": None,
        "assistant_reply": "Hi!", "graph_update": {},
    })
    real_owner_check = tutor_sessions.arequire_session_owner

    async def owner_check_then_discard(session_id, user_id, **kw):
        await real_owner_check(session_id, user_id, **kw)  # passes: still pending
        with tutor_sessions.materialization_lock(session_id):
            tutor_sessions.discard_pending(session_id, user_id=user_id, reason=reason)

    with patch_tutor("arequire_session_owner", side_effect=owner_check_then_discard):
        r = client.post("/api/learn/chat", json={
            "session_id": SESSION, "user_id": USER, "message": "hi",
        })
    assert r.status_code == status, r.text
    assert not h["agent"].run.called
    assert not h["tables"].called("messages", "insert")
    assert not h["tables"].called("sessions", "upsert")


def test_delete_leaves_a_tombstone_that_stops_an_inflight_write(h):
    r = client.delete(f"/api/learn/sessions/{SESSION}", params={"user_id": USER})
    assert r.status_code == 200
    with pytest.raises(Exception) as exc:
        asyncio.run(learn.save_message(SESSION, "assistant", "late reply"))
    assert getattr(exc.value, "status_code", None) == 404


# ── turn ids: idempotent writes, replay of a persisted turn ─────────────────

TURN = "turn-0001-abcd"


def test_turn_id_makes_both_writes_idempotent_upserts(h):
    r = client.post("/api/learn/chat", json={
        "session_id": SESSION, "user_id": USER, "message": "hi", "turn_id": TURN,
    })
    assert r.status_code == 200, r.text
    upserts = h["tables"].mocks["messages"].upsert.call_args_list
    ids = [c.args[0]["id"] for c in upserts]
    assert ids == [
        learn._turn_message_id(SESSION, TURN, "user"),
        learn._turn_message_id(SESSION, TURN, "assistant"),
    ]
    assert all(c.kwargs == {"on_conflict": "id", "ignore_duplicates": True} for c in upserts)
    assert not h["tables"].called("messages", "insert")


def test_turn_message_ids_are_session_scoped():
    assert learn._turn_message_id("s1", TURN, "user") != learn._turn_message_id("s2", TURN, "user")


def test_resent_persisted_turn_replays_instead_of_running_again(h):
    h["tables"].message_rows = [{
        "id": learn._turn_message_id(SESSION, TURN, "assistant"),
        "role": "assistant",
        "content": encrypt_if_present("The stored reply."),
        "graph_update_json": {"new_nodes": [{"concept_name": "Recursion"}]},
    }]
    r = client.post("/api/learn/chat", json={
        "session_id": SESSION, "user_id": USER, "message": "hi", "turn_id": TURN,
    })
    assert r.status_code == 200, r.text
    assert r.json()["reply"] == "The stored reply."
    assert r.json()["replayed"] is True
    assert not h["agent"].run.called, "a persisted turn must never run twice"
    assert not h["tables"].called("messages", "upsert")


def test_resent_persisted_turn_replays_on_the_stream_route(h):
    h["tables"].message_rows = [{
        "id": learn._turn_message_id(SESSION, TURN, "assistant"),
        "role": "assistant",
        "content": encrypt_if_present("The stored reply."),
        "graph_update_json": None,
    }]
    with patch_tutor("stream_agent_turn") as stream:
        r = client.post("/api/learn/chat/stream", json={
            "session_id": SESSION, "user_id": USER, "message": "hi", "turn_id": TURN,
        })
    assert r.status_code == 200, r.text
    stream.assert_not_called()
    events = [
        json.loads(line[len("data:"):].strip())
        for line in r.text.splitlines() if line.startswith("data:")
    ]
    assert [e["type"] for e in events] == ["status", "token", "done"]
    assert events[1]["data"]["delta"] == "The stored reply."
    assert events[2]["data"]["reply"] == "The stored reply."


def test_retry_history_skips_the_orphan_user_row_of_its_own_turn(h):
    user_id = learn._turn_message_id(SESSION, TURN, "user")
    h["tables"].message_rows = [
        {"id": "m0", "role": "assistant", "content": encrypt_if_present("Earlier.")},
        {"id": user_id, "role": "user", "content": encrypt_if_present("hi")},
    ]
    history = asyncio.run(learn._load_message_history(SESSION, exclude_id=user_id))
    assert len(history) == 1


def test_turn_id_rejects_unsafe_values(h):
    r = client.post("/api/learn/chat", json={
        "session_id": SESSION, "user_id": USER, "message": "hi", "turn_id": "x",
    })
    assert r.status_code == 422


# ── partial persistence on the stream ───────────────────────────────────────

def _stream_with_failing_assistant_write(h, body_extra):
    h["tables"].mocks.pop("messages", None)
    msgs = h["tables"]("messages")

    def fail_assistant(row, *a, **k):
        if row["role"] == "assistant":
            raise RuntimeError("db write failed")
        return []

    msgs.insert.side_effect = fail_assistant
    msgs.upsert.side_effect = fail_assistant

    async def fake_run_stream_events(*_a, **_k):
        from pydantic_ai.messages import PartStartEvent, TextPart
        yield PartStartEvent(index=0, part=TextPart(content="Streamed reply."))

    h["agent"].run_stream_events = fake_run_stream_events
    r = client.post("/api/learn/chat/stream", json={
        "session_id": SESSION, "user_id": USER, "message": "hi", **body_extra,
    })
    assert r.status_code == 200, r.text
    events = [
        json.loads(line[len("data:"):].strip())
        for line in r.text.splitlines() if line.startswith("data:")
    ]
    assert events[-1]["type"] == "error", events
    return events[-1]


def test_partial_persist_without_turn_id_is_not_retryable(h):
    """The user row landed; a retry without a turn id would write it again."""
    err = _stream_with_failing_assistant_write(h, {})
    assert err["data"]["retryable"] is False


def test_partial_persist_with_turn_id_stays_retryable(h):
    """With a turn id the retry re-writes the same user row id (ignored as a
    duplicate), so retrying is safe."""
    err = _stream_with_failing_assistant_write(h, {"turn_id": TURN})
    assert err["data"]["retryable"] is True


def test_streamed_persist_off_loop_still_schedules_the_router_on_the_loop(h):
    """_persist now runs in a worker thread; the #640 router schedules an
    asyncio task, so it must be handed back to the loop, not silently dropped
    (observe_tutor_turn swallows a missing running loop)."""
    import asyncio

    seen = []

    def spy(**kw):
        try:
            asyncio.get_running_loop()
            seen.append("loop")
        except RuntimeError:
            seen.append("no-loop")

    async def fake_run_stream_events(*_a, **_k):
        from pydantic_ai.messages import PartStartEvent, TextPart
        yield PartStartEvent(index=0, part=TextPart(content="Streamed reply."))

    h["agent"].run_stream_events = fake_run_stream_events
    with patch_tutor("observe_tutor_turn", side_effect=spy):
        r = client.post("/api/learn/chat/stream", json={
            "session_id": SESSION, "user_id": USER, "message": "hi",
        })
    assert r.status_code == 200 and '"done"' in r.text, r.text
    assert seen == ["loop"]


# ── error envelope ──────────────────────────────────────────────────────────

def test_error_content_adds_the_error_object_only_for_coded_non_quiz_errors():
    from services.quiz.errors import error_content
    assert error_content("/api/learn/chat", 404, "Session not found", "rid") == {
        "detail": "Session not found", "request_id": "rid",
    }
    assert error_content(
        "/api/learn/chat", 409, "ended", "rid", code="SESSION_ENDED",
    ) == {
        "detail": "ended", "request_id": "rid",
        "error": {"code": "SESSION_ENDED", "message": "ended", "request_id": "rid"},
    }
