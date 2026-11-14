"""Smallest files the upload signature checks (services/upload_validation.py)
accept as what their names say."""
import io
import zipfile

PDF_BYTES = b"%PDF-1.4 sample content for testing"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF_BYTES = b"GIF89a" + b"\x00" * 32
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 32


def _zip(*parts: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        for part in parts:
            zf.writestr(part, "<x/>")
    return buf.getvalue()


def docx_bytes() -> bytes:
    return _zip("word/document.xml")


def pptx_bytes() -> bytes:
    return _zip("ppt/presentation.xml")
