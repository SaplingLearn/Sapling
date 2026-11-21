"""
backend/services/documents/page_count.py

How many pages an uploaded file has, counted from the file itself.

The Library shows this in its Pages column and sorts by it ("Most Pages"), so
it is read off the bytes at upload time and stored on `documents.page_count`.
Never raises and never guesses: a format with no fixed pagination, a file the
parser cannot open, or anything unexpected answers ``None``, which the Library
renders as an em dash and sorts last.

DOCX deliberately answers ``None``. A Word document has no pages until a
renderer lays it out — the page count Word shows is produced by Word, and the
`w:lastRenderedPageBreak` hints in the XML are a stale cache of whatever last
opened the file, not a fact about the document.
"""
from __future__ import annotations

import io
import logging
import zipfile

logger = logging.getLogger(__name__)

#: Refuse an implausible count rather than storing it. A real course document
#: is far under this; anything above means the parse went wrong.
MAX_PAGES = 10_000


def page_count_of(file_bytes: bytes, filename: str, content_type: str = "") -> int | None:
    """Pages in ``file_bytes``, or ``None`` when it cannot be known."""
    if not file_bytes:
        return None
    lower = (filename or "").lower()
    try:
        if content_type == "application/pdf" or lower.endswith(".pdf"):
            return _bounded(_pdf_pages(file_bytes))
        if lower.endswith(".pptx") or "presentationml" in content_type:
            return _bounded(_pptx_slides(file_bytes))
    except Exception:
        # A document that will not parse is still a perfectly good document;
        # only its page count is unknown.
        logger.debug("page count unavailable for %s", filename, exc_info=True)
    return None


def _bounded(n: int | None) -> int | None:
    if n is None or n < 1 or n > MAX_PAGES:
        return None
    return n


def _pdf_pages(file_bytes: bytes) -> int | None:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes), strict=False)
    # An encrypted PDF still reports its page count once the empty-password
    # decrypt succeeds, which is the common "owner password only" case.
    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception:
            return None
    return len(reader.pages)


def _pptx_slides(file_bytes: bytes) -> int | None:
    """Slides in a PPTX, counted from the package parts.

    Reading the zip directory is enough and costs nothing: python-pptx would
    parse the whole presentation to answer the same question.
    """
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        return sum(
            1
            for n in z.namelist()
            if n.startswith("ppt/slides/slide") and n.endswith(".xml")
        )
