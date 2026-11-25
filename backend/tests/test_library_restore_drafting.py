"""A document restored from the Trash is drafted again (#866 x #717).

Moving a document to the Trash retires the check items drafted from it
(A23: `retire_items_for_documents` deletes them). Restore brings the document
back, so its `check_items_status` must not keep saying `done` for items that
no longer exist: it goes back to never-drafted, which draft on enable
(`claim_undrafted_documents`) claims again.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from services.documents import library
from tests.db_fakes import fake_table


def test_restore_forgets_the_drafting_mark():
    docs = fake_table()
    docs.update.return_value = []
    with patch.object(library, "table", return_value=docs), \
            patch.object(library, "forget_drafting") as forget, \
            patch.object(library, "schedule_document_index", MagicMock()):
        asyncio.run(library.restore_document("d1", "u1"))

    forget.assert_called_once_with("d1")
    # The deleted_at clear lands first: the mark is forgotten for a document
    # that is live again.
    first = docs.update.call_args_list[0]
    assert first.args[0] == {"deleted_at": None}


def test_soft_delete_still_retires_the_items():
    docs = fake_table()
    docs.update.return_value = []
    with patch.object(library, "table", return_value=docs), \
            patch("services.chunk_visibility.withdraw_document_chunks"), \
            patch.object(library, "retire_items_for_documents") as retire:
        asyncio.run(library.soft_delete_document("d1", "u1"))

    retire.assert_called_once_with(["d1"])
