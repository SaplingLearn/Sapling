# Notetaker Dynamic Frontend + Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the static notetaker page at `frontend/src/app/(shell)/notetaker/page.tsx` to a real backend — notes, concept-links, AI summarize/extract/chat/quiz actions — using two new Supabase tables, three new Pydantic AI agents, and a new `routes/notes.py` router.

**Architecture:** Two encrypted-text tables (`notes`, `note_concepts`). One thin service for CRUD with encryption at the boundary. One router under `/api/notes`. Three small-output-type agents (`note_summary`, `note_concepts`, `note_chat`) that follow the established pattern from refactors #1–#4 — each agent uses `SaplingDeps`, registers in `_providers.py` for env-overridable model selection, and reuses existing tools (`apply_concepts_to_graph`, `read_user_progress`, `search_course_materials`) where useful. Frontend replaces the mock `SEED_NOTES` with API-driven state, adds debounced autosave, and wires the four Sapling action buttons + AI Chat panel.

**Tech Stack:** FastAPI, Supabase (REST via `db.connection.table()`), Pydantic AI 0.x agents over `gemini-2.5-flash` / `flash-lite`, `services/encryption.py` (AES-GCM column-level), Next.js 15 / React 19, pytest with the existing `tests/conftest.py` mocks.

**Spec context:** the existing page (`frontend/src/app/(shell)/notetaker/page.tsx`) is the spec — every interaction it scaffolds (CRUD, filters, search, course picker, concept link, tags, the four action buttons, the AI chat panel) maps to a task below.

**Frontend testing note:** Per CLAUDE.md and prior plans, frontend uses `npx tsc --noEmit` + manual browser smoke as the verification gate. Backend uses real TDD with pytest.

---

## File Map

**Created:**
- `backend/db/migration_notes.sql`
- `backend/services/notes_service.py`
- `backend/routes/notes.py`
- `backend/agents/note_summary.py`
- `backend/agents/note_concepts.py`
- `backend/agents/note_chat.py`
- `backend/agents/tools/note_context.py`
- `backend/tests/test_notes_service.py`
- `backend/tests/test_notes_routes.py`
- `backend/tests/test_note_agents_imports.py`
- `backend/tests/test_note_context_tool.py`

**Modified:**
- `backend/db/supabase_schema.sql` — append `notes` + `note_concepts` CREATE TABLEs
- `backend/agents/_providers.py` — add `note_summary`, `note_concepts`, `note_chat` task slots
- `backend/main.py` — mount `routes.notes` at `/api/notes`
- `frontend/src/lib/types.ts` — add `Note`, `LinkedConcept` types
- `frontend/src/lib/api.ts` — add notes API helpers
- `frontend/src/app/(shell)/notetaker/page.tsx` — replace mock state with API hooks, wire all actions

---

## Phase 0 — Schema

### Task 1: Create the `notes` and `note_concepts` migration

**Files:**
- Create: `backend/db/migration_notes.sql`
- Modify: `backend/db/supabase_schema.sql` (append after the last CREATE TABLE)

- [ ] **Step 1: Write the migration file**

Create `backend/db/migration_notes.sql`:

```sql
-- Migration: Notetaker tables (notes + note_concepts)
-- notes.title and notes.body are AES-GCM encrypted at the application layer
-- (services/encryption.py). tags is plaintext text[] so PostgREST array
-- filters work for tag-based search. last_summary is the cached output of
-- the most recent /summarize action; null until the user runs it.
--
-- note_concepts is a junction table linking notes <-> graph_nodes.
-- ON DELETE CASCADE on note_id ensures deleting a note cleans up its
-- links. The graph_node FK is intentionally NOT a hard FK because
-- graph_nodes uses TEXT ids managed by application code (no enforced FK
-- pattern elsewhere in this codebase — see graph_edges.source_node_id).

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    title TEXT,
    body TEXT,
    tags TEXT[] NOT NULL DEFAULT '{}',
    last_summary TEXT,
    last_summary_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notes_user_updated
    ON notes (user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_notes_user_course
    ON notes (user_id, course_id);

CREATE TABLE IF NOT EXISTS note_concepts (
    note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    concept_node_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (note_id, concept_node_id)
);

CREATE INDEX IF NOT EXISTS idx_note_concepts_concept
    ON note_concepts (concept_node_id);
```

- [ ] **Step 2: Append the same DDL to `backend/db/supabase_schema.sql`**

Open `backend/db/supabase_schema.sql`, scroll to the bottom, and append the two `CREATE TABLE` statements and three indexes verbatim from Step 1 (drop the `IF NOT EXISTS` clauses to match the file's style; the file is the schema-of-record, not idempotent re-runs).

- [ ] **Step 3: Apply the migration on the Supabase dev project**

Apply via the Supabase MCP `apply_migration` tool with name `notes_tables` and the body of `migration_notes.sql`.

- [ ] **Step 4: Verify the tables exist**

Run via the Supabase MCP `execute_sql`:

```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema='public' AND table_name IN ('notes','note_concepts');
```

Expected: 2 rows.

- [ ] **Step 5: Commit**

```bash
git add backend/db/migration_notes.sql backend/db/supabase_schema.sql
git commit -m "feat(notes): add notes + note_concepts tables"
```

---

## Phase 1 — Notes service (encryption boundary)

### Task 2: CRUD primitives with encryption

**Files:**
- Create: `backend/services/notes_service.py`
- Test: `backend/tests/test_notes_service.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_notes_service.py`:

```python
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
```

- [ ] **Step 2: Run test, confirm it fails (import error)**

```bash
cd backend && python -m pytest tests/test_notes_service.py -q
```

Expected: ImportError on `services.notes_service`.

- [ ] **Step 3: Implement `services/notes_service.py`**

```python
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
```

- [ ] **Step 4: Run tests, confirm green**

```bash
cd backend && python -m pytest tests/test_notes_service.py -q
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/notes_service.py backend/tests/test_notes_service.py
git commit -m "feat(notes): notes CRUD service with column encryption"
```

---

## Phase 2 — Notes routes (CRUD)

### Task 3: Mount `routes/notes.py` with list/create/get/update/delete

**Files:**
- Create: `backend/routes/notes.py`
- Test: `backend/tests/test_notes_routes.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_notes_routes.py`:

```python
"""Route tests for /api/notes.

Uses the autouse `_bypass_session_auth` fixture from conftest.py — every
test exercises route logic via the TestClient with `user_id` resolved
from query/path/body to "user_andres" by default.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestListNotes:
    def test_returns_notes_for_user(self, client):
        notes = [
            {"id": "n1", "user_id": "u1", "course_id": "c1",
             "title": "A", "body": "", "tags": [],
             "last_summary": None, "last_summary_at": None,
             "created_at": "2026-05-11T00:00:00Z",
             "updated_at": "2026-05-11T00:00:00Z"},
        ]
        async def fake_list(user_id, course_id=None):
            assert user_id == "u1"
            assert course_id is None
            return notes
        with patch("routes.notes.list_notes", side_effect=fake_list):
            r = client.get("/api/notes/user/u1")
        assert r.status_code == 200
        assert r.json() == {"notes": notes}

    def test_course_filter_passes_through(self, client):
        async def fake_list(user_id, course_id=None):
            assert course_id == "c2"
            return []
        with patch("routes.notes.list_notes", side_effect=fake_list):
            r = client.get("/api/notes/user/u1?course_id=c2")
        assert r.status_code == 200


class TestCreateNote:
    def test_creates_with_required_fields(self, client):
        async def fake_create(user_id, course_id, title, body, tags):
            return {"id": "n1", "user_id": user_id, "course_id": course_id,
                    "title": title, "body": body, "tags": tags,
                    "last_summary": None, "last_summary_at": None,
                    "created_at": "2026-05-11T00:00:00Z",
                    "updated_at": "2026-05-11T00:00:00Z"}
        with patch("routes.notes.create_note", side_effect=fake_create):
            r = client.post(
                "/api/notes",
                json={"user_id": "u1", "course_id": "c1",
                      "title": "T", "body": "B", "tags": ["a"]},
            )
        assert r.status_code == 200
        assert r.json()["id"] == "n1"

    def test_missing_course_id_returns_422(self, client):
        r = client.post(
            "/api/notes",
            json={"user_id": "u1", "title": "T"},
        )
        assert r.status_code == 422


class TestGetNote:
    def test_returns_note_when_owned(self, client):
        async def fake_get(note_id, user_id):
            return {"id": note_id, "user_id": user_id, "course_id": "c1",
                    "title": "T", "body": "B", "tags": [],
                    "last_summary": None, "last_summary_at": None,
                    "created_at": "2026-05-11T00:00:00Z",
                    "updated_at": "2026-05-11T00:00:00Z"}
        with patch("routes.notes.get_note", side_effect=fake_get):
            r = client.get("/api/notes/n1?user_id=u1")
        assert r.status_code == 200
        assert r.json()["id"] == "n1"

    def test_returns_404_when_missing(self, client):
        async def fake_get(note_id, user_id):
            return None
        with patch("routes.notes.get_note", side_effect=fake_get):
            r = client.get("/api/notes/missing?user_id=u1")
        assert r.status_code == 404


class TestUpdateNote:
    def test_patches_title_only(self, client):
        captured = {}
        async def fake_update(note_id, user_id, patch):
            captured["patch"] = patch
            return {"id": note_id, "user_id": user_id, "course_id": "c1",
                    "title": patch.get("title", ""), "body": "", "tags": [],
                    "last_summary": None, "last_summary_at": None,
                    "created_at": "2026-05-11T00:00:00Z",
                    "updated_at": "2026-05-11T00:00:00Z"}
        with patch("routes.notes.update_note", side_effect=fake_update):
            r = client.patch(
                "/api/notes/n1",
                json={"user_id": "u1", "title": "New"},
            )
        assert r.status_code == 200
        assert captured["patch"] == {"title": "New"}

    def test_missing_returns_404(self, client):
        async def fake_update(note_id, user_id, patch):
            return None
        with patch("routes.notes.update_note", side_effect=fake_update):
            r = client.patch(
                "/api/notes/missing",
                json={"user_id": "u1", "title": "x"},
            )
        assert r.status_code == 404


class TestDeleteNote:
    def test_deletes(self, client):
        called = {}
        async def fake_delete(note_id, user_id):
            called["args"] = (note_id, user_id)
        with patch("routes.notes.delete_note", side_effect=fake_delete):
            r = client.delete("/api/notes/n1?user_id=u1")
        assert r.status_code == 200
        assert r.json() == {"deleted": True}
        assert called["args"] == ("n1", "u1")
```

- [ ] **Step 2: Run test, confirm it fails**

```bash
cd backend && python -m pytest tests/test_notes_routes.py -q
```

Expected: ImportError / module-not-found on `routes.notes`.

- [ ] **Step 3: Implement `routes/notes.py`**

```python
"""HTTP routes for the notetaker.

CRUD lives here; agent-backed actions (summarize, extract concepts, chat,
generate quiz, send to tutor) come in Phase 4 below.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services.auth_guard import get_session_user_id, require_self
from services.notes_service import (
    create_note,
    delete_note,
    get_note,
    list_notes,
    update_note,
)

router = APIRouter()


class CreateNoteBody(BaseModel):
    user_id: str
    course_id: str
    title: str = ""
    body: str = ""
    tags: list[str] = Field(default_factory=list)


class UpdateNoteBody(BaseModel):
    user_id: str
    title: str | None = None
    body: str | None = None
    tags: list[str] | None = None
    course_id: str | None = None


@router.get("/user/{user_id}")
async def list_user_notes(
    user_id: str,
    request: Request,
    course_id: str | None = None,
):
    require_self(user_id, request)
    notes = await list_notes(user_id=user_id, course_id=course_id)
    return {"notes": notes}


@router.post("")
async def create(body: CreateNoteBody, request: Request):
    require_self(body.user_id, request)
    note = await create_note(
        user_id=body.user_id,
        course_id=body.course_id,
        title=body.title,
        body=body.body,
        tags=body.tags,
    )
    return note


@router.get("/{note_id}")
async def read(note_id: str, request: Request, user_id: str):
    require_self(user_id, request)
    note = await get_note(note_id=note_id, user_id=user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    return note


@router.patch("/{note_id}")
async def patch(note_id: str, body: UpdateNoteBody, request: Request):
    require_self(body.user_id, request)
    patch_dict: dict = {}
    if body.title is not None:
        patch_dict["title"] = body.title
    if body.body is not None:
        patch_dict["body"] = body.body
    if body.tags is not None:
        patch_dict["tags"] = body.tags
    if body.course_id is not None:
        patch_dict["course_id"] = body.course_id
    if not patch_dict:
        raise HTTPException(status_code=400, detail="No fields to update.")
    updated = await update_note(
        note_id=note_id, user_id=body.user_id, patch=patch_dict
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Note not found.")
    return updated


@router.delete("/{note_id}")
async def remove(note_id: str, request: Request, user_id: str):
    require_self(user_id, request)
    await delete_note(note_id=note_id, user_id=user_id)
    return {"deleted": True}
```

- [ ] **Step 4: Mount the router**

Edit `backend/main.py`. Add `notes` to the line-24 routes import and the router-mount section. Around line 24:

```python
from routes import graph, learn, quiz, calendar, social, extract, auth, documents, flashcards, study_guide, feedback, careers, onboarding, gradebook, notes
```

And around line 155, after the `gradebook` mount:

```python
app.include_router(notes.router,       prefix="/api/notes")
```

- [ ] **Step 5: Run tests, confirm green**

```bash
cd backend && python -m pytest tests/test_notes_routes.py -q
```

Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/routes/notes.py backend/tests/test_notes_routes.py backend/main.py
git commit -m "feat(notes): CRUD routes under /api/notes"
```

---

## Phase 3 — Concept link routes

### Task 4: Link / unlink / read-with-mastery for concepts on a note

**Files:**
- Modify: `backend/routes/notes.py`
- Modify: `backend/services/notes_service.py` (add `list_linked_concepts`, `link_concept`, `unlink_concept`)
- Modify: `backend/tests/test_notes_service.py` (add 3 tests)
- Modify: `backend/tests/test_notes_routes.py` (add 3 tests)

- [ ] **Step 1: Add the failing service tests**

Append to `backend/tests/test_notes_service.py`:

```python
from services.notes_service import (
    link_concept,
    list_linked_concepts,
    unlink_concept,
)


class TestLinkedConcepts:
    def test_link_concept_inserts_junction_row(self):
        notes_fake = FakeTable(rows=[{"id": "n1", "user_id": "u1"}])
        nc_fake = FakeTable()
        def picker(name):
            return {"notes": notes_fake, "note_concepts": nc_fake}[name]
        with patch("services.notes_service.table", side_effect=picker):
            _run(link_concept(note_id="n1", user_id="u1", concept_node_id="g1"))
        assert nc_fake.inserted == [{"note_id": "n1", "concept_node_id": "g1"}]

    def test_link_concept_rejects_unowned_note(self):
        notes_fake = FakeTable(rows=[])  # no such note for this user
        nc_fake = FakeTable()
        def picker(name):
            return {"notes": notes_fake, "note_concepts": nc_fake}[name]
        with patch("services.notes_service.table", side_effect=picker):
            ok = _run(link_concept(note_id="n1", user_id="u1", concept_node_id="g1"))
        assert ok is False
        assert nc_fake.inserted == []

    def test_list_linked_concepts_joins_against_graph_nodes(self):
        nc_fake = FakeTable(rows=[
            {"note_id": "n1", "concept_node_id": "g1"},
            {"note_id": "n1", "concept_node_id": "g2"},
        ])
        nodes_fake = FakeTable(rows=[
            {"id": "g1", "concept_name": "Photosynthesis",
             "mastery_tier": "learning", "mastery_score": 0.5,
             "course_id": "c1"},
            {"id": "g2", "concept_name": "Calvin Cycle",
             "mastery_tier": "struggling", "mastery_score": 0.2,
             "course_id": "c1"},
        ])
        def picker(name):
            return {"note_concepts": nc_fake, "graph_nodes": nodes_fake}[name]
        with patch("services.notes_service.table", side_effect=picker):
            out = _run(list_linked_concepts(note_id="n1", user_id="u1"))
        names = {c["concept_name"] for c in out}
        assert names == {"Photosynthesis", "Calvin Cycle"}
        assert all("mastery_tier" in c for c in out)

    def test_unlink_concept_scopes_by_note(self):
        nc_fake = FakeTable()
        notes_fake = FakeTable(rows=[{"id": "n1", "user_id": "u1"}])
        def picker(name):
            return {"notes": notes_fake, "note_concepts": nc_fake}[name]
        with patch("services.notes_service.table", side_effect=picker):
            _run(unlink_concept(note_id="n1", user_id="u1", concept_node_id="g1"))
        assert nc_fake.deleted == [
            {"note_id": "eq.n1", "concept_node_id": "eq.g1"}
        ]
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd backend && python -m pytest tests/test_notes_service.py -q
```

Expected: 4 new tests fail with ImportError on the new symbols.

- [ ] **Step 3: Implement the service helpers**

Append to `backend/services/notes_service.py`:

```python
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
```

- [ ] **Step 4: Run service tests, confirm green**

```bash
cd backend && python -m pytest tests/test_notes_service.py -q
```

Expected: 10 passed total (6 from Task 2 + 4 new).

- [ ] **Step 5: Add route tests**

Append to `backend/tests/test_notes_routes.py`:

```python
class TestLinkConceptRoute:
    def test_list_linked(self, client):
        async def fake_list(note_id, user_id):
            return [{"id": "g1", "concept_name": "X",
                     "mastery_tier": "learning",
                     "mastery_score": 0.5, "course_id": "c1"}]
        with patch("routes.notes.list_linked_concepts", side_effect=fake_list):
            r = client.get("/api/notes/n1/concepts?user_id=u1")
        assert r.status_code == 200
        assert r.json() == {"concepts": [{
            "id": "g1", "concept_name": "X",
            "mastery_tier": "learning",
            "mastery_score": 0.5, "course_id": "c1",
        }]}

    def test_link(self, client):
        async def fake_link(note_id, user_id, concept_node_id):
            return True
        with patch("routes.notes.link_concept", side_effect=fake_link):
            r = client.post(
                "/api/notes/n1/concepts",
                json={"user_id": "u1", "concept_node_id": "g1"},
            )
        assert r.status_code == 200
        assert r.json() == {"linked": True}

    def test_unlink(self, client):
        async def fake_unlink(note_id, user_id, concept_node_id):
            return True
        with patch("routes.notes.unlink_concept", side_effect=fake_unlink):
            r = client.delete(
                "/api/notes/n1/concepts/g1?user_id=u1"
            )
        assert r.status_code == 200
        assert r.json() == {"unlinked": True}
```

- [ ] **Step 6: Add the route handlers**

Append to `backend/routes/notes.py` (after the existing imports, add the new symbols):

```python
from services.notes_service import (
    link_concept,
    list_linked_concepts,
    unlink_concept,
)


class LinkConceptBody(BaseModel):
    user_id: str
    concept_node_id: str


@router.get("/{note_id}/concepts")
async def list_concepts(note_id: str, request: Request, user_id: str):
    require_self(user_id, request)
    concepts = await list_linked_concepts(note_id=note_id, user_id=user_id)
    return {"concepts": concepts}


@router.post("/{note_id}/concepts")
async def link_concept_route(
    note_id: str, body: LinkConceptBody, request: Request
):
    require_self(body.user_id, request)
    ok = await link_concept(
        note_id=note_id,
        user_id=body.user_id,
        concept_node_id=body.concept_node_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Note not found.")
    return {"linked": True}


@router.delete("/{note_id}/concepts/{concept_node_id}")
async def unlink_concept_route(
    note_id: str,
    concept_node_id: str,
    request: Request,
    user_id: str,
):
    require_self(user_id, request)
    ok = await unlink_concept(
        note_id=note_id, user_id=user_id, concept_node_id=concept_node_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Note not found.")
    return {"unlinked": True}
```

- [ ] **Step 7: Run route tests, confirm green**

```bash
cd backend && python -m pytest tests/test_notes_routes.py -q
```

Expected: 11 passed total.

- [ ] **Step 8: Commit**

```bash
git add backend/services/notes_service.py backend/routes/notes.py backend/tests/test_notes_service.py backend/tests/test_notes_routes.py
git commit -m "feat(notes): link/unlink/list concept routes"
```

---

## Phase 4 — Agents (note_summary, note_concepts, note_chat)

### Task 5: Register the three task slots in `_providers.py`

**Files:**
- Modify: `backend/agents/_providers.py`

- [ ] **Step 1: Patch `_providers.py`**

Edit `backend/agents/_providers.py:29` (the `AgentTask` literal) and `:34` (the `_DEFAULTS` dict).

Change the `AgentTask` literal:

```python
AgentTask = Literal[
    "classifier", "summary", "concepts", "syllabus", "quiz", "chat_tutor",
    "note_summary", "note_concepts", "note_chat",
]
```

Add the three new entries to `_DEFAULTS` (note_summary + note_concepts run lite; note_chat runs flash because it has tool calls and benefits from stronger instruction-following than lite):

```python
    "note_summary": "gemini-2.5-flash-lite",
    "note_concepts": "gemini-2.5-flash-lite",
    "note_chat": "gemini-2.5-flash",
```

- [ ] **Step 2: Smoke-check**

```bash
cd backend && python -c "from agents._providers import model_for; print([model_for(t).model_name for t in ('note_summary','note_concepts','note_chat')])"
```

Expected: three Gemini model names printed.

- [ ] **Step 3: Commit**

```bash
git add backend/agents/_providers.py
git commit -m "feat(notes): register note_summary/note_concepts/note_chat model slots"
```

---

### Task 6: `agents/note_summary.py` — summarize agent

**Files:**
- Create: `backend/agents/note_summary.py`
- Test: `backend/tests/test_note_agents_imports.py`

- [ ] **Step 1: Write the failing import test**

Create `backend/tests/test_note_agents_imports.py`:

```python
"""Import-level smoke tests for the three notetaker agents.

Pins: each agent exists, has a stable prompt hash, declares the right
output type, and (for note_chat) registers its tools.
"""
from __future__ import annotations


def test_note_summary_agent_exists():
    from agents.note_summary import note_summary_agent, NoteSummary
    assert note_summary_agent is not None
    # Output type is the NoteSummary BaseModel with one `summary` field.
    fields = set(NoteSummary.model_fields.keys())
    assert fields == {"summary"}


def test_note_summary_prompt_hash_stable():
    from agents.note_summary import _PROMPT_HASH
    # Hash is 12 lowercase hex chars (sha256[:12]) — pin the shape so a
    # future refactor that drops the hash gets flagged.
    assert isinstance(_PROMPT_HASH, str) and len(_PROMPT_HASH) == 12


def test_note_concepts_agent_exists():
    from agents.note_concepts import note_concepts_agent, NoteConcepts
    assert note_concepts_agent is not None
    fields = set(NoteConcepts.model_fields.keys())
    assert fields == {"concepts"}


def test_note_chat_agent_exists_with_tools():
    from agents.note_chat import note_chat_agent
    tool_names = {t.name for t in note_chat_agent._function_tools.values()}
    # read_active_note must be registered; existing course-material and
    # graph-update tools come along for grounding.
    assert "read_active_note" in tool_names
    assert "apply_graph_update_tool" in tool_names or "apply_graph_update" in tool_names
```

- [ ] **Step 2: Run, confirm fail (ImportError)**

```bash
cd backend && python -m pytest tests/test_note_agents_imports.py -q
```

- [ ] **Step 3: Implement `agents/note_summary.py`**

```python
"""Note-summary agent — short paragraph summary of a single user note.

Output type is intentionally one field (NoteSummary.summary) per the
"keep agent output types small" lesson from
docs/attempts/2026-05-03-orchestrator-schema-complexity.md.
"""
from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps


class NoteSummary(BaseModel):
    summary: str = Field(
        description="2–4 sentence summary of the note's main idea.",
    )


_PROMPT = (
    "You are summarizing a single student's note. Produce a faithful "
    "2–4 sentence summary that captures the key idea and any "
    "explicit open questions the student wrote. Do not invent facts; "
    "if the note is empty or near-empty, say so plainly. Output Markdown."
)

_PROMPT_HASH = hashlib.sha256(_PROMPT.encode("utf-8")).hexdigest()[:12]


note_summary_agent = Agent[SaplingDeps, NoteSummary](
    model=model_for("note_summary"),
    deps_type=SaplingDeps,
    output_type=NoteSummary,
    system_prompt=_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "note_summary"},
)
```

- [ ] **Step 4: Run, confirm summary tests pass (chat/concepts still fail)**

```bash
cd backend && python -m pytest tests/test_note_agents_imports.py -q
```

---

### Task 7: `agents/note_concepts.py` — concept-extraction agent

**Files:**
- Create: `backend/agents/note_concepts.py`

- [ ] **Step 1: Implement the agent**

```python
"""Note-concept-extraction agent — pulls Title-Case concept names from
a single student note for merge into the user's knowledge graph.

Output is one field (a list of names) so the structured-output schema
stays well under Gemini's complexity threshold (see
docs/attempts/2026-05-03-orchestrator-schema-complexity.md).
"""
from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps


class NoteConcepts(BaseModel):
    concepts: list[str] = Field(
        default_factory=list,
        description=(
            "Title-Case noun phrases naming the distinct concepts the "
            "note covers. 0–15 entries. No assignment titles, page "
            "numbers, or administrative items."
        ),
    )


_PROMPT = (
    "You are extracting concept labels from a single student's note. "
    "Return up to 15 distinct Title-Case noun phrases (e.g. 'Linear "
    "Regression', 'Calvin Cycle'). Exclude assignment titles, week "
    "labels, problem numbers, and administrative items. If the note is "
    "empty or has no clear concepts, return an empty list."
)
_PROMPT_HASH = hashlib.sha256(_PROMPT.encode("utf-8")).hexdigest()[:12]


note_concepts_agent = Agent[SaplingDeps, NoteConcepts](
    model=model_for("note_concepts"),
    deps_type=SaplingDeps,
    output_type=NoteConcepts,
    system_prompt=_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "note_concepts"},
)
```

- [ ] **Step 2: Run, confirm concept tests pass**

```bash
cd backend && python -m pytest tests/test_note_agents_imports.py::test_note_concepts_agent_exists -q
```

---

### Task 8: `agents/tools/note_context.py` — `read_active_note` tool

**Files:**
- Create: `backend/agents/tools/note_context.py`
- Test: `backend/tests/test_note_context_tool.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_note_context_tool.py`:

```python
"""Unit tests for agents/tools/note_context.py."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from agents.tools.note_context import (
    NoteContext,
    read_active_note,
)


def _run(coro):
    return asyncio.run(coro)


def test_read_active_note_returns_title_body_concepts():
    async def fake_get_note(note_id, user_id):
        return {"id": note_id, "user_id": user_id, "course_id": "c1",
                "title": "Photosynthesis", "body": "Light reactions...",
                "tags": ["lecture"],
                "last_summary": None, "last_summary_at": None,
                "created_at": "", "updated_at": ""}
    async def fake_list_linked(note_id, user_id):
        return [{"id": "g1", "concept_name": "Photosynthesis",
                 "mastery_tier": "learning", "mastery_score": 0.5,
                 "course_id": "c1"}]

    with patch("agents.tools.note_context.get_note", side_effect=fake_get_note), \
         patch("agents.tools.note_context.list_linked_concepts", side_effect=fake_list_linked):
        out = _run(read_active_note(note_id="n1", user_id="u1"))

    assert isinstance(out, NoteContext)
    assert out.title == "Photosynthesis"
    assert out.body == "Light reactions..."
    assert out.tags == ["lecture"]
    assert len(out.linked_concepts) == 1
    assert out.linked_concepts[0].concept_name == "Photosynthesis"


def test_read_active_note_missing_returns_empty_context():
    async def fake_get_note(note_id, user_id):
        return None
    with patch("agents.tools.note_context.get_note", side_effect=fake_get_note):
        out = _run(read_active_note(note_id="x", user_id="u1"))
    assert out.title == ""
    assert out.body == ""
    assert out.linked_concepts == []
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd backend && python -m pytest tests/test_note_context_tool.py -q
```

- [ ] **Step 3: Implement the tool**

```python
"""Read tool for the note-chat agent.

The agent runs with `ctx.deps.session_id` overloaded to carry the
active note_id (the note-chat route sets it on SaplingDeps before
running the agent). `read_active_note` pulls the note body and its
linked concepts so the chat reply stays grounded in what the student
actually wrote.
"""
from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai import RunContext

from agents.deps import SaplingDeps
from services.notes_service import get_note, list_linked_concepts


class LinkedConcept(BaseModel):
    id: str
    concept_name: str
    mastery_tier: str
    mastery_score: float


class NoteContext(BaseModel):
    title: str
    body: str
    tags: list[str]
    linked_concepts: list[LinkedConcept]


async def read_active_note(note_id: str, user_id: str) -> NoteContext:
    note = await get_note(note_id=note_id, user_id=user_id)
    if not note:
        return NoteContext(title="", body="", tags=[], linked_concepts=[])
    concepts_raw = await list_linked_concepts(note_id=note_id, user_id=user_id)
    concepts = [
        LinkedConcept(
            id=c.get("id") or "",
            concept_name=c.get("concept_name") or "",
            mastery_tier=c.get("mastery_tier") or "unexplored",
            mastery_score=float(c.get("mastery_score") or 0.0),
        )
        for c in concepts_raw
    ]
    return NoteContext(
        title=note.get("title") or "",
        body=note.get("body") or "",
        tags=list(note.get("tags") or []),
        linked_concepts=concepts,
    )


async def read_active_note_tool(
    ctx: RunContext[SaplingDeps],
) -> NoteContext:
    """Pydantic AI wrapper.

    `note_id` rides on `ctx.deps.session_id` (the route sets it). The
    LLM never names whose note to read.
    """
    note_id = ctx.deps.session_id
    if not note_id:
        return NoteContext(title="", body="", tags=[], linked_concepts=[])
    return await read_active_note(note_id=note_id, user_id=ctx.deps.user_id)
```

- [ ] **Step 4: Run, confirm green**

```bash
cd backend && python -m pytest tests/test_note_context_tool.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/agents/note_summary.py backend/agents/note_concepts.py backend/agents/tools/note_context.py backend/tests/test_note_context_tool.py backend/tests/test_note_agents_imports.py
git commit -m "feat(notes): note_summary, note_concepts agents + read_active_note tool"
```

---

### Task 9: `agents/note_chat.py` — note-scoped chat agent

**Files:**
- Create: `backend/agents/note_chat.py`

- [ ] **Step 1: Implement**

```python
"""Note-scoped chat agent.

Powers the AI Chat panel inside the notetaker. Distinct from
`chat_tutor.py` because the scope is one note, not a course-wide
tutoring session, and the system prompt nudges the agent to ground
in what the student is actively writing.

Tools:
  - read_active_note (note-specific; from agents/tools/note_context.py)
  - search_course_materials (existing; reuses chat_tutor's grounding)
  - apply_graph_update (existing; lets the agent mark new concepts
    while answering, the same way the course tutor does)
"""
from __future__ import annotations

import hashlib

from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps
from agents.tools.chat_context import search_course_materials_tool
from agents.tools.graph import apply_graph_update_tool
from agents.tools.note_context import read_active_note_tool


_PROMPT = (
    "You are Sapling's quick-questions assistant inside the notetaker. "
    "The student is actively writing one note. Use `read_active_note` "
    "to ground every answer in the note's title, body, and linked "
    "concepts. Use `search_course_materials` when the question reaches "
    "beyond the note. Use `apply_graph_update_tool` when the student "
    "mentions a concept that isn't yet in their knowledge graph for "
    "this course.\n\n"
    "Tone: warm, concise, no filler. Use math/code blocks where helpful "
    "(LaTeX `$x^2$`, ```mermaid```, ```plot```). Keep replies short — "
    "this is a sidecar chat, not a tutoring session."
)
_PROMPT_HASH = hashlib.sha256(_PROMPT.encode("utf-8")).hexdigest()[:12]


note_chat_agent = Agent[SaplingDeps, str](
    model=model_for("note_chat"),
    deps_type=SaplingDeps,
    output_type=str,
    system_prompt=_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "note_chat"},
    tools=[
        read_active_note_tool,
        search_course_materials_tool,
        apply_graph_update_tool,
    ],
)
```

- [ ] **Step 2: Run all four import tests**

```bash
cd backend && python -m pytest tests/test_note_agents_imports.py -q
```

Expected: 4 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/agents/note_chat.py
git commit -m "feat(notes): note_chat agent with read_active_note + grounding tools"
```

---

## Phase 5 — Agent-backed routes

### Task 10: `/summarize` and `/extract-concepts` routes

**Files:**
- Modify: `backend/routes/notes.py`
- Modify: `backend/tests/test_notes_routes.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_notes_routes.py`:

```python
class TestSummarizeRoute:
    def test_runs_agent_and_persists(self, client):
        captured = {}
        class FakeResult:
            output = type("S", (), {"summary": "Short summary."})()
        async def fake_run(*args, **kwargs):
            captured["called"] = True
            return FakeResult()
        async def fake_get_note(note_id, user_id):
            return {"id": note_id, "user_id": user_id, "course_id": "c1",
                    "title": "T", "body": "Long body…", "tags": [],
                    "last_summary": None, "last_summary_at": None,
                    "created_at": "", "updated_at": ""}
        async def fake_save_summary(note_id, user_id, summary):
            captured["saved"] = summary
            return {"id": note_id, "last_summary": summary,
                    "last_summary_at": "2026-05-11T00:00:00Z",
                    "user_id": user_id, "course_id": "c1",
                    "title": "T", "body": "Long body…", "tags": [],
                    "created_at": "", "updated_at": ""}
        with patch("routes.notes.note_summary_agent.run", side_effect=fake_run), \
             patch("routes.notes.get_note", side_effect=fake_get_note), \
             patch("routes.notes.save_summary", side_effect=fake_save_summary):
            r = client.post(
                "/api/notes/n1/summarize",
                json={"user_id": "u1"},
            )
        assert r.status_code == 200
        assert r.json()["summary"] == "Short summary."
        assert captured["saved"] == "Short summary."

    def test_404_when_note_missing(self, client):
        async def fake_get_note(note_id, user_id):
            return None
        with patch("routes.notes.get_note", side_effect=fake_get_note):
            r = client.post(
                "/api/notes/missing/summarize",
                json={"user_id": "u1"},
            )
        assert r.status_code == 404


class TestExtractConceptsRoute:
    def test_extracts_and_links(self, client):
        class FakeResult:
            output = type("C", (), {"concepts": ["Photosynthesis", "Calvin Cycle"]})()
        async def fake_run(*args, **kwargs):
            return FakeResult()
        async def fake_get_note(note_id, user_id):
            return {"id": note_id, "user_id": user_id, "course_id": "c1",
                    "title": "T", "body": "B", "tags": [],
                    "last_summary": None, "last_summary_at": None,
                    "created_at": "", "updated_at": ""}
        merged: list[str] = []
        async def fake_apply(user_id, course_id, names):
            merged.extend(names)
            return len(names)
        async def fake_lookup(user_id, course_id, names):
            return [{"id": f"g_{n}", "concept_name": n} for n in names]
        linked: list[tuple[str, str]] = []
        async def fake_link(note_id, user_id, concept_node_id):
            linked.append((note_id, concept_node_id))
            return True

        with patch("routes.notes.note_concepts_agent.run", side_effect=fake_run), \
             patch("routes.notes.get_note", side_effect=fake_get_note), \
             patch("routes.notes.apply_concepts_to_graph", side_effect=fake_apply), \
             patch("routes.notes._lookup_concept_nodes_by_name", side_effect=fake_lookup), \
             patch("routes.notes.link_concept", side_effect=fake_link):
            r = client.post(
                "/api/notes/n1/extract-concepts",
                json={"user_id": "u1"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["concepts"] == ["Photosynthesis", "Calvin Cycle"]
        assert merged == ["Photosynthesis", "Calvin Cycle"]
        assert {n[1] for n in linked} == {"g_Photosynthesis", "g_Calvin Cycle"}
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd backend && python -m pytest tests/test_notes_routes.py::TestSummarizeRoute -q
```

- [ ] **Step 3: Implement the route handlers**

Append to `backend/routes/notes.py`. Add the new imports at the top:

```python
from agents.deps import SaplingDeps
from agents.note_concepts import note_concepts_agent
from agents.note_summary import note_summary_agent
from agents.tools.graph import apply_concepts_to_graph
from db.connection import table
from services.notes_service import save_summary
from services.request_context import current_request_id
```

Then add the request body model and helpers:

```python
class AgentActionBody(BaseModel):
    user_id: str


async def _lookup_concept_nodes_by_name(
    user_id: str, course_id: str | None, names: list[str]
) -> list[dict]:
    """Find graph_nodes for the freshly-merged concepts so we can link
    them to the note. Case-sensitive equality match — apply_graph_update
    normalizes on insert, so the names we get back from the agent should
    round-trip; if a node is missing here it means the merge skipped a
    duplicate, which is fine to silently drop."""
    import asyncio as _asyncio
    if not names:
        return []
    in_clause = "in.(" + ",".join(names) + ")"
    filters = {"user_id": f"eq.{user_id}", "concept_name": in_clause}
    if course_id:
        filters["course_id"] = f"eq.{course_id}"

    def _fetch() -> list[dict]:
        return table("graph_nodes").select(
            "id,concept_name", filters=filters
        ) or []
    return await _asyncio.to_thread(_fetch)


def _deps_for(user_id: str, course_id: str | None, note_id: str | None) -> SaplingDeps:
    from db.connection import _client  # type: ignore  # only for opaque pass-through
    return SaplingDeps(
        user_id=user_id,
        course_id=course_id,
        supabase=_client,
        request_id=current_request_id() or "",
        session_id=note_id,
    )


@router.post("/{note_id}/summarize")
async def summarize(note_id: str, body: AgentActionBody, request: Request):
    require_self(body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    user_prompt = (
        f"Title: {note.get('title') or '(untitled)'}\n\n"
        f"Body:\n{note.get('body') or '(empty)'}"
    )
    deps = _deps_for(body.user_id, note.get("course_id"), note_id)
    result = await note_summary_agent.run(user_prompt, deps=deps)
    summary_text = result.output.summary
    await save_summary(note_id=note_id, user_id=body.user_id, summary=summary_text)
    return {"summary": summary_text}


@router.post("/{note_id}/extract-concepts")
async def extract_concepts(
    note_id: str, body: AgentActionBody, request: Request
):
    require_self(body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    user_prompt = (
        f"Title: {note.get('title') or '(untitled)'}\n\n"
        f"Body:\n{note.get('body') or '(empty)'}"
    )
    deps = _deps_for(body.user_id, note.get("course_id"), note_id)
    result = await note_concepts_agent.run(user_prompt, deps=deps)
    names = [n.strip() for n in (result.output.concepts or []) if n and n.strip()]
    course_id = note.get("course_id")
    await apply_concepts_to_graph(
        user_id=body.user_id, course_id=course_id, concept_names=names
    )
    nodes = await _lookup_concept_nodes_by_name(
        user_id=body.user_id, course_id=course_id, names=names
    )
    for n in nodes:
        await link_concept(
            note_id=note_id, user_id=body.user_id,
            concept_node_id=n["id"],
        )
    return {"concepts": names, "linked": len(nodes)}
```

- [ ] **Step 4: Run summarize + extract tests**

```bash
cd backend && python -m pytest tests/test_notes_routes.py::TestSummarizeRoute tests/test_notes_routes.py::TestExtractConceptsRoute -q
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/routes/notes.py backend/tests/test_notes_routes.py
git commit -m "feat(notes): /summarize + /extract-concepts agent-backed routes"
```

---

### Task 11: `/chat` route (JSON, not SSE)

**Files:**
- Modify: `backend/routes/notes.py`
- Modify: `backend/tests/test_notes_routes.py`

The chat path mirrors `routes/learn.py::chat` — a single JSON request/response — rather than SSE. The streaming path is a future iteration; the existing notetaker UI just appends a finished message bubble after a 600ms simulated delay, so JSON is sufficient.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_notes_routes.py`:

```python
class TestNoteChatRoute:
    def test_runs_note_chat_agent(self, client):
        class FakeResult:
            output = "Here is a quick answer."
        async def fake_run(*args, **kwargs):
            return FakeResult()
        async def fake_get_note(note_id, user_id):
            return {"id": note_id, "user_id": user_id, "course_id": "c1",
                    "title": "T", "body": "B", "tags": [],
                    "last_summary": None, "last_summary_at": None,
                    "created_at": "", "updated_at": ""}
        with patch("routes.notes.note_chat_agent.run", side_effect=fake_run), \
             patch("routes.notes.get_note", side_effect=fake_get_note):
            r = client.post(
                "/api/notes/n1/chat",
                json={"user_id": "u1", "message": "What's the gist?"},
            )
        assert r.status_code == 200
        assert r.json() == {"reply": "Here is a quick answer."}
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd backend && python -m pytest tests/test_notes_routes.py::TestNoteChatRoute -q
```

- [ ] **Step 3: Implement**

Add at the top of `backend/routes/notes.py`:

```python
from agents.note_chat import note_chat_agent
```

And the body model + handler:

```python
class NoteChatBody(BaseModel):
    user_id: str
    message: str


@router.post("/{note_id}/chat")
async def note_chat(note_id: str, body: NoteChatBody, request: Request):
    require_self(body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    deps = _deps_for(body.user_id, note.get("course_id"), note_id)
    result = await note_chat_agent.run(body.message, deps=deps)
    return {"reply": result.output}
```

- [ ] **Step 4: Run, confirm green**

```bash
cd backend && python -m pytest tests/test_notes_routes.py::TestNoteChatRoute -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/routes/notes.py backend/tests/test_notes_routes.py
git commit -m "feat(notes): /chat JSON route powered by note_chat_agent"
```

---

### Task 12: `/send-to-tutor` and `/generate-quiz` proxy routes

**Files:**
- Modify: `backend/routes/notes.py`
- Modify: `backend/tests/test_notes_routes.py`

`/send-to-tutor` returns a `topic` + `course_id` payload the frontend can use to navigate to the Learn page and call `startSession`. `/generate-quiz` picks the lowest-mastery linked concept on the note and proxies to the existing quiz generation.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_notes_routes.py`:

```python
class TestSendToTutorRoute:
    def test_returns_topic_and_course(self, client):
        async def fake_get_note(note_id, user_id):
            return {"id": note_id, "user_id": user_id, "course_id": "c1",
                    "title": "Photosynthesis — light vs dark reactions",
                    "body": "B", "tags": [],
                    "last_summary": "A short summary",
                    "last_summary_at": "2026-05-11T00:00:00Z",
                    "created_at": "", "updated_at": ""}
        with patch("routes.notes.get_note", side_effect=fake_get_note):
            r = client.post(
                "/api/notes/n1/send-to-tutor",
                json={"user_id": "u1"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["course_id"] == "c1"
        # topic uses the note title (first 80 chars, single line).
        assert body["topic"].startswith("Photosynthesis")
        # preface carries note summary + body excerpt for the Learn page.
        assert "preface" in body and isinstance(body["preface"], str)


class TestGenerateQuizFromNote:
    def test_picks_lowest_mastery_linked_concept(self, client):
        async def fake_get_note(note_id, user_id):
            return {"id": note_id, "user_id": user_id, "course_id": "c1",
                    "title": "T", "body": "B", "tags": [],
                    "last_summary": None, "last_summary_at": None,
                    "created_at": "", "updated_at": ""}
        async def fake_list_linked(note_id, user_id):
            return [
                {"id": "g1", "concept_name": "Easy",
                 "mastery_tier": "mastered", "mastery_score": 0.9,
                 "course_id": "c1"},
                {"id": "g2", "concept_name": "Hard",
                 "mastery_tier": "struggling", "mastery_score": 0.2,
                 "course_id": "c1"},
            ]
        with patch("routes.notes.get_note", side_effect=fake_get_note), \
             patch("routes.notes.list_linked_concepts", side_effect=fake_list_linked):
            r = client.post(
                "/api/notes/n1/generate-quiz",
                json={"user_id": "u1"},
            )
        assert r.status_code == 200
        # The route hands the frontend the chosen concept_node_id; the
        # frontend then calls /api/quiz/generate. We don't proxy the
        # quiz call server-side because the existing client already
        # handles quiz state.
        assert r.json() == {"concept_node_id": "g2", "concept_name": "Hard"}

    def test_returns_400_when_no_linked_concepts(self, client):
        async def fake_get_note(note_id, user_id):
            return {"id": note_id, "user_id": user_id, "course_id": "c1",
                    "title": "", "body": "", "tags": [],
                    "last_summary": None, "last_summary_at": None,
                    "created_at": "", "updated_at": ""}
        async def fake_list_linked(note_id, user_id):
            return []
        with patch("routes.notes.get_note", side_effect=fake_get_note), \
             patch("routes.notes.list_linked_concepts", side_effect=fake_list_linked):
            r = client.post(
                "/api/notes/n1/generate-quiz",
                json={"user_id": "u1"},
            )
        assert r.status_code == 400
```

- [ ] **Step 2: Implement**

Append to `backend/routes/notes.py`:

```python
@router.post("/{note_id}/send-to-tutor")
async def send_to_tutor(
    note_id: str, body: AgentActionBody, request: Request
):
    require_self(body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    title = (note.get("title") or "").strip() or "Untitled note"
    topic = title.splitlines()[0][:80]
    preface_parts: list[str] = []
    if note.get("last_summary"):
        preface_parts.append(f"Note summary: {note['last_summary']}")
    body_text = (note.get("body") or "").strip()
    if body_text:
        preface_parts.append(f"Note excerpt:\n{body_text[:1500]}")
    preface = "\n\n".join(preface_parts)
    return {
        "topic": topic,
        "course_id": note.get("course_id"),
        "preface": preface,
    }


@router.post("/{note_id}/generate-quiz")
async def generate_quiz_from_note(
    note_id: str, body: AgentActionBody, request: Request
):
    require_self(body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    linked = await list_linked_concepts(note_id=note_id, user_id=body.user_id)
    if not linked:
        raise HTTPException(
            status_code=400,
            detail="Link at least one concept before generating a quiz.",
        )
    # Lowest mastery wins so the quiz targets the weakest spot.
    chosen = min(linked, key=lambda c: float(c.get("mastery_score") or 0.0))
    return {
        "concept_node_id": chosen.get("id"),
        "concept_name": chosen.get("concept_name"),
    }
```

- [ ] **Step 3: Run all route tests**

```bash
cd backend && python -m pytest tests/test_notes_routes.py -q
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add backend/routes/notes.py backend/tests/test_notes_routes.py
git commit -m "feat(notes): /send-to-tutor and /generate-quiz routes"
```

---

## Phase 6 — Frontend types + API helpers

### Task 13: Add Note types

**Files:**
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Append the types**

At the bottom of `frontend/src/lib/types.ts`, add:

```typescript
export interface LinkedConcept {
  id: string;
  concept_name: string;
  mastery_tier: 'mastered' | 'learning' | 'struggling' | 'unexplored' | 'subject_root';
  mastery_score: number;
  course_id: string | null;
}

export interface Note {
  id: string;
  user_id: string;
  course_id: string;
  title: string;
  body: string;
  tags: string[];
  last_summary: string | null;
  last_summary_at: string | null;
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

---

### Task 14: Add notes API helpers

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Append the helpers**

At the bottom of `frontend/src/lib/api.ts`, before any default exports, add:

```typescript
import type { Note, LinkedConcept } from '@/lib/types';

// Notes
export const listNotes = (userId: string, courseId?: string) => {
  const qs = courseId ? `?course_id=${encodeURIComponent(courseId)}` : '';
  return fetchJSON<{ notes: Note[] }>(`/api/notes/user/${userId}${qs}`);
};

export const createNote = (
  userId: string,
  courseId: string,
  title = '',
  body = '',
  tags: string[] = [],
) =>
  fetchJSON<Note>('/api/notes', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, course_id: courseId, title, body, tags }),
  });

export const getNote = (noteId: string, userId: string) =>
  fetchJSON<Note>(`/api/notes/${noteId}?user_id=${encodeURIComponent(userId)}`);

export const patchNote = (
  noteId: string,
  userId: string,
  patch: Partial<Pick<Note, 'title' | 'body' | 'tags' | 'course_id'>>,
) =>
  fetchJSON<Note>(`/api/notes/${noteId}`, {
    method: 'PATCH',
    body: JSON.stringify({ user_id: userId, ...patch }),
  });

export const deleteNote = (noteId: string, userId: string) =>
  fetchJSON<{ deleted: boolean }>(
    `/api/notes/${noteId}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

export const listNoteConcepts = (noteId: string, userId: string) =>
  fetchJSON<{ concepts: LinkedConcept[] }>(
    `/api/notes/${noteId}/concepts?user_id=${encodeURIComponent(userId)}`,
  );

export const linkNoteConcept = (noteId: string, userId: string, conceptNodeId: string) =>
  fetchJSON<{ linked: boolean }>(`/api/notes/${noteId}/concepts`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, concept_node_id: conceptNodeId }),
  });

export const unlinkNoteConcept = (noteId: string, userId: string, conceptNodeId: string) =>
  fetchJSON<{ unlinked: boolean }>(
    `/api/notes/${noteId}/concepts/${encodeURIComponent(conceptNodeId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

export const summarizeNote = (noteId: string, userId: string) =>
  fetchJSON<{ summary: string }>(`/api/notes/${noteId}/summarize`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

export const extractNoteConcepts = (noteId: string, userId: string) =>
  fetchJSON<{ concepts: string[]; linked: number }>(
    `/api/notes/${noteId}/extract-concepts`,
    { method: 'POST', body: JSON.stringify({ user_id: userId }) },
  );

export const noteChat = (noteId: string, userId: string, message: string) =>
  fetchJSON<{ reply: string }>(`/api/notes/${noteId}/chat`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, message }),
  });

export const sendNoteToTutor = (noteId: string, userId: string) =>
  fetchJSON<{ topic: string; course_id: string; preface: string }>(
    `/api/notes/${noteId}/send-to-tutor`,
    { method: 'POST', body: JSON.stringify({ user_id: userId }) },
  );

export const generateQuizFromNote = (noteId: string, userId: string) =>
  fetchJSON<{ concept_node_id: string; concept_name: string }>(
    `/api/notes/${noteId}/generate-quiz`,
    { method: 'POST', body: JSON.stringify({ user_id: userId }) },
  );
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts
git commit -m "feat(notes): frontend types + API helpers"
```

---

## Phase 7 — Wire the notetaker page

The page is currently a single file (`frontend/src/app/(shell)/notetaker/page.tsx`, ~1093 lines) that holds all sub-components. We keep the structure in place and replace the mock data + handlers; sub-components don't need to move.

### Task 15: Replace mock state with API-driven state + real course picker

**Files:**
- Modify: `frontend/src/app/(shell)/notetaker/page.tsx`

- [ ] **Step 1: Add imports + hooks at the top of `NotetakerPage`**

Inside `frontend/src/app/(shell)/notetaker/page.tsx`, replace the file's hard-coded `COURSES` / `SEED_NOTES` constants with API-driven loading.

Add to the import block at the top of the file:

```typescript
import { useAuth } from "@/context/AuthContext";
import {
  createNote as apiCreateNote,
  deleteNote as apiDeleteNote,
  extractNoteConcepts,
  generateQuizFromNote,
  getCourses,
  type EnrolledCourse,
  linkNoteConcept,
  listNoteConcepts,
  listNotes,
  noteChat,
  patchNote,
  sendNoteToTutor,
  summarizeNote,
  unlinkNoteConcept,
} from "@/lib/api";
import type { LinkedConcept, Note as ApiNote } from "@/lib/types";
```

(If `useAuth` lives at a different path in this repo, grep `@/context/AuthContext` for the actual location and adjust.)

Replace the `Note` / `Course` / `Concept` local types and the `COURSES`/`SEED_NOTES` constants with adapters that map the API shapes into the existing prop shapes used by sub-components. Keep `Course`, `Note`, `Concept` symbol names exactly so the sub-components don't need to change. Replace types as:

```typescript
type Mastery = "mastered" | "learning" | "struggling" | "unexplored";

type Course = {
  id: string;        // course_id
  name: string;      // course_name
  code: string;      // course_code
  color: string;
};

type Concept = {
  id: string;        // graph_nodes.id
  name: string;      // concept_name
  course: string;    // course_code (display label)
  mastery: Mastery;
};

type Note = {
  id: string;
  title: string;
  body: string;
  courseId: string;
  updatedAt: Date;
  tags: string[];
  linkedConcepts: Concept[];
  lastSummary: string | null;
};
```

Replace the body of `NotetakerPage` with API-driven state. Replace the `const [notes, setNotes] = React.useState<Note[]>(SEED_NOTES);` block down through `const active = ...` with:

```typescript
const { user } = useAuth();
const userId = user?.id ?? "";

const [courses, setCourses] = React.useState<Course[]>([]);
const [notes, setNotes] = React.useState<Note[]>([]);
const [activeId, setActiveId] = React.useState<string | null>(null);
const [query, setQuery] = React.useState("");
const [courseFilter, setCourseFilter] = React.useState<string | null>(null);
const [fullscreen, setFullscreen] = React.useState(false);
const [pickerOpen, setPickerOpen] = React.useState(false);
const [loading, setLoading] = React.useState(true);

React.useEffect(() => {
  if (!userId) return;
  let cancelled = false;
  (async () => {
    try {
      const [coursesRes, notesRes] = await Promise.all([
        getCourses(userId),
        listNotes(userId),
      ]);
      if (cancelled) return;
      setCourses(
        coursesRes.courses.map((c: EnrolledCourse) => ({
          id: c.course_id,
          name: c.course_name,
          code: c.course_code,
          color: c.color ?? "#9a9a9a",
        })),
      );
      const adapted = await Promise.all(
        notesRes.notes.map((n) => adaptNote(n, userId)),
      );
      setNotes(adapted);
      setActiveId(adapted[0]?.id ?? null);
    } finally {
      if (!cancelled) setLoading(false);
    }
  })();
  return () => {
    cancelled = true;
  };
}, [userId]);

const active = notes.find((n) => n.id === activeId) ?? notes[0] ?? null;

const courseFor = React.useCallback(
  (id: string): Course =>
    courses.find((c) => c.id === id) ?? {
      id, name: "Course", code: "—", color: "#9a9a9a",
    },
  [courses],
);
```

Then change every prior reference to the top-level `courseFor` helper inside this file to use the local `courseFor` from this scope (the sub-components that take a `course` prop already get it passed in — `<NoteDetail course={courseFor(active.courseId)} />` — so they don't need to change).

Add the adapter helper above `NotetakerPage`:

```typescript
async function adaptNote(api: ApiNote, userId: string): Promise<Note> {
  const conceptsRes = await listNoteConcepts(api.id, userId).catch(
    () => ({ concepts: [] as LinkedConcept[] }),
  );
  return {
    id: api.id,
    title: api.title,
    body: api.body,
    courseId: api.course_id,
    updatedAt: new Date(api.updated_at),
    tags: api.tags,
    lastSummary: api.last_summary,
    linkedConcepts: conceptsRes.concepts.map((c) => ({
      id: c.id,
      name: c.concept_name,
      course: "",
      mastery: (c.mastery_tier === "subject_root"
        ? "unexplored"
        : c.mastery_tier) as Mastery,
    })),
  };
}
```

Replace the early-return guard at the top of the JSX return (before `<div style={...}>`):

```typescript
if (!userId) return null;
if (loading) {
  return <div style={{ padding: 24, fontSize: 13, color: "var(--text-muted)" }}>Loading…</div>;
}
if (!active) {
  return (
    <EmptyNotetaker
      courses={courses}
      onCreate={() => setPickerOpen(true)}
      pickerOpen={pickerOpen}
      onPickerClose={() => setPickerOpen(false)}
      onPick={async (courseId) => {
        const fresh = await apiCreateNote(userId, courseId, "Untitled note");
        const adapted = await adaptNote(fresh, userId);
        setNotes([adapted]);
        setActiveId(adapted.id);
        setPickerOpen(false);
      }}
    />
  );
}
```

Add the `EmptyNotetaker` component above `NotetakerPage`:

```typescript
function EmptyNotetaker({
  courses,
  onCreate,
  pickerOpen,
  onPickerClose,
  onPick,
}: {
  courses: Course[];
  onCreate: () => void;
  pickerOpen: boolean;
  onPickerClose: () => void;
  onPick: (courseId: string) => void;
}) {
  return (
    <div
      style={{
        display: "flex", alignItems: "center", justifyContent: "center",
        height: "100vh", flexDirection: "column", gap: 14,
      }}
    >
      <div className="label-micro">No notes yet</div>
      <button
        type="button"
        className="btn btn--primary"
        onClick={onCreate}
      >
        Create your first note
      </button>
      {pickerOpen && (
        <CoursePickerModal
          courses={courses}
          onPick={onPick}
          onClose={onPickerClose}
        />
      )}
    </div>
  );
}
```

Update the `CoursePickerModal` signature inline in the file to accept `courses: Course[]` instead of using the hard-coded `COURSES`. Update its body's `{COURSES.map((c) => (` to `{courses.map((c) => (`.

Update `createNoteIn`:

```typescript
const createNoteIn = async (courseId: string) => {
  const fresh = await apiCreateNote(userId, courseId, "Untitled note");
  const adapted = await adaptNote(fresh, userId);
  setNotes((prev) => [adapted, ...prev]);
  setActiveId(adapted.id);
  setPickerOpen(false);
};
```

Update the JSX that renders `<CoursePickerModal ... />` to pass `courses={courses}`.

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: Smoke test**

Start the dev server and the backend, sign in, open `/notetaker`, confirm the empty state shows, click "Create your first note", pick a course, confirm a fresh "Untitled note" is created and selected.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/\(shell\)/notetaker/page.tsx
git commit -m "feat(notetaker): wire API-driven state and real course picker"
```

---

### Task 16: Autosave for title/body + tag CRUD

**Files:**
- Modify: `frontend/src/app/(shell)/notetaker/page.tsx`

- [ ] **Step 1: Replace the `updateActive` handler with a debounced autosave version**

Replace the `updateActive` callback inside `NotetakerPage` with:

```typescript
const updateActive = React.useCallback(
  (patch: Partial<Pick<Note, "title" | "body" | "tags">>) => {
    if (!active) return;
    setNotes((prev) =>
      prev.map((n) =>
        n.id === active.id ? { ...n, ...patch, updatedAt: new Date() } : n,
      ),
    );
  },
  [active],
);

// Debounced autosave: any change to title/body/tags triggers a PATCH
// 800ms after the user stops typing. Cancels prior pending saves.
const saveTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
const lastSavedSignature = React.useRef<string>("");

React.useEffect(() => {
  if (!active || !userId) return;
  const signature = JSON.stringify({
    id: active.id,
    title: active.title,
    body: active.body,
    tags: active.tags,
  });
  if (signature === lastSavedSignature.current) return;
  if (saveTimer.current) clearTimeout(saveTimer.current);
  saveTimer.current = setTimeout(() => {
    patchNote(active.id, userId, {
      title: active.title,
      body: active.body,
      tags: active.tags,
    })
      .then(() => {
        lastSavedSignature.current = signature;
      })
      .catch(() => {
        // Save failed — leave the signature unchanged so the next edit
        // (or a retry from the effect) reattempts. No UI error today;
        // a future task can surface a toast via ToastProvider.
      });
  }, 800);
  return () => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
  };
}, [active?.id, active?.title, active?.body, active?.tags, userId]);
```

- [ ] **Step 2: Wire tag add/remove in `NoteDetail`**

Update the `NoteDetail` component's signature to accept an `onChange` and `onDelete` callback so it can mutate the active note. Change its props:

```typescript
function NoteDetail({
  note,
  course,
  onChange,
  onDelete,
  onLink,
  onUnlink,
}: {
  note: Note;
  course: Course;
  onChange: (patch: Partial<Pick<Note, "tags">>) => void;
  onDelete: () => void;
  onLink: () => void;
  onUnlink: (conceptId: string) => void;
}) { ... }
```

Replace the static `<button>+ Add</button>` chip with a tag-input flow. Add inside `NoteDetail` body:

```typescript
const [tagDraft, setTagDraft] = React.useState("");
const addTag = () => {
  const t = tagDraft.trim();
  if (!t) return;
  if (note.tags.includes(t)) {
    setTagDraft("");
    return;
  }
  onChange({ tags: [...note.tags, t] });
  setTagDraft("");
};
const removeTag = (t: string) => {
  onChange({ tags: note.tags.filter((x) => x !== t) });
};
```

Replace the existing "+ Add" chip with:

```typescript
{note.tags.map((t) => (
  <button
    key={t}
    type="button"
    className="chip"
    onClick={() => removeTag(t)}
    style={{ cursor: "pointer" }}
    title="Remove tag"
  >
    {t} ×
  </button>
))}
<input
  value={tagDraft}
  onChange={(e) => setTagDraft(e.target.value)}
  onKeyDown={(e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addTag();
    }
  }}
  placeholder="+ add tag"
  className="chip"
  style={{
    background: "transparent",
    border: "1px dashed var(--border-strong)",
    outline: "none",
    minWidth: 80,
    fontFamily: "var(--font-sans)",
  }}
/>
```

Replace the Delete button's handler:

```typescript
<button
  type="button"
  className="btn btn--danger btn--sm"
  onClick={onDelete}
  style={{ marginTop: 12, width: "100%", justifyContent: "center", display: "inline-flex" }}
>
  <Icon name="x" size={11} /> Delete note
</button>
```

Wire `onDelete` / `onLink` / `onUnlink` / `onChange` at the call site in `NotetakerPage`:

```typescript
<NoteDetail
  note={active}
  course={courseFor(active.courseId)}
  onChange={(patch) => updateActive(patch)}
  onDelete={async () => {
    if (!userId) return;
    await apiDeleteNote(active.id, userId);
    setNotes((prev) => prev.filter((n) => n.id !== active.id));
    setActiveId((id) => {
      const remaining = notes.filter((n) => n.id !== id);
      return remaining[0]?.id ?? null;
    });
  }}
  onLink={() => { /* placeholder; wired in Task 17 */ }}
  onUnlink={async (conceptId: string) => {
    if (!userId) return;
    await unlinkNoteConcept(active.id, userId, conceptId);
    const fresh = await listNoteConcepts(active.id, userId);
    setNotes((prev) =>
      prev.map((n) =>
        n.id === active.id
          ? {
              ...n,
              linkedConcepts: fresh.concepts.map((c) => ({
                id: c.id, name: c.concept_name, course: "",
                mastery: (c.mastery_tier === "subject_root" ? "unexplored" : c.mastery_tier) as Mastery,
              })),
            }
          : n,
      ),
    );
  }}
/>
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: Smoke**

Edit a note's title and body, wait 800ms, refresh the page, confirm changes persist. Add a tag, refresh, confirm it persists. Click a tag chip to remove, refresh, confirm gone. Delete a note, confirm it disappears and the next note becomes active.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/\(shell\)/notetaker/page.tsx
git commit -m "feat(notetaker): debounced autosave + tag/delete wiring"
```

---

### Task 17: Concept link/unlink picker + Sapling action buttons

**Files:**
- Modify: `frontend/src/app/(shell)/notetaker/page.tsx`

- [ ] **Step 1: Add a concept picker modal**

Add a new `ConceptPickerModal` component below `CoursePickerModal`:

```typescript
function ConceptPickerModal({
  userId,
  courseId,
  alreadyLinkedIds,
  onPick,
  onClose,
}: {
  userId: string;
  courseId: string;
  alreadyLinkedIds: Set<string>;
  onPick: (conceptNodeId: string) => void;
  onClose: () => void;
}) {
  const [nodes, setNodes] = React.useState<{ id: string; concept_name: string; mastery_tier: string }[]>([]);
  const [q, setQ] = React.useState("");

  React.useEffect(() => {
    let cancelled = false;
    import("@/lib/api").then(({ getGraph }) => getGraph(userId)).then((res) => {
      if (cancelled) return;
      const filtered = (res.nodes as { id: string; concept_name: string; mastery_tier: string; course_id?: string | null }[])
        .filter((n) => !n.course_id || n.course_id === courseId)
        .filter((n) => !alreadyLinkedIds.has(n.id));
      setNodes(filtered);
    });
    return () => { cancelled = true; };
  }, [userId, courseId, alreadyLinkedIds]);

  const filtered = nodes.filter((n) =>
    q ? n.concept_name.toLowerCase().includes(q.toLowerCase()) : true,
  );

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 200,
        background: "rgba(19, 17, 13, 0.45)", backdropFilter: "blur(2px)",
        display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card"
        style={{ width: "100%", maxWidth: 520, padding: 0, boxShadow: "var(--shadow-lg)", overflow: "hidden" }}
      >
        <div style={{ padding: "20px 24px 12px", borderBottom: "1px solid var(--border)" }}>
          <div className="label-micro" style={{ marginBottom: 6 }}>Link concept</div>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search concepts…"
            style={{
              width: "100%", padding: "8px 10px", fontSize: 13,
              background: "var(--bg-input)", border: "1px solid var(--border)",
              borderRadius: "var(--r-sm)", color: "var(--text)", outline: "none",
            }}
          />
        </div>
        <div style={{ padding: 10, maxHeight: 380, overflowY: "auto" }}>
          {filtered.length === 0 ? (
            <div style={{ padding: 16, fontSize: 12, color: "var(--text-muted)", textAlign: "center" }}>
              No matching concepts in this course.
            </div>
          ) : filtered.map((n) => (
            <button
              key={n.id}
              type="button"
              onClick={() => onPick(n.id)}
              style={{
                display: "block", width: "100%", textAlign: "left",
                padding: "10px 12px", borderRadius: "var(--r-sm)",
                background: "transparent", border: "none",
                cursor: "pointer", fontSize: 13, color: "var(--text)",
              }}
            >
              {n.concept_name}
              <span className="mono" style={{ marginLeft: 8, fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}>
                {n.mastery_tier}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add concept picker state + wire `onLink`**

Inside `NotetakerPage`, add:

```typescript
const [conceptPickerOpen, setConceptPickerOpen] = React.useState(false);

const refreshConcepts = React.useCallback(async () => {
  if (!active || !userId) return;
  const fresh = await listNoteConcepts(active.id, userId);
  setNotes((prev) =>
    prev.map((n) =>
      n.id === active.id
        ? {
            ...n,
            linkedConcepts: fresh.concepts.map((c) => ({
              id: c.id, name: c.concept_name, course: "",
              mastery: (c.mastery_tier === "subject_root" ? "unexplored" : c.mastery_tier) as Mastery,
            })),
          }
        : n,
    ),
  );
}, [active?.id, userId]);
```

Change the `onLink` on `<NoteDetail>` to open the picker:

```typescript
onLink={() => setConceptPickerOpen(true)}
```

Render the modal after the existing `{pickerOpen && ...}` block:

```typescript
{conceptPickerOpen && active && userId && (
  <ConceptPickerModal
    userId={userId}
    courseId={active.courseId}
    alreadyLinkedIds={new Set(active.linkedConcepts.map((c) => c.id))}
    onPick={async (cid) => {
      await linkNoteConcept(active.id, userId, cid);
      await refreshConcepts();
      setConceptPickerOpen(false);
    }}
    onClose={() => setConceptPickerOpen(false)}
  />
)}
```

- [ ] **Step 3: Wire the four Sapling action buttons inside `NoteDetail`**

Update `NoteDetail` props to accept four handler callbacks and a busy state. Replace the four ghost buttons in the "Sapling actions" card with:

```typescript
<button
  type="button"
  className="btn btn--ghost"
  disabled={!!busy}
  onClick={onSummarize}
  style={{ justifyContent: "flex-start", textAlign: "left" }}
>
  <Icon name="sparkle" size={13} /> {busy === "summarize" ? "Summarizing…" : "Summarize note"}
</button>
<button
  type="button"
  className="btn btn--ghost"
  disabled={!!busy}
  onClick={onExtractConcepts}
  style={{ justifyContent: "flex-start", textAlign: "left" }}
>
  <Icon name="brain" size={13} /> {busy === "extract" ? "Extracting…" : "Extract concepts"}
</button>
<button
  type="button"
  className="btn btn--ghost"
  disabled={!!busy}
  onClick={onGenerateQuiz}
  style={{ justifyContent: "flex-start", textAlign: "left" }}
>
  <Icon name="flask" size={13} /> {busy === "quiz" ? "Generating…" : "Generate quiz"}
</button>
<button
  type="button"
  className="btn btn--ghost"
  disabled={!!busy}
  onClick={onSendToTutor}
  style={{ justifyContent: "flex-start", textAlign: "left" }}
>
  <Icon name="bolt" size={13} /> {busy === "tutor" ? "Opening tutor…" : "Send to tutor"}
</button>
```

And add the last summary display (above the action buttons) if `note.lastSummary` is set (the type already includes it from Task 15). Add to the Sapling-actions card, above the buttons:

```typescript
{note.lastSummary && (
  <div style={{ marginBottom: 10, padding: 10, background: "var(--bg-subtle)", borderRadius: "var(--r-sm)", fontSize: 12, lineHeight: 1.5 }}>
    {note.lastSummary}
  </div>
)}
```

- [ ] **Step 4: Wire the handlers in `NotetakerPage`**

Above the JSX return, add:

```typescript
const [busy, setBusy] = React.useState<null | "summarize" | "extract" | "quiz" | "tutor">(null);
const router = useRouter(); // from next/navigation

const onSummarize = async () => {
  if (!active || !userId) return;
  setBusy("summarize");
  try {
    const { summary } = await summarizeNote(active.id, userId);
    setNotes((prev) =>
      prev.map((n) => (n.id === active.id ? { ...n, lastSummary: summary } : n)),
    );
  } finally {
    setBusy(null);
  }
};

const onExtractConcepts = async () => {
  if (!active || !userId) return;
  setBusy("extract");
  try {
    await extractNoteConcepts(active.id, userId);
    await refreshConcepts();
  } finally {
    setBusy(null);
  }
};

const onGenerateQuiz = async () => {
  if (!active || !userId) return;
  setBusy("quiz");
  try {
    const { concept_node_id } = await generateQuizFromNote(active.id, userId);
    router.push(`/quiz?concept=${encodeURIComponent(concept_node_id)}`);
  } catch (e) {
    // Surface as console error for now; toast wiring is a future task.
    console.error("Quiz generation failed", e);
  } finally {
    setBusy(null);
  }
};

const onSendToTutor = async () => {
  if (!active || !userId) return;
  setBusy("tutor");
  try {
    const { topic, course_id } = await sendNoteToTutor(active.id, userId);
    router.push(
      `/learn?topic=${encodeURIComponent(topic)}&course=${encodeURIComponent(course_id)}`,
    );
  } finally {
    setBusy(null);
  }
};
```

Pass them through `<NoteDetail ... onSummarize={onSummarize} onExtractConcepts={onExtractConcepts} onGenerateQuiz={onGenerateQuiz} onSendToTutor={onSendToTutor} busy={busy} />`.

Add `import { useRouter } from "next/navigation";` at the top of the file.

> NOTE: The deep-link query params (`/quiz?concept=...`, `/learn?topic=...&course=...`) must match what those pages read. If those pages currently only accept their own state, leave the `router.push` calls in place but expect a follow-up task to wire the query-param parsing on those pages. Smoke-test by checking the URL changes and the destination page renders, even if the auto-start behavior needs a future task.

- [ ] **Step 5: Type-check + smoke**

```bash
cd frontend && npx tsc --noEmit
```

Then in the browser:
- Click "Summarize note" → spinner → summary appears in the side card. Refresh → summary persists.
- Click "Extract concepts" → spinner → linked concepts panel updates with new entries from the graph.
- Click "Link concept" → modal opens with the course's existing graph nodes → pick one → it appears in linked concepts.
- Click an existing linked-concept chip with × → removed from the list.
- Click "Generate quiz" → URL changes to `/quiz?concept=...`.
- Click "Send to tutor" → URL changes to `/learn?topic=...&course=...`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/\(shell\)/notetaker/page.tsx
git commit -m "feat(notetaker): wire concept link/unlink + four Sapling actions"
```

---

### Task 18: Wire the AI Chat panel

**Files:**
- Modify: `frontend/src/app/(shell)/notetaker/page.tsx`

- [ ] **Step 1: Replace the simulated `setTimeout` reply in `AIChatPanel` with a real call**

Update `AIChatPanel`'s signature to receive `noteId` + `userId`:

```typescript
function AIChatPanel({ noteId, userId }: { noteId: string | null; userId: string }) {
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [input, setInput] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  // Reset the panel when the active note changes — the chat is per-note.
  React.useEffect(() => {
    setMessages([]);
  }, [noteId]);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text || !noteId || pending) return;
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setPending(true);
    try {
      const { reply } = await noteChat(noteId, userId, text);
      setMessages((prev) => [...prev, { role: "ai", text: reply }]);
    } catch (e) {
      setMessages((prev) => [...prev, { role: "ai", text: "Sapling hit an error answering that. Try again?" }]);
    } finally {
      setPending(false);
    }
  };

  // …rest of component unchanged, except disable the send button while pending:
  // <button … disabled={!input.trim() || pending}>
  // and show a "Thinking…" placeholder bubble while pending if you'd like.
}
```

Update the call site:

```typescript
<AIChatPanel noteId={active?.id ?? null} userId={userId} />
```

- [ ] **Step 2: Type-check + smoke**

```bash
cd frontend && npx tsc --noEmit
```

In the browser, toggle the editor to fullscreen, type a question in the chat panel, confirm a real reply comes back referencing the note's content (the agent should ground via `read_active_note`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/\(shell\)/notetaker/page.tsx
git commit -m "feat(notetaker): wire AI Chat panel to /api/notes/{id}/chat"
```

---

## Phase 8 — End-to-end verification

### Task 19: Full backend test sweep

- [ ] **Step 1: Run the full notes test set**

```bash
cd backend && python -m pytest tests/test_notes_service.py tests/test_notes_routes.py tests/test_note_agents_imports.py tests/test_note_context_tool.py -v
```

Expected: all green; numeric count ~25 tests.

- [ ] **Step 2: Run the whole suite to confirm no regressions**

```bash
cd backend && python -m pytest -q
```

Expected: only the three pre-existing live-Supabase failures (`test_skips_self_edges`, `test_save_to_db`, `test_full_pipeline`) from ADR 0015 / 0016. No new failures.

### Task 20: End-to-end manual smoke

- [ ] **Step 1: Backend up**

```bash
cd backend && python main.py
```

- [ ] **Step 2: Frontend up**

```bash
cd frontend && npm run dev
```

- [ ] **Step 3: Run the smoke script**

In the browser, signed in:

1. `/notetaker` loads. If empty state shows, click "Create your first note", pick a course, confirm a fresh note appears.
2. Edit the title + body. Wait 1 second. Refresh page. Confirm changes persisted.
3. Add two tags; refresh; confirm they persist.
4. Click "Summarize note". Confirm spinner → summary card appears. Refresh; summary persists.
5. Click "Extract concepts". Confirm linked-concepts panel updates with new chips.
6. Click "Link concept" in the linked-concepts card. Confirm modal lists graph nodes for the active course. Pick one; confirm it appears in the chips.
7. Click a concept chip's × button. Confirm it disappears.
8. Search box: type the body text of one note; confirm filter narrows the list.
9. Click a course chip in the left rail; confirm only matching notes show.
10. Toggle fullscreen; type a question into the AI chat panel; confirm a real reply.
11. Click "Generate quiz". URL changes to `/quiz?concept=...`.
12. Back to `/notetaker`. Click "Send to tutor". URL changes to `/learn?topic=...&course=...`.
13. Delete a note. Confirm it disappears and the next becomes active.

### Task 21: Log the ADR

- [ ] **Step 1: Create the ADR**

Run `/log-decision` with title "Notetaker dynamic frontend + backend". Capture the non-obvious contracts:

- `note_id` rides on `SaplingDeps.session_id` for the note-chat agent (avoids inflating the deps type).
- `note_concepts.concept_node_id` is not a hard FK (intentional — graph_nodes uses application-managed TEXT ids; this matches `graph_edges`).
- `/generate-quiz` is a thin selector route — the frontend still calls `/api/quiz/generate` separately. We chose not to chain server-side so the existing quiz client stays the source of truth for quiz state.
- The AI chat panel uses JSON request/response, not SSE — matches `routes/learn.py::chat`. Streaming is a future iteration.
- Saving the summary on the note row (`notes.last_summary`) rather than a separate table — single-summary-per-note is enough today; revisit if we ever want history.

- [ ] **Step 2: Commit the ADR**

```bash
git add docs/decisions/0017-notetaker-dynamic.md
git commit -m "docs: ADR 0017 notetaker dynamic implementation"
```

---

## Notes on what this plan deliberately doesn't do

- **No SSE streaming** for the AI chat panel — the existing tutor `/chat` route returns a JSON blob, so the notetaker chat does too. Adding SSE is a future iteration.
- **No tag autocomplete / shared-tag suggestions** — tags are per-note strings, free-form, no cross-note index.
- **No RLS policies on `notes` / `note_concepts`** — the rest of the schema runs RLS-disabled with ownership enforced in route code via `require_self`. Adding RLS is a project-wide concern (see the advisory in the Supabase MCP output during planning).
- **No eval cases for the three note agents** yet. Refactors #1–#4 shipped evals; this is a brand-new feature surface so the first iteration leans on unit tests + manual smoke. Add `tests/evals/note_summary.py` / `note_concepts.py` / `note_chat.py` in a follow-up.
- **No live retry of failed autosaves** — failures stay silent; a toast surface is a future polish task.
- **No deep-link parsing on `/quiz` and `/learn`** — those pages may not yet read the `concept=` / `topic=` query params we push. If smoke-test step 11 / 12 doesn't auto-start the quiz / session, file a follow-up task to wire those page-level param readers; the notetaker side is done.
