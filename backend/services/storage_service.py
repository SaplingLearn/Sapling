"""
Storage service for avatar and cosmetic asset uploads via Supabase Storage.
"""

import logging

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
    elif resp.status_code == 409:
        # "Bucket already exists" — expected on every restart after the
        # first. Don't log at warning level; this is the steady-state path.
        logger.debug("Storage bucket %s already exists.", bucket_id)
    else:
        logger.warning(
            "ensure_bucket_exists(%s): Supabase returned %d body=%s",
            bucket_id,
            resp.status_code,
            (resp.text or "").strip()[:300],
        )


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
