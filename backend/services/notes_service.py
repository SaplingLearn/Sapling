"""CRUD service for the notetaker.

The encryption boundary lives entirely in this module: every write
encrypts `title` and `body` before reaching Supabase; every read
decrypts before returning. Routes never touch ciphertext directly.

Schema (see backend/db/migration_notes.sql):
    notes(id, user_id, course_id, title*, body*, tags text[],
          last_summary*, last_summary_at, created_at, updated_at)
    * = AES-GCM encrypted at rest.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from db.connection import table
from services.encryption import (
    decrypt_if_present,
    encrypt_if_present,
)


_SELECT_COLS = (
    "id,user_id,course_id,title,body,tags,"
    "last_summary,last_summary_at,created_at,updated_at"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decrypt_row(row: dict) -> dict:
    out = dict(row)
    out["title"] = decrypt_if_present(out.get("title")) or ""
    out["body"] = decrypt_if_present(out.get("body")) or ""
    out["last_summary"] = decrypt_if_present(out.get("last_summary"))
    out["tags"] = list(out.get("tags") or [])
    return out


async def create_note(
    user_id: str,
    course_id: str,
    title: str = "",
    body: str = "",
    tags: list[str] | None = None,
) -> dict:
    note_id = str(uuid.uuid4())
    now = _now_iso()
    row = {
        "id": note_id,
        "user_id": user_id,
        "course_id": course_id,
        "title": encrypt_if_present(title) if title else None,
        "body": encrypt_if_present(body) if body else None,
        "tags": list(tags or []),
        "created_at": now,
        "updated_at": now,
    }

    def _insert() -> None:
        table("notes").insert(row)

    await asyncio.to_thread(_insert)
    return _decrypt_row(row)


async def get_note(note_id: str, user_id: str) -> dict | None:
    def _fetch() -> list[dict]:
        return table("notes").select(
            _SELECT_COLS,
            filters={"id": f"eq.{note_id}", "user_id": f"eq.{user_id}"},
            limit=1,
        ) or []

    rows = await asyncio.to_thread(_fetch)
    if not rows:
        return None
    return _decrypt_row(rows[0])


async def list_notes(
    user_id: str,
    course_id: str | None = None,
) -> list[dict]:
    filters: dict[str, str] = {"user_id": f"eq.{user_id}"}
    if course_id:
        filters["course_id"] = f"eq.{course_id}"

    def _fetch() -> list[dict]:
        return table("notes").select(
            _SELECT_COLS,
            filters=filters,
            order="updated_at.desc",
        ) or []

    rows = await asyncio.to_thread(_fetch)
    return [_decrypt_row(r) for r in rows]


async def update_note(
    note_id: str,
    user_id: str,
    patch: dict[str, Any],
) -> dict | None:
    update: dict[str, Any] = {"updated_at": _now_iso()}
    if "title" in patch:
        update["title"] = encrypt_if_present(patch["title"]) if patch["title"] else None
    if "body" in patch:
        update["body"] = encrypt_if_present(patch["body"]) if patch["body"] else None
    if "tags" in patch:
        update["tags"] = list(patch["tags"] or [])
    if "course_id" in patch:
        update["course_id"] = patch["course_id"]

    def _do() -> list[dict]:
        return table("notes").update(
            update,
            filters={"id": f"eq.{note_id}", "user_id": f"eq.{user_id}"},
        ) or []

    rows = await asyncio.to_thread(_do)
    if not rows:
        return None
    return _decrypt_row(rows[0])


async def delete_note(note_id: str, user_id: str) -> None:
    def _do() -> None:
        table("notes").delete(
            filters={"id": f"eq.{note_id}", "user_id": f"eq.{user_id}"},
        )

    await asyncio.to_thread(_do)


async def save_summary(
    note_id: str,
    user_id: str,
    summary: str,
) -> dict | None:
    """Persist the latest `/summarize` agent output on the note row."""
    update = {
        "last_summary": encrypt_if_present(summary) if summary else None,
        "last_summary_at": _now_iso(),
        "updated_at": _now_iso(),
    }

    def _do() -> list[dict]:
        return table("notes").update(
            update,
            filters={"id": f"eq.{note_id}", "user_id": f"eq.{user_id}"},
        ) or []

    rows = await asyncio.to_thread(_do)
    if not rows:
        return None
    return _decrypt_row(rows[0])
