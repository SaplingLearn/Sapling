"""
Unit tests for services/extraction_service.py

Tests cover:
  - _clean_text          — whitespace normalisation
  - extract_text_from_docx  — delegates to mammoth
  - extract_text_from_pptx  — iterates slides/shapes/paragraphs
  - extract_text_from_file  — routing by filename extension and content-type
"""
import io
import pytest
from unittest.mock import MagicMock, patch, call

from services.extraction_service import (
    _clean_text,
    extract_text_from_docx,
    extract_text_from_pptx,
    extract_text_from_file,
)


# ── _clean_text ───────────────────────────────────────────────────────────────

class TestCleanText:
    def test_strips_trailing_whitespace_on_lines(self):
        assert _clean_text("hello   \nworld  ") == "hello\nworld"

    def test_strips_leading_and_trailing_blank_lines(self):
        assert _clean_text("\n\nhello\n\n") == "hello"

    def test_empty_string_returns_empty(self):
        assert _clean_text("") == ""

    def test_preserves_internal_blank_lines(self):
        result = _clean_text("line1\n\nline2")
        assert "line1" in result
        assert "line2" in result


# ── extract_text_from_docx ────────────────────────────────────────────────────

class TestExtractTextFromDocx:
    def test_returns_extracted_text(self):
        mock_result = MagicMock()
        mock_result.value = "  Chapter 1: Introduction  \n"

        # mammoth is imported lazily inside extract_text_from_docx; patch at the module level
        with patch("mammoth.extract_raw_text", return_value=mock_result):
            result = extract_text_from_docx(b"fake docx bytes")

        assert result == "Chapter 1: Introduction"

    def test_passes_bytes_as_bytesio(self):
        mock_result = MagicMock()
        mock_result.value = "text"

        with patch("mammoth.extract_raw_text", return_value=mock_result) as mock_fn:
            extract_text_from_docx(b"docx content")

            args = mock_fn.call_args[0]
            assert isinstance(args[0], io.BytesIO)
            assert args[0].read() == b"docx content"

    def test_empty_docx_returns_empty_string(self):
        mock_result = MagicMock()
        mock_result.value = ""

        with patch("mammoth.extract_raw_text", return_value=mock_result):
            assert extract_text_from_docx(b"") == ""


# ── extract_text_from_pptx ────────────────────────────────────────────────────

def _make_pptx_mock(slide_texts: list[list[str]]):
    """
    Build a mock pptx.Presentation where each inner list is the text of
    paragraphs on that slide (one shape per paragraph for simplicity).
    """
    slides = []
    for para_texts in slide_texts:
        shapes = []
        for text in para_texts:
            run = MagicMock()
            run.text = text
            para = MagicMock()
            para.runs = [run]
            tf = MagicMock()
            tf.paragraphs = [para]
            shape = MagicMock()
            shape.has_text_frame = True
            shape.text_frame = tf
            shapes.append(shape)
        slide = MagicMock()
        slide.shapes = shapes
        slides.append(slide)

    prs = MagicMock()
    prs.slides = slides
    return prs


class TestExtractTextFromPptx:
    def test_extracts_text_from_single_slide(self):
        prs = _make_pptx_mock([["Hello world"]])

        # Presentation is imported as `from pptx import Presentation` inside the function
        with patch("pptx.Presentation", return_value=prs):
            result = extract_text_from_pptx(b"fake pptx")

        assert "Hello world" in result

    def test_extracts_text_from_multiple_slides(self):
        prs = _make_pptx_mock([["Slide 1 content"], ["Slide 2 content"]])

        with patch("pptx.Presentation", return_value=prs):
            result = extract_text_from_pptx(b"fake pptx")

        assert "Slide 1 content" in result
        assert "Slide 2 content" in result

    def test_skips_shapes_without_text_frame(self):
        shape_no_text = MagicMock()
        shape_no_text.has_text_frame = False
        slide = MagicMock()
        slide.shapes = [shape_no_text]
        prs = MagicMock()
        prs.slides = [slide]

        with patch("pptx.Presentation", return_value=prs):
            result = extract_text_from_pptx(b"fake pptx")

        assert result == ""

    def test_passes_bytes_as_bytesio(self):
        prs = _make_pptx_mock([])

        with patch("pptx.Presentation") as mock_prs_cls:
            mock_prs_cls.return_value = prs
            extract_text_from_pptx(b"pptx bytes")
            args = mock_prs_cls.call_args[0]
            assert isinstance(args[0], io.BytesIO)
            assert args[0].read() == b"pptx bytes"

    def test_empty_presentation_returns_empty_string(self):
        prs = _make_pptx_mock([])

        with patch("pptx.Presentation", return_value=prs):
            assert extract_text_from_pptx(b"") == ""


# ── extract_text_from_file (routing) ─────────────────────────────────────────

class TestExtractTextFromFileRouting:
    def test_routes_pdf_by_content_type(self):
        with (
            patch("services.extraction_service.extract_text_from_pdf_native", return_value=("native text " * 10, 1)) as mock_native,
            patch("services.extraction_service.extract_text_from_pdf_ocr") as mock_ocr,
        ):
            result = extract_text_from_file(b"pdf bytes", "doc.pdf", "application/pdf")
            mock_native.assert_called_once()
            mock_ocr.assert_not_called()
            assert result == "native text " * 10

    def test_routes_pdf_by_extension(self):
        with (
            patch("services.extraction_service.extract_text_from_pdf_native", return_value=("x " * 30, 1)),
            patch("services.extraction_service.extract_text_from_pdf_ocr") as mock_ocr,
        ):
            extract_text_from_file(b"pdf bytes", "report.PDF", "application/octet-stream")
            mock_ocr.assert_not_called()

    def test_pdf_falls_back_to_ocr_when_native_text_too_short(self):
        with (
            patch("services.extraction_service.extract_text_from_pdf_native", return_value=("hi", 1)),
            patch("services.extraction_service.extract_text_from_pdf_ocr", return_value=("ocr text", 1)) as mock_ocr,
        ):
            result = extract_text_from_file(b"pdf bytes", "scan.pdf", "application/pdf")
            mock_ocr.assert_called_once()
            assert result == "ocr text"

    def test_pdf_falls_back_to_ocr_on_native_exception(self):
        with (
            patch("services.extraction_service.extract_text_from_pdf_native", side_effect=Exception("corrupt")),
            patch("services.extraction_service.extract_text_from_pdf_ocr", return_value=("ocr fallback", 1)) as mock_ocr,
        ):
            result = extract_text_from_file(b"pdf bytes", "bad.pdf", "application/pdf")
            mock_ocr.assert_called_once()
            assert result == "ocr fallback"

    def test_routes_docx_by_extension(self):
        with patch("services.extraction_service.extract_text_from_docx", return_value="docx content") as mock_docx:
            result = extract_text_from_file(b"docx bytes", "notes.docx", "application/octet-stream")
            mock_docx.assert_called_once_with(b"docx bytes")
            assert result == "docx content"

    def test_routes_docx_by_content_type(self):
        ct = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        with patch("services.extraction_service.extract_text_from_docx", return_value="docx") as mock_docx:
            extract_text_from_file(b"docx bytes", "file.bin", ct)
            mock_docx.assert_called_once()

    def test_routes_pptx_by_extension(self):
        with patch("services.extraction_service.extract_text_from_pptx", return_value="pptx content") as mock_pptx:
            result = extract_text_from_file(b"pptx bytes", "slides.pptx", "application/octet-stream")
            mock_pptx.assert_called_once_with(b"pptx bytes")
            assert result == "pptx content"

    def test_routes_pptx_by_content_type(self):
        ct = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        with patch("services.extraction_service.extract_text_from_pptx", return_value="pptx") as mock_pptx:
            extract_text_from_file(b"pptx bytes", "file.bin", ct)
            mock_pptx.assert_called_once()

    def test_routes_txt_by_content_type(self):
        result = extract_text_from_file(b"hello world", "readme.txt", "text/plain")
        assert result == "hello world"

    def test_routes_txt_by_extension(self):
        result = extract_text_from_file(b"plain text", "notes.txt", "application/octet-stream")
        assert result == "plain text"


# ── Router dispatch by OCR_ENGINE ─────────────────────────────────────────────

from services.extraction_service import (
    extract_text_from_pdf_ocr,
    extract_text_from_image_bytes,
)


class TestRouterDispatch:
    def test_engine_tesseract_uses_legacy_pdf_ocr(self, monkeypatch):
        monkeypatch.setenv("OCR_ENGINE", "tesseract")
        with (
            patch(
                "services.extraction_backends.tesseract_backend.extract_text_from_pdf_ocr_impl",
                return_value=("legacy-ocr", 3),
            ) as mock_tess,
            patch("services.extraction_service.extract_pdf_with_docling") as mock_docling,
        ):
            text, pages = extract_text_from_pdf_ocr(b"pdf", max_pages=5, lang="eng")

        mock_tess.assert_called_once()
        mock_docling.assert_not_called()
        assert text == "legacy-ocr"
        assert pages == 3

    def test_engine_docling_uses_docling_backend(self, monkeypatch):
        monkeypatch.setenv("OCR_ENGINE", "docling")
        monkeypatch.setenv("GOT_OCR_ENABLED", "false")
        with (
            patch(
                "services.extraction_service.extract_pdf_with_docling",
                return_value=("# Markdown", 2, {"fallback_pages": [], "per_page_markdown": ["# Markdown"]}),
            ) as mock_docling,
            patch(
                "services.extraction_backends.tesseract_backend.extract_text_from_pdf_ocr_impl"
            ) as mock_tess,
        ):
            text, pages = extract_text_from_pdf_ocr(b"pdf")

        mock_docling.assert_called_once()
        mock_tess.assert_not_called()
        assert text == "# Markdown"
        assert pages == 2

    def test_engine_auto_skips_got_ocr_when_disabled(self, monkeypatch):
        monkeypatch.setenv("OCR_ENGINE", "auto")
        monkeypatch.setenv("GOT_OCR_ENABLED", "false")
        metadata = {
            "per_page_markdown": ["math page with ≥"],
            "fallback_pages": [0],
        }
        with (
            patch(
                "services.extraction_service.extract_pdf_with_docling",
                return_value=("math page with ≥", 1, metadata),
            ),
            patch("services.extraction_service.extract_page_with_got_ocr") as mock_got,
        ):
            text, _ = extract_text_from_pdf_ocr(b"pdf")

        mock_got.assert_not_called()
        assert "math page" in text

    def test_engine_auto_invokes_got_ocr_for_flagged_pages(self, monkeypatch):
        monkeypatch.setenv("OCR_ENGINE", "auto")
        monkeypatch.setenv("GOT_OCR_ENABLED", "true")
        metadata = {
            "per_page_markdown": ["weak page 0", "good page 1"],
            "fallback_pages": [0],
        }

        fake_pdf = MagicMock()
        fake_pdf.__len__ = MagicMock(return_value=2)
        fake_page = MagicMock()
        fake_pdf.__getitem__ = MagicMock(return_value=fake_page)
        rendered = MagicMock()

        from PIL import Image
        dummy_img = Image.new("RGB", (2, 2), color="white")
        rendered.to_pil = MagicMock(return_value=dummy_img)
        fake_page.render = MagicMock(return_value=rendered)
        fake_page.close = MagicMock()

        with (
            patch(
                "services.extraction_service.extract_pdf_with_docling",
                return_value=("weak page 0\n\ngood page 1", 2, metadata),
            ),
            patch("pypdfium2.PdfDocument", return_value=fake_pdf),
            patch(
                "services.extraction_service.extract_page_with_got_ocr",
                return_value="\\frac{1}{2}",
            ) as mock_got,
        ):
            text, _ = extract_text_from_pdf_ocr(b"pdf")

        mock_got.assert_called_once()
        assert "\\frac{1}{2}" in text
        assert "good page 1" in text

    def test_docling_failure_falls_back_to_tesseract(self, monkeypatch):
        from services.extraction_backends.docling_backend import DoclingUnavailableError
        monkeypatch.setenv("OCR_ENGINE", "docling")
        with (
            patch(
                "services.extraction_service.extract_pdf_with_docling",
                side_effect=DoclingUnavailableError("not installed"),
            ),
            patch(
                "services.extraction_backends.tesseract_backend.extract_text_from_pdf_ocr_impl",
                return_value=("tess-fallback", 1),
            ) as mock_tess,
        ):
            text, pages = extract_text_from_pdf_ocr(b"pdf")

        mock_tess.assert_called_once()
        assert text == "tess-fallback"
        assert pages == 1

    def test_image_tesseract_engine_uses_legacy(self, monkeypatch):
        monkeypatch.setenv("OCR_ENGINE", "tesseract")
        with (
            patch(
                "services.extraction_backends.tesseract_backend.extract_text_from_image_bytes_impl",
                return_value="legacy-img",
            ) as mock_tess,
            patch("services.extraction_service.extract_pdf_with_docling") as mock_docling,
        ):
            result = extract_text_from_image_bytes(b"imgbytes")

        mock_tess.assert_called_once()
        mock_docling.assert_not_called()
        assert result == "legacy-img"


class TestGeminiVisionFallback:
    """Gemini-vision OCR for pages Docling flagged as having no usable text.

    Regression context: a rasterized practice exam of handwritten linear
    algebra extracted to "" on every page. Docling *did* flag all 13 pages in
    `fallback_pages`, but the only consumer of that signal was gated behind
    `OCR_ENGINE=auto` + GOT-OCR, so under the default `docling` engine the
    signal was computed and discarded. The empty text then reached the classify
    prompt and the model invented a document.
    """

    @staticmethod
    def _fake_pdf(pages=2):
        from PIL import Image
        fake_pdf = MagicMock()
        fake_pdf.__len__ = MagicMock(return_value=pages)
        fake_page = MagicMock()
        fake_pdf.__getitem__ = MagicMock(return_value=fake_page)
        rendered = MagicMock()
        rendered.to_pil = MagicMock(return_value=Image.new("RGB", (2, 2), color="white"))
        fake_page.render = MagicMock(return_value=rendered)
        fake_page.close = MagicMock()
        return fake_pdf

    def test_replaces_flagged_pages_under_the_default_engine(self, monkeypatch):
        """Must fire with OCR_ENGINE at its default. The old gate required
        `auto`, which is why real uploads never benefited."""
        monkeypatch.setenv("OCR_ENGINE", "docling")
        monkeypatch.setenv("GOT_OCR_ENABLED", "false")
        monkeypatch.setenv("GEMINI_VISION_OCR_ENABLED", "true")
        metadata = {"per_page_markdown": ["", "good page 1"], "fallback_pages": [0]}

        with (
            patch(
                "services.extraction_service.extract_pdf_with_docling",
                return_value=("good page 1", 2, metadata),
            ),
            patch("pypdfium2.PdfDocument", return_value=self._fake_pdf()),
            patch(
                "services.extraction_service.extract_page_with_gemini_vision",
                return_value="Problem 2  $\\lambda = -1, 8$",
            ) as mock_vision,
        ):
            text, _ = extract_text_from_pdf_ocr(b"pdf")

        mock_vision.assert_called_once()
        assert "\\lambda" in text
        assert "good page 1" in text

    def test_not_called_when_disabled(self, monkeypatch):
        monkeypatch.setenv("OCR_ENGINE", "docling")
        monkeypatch.setenv("GOT_OCR_ENABLED", "false")
        monkeypatch.setenv("GEMINI_VISION_OCR_ENABLED", "false")
        metadata = {"per_page_markdown": [""], "fallback_pages": [0]}

        with (
            patch(
                "services.extraction_service.extract_pdf_with_docling",
                return_value=("", 1, metadata),
            ),
            patch(
                "services.extraction_service.extract_page_with_gemini_vision"
            ) as mock_vision,
        ):
            extract_text_from_pdf_ocr(b"pdf")

        mock_vision.assert_not_called()

    def test_not_called_when_no_pages_are_flagged(self, monkeypatch):
        """A normal text PDF must cost zero vision calls."""
        monkeypatch.setenv("OCR_ENGINE", "docling")
        monkeypatch.setenv("GEMINI_VISION_OCR_ENABLED", "true")
        metadata = {"per_page_markdown": ["full page of text"], "fallback_pages": []}

        with (
            patch(
                "services.extraction_service.extract_pdf_with_docling",
                return_value=("full page of text", 1, metadata),
            ),
            patch(
                "services.extraction_service.extract_page_with_gemini_vision"
            ) as mock_vision,
        ):
            text, _ = extract_text_from_pdf_ocr(b"pdf")

        mock_vision.assert_not_called()
        assert text == "full page of text"

    def test_one_page_failing_does_not_lose_the_document(self, monkeypatch):
        """A quota error on page 0 must leave the rest of the document intact."""
        monkeypatch.setenv("OCR_ENGINE", "docling")
        monkeypatch.setenv("GEMINI_VISION_OCR_ENABLED", "true")
        metadata = {
            "per_page_markdown": ["original 0", "original 1"],
            "fallback_pages": [0, 1],
        }

        with (
            patch(
                "services.extraction_service.extract_pdf_with_docling",
                return_value=("original 0\n\noriginal 1", 2, metadata),
            ),
            patch("pypdfium2.PdfDocument", return_value=self._fake_pdf()),
            patch(
                "services.extraction_service.extract_page_with_gemini_vision",
                side_effect=[RuntimeError("429 quota"), "transcribed 1"],
            ),
        ):
            text, _ = extract_text_from_pdf_ocr(b"pdf")

        assert "original 0" in text      # failed page keeps what Docling had
        assert "transcribed 1" in text   # later page still transcribed

    def test_unavailable_stops_trying_further_pages(self, monkeypatch):
        """Misconfiguration is not per-page — stop rather than burning a failed
        call for every page in a 200-page scan."""
        from services.extraction_backends.gemini_vision_backend import (
            GeminiVisionUnavailableError,
        )
        monkeypatch.setenv("OCR_ENGINE", "docling")
        monkeypatch.setenv("GEMINI_VISION_OCR_ENABLED", "true")
        metadata = {
            "per_page_markdown": ["p0", "p1", "p2"],
            "fallback_pages": [0, 1, 2],
        }

        with (
            patch(
                "services.extraction_service.extract_pdf_with_docling",
                return_value=("p0\n\np1\n\np2", 3, metadata),
            ),
            patch("pypdfium2.PdfDocument", return_value=self._fake_pdf(pages=3)),
            patch(
                "services.extraction_service.extract_page_with_gemini_vision",
                side_effect=GeminiVisionUnavailableError("no key"),
            ) as mock_vision,
        ):
            extract_text_from_pdf_ocr(b"pdf")

        assert mock_vision.call_count == 1


class TestOcrCacheKey:
    def test_cache_key_includes_the_vision_flag(self, monkeypatch):
        """Turning vision OCR on must not return the empty text cached from a
        run made before it was enabled."""
        from services.extraction_service import _ocr_cache_key

        monkeypatch.setenv("GEMINI_VISION_OCR_ENABLED", "false")
        off = _ocr_cache_key(b"same-bytes")
        monkeypatch.setenv("GEMINI_VISION_OCR_ENABLED", "true")
        on = _ocr_cache_key(b"same-bytes")

        assert off != on
