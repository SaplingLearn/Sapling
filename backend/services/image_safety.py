"""Pixel bounds for every image the OCR paths decode or render.

An uploaded PNG/JPEG of a few MB can declare a canvas of billions of pixels
(a decompression bomb), and a PDF page can declare any media box, which
``page.render(scale=2)`` turns into a bitmap of that size. Every image path
in the extraction pipeline goes through here:

* :func:`open_image` — ``PIL.Image.open`` with the pixel ceiling enforced
  explicitly (PIL alone only WARNS between 1x and 2x its ceiling);
* :func:`render_pdf_page` — a pdfium page rendered at ``scale`` clamped so
  width x height stays under :data:`MAX_RENDER_PIXELS`.

Importing this module also sets ``PIL.Image.MAX_IMAGE_PIXELS`` and turns
``DecompressionBombWarning`` into an error process-wide, so a PIL decode
elsewhere is bounded too.
"""
from __future__ import annotations

import io
import math
import warnings

from PIL import Image

#: Largest image decoded: 64 MP (8000 x 8000). Full-resolution phone photos
#: run up to 48-50 MP (8064 x 6048, 8160 x 6120) and a student photographing
#: notes must get through; past that is a 108/200 MP sensor mode or a
#: crafted canvas. (PIL's own default ceiling is ~89 MP, but there it only
#: warns; here anything past this is refused, so the bound is the real one.)
MAX_IMAGE_PIXELS = 64_000_000
#: Largest bitmap one PDF page is rendered to. A letter page at scale 2 is
#: ~2 MP; a poster-sized page renders at a lower scale instead.
MAX_RENDER_PIXELS = 16_000_000


class ImageTooLarge(ValueError):
    """The image or page would decode past the pixel ceiling."""


def _configure() -> None:
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    warnings.filterwarnings("error", category=Image.DecompressionBombWarning)


_configure()


def open_image(data: bytes) -> Image.Image:
    """``Image.open`` over ``data``, refused when its declared size is past
    :data:`MAX_IMAGE_PIXELS`. Only the header has been read when this
    returns, so nothing large has been allocated yet."""
    try:
        img = Image.open(io.BytesIO(data))
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
        raise ImageTooLarge(str(e)) from e
    width, height = img.size
    if width * height > MAX_IMAGE_PIXELS:
        img.close()
        raise ImageTooLarge(f"image is {width}x{height} pixels (max {MAX_IMAGE_PIXELS})")
    return img


def safe_render_scale(width_pt: float, height_pt: float, scale: float = 2.0,
                      max_pixels: int = MAX_RENDER_PIXELS) -> float:
    """``scale``, lowered so a ``width_pt`` x ``height_pt`` page renders to at
    most ``max_pixels``. Raises :class:`ImageTooLarge` for a degenerate size,
    or a page so large that fitting the budget would leave it illegible."""
    if not (width_pt > 0 and height_pt > 0) or not math.isfinite(width_pt * height_pt):
        raise ImageTooLarge(f"page size {width_pt}x{height_pt} is not renderable")
    area = width_pt * height_pt
    clamped = min(scale, math.sqrt(max_pixels / area))
    # Below ~0.25 (18 dpi) nothing is legible: the page is junk, not a poster.
    if clamped < 0.25:
        raise ImageTooLarge(f"page size {width_pt:.0f}x{height_pt:.0f} pt is too large to render")
    return clamped


def render_pdf_page(page, scale: float = 2.0) -> Image.Image:
    """A pdfium page as a PIL image at ``scale``, clamped by
    :func:`safe_render_scale`."""
    width, height = page.get_size()
    return page.render(scale=safe_render_scale(width, height, scale)).to_pil()
