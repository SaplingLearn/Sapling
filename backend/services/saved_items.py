"""What a student saved from a tutor session (the Tutor session panel's
"Saved" tab; Tutor redesign, owner decision 2026-11-26), behind the
`saved_items` flag.

One `tutor_saved_items` row per saved thing: its session, the session's
abstract course (from the session's offering, so a course's items list
without a join), a short title and the saved text. Both texts are 🔒 columns
(services/encryption.py), sealed to the row id, which is minted here before
the insert. Only a session the student owns, and that has a row (a chatted-in
session), can hold saved items.
"""
from __future__ import annotations

import uuid

from db.connection import table
from services import encryption
from services.academics import offering_course_id

TABLE = "tutor_saved_items"
SAVED_ITEMS_FLAG = "saved_items"

#: Caps: a title is a label, the content one message (the tutor's replies are
#: far shorter); a session holds a page of items, not an archive.
TITLE_MAX = 200
CONTENT_MAX = 20_000
PER_SESSION_MAX = 50


class SavedItemError(Exception):
    """A request the store refuses: `status` is the HTTP answer the route gives."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _bind(column: str, item_id: str):
    return encryption.bind(TABLE, column, {"id": item_id})


def _public(row: dict) -> dict:
    item_id = row["id"]
    return {
        "id": item_id,
        "session_id": row.get("session_id"),
        "course_id": row.get("course_id"),
        "title": encryption.decrypt_if_present(row.get("title"), bind=_bind("title", item_id)) or "",
        "content": encryption.decrypt_if_present(row.get("content"), bind=_bind("content", item_id)) or "",
        "created_at": row.get("created_at"),
    }


def _owned_session(user_id: str, session_id: str) -> dict:
    rows = table("sessions").select("id,user_id,offering_id", filters={"id": f"eq.{session_id}"}, limit=1) or []
    if not rows or rows[0].get("user_id") != user_id:
        raise SavedItemError(404, "Session not found")
    return rows[0]


def list_saved_items(user_id: str, *, session_id: str | None = None, course_id: str | None = None) -> list[dict]:
    """The student's saved items, newest first; one session's, or one course's."""
    filters = {"user_id": f"eq.{user_id}"}
    if session_id:
        filters["session_id"] = f"eq.{session_id}"
    if course_id:
        filters["course_id"] = f"eq.{course_id}"
    rows = table(TABLE).select("id,session_id,course_id,title,content,created_at",
                               filters=filters, order="created_at.desc", limit=200) or []
    return [_public(r) for r in rows]


def create_saved_item(user_id: str, *, session_id: str, title: str, content: str) -> dict:
    title, content = (title or "").strip(), (content or "").strip()
    if not content:
        raise SavedItemError(422, "Nothing to save")
    title = (title or content.splitlines()[0])[:TITLE_MAX].strip() or "Saved"
    if len(content) > CONTENT_MAX:
        raise SavedItemError(422, "That is too long to save")
    session = _owned_session(user_id, session_id)
    held = table(TABLE).select("id", filters={"user_id": f"eq.{user_id}", "session_id": f"eq.{session_id}"},
                               limit=PER_SESSION_MAX + 1) or []
    if len(held) >= PER_SESSION_MAX:
        raise SavedItemError(409, "This session's Saved list is full")
    offering = session.get("offering_id") or ""
    item_id = str(uuid.uuid4())
    row = {
        "id": item_id,
        "user_id": user_id,
        "session_id": session_id,
        "course_id": (offering_course_id(offering) or None) if offering else None,
        "title": encryption.encrypt_if_present(title, bind=_bind("title", item_id)),
        "content": encryption.encrypt_if_present(content, bind=_bind("content", item_id)),
    }
    saved = table(TABLE).insert(row) or [row]
    return _public({**row, **(saved[0] if isinstance(saved, list) and saved else {})})


def delete_saved_item(user_id: str, item_id: str) -> None:
    rows = table(TABLE).select("id,user_id", filters={"id": f"eq.{item_id}"}, limit=1) or []
    if not rows or rows[0].get("user_id") != user_id:
        raise SavedItemError(404, "Saved item not found")
    table(TABLE).delete(filters={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"})
