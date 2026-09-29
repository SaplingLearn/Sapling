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


def test_shutdown_cancels_queued_drafting_and_is_idempotent(svc):
    running = threading.Event()
    release = threading.Event()
    ran: list[str] = []

    def fake_generate(document_id, **kwargs):
        ran.append(document_id)
        running.set()
        release.wait(10)

    with patch.object(svc, "generate_for_document", side_effect=fake_generate):
        kw = {"user_id": "u1", "course_id": "course-1", "concept_names": ["A"]}
        first = svc.queue_generation_for_document("doc-1", **kw)
        assert running.wait(10)
        queued = [svc.queue_generation_for_document(f"doc-{n}", **kw) for n in (2, 3)]
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
