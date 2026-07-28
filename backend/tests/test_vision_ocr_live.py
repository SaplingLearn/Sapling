"""Vision-OCR rescue against the real Docling pipeline and a real model.

The one thing the rest of this feature's suite structurally cannot prove. Every
other test substitutes the model — FunctionModel or mock — so all of them pass
whether or not the transcription is any good. They passed while the prompt was
returning an entire LaTeX document (\\documentclass, \\usepackage, tabular)
instead of page content. Only a real call caught that.

Deliberately NOT in tests/integration/: this needs Docling and a live model, not
Postgres, and that lane's conftest mandates a running local Supabase stack plus
autouse truncation. `live_llm` is the documented lane for billable model calls
(see the marker registered in conftest.pytest_configure) and bypasses the
`_hermetic_llm_transport` guard that otherwise cuts the wire under every test.

WHAT MAKES THE FIXTURE WORK. `tests/fixtures/scanned_math_ps4.pdf` is an
image-only render of a math worksheet — zero text layer. That alone does NOT
reach vision: Docling ships RapidOCR and reads clean rasterized text perfectly
well, so a rasterized prose page comes back fine and `fallback_pages` stays
empty. This page is reached because `_detect_math_without_latex` flags
math-shaped content carrying no LaTeX (docling_backend.py:104,
`char_count < 40 or math_flag`) — the scanned/handwritten-math case the feature
exists for. Regenerate with
`python tests/fixtures/make_scanned_math_ps4.py <out.pdf>`.

MEASURED on this fixture — same code, only the flag changes:

    vision off -> 230 chars, problem 3 dropped as `<!-- formula-not-decoded -->`,
                  `∫x~2 dxfrom 0 to 3`, `af/ax` for `∂f/∂x`, no LaTeX
    vision on  -> 302 chars, problem 3 recovered as `$\\sqrt{x^2 + 16} \\leq 5$`,
                  `$\\int x^2 dx$`, `$\\partial f/\\partial x$`

Docling losing a whole problem is the point: content it drops never reaches the
concept prompt, so it never reaches the student's graph.

Costs real Gemini calls. Skipped unless RUN_LIVE_OCR=1 and a real key is set.
"""
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.live_llm

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "scanned_math_ps4.pdf"

_PLACEHOLDER_KEYS = {"", "dummy-key-for-import", "dummy-not-used-in-tests", "test-key"}


def _requires_live_ocr():
    if os.getenv("RUN_LIVE_OCR") != "1":
        pytest.skip("billable live-model lane is opt-in (RUN_LIVE_OCR=1)")
    pytest.importorskip("docling", reason="vision rescue needs Docling to flag pages")
    if (os.getenv("GEMINI_API_KEY") or "").strip() in _PLACEHOLDER_KEYS:
        pytest.skip("needs a real GEMINI_API_KEY — this test makes live model calls")


def _extract(monkeypatch, *, vision: bool) -> str:
    from services.extraction_service import extract_text_from_pdf_ocr

    monkeypatch.setenv("OCR_ENGINE", "docling")
    monkeypatch.setenv("GOT_OCR_ENABLED", "false")
    monkeypatch.setenv("GEMINI_VISION_OCR_ENABLED", "true" if vision else "false")
    markdown, _ = extract_text_from_pdf_ocr(FIXTURE.read_bytes(), max_pages=20)
    return markdown


def test_the_fixture_actually_reaches_the_rescue(monkeypatch):
    """Guard the premise. If Docling stops flagging this page, the tests below
    would still pass while proving nothing — vision would never run and both
    branches would return identical Docling output."""
    _requires_live_ocr()
    from services.extraction_backends.docling_backend import extract_pdf_with_docling

    monkeypatch.setenv("OCR_ENGINE", "docling")
    _, _, metadata = extract_pdf_with_docling(FIXTURE.read_bytes(), max_pages=20)
    assert metadata.get("fallback_pages"), (
        "Docling no longer flags the math fixture, so vision OCR is unreachable "
        "and every assertion below is vacuous"
    )


def test_vision_recovers_content_docling_drops(monkeypatch):
    """The load-bearing claim: Docling loses problem 3 entirely; vision gets it
    back. Content Docling drops never reaches the concept prompt at all."""
    _requires_live_ocr()

    without = _extract(monkeypatch, vision=False)
    assert "formula-not-decoded" in without, (
        "expected Docling to drop the square-root problem on this fixture"
    )

    with_vision = _extract(monkeypatch, vision=True)
    assert "formula-not-decoded" not in with_vision
    assert "sqrt" in with_vision.lower() or "√" in with_vision
    assert len(with_vision) > len(without)


def test_vision_output_is_math_notation_not_a_latex_document(monkeypatch):
    """Regression guard for the prompt-placement bug.

    With the instruction as a system prompt rather than in the user turn beside
    the image, the model returns a whole LaTeX FILE. That preamble flows into
    extracted_text, then the concept prompt and course_chunks, so 'amsmath' and
    'booktabs' become candidate concepts on a graph shared by every student in
    the course.
    """
    _requires_live_ocr()

    markdown = _extract(monkeypatch, vision=True)

    assert "$" in markdown, "expected inline LaTeX math from the transcription"
    for artifact in ("\\documentclass", "\\usepackage", "\\begin{document}", "\\end{document}"):
        assert artifact not in markdown, f"LaTeX document wrapper leaked: {artifact}"
