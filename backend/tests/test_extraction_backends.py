"""
Unit tests for services/extraction_backends/*.

Coverage:
  - docling_backend — DocumentConverter is mocked; validates markdown parsing,
    frontmatter stripping, and fallback-page signal logic.
  - got_ocr_backend — AutoModel.from_pretrained is mocked to simulate both
    success and GotOcrUnavailableError paths.
  - tesseract_backend — relocated logic still works identically.
"""
import io
import os
from unittest.mock import MagicMock, patch

import pytest

from services.extraction_backends import tesseract_backend
from services.extraction_backends.docling_backend import (
    DoclingUnavailableError,
    _detect_math_without_latex,
    _strip_frontmatter,
    _strip_image_placeholders,
    extract_pdf_with_docling,
    reset_converter_cache,
)


@pytest.fixture(autouse=True)
def _reset_docling_converter_cache():
    reset_converter_cache()
    yield
    reset_converter_cache()
from services.extraction_backends.got_ocr_backend import (
    GotOcrUnavailableError,
    extract_page_with_got_ocr,
    reset_model_cache,
)


# ── Docling backend ──────────────────────────────────────────────────────────

class TestDoclingStripFrontmatter:
    def test_strips_yaml_frontmatter(self):
        md = "---\ntitle: x\n---\n# Heading"
        assert _strip_frontmatter(md) == "# Heading"

    def test_no_frontmatter_unchanged(self):
        assert _strip_frontmatter("# Heading") == "# Heading"

    def test_empty_string(self):
        assert _strip_frontmatter("") == ""


class TestDoclingImagePlaceholders:
    def test_strips_single_placeholder(self):
        assert _strip_image_placeholders("<!-- image -->") == ""

    def test_strips_placeholder_with_surrounding_text(self):
        result = _strip_image_placeholders("before\n\n<!-- image -->\n\nafter")
        assert "<!-- image -->" not in result
        assert "before" in result
        assert "after" in result

    def test_handles_no_placeholders(self):
        assert _strip_image_placeholders("plain text") == "plain text"


class TestDoclingMathDetection:
    def test_detects_unicode_math(self):
        assert _detect_math_without_latex("x ≥ 0 and y ≠ 1") is True

    def test_detects_superscript(self):
        assert _detect_math_without_latex("E = mc^2 for c_{0}") is True

    def test_latex_present_skips_fallback(self):
        assert _detect_math_without_latex("\\frac{a}{b}") is False

    def test_plain_text_no_math(self):
        assert _detect_math_without_latex("Hello world") is False


def _make_doc_mock(pages: dict, tables=None, page_markdowns: dict | None = None):
    """Build a mock Docling doc.

    pages: {page_no: placeholder} — drives the iteration order.
    page_markdowns: {page_no: md_str} returned by export_to_markdown(page_no=...).
    """
    doc = MagicMock()
    doc.pages = pages
    doc.tables = tables or []

    def export_to_markdown(page_no=None, **kwargs):
        if page_no is not None and page_markdowns and page_no in page_markdowns:
            return page_markdowns[page_no]
        if page_markdowns:
            return "\n\n".join(page_markdowns.values())
        return ""

    doc.export_to_markdown = MagicMock(side_effect=export_to_markdown)
    return doc


class TestExtractPdfWithDocling:
    def test_raises_when_docling_missing(self, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, "docling.document_converter", None)
        with pytest.raises(DoclingUnavailableError):
            extract_pdf_with_docling(b"fake pdf")

    def test_returns_merged_markdown_and_metadata(self):
        page_mds = {1: "# Intro\n\nHello world " * 3, 2: "Short"}
        doc = _make_doc_mock(pages={1: object(), 2: object()}, page_markdowns=page_mds)
        result = MagicMock()
        result.document = doc

        converter = MagicMock()
        converter.convert = MagicMock(return_value=result)

        with (
            patch("docling.document_converter.DocumentConverter", return_value=converter),
            patch("docling.datamodel.base_models.DocumentStream") as mock_stream,
        ):
            mock_stream.side_effect = lambda name, stream: MagicMock()
            markdown, page_count, metadata = extract_pdf_with_docling(b"fake pdf")

        assert "Intro" in markdown
        assert page_count == 2
        assert len(metadata["per_page_markdown"]) == 2
        assert len(metadata["per_page_char_counts"]) == 2
        # Page 2 ("Short") has 5 chars < 40 threshold → fallback flagged
        assert 1 in metadata["fallback_pages"]

    def test_flags_math_page_for_fallback(self):
        page_mds = {1: "Integrate x² where x ≥ 0. " * 5}
        doc = _make_doc_mock(pages={1: object()}, page_markdowns=page_mds)
        result = MagicMock()
        result.document = doc
        converter = MagicMock()
        converter.convert = MagicMock(return_value=result)

        with (
            patch("docling.document_converter.DocumentConverter", return_value=converter),
            patch("docling.datamodel.base_models.DocumentStream"),
        ):
            _, _, metadata = extract_pdf_with_docling(b"fake pdf")

        assert metadata["per_page_math_flags"][0] is True
        assert 0 in metadata["fallback_pages"]


# ── GOT-OCR backend ──────────────────────────────────────────────────────────

class TestGotOcrBackend:
    def setup_method(self):
        reset_model_cache()

    def teardown_method(self):
        reset_model_cache()

    def test_raises_when_disabled(self, monkeypatch):
        monkeypatch.setenv("GOT_OCR_ENABLED", "false")
        with pytest.raises(GotOcrUnavailableError):
            extract_page_with_got_ocr(b"fake image")

    def test_raises_when_weights_fail(self, monkeypatch):
        monkeypatch.setenv("GOT_OCR_ENABLED", "true")

        def _fail(*args, **kwargs):
            raise OSError("no weights")

        with (
            patch("transformers.AutoTokenizer.from_pretrained", side_effect=_fail),
            patch("transformers.AutoModel.from_pretrained", side_effect=_fail),
        ):
            with pytest.raises(GotOcrUnavailableError):
                extract_page_with_got_ocr(b"fake image")

    def test_disabled_flag_short_circuits_even_with_cached_model(self, monkeypatch):
        """Once loaded, the model cache must not bypass the GOT_OCR_ENABLED gate
        if the flag is later flipped to false. Regression for Apr-2026 review."""
        from services.extraction_backends import got_ocr_backend as g
        # Pretend a model was previously cached in this process
        g._CACHED_MODEL = MagicMock()
        g._CACHED_TOKENIZER = MagicMock()
        monkeypatch.setenv("GOT_OCR_ENABLED", "false")
        with pytest.raises(GotOcrUnavailableError):
            extract_page_with_got_ocr(b"fake image")

    def test_returns_chat_output(self, monkeypatch):
        monkeypatch.setenv("GOT_OCR_ENABLED", "true")

        mock_model = MagicMock()
        mock_model.eval = MagicMock(return_value=mock_model)
        mock_model.chat = MagicMock(return_value="  \\frac{1}{2}  ")
        mock_tokenizer = MagicMock()

        # Provide a minimal valid PNG so Pillow can open it
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (10, 10), color="white").save(buf, format="PNG")
        image_bytes = buf.getvalue()

        with (
            patch("transformers.AutoTokenizer.from_pretrained", return_value=mock_tokenizer),
            patch("transformers.AutoModel.from_pretrained", return_value=mock_model),
        ):
            result = extract_page_with_got_ocr(image_bytes, ocr_type="format")

        assert result == "\\frac{1}{2}"
        mock_model.chat.assert_called_once()


# ── Tesseract backend (relocated) ────────────────────────────────────────────

class TestTesseractBackend:
    def test_docx_impl(self):
        mock_result = MagicMock()
        mock_result.value = "  Hello  "
        with patch("mammoth.extract_raw_text", return_value=mock_result):
            assert tesseract_backend.extract_text_from_docx_impl(b"x") == "Hello"

    def test_pptx_impl_empty(self):
        prs = MagicMock()
        prs.slides = []
        with patch("pptx.Presentation", return_value=prs):
            assert tesseract_backend.extract_text_from_pptx_impl(b"") == ""

    def test_tesseract_available_returns_tuple(self):
        ok, ver = tesseract_backend.tesseract_available()
        assert isinstance(ok, bool)
        assert ver is None or isinstance(ver, str)
