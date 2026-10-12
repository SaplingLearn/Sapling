"""Tests for services/summary_docs_service.py."""
from __future__ import annotations

from services.summary_docs_service import (
    plaintext_from_prosemirror,
    prosemirror_doc_from_text,
)


class TestProsemirrorDocFromText:
    def test_splits_on_blank_lines_into_paragraphs(self):
        doc = prosemirror_doc_from_text("First paragraph.\n\nSecond paragraph.")
        assert doc == {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "First paragraph."}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Second paragraph."}]},
            ],
        }

    def test_empty_text_yields_empty_doc(self):
        assert prosemirror_doc_from_text("") == {"type": "doc", "content": []}
        assert prosemirror_doc_from_text("   \n\n  ") == {"type": "doc", "content": []}

    def test_single_paragraph_no_blank_lines(self):
        doc = prosemirror_doc_from_text("Just one paragraph of text.")
        assert doc == {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Just one paragraph of text."}]},
            ],
        }


class TestPlaintextFromProsemirror:
    def test_joins_paragraph_text_with_blank_lines(self):
        doc = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Alpha."}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Beta."}]},
            ],
        }
        assert plaintext_from_prosemirror(doc) == "Alpha.\n\nBeta."

    def test_concatenates_multiple_text_nodes_in_one_paragraph(self):
        doc = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "Bold "},
                    {"type": "text", "text": "and plain."},
                ]},
            ],
        }
        assert plaintext_from_prosemirror(doc) == "Bold and plain."

    def test_empty_doc_yields_empty_string(self):
        assert plaintext_from_prosemirror({"type": "doc", "content": []}) == ""

    def test_truncates_to_max_chars(self):
        doc = prosemirror_doc_from_text("A" * 500)
        assert len(plaintext_from_prosemirror(doc, max_chars=50)) == 50


from unittest.mock import MagicMock, patch

from services.summary_docs_service import create_summary_doc, get_summary_doc


class TestCreateSummaryDoc:
    def test_inserts_doc_source_and_initial_version(self):
        inserted_doc = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": "ciphertext", "created_at": "t0", "updated_at": "t0",
        }
        fake_tables = {
            "summary_docs": MagicMock(insert=MagicMock(return_value=[inserted_doc])),
            "summary_doc_sources": MagicMock(insert=MagicMock(return_value=[{}])),
            "summary_doc_versions": MagicMock(insert=MagicMock(return_value=[{}])),
        }
        with patch(
            "services.summary_docs_service.table",
            side_effect=lambda name: fake_tables[name],
        ):
            result = create_summary_doc(
                user_id="u1", primary_document_id="doc1",
                seed_text="The main idea.",
            )

        assert result["id"] == "sd1"
        assert result["content"] == {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "The main idea."}]}],
        }
        fake_tables["summary_doc_sources"].insert.assert_called_once_with(
            {"summary_doc_id": "sd1", "document_id": "doc1"}
        )
        version_call = fake_tables["summary_doc_versions"].insert.call_args[0][0]
        assert version_call["summary_doc_id"] == "sd1"
        assert version_call["trigger"] == "initial"


class TestGetSummaryDoc:
    def test_returns_none_when_not_owned(self):
        with patch("services.summary_docs_service.table") as mock_table:
            mock_table.return_value.select.return_value = []
            assert get_summary_doc("sd1", "u1") is None

    def test_attaches_sources_and_pending_suggestions(self):
        from services.encryption import encrypt_json

        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": []}),
            "created_at": "t0", "updated_at": "t0",
        }
        source_rows = [{"document_id": "doc1", "added_at": "t0"}]
        file_rows = [{"id": "doc1", "file_name": "Lecture 4.pdf"}]
        suggestion_rows = [{
            "id": "sg1", "summary_doc_id": "sd1", "anchor_from": 0, "anchor_to": 5,
            "instruction": "shorter", "original_text": "Hello", "proposed_text": "Hi",
            "status": "pending", "created_at": "t0", "resolved_at": None,
        }]

        def _select(name):
            m = MagicMock()
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_sources":
                m.select.return_value = source_rows
            elif name == "documents":
                m.select.return_value = file_rows
            elif name == "summary_doc_suggestions":
                m.select.return_value = suggestion_rows
            return m

        with patch("services.summary_docs_service.table", side_effect=_select):
            result = get_summary_doc("sd1", "u1")

        assert result["content"] == {"type": "doc", "content": []}
        assert result["sources"] == [{"document_id": "doc1", "file_name": "Lecture 4.pdf", "added_at": "t0"}]
        assert len(result["pending_suggestions"]) == 1
        assert result["pending_suggestions"][0]["instruction"] == "shorter"


from services.summary_docs_service import add_source, remove_source


class TestAddSource:
    def test_adds_source_and_writes_version(self):
        from services.encryption import encrypt_json

        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": []}),
            "created_at": "t0", "updated_at": "t0",
        }

        mock_tables = {}

        def _table(name):
            if name not in mock_tables:
                mock_tables[name] = MagicMock()
            m = mock_tables[name]
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_sources":
                m.select.return_value = []
                m.insert.return_value = [{}]
            elif name == "documents":
                m.select.return_value = []
            elif name == "summary_doc_suggestions":
                m.select.return_value = []
            elif name == "summary_doc_versions":
                m.insert.return_value = [{}]
            return m

        with patch("services.summary_docs_service.table", side_effect=_table):
            result = add_source("sd1", "u1", "doc2")

        assert result is not None
        insert_calls = mock_tables["summary_doc_sources"].insert.call_args_list
        assert len(insert_calls) > 0
        assert insert_calls[-1][0][0] == {"summary_doc_id": "sd1", "document_id": "doc2"}

    def test_returns_none_when_not_owned(self):
        with patch("services.summary_docs_service.table") as mock_table:
            mock_table.return_value.select.return_value = []
            assert add_source("sd1", "u1", "doc2") is None


class TestRemoveSource:
    def test_deletes_source_row_and_writes_version(self):
        from services.encryption import encrypt_json

        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": []}),
            "created_at": "t0", "updated_at": "t0",
        }

        mock_tables = {}

        def _table(name):
            if name not in mock_tables:
                mock_tables[name] = MagicMock()
            m = mock_tables[name]
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_sources":
                m.select.return_value = [
                    {"document_id": "doc1", "added_at": "t0"},
                    {"document_id": "doc2", "added_at": "t1"}
                ]
                m.delete.return_value = [{}]
            elif name == "documents":
                m.select.return_value = [
                    {"id": "doc1", "file_name": "Doc 1.pdf"},
                    {"id": "doc2", "file_name": "Doc 2.pdf"},
                ]
            elif name == "summary_doc_suggestions":
                m.select.return_value = []
            elif name == "summary_doc_versions":
                m.insert.return_value = [{}]
            return m

        with patch("services.summary_docs_service.table", side_effect=_table):
            result = remove_source("sd1", "u1", "doc2")

        assert result is not None
        mock_tables["summary_doc_sources"].delete.assert_called_with(
            filters={"summary_doc_id": "eq.sd1", "document_id": "eq.doc2"}
        )

    def test_refuses_to_remove_the_primary_document(self):
        from services.encryption import encrypt_json

        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": []}),
            "created_at": "t0", "updated_at": "t0",
        }

        mock_tables = {}

        def _table(name):
            if name not in mock_tables:
                mock_tables[name] = MagicMock()
            m = mock_tables[name]
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_sources":
                m.select.return_value = [{"document_id": "doc1", "added_at": "t0"}]
            elif name == "documents":
                m.select.return_value = [{"id": "doc1", "file_name": "Doc 1.pdf"}]
            elif name == "summary_doc_suggestions":
                m.select.return_value = []
            return m

        with patch("services.summary_docs_service.table", side_effect=_table):
            result = remove_source("sd1", "u1", "doc1")
        assert result == "primary"


from services.summary_docs_service import update_content


class TestUpdateContent:
    def test_updates_content_without_writing_a_version(self):
        new_content = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Edited."}]}]}

        def _select(name):
            m = MagicMock()
            if name == "summary_docs":
                m.update.return_value = [{
                    "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
                    "content": "ciphertext", "created_at": "t0", "updated_at": "t1",
                }]
            return m

        with patch("services.summary_docs_service.table", side_effect=_select) as mock_table, \
             patch("services.summary_docs_service.decrypt_json", return_value=new_content), \
             patch("services.summary_docs_service.encrypt_json", return_value="ciphertext") as enc:
            result = update_content("sd1", "u1", new_content)

        assert result["content"] == new_content
        enc.assert_called_once_with(new_content)
        # update_content writes no version row (see Task header docstring) —
        # confirm `table("summary_doc_versions")` was never called.
        called_names = [c.args[0] for c in mock_table.call_args_list if c.args]
        assert "summary_doc_versions" not in called_names

    def test_returns_none_when_not_owned(self):
        with patch("services.summary_docs_service.table") as mock_table:
            mock_table.return_value.update.return_value = []
            assert update_content("sd1", "u1", {"type": "doc", "content": []}) is None


from services.summary_docs_service import list_versions, restore_version


class TestListVersions:
    def test_returns_versions_with_plaintext_preview(self):
        from services.encryption import encrypt_json

        content_a = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "First."}]}]}
        content_b = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Second."}]}]}
        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json(content_b), "created_at": "t0", "updated_at": "t1",
        }
        version_rows = [
            {"id": "v2", "summary_doc_id": "sd1", "content": encrypt_json(content_b), "trigger": "ai_edit_kept", "created_at": "t1"},
            {"id": "v1", "summary_doc_id": "sd1", "content": encrypt_json(content_a), "trigger": "initial", "created_at": "t0"},
        ]

        def _select(name):
            m = MagicMock()
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_versions":
                m.select.return_value = version_rows
            elif name in ("summary_doc_sources", "summary_doc_suggestions", "documents"):
                m.select.return_value = []
            return m

        with patch("services.summary_docs_service.table", side_effect=_select):
            result = list_versions("sd1", "u1")

        assert [v["id"] for v in result] == ["v2", "v1"]
        assert result[0]["preview"] == "Second."
        assert result[0]["trigger"] == "ai_edit_kept"

    def test_returns_none_when_not_owned(self):
        with patch("services.summary_docs_service.table") as mock_table:
            mock_table.return_value.select.return_value = []
            assert list_versions("sd1", "u1") is None


class TestRestoreVersion:
    def test_restores_content_and_writes_a_new_version(self):
        from services.encryption import encrypt_json

        old_content = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Old."}]}]}
        current_content = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Current."}]}]}
        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json(current_content), "created_at": "t0", "updated_at": "t1",
        }
        version_row = {"id": "v1", "summary_doc_id": "sd1", "content": encrypt_json(old_content), "trigger": "initial", "created_at": "t0"}

        # Cache one mock per table name — `table(name)` is called more than
        # once for "summary_docs"/"summary_doc_versions" during
        # restore_version's own execution AND again below when the test
        # inspects call history, so a fresh MagicMock() per call (no cache)
        # would hand the assertion a different, never-called mock.
        mock_tables: dict = {}

        def _select(name):
            if name not in mock_tables:
                mock_tables[name] = MagicMock()
            m = mock_tables[name]
            if name == "summary_docs":
                m.select.return_value = [doc_row]
                m.update.return_value = [{**doc_row, "content": encrypt_json(old_content)}]
            elif name == "summary_doc_versions":
                m.select.return_value = [version_row]
                m.insert.return_value = [{}]
            elif name in ("summary_doc_sources", "summary_doc_suggestions", "documents"):
                m.select.return_value = []
            return m

        with patch("services.summary_docs_service.table", side_effect=_select):
            result = restore_version("sd1", "u1", "v1")

        assert result["content"] == old_content
        version_insert = mock_tables["summary_doc_versions"].insert.call_args[0][0]
        assert version_insert["trigger"] == "restored"

    def test_returns_none_for_unknown_version(self):
        from services.encryption import encrypt_json

        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": []}), "created_at": "t0", "updated_at": "t0",
        }

        def _select(name):
            m = MagicMock()
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_versions":
                m.select.return_value = []
            return m

        with patch("services.summary_docs_service.table", side_effect=_select):
            assert restore_version("sd1", "u1", "missing") is None
