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
