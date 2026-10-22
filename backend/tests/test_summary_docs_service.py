"""Tests for services/summary_docs_service.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents._providers import clear_function_handlers, model_for, register_function_handler
from agents.summary_edit import summary_edit_agent
from services.summary_docs_service import (
    _build_ask_prompt,
    add_source,
    attach_summary_previews,
    body_to_prosemirror_nodes,
    create_suggestion,
    create_summary_doc,
    delete_summary_docs_for_document,
    get_summary_doc,
    keep_suggestion,
    list_versions,
    plaintext_for_primary_document,
    plaintext_from_prosemirror,
    prosemirror_doc_from_text,
    remove_source,
    restore_version,
    undo_suggestion,
    update_content,
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


class TestBodyToProsemirrorNodes:
    def test_single_paragraph(self):
        nodes = body_to_prosemirror_nodes("Just one paragraph.")
        assert nodes == [
            {"type": "paragraph", "content": [{"type": "text", "text": "Just one paragraph."}]},
        ]

    def test_multiple_paragraphs_blank_line_separated(self):
        nodes = body_to_prosemirror_nodes("First.\n\nSecond.")
        assert nodes == [
            {"type": "paragraph", "content": [{"type": "text", "text": "First."}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "Second."}]},
        ]

    def test_bullet_list_lines(self):
        nodes = body_to_prosemirror_nodes("- First law\n- Second law\n- Third law")
        assert nodes == [{
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "First law"}]}]},
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Second law"}]}]},
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Third law"}]}]},
            ],
        }]

    def test_numbered_list_lines(self):
        nodes = body_to_prosemirror_nodes("1. Step one\n2. Step two")
        assert nodes == [{
            "type": "orderedList",
            "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Step one"}]}]},
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Step two"}]}]},
            ],
        }]

    def test_inline_math_span(self):
        nodes = body_to_prosemirror_nodes("The formula is $F = ma$ for force.")
        assert nodes == [{
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "The formula is "},
                {"type": "math", "attrs": {"latex": "F = ma", "block": False}},
                {"type": "text", "text": " for force."},
            ],
        }]

    def test_block_math_span(self):
        nodes = body_to_prosemirror_nodes("$$\\lim_{x \\to a} f(x) = L$$")
        assert nodes == [{
            "type": "paragraph",
            "content": [{"type": "math", "attrs": {"latex": "\\lim_{x \\to a} f(x) = L", "block": True}}],
        }]

    def test_unclosed_math_delimiter_falls_back_to_literal_text(self):
        nodes = body_to_prosemirror_nodes("The price was $5 and that's it.")
        assert nodes == [{
            "type": "paragraph",
            "content": [{"type": "text", "text": "The price was $5 and that's it."}],
        }]

    def test_empty_body_returns_empty_list(self):
        assert body_to_prosemirror_nodes("") == []
        assert body_to_prosemirror_nodes("   \n\n  ") == []

    def test_mixed_paragraph_and_list_blocks(self):
        nodes = body_to_prosemirror_nodes("Intro paragraph.\n\n- Item one\n- Item two\n\nClosing paragraph.")
        assert len(nodes) == 3
        assert nodes[0]["type"] == "paragraph"
        assert nodes[1]["type"] == "bulletList"
        assert nodes[2]["type"] == "paragraph"


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
        assert result["sources"] == [{
            "document_id": "doc1", "file_name": "Lecture 4.pdf", "added_at": "t0",
            "has_original": False,
        }]
        assert len(result["pending_suggestions"]) == 1
        assert result["pending_suggestions"][0]["instruction"] == "shorter"

    def test_sources_report_has_original_per_document(self):
        from services.encryption import encrypt_json

        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": []}),
            "created_at": "t0", "updated_at": "t0",
        }

        def _select(name):
            m = MagicMock()
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_sources":
                m.select.return_value = [
                    {"document_id": "doc1", "added_at": "t0"},
                    {"document_id": "doc2", "added_at": "t1"},
                ]
            elif name == "documents":
                m.select.return_value = [
                    {"id": "doc1", "file_name": "notes.pdf", "original_storage_path": "doc1/notes.pdf"},
                    {"id": "doc2", "file_name": "slides.pptx", "original_storage_path": None},
                ]
            elif name == "summary_doc_suggestions":
                m.select.return_value = []
            return m

        with patch("services.summary_docs_service.table", side_effect=_select):
            doc = get_summary_doc("sd1", "u1")

        by_id = {s["document_id"]: s for s in doc["sources"]}
        assert by_id["doc1"]["has_original"] is True
        assert by_id["doc2"]["has_original"] is False


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

    def test_degradation_on_corrupted_version_content(self):
        from services.encryption import encrypt_json

        content_good = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Valid."}],
                }
            ],
        }
        doc_row = {
            "id": "sd1",
            "owner_user_id": "u1",
            "primary_document_id": "doc1",
            "content": encrypt_json(content_good),
            "created_at": "t0",
            "updated_at": "t0",
        }
        version_rows = [
            {
                "id": "v2",
                "summary_doc_id": "sd1",
                "content": encrypt_json(content_good),
                "trigger": "edit",
                "created_at": "t2",
            },
            {
                "id": "v_corrupt",
                "summary_doc_id": "sd1",
                "content": "corrupted_ciphertext_bytes",
                "trigger": "edit",
                "created_at": "t1",
            },
            {
                "id": "v1",
                "summary_doc_id": "sd1",
                "content": encrypt_json(content_good),
                "trigger": "initial",
                "created_at": "t0",
            },
        ]

        def _select(name):
            m = MagicMock()
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_versions":
                m.select.return_value = version_rows
            return m

        with patch("services.summary_docs_service.table", side_effect=_select):
            result = list_versions("sd1", "u1")

        assert result is not None
        assert len(result) == 3
        # The corrupted version should show the placeholder preview
        assert result[1]["id"] == "v_corrupt"
        assert result[1]["preview"] == "[Could not load this version]"
        # Other versions should still have valid previews
        assert result[0]["id"] == "v2"
        assert result[0]["preview"] == "Valid."
        assert result[2]["id"] == "v1"
        assert result[2]["preview"] == "Valid."


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
            "id": "sd1",
            "owner_user_id": "u1",
            "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": []}),
            "created_at": "t0",
            "updated_at": "t0",
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

    def test_returns_none_on_corrupted_version_content(self):
        from services.encryption import encrypt_json

        doc_row = {
            "id": "sd1",
            "owner_user_id": "u1",
            "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": []}),
            "created_at": "t0",
            "updated_at": "t0",
        }
        corrupted_version_row = {
            "id": "v_corrupt",
            "summary_doc_id": "sd1",
            "content": "corrupted_ciphertext_bytes",
            "trigger": "edit",
            "created_at": "t1",
        }

        mock_tables: dict = {}

        def _select(name):
            if name not in mock_tables:
                mock_tables[name] = MagicMock()
            m = mock_tables[name]
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_versions":
                m.select.return_value = [corrupted_version_row]
            return m

        with patch("services.summary_docs_service.table", side_effect=_select):
            result = restore_version("sd1", "u1", "v_corrupt")

        # restore_version should return None when decryption fails, matching
        # the behavior of "not owned" and "version not found" paths
        assert result is None


class TestKeepSuggestion:
    def test_applies_content_marks_kept_and_writes_version(self):
        from services.encryption import encrypt_json

        new_content = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Edited."}]}]}
        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": []}), "created_at": "t0", "updated_at": "t0",
        }
        suggestion_row = {"id": "sg1", "summary_doc_id": "sd1", "status": "pending"}

        # Cache one mock per table name — see the note in Task 4/Task 6's
        # tests: `table(name)` is called more than once for
        # "summary_doc_suggestions"/"summary_doc_versions" (inside
        # keep_suggestion, then again below for assertions), so a fresh
        # MagicMock() per call would hand the assertion a different,
        # never-called mock.
        mock_tables: dict = {}

        def _select(name):
            if name not in mock_tables:
                mock_tables[name] = MagicMock()
            m = mock_tables[name]
            if name == "summary_docs":
                m.select.return_value = [doc_row]
                m.update.return_value = [{**doc_row, "content": encrypt_json(new_content)}]
            elif name == "summary_doc_suggestions":
                m.select.return_value = [suggestion_row]
                m.update.return_value = [{}]
            elif name == "summary_doc_versions":
                m.insert.return_value = [{}]
            elif name in ("summary_doc_sources", "documents"):
                m.select.return_value = []
            return m

        with patch("services.summary_docs_service.table", side_effect=_select):
            result = keep_suggestion("sd1", "u1", "sg1", new_content)

        assert result["content"] == new_content
        suggestion_update = mock_tables["summary_doc_suggestions"].update.call_args[0][0]
        assert suggestion_update["status"] == "kept"
        version_insert = mock_tables["summary_doc_versions"].insert.call_args[0][0]
        assert version_insert["trigger"] == "ai_edit_kept"

    def test_returns_none_for_already_resolved_suggestion(self):
        from services.encryption import encrypt_json

        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": []}), "created_at": "t0", "updated_at": "t0",
        }

        def _select(name):
            m = MagicMock()
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_suggestions":
                m.select.return_value = [{"id": "sg1", "summary_doc_id": "sd1", "status": "kept"}]
            return m

        with patch("services.summary_docs_service.table", side_effect=_select):
            assert keep_suggestion("sd1", "u1", "sg1", {"type": "doc", "content": []}) is None


class TestUndoSuggestion:
    def test_marks_undone_without_touching_content(self):
        from services.encryption import encrypt_json

        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": []}), "created_at": "t0", "updated_at": "t0",
        }

        mock_tables: dict = {}

        def _select(name):
            if name not in mock_tables:
                mock_tables[name] = MagicMock()
            m = mock_tables[name]
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_suggestions":
                m.select.return_value = [{"id": "sg1", "summary_doc_id": "sd1", "status": "pending"}]
                m.update.return_value = [{}]
            return m

        with patch("services.summary_docs_service.table", side_effect=_select):
            assert undo_suggestion("sd1", "u1", "sg1") is True
        update_call = mock_tables["summary_doc_suggestions"].update.call_args[0][0]
        assert update_call["status"] == "undone"

    def test_returns_false_when_not_owned_or_not_pending(self):
        with patch("services.summary_docs_service.table") as mock_table:
            mock_table.return_value.select.return_value = []
            assert undo_suggestion("sd1", "u1", "sg1") is False


class TestAttachSummaryPreviews:
    def test_attaches_preview_id_and_source_count(self):
        from services.encryption import encrypt_json

        content = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Mitosis overview."}]}]}
        docs_in = [{"id": "doc1"}, {"id": "doc2"}]
        summary_rows = [
            {"id": "sd1", "primary_document_id": "doc1", "content": encrypt_json(content)},
        ]
        source_rows = [
            {"summary_doc_id": "sd1", "document_id": "doc1"},
            {"summary_doc_id": "sd1", "document_id": "doc3"},
        ]

        def _select(name):
            m = MagicMock()
            if name == "summary_docs":
                m.select.return_value = summary_rows
            elif name == "summary_doc_sources":
                m.select.return_value = source_rows
            return m

        with patch("services.summary_docs_service.table", side_effect=_select):
            attach_summary_previews(docs_in)

        assert docs_in[0]["summary_doc_id"] == "sd1"
        assert docs_in[0]["summary_preview"] == "Mitosis overview."
        assert docs_in[0]["summary_source_count"] == 2
        assert docs_in[1]["summary_doc_id"] is None
        assert docs_in[1]["summary_preview"] is None
        assert docs_in[1]["summary_source_count"] == 0

    def test_empty_input_is_a_no_op(self):
        with patch("services.summary_docs_service.table") as mock_table:
            attach_summary_previews([])
        mock_table.assert_not_called()

    def test_degrades_preview_to_none_on_corrupted_content(self):
        docs_in = [{"id": "doc1"}]
        summary_rows = [
            {"id": "sd1", "primary_document_id": "doc1", "content": "corrupted_ciphertext_bytes"},
        ]

        def _select(name):
            m = MagicMock()
            if name == "summary_docs":
                m.select.return_value = summary_rows
            elif name == "summary_doc_sources":
                m.select.return_value = []
            return m

        with patch("services.summary_docs_service.table", side_effect=_select):
            attach_summary_previews(docs_in)

        assert docs_in[0]["summary_doc_id"] == "sd1"
        assert docs_in[0]["summary_preview"] is None
        assert docs_in[0]["summary_source_count"] == 0


class TestDeleteSummaryDocsForDocument:
    def test_deletes_the_summary_doc_row(self):
        with patch("services.summary_docs_service.table") as mock_table:
            delete_summary_docs_for_document("doc1")
        mock_table.assert_called_once_with("summary_docs")
        mock_table.return_value.delete.assert_called_once_with(
            filters={"primary_document_id": "eq.doc1"}
        )


def _scripted_summary_edit(proposed_text: str):
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    def _handler(messages, info):
        return ModelResponse(parts=[
            ToolCallPart(tool_name="final_result", args={"proposed_text": proposed_text}),
        ])
    return _handler


class TestCreateSuggestion:
    def setup_method(self):
        clear_function_handlers()

    def teardown_method(self):
        clear_function_handlers()

    def test_creates_a_pending_suggestion_from_the_agent_output(self, monkeypatch):
        from services.encryption import encrypt_json

        # summary_edit_agent is built at module-import time with whatever
        # model `model_for("summary_edit")` returned THEN (real mode, by
        # default, in the hermetic suite) — registering a function handler
        # alone does nothing unless the agent is ALSO driven by a
        # FunctionModel for this call. `.override()` swaps the model for
        # just this `with` block (same pattern as
        # tests/test_e2e_function_handlers.py), so this test needs no
        # process-wide SAPLING_MODEL_MODE mutation that would leak into
        # unrelated tests sharing this pytest process.
        monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
        register_function_handler("summary_edit", _scripted_summary_edit("Shorter version."))
        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Original long text."}]},
            ]}),
            "created_at": "t0", "updated_at": "t0",
        }

        def _select(name):
            m = MagicMock()
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_sources":
                m.select.return_value = []
            elif name in ("documents", "summary_doc_suggestions"):
                m.select.return_value = []
                m.insert.return_value = [{
                    "id": "sg1", "summary_doc_id": "sd1", "anchor_from": 0, "anchor_to": 20,
                    "instruction": "ciphertext", "original_text": "ciphertext",
                    "proposed_text": "ciphertext", "status": "pending",
                    "created_at": "t0", "resolved_at": None,
                }]
            return m

        with patch("services.summary_docs_service.table", side_effect=_select), \
             summary_edit_agent.override(model=model_for("summary_edit")):
            result = create_suggestion(
                "sd1", "u1",
                anchor_from=0, anchor_to=20,
                instruction="make it shorter",
                original_text="Original long text.",
            )

        assert result["status"] == "pending"
        assert result["proposed_text"] == "Shorter version."

    def test_passes_a_reference_image_to_the_agent_as_binary_content(self, monkeypatch):
        from pydantic_ai import BinaryContent
        from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
        from services.encryption import encrypt_json

        captured_user_prompts = []

        def _capturing_handler(messages, info):
            for m in messages:
                if isinstance(m, ModelRequest):
                    for part in m.parts:
                        if isinstance(part, UserPromptPart):
                            captured_user_prompts.append(part.content)
            return ModelResponse(parts=[
                ToolCallPart(tool_name="final_result", args={"proposed_text": "Woven in."}),
            ])

        monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
        register_function_handler("summary_edit", _capturing_handler)
        doc_row = {
            "id": "sd1", "owner_user_id": "u1", "primary_document_id": "doc1",
            "content": encrypt_json({"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Existing text."}]},
            ]}),
            "created_at": "t0", "updated_at": "t0",
        }

        def _select(name):
            m = MagicMock()
            if name == "summary_docs":
                m.select.return_value = [doc_row]
            elif name == "summary_doc_sources":
                m.select.return_value = []
            elif name in ("documents", "summary_doc_suggestions"):
                m.select.return_value = []
                m.insert.return_value = [{
                    "id": "sg1", "summary_doc_id": "sd1", "anchor_from": None, "anchor_to": None,
                    "instruction": "ciphertext", "original_text": None,
                    "proposed_text": "ciphertext", "status": "pending",
                    "created_at": "t0", "resolved_at": None,
                }]
            return m

        with patch("services.summary_docs_service.table", side_effect=_select), \
             summary_edit_agent.override(model=model_for("summary_edit")):
            result = create_suggestion(
                "sd1", "u1",
                anchor_from=None, anchor_to=None,
                instruction="add the diagram",
                original_text=None,
                reference_image_bytes=b"\x89PNG fake bytes",
            )

        assert result["proposed_text"] == "Woven in."
        # The captured user-turn content is a list (text + the image part),
        # not a plain string, whenever a reference image is attached.
        assert len(captured_user_prompts) == 1
        parts = captured_user_prompts[0]
        assert isinstance(parts, list)
        image_parts = [p for p in parts if isinstance(p, BinaryContent)]
        assert len(image_parts) == 1
        assert image_parts[0].data == b"\x89PNG fake bytes"


class TestBuildAskPrompt:
    def test_whole_doc_ask_uses_whole_document_framing(self):
        prompt = _build_ask_prompt(
            instruction="make it shorter",
            selection_text=None,
            doc_plaintext="Some long document text.",
            sources=[],
            allow_surrounding_edits=False,
        )

        assert "the whole document" in prompt
        assert "highlighted section" not in prompt

    def test_allow_surrounding_edits_changes_the_scope_instruction(self):
        confined = _build_ask_prompt(
            instruction="make it shorter",
            selection_text="some text",
            doc_plaintext="Some long document text.",
            sources=[],
            allow_surrounding_edits=False,
        )
        relaxed = _build_ask_prompt(
            instruction="make it shorter",
            selection_text="some text",
            doc_plaintext="Some long document text.",
            sources=[],
            allow_surrounding_edits=True,
        )

        assert confined != relaxed
        assert "ONLY rewrite the exact text above" in confined
        assert "may also lightly adjust" in relaxed

    def test_reference_text_is_added_as_its_own_block(self):
        prompt = _build_ask_prompt(
            instruction="add this",
            selection_text=None,
            doc_plaintext="Existing summary text.",
            sources=[],
            allow_surrounding_edits=False,
            reference_text="A circled excerpt from the DOCX source.",
        )
        assert "A circled excerpt from the DOCX source." in prompt
        assert "pointed at by the student" in prompt

    def test_has_reference_image_adds_a_note_without_the_image_itself(self):
        prompt = _build_ask_prompt(
            instruction="add this",
            selection_text=None,
            doc_plaintext="Existing summary text.",
            sources=[],
            allow_surrounding_edits=False,
            has_reference_image=True,
        )
        assert "image is attached" in prompt.lower()


class TestPlaintextForPrimaryDocument:
    def test_returns_plaintext_of_the_docs_summary(self):
        from services.encryption import encrypt_json

        content = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Intro to sorting."}]}]}
        with patch("services.summary_docs_service.table") as mock_table:
            mock_table.return_value.select.return_value = [{"content": encrypt_json(content)}]
            result = plaintext_for_primary_document("doc1")
        assert result == "Intro to sorting."
        mock_table.return_value.select.assert_called_once_with(
            "content", filters={"primary_document_id": "eq.doc1"}, limit=1,
        )

    def test_returns_none_when_no_summary_doc_exists(self):
        with patch("services.summary_docs_service.table") as mock_table:
            mock_table.return_value.select.return_value = []
            assert plaintext_for_primary_document("doc1") is None

    def test_degrades_to_none_on_corrupted_content(self):
        with patch("services.summary_docs_service.table") as mock_table:
            mock_table.return_value.select.return_value = [{"content": "corrupted_ciphertext_bytes"}]
            assert plaintext_for_primary_document("doc1") is None

    def test_truncates_a_long_summary_for_the_scan_prompt(self):
        from services.encryption import encrypt_json

        long_text = "A" * 10_000
        content = prosemirror_doc_from_text(long_text)
        with patch("services.summary_docs_service.table") as mock_table:
            mock_table.return_value.select.return_value = [{"content": encrypt_json(content)}]
            result = plaintext_for_primary_document("doc1")
        assert len(result) == 4000
