"""CRUD service for the notetaker.

The encryption boundary lives entirely in this module: every write
encrypts `title` and `body` before reaching Supabase; every read
decrypts before returning. Routes never touch ciphertext directly.

Schema (see backend/db/migrations/0025_study_integrity.sql):
    notes(id, user_id, offering_id, title*, body*, tags text[],
          last_summary*, last_summary_at, created_at, updated_at, deleted_at)
    * = AES-GCM encrypted at rest.

Notes key on the OFFERING (a course taught in a specific term), not the
abstract catalog course. Soft-delete via `deleted_at`: deletes stamp the
column and every read filters `deleted_at IS NULL`.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from db.connection import table
from services.encryption import (
    decrypt_if_present,
    encrypt_if_present,
)


_SELECT_COLS = (
    "id,user_id,offering_id,title,body,tags,"
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
    offering_id: str,
    title: str = "",
    body: str = "",
    tags: list[str] | None = None,
) -> dict:
    note_id = str(uuid.uuid4())
    now = _now_iso()
    row = {
        "id": note_id,
        "user_id": user_id,
        "offering_id": offering_id,
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
            filters={
                "id": f"eq.{note_id}",
                "user_id": f"eq.{user_id}",
                "deleted_at": "is.null",
            },
            limit=1,
        ) or []

    rows = await asyncio.to_thread(_fetch)
    if not rows:
        return None
    return _decrypt_row(rows[0])


async def list_notes(
    user_id: str,
    offering_id: str | list[str] | None = None,
) -> list[dict]:
    """The user's live notes, newest first. ``offering_id`` narrows them to
    one offering, or (a list) to any of several — a course's offerings."""
    filters: dict[str, str] = {"user_id": f"eq.{user_id}", "deleted_at": "is.null"}
    if isinstance(offering_id, list):
        filters["offering_id"] = f"in.({','.join(offering_id)})"
    elif offering_id:
        filters["offering_id"] = f"eq.{offering_id}"

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
    if "offering_id" in patch:
        update["offering_id"] = patch["offering_id"]

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
    """Soft delete (0025): stamp ``deleted_at`` instead of removing the row,
    so reads filter it out while the data stays recoverable. Stays scoped to
    the owner."""
    def _do() -> None:
        table("notes").update(
            {"deleted_at": _now_iso()},
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
            filters={
                "id": f"eq.{note_id}",
                "user_id": f"eq.{user_id}",
                "deleted_at": "is.null",
            },
        ) or []

    rows = await asyncio.to_thread(_do)
    if not rows:
        return None
    return _decrypt_row(rows[0])


async def _owned(
    table_name: str, row_id: str, user_id: str, extra: dict | None = None
) -> bool:
    """The one ownership probe behind the note AND node checks: does
    `table_name` hold a row `row_id` owned by `user_id`? A row that is
    someone else's, and a row that does not exist (or vanished), are the
    same False — callers turn both into one 404, so the answer is never an
    existence oracle for another student's ids."""
    filters = {"id": f"eq.{row_id}", "user_id": f"eq.{user_id}", **(extra or {})}

    def _fetch() -> list[dict]:
        return table(table_name).select("id", filters=filters, limit=1) or []
    rows = await asyncio.to_thread(_fetch)
    return bool(rows)


async def _note_belongs_to_user(note_id: str, user_id: str) -> bool:
    return await _owned("notes", note_id, user_id, {"deleted_at": "is.null"})


async def _node_belongs_to_user(node_id: str, user_id: str) -> bool:
    return await _owned("graph_nodes", node_id, user_id)


# Postgres foreign_key_violation. PostgREST answers it with a 409 — the same
# status as a unique conflict — so only the body's SQLSTATE tells them apart.
_FK_VIOLATION = "23503"


def _is_fk_violation(exc: httpx.HTTPStatusError) -> bool:
    if exc.response.status_code != 409:
        return False
    try:
        body = exc.response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("code") == _FK_VIOLATION


def _upsert_links(rows: list[dict]) -> bool:
    """Write junction rows idempotently: ON CONFLICT (note_id,
    concept_node_id) DO NOTHING, so re-linking an already-linked concept
    (or re-running extract-concepts) is a no-op, not a PK-conflict 500.

    Returns False when a row's note or node vanished between the caller's
    ownership check and this write (the FK refuses it) — the same answer as
    a node the caller never owned. Any other failure propagates."""
    try:
        table("note_concepts").upsert(
            rows, on_conflict="note_id,concept_node_id", ignore_duplicates=True
        )
    except httpx.HTTPStatusError as exc:
        if _is_fk_violation(exc):
            return False
        raise
    return True


async def link_concept(
    note_id: str, user_id: str, concept_node_id: str
) -> bool:
    """Link a concept node to a note (idempotent). Returns True when the
    link exists afterwards, False if the note OR the concept node does not
    belong to user_id — including a node (or note) that does not exist or
    was deleted mid-request (silent reject — caller converts to 404).

    The node check closes a cross-user write (#115): without it a caller
    could link another student's graph node to their own note, and the
    FK answer (insert ok vs. violation) was an existence oracle for any
    node id. A foreign node, a missing node and one that vanishes between
    the check and the write all take the same False.
    """
    if not await _note_belongs_to_user(note_id, user_id):
        return False
    if not await _node_belongs_to_user(concept_node_id, user_id):
        return False
    row = {"note_id": note_id, "concept_node_id": concept_node_id}
    return await asyncio.to_thread(_upsert_links, [row])


async def link_prechecked_concepts(note_id: str, node_ids: list[str]) -> int:
    """Bulk-link nodes to a note with NO ownership checks — one write
    instead of two probes plus an insert per node.

    The caller MUST already have proved both sides belong to the student:
    the note via a user-scoped read (`get_note`), the nodes via a
    `graph_nodes` select filtered by the same `user_id` (extract-concepts
    does both). Anything else goes through `link_concept`.

    Idempotent like `link_concept`. If the batch hits an FK violation (a
    node deleted concurrently), it retries row by row so the survivors still
    link. Returns how many links exist afterwards."""
    ids = list(dict.fromkeys(i for i in node_ids if i))
    if not ids:
        return 0
    rows = [{"note_id": note_id, "concept_node_id": i} for i in ids]
    if await asyncio.to_thread(_upsert_links, rows):
        return len(rows)
    linked = 0
    for row in rows:
        if await asyncio.to_thread(_upsert_links, [row]):
            linked += 1
    return linked


async def unlink_concept(
    note_id: str, user_id: str, concept_node_id: str
) -> bool:
    """Remove a (note, node) link. False — the caller's 404 — when the note
    or the node is not the caller's (or no longer exists), and when there
    was no such link to remove."""
    if not await _note_belongs_to_user(note_id, user_id):
        return False
    if not await _node_belongs_to_user(concept_node_id, user_id):
        return False

    def _delete() -> list:
        return table("note_concepts").delete(
            filters={
                "note_id": f"eq.{note_id}",
                "concept_node_id": f"eq.{concept_node_id}",
            }
        ) or []
    removed = await asyncio.to_thread(_delete)
    return bool(removed)


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
