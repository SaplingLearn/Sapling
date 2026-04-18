import io
import re
from typing import Tuple

MATH_WITHOUT_LATEX = re.compile(r"[∫∑∏√∂∇≈≠≤≥±×÷]")
MATH_SCRIPT_PATTERN = re.compile(r"(?<![A-Za-z])[A-Za-z]\^[A-Za-z0-9]|_\{[^}]+\}")
MATH_LATEX_PATTERN = re.compile(r"\\frac|\\int|\\sum|\\sqrt|\\alpha|\\beta|\\theta|\$")

LOW_CHAR_THRESHOLD = 40

_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_IMAGE_PLACEHOLDER_RE = re.compile(r"<!--\s*image\s*-->\s*")


class DoclingUnavailableError(RuntimeError):
    """Raised when Docling cannot be imported or converter construction fails."""


_CACHED_CONVERTER = None


def _get_converter():
    global _CACHED_CONVERTER
    if _CACHED_CONVERTER is not None:
        return _CACHED_CONVERTER
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as e:
        raise DoclingUnavailableError(f"Docling not installed: {e}") from e
    _CACHED_CONVERTER = DocumentConverter()
    return _CACHED_CONVERTER


def reset_converter_cache():
    """For tests: drop the cached converter."""
    global _CACHED_CONVERTER
    _CACHED_CONVERTER = None


def _strip_frontmatter(markdown: str) -> str:
    return _FRONTMATTER_RE.sub("", markdown, count=1).lstrip()


def _strip_image_placeholders(markdown: str) -> str:
    return _IMAGE_PLACEHOLDER_RE.sub("", markdown)


def _detect_math_without_latex(page_text: str) -> bool:
    if MATH_LATEX_PATTERN.search(page_text):
        return False
    return bool(MATH_WITHOUT_LATEX.search(page_text) or MATH_SCRIPT_PATTERN.search(page_text))


def extract_pdf_with_docling(pdf_bytes: bytes, max_pages: int = 50) -> Tuple[str, int, dict]:
    try:
        from docling.datamodel.base_models import DocumentStream
    except ImportError as e:
        raise DoclingUnavailableError(f"Docling not installed: {e}") from e

    converter = _get_converter()
    stream = DocumentStream(name="input.pdf", stream=io.BytesIO(pdf_bytes))
    result = converter.convert(stream)
    doc = result.document

    page_count = 0
    try:
        page_count = min(len(doc.pages), max_pages) if doc.pages else 0
    except Exception:
        page_count = 0

    per_page_markdown = []
    per_page_char_counts = []
    per_page_math_flags = []
    fallback_pages = []

    try:
        page_numbers = sorted(doc.pages.keys()) if doc.pages else []
    except Exception:
        page_numbers = []

    per_page_supported = True
    for idx, pno in enumerate(page_numbers[:max_pages]):
        page_md = ""
        if per_page_supported:
            try:
                page_md = doc.export_to_markdown(page_no=pno, traverse_pictures=True)
            except TypeError:
                per_page_supported = False
            except Exception:
                page_md = ""
        if not per_page_supported:
            # API mismatch: bail to the single-doc branch below
            per_page_markdown = []
            per_page_char_counts = []
            per_page_math_flags = []
            fallback_pages = []
            break
        page_md = _strip_image_placeholders(_strip_frontmatter(page_md or ""))
        per_page_markdown.append(page_md)
        char_count = len(page_md.strip())
        per_page_char_counts.append(char_count)
        math_flag = _detect_math_without_latex(page_md)
        per_page_math_flags.append(math_flag)
        if char_count < LOW_CHAR_THRESHOLD or math_flag:
            fallback_pages.append(idx)

    if not per_page_markdown:
        try:
            full_md = doc.export_to_markdown(traverse_pictures=True)
        except TypeError:
            full_md = doc.export_to_markdown()
        full_md = _strip_image_placeholders(_strip_frontmatter(full_md or ""))
        per_page_markdown = [full_md]
        per_page_char_counts = [len(full_md.strip())]
        per_page_math_flags = [_detect_math_without_latex(full_md)]
        if page_count == 0:
            page_count = 1 if full_md else 0
        if per_page_char_counts[0] < LOW_CHAR_THRESHOLD or per_page_math_flags[0]:
            fallback_pages = [0]

    merged = "\n\n".join(md for md in per_page_markdown if md).strip()

    table_count = 0
    try:
        table_count = len(getattr(doc, "tables", []) or [])
    except Exception:
        table_count = 0

    metadata = {
        "per_page_markdown": per_page_markdown,
        "per_page_char_counts": per_page_char_counts,
        "per_page_math_flags": per_page_math_flags,
        "fallback_pages": fallback_pages,
        "table_count": table_count,
    }
    return merged, page_count or len(per_page_markdown), metadata


def docling_available() -> Tuple[bool, str | None]:
    try:
        import importlib.metadata as md
        try:
            import docling  # noqa: F401
        except Exception:
            return False, None
        try:
            return True, md.version("docling")
        except Exception:
            return True, None
    except Exception:
        return False, None
