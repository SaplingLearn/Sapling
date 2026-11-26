"""PR #866 Z34: a document delete whose check-item withdrawal fails is never
silent.

The delete swallowed a failed `retire_items_for_documents` with a WARNING and
answered {deleted: true}: no event recorded that the deleted document's items
were still stored, so nothing told an operator to re-run the withdrawal (the
opt-out path has always reported its own as `learn.check_items_failed`,
WithdrawalError). The serving reads withhold such items meanwhile
(`_with_live_sources`, 385242c0/320aa827); this is the operator's half."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from tests.db_fakes import with_async_twins
from tests.split_patches import DOCUMENTS_MODULES, patch_documents, setattr_in
from tests.test_learning_check_items import _cached_tables


def _delete(monkeypatch, **retire):
    from fastapi.testclient import TestClient
    from main import app
    from routes import documents

    factory, _ = _cached_tables({"documents": [{"id": "doc-1"}]})
    setattr_in(monkeypatch, DOCUMENTS_MODULES, "table", with_async_twins(factory))
    monkeypatch.setattr(documents, "require_self", lambda *a, **k: None)
    monkeypatch.setattr(documents, "_validate_user", AsyncMock(return_value=None))
    with (
        patch_documents("retire_items_for_documents", **retire),
        patch("services.check_item_service.log_event") as ev,
    ):
        r = TestClient(app).delete("/api/documents/doc/doc-1?user_id=user_andres")
    return r, ev


def _failures(ev) -> list[dict]:
    return [
        c.kwargs for c in ev.call_args_list if c.args and c.args[0] == "learn.check_items_failed"
    ]


def test_a_failed_withdrawal_is_reported_and_the_delete_still_succeeds(monkeypatch):
    r, ev = _delete(monkeypatch, side_effect=RuntimeError("pg down"))

    assert r.status_code == 200 and r.json() == {"deleted": True}
    (event,) = _failures(ev)
    assert event["category"] == "error" and event["user_id"] == "user_andres"
    assert event["payload"] == {"document_id": "doc-1", "course_id": None, "reason": "WithdrawalError"}


def test_a_withdrawal_that_works_reports_nothing(monkeypatch):
    r, ev = _delete(monkeypatch, return_value=2)

    assert r.status_code == 200 and _failures(ev) == []
