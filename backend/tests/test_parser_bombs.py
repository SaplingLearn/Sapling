"""sec2 M5: the OCR / Office / PDF paths are bounded before they parse.

Every bomb is small and built in-test: a PNG whose header declares 50 M
pixels, an Office zip whose members declare more than 200 MB, a PDF page
that would render to hundreds of megapixels, a Docling call that must not
convert the whole document, and Tesseract language codes that are not
installed.
"""
from __future__ import annotations

import io
import sys
import types
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from services import image_safety
from services.archive_limits import MAX_ENTRIES, MAX_UNCOMPRESSED_BYTES, ArchiveTooLarge
from services.extraction_backends import docling_backend, tesseract_backend
from services.image_safety import ImageTooLarge


# ── images ───────────────────────────────────────────────────────────────────


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("1", (width, height)).save(buf, format="PNG")  # 1-bit: tiny in memory
    return buf.getvalue()


def test_pil_is_configured_process_wide():
    assert Image.MAX_IMAGE_PIXELS == image_safety.MAX_IMAGE_PIXELS == 64_000_000


def test_a_decompression_bomb_is_refused_at_open():
    bomb = _png(10_000, 7_000)  # 70 M pixels, a few KB on the wire
    assert len(bomb) < 200_000
    with pytest.raises(ImageTooLarge):
        image_safety.open_image(bomb)


def test_an_ordinary_image_opens():
    assert image_safety.open_image(_png(800, 600)).size == (800, 600)


def test_a_full_resolution_48mp_phone_photo_opens():
    assert image_safety.open_image(_png(8064, 6048)).size == (8064, 6048)


@pytest.mark.parametrize("engine", ["tesseract", "docling"])
def test_every_image_ocr_path_refuses_the_bomb(engine, monkeypatch):
    from services import extraction_service

    monkeypatch.setenv("OCR_ENGINE", engine)
    with patch("services.extraction_service.extract_pdf_with_docling") as docling, \
         patch("pytesseract.image_to_string") as tess:
        with pytest.raises(ImageTooLarge):
            extraction_service.extract_text_from_image_bytes(_png(10_000, 7_000))
    docling.assert_not_called()
    tess.assert_not_called()


def test_the_image_route_answers_413_for_a_bomb():
    from main import app

    client = TestClient(app)
    with patch("routes.extract.validate_lang", side_effect=lambda lang: lang):
        r = client.post("/api/extract/image",
                        files={"file": ("x.png", _png(10_000, 7_000), "image/png")})
    assert r.status_code == 413, r.text


# ── PDF page rendering ───────────────────────────────────────────────────────


def test_a_letter_page_renders_at_the_requested_scale():
    assert image_safety.safe_render_scale(612, 792, 2.0) == 2.0


def test_a_huge_page_is_rendered_under_the_pixel_budget():
    scale = image_safety.safe_render_scale(14_400, 14_400, 2.0)  # PDF's largest page
    assert scale < 2.0
    assert (14_400 * scale) * (14_400 * scale) <= image_safety.MAX_RENDER_PIXELS + 1


@pytest.mark.parametrize("w,h", [(0, 792), (612, -1), (float("inf"), 1), (10**9, 10**9)])
def test_degenerate_or_absurd_pages_are_refused(w, h):
    with pytest.raises(ImageTooLarge):
        image_safety.safe_render_scale(w, h)


def test_render_pdf_page_passes_the_clamped_scale():
    page = MagicMock()
    page.get_size.return_value = (14_400.0, 14_400.0)
    image_safety.render_pdf_page(page, scale=2)
    used = page.render.call_args.kwargs["scale"]
    assert used == image_safety.safe_render_scale(14_400, 14_400, 2)


def test_tesseract_pdf_ocr_renders_through_the_clamp(monkeypatch):
    page = MagicMock()
    page.get_size.return_value = (14_400.0, 14_400.0)
    page.render.return_value.to_pil.return_value = Image.new("L", (4, 4))
    pdf = MagicMock()
    pdf.__len__ = MagicMock(return_value=1)
    pdf.__getitem__ = MagicMock(return_value=page)
    with patch("pypdfium2.PdfDocument", return_value=pdf), \
         patch("pytesseract.image_to_string", return_value="text"):
        tesseract_backend.extract_text_from_pdf_ocr_impl(b"%PDF-", max_pages=1)
    assert page.render.call_args.kwargs["scale"] < 2


# ── Office zips ──────────────────────────────────────────────────────────────


def _office_bomb(member: str) -> bytes:
    """A zip whose one member inflates past MAX_UNCOMPRESSED_BYTES (~200 KB on the wire)."""
    buf = io.BytesIO()
    chunk = b"\0" * (1024 * 1024)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        with z.open(member, "w", force_zip64=True) as f:
            for _ in range(MAX_UNCOMPRESSED_BYTES // len(chunk) + 1):
                f.write(chunk)
    return buf.getvalue()


def test_a_docx_bomb_is_refused_before_mammoth_runs():
    bomb = _office_bomb("word/document.xml")
    assert len(bomb) < 2 * 1024 * 1024
    with patch("mammoth.extract_raw_text", side_effect=AssertionError("parsed")):
        with pytest.raises(ArchiveTooLarge):
            tesseract_backend.extract_text_from_docx_impl(bomb)


def test_a_pptx_with_too_many_parts_is_refused_before_python_pptx_runs():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ppt/presentation.xml", b"")
        for i in range(MAX_ENTRIES):
            z.writestr(f"ppt/x{i}", b"")
    with patch("pptx.Presentation", side_effect=AssertionError("parsed")):
        with pytest.raises(ArchiveTooLarge, match="too many parts"):
            tesseract_backend.extract_text_from_pptx_impl(buf.getvalue())


# ── Docling: bounded input, bounded time ─────────────────────────────────────


class _SignatureConverter:
    """Docling 2.x's ``convert`` signature, recording what it is asked for."""

    def __init__(self):
        self.kwargs = None

    def convert(self, source, headers=None, raises_on_error=True, max_num_pages=None,
                max_file_size=None, page_range=None):
        self.kwargs = {"max_num_pages": max_num_pages, "max_file_size": max_file_size,
                       "page_range": page_range}
        doc = MagicMock()
        doc.pages = {}
        doc.tables = []
        doc.export_to_markdown = MagicMock(return_value="text")
        return types.SimpleNamespace(document=doc)


@pytest.fixture
def fake_docling_stream(monkeypatch):
    base_models = types.ModuleType("docling.datamodel.base_models")
    base_models.DocumentStream = lambda name, stream: MagicMock()
    for name in ("docling", "docling.datamodel"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", base_models)


def test_docling_converts_only_the_pages_it_will_use(fake_docling_stream):
    conv = _SignatureConverter()
    with patch.object(docling_backend, "_get_converter", return_value=conv):
        docling_backend.extract_pdf_with_docling(b"%PDF-1.4", max_pages=7)
    assert conv.kwargs == {
        "page_range": (1, 7),
        "max_num_pages": docling_backend.MAX_NUM_PAGES,
        "max_file_size": docling_backend.MAX_FILE_BYTES,
    }


def test_an_older_docling_gets_only_the_bounds_it_knows():
    class Old:
        def convert(self, source, max_num_pages=None):
            pass

    assert docling_backend._convert_kwargs(Old(), 5) == {
        "max_num_pages": docling_backend.MAX_NUM_PAGES,
    }


def test_docling_refuses_an_oversize_pdf_before_converting(fake_docling_stream, monkeypatch):
    monkeypatch.setattr(docling_backend, "MAX_FILE_BYTES", 10)
    with patch.object(docling_backend, "_get_converter") as get:
        with pytest.raises(ValueError):
            docling_backend.extract_pdf_with_docling(b"%PDF-" + b"x" * 20)
    get.assert_not_called()


def test_the_docling_size_bound_never_refuses_a_route_capped_upload():
    from routes.documents import MAX_FILE_SIZE

    assert docling_backend.MAX_FILE_BYTES > MAX_FILE_SIZE


def test_the_converter_is_built_with_a_document_timeout(monkeypatch):
    seen = {}

    class Options:
        document_timeout = None

    class PdfFormatOption:
        def __init__(self, pipeline_options):
            seen["options"] = pipeline_options

    def DocumentConverter(format_options=None):
        seen["format_options"] = format_options
        return "converter"

    mods = {
        "docling": types.ModuleType("docling"),
        "docling.datamodel": types.ModuleType("docling.datamodel"),
        "docling.datamodel.base_models": types.ModuleType("docling.datamodel.base_models"),
        "docling.datamodel.pipeline_options": types.ModuleType("docling.datamodel.pipeline_options"),
        "docling.document_converter": types.ModuleType("docling.document_converter"),
    }
    mods["docling.datamodel.base_models"].InputFormat = types.SimpleNamespace(PDF="pdf")
    mods["docling.datamodel.pipeline_options"].PdfPipelineOptions = Options
    mods["docling.document_converter"].PdfFormatOption = PdfFormatOption
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)

    assert docling_backend._build_converter(DocumentConverter) == "converter"
    assert seen["options"].document_timeout == docling_backend.DOCUMENT_TIMEOUT_S
    assert list(seen["format_options"]) == ["pdf"]


# ── Tesseract language ───────────────────────────────────────────────────────


@pytest.fixture
def installed(monkeypatch):
    tesseract_backend.reset_language_cache()
    monkeypatch.setattr(tesseract_backend, "_installed_langs", frozenset({"eng", "fra", "chi_sim"}))
    yield
    tesseract_backend.reset_language_cache()


@pytest.mark.usefixtures("installed")
@pytest.mark.parametrize("lang", ["eng", "eng+fra", "chi_sim"])
def test_installed_languages_pass(lang):
    assert tesseract_backend.validate_lang(lang) == lang


@pytest.mark.usefixtures("installed")
@pytest.mark.parametrize("lang", [
    "", "deu", "../../tmp/evil", "eng --oem 0", "eng+fra+chi_sim+eng", "eng+", "e",
])
def test_anything_else_is_refused(lang):
    with pytest.raises(ValueError):
        tesseract_backend.validate_lang(lang)


@pytest.mark.usefixtures("installed")
@pytest.mark.parametrize("path,files", [
    ("/api/extract/pdf", {"file": ("d.pdf", b"%PDF-1.4 hi", "application/pdf")}),
    ("/api/extract/image", {"file": ("i.png", b"\x89PNG\r\n\x1a\n x", "image/png")}),
])
def test_the_routes_refuse_an_uninstalled_language_before_any_ocr(path, files):
    from main import app

    client = TestClient(app)
    with patch("routes.extract.extract_text_from_pdf_native") as native, \
         patch("routes.extract.extract_text_from_image_bytes") as image:
        r = client.post(f"{path}?lang=../../tmp/evil", files=files)
    assert r.status_code == 400
    assert r.json()["detail"] == "Unsupported OCR language."
    native.assert_not_called()
    image.assert_not_called()
