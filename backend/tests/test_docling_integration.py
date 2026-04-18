"""
Integration test — runs real Docling against a tiny syllabus PDF fixture.

Skipped if docling is not installed so CI without the ML extras stays green.
Do NOT run this in CI environments that can't download Docling's layout
model weights on first use.
"""
import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("docling") is None,
    reason="Docling not installed",
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_syllabus.pdf"


@pytest.fixture(autouse=True)
def _reset_docling_cache():
    from services.extraction_backends.docling_backend import reset_converter_cache
    reset_converter_cache()
    yield
    reset_converter_cache()


@pytest.fixture
def syllabus_pdf_bytes():
    if not FIXTURE.exists():
        pytest.skip(f"fixture missing: {FIXTURE}")
    return FIXTURE.read_bytes()


def test_docling_extracts_heading_and_table(syllabus_pdf_bytes):
    if os.getenv("SKIP_DOCLING_INTEGRATION", "false").lower() == "true":
        pytest.skip("SKIP_DOCLING_INTEGRATION=true")

    from services.extraction_backends.docling_backend import extract_pdf_with_docling

    markdown, page_count, metadata = extract_pdf_with_docling(syllabus_pdf_bytes, max_pages=5)

    assert page_count >= 1
    assert "CS 101" in markdown or "Syllabus" in markdown.lower() or "Course" in markdown
    assert "Lab 1" in markdown
    assert "March 15" in markdown
    # Table should survive as pipe table OR structured rows
    structured_table = "|" in markdown or metadata.get("table_count", 0) >= 1
    assert structured_table, f"expected table structure in markdown; got:\n{markdown}"


def test_docling_metadata_shape(syllabus_pdf_bytes):
    if os.getenv("SKIP_DOCLING_INTEGRATION", "false").lower() == "true":
        pytest.skip("SKIP_DOCLING_INTEGRATION=true")

    from services.extraction_backends.docling_backend import extract_pdf_with_docling

    _, _, metadata = extract_pdf_with_docling(syllabus_pdf_bytes, max_pages=5)

    assert "per_page_markdown" in metadata
    assert "per_page_char_counts" in metadata
    assert "per_page_math_flags" in metadata
    assert "fallback_pages" in metadata
    assert "table_count" in metadata
