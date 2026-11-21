"""
The Library redesign's new routes in routes/documents.py:

  - PATCH  /api/documents/doc/{id}          rename / re-file / re-type
  - GET    /api/documents/user/{id}/trash   the Trash view
  - POST   /api/documents/doc/{id}/restore  take one back out
  - DELETE /api/documents/doc/{id}?hard=1   delete forever
  - GET/POST/PATCH/DELETE /api/documents/folders
  - POST   /api/documents/blank             "New Document"
  - the per-document notes: GET / PUT / regenerate / ask

Every DB call and agent run is mocked; what is pinned here is the contract the
Library depends on, and the two guards that keep it safe: a hard delete is
Trash-only, and a move is refused into a course the student is not taking.
"""
import pytest
from unittest.mock import AsyncMock
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from tests.db_fakes import fake_table
from tests.split_patches import patch_documents

client = TestClient(app)

# #117: these handlers run on the async seam; a sync PostgREST call creeping
# back onto the event loop raises instead of only logging.
pytestmark = pytest.mark.usefixtures("no_sync_db_on_loop")


def _validated():
    return patch_documents("_validate_user", return_value=None)


def _owned(table_mock, rows=({"id": "d1"},)):
    """Make the ownership / existence reads answer with `rows`."""
    table_mock.return_value.select.return_value = list(rows)


# ── PATCH: rename, re-file, re-type ──────────────────────────────────────────

class TestUpdateDocumentFields:
    def test_renames(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t:
            _owned(t)
            t.return_value.update.return_value = [{"id": "d1", "file_name": "Week 3.pdf"}]
            r = client.patch(
                "/api/documents/doc/d1",
                json={"user_id": "u1", "file_name": "Week 3.pdf"},
            )
        assert r.status_code == 200
        assert t.return_value.update.call_args[0][0] == {"file_name": "Week 3.pdf"}

    def test_refuses_a_blank_name(self):
        r = client.patch("/api/documents/doc/d1", json={"user_id": "u1", "file_name": "   "})
        assert r.status_code == 400

    def test_moves_into_a_course_through_its_offering(self):
        """Documents key on the OFFERING while the API speaks the abstract
        course id (#435), so a move has to resolve one — and only for a course
        the student is actually enrolled in."""
        with _validated(), patch_documents("table", return_value=fake_table()) as t, \
                patch_documents("require_course_enrollment",
                                return_value="off-9") as enroll:
            _owned(t)
            t.return_value.update.return_value = [{"id": "d1"}]
            r = client.patch("/api/documents/doc/d1", json={"user_id": "u1", "course_id": "c1"})

        assert r.status_code == 200
        enroll.assert_called_once_with("u1", "c1")
        written = t.return_value.update.call_args[0][0]
        assert written["offering_id"] == "off-9"
        # Leaving the course unfiles the document: a folder lives inside one.
        assert written["folder_id"] is None

    def test_a_null_course_means_no_course(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t:
            _owned(t)
            t.return_value.update.return_value = [{"id": "d1"}]
            r = client.patch("/api/documents/doc/d1", json={"user_id": "u1", "course_id": None})

        assert r.status_code == 200
        assert t.return_value.update.call_args[0][0]["offering_id"] is None

    def test_naming_a_folder_in_the_same_call_keeps_the_filing(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t, \
                patch_documents("require_course_enrollment", return_value="off-9"), \
                patch_documents("get_folder", new=AsyncMock(return_value={"id": "f1"})):
            _owned(t)
            t.return_value.update.return_value = [{"id": "d1"}]
            r = client.patch(
                "/api/documents/doc/d1",
                json={"user_id": "u1", "course_id": "c1", "folder_id": "f1"},
            )

        assert r.status_code == 200
        assert t.return_value.update.call_args[0][0]["folder_id"] == "f1"

    def test_refuses_a_folder_that_is_not_the_users(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t, \
                patch_documents("get_folder", new=AsyncMock(return_value=None)):
            _owned(t)
            r = client.patch("/api/documents/doc/d1", json={"user_id": "u1", "folder_id": "nope"})
        assert r.status_code == 404


# ── Trash ────────────────────────────────────────────────────────────────────

class TestTrash:
    def test_lists_the_soft_deleted(self):
        trashed = [{"id": "d9", "file_name": "old.pdf", "deleted_at": "2026-11-01T00:00:00Z"}]
        with _validated(), patch_documents("list_trashed_documents",
                                           new=AsyncMock(return_value=trashed)):
            r = client.get("/api/documents/user/u1/trash")
        assert r.status_code == 200
        assert r.json()["documents"] == trashed

    def test_restores_one(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t, \
                patch_documents("restore_document", new=AsyncMock()) as restore:
            _owned(t, [{"id": "d1"}])
            r = client.post("/api/documents/doc/d1/restore", json={"user_id": "u1"})
        assert r.status_code == 200
        restore.assert_awaited_once_with("d1", "u1")

    def test_restoring_something_not_in_the_trash_is_a_404(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t, \
                patch_documents("restore_document", new=AsyncMock()) as restore:
            _owned(t, [])
            r = client.post("/api/documents/doc/d1/restore", json={"user_id": "u1"})
        assert r.status_code == 404
        restore.assert_not_awaited()

    def test_hard_delete_only_applies_to_the_trash(self):
        """The guard that matters: a live document can never be purged by id,
        so a mis-click in the Library cannot skip the 30-day grace."""
        with _validated(), patch_documents("table", return_value=fake_table()) as t, \
                patch_documents("hard_delete_document", new=AsyncMock()) as purge:
            _owned(t, [])  # nothing matches "mine AND in the trash"
            r = client.delete("/api/documents/doc/d1?user_id=u1&hard=1")
        assert r.status_code == 404
        purge.assert_not_awaited()

    def test_hard_delete_purges_a_trashed_document(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t, \
                patch_documents("hard_delete_document", new=AsyncMock()) as purge:
            _owned(t, [{"id": "d1"}])
            r = client.delete("/api/documents/doc/d1?user_id=u1&hard=1")
        assert r.status_code == 200
        assert r.json() == {"deleted": True, "purged": True}
        purge.assert_awaited_once_with("d1", "u1")


# ── folders ──────────────────────────────────────────────────────────────────

class TestFolders:
    """The handler bodies live in `services/documents/folders.py` (#118), so
    these patch its reads and writes and let the real logic run."""

    def test_lists(self):
        rows = [{"id": "f1", "name": "Midterm Prep", "course_id": "c1"}]
        with _validated(), patch_documents("list_folders", new=AsyncMock(return_value=rows)):
            r = client.get("/api/documents/folders?user_id=u1")
        assert r.status_code == 200
        assert r.json()["folders"] == rows

    def test_an_unnamed_folder_saves_as_new_folder(self):
        """The Library creates a folder and renames it in place, so a blank
        name is its normal first state, not an error."""
        with _validated(), \
                patch_documents("count_folders", new=AsyncMock(return_value=0)), \
                patch_documents("create_folder",
                                new=AsyncMock(return_value={"id": "f1"})) as create:
            r = client.post("/api/documents/folders", json={"user_id": "u1", "name": ""})
        assert r.status_code == 200
        assert create.await_args[0][1] == "New Folder"

    def test_refuses_a_course_the_student_is_not_taking(self):
        with _validated(), \
                patch_documents("create_folder", new=AsyncMock()) as create, \
                patch_documents("require_course_enrollment",
                                side_effect=HTTPException(status_code=404,
                                                          detail="not enrolled")):
            r = client.post(
                "/api/documents/folders",
                json={"user_id": "u1", "name": "Labs", "course_id": "c9"},
            )
        assert r.status_code == 404
        create.assert_not_awaited()

    def test_caps_how_many_a_student_can_have(self):
        from services.documents import folders as folders_service

        with _validated(), \
                patch_documents("count_folders",
                                new=AsyncMock(return_value=folders_service.MAX_FOLDERS)), \
                patch_documents("create_folder", new=AsyncMock()) as create:
            r = client.post("/api/documents/folders", json={"user_id": "u1", "name": "One more"})
        assert r.status_code == 400
        create.assert_not_awaited()

    def test_renames(self):
        with _validated(), \
                patch_documents("get_folder", new=AsyncMock(return_value={"id": "f1"})), \
                patch_documents("rename_folder",
                                new=AsyncMock(return_value={"id": "f1", "name": "Exam Prep"})):
            r = client.patch(
                "/api/documents/folders/f1", json={"user_id": "u1", "name": "Exam Prep"},
            )
        assert r.status_code == 200
        assert r.json()["name"] == "Exam Prep"

    def test_refuses_to_rename_a_folder_to_nothing(self):
        """Unlike creating one: the student is renaming something that already
        has a name, so emptying it is a mistake rather than a default."""
        with _validated(), \
                patch_documents("get_folder", new=AsyncMock(return_value={"id": "f1"})), \
                patch_documents("rename_folder", new=AsyncMock()) as rename:
            r = client.patch("/api/documents/folders/f1", json={"user_id": "u1", "name": "  "})
        assert r.status_code == 400
        rename.assert_not_awaited()

    def test_deletes(self):
        with _validated(), \
                patch_documents("get_folder", new=AsyncMock(return_value={"id": "f1"})), \
                patch_documents("delete_folder", new=AsyncMock()) as delete:
            r = client.delete("/api/documents/folders/f1?user_id=u1")
        assert r.status_code == 200
        delete.assert_awaited_once_with("f1", "u1")

    def test_a_folder_that_is_not_yours_is_a_404(self):
        with _validated(), \
                patch_documents("get_folder", new=AsyncMock(return_value=None)), \
                patch_documents("delete_folder", new=AsyncMock()) as delete:
            r = client.delete("/api/documents/folders/f1?user_id=u1")
        assert r.status_code == 404
        delete.assert_not_awaited()


# ── "New Document" ───────────────────────────────────────────────────────────

class TestBlankDocument:
    def test_creates_an_unindexable_row(self):
        """An empty document has no text, so it is born terminal: a `pending`
        row with nothing to index would be claimed until it exhausted its
        attempt budget."""
        with _validated(), patch_documents("table", return_value=fake_table()) as t:
            t.return_value.insert.side_effect = lambda row: [dict(row)]
            r = client.post("/api/documents/blank", json={"user_id": "u1"})

        assert r.status_code == 200
        row = t.return_value.insert.call_args[0][0]
        assert row["index_status"] == "skipped"
        assert row["file_name"] == "New Document"
        assert row["category"] == "other"
        # The HTTP boundary speaks the abstract course id, not the offering.
        assert "offering_id" not in r.json()

    def test_inherits_the_open_course_and_folder(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t, \
                patch_documents("require_course_enrollment", return_value="off-2"), \
                patch_documents("get_folder", new=AsyncMock(return_value={"id": "f1"})):
            t.return_value.insert.side_effect = lambda row: [dict(row)]
            r = client.post(
                "/api/documents/blank",
                json={"user_id": "u1", "file_name": "Scratch", "course_id": "c1",
                      "folder_id": "f1"},
            )

        assert r.status_code == 200
        row = t.return_value.insert.call_args[0][0]
        assert row["offering_id"] == "off-2"
        assert row["folder_id"] == "f1"
        assert r.json()["course_id"] == "c1"


# ── the document's notes ─────────────────────────────────────────────────────

STORED = {
    "document_id": "d1", "user_id": "u1", "title": "Determinants",
    "content": "<h2>Overview</h2>", "final": False,
    "created_at": "2026-11-01T00:00:00Z", "updated_at": "2026-11-01T00:00:00Z",
}


class TestDocumentNotes:
    def test_returns_what_is_stored_without_generating_again(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t, \
                patch_documents("doc_notes") as notes:
            _owned(t)
            notes.get_notes = AsyncMock(return_value=STORED)
            notes.save_notes = AsyncMock()
            r = client.get("/api/documents/doc/d1/notes?user_id=u1")

        assert r.status_code == 200
        assert r.json()["content"] == "<h2>Overview</h2>"
        # Generation happens once; a reload must not draft a second version.
        notes.save_notes.assert_not_awaited()

    def test_generates_and_stores_on_the_first_read(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t, \
                patch_documents("doc_notes") as notes, \
                patch_documents("generate", new=AsyncMock(return_value="<p>Drafted</p>")):
            _owned(t)
            notes.get_notes = AsyncMock(return_value=None)
            notes.source_text = AsyncMock(return_value=("text", {"file_name": "a.pdf"}))
            notes.save_notes = AsyncMock(return_value={**STORED, "content": "<p>Drafted</p>"})
            r = client.get("/api/documents/doc/d1/notes?user_id=u1")

        assert r.status_code == 200
        assert r.json()["content"] == "<p>Drafted</p>"
        assert notes.save_notes.await_args.kwargs["content"] == "<p>Drafted</p>"

    def test_saves_only_the_fields_it_is_given(self):
        """The editor autosaves a body on a debounce while Finalize flips a
        flag; neither may clear the other."""
        with _validated(), patch_documents("table", return_value=fake_table()) as t, \
                patch_documents("doc_notes") as notes:
            _owned(t)
            notes.MAX_CONTENT = 400_000
            notes.save_notes = AsyncMock(return_value=STORED)
            r = client.put("/api/documents/doc/d1/notes", json={"user_id": "u1", "final": True})

        assert r.status_code == 200
        kwargs = notes.save_notes.await_args.kwargs
        assert kwargs["final"] is True
        assert kwargs["content"] is None
        assert kwargs["title"] is None

    def test_refuses_a_body_past_the_cap(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t, \
                patch_documents("doc_notes") as notes:
            _owned(t)
            notes.MAX_CONTENT = 10
            notes.save_notes = AsyncMock()
            r = client.put(
                "/api/documents/doc/d1/notes",
                json={"user_id": "u1", "content": "x" * 50},
            )
        assert r.status_code == 413
        notes.save_notes.assert_not_awaited()

    def test_regenerate_replaces_the_body_and_clears_final(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t, \
                patch_documents("doc_notes") as notes, \
                patch_documents("generate", new=AsyncMock(return_value="<p>Fresh</p>")):
            _owned(t)
            notes.source_text = AsyncMock(return_value=("text", {"file_name": "a.pdf"}))
            notes.save_notes = AsyncMock(return_value={**STORED, "content": "<p>Fresh</p>"})
            r = client.post("/api/documents/doc/d1/notes/regenerate", json={"user_id": "u1"})

        assert r.status_code == 200
        kwargs = notes.save_notes.await_args.kwargs
        assert kwargs["content"] == "<p>Fresh</p>"
        assert kwargs["final"] is False

    def test_ask_needs_a_question(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t:
            _owned(t)
            r = client.post("/api/documents/doc/d1/notes/ask", json={"user_id": "u1", "message": " "})
        assert r.status_code == 400

    def test_ask_answers_with_the_reply(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t, \
                patch_documents("doc_notes") as notes, \
                patch_documents("run_agent", new=AsyncMock(return_value="  Try this.  ")):
            _owned(t)
            notes.MAX_SOURCE_CHARS = 24_000
            notes.source_text = AsyncMock(return_value=("text", {"file_name": "a.pdf"}))
            r = client.post(
                "/api/documents/doc/d1/notes/ask",
                json={"user_id": "u1", "message": "What is a determinant?",
                      "notes": "Some notes", "history": [{"role": "user", "text": "hi"}]},
            )

        assert r.status_code == 200
        assert r.json() == {"reply": "Try this."}

    def test_notes_for_a_document_that_is_not_yours_is_a_404(self):
        with _validated(), patch_documents("table", return_value=fake_table()) as t:
            _owned(t, [])
            r = client.get("/api/documents/doc/d1/notes?user_id=u1")
        assert r.status_code == 404


# ── the deploy-before-migrate window ─────────────────────────────────────────

class TestReadBeforeMigration:
    """A deploy can land before its migration runs. The Library's two new
    columns are display-only, so the list read drops them rather than failing:
    a thinner page beats no page. Anything else still surfaces."""

    def _missing_column_error(self):
        from httpx import Response
        err = Exception("Client error '400 Bad Request'")
        err.response = Response(
            400, text='{"code":"PGRST204","message":"Could not find the '
                      "'page_count' column of 'documents'\"}",
        )
        return err

    def test_falls_back_to_the_columns_that_exist(self):
        from services.documents import library

        calls = []

        async def aselect(cols, **kw):
            calls.append(cols)
            if "page_count" in cols:
                raise self._missing_column_error()
            return [{"id": "d1", "user_id": "u1", "offering_id": None}]

        with patch_documents("table", return_value=fake_table()) as t:
            t.return_value.aselect = aselect
            docs = __import__("asyncio").run(library.list_user_documents("u1"))

        assert len(calls) == 2
        assert "page_count" in calls[0] and "folder_id" in calls[0]
        assert "page_count" not in calls[1] and "folder_id" not in calls[1]
        assert docs[0]["id"] == "d1"

    def test_a_real_failure_still_fails(self):
        from services.documents import library

        async def aselect(cols, **kw):
            raise RuntimeError("the database is down")

        with patch_documents("table", return_value=fake_table()) as t:
            t.return_value.aselect = aselect
            with pytest.raises(RuntimeError, match="database is down"):
                __import__("asyncio").run(library.list_user_documents("u1"))
