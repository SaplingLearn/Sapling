"""What an uploaded file IS, from its bytes, and reading one within a cap.

A client names a file and declares a ``Content-Type``; both are free text. The
upload routes decide from the bytes instead: :func:`sniff_type` reads the
file's signature (magic bytes), and a route accepts a file only when the
extension it is named with AND its signature agree on an allowed type. Office
documents are zip archives, so a DOCX/PPTX is also checked for the part that
makes it one (``word/document.xml`` / ``ppt/presentation.xml``).

:func:`read_upload_capped` reads in chunks and stops at the cap, so an oversize
upload is refused without ever being held in memory whole.
"""
from __future__ import annotations

import io
import zipfile
from typing import Iterable, Optional

from fastapi import HTTPException, UploadFile

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PNG = "image/png"
JPEG = "image/jpeg"
GIF = "image/gif"
WEBP = "image/webp"
TEXT = "text/plain"

#: The extensions each type may be named with.
EXTENSIONS: dict[str, tuple[str, ...]] = {
    PDF: (".pdf",),
    DOCX: (".docx",),
    PPTX: (".pptx",),
    PNG: (".png",),
    JPEG: (".jpg", ".jpeg"),
    GIF: (".gif",),
    WEBP: (".webp",),
    TEXT: (".txt",),
}

#: The canonical extension each image type is stored under.
IMAGE_EXTENSION = {PNG: "png", JPEG: "jpg", GIF: "gif", WEBP: "webp"}

_CHUNK = 1024 * 1024
#: A PDF's header may follow a little leading junk; readers accept it within 1 KB.
_PDF_HEADER_WINDOW = 1024


def extension_of(filename: Optional[str]) -> str:
    """``.pdf`` for ``notes.PDF``; ``""`` when there is none."""
    name = filename or ""
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""


def sniff_image(data: bytes) -> Optional[str]:
    """The image type ``data``'s signature names, or None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith((b"GIF87a", b"GIF89a")):
        return GIF
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    return None


def _office_type(data: bytes) -> Optional[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
    except (zipfile.BadZipFile, ValueError, OSError):
        return None
    if "word/document.xml" in names:
        return DOCX
    if "ppt/presentation.xml" in names:
        return PPTX
    return None


def _looks_like_text(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return False
    try:
        data[:8192].decode("utf-8")
    except UnicodeDecodeError as e:
        # A multi-byte character cut by the 8 KB window is still text.
        return e.start >= 8192 - 4
    return True


def sniff_type(data: bytes, *, allow_text: bool = False) -> Optional[str]:
    """The allowed type ``data`` is by its bytes (PDF, DOCX, PPTX, an image,
    and — only when asked — UTF-8 plain text), or None."""
    if b"%PDF-" in data[:_PDF_HEADER_WINDOW]:
        return PDF
    if data.startswith(b"PK\x03\x04"):
        return _office_type(data)
    image = sniff_image(data)
    if image:
        return image
    if allow_text and data and _looks_like_text(data):
        return TEXT
    return None


def matching_type(filename: Optional[str], data: bytes, allowed: Iterable[str]) -> Optional[str]:
    """The type ``data`` is, when it is one of ``allowed`` AND ``filename``'s
    extension is one that type may carry; else None."""
    allowed = set(allowed)
    sniffed = sniff_type(data, allow_text=TEXT in allowed)
    if sniffed not in allowed:
        return None
    return sniffed if extension_of(filename) in EXTENSIONS[sniffed] else None


def too_large_detail(max_bytes: int) -> str:
    return (
        f"File exceeds the {max_bytes // (1024 * 1024)} MB limit. "
        "Please upload a smaller file."
    )


async def read_checked_upload(
    upload: UploadFile,
    *,
    allowed: Iterable[str],
    max_bytes: int,
    unsupported_detail: str,
    oversize_status: int = 413,
) -> tuple[bytes, str]:
    """(bytes, type) of an upload that is one of ``allowed`` by name AND by
    signature, read within ``max_bytes``.

    400 ``unsupported_detail`` when the extension is not an allowed one
    (checked before reading anything) or the bytes are not what it names;
    ``oversize_status`` past the cap. The returned type is the sniffed one —
    the client's declared Content-Type is never used."""
    allowed = tuple(allowed)
    if extension_of(upload.filename) not in {e for t in allowed for e in EXTENSIONS[t]}:
        raise HTTPException(status_code=400, detail=unsupported_detail)
    data = await read_upload_capped(upload, max_bytes, status_code=oversize_status)
    content_type = matching_type(upload.filename, data, allowed)
    if content_type is None:
        raise HTTPException(status_code=400, detail=unsupported_detail)
    return data, content_type


async def read_upload_capped(upload: UploadFile, max_bytes: int, *, status_code: int = 413) -> bytes:
    """Read ``upload`` in 1 MB chunks, refusing it (``status_code``) as soon as
    it passes ``max_bytes`` — never more than one chunk past the cap is read."""
    parts: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=status_code, detail=too_large_detail(max_bytes))
        parts.append(chunk)
    return b"".join(parts)
