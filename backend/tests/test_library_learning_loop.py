"""The Library's Trash and the learning loop's check items (#866 over the
Library redesign): a delete retires a document's items, so a restore must put
the document back in line for drafting, and a permanent delete must withdraw
what a failed earlier withdrawal left."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import check_item_service
from services.documents import library

DOC, USER = "doc-1", "user-1"


def _documents(**verbs):
    handle = MagicMock()
    for name, value in verbs.items():
        setattr(handle, name, AsyncMock(return_value=value))
    return handle


def test_a_restore_forgets_the_drafting_its_delete_undid():
    handle = _documents(aupdate=[{"id": DOC}])
    with (
        patch.object(library, "table", return_value=handle),
        patch.object(library, "forget_drafting") as forget,
        patch.object(library, "schedule_document_index") as index,
    ):
        asyncio.run(library.restore_document(DOC, USER))
    forget.assert_called_once_with(DOC)
    index.assert_called_once_with(DOC, USER)
    assert handle.aupdate.await_args_list[0].args[0] == {"deleted_at": None}


def test_forget_drafting_writes_only_a_document_that_was_drafted():
    handle = MagicMock()
    with patch.object(check_item_service, "table", return_value=handle):
        check_item_service.forget_drafting(DOC)
    call = handle.update.call_args
    assert call.args[0] == {"check_items_status": None, "check_items_at": None}
    assert call.kwargs["filters"] == {"id": f"eq.{DOC}", "check_items_status": "not.is.null"}


def test_forget_drafting_never_fails_the_restore():
    handle = MagicMock()
    handle.update.side_effect = RuntimeError("down")
    with patch.object(check_item_service, "table", return_value=handle):
        check_item_service.forget_drafting(DOC)


@pytest.mark.parametrize("removed, withdrawn", [([{"id": DOC}], True), ([], False), (None, False)])
def test_a_permanent_delete_withdraws_the_items_of_a_row_it_removed(removed, withdrawn):
    """A row restored between the Trash check and the delete is live: its
    delete removes nothing, and its items stay."""
    handle = _documents(adelete=removed)
    with (
        patch.object(library, "table", return_value=handle),
        patch.object(library, "retire_items_for_documents") as retire,
    ):
        asyncio.run(library.hard_delete_document(DOC, USER))
    assert retire.called is withdrawn
    assert handle.adelete.await_args.kwargs["filters"]["deleted_at"] == "not.is.null"


@pytest.mark.parametrize("delete", ["soft", "hard"])
def test_a_failed_withdrawal_is_reported_and_never_fails_the_delete(delete):
    handle = _documents(aupdate=[{"id": DOC}], adelete=[{"id": DOC}])
    with (
        patch.object(library, "table", return_value=handle),
        patch("services.chunk_visibility.withdraw_document_chunks"),
        patch.object(library, "retire_items_for_documents", side_effect=RuntimeError("down")),
        patch.object(library, "report_withdrawal_failure") as report,
    ):
        run = library.soft_delete_document if delete == "soft" else library.hard_delete_document
        asyncio.run(run(DOC, USER))
    report.assert_called_once_with(USER, DOC)


def test_the_list_carries_the_drafting_status_and_the_trash_makes_no_graph_read():
    handle = _documents(aselect=[])
    with (
        patch.object(library, "table", return_value=handle),
        patch.object(library, "_attach_concept_node_ids", new=AsyncMock()) as attach,
    ):
        asyncio.run(library.list_user_documents(USER))
        assert "check_items_status" in handle.aselect.await_args.args[0]
        asyncio.run(library.list_trashed_documents(USER))
    attach.assert_awaited_once()
