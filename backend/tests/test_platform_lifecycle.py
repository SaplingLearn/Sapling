"""#771 (workstream M): process lifecycle — lifespan teardown order, the
events worker's shutdown, and PostHog's stopped state."""
from __future__ import annotations

import asyncio
import threading
import time
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from services import events_service, posthog_client


# ── Lifespan ────────────────────────────────────────────────────────────────


def _patch_lifecycle(stack: ExitStack, calls: list[str], *, fail_at: str | None = None):
    def sync(name):
        def _f(*_a, **_k):
            calls.append(name)
            if name == fail_at:
                raise RuntimeError(f"{name} failed")
        return _f

    def async_(name):
        async def _f(*_a, **_k):
            calls.append(name)
        return _f

    stack.enter_context(patch("main.ensure_bucket_exists", new=AsyncMock()))
    stack.enter_context(patch("services.posthog_client.initialize_posthog", sync("posthog.init")))
    stack.enter_context(patch("services.posthog_client.shutdown_posthog", sync("posthog.shutdown")))
    stack.enter_context(patch("services.events_service.start_worker", sync("events.start")))
    stack.enter_context(patch("services.events_service.shutdown", sync("events.shutdown")))
    stack.enter_context(patch("services.typesafe_client.aclose_clients", async_("jev.close")))
    stack.enter_context(patch("services.tutor_router.drain_inflight", async_("router.drain")))
    stack.enter_context(patch("main.init_dbos", sync("dbos.init")))
    stack.enter_context(patch("routes.documents.drain_post_roll", async_("postroll.drain")))
    stack.enter_context(patch("main.shutdown_dbos", sync("dbos.shutdown")))
    stack.enter_context(patch("main.start_sweeper", sync("sweeper.start")))
    stack.enter_context(patch("main.stop_sweeper", async_("sweeper.stop")))
    stack.enter_context(patch("main.start_local_seed_watcher", sync("watcher.start")))
    stack.enter_context(patch("main.stop_local_seed_watcher", async_("watcher.stop")))


def test_shutdown_stops_producers_before_sinks():
    """Every producer that can still log_event stops (or drains) before the
    events worker, and PostHog goes last; DBOS no longer outlives the sink."""
    calls: list[str] = []
    with ExitStack() as stack:
        _patch_lifecycle(stack, calls)
        from main import app

        with TestClient(app):
            started = list(calls)
    stopped = calls[len(started):]
    assert stopped == [
        "watcher.stop", "sweeper.stop", "postroll.drain", "dbos.shutdown",
        "router.drain", "jev.close", "events.shutdown", "posthog.shutdown",
    ]


def test_a_startup_failure_tears_down_what_already_started():
    """init_dbos raising (an operator opted in and launch failed) used to skip
    every teardown: the events worker and PostHog were left running."""
    calls: list[str] = []
    with ExitStack() as stack:
        _patch_lifecycle(stack, calls, fail_at="dbos.init")
        from main import app

        with pytest.raises(RuntimeError, match="dbos.init failed"):
            with TestClient(app):
                pass
    assert "sweeper.start" not in calls
    tail = calls[calls.index("dbos.init") + 1:]
    assert tail == [
        "dbos.shutdown", "router.drain", "jev.close", "events.shutdown", "posthog.shutdown",
    ]


# ── events_service.shutdown ─────────────────────────────────────────────────


def test_shutdown_waits_for_the_in_flight_batch(monkeypatch):
    """A join that times out mid-insert used to race flush_now and return
    while the worker was still inserting — the process then exited under it."""
    inserted: list[dict] = []
    in_insert = threading.Event()
    release = threading.Event()

    def fake_table(_name):
        t = MagicMock()

        def _insert(rows):
            in_insert.set()
            release.wait(5)
            inserted.extend(rows)

        t.insert.side_effect = _insert
        return t

    monkeypatch.setattr(events_service, "table", fake_table)
    monkeypatch.setattr(events_service, "_SHUTDOWN_JOIN_S", 0.05)
    events_service.start_worker()
    events_service.log_event("a", category="system")
    assert in_insert.wait(5)
    events_service.log_event("b", category="system")  # queued behind the batch

    done = threading.Event()
    t = threading.Thread(target=lambda: (events_service.shutdown(), done.set()))
    t.start()
    assert not done.wait(0.3), "shutdown returned while a batch was still in flight"
    release.set()
    assert done.wait(5)
    assert sorted(r["event_type"] for r in inserted) == ["a", "b"]


def test_a_row_logged_after_shutdown_is_inserted_inline_off_the_loop(monkeypatch):
    rows: list[dict] = []
    t = MagicMock()
    t.insert.side_effect = rows.extend
    monkeypatch.setattr(events_service, "table", lambda _n: t)
    events_service.start_worker()
    events_service.shutdown()

    # A sweeper/to_thread worker that outlived its cancelled loop.
    worker = threading.Thread(
        target=lambda: events_service.log_event("late", category="system"),
    )
    worker.start()
    worker.join(5)
    assert [r["event_type"] for r in rows] == ["late"]
    assert events_service._queue.qsize() == 0


def test_a_row_logged_on_a_loop_after_shutdown_is_counted_not_blocking(monkeypatch):
    t = MagicMock()
    monkeypatch.setattr(events_service, "table", lambda _n: t)
    events_service.shutdown()

    async def on_loop():
        events_service.log_event("late", category="system")

    asyncio.run(on_loop())
    t.insert.assert_not_called()
    assert events_service._late_dropped == 1


def test_start_worker_reopens_after_shutdown(monkeypatch):
    events_service.shutdown()
    events_service.start_worker()
    try:
        events_service._enqueue("events", {"event_type": "x"})
        assert events_service._closed is False
    finally:
        monkeypatch.setattr(events_service, "table", lambda _n: MagicMock())
        events_service.shutdown()


# ── posthog_client stopped state ────────────────────────────────────────────


@pytest.fixture
def ph(monkeypatch):
    sent: list[str] = []
    client = MagicMock()
    client.capture.side_effect = lambda name, **_k: sent.append(name)
    monkeypatch.setattr(posthog_client, "_product_analytics_on", lambda actor: True)
    monkeypatch.setattr(posthog_client, "_distinct_id_for", lambda actor: actor)
    posthog_client.set_client_for_tests(client)
    yield client, sent
    posthog_client.set_client_for_tests(None)


def _item(name: str) -> "posthog_client._Item":
    return posthog_client._Item(name, {}, "user_1", 0.0)


def test_no_item_is_accepted_and_then_lost_at_shutdown(ph, monkeypatch):
    """The old order flushed, THEN dropped the client: an item submitted in
    between was accepted, delivered to a None client and silently dropped.
    Now every item is either delivered or visibly refused."""
    client, sent = ph
    monkeypatch.setattr(posthog_client, "_refused_after_stop", 0)
    gate = threading.Event()

    def capture(name, **_k):
        if name == "first":
            gate.wait(5)  # the worker is mid-delivery while shutdown runs
        sent.append(name)

    client.capture.side_effect = capture
    posthog_client._enqueue(_item("first"))
    done = threading.Event()
    t = threading.Thread(target=lambda: (posthog_client.shutdown_posthog(), done.set()))
    t.start()
    deadline = time.monotonic() + 5
    while not posthog_client._stopped and time.monotonic() < deadline:
        time.sleep(0.001)
    posthog_client._enqueue(_item("during"))  # a request racing the shutdown
    gate.set()
    assert done.wait(10)
    assert sent == ["first"]
    assert posthog_client._refused_after_stop == 1
    client.shutdown.assert_called_once()


def test_after_shutdown_nothing_is_accepted_and_no_worker_restarts(ph):
    client, sent = ph
    posthog_client.shutdown_posthog()
    assert posthog_client._worker is None
    posthog_client._enqueue(_item("e.late"))
    assert posthog_client._worker is None, "_ensure_worker resurrected the worker"
    assert posthog_client._queue.qsize() == 0
    assert posthog_client._refused_after_stop >= 1
    assert sent == []


# ── Dead state (#771) ───────────────────────────────────────────────────────


def test_dropped_columns_have_no_reader_left():
    """users.current_room_id and courses.deleted_at are dropped by
    20261106055333_state_machines_audit; a reader added back would 400 at
    PostgREST (mocked tests cannot see that)."""
    from pathlib import Path
    from unittest.mock import MagicMock

    from services import topic_checklist_service as svc

    backend = Path(__file__).resolve().parents[1]
    for path in backend.rglob("*.py"):
        if "venv" in path.parts or "tests" in path.parts:
            continue
        assert "current_room_id" not in path.read_text(encoding="utf-8"), path

    seen: dict = {}

    def fake_table(name):
        m = MagicMock()

        def select(cols, filters=None, **_k):
            if name == "courses":
                seen.update(filters or {})
            return []
        m.select.side_effect = select
        return m

    with patch("services.topic_checklist_service.table", side_effect=fake_table), \
         patch("services.topic_checklist_service.user_offering_ids_for_course", return_value=[]):
        with pytest.raises(Exception):
            svc.resolve_scope("u1", "c1", None)
    assert seen and "deleted_at" not in seen


# ── Model mode is immutable after boot ──────────────────────────────────────


def test_model_mode_is_frozen_at_boot(monkeypatch, caplog):
    """Agents capture their model at import while the gates read the mode per
    call: a runtime env change used to split them. After the lifespan's
    freeze, every reader keeps the boot value."""
    from agents import _providers

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    assert _providers.freeze_model_mode() == "function"
    monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
    with caplog.at_level("WARNING"):
        assert _providers.model_mode() == "function"
        assert _providers._model_mode() == "function"
        assert _providers.model_mode() == "function"
    assert sum("frozen at startup" in r.message for r in caplog.records) == 1
    # Idempotent: a second freeze keeps the first value.
    assert _providers.freeze_model_mode() == "function"


def test_model_mode_reads_the_env_until_frozen(monkeypatch):
    from agents import _providers

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    assert _providers.model_mode() == "function"
    monkeypatch.setenv("SAPLING_MODEL_MODE", " REAL ")
    assert _providers.model_mode() == "real"


def test_the_lifespan_freezes_the_mode(monkeypatch):
    from agents import _providers

    calls: list[str] = []
    with ExitStack() as stack:
        _patch_lifecycle(stack, calls)
        from main import app

        monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
        with TestClient(app) as client:
            monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
            assert _providers.model_mode() == "real"
            assert client.get("/api/health").json()["model_mode"] == "real"
