"""PKG-04 post-hoc (owner decision A38, low-severity 4): with the flag on a
deploy could hang — the drafting pool's workers are non-daemon and a queued
Flex drafting can take FLEX_TIMEOUT_S, so interpreter exit waited on the whole
queue. The app's shutdown now drops the queue (`shutdown_draft_pool`)."""

from __future__ import annotations

import threading
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def svc(monkeypatch):
    from services import check_item_service as svc

    svc.shutdown_draft_pool()  # a fresh one-worker pool for this test
    monkeypatch.setattr(svc, "CHECK_ITEM_DRAFT_WORKERS", 1)
    yield svc
    svc.shutdown_draft_pool()


def test_shutdown_cancels_queued_drafting_and_is_idempotent(svc, monkeypatch):
    running = threading.Event()
    release = threading.Event()
    ran: list[str] = []

    def fake_generate(document_id, **kwargs):
        ran.append(document_id)
        running.set()
        release.wait(10)

    monkeypatch.setattr(svc, "clear_dropped_drafting", lambda: 0)
    with patch.object(svc, "generate_for_document", side_effect=fake_generate):
        kw = {"course_id": "course-1", "concept_names": ["A"]}
        first = svc.queue_generation_for_document("doc-1", user_id="u1", **kw)
        assert running.wait(10)
        queued = [
            svc.queue_generation_for_document(f"doc-{n}", user_id=f"u{n}", **kw) for n in (2, 3)
        ]
        svc.shutdown_draft_pool()
        assert all(f.cancelled() for f in queued), "queued drafting is dropped, not awaited"
        svc.shutdown_draft_pool()  # idempotent
        release.set()
        assert first.result(timeout=10) is None  # the in-flight run is left to finish
    assert ran == ["doc-1"]


def test_shutdown_without_a_pool_is_a_no_op_and_a_later_upload_gets_a_new_pool(svc):
    svc.shutdown_draft_pool()
    assert svc._draft_pool_instance is None
    with patch.object(svc, "generate_for_document") as gen:
        svc.queue_generation_for_document(
            "doc-9", user_id="u1", course_id="course-1", concept_names=[]
        ).result(timeout=10)
    gen.assert_called_once()


def test_the_app_lifespan_shuts_the_pool_down():
    from fastapi.testclient import TestClient

    with (
        patch("main.shutdown_draft_pool") as down,
        patch("main.start_sweeper"),
        patch("main.stop_sweeper", new=AsyncMock()),
        patch("main.ensure_bucket_exists", new=AsyncMock()),
    ):
        from main import app

        with TestClient(app):
            down.assert_not_called()
        down.assert_called_once_with()


def test_the_pool_is_shut_down_before_the_event_drain_and_dbos():
    """A38 fix round (m8): drafting still running would log usage and events after
    events_service stopped, and a failing shutdown_dbos (or stop_sweeper) must not skip
    dropping the queue — so the pool goes first."""
    from fastapi.testclient import TestClient

    order: list[str] = []
    with (
        patch("main.shutdown_draft_pool", side_effect=lambda: order.append("pool")),
        patch("main.shutdown_dbos", side_effect=lambda: order.append("dbos")),
        patch("main.start_sweeper"),
        patch("main.stop_sweeper", new=AsyncMock(side_effect=lambda: order.append("sweeper"))),
        patch("main.ensure_bucket_exists", new=AsyncMock()),
        patch(
            "services.events_service.shutdown",
            side_effect=lambda *a, **k: order.append("events"),
        ),
    ):
        from main import app

        with TestClient(app):
            pass
    assert order[0] == "pool", order
    # #771: DBOS is destroyed BEFORE the events worker stops (its workflows log
    # events); the pool still goes first of all.
    assert order.index("pool") < order.index("dbos") < order.index("events"), order


def test_a_failing_dbos_shutdown_never_skips_the_pool():
    from fastapi.testclient import TestClient

    with (
        patch("main.shutdown_draft_pool") as down,
        patch("main.shutdown_dbos", side_effect=RuntimeError("dbos")),
        patch("main.start_sweeper"),
        patch("main.stop_sweeper", new=AsyncMock(side_effect=RuntimeError("sweeper"))),
        patch("main.ensure_bucket_exists", new=AsyncMock()),
    ):
        from main import app

        with pytest.raises(RuntimeError):
            with TestClient(app):
                pass
        down.assert_called_once_with()


def test_one_uploader_cannot_queue_drafting_ahead_of_everyone_else(svc, monkeypatch):
    """Z21: an uploader holds at most CHECK_ITEM_DRAFT_QUEUE_PER_USER places on
    the pool (queued or running). A document past that is not queued: its
    `pending` mark goes back to "never drafted", so draft on enable claims it.
    A classmate's upload still queues, and a finished run frees its place."""
    from learning.params import CHECK_ITEM_DRAFT_QUEUE_PER_USER

    release = threading.Event()
    ran: list[str] = []
    cleared: list[str] = []
    monkeypatch.setattr(svc, "clear_drafting", cleared.append)

    def fake_generate(document_id, **kwargs):
        ran.append(document_id)
        release.wait(10)

    kw = {"course_id": "course-1", "concept_names": ["A"]}
    with patch.object(svc, "generate_for_document", side_effect=fake_generate):
        mine = [
            svc.queue_generation_for_document(f"bulk-{n}", user_id="u1", **kw)
            for n in range(CHECK_ITEM_DRAFT_QUEUE_PER_USER + 3)
        ]
        theirs = svc.queue_generation_for_document("classmate", user_id="u2", **kw)
        assert all(f is not None for f in mine[:CHECK_ITEM_DRAFT_QUEUE_PER_USER])
        assert mine[CHECK_ITEM_DRAFT_QUEUE_PER_USER:] == [None, None, None]
        assert cleared == [f"bulk-{n}" for n in range(CHECK_ITEM_DRAFT_QUEUE_PER_USER, len(mine))]
        assert theirs is not None
        release.set()
        for f in [*mine[:CHECK_ITEM_DRAFT_QUEUE_PER_USER], theirs]:
            f.result(timeout=10)
        later = svc.queue_generation_for_document("bulk-later", user_id="u1", **kw)
        assert later is not None
        later.result(timeout=10)
    assert "classmate" in ran and "bulk-later" in ran
    assert svc._drafting_by_user == {} and svc._drafting_docs == {}


def test_shutdown_takes_back_the_dropped_documents_marks_in_one_write(svc, monkeypatch):
    """Z21: a deploy drops the queued drafting; the dropped documents go back to
    "never drafted" at once (one conditional write), so draft on enable re-drives
    them instead of leaving them `pending` until the TTL."""
    running = threading.Event()
    release = threading.Event()
    writes: list[tuple[dict, dict]] = []

    class _Docs:
        def update(self, data, *, filters, prefer_return_minimal):
            writes.append((data, filters))

    monkeypatch.setattr(svc, "table", lambda name: _Docs())

    def fake_generate(document_id, **kwargs):
        running.set()
        release.wait(10)

    kw = {"course_id": "course-1", "concept_names": ["A"]}
    with patch.object(svc, "generate_for_document", side_effect=fake_generate):
        first = svc.queue_generation_for_document("doc-1", user_id="u1", **kw)
        assert running.wait(10)
        svc.queue_generation_for_document("doc-2", user_id="u2", **kw)
        svc.queue_generation_for_document("doc-3", user_id="u3", **kw)
        svc.shutdown_draft_pool()
        release.set()
        first.result(timeout=10)
    assert writes == [(
        {"check_items_status": None, "check_items_at": None},
        {"id": 'in.("doc-2","doc-3")', "check_items_status": "eq.pending"},
    )]
    svc.shutdown_draft_pool()
    assert len(writes) == 1, "nothing dropped twice"
