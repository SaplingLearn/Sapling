"""Unit tests for services/notes_service.py.

Pins the encryption boundary (title/body are ciphertext at rest,
plaintext in the return shape) and the CRUD contract used by
routes/notes.py.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from services.notes_service import (
    create_note,
    delete_note,
    get_note,
    list_notes,
    update_note,
)


def _run(coro):
    return asyncio.run(coro)


class FakeTable:
    """Minimal stand-in for db.connection.table() returning recorded calls."""
    def __init__(self, rows=None):
        self.rows = rows or []
        self.inserted = []
        self.updated = []
        self.deleted = []
        self.select_calls = []

    def select(self, *args, **kwargs):
        self.select_calls.append((args, kwargs))
        return list(self.rows)

    def insert(self, data):
        self.inserted.append(data)
        return [data]

    def update(self, data, filters):
        self.updated.append((data, filters))
        return [{**self.rows[0], **data} if self.rows else data]

    def delete(self, filters):
        self.deleted.append(filters)
        return []


def test_create_note_encrypts_title_and_body():
    fake = FakeTable()
    with patch("services.notes_service.table", return_value=fake):
        out = _run(create_note(
            user_id="u1",
            course_id="c1",
            title="Photosynthesis",
            body="Light reactions happen in the thylakoid",
            tags=["lecture"],
        ))

    assert fake.inserted, "insert was not called"
    row = fake.inserted[0]
    # Title and body must NOT be plaintext in the row written to Supabase.
    assert row["title"] != "Photosynthesis"
    assert row["body"] != "Light reactions happen in the thylakoid"
    # Return shape must hand back plaintext for the caller to render.
    assert out["title"] == "Photosynthesis"
    assert out["body"] == "Light reactions happen in the thylakoid"
    assert out["tags"] == ["lecture"]
    assert out["user_id"] == "u1"
    assert out["course_id"] == "c1"
    assert isinstance(out["id"], str) and len(out["id"]) > 0


def test_get_note_decrypts_and_enforces_ownership():
    from services.encryption import encrypt
    fake = FakeTable(rows=[{
        "id": "n1",
        "user_id": "u1",
        "course_id": "c1",
        "title": encrypt("My title"),
        "body": encrypt("My body"),
        "tags": ["a"],
        "last_summary": None,
        "last_summary_at": None,
        "created_at": "2026-05-11T00:00:00Z",
        "updated_at": "2026-05-11T00:00:00Z",
    }])
    with patch("services.notes_service.table", return_value=fake):
        out = _run(get_note(note_id="n1", user_id="u1"))

    assert out["title"] == "My title"
    assert out["body"] == "My body"
    # Caller must filter on both id AND user_id — verifies ownership in the query.
    call_args, call_kwargs = fake.select_calls[0]
    filters = call_kwargs.get("filters", {})
    assert filters.get("id") == "eq.n1"
    assert filters.get("user_id") == "eq.u1"


def test_get_note_returns_none_when_missing():
    fake = FakeTable(rows=[])
    with patch("services.notes_service.table", return_value=fake):
        out = _run(get_note(note_id="missing", user_id="u1"))
    assert out is None


def test_update_note_only_encrypts_present_fields():
    from services.encryption import encrypt
    fake = FakeTable(rows=[{
        "id": "n1", "user_id": "u1", "course_id": "c1",
        "title": encrypt("Old"), "body": encrypt("Old body"),
        "tags": [], "last_summary": None, "last_summary_at": None,
        "created_at": "2026-05-11T00:00:00Z",
        "updated_at": "2026-05-11T00:00:00Z",
    }])
    with patch("services.notes_service.table", return_value=fake):
        out = _run(update_note(
            note_id="n1", user_id="u1",
            patch={"title": "New title"},
        ))
    assert fake.updated, "update was not called"
    data, _filters = fake.updated[0]
    # Body must NOT be in the update payload (we only patched title).
    assert "body" not in data
    # Title must be ciphertext in the update payload.
    assert data["title"] != "New title"
    # updated_at must be stamped.
    assert "updated_at" in data
    # Return shape: plaintext title comes back.
    assert out["title"] == "New title"


def test_list_notes_filters_by_user_and_optional_course():
    fake = FakeTable(rows=[])
    with patch("services.notes_service.table", return_value=fake):
        _run(list_notes(user_id="u1", course_id="c1"))
    args, kwargs = fake.select_calls[0]
    filters = kwargs.get("filters", {})
    assert filters.get("user_id") == "eq.u1"
    assert filters.get("course_id") == "eq.c1"


def test_delete_note_scopes_by_user():
    fake = FakeTable()
    with patch("services.notes_service.table", return_value=fake):
        _run(delete_note(note_id="n1", user_id="u1"))
    assert fake.deleted == [{"id": "eq.n1", "user_id": "eq.u1"}]
