"""Private, encrypted storage for editable imports' original files."""
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from starlette.responses import Response

from services.encryption import Binding, decrypt_bytes, encrypt_bytes
from services.storage_service import _headers, _storage_base, delete_objects

BUCKET = "note-originals"
MAX_IMPORT_BYTES = 2 * 1024 * 1024


def original_path(user_id: str, note_id: str) -> str:
    return f"{user_id}/{note_id}"


def store_original(user_id: str, note_id: str, contents: bytes) -> int:
    path = original_path(user_id, note_id)
    encrypted = encrypt_bytes(contents, bind=Binding(BUCKET, "file", path), v2=True).encode("ascii")
    response = httpx.post(
        f"{_storage_base}/{BUCKET}/{path}",
        content=encrypted,
        headers={**_headers, "Content-Type": "application/octet-stream"},
        timeout=30.0,
    )
    response.raise_for_status()
    return len(encrypted)


def remove_originals(user_id: str, note_ids: list[str]) -> None:
    delete_objects(BUCKET, [original_path(user_id, note_id) for note_id in note_ids])


def download_original(note: dict) -> Response:
    path = original_path(note["user_id"], note["id"])
    response = httpx.get(
        f"{_storage_base}/authenticated/{BUCKET}/{path}", headers=_headers, timeout=30.0
    )
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Original file is unavailable.")
    response.raise_for_status()
    data = decrypt_bytes(response.text, bind=Binding(BUCKET, "file", path))
    filename = quote(note["original_filename"], safe="")
    return Response(
        data,
        media_type=note["original_type"],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
