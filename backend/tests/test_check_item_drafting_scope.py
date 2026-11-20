"""PR #866 Z14 / Z66: upload-time check-item drafting runs as the service role.

The upload's index-then-draft chain runs in the upload request's post-roll
(or BackgroundTask), and the drafting pool copies that request's context on
purpose, so under `db_user_scope=enforce` (#115) every PostgREST call made
there would go out as the student. The student's role holds no grant on the
loop's tables (spec §13 A148) and no UPDATE on the drafting-status columns of
`documents` (main's step-2c column grant), so each such call must resolve to
the service role.

Hermetic: the request is a RequestView whose state says enforce for a
subject, and a recording `table()` asks db/scope.py which identity each call
would go out as (None = the service role)."""

from __future__ import annotations

import pytest

from db import scope as db_scope
from services import check_item_service as svc
from services import request_context

#: What a call made as the student would carry (db/scope.py::_user_headers).
STUDENT = {"apikey": "anon-key", "Authorization": "Bearer student-jwt"}


@pytest.fixture
def enforced(monkeypatch):
    """Inside an upload request whose student is under db_user_scope=enforce."""
    monkeypatch.setattr(db_scope, "_user_headers", lambda subject: dict(STUDENT))
    view = request_context.RequestView(
        {"state": {db_scope.SUBJECT_KEY: "u1", db_scope.MODE_KEY: db_scope.ENFORCE}}
    )
    token = request_context._REQUEST_CTX.set(view)
    # the fixture's own premise: an unmarked call here goes out as the student
    assert db_scope.resolve_headers("notes") == STUDENT
    yield
    request_context._REQUEST_CTX.reset(token)


class _Recorder:
    """A `table()` that records (table, verb, the identity it resolved to)."""

    def __init__(self, rows: dict[str, list[dict]] | None = None):
        self.rows = rows or {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, name: str):
        rec = self

        class _Table:
            def _note(self, verb):
                rec.calls.append((name, verb, db_scope.resolve_headers(name)))

            def select(self, *_a, **_k):
                self._note("select")
                return [dict(r) for r in rec.rows.get(name, [])]

            def update(self, *_a, **_k):
                self._note("update")
                return []

            def upsert(self, *_a, **_k):
                self._note("upsert")
                return []

            def insert(self, *_a, **_k):
                self._note("insert")
                return []

            def delete(self, *_a, **_k):
                self._note("delete")
                return []

        return _Table()

    def as_student(self) -> list[tuple[str, str]]:
        return [(t, v) for t, v, headers in self.calls if headers is not None]


def test_the_drafting_status_writes_run_as_the_service_role(enforced, monkeypatch):
    """Z66: `pending` at the upload, the run's end, and a mark taken back."""
    rec = _Recorder()
    monkeypatch.setattr(svc, "table", rec)

    svc.mark_drafting("doc-1", svc.DRAFTING_PENDING)
    svc.mark_drafting("doc-1", svc.DRAFTING_DONE)
    svc.clear_drafting("doc-1")

    assert [(t, v) for t, v, _ in rec.calls] == [("documents", "update")] * 3
    assert rec.as_student() == []


def test_an_upload_drafting_run_reads_and_writes_as_the_service_role(enforced, monkeypatch):
    """Z14: the run inside the upload request's scope (the post-roll, or the
    pool that copies its context) — the document read, the item count, the
    redraft ledger, the run's end mark — never goes out as the student."""
    import config
    from agents.check_items import CheckItemsUnavailable

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    rec = _Recorder({"documents": [{"id": "doc-1", "user_id": "u1"}]})
    monkeypatch.setattr(svc, "table", rec)
    chunk = {"id": "c1", "chunk_index": 0, "doc_id": "doc-1",
             "chunk_text": "Gradient descent moves each parameter by the learning rate."}
    monkeypatch.setattr(svc, "source_chunks", lambda row: [dict(chunk)])
    monkeypatch.setattr(svc, "draft_items", lambda *a, **k: None)
    monkeypatch.setattr(svc, "run_agent_sync", lambda _coro: CheckItemsUnavailable(reason="Timeout"))
    monkeypatch.setattr(svc, "log_event", lambda *a, **k: None)

    out = svc.generate_for_document(
        "doc-1", user_id="u1", course_id="c-1", concept_names=["Learning rate"], flex=True
    )

    assert out.unavailable == 1  # the run reached its drafting call
    touched = {(t, v) for t, v, _ in rec.calls}
    assert {("documents", "select"), ("check_items", "select"),
            ("check_item_draft_failures", "select"), ("documents", "update")} <= touched
    assert rec.as_student() == []
