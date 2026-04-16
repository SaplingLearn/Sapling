"""
Storage service for avatar and cosmetic asset uploads via Supabase Storage.
"""

from fastapi import HTTPException
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY, STORAGE_BUCKET, MAX_AVATAR_SIZE
import httpx

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
        raise HTTPException(status_code=502, detail="Failed to upload avatar")
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
        raise HTTPException(status_code=502, detail="Failed to upload cosmetic asset")
    public_url = f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{path}"
    return public_url


def delete_asset(path: str) -> None:
    url = f"{_storage_base}/{STORAGE_BUCKET}/{path}"
    httpx.delete(url, headers=_headers)
