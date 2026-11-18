"""#117: lazy tutor sessions that survive two API replicas.

With `stateless_tutor_sessions` on, a pending session and its end/delete
tombstone live in `tutor_pending_sessions` (services/tutor_sessions.py), so a
session started on one replica can be continued, ended or deleted on the
other. Each test wipes the process-local store between steps (`_replica_hop`)
to stand in for "the next request landed on the other replica".

The fake below mirrors the three SQL functions of
20261109024225_tutor_pending_sessions.sql (with the loop document of
20261111030007_tutor_pending_loop_state.sql); tests/integration/
test_tutor_pending_sessions_db.py pins the SQL itself against Postgres.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services import tutor_sessions as ts
from services.encryption import bind, decrypt_if_present
from tests.agent_run_fakes import run_result
from tests.db_fakes import add_async_twins
from tests.split_patches import patch_tutor

#: #117 wave 3: a sync PostgREST call on the event loop raises here. Spec §11.5
#: (learning loop PKG-14b): these drive the legacy /api/learn/* tutor, so they
#: run as kill-switch tests (with the loop on, the routes hand the turn to it).
pytestmark = [pytest.mark.kill_switch, pytest.mark.usefixtures("no_sync_db_on_loop")]

client = TestClient(app)

USER, OTHER = "user_store", "user_other"
GREETING = "Welcome! What do you know about recursion?"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _match(row: dict, filters: dict) -> bool:
    for col, cond in (filters or {}).items():
        op, _, val = cond.partition(".")
        cur = row.get(col)
        if op == "eq" and (cur is None or str(cur) != val):
            return False
        if op == "is" and val == "null" and cur is not None:
            return False
        if op == "gte" and (cur is None or datetime.fromisoformat(cur) < datetime.fromisoformat(val)):
            return False
    return True


class _FakeDB:
    """tutor_pending_sessions + sessions + messages, and the three functions."""

    def __init__(self):
        self.rows: dict[str, list[dict]] = {
            "tutor_pending_sessions": [], "sessions": [], "messages": [],
        }
        self.rpcs: list[str] = []
        self.touched: set[str] = set()
        self.reads: list[str] = []

    # ── table() ──
    def table(self, name):
        self.touched.add(name)
        rows = self.rows.setdefault(name, [])
        m = MagicMock(name=f"table({name})")

        def select(_cols="*", filters=None, limit=None, **_k):
            self.reads.append(name)
            out = [dict(r) for r in rows if _match(r, filters)]
            return out[:limit] if limit else out

        def update(data, filters=None, **_k):
            hit = [r for r in rows if _match(r, filters)]
            for r in hit:
                r.update(data)
            return [dict(r) for r in hit]

        def _with_defaults(row):
            if name == "sessions":  # the column defaults the table has
                return {"started_at": _now().isoformat(), "ended_at": None, **row}
            return dict(row)

        def insert(row, **_k):
            rows.extend(_with_defaults(r) for r in (row if isinstance(row, list) else [row]))
            return []

        def upsert(row, on_conflict="id", **_k):
            if not any(r.get(on_conflict) == row.get(on_conflict) for r in rows):
                rows.append(_with_defaults(row))
            return []

        def delete(filters=None, **_k):
            gone = [dict(r) for r in rows if _match(r, filters)]  # Prefer: return=representation
            rows[:] = [r for r in rows if not _match(r, filters)]
            return gone

        m.select.side_effect = select
        m.update.side_effect = update
        m.insert.side_effect = insert
        m.upsert.side_effect = upsert
        m.delete.side_effect = delete
        return add_async_twins(m)

    def store(self, sid=None) -> dict | None:
        rows = self.rows["tutor_pending_sessions"]
        return next((r for r in rows if r["session_id"] == sid), None)

    # ── rpc() ──
    def rpc(self, fn, p, **_k):
        self.rpcs.append(fn)
        return getattr(self, fn)(p)

    def stash_tutor_session(self, p):
        rows, now = self.rows["tutor_pending_sessions"], _now()
        rows[:] = [r for r in rows if not (
            (r["state"] == "pending"
             and datetime.fromisoformat(r["stashed_at"]) < now - timedelta(seconds=p["p_ttl_seconds"]))
            or (r["state"] != "pending" and datetime.fromisoformat(r["discarded_at"])
                < now - timedelta(seconds=p["p_tombstone_ttl_seconds"])))]
        pending = sorted((r for r in rows if r["state"] == "pending"),
                         key=lambda r: r["stashed_at"], reverse=True)
        doomed = {r["session_id"] for r in pending[p["p_max_entries"] - 1:]}
        rows[:] = [r for r in rows if r["session_id"] not in doomed]
        rows.append({
            "session_id": p["p_session_id"], "user_id": p["p_user_id"], "state": "pending",
            "mode": p["p_mode"], "topic": p["p_topic"], "course_id": p["p_course_id"],
            "offering_id": p["p_offering_id"], "use_shared_context": p["p_use_shared_context"],
            "assistant_reply": p["p_assistant_reply"], "graph_update": p["p_graph_update"],
            "loop_state": p.get("p_loop_state"),
            "stashed_at": now.isoformat(), "discarded_at": None,
        })
        return True

    def materialize_tutor_session(self, p):
        r, now = self.store(p["p_session_id"]), _now()
        if r is None:
            return [{"outcome": "none"}]
        if r["state"] != "pending":
            fresh = datetime.fromisoformat(r["discarded_at"]) >= now - timedelta(
                seconds=p["p_tombstone_ttl_seconds"])
            ok = r["user_id"] == p["p_user_id"] and fresh
            return [{"outcome": r["state"] if ok else "none"}]
        if datetime.fromisoformat(r["stashed_at"]) < now - timedelta(seconds=p["p_ttl_seconds"]):
            return [{"outcome": "none"}]
        if r["user_id"] != p["p_user_id"]:
            return [{"outcome": "foreign"}]
        if not any(s["id"] == r["session_id"] for s in self.rows["sessions"]):
            self.rows["sessions"].append({
                "id": r["session_id"], "user_id": r["user_id"], "mode": r["mode"],
                "topic": r["topic"], "offering_id": r["offering_id"] or None,
                "loop_state": r.get("loop_state") or {},
                "started_at": now.isoformat(), "ended_at": None,
            })
        self.rows["messages"].append({
            "id": f"m-{len(self.rows['messages'])}", "session_id": r["session_id"],
            "role": "assistant", "content": r["assistant_reply"],
            "graph_update_json": r["graph_update"],
            "created_at": p["p_created_at"] or now.isoformat(),
        })
        self.rows["tutor_pending_sessions"].remove(r)
        return [{"outcome": "materialized", "session_mode": r["mode"],
                 "session_topic": r["topic"], "session_offering_id": r["offering_id"]}]

    def claim_tutor_session(self, p):
        """claim_tutor_session: the caller's own live pending row, returned as
        it was and turned into an "ended" tombstone, in one step."""
        r, now = self.store(p["p_session_id"]), _now()
        if not (r and r["user_id"] == p["p_user_id"] and r["state"] == "pending"
                and datetime.fromisoformat(r["stashed_at"]) >= now - timedelta(seconds=p["p_ttl_seconds"])):
            return []
        claimed = dict(r)
        r.update(state="ended", discarded_at=now.isoformat(), mode=None, topic=None,
                 course_id=None, offering_id=None, assistant_reply=None,
                 graph_update=None, loop_state=None)
        return [claimed]

    def discard_tutor_session(self, p):
        r, now = self.store(p["p_session_id"]), _now()
        was = bool(r and r["state"] == "pending" and datetime.fromisoformat(r["stashed_at"])
                   >= now - timedelta(seconds=p["p_ttl_seconds"]))
        if p["p_only_if_pending"] and not was:
            return False
        if r is not None:
            self.rows["tutor_pending_sessions"].remove(r)
        self.rows["tutor_pending_sessions"].append({
            "session_id": p["p_session_id"], "user_id": p["p_user_id"],
            "state": p["p_reason"], "discarded_at": now.isoformat(),
            "stashed_at": now.isoformat(), "mode": None, "topic": None,
            "assistant_reply": None, "graph_update": None, "loop_state": None,
        })
        return was


def _replica_hop():
    """The next request lands on the other replica: no process memory."""
    ts.PENDING_SESSIONS.clear()
    ts._DISCARDED.clear()


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_STATELESS_TUTOR_SESSIONS", "on")
    fake = _FakeDB()

    async def arpc(fn, p, **k):
        return fake.rpc(fn, p, **k)

    agent = MagicMock()
    agent.run = AsyncMock(side_effect=[run_result(GREETING)] + [run_result("A reply.")] * 5)
    _replica_hop()
    with (
        patch_tutor("table", side_effect=fake.table),
        patch("services.tutor_sessions.table", side_effect=fake.table),
        patch("services.tutor_sessions.rpc", side_effect=fake.rpc),
        patch("services.tutor_sessions.arpc", side_effect=arpc),
        patch_tutor("agent_for_mode", return_value=agent),
        patch_tutor("get_graph", return_value={"nodes": [], "edges": []}),
        patch_tutor("get_display_name", return_value="Store Student"),
        patch_tutor("offering_course_id", return_value=""),
        patch("services.events_service.log_event") as log_event,
    ):
        fake.log_event = log_event
        yield fake
    _replica_hop()


def _start(uid=USER) -> str:
    r = client.post("/api/learn/start-session", json={
        "user_id": uid, "topic": "Recursion", "mode": "socratic",
    })
    assert r.status_code == 200, r.text
    assert r.json()["initial_message"] == GREETING
    return r.json()["session_id"]


def _chat(sid, uid=USER):
    return client.post("/api/learn/chat", json={
        "session_id": sid, "user_id": uid, "message": "hi", "mode": "socratic",
    })


def _started_events(db):
    return [c for c in db.log_event.call_args_list if c.args[0] == "session.started"]


def test_a_session_started_on_one_replica_continues_on_the_other(db):
    sid = _start()
    assert ts.PENDING_SESSIONS == {}, "flag on: nothing pending in process memory"
    row = db.store(sid)
    assert row["state"] == "pending" and row["topic"] == "Recursion"
    assert row["assistant_reply"] != GREETING, "the stored greeting is ciphertext"
    assert db.rows["sessions"] == [], "still lazy: no sessions row before the first turn"

    _replica_hop()
    r = _chat(sid)
    assert r.status_code == 200, r.text
    assert [s["id"] for s in db.rows["sessions"]] == [sid]
    # The greeting was sealed for messages.content of this session before the
    # SQL copy, so it opens in its new row (AES-GCM AAD keyed on session_id).
    roles = [(m["role"], decrypt_if_present(m["content"], bind=bind("messages", "content", m)))
             for m in db.rows["messages"]]
    assert roles[0] == ("assistant", GREETING)
    assert [role for role, _ in roles] == ["assistant", "user", "assistant"]
    assert db.store(sid) is None, "materialised: the pending row is gone"
    assert len(_started_events(db)) == 1

    _replica_hop()
    assert _chat(sid).status_code == 200
    assert len(db.rows["sessions"]) == 1 and len(_started_events(db)) == 1


@pytest.mark.parametrize("reason,status", [("ended", 409), ("deleted", 404)])
def test_a_discard_on_one_replica_stops_turns_on_the_other(db, reason, status):
    sid = _start()
    _replica_hop()
    if reason == "ended":
        r = client.post("/api/learn/end-session", json={"session_id": sid, "user_id": USER})
        assert r.status_code == 200 and r.json()["summary"]["time_spent_minutes"] == 0
    else:
        assert client.delete(f"/api/learn/sessions/{sid}?user_id={USER}").status_code == 200
    assert db.store(sid)["state"] == reason
    assert db.store(sid)["assistant_reply"] is None, "a tombstone keeps no content"

    _replica_hop()
    r = _chat(sid)
    assert r.status_code == status, r.text
    if reason == "ended":
        assert r.json()["error"]["code"] == ts.SESSION_ENDED_CODE
        again = client.post("/api/learn/end-session", json={"session_id": sid, "user_id": USER})
        assert again.status_code == 200, "a repeat end is still answered"
    assert db.rows["sessions"] == [] and db.rows["messages"] == []


def test_the_materialised_greeting_sorts_before_the_turns_user_row(db):
    """The greeting is stamped on the app clock at the turn, before the turn's
    own rows (finding: a DB-clock stamp could sort after a skewed user row)."""
    sid = _start()
    _replica_hop()
    assert _chat(sid).status_code == 200
    stamps = [(m["role"], datetime.fromisoformat(m["created_at"])) for m in db.rows["messages"]]
    assert [r for r, _ in stamps] == ["assistant", "user", "assistant"]
    assert stamps[0][1] <= stamps[1][1] <= stamps[2][1]


def test_another_students_stored_session_is_404_and_left_intact(db):
    sid = _start()
    _replica_hop()
    assert _chat(sid, uid=OTHER).status_code == 404
    assert client.get(f"/api/learn/sessions/{sid}/resume?user_id={OTHER}").status_code == 404
    assert db.store(sid)["state"] == "pending"
    assert db.rows["sessions"] == []


def test_resume_and_rename_of_a_stored_pending_session(db):
    sid = _start()
    _replica_hop()
    r = client.get(f"/api/learn/sessions/{sid}/resume?user_id={USER}")
    assert r.status_code == 200, r.text
    assert r.json()["messages"][0]["content"] == GREETING

    r = client.patch(f"/api/learn/sessions/{sid}", json={"user_id": USER, "topic": "Trees"})
    assert r.status_code == 200, r.text
    assert db.rows["sessions"] == [], "renaming a pending session writes no row"
    assert db.store(sid)["topic"] == "Trees"
    _replica_hop()
    assert _chat(sid).status_code == 200
    assert db.rows["sessions"][0]["topic"] == "Trees"


def test_an_expired_stored_session_answers_like_an_unknown_one(db):
    sid = _start()
    db.store(sid)["stashed_at"] = (_now() - timedelta(seconds=ts.PENDING_TTL_SECONDS + 5)).isoformat()
    _replica_hop()
    assert _chat(sid).status_code == 404
    assert db.rows["sessions"] == []


def test_mode_switch_materialises_a_stored_session(db):
    sid = _start()
    _replica_hop()
    r = client.post("/api/learn/mode-switch", json={
        "session_id": sid, "user_id": USER, "new_mode": "expository",
    })
    assert r.status_code == 200, r.text
    assert db.rows["sessions"][0]["mode"] == "expository"


def test_a_session_pending_in_memory_finishes_there_after_the_flag_turns_on(db, monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_STATELESS_TUTOR_SESSIONS", "off")
    sid = _start()
    assert sid in ts.PENDING_SESSIONS and db.store(sid) is None
    monkeypatch.setenv("SAPLING_FLAG_STATELESS_TUTOR_SESSIONS", "on")
    assert _chat(sid).status_code == 200
    assert "materialize_tutor_session" not in db.rpcs
    assert [s["id"] for s in db.rows["sessions"]] == [sid]


def test_a_memory_tombstone_answers_409_with_the_flag_on(db, monkeypatch):
    """A session pending in memory when the flag went on is ENDED in memory
    (discard_if_pending pops it here). Its next turn must still be the 409
    SESSION_ENDED, not the bare 404 the table path gives an unknown id."""
    monkeypatch.setenv("SAPLING_FLAG_STATELESS_TUTOR_SESSIONS", "off")
    sid = _start()
    monkeypatch.setenv("SAPLING_FLAG_STATELESS_TUTOR_SESSIONS", "on")
    assert client.post("/api/learn/end-session",
                       json={"session_id": sid, "user_id": USER}).status_code == 200
    assert sid in ts._DISCARDED and db.store(sid) is None
    r = _chat(sid)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == ts.SESSION_ENDED_CODE
    assert "materialize_tutor_session" not in db.rpcs, "answered from memory, no I/O"


def _live_session(db) -> str:
    sid = _start()
    _replica_hop()
    assert _chat(sid).status_code == 200  # the first turn materialises it
    db.rpcs.clear()
    db.reads.clear()
    _replica_hop()
    return sid


def test_a_turn_on_a_live_stored_session_skips_the_materialise_call(db):
    """#117 review: every turn used to call materialize_tutor_session first
    and read the tombstone table once per written row. A live session now
    answers from its sessions row, and the turn reads the store once."""
    sid = _live_session(db)
    assert _chat(sid).status_code == 200
    assert "materialize_tutor_session" not in db.rpcs
    assert db.reads.count("sessions") >= 1
    assert db.reads.count("tutor_pending_sessions") == 1


def test_a_live_session_ended_on_the_other_replica_still_refuses(db):
    sid = _live_session(db)
    r = client.post("/api/learn/end-session", json={"session_id": sid, "user_id": USER})
    assert r.status_code == 200
    _replica_hop()
    r = _chat(sid)
    assert r.status_code == 409 and r.json()["error"]["code"] == ts.SESSION_ENDED_CODE
    assert _chat(sid, uid=OTHER).status_code == 404


def test_a_delete_tombstone_written_mid_turn_still_stops_the_write(db):
    """The delete's tombstone lands before its row delete: a turn that saw the
    row is refused at its write (the one store read), as before."""
    sid = _live_session(db)
    db.rows["tutor_pending_sessions"].append({
        "session_id": sid, "user_id": USER, "state": "deleted",
        "discarded_at": _now().isoformat(), "stashed_at": _now().isoformat(),
    })
    before = len(db.rows["messages"])
    assert _chat(sid).status_code == 404
    assert len(db.rows["messages"]) == before


def test_flag_off_never_touches_the_store(db, monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_STATELESS_TUTOR_SESSIONS", "off")
    sid = _start()
    assert _chat(sid).status_code == 200
    assert client.post("/api/learn/end-session",
                       json={"session_id": sid, "user_id": USER}).status_code == 200
    assert client.delete(f"/api/learn/sessions/{sid}?user_id={USER}").status_code == 200
    assert db.rpcs == []
    assert "tutor_pending_sessions" not in db.touched


def test_the_stash_carries_the_bounds():
    params = ts._stash_params("s1", {
        "user_id": USER, "mode": "socratic", "topic": "T", "course_id": "",
        "offering_id": "", "use_shared_context": False, "assistant_reply": GREETING,
        "graph_update": {},
    })
    assert (params["p_ttl_seconds"], params["p_tombstone_ttl_seconds"], params["p_max_entries"]) == (
        ts.PENDING_TTL_SECONDS, ts.DISCARD_TOMBSTONE_TTL_SECONDS, ts.PENDING_MAX_ENTRIES)
    assert params["p_graph_update"] is None, "an empty graph update stores NULL, like messages"
    assert params["p_loop_state"] is None, "a tutor session carries no loop document"
    # Sealed for the messages row the materialisation copies it into.
    assert decrypt_if_present(params["p_assistant_reply"],
                              bind=bind("messages", "content", "s1")) == GREETING
    assert decrypt_if_present(params["p_assistant_reply"],
                              bind=bind("messages", "content", "s2")) is None


# ── a close racing the first turn (claim_pending under the lock) ────────────


def test_a_close_waits_for_a_materialising_first_turn_and_finds_nothing_pending(monkeypatch):
    """Turn first: it holds the materialisation lock while it writes the row and
    only then drops the pending entry. The close's claim_pending waits for it
    and then sees the session as materialised (None)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeout

    monkeypatch.setattr(ts, "stored", lambda: False)
    monkeypatch.setitem(ts.PENDING_SESSIONS, "s-race", {"user_id": "u1", "stashed_at": "now"})
    inside, release = threading.Event(), threading.Event()

    def first_turn():
        with ts.materialization_lock("s-race"):
            inside.set()
            release.wait(5)
            ts.PENDING_SESSIONS.pop("s-race", None)  # the row is written: no longer pending

    # Futures re-raise a thread's exception at .result(), so a failing
    # claim_pending surfaces as itself; release is set whatever happens.
    with ThreadPoolExecutor(max_workers=2) as pool:
        turn = pool.submit(first_turn)
        try:
            assert inside.wait(5)
            close = pool.submit(ts.claim_pending, "s-race", "u1")
            with pytest.raises(FutureTimeout):
                close.result(timeout=0.2)  # still waiting for the turn's lock
        finally:
            release.set()
        turn.result(timeout=5)
        assert close.result(timeout=5) is None
    assert ts.discarded_reason("s-race", "u1") is None, "nothing was ended: the turn won"


def test_a_close_that_wins_makes_a_waiting_first_turn_answer_409_at_materialisation(monkeypatch):
    """Close first, memory mode: a first turn already past its ownership check
    and waiting on the materialisation lock re-checks under it, finds the entry
    gone and the claim's "ended" tombstone, and refuses with 409 — it never
    writes into (or 404s on) the session being closed."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from fastapi import HTTPException

    from services.tutor import pending as tutor_pending

    monkeypatch.setattr(ts, "stored", lambda: False)
    monkeypatch.setitem(ts.PENDING_SESSIONS, "s-won", {"user_id": "u1", "topic": "T"})
    turn_started = threading.Event()
    real_lock = ts.materialization_lock

    def lock_announcing_the_turn(session_id):
        turn_started.set()
        return real_lock(session_id)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with real_lock("s-won"):  # the close holds the lock first...
            monkeypatch.setattr(tutor_pending, "materialization_lock", lock_announcing_the_turn)
            turn = pool.submit(tutor_pending._consume_pending, "s-won", "u1")
            assert turn_started.wait(5), "the turn reached its locked re-check"
            # ...and claims under it, exactly as claim_pending does.
            assert ts.discard_pending("s-won", user_id="u1", reason="ended") == {"user_id": "u1", "topic": "T"}
        with pytest.raises(HTTPException) as exc:
            turn.result(timeout=5)
    assert exc.value.status_code == 409


def test_a_close_that_wins_leaves_a_tombstone_until_its_row_is_stored(monkeypatch):
    """Close first: the claim takes the payload and leaves the "ended"
    tombstone; a later first turn answers 409. Once the close has stored the
    row, release_claim_tombstone drops it — the row's close is the guard."""
    from fastapi import HTTPException

    from services.tutor import pending as tutor_pending

    monkeypatch.setattr(ts, "stored", lambda: False)
    monkeypatch.setitem(ts.PENDING_SESSIONS, "s-won", {"user_id": "u1", "topic": "T"})

    assert ts.claim_pending("s-won", "u1") == {"user_id": "u1", "topic": "T"}
    assert "s-won" not in ts.PENDING_SESSIONS
    assert ts.discarded_reason("s-won", "u1") == "ended"
    with pytest.raises(HTTPException) as exc:
        tutor_pending._consume_pending("s-won", "u1")
    assert exc.value.status_code == 409
    assert ts.claim_pending("s-won", "u1") is None, "a second close finds nothing pending"

    ts.release_claim_tombstone("s-won", "u1")
    assert ts.discarded_reason("s-won", "u1") is None


def test_the_table_claim_is_one_locked_call_and_a_racing_turn_reads_it_as_ended(db):
    """Table mode: claim_tutor_session returns the payload and leaves the
    tombstone in one call (no separate read, no snapshot to go stale); the
    racing turn's materialisation answers 409."""
    from fastapi import HTTPException

    ts.stash_pending("s-tab", {
        "user_id": "u1", "mode": "socratic", "topic": "Recursion", "course_id": "",
        "offering_id": "", "use_shared_context": True, "assistant_reply": GREETING,
        "graph_update": {},
    })
    _replica_hop()
    db.rpcs.clear()
    claimed = ts.claim_pending("s-tab", "u1")
    assert claimed["topic"] == "Recursion" and db.rpcs == ["claim_tutor_session"]
    assert db.store("s-tab")["state"] == "ended" and db.store("s-tab")["topic"] is None
    with pytest.raises(HTTPException) as exc:
        ts.materialize_stored("s-tab", "u1")
    assert exc.value.status_code == 409

    ts.release_claim_tombstone("s-tab", "u1")
    assert db.store("s-tab") is None


def test_a_table_claim_at_the_ttl_edge_trusts_the_databases_clock(db, monkeypatch):
    """The RPC decided liveness on the DATABASE clock, under its lock, and has
    already tombstoned the row. The app must not re-check `stashed_at` with
    its own clock: a few seconds of skew at the TTL's edge would read the row
    it just claimed as expired, and the close of a real session would 404
    (C7)."""
    ts.stash_pending("s-edge", {
        "user_id": "u1", "mode": "socratic", "topic": "Recursion", "course_id": "",
        "offering_id": "", "use_shared_context": True, "assistant_reply": GREETING,
        "graph_update": {},
    })
    _replica_hop()
    # The database still calls the row live; this process's clock is past the TTL.
    monkeypatch.setattr(ts, "_within", lambda _ts, _seconds: False)
    claimed = ts.claim_pending("s-edge", "u1")
    assert claimed is not None and claimed["topic"] == "Recursion"
    assert claimed["assistant_reply"] == GREETING
    assert db.store("s-edge")["state"] == "ended"


def test_a_table_claim_of_another_students_session_is_404_and_changes_nothing(db):
    from fastapi import HTTPException

    ts.stash_pending("s-foreign", {
        "user_id": "u2", "mode": "socratic", "topic": "T", "course_id": "",
        "offering_id": "", "use_shared_context": True, "assistant_reply": GREETING,
        "graph_update": {},
    })
    _replica_hop()
    with pytest.raises(HTTPException) as exc:
        ts.claim_pending("s-foreign", "u1")
    assert exc.value.status_code == 404
    assert db.store("s-foreign")["state"] == "pending"


def test_claim_pending_refuses_another_students_session(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(ts, "stored", lambda: False)
    monkeypatch.setitem(ts.PENDING_SESSIONS, "s-other", {"user_id": "u2"})
    with pytest.raises(HTTPException) as exc:
        ts.claim_pending("s-other", "u1")
    assert exc.value.status_code == 404
    assert "s-other" in ts.PENDING_SESSIONS and ts.discarded_reason("s-other") is None
