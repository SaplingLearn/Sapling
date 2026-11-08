"""Routes for Library folders (/api/library, migration 20261108225556).

The session user (stubbed by conftest as ``user_andres``) is the only identity;
every query is pinned to it, and folder moves refuse a folder in another course.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)
ME = "user_andres"


class FakeTable:
    """Records calls per table name; `select` answers from a queue per table."""

    def __init__(self, selects=None, inserts=None):
        self.selects = {k: list(v) for k, v in (selects or {}).items()}
        self.inserts = inserts or {}
        self.calls: list[tuple] = []

    def __call__(self, name):
        t = MagicMock()

        def select(cols="*", filters=None, **kw):
            self.calls.append((name, "select", filters))
            q = self.selects.get(name) or [[]]
            return q.pop(0) if len(q) > 1 else q[0]

        def insert(row):
            self.calls.append((name, "insert", row))
            return [{"id": "f-new", **row}] if name not in self.inserts else self.inserts[name]

        def update(data, filters=None, **kw):
            self.calls.append((name, "update", data, filters))
            return [data]

        def delete(filters=None):
            self.calls.append((name, "delete", filters))
            return []

        t.select.side_effect = select
        t.insert.side_effect = insert
        t.update.side_effect = update
        t.delete.side_effect = delete
        return t

    def of(self, name, op):
        return [c for c in self.calls if c[0] == name and c[1] == op]


def _patch(fake):
    return patch("services.library_folders.table", fake)


class TestListFolders:
    def test_returns_own_folders_and_placements(self):
        fake = FakeTable(selects={
            "library_folders": [[{"id": "f1", "course_id": "c1", "name": "Labs", "created_at": "x"}]],
            "documents": [[{"id": "d1", "folder_id": "f1"}]],
        })
        with _patch(fake):
            r = client.get("/api/library/folders")
        assert r.status_code == 200
        body = r.json()
        assert body["folders"][0]["name"] == "Labs"
        assert body["placements"] == {"d1": "f1"}
        for _, _, filters in fake.of("library_folders", "select") + fake.of("documents", "select"):
            assert filters["user_id"] == f"eq.{ME}"
        assert fake.of("documents", "select")[0][2]["deleted_at"] == "is.null"


class TestCreateFolder:
    def test_creates_under_an_enrolled_course(self):
        fake = FakeTable()
        with _patch(fake), patch("services.library_folders.user_offering_ids_for_course", return_value=["o1"]):
            r = client.post("/api/library/folders", json={"name": "  Midterm Prep ", "course_id": "c1"})
        assert r.status_code == 200
        assert r.json()["name"] == "Midterm Prep"
        row = fake.of("library_folders", "insert")[0][2]
        assert row["user_id"] == ME and row["course_id"] == "c1"

    def test_refuses_a_course_the_user_is_not_in(self):
        fake = FakeTable()
        with _patch(fake), patch("services.library_folders.user_offering_ids_for_course", return_value=[]):
            r = client.post("/api/library/folders", json={"name": "X", "course_id": "c-other"})
        assert r.status_code == 404
        assert not fake.of("library_folders", "insert")

    def test_uncategorized_folder_needs_no_course(self):
        fake = FakeTable()
        with _patch(fake):
            r = client.post("/api/library/folders", json={"name": "Loose"})
        assert r.status_code == 200
        assert fake.of("library_folders", "insert")[0][2]["course_id"] is None

    def test_blank_name_is_400(self):
        with _patch(FakeTable()):
            r = client.post("/api/library/folders", json={"name": "   "})
        assert r.status_code == 400


class TestRenameAndDeleteFolder:
    def test_rename_own_folder(self):
        fake = FakeTable(selects={"library_folders": [[{"id": "f1", "user_id": ME, "course_id": None, "name": "a"}]]})
        with _patch(fake):
            r = client.patch("/api/library/folders/f1", json={"name": "Essay Sources"})
        assert r.status_code == 200 and r.json()["name"] == "Essay Sources"
        _, _, data, filters = fake.of("library_folders", "update")[0]
        assert data == {"name": "Essay Sources"} and filters["user_id"] == f"eq.{ME}"

    def test_someone_elses_folder_is_404(self):
        fake = FakeTable(selects={"library_folders": [[]]})
        with _patch(fake):
            assert client.patch("/api/library/folders/f9", json={"name": "x"}).status_code == 404
            assert client.delete("/api/library/folders/f9").status_code == 404
        assert not fake.of("library_folders", "update")
        assert not fake.of("library_folders", "delete")

    def test_delete_own_folder(self):
        fake = FakeTable(selects={"library_folders": [[{"id": "f1", "user_id": ME}]]})
        with _patch(fake):
            r = client.delete("/api/library/folders/f1")
        assert r.status_code == 200 and r.json() == {"deleted": True}
        assert fake.of("library_folders", "delete")[0][2] == {"id": "eq.f1", "user_id": f"eq.{ME}"}


class TestMoveDocuments:
    def test_moves_into_a_folder_of_the_same_course(self):
        fake = FakeTable(selects={
            "documents": [[{"id": "d1", "offering_id": "o1"}, {"id": "d2", "offering_id": "o1"}]],
            "library_folders": [[{"id": "f1", "user_id": ME, "course_id": "c1"}]],
        })
        with _patch(fake), patch("services.library_folders.offering_course_id", return_value="c1"):
            r = client.put("/api/library/documents/folder", json={"document_ids": ["d1", "d2"], "folder_id": "f1"})
        assert r.status_code == 200 and r.json()["moved"] == 2
        _, _, data, filters = fake.of("documents", "update")[0]
        assert data == {"folder_id": "f1"}
        assert filters["user_id"] == f"eq.{ME}" and filters["id"] == 'in.("d1","d2")'

    def test_refuses_a_folder_in_another_course(self):
        fake = FakeTable(selects={
            "documents": [[{"id": "d1", "offering_id": "o1"}]],
            "library_folders": [[{"id": "f1", "user_id": ME, "course_id": "c2"}]],
        })
        with _patch(fake), patch("services.library_folders.offering_course_id", return_value="c1"):
            r = client.put("/api/library/documents/folder", json={"document_ids": ["d1"], "folder_id": "f1"})
        assert r.status_code == 409
        assert not fake.of("documents", "update")

    def test_a_document_that_is_not_mine_refuses_the_whole_move(self):
        fake = FakeTable(selects={"documents": [[{"id": "d1", "offering_id": "o1"}]]})
        with _patch(fake):
            r = client.put("/api/library/documents/folder", json={"document_ids": ["d1", "d-other"], "folder_id": None})
        assert r.status_code == 404
        assert not fake.of("documents", "update")

    def test_null_folder_takes_documents_out(self):
        fake = FakeTable(selects={"documents": [[{"id": "d1", "offering_id": "o1"}]]})
        with _patch(fake):
            r = client.put("/api/library/documents/folder", json={"document_ids": ["d1"], "folder_id": None})
        assert r.status_code == 200
        assert fake.of("documents", "update")[0][2] == {"folder_id": None}

    def test_empty_move_is_400(self):
        with _patch(FakeTable()):
            r = client.put("/api/library/documents/folder", json={"document_ids": [], "folder_id": None})
        assert r.status_code == 400


class TestRenameDocument:
    def test_keeps_the_extension(self):
        fake = FakeTable(selects={"documents": [[{"id": "d1", "file_name": "Lecture 7.pdf"}]]})
        with _patch(fake):
            r = client.patch("/api/library/documents/d1", json={"file_name": "Determinants"})
        assert r.status_code == 200 and r.json()["file_name"] == "Determinants.pdf"
        _, _, data, filters = fake.of("documents", "update")[0]
        assert data == {"file_name": "Determinants.pdf"}
        assert filters == {"id": "eq.d1", "user_id": f"eq.{ME}"}

    def test_unknown_document_is_404(self):
        fake = FakeTable(selects={"documents": [[]]})
        with _patch(fake):
            r = client.patch("/api/library/documents/nope", json={"file_name": "x"})
        assert r.status_code == 404
        assert not fake.of("documents", "update")
