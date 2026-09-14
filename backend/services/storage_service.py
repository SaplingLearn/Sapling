"""
Storage service for avatar and cosmetic asset uploads via Supabase Storage.
"""

import logging
import re
import struct

from fastapi import HTTPException
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY, STORAGE_BUCKET, MAX_AVATAR_SIZE
import httpx

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

_EXT_MAP = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}

_storage_base = f"{SUPABASE_URL}/storage/v1/object"
_headers = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
}


async def ensure_bucket_exists(
    bucket_id: str,
    *,
    public: bool,
    file_size_limit: int,
    allowed_mime_types: list[str],
) -> None:
    """Idempotently ensure a Supabase Storage bucket exists with the
    given settings. Called from FastAPI's `lifespan` on app startup
    so new environments self-bootstrap.

    The Supabase Storage API returns:
      • 200 — bucket created.
      • 409 — bucket already exists. Treated as success; we DO NOT
              overwrite settings, in case an admin has intentionally
              tuned them in the dashboard.
      • 4xx/5xx — logged as a warning and we move on. Startup is not
              gated on storage-bucket availability — a transient
              Supabase outage shouldn't block the deploy. If the
              bucket genuinely doesn't exist after this, the next
              upload returns 502 with the upstream error visible
              (per upload_avatar's diagnostic logging from PR #86).

    Service-role uploads bypass Storage RLS, so no policy needs to be
    attached after creation.

    Async because it runs inside FastAPI's async lifespan; using
    httpx.AsyncClient avoids blocking the event loop during startup.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.warning(
            "ensure_bucket_exists(%s): SUPABASE_URL or SUPABASE_SERVICE_KEY "
            "missing — skipping bucket bootstrap. Storage operations will "
            "fail at runtime if the bucket doesn't exist.",
            bucket_id,
        )
        return

    url = f"{SUPABASE_URL}/storage/v1/bucket"
    body = {
        "id": bucket_id,
        "name": bucket_id,
        "public": public,
        "file_size_limit": file_size_limit,
        "allowed_mime_types": allowed_mime_types,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers=_headers)
    except Exception:
        logger.exception(
            "ensure_bucket_exists(%s): Supabase Storage API call raised — "
            "bucket existence is unknown.",
            bucket_id,
        )
        return

    if resp.status_code in (200, 201):
        logger.info("Storage bucket %s created.", bucket_id)
    elif _is_duplicate_bucket(resp):
        # "Bucket already exists" — expected on every restart after the
        # first. Supabase signals this as HTTP 400 with body
        # {"statusCode":"409","error":"Duplicate", ...}, not as a real 409.
        logger.debug("Storage bucket %s already exists.", bucket_id)
    else:
        logger.warning(
            "ensure_bucket_exists(%s): Supabase returned %d body=%s",
            bucket_id,
            resp.status_code,
            (resp.text or "").strip()[:300],
        )


def _is_duplicate_bucket(resp: httpx.Response) -> bool:
    if resp.status_code == 409:
        return True
    if resp.status_code != 400:
        return False
    try:
        body = resp.json()
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    return str(body.get("statusCode")) == "409" or body.get("error") == "Duplicate"


def _validate_upload(file_bytes: bytes, content_type: str):
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported image type. Allowed: jpeg, png, webp, gif")
    if len(file_bytes) > MAX_AVATAR_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 5 MB")


def upload_avatar(user_id: str, file_bytes: bytes, content_type: str) -> str:
    _validate_upload(file_bytes, content_type)
    ext = _EXT_MAP.get(content_type, "png")
    path = f"avatars/{user_id}/avatar.{ext}"
    url = f"{_storage_base}/{STORAGE_BUCKET}/{path}"
    resp = httpx.put(
        url,
        content=file_bytes,
        headers={**_headers, "Content-Type": content_type, "x-upsert": "true"},
    )
    if resp.status_code not in (200, 201):
        # Surface the real Supabase response so the failure is debuggable
        # without server access. Common shapes:
        #   {"statusCode":"404","error":"Bucket not found"}    — bucket missing
        #   {"statusCode":"403","error":"new row violates ..."} — RLS/policy denied
        #   {"statusCode":"413","error":"Payload too large"}   — bucket size limit
        body_text = (resp.text or "").strip()[:500]
        logger.warning(
            "upload_avatar: Supabase storage rejected upload "
            "user=%s status=%d body=%s",
            user_id, resp.status_code, body_text,
        )
        # Pass through the upstream message so the caller's toast is
        # actionable. We only show body_text — never the URL or headers
        # (the latter contains the service-role key).
        raise HTTPException(
            status_code=502,
            detail=f"Avatar upload failed (Supabase {resp.status_code}): {body_text or 'no body'}",
        )
    public_url = f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{path}"
    return public_url


def upload_cosmetic_asset(cosmetic_id: str, file_bytes: bytes, content_type: str) -> str:
    _validate_upload(file_bytes, content_type)
    ext = _EXT_MAP.get(content_type, "png")
    path = f"cosmetics/{cosmetic_id}.{ext}"
    url = f"{_storage_base}/{STORAGE_BUCKET}/{path}"
    resp = httpx.put(
        url,
        content=file_bytes,
        headers={**_headers, "Content-Type": content_type, "x-upsert": "true"},
    )
    if resp.status_code not in (200, 201):
        # Same shape as upload_avatar's error path — surface the real
        # Supabase response so admin-side cosmetic uploads aren't a
        # black box either. URL + headers stay out of the message
        # (the latter contains the service-role key).
        body_text = (resp.text or "").strip()[:500]
        logger.warning(
            "upload_cosmetic_asset: Supabase storage rejected upload "
            "cosmetic=%s status=%d body=%s",
            cosmetic_id, resp.status_code, body_text,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Cosmetic asset upload failed (Supabase {resp.status_code}): {body_text or 'no body'}",
        )
    public_url = f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{path}"
    return public_url


def delete_asset(path: str) -> None:
    url = f"{_storage_base}/{STORAGE_BUCKET}/{path}"
    httpx.delete(url, headers=_headers)


# ── Achievement icons ────────────────────────────────────────────────────────
#
# Admins upload a 512x512 PNG/WebP/SVG for `achievements.icon_url` (0043).
# Dimensions are parsed from the file header, never trusted from the client —
# this is the actual enforcement (the admin-UI dimension check in Task 15 is
# only a convenience). Malformed/truncated input must fail with a clean 400,
# never an unhandled struct.error/IndexError.

ICON_CONTENT_TYPES = {"image/png", "image/webp", "image/svg+xml"}
ICON_SIZE_PX = 512
MAX_ICON_BYTES = 512 * 1024

_ICON_EXT = {"image/png": "png", "image/webp": "webp", "image/svg+xml": "svg"}


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    # 8-byte signature, 4-byte length, 4-byte "IHDR", then width/height.
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    if data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    # 30 is the max of the three variants' offset requirements (VP8X/VP8
    # both need up to byte 30; a minimal VP8L only needs 25) — deliberately
    # shared rather than split per-variant so this stays one guard to read.
    # Harmless: it fails closed, and real WebP files always exceed it.
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    fourcc = data[12:16]
    if fourcc == b"VP8X":
        w = int.from_bytes(data[24:27], "little") + 1
        h = int.from_bytes(data[27:30], "little") + 1
        return w, h
    if fourcc == b"VP8 ":
        w = int.from_bytes(data[26:28], "little") & 0x3FFF
        h = int.from_bytes(data[28:30], "little") & 0x3FFF
        return w, h
    if fourcc == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def _svg_root_attrs(data: bytes) -> bytes | None:
    """Return the root <svg> element's own attribute text, or None.

    Only the root element's attributes count — a `viewBox` anywhere else in
    the document (a decoy inside a comment, or a real attribute on a nested
    <symbol>/<pattern>/inner <svg>) must not be mistaken for the root's. An
    admin bypassing the upload form with a raw request could otherwise plant
    a square decoy ahead of the real, non-square root element.

    Skips leading whitespace, an XML declaration, a DOCTYPE, and comments,
    then requires the very next tag to be the `<svg` open tag. Anything else
    (malformed markup, no root <svg> at all, a truncated tag) returns None —
    fail closed, same as the PNG/WebP header parsers.
    """
    text = data[:4096]
    pos = 0
    while True:
        m = re.match(rb"\s+", text[pos:])
        if m:
            pos += m.end()
            continue
        m = re.match(rb"<\?.*?\?>", text[pos:], re.DOTALL)
        if m:
            pos += m.end()
            continue
        m = re.match(rb"<!DOCTYPE.*?>", text[pos:], re.IGNORECASE | re.DOTALL)
        if m:
            pos += m.end()
            continue
        m = re.match(rb"<!--.*?-->", text[pos:], re.DOTALL)
        if m:
            pos += m.end()
            continue
        break

    root = re.match(rb"<svg\b([^>]*)>", text[pos:], re.IGNORECASE)
    return root.group(1) if root else None


def _svg_is_square(data: bytes) -> bool:
    attrs = _svg_root_attrs(data)
    if attrs is None:
        return False
    match = re.search(rb'viewBox\s*=\s*["\']([^"\']+)["\']', attrs)
    if not match:
        return False
    parts = match.group(1).replace(b",", b" ").split()
    if len(parts) != 4:
        return False
    try:
        width, height = float(parts[2]), float(parts[3])
    except ValueError:
        return False
    return width > 0 and abs(width - height) < 0.01


def validate_icon(file_bytes: bytes, content_type: str) -> None:
    """Reject anything that would render badly in the badge grid.

    Dimensions come from the file header, not the client — an admin bypassing
    the upload form must not be able to plant a 4000px icon.
    """
    if content_type not in ICON_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Icon must be PNG, WebP or SVG (got {content_type})",
        )
    if len(file_bytes) > MAX_ICON_BYTES:
        raise HTTPException(status_code=400, detail="Icon must be 512 KB or smaller")

    if content_type == "image/svg+xml":
        if not _svg_is_square(file_bytes):
            raise HTTPException(
                status_code=400,
                detail="SVG icons need a square viewBox (e.g. viewBox=\"0 0 64 64\")",
            )
        return

    dims = (_png_dimensions(file_bytes) if content_type == "image/png"
            else _webp_dimensions(file_bytes))
    if not dims:
        raise HTTPException(status_code=400, detail="Could not read the image header")
    width, height = dims
    if width != ICON_SIZE_PX or height != ICON_SIZE_PX:
        raise HTTPException(
            status_code=400,
            detail=f"Icon must be exactly {ICON_SIZE_PX}x{ICON_SIZE_PX} (got {width}x{height})",
        )


def upload_achievement_icon(achievement_id: str, file_bytes: bytes, content_type: str) -> str:
    validate_icon(file_bytes, content_type)
    ext = _ICON_EXT[content_type]
    path = f"achievement-icons/{achievement_id}.{ext}"
    url = f"{_storage_base}/{STORAGE_BUCKET}/{path}"
    resp = httpx.put(
        url,
        content=file_bytes,
        headers={**_headers, "Content-Type": content_type, "x-upsert": "true"},
    )
    if resp.status_code not in (200, 201):
        body_text = (resp.text or "").strip()[:500]
        logger.warning(
            "upload_achievement_icon: Supabase storage rejected upload "
            "achievement=%s status=%d body=%s",
            achievement_id, resp.status_code, body_text,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Icon upload failed (Supabase {resp.status_code}): {body_text or 'no body'}",
        )
    return f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{path}"
