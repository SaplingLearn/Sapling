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


async def _note_belongs_to_user(note_id: str, user_id: str) -> bool:
    def _fetch() -> list[dict]:
        return table("notes").select(
            "id",
            filters={"id": f"eq.{note_id}", "user_id": f"eq.{user_id}"},
            limit=1,
        ) or []
    rows = await asyncio.to_thread(_fetch)
    return bool(rows)


async def link_concept(
    note_id: str, user_id: str, concept_node_id: str
) -> bool:
    """Insert a (note_id, concept_node_id) row. Returns True on success,
    False if the note does not belong to user_id (silent reject — caller
    converts to 404)."""
    if not await _note_belongs_to_user(note_id, user_id):
        return False

    def _insert() -> None:
        table("note_concepts").insert(
            {"note_id": note_id, "concept_node_id": concept_node_id}
        )
    await asyncio.to_thread(_insert)
    return True


async def unlink_concept(
    note_id: str, user_id: str, concept_node_id: str
) -> bool:
    if not await _note_belongs_to_user(note_id, user_id):
        return False

    def _delete() -> None:
        table("note_concepts").delete(
            filters={
                "note_id": f"eq.{note_id}",
                "concept_node_id": f"eq.{concept_node_id}",
            }
        )
    await asyncio.to_thread(_delete)
    return True


async def list_linked_concepts(note_id: str, user_id: str) -> list[dict]:
    """Return linked concepts decorated with mastery_tier + concept_name.

    Two queries: pull junction rows, then graph_nodes by id IN (...).
    Scoped to user_id at the graph_nodes layer so a stale junction row
    pointing at another user's node never leaks.
    """
    def _fetch_links() -> list[dict]:
        return table("note_concepts").select(
            "concept_node_id",
            filters={"note_id": f"eq.{note_id}"},
        ) or []

    links = await asyncio.to_thread(_fetch_links)
    if not links:
        return []
    ids = [l["concept_node_id"] for l in links if l.get("concept_node_id")]
    if not ids:
        return []

    in_clause = "in.(" + ",".join(ids) + ")"
    def _fetch_nodes() -> list[dict]:
        return table("graph_nodes").select(
            "id,concept_name,mastery_tier,mastery_score,course_id",
            filters={"user_id": f"eq.{user_id}", "id": in_clause},
        ) or []
    nodes = await asyncio.to_thread(_fetch_nodes)
    return nodes
