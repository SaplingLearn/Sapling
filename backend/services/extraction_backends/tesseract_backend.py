import io
import re
from typing import List, Tuple

from pypdf import PdfReader

from services.archive_limits import check_zip_bounds
from services.image_safety import open_image, render_pdf_page


#: One Tesseract language code ("eng", "chi_sim"); a request may join a few
#: with "+". The code names a traineddata file, so it is never passed on
#: unless Tesseract reports it installed.
_LANG_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,31}$")
MAX_OCR_LANGS = 3
_installed_langs: frozenset[str] | None = None


def reset_language_cache() -> None:
    """Forget the installed-language list (tests)."""
    global _installed_langs
    _installed_langs = None


def installed_languages() -> frozenset[str]:
    """The languages this Tesseract has (read once per process: installing a
    language pack means a new image, so a restart). When Tesseract cannot be
    asked, only ``eng`` (nothing is cached, so a later call asks again)."""
    global _installed_langs
    if _installed_langs is None:
        try:
            import pytesseract

            langs = frozenset(pytesseract.get_languages(config="")) - {"osd"}
        except Exception:
            return frozenset({"eng"})
        _installed_langs = langs or frozenset({"eng"})
    return _installed_langs


def validate_lang(lang: str) -> str:
    """``lang`` when every "+"-joined code is a well-formed, installed
    Tesseract language (at most MAX_OCR_LANGS); else ValueError."""
    parts = (lang or "").split("+")
    if len(parts) > MAX_OCR_LANGS or not all(_LANG_CODE.match(p) for p in parts):
        raise ValueError("unsupported OCR language")
    installed = installed_languages()
    if any(p not in installed for p in parts):
        raise ValueError("unsupported OCR language")
    return lang


def _clean_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.splitlines()).strip()


def _preprocess_for_ocr(image):
    from PIL import ImageOps
    gray = ImageOps.grayscale(image)
    return ImageOps.autocontrast(gray)


def extract_text_from_image_bytes_impl(image_bytes: bytes, lang: str = "eng") -> str:
    try:
        import pytesseract
    except ImportError as e:
        raise RuntimeError(f"OCR library not installed: {e}") from e

    image = open_image(image_bytes)
    image = _preprocess_for_ocr(image)
    text = pytesseract.image_to_string(image, lang=lang, config="--psm 6")
    return _clean_text(text)


def extract_text_from_pdf_native_impl(pdf_bytes: bytes, max_pages: int = 50) -> Tuple[str, int]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_count = min(len(reader.pages), max_pages)
    chunks: List[str] = []
    for i in range(page_count):
        chunks.append(reader.pages[i].extract_text() or "")
    return _clean_text("\n\n".join(chunks)), page_count


def extract_text_from_pdf_ocr_impl(
    pdf_bytes: bytes, max_pages: int = 20, lang: str = "eng"
) -> Tuple[str, int]:
    try:
        import pypdfium2 as pdfium
        import pytesseract
        from PIL import Image  # noqa: F401
    except ImportError as e:
        raise RuntimeError(f"OCR library not installed: {e}") from e

    pdf = pdfium.PdfDocument(pdf_bytes)
    page_count = min(len(pdf), max_pages)
    chunks: List[str] = []
    for i in range(page_count):
        page = pdf[i]
        pil_image = render_pdf_page(page, scale=2)
        processed = _preprocess_for_ocr(pil_image)
        chunks.append(pytesseract.image_to_string(processed, lang=lang, config="--psm 6"))
        page.close()
    return _clean_text("\n\n".join(chunks)), page_count


def extract_text_from_docx_impl(file_bytes: bytes) -> str:
    import mammoth

    check_zip_bounds(file_bytes)  # a DOCX is a zip: refuse a bomb before mammoth inflates it
    result = mammoth.extract_raw_text(io.BytesIO(file_bytes))
    return _clean_text(result.value)


def extract_text_from_pptx_impl(file_bytes: bytes) -> str:
    from pptx import Presentation

    check_zip_bounds(file_bytes)  # a PPTX is a zip, as above
    prs = Presentation(io.BytesIO(file_bytes))
    chunks = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    line = " ".join(run.text for run in para.runs).strip()
                    if line:
                        chunks.append(line)
    return _clean_text("\n".join(chunks))


def tesseract_available() -> Tuple[bool, str | None]:
    try:
        import pytesseract
        return True, str(pytesseract.get_tesseract_version())
    except Exception:
        return False, None
