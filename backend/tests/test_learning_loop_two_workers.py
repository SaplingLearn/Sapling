"""#117: a learning-loop session survives more than one worker.

With `stateless_tutor_sessions` on, no learning-loop state may live only in
one process's memory: a loop session started on one worker is answered,
materialised, closed or refused by any other, and a failed turn's timing
anchor is read by every worker. Each test runs its requests on two simulated
workers (`Worker`), each with its OWN copy of every module-level map the loop
and its pending-session store keep across requests, swapped in for the
request it serves; "the database" (the pending store fake of
tests/test_tutor_sessions_store.py, which mirrors the SQL functions, and the
loop routes' compare-and-set loop-state fake) is shared, as Postgres is.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from learning import turn_activity
from learning.ladder import Rung
from routes import learn_loop
from services import tutor_sessions as ts
from services.encryption import decrypt_if_present
from services.tutor import pending as tutor_pending
from tests import test_learn_loop_routes as routes
from tests.split_patches import patch_tutor
from tests.test_learning_teach_attempt import CLAIM
from tests.test_quiz_ask_session import _opener
from tests.test_tutor_sessions_store import _FakeDB
from tests.split_patches import patch_loop
import services.loop.history

client = routes.client
gate_on, no_rate_limit, seams = routes.gate_on, routes.no_rate_limit, routes.seams
NOW = routes.NOW
UID, OTHER = "u1", "u-other"

#: Every module-level map the learning loop (and the pending-session store it
#: rides) keeps across requests. A worker's request sees only its own.
_PROCESS_MAPS = (
    (ts, "PENDING_SESSIONS"),
    (ts, "_DISCARDED"),
    (services.loop.history, "_BRIEF_FAILED"),
    (learn_loop, "_DUE_CACHE"),
)


class Worker:
    """One API worker's process memory."""

    def __init__(self) -> None:
        self.memory: dict[str, dict] = {name: {} for _, name in _PROCESS_MAPS}

    @contextmanager
    def serving(self):
        """Serve the requests in the block on this worker: its maps are swapped
        in (the modules hold the dicts by reference, so they change in place),
        and swapped back out afterwards."""
        outside = {}
        for module, name in _PROCESS_MAPS:
            live = getattr(module, name)
            outside[name] = dict(live)
            live.clear()
            live.update(self.memory[name])
        try:
            yield self
        finally:
            for module, name in _PROCESS_MAPS:
                live = getattr(module, name)
                self.memory[name] = dict(live)
                live.clear()
                live.update(outside[name])

    def held(self) -> dict:
        """The non-empty maps this worker holds after its requests."""
        return {name: m for name, m in self.memory.items() if m}


@pytest.fixture
def db(monkeypatch):
    """The shared pending store (flag on), with `session.started` captured."""
    monkeypatch.setenv("SAPLING_FLAG_STATELESS_TUTOR_SESSIONS", "on")
    fake = _FakeDB()

    async def arpc(fn, p, **k):
        return fake.rpc(fn, p, **k)

    from services import events_service

    # Through monkeypatch (LIFO with any later monkeypatch of the same name,
    # e.g. _wire_close's), never a `patch` context: mixing the two would
    # restore this mock for good at teardown.
    fake.log_event = MagicMock()
    monkeypatch.setattr(events_service, "log_event", fake.log_event)
    with (
        patch("services.tutor_sessions.table", side_effect=fake.table),
        patch("services.tutor_sessions.rpc", side_effect=fake.rpc),
        patch("services.tutor_sessions.arpc", side_effect=arpc),
        patch_tutor("table", side_effect=fake.table),
    ):
        yield fake


def _started(db) -> list:
    return [c for c in db.log_event.call_args_list if c.args[0] == "session.started"]


def _loop_payload(*, user_id=UID, loop_state=None) -> dict:
    """What `_LoopOpener.complete` stashes (routes/learn_loop.py)."""
    payload = {
        "user_id": user_id,
        "mode": "socratic",
        "topic": "Recursion",
        "course_id": "c1",
        "offering_id": "off-1",
        "use_shared_context": True,
        "assistant_reply": "Welcome. Let's start with a quick check-in.",
        "graph_update": {},
        "loop": True,
    }
    if loop_state:
        payload["loop_state"] = loop_state
    return payload


# ── start on one worker, continue on the other ───────────────────────────────


def test_a_quiz_ask_session_started_on_one_worker_continues_on_the_other(gate_on, seams, db):
    """The quiz's "Ask about this" session (spec §13 A99) starts in `teach` on the
    quiz's concept: that document must reach the row the OTHER worker writes."""
    from routes.learn_loop import quiz_ask_state

    a, b = Worker(), Worker()
    opener, _ = routes._json_agent("Key idea: the base case. Which input stops it?")
    with a.serving():
        r, record = _opener("/api/learn/loop/start-session", agent=opener)
    assert r.status_code == 200, r.text
    sid, greeting = r.json()["session_id"], r.json()["initial_message"]
    record.assert_called_once()  # the help row (A93) is durable before any text
    assert a.held() == {}, "flag on: nothing pending in worker A's memory"
    doc = {**quiz_ask_state("node-1"), "open_question": True}
    row = db.store(sid)
    assert row["state"] == "pending" and row["loop_state"] == doc
    assert row["assistant_reply"] != greeting and decrypt_if_present(row["assistant_reply"]) == greeting
    assert db.rows["sessions"] == [], "still lazy: no sessions row before the first loop write"

    with b.serving():
        status = client.get(f"/api/learn/loop/status?user_id={UID}&session_id={sid}")
        foreign = client.get(f"/api/learn/loop/status?user_id={OTHER}&session_id={sid}")
    assert status.status_code == 200, status.text
    assert status.json()["phase"] == "teach", "worker B reads the pending document"
    assert foreign.status_code == 404
    seams.load.assert_not_called()

    seams.store["doc"] = copy.deepcopy(doc)  # sessions.loop_state, once materialised
    turn, _ = routes._json_agent("Right. What does factorial(0) return?")
    with (
        b.serving(),
        patch_loop("loop_tutor_agent", turn),
        patch_loop("record_agent_usage", side_effect=lambda r, **k: r),
    ):
        r = client.post(
            "/api/learn/loop/chat", json={"session_id": sid, "user_id": UID, "message": "n == 0"}
        )
    assert r.status_code == 200, r.text
    assert [s["id"] for s in db.rows["sessions"]] == [sid]
    assert db.rows["sessions"][0]["loop_state"] == doc, "the row keeps the session's document"
    assert db.rows["sessions"][0]["offering_id"] == row["offering_id"]
    assert [(m["role"], decrypt_if_present(m["content"])) for m in db.rows["messages"]] == [
        ("assistant", greeting)
    ]
    assert db.store(sid) is None, "materialised: the pending row is gone"
    assert len(_started(db)) == 1
    assert a.held() == {} and b.held() == {}


def test_a_probe_session_materialises_on_the_other_worker_through_the_sync_entry(db):
    """The probe/plan/goal routes materialise through the sync `_consume_pending`
    (threadpool). A probe session starts with an empty document: it is stored as
    `{}` (a loop session) and written as the row's default."""
    a, b = Worker(), Worker()
    with a.serving():
        ts.stash_pending("s-probe", _loop_payload())
    assert a.held() == {} and db.store("s-probe")["loop_state"] == {}
    with b.serving():
        pending = ts.get_pending("s-probe")
        assert pending["loop"] is True and "loop_state" not in pending, "reads back as stashed"
        with pytest.raises(Exception) as foreign:
            tutor_pending._consume_pending("s-probe", OTHER)
        assert getattr(foreign.value, "status_code", None) == 404
        assert tutor_pending._consume_pending("s-probe", UID) is True
        assert tutor_pending._consume_pending("s-probe", UID) is False, "the loser of a race"
    assert db.rows["sessions"][0]["loop_state"] == {}
    assert len(db.rows["messages"]) == 1 and len(_started(db)) == 1
    with a.serving():
        assert tutor_pending._consume_pending("s-probe", UID) is False, "live on every worker"
    assert len(db.rows["sessions"]) == 1 and a.held() == {} and b.held() == {}


def test_a_goal_session_keeps_its_encrypted_goal_across_workers(db):
    from learning.goals import encode_goal
    from models import LoopGoal

    goal = encode_goal(LoopGoal(text="Prepare for my private internship", target_node_ids=["B"]))
    state = {"goal": goal, "goal_version": 1}
    a, b = Worker(), Worker()
    with a.serving():
        ts.stash_pending("s-goal", _loop_payload(loop_state=state))
    assert "private internship" not in repr(db.store("s-goal")), "the goal text is ciphertext"
    with b.serving():
        assert ts.get_pending("s-goal")["loop_state"] == state
        assert tutor_pending._consume_pending("s-goal", UID) is True
    assert db.rows["sessions"][0]["loop_state"] == state


# ── end, close and refuse on the other worker ───────────────────────────────


@pytest.mark.parametrize("reason,status", [("ended", 409), ("deleted", 404)])
def test_a_loop_session_discarded_on_one_worker_is_refused_on_the_other(
    gate_on, seams, db, reason, status
):
    a, b = Worker(), Worker()
    with a.serving():
        ts.stash_pending("s-end", _loop_payload(loop_state={"phase": "teach"}))
        assert ts.discard_if_pending("s-end", user_id=UID, reason=reason) == {}
    assert db.store("s-end")["state"] == reason and db.store("s-end")["loop_state"] is None
    turn = MagicMock()
    turn.run = AsyncMock(side_effect=AssertionError("no turn runs on a discarded session"))
    with b.serving(), patch_loop("loop_tutor_agent", turn):
        r = client.post(
            "/api/learn/loop/chat", json={"session_id": "s-end", "user_id": UID, "message": "hi"}
        )
    assert r.status_code == status, r.text
    if reason == "ended":
        assert r.json()["error"]["code"] == ts.SESSION_ENDED_CODE
    assert db.rows["sessions"] == [] and db.rows["messages"] == []


def test_another_students_loop_session_is_404_on_the_other_worker_and_left_intact(
    gate_on, seams, db
):
    a, b = Worker(), Worker()
    with a.serving():
        ts.stash_pending("s-mine", _loop_payload(loop_state={"phase": "teach"}))
    with b.serving():
        r = client.post(
            "/api/learn/loop/chat", json={"session_id": "s-mine", "user_id": OTHER, "message": "hi"}
        )
    assert r.status_code == 404
    assert db.store("s-mine")["state"] == "pending" and db.rows["sessions"] == []


def test_a_never_answered_loop_session_closes_on_the_other_worker(monkeypatch, db):
    """`/close` of a session nobody answered in (Behaviour 10): the payload is
    claimed — taken away in one atomic call — and the close writes the row
    itself, with no greeting and no `session.started`, exactly as from memory."""
    from tests.test_learning_close_brief import _wire_close

    tables, events, _ = _wire_close(monkeypatch, session=False)
    a, b = Worker(), Worker()
    with a.serving():
        ts.stash_pending("s-close", _loop_payload(loop_state={"phase": "probe"}))
    with b.serving():
        foreign = client.post("/api/learn/loop/close", json={"session_id": "s-close", "user_id": OTHER})
        r = client.post("/api/learn/loop/close", json={"session_id": "s-close", "user_id": UID})
    assert foreign.status_code == 404
    assert r.status_code == 200, r.text
    assert r.json()["close_phase"] == "close"
    assert db.store("s-close") is None, "claimed: the pending row is gone"
    assert tables.writes("insert", "sessions")[0][2] == {
        "id": "s-close",
        "user_id": UID,
        "mode": "socratic",
        "topic": "Recursion",
        "offering_id": "off-1",
    }
    assert [e for e, _ in events] == ["learn.session_closed"]
    with a.serving():
        assert ts.claim_pending("s-close", UID) is None, "a second close finds nothing pending"
    assert db.rows["messages"] == []


def test_a_claim_has_one_winner():
    fake = _FakeDB()
    with (
        patch.dict("os.environ", {"SAPLING_FLAG_STATELESS_TUTOR_SESSIONS": "on"}),
        patch("services.tutor_sessions.table", side_effect=fake.table),
        patch("services.tutor_sessions.rpc", side_effect=fake.rpc),
    ):
        ts.stash_pending("s-claim", _loop_payload(loop_state={"phase": "probe"}))
        first = ts.claim_pending("s-claim", UID)
        assert first["loop_state"] == {"phase": "probe"} and first["topic"] == "Recursion"
        assert ts.claim_pending("s-claim", UID) is None
        assert fake.rpc("materialize_tutor_session", {
            "p_session_id": "s-claim", "p_user_id": UID, "p_ttl_seconds": ts.PENDING_TTL_SECONDS,
            "p_tombstone_ttl_seconds": ts.DISCARD_TOMBSTONE_TTL_SECONDS, "p_created_at": None,
        }) == [{"outcome": "none"}], "a claimed session is never materialised after"
    assert "s-claim" not in ts.PENDING_SESSIONS


# ── a failed turn's timing anchor ────────────────────────────────────────────


def test_a_failure_on_one_worker_times_the_retry_on_the_other(gate_on, seams):
    """Spec §13 A85: a retry right after a failed turn is timed from the failure,
    so it can never pass the independent-time gate on the strength of the lost
    turn — on whichever worker the retry lands (#117: the anchor is in the loop
    document, not a per-process cache)."""
    seams.store["doc"] = routes._plan_state(served_at=NOW - 600.0)
    seams.p_known["node-1"] = 0.99  # profic: a teach attempt would raise H1 -> H3
    broken = MagicMock()

    async def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    broken.run = fail
    a, b = Worker(), Worker()
    with a.serving(), patch_loop("loop_tutor_agent", broken):
        r = client.post(
            "/api/learn/loop/chat", json={"session_id": "s1", "user_id": UID, "message": CLAIM}
        )
    assert r.status_code >= 500
    assert turn_activity.failed_at(seams.store["doc"]) == NOW
    assert a.held() == {}, "nothing about the failure stays in worker A's memory"

    agent, _ = routes._json_agent("You looked at the numerator only.")
    with (
        b.serving(),
        patch_loop("loop_tutor_agent", agent),
        patch_loop("record_agent_usage", side_effect=lambda r, **k: r),
    ):
        r = client.post(
            "/api/learn/loop/chat", json={"session_id": "s1", "user_id": UID, "message": CLAIM}
        )
    assert r.status_code == 200, r.text
    assert r.json()["ceiling"] == int(Rung.H1), "timed from the failure, not the old served turn"
    assert not seams.ceiling.call_args.kwargs.get("teach_attempt")


def test_a_turn_whose_activity_marker_never_landed_still_leaves_the_anchor(gate_on, seams):
    """The stream's first write (the pending activity marker) fails: no model
    runs, and the failure anchor is still written durably (it used to be only
    in the failing worker's memory), so the other worker times from it."""
    seams.store["doc"] = routes._plan_state(served_at=NOW - 600.0)
    real_save = seams.save.side_effect
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("storage blip")
        return real_save(*args, **kwargs)

    seams.save.side_effect = flaky
    model = MagicMock(side_effect=AssertionError("no AI before the activity marker lands"))
    with Worker().serving(), patch_loop("stream_structured_turn", model):
        r = client.post(
            "/api/learn/loop/chat/stream", json={"session_id": "s1", "user_id": UID, "message": CLAIM}
        )
    assert [e["type"] for e in routes._sse_events(r.text)] == ["error"]
    model.assert_not_called()
    assert turn_activity.KEY not in seams.store["doc"], "the marker never landed"
    assert turn_activity.failed_at(seams.store["doc"]) == NOW


def test_the_failure_anchor_only_moves_forward_and_fences_a_newer_turn():
    doc: dict = {}
    turn_activity.begin(doc, "newer", NOW)
    turn_activity.fail(doc, "older", NOW - 10)  # an old cancellation
    assert doc[turn_activity.KEY] == {"id": "newer", "state": "pending", "at": NOW}
    assert turn_activity.failed_at(doc) == NOW - 10
    turn_activity.fail(doc, "newer", NOW + 5)
    assert doc[turn_activity.KEY]["state"] == "interrupted"
    turn_activity.fail(doc, "older", NOW - 100)
    assert turn_activity.failed_at(doc) == NOW + 5, "never moved back"
    assert turn_activity.failed_at({turn_activity.FAILED_KEY: float("nan")}) is None
    assert turn_activity.failed_at({turn_activity.FAILED_KEY: True}) is None


# ── flag off: the in-memory store, as before ─────────────────────────────────


def test_flag_off_keeps_the_loop_session_in_the_starting_workers_memory(
    gate_on, seams, db, monkeypatch
):
    """The flag is the multi-worker switch: off, a loop session is pending in the
    starting worker's memory and the table is never touched (one worker is the
    supported shape then, as before #117)."""
    from routes.learn_loop import quiz_ask_state

    monkeypatch.setenv("SAPLING_FLAG_STATELESS_TUTOR_SESSIONS", "off")
    a = Worker()
    opener, _ = routes._json_agent("Key idea: the base case. Which input stops it?")
    with a.serving():
        r, _ = _opener("/api/learn/loop/start-session", agent=opener)
        sid = r.json()["session_id"]
        assert tutor_pending._consume_pending(sid, UID) is True
    assert r.status_code == 200
    assert db.rpcs == [] and "tutor_pending_sessions" not in db.touched
    assert db.rows["sessions"][0]["loop_state"] == {**quiz_ask_state("node-1"), "open_question": True}
    assert a.held() == {}, "materialised: the memory entry is gone"
