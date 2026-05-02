# Gradebook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a user-driven gradebook under the Tools nav: track grades per course per semester, define categories with weights (manual or syllabus-extracted), enter graded assignments, and see a computed current grade + letter.

**Architecture:** One additive DB migration extending `assignments` and `user_courses`, plus a new `course_categories` table. New `gradebook_service.py` for the grade-calc math. New `routes/gradebook.py` exposing 10 endpoints. The existing syllabus extraction prompt gains a `categories` array. Frontend gets a landing page (`/gradebook`) with semester chips + course grid and a detail page (`/gradebook/[courseId]`) with category/assignment panels and modals.

**Tech Stack:** FastAPI, Supabase (REST via `db.connection.table()`), Gemini (existing `gemini_service`), pytest, Next.js + React, TypeScript.

**Spec:** `docs/superpowers/specs/2026-05-02-gradebook-design.md`

**Frontend testing note:** Per `CLAUDE.md`, this branch has no automated frontend test framework. Frontend tasks use `npx tsc --noEmit` + manual smoke as the verification gate, **not** Jest/Vitest. Backend tasks use real TDD with pytest.

---

## File Map

**Created:**
- `backend/db/migration_gradebook.sql`
- `backend/services/gradebook_service.py`
- `backend/routes/gradebook.py`
- `backend/tests/test_gradebook_service.py`
- `backend/tests/test_gradebook_routes.py`
- `frontend/src/app/(shell)/gradebook/[courseId]/page.tsx`
- `frontend/src/components/screens/Gradebook/Landing.tsx`
- `frontend/src/components/screens/Gradebook/Course.tsx`
- `frontend/src/components/Gradebook/CategoryPanel.tsx`
- `frontend/src/components/Gradebook/EditWeightsModal.tsx`
- `frontend/src/components/Gradebook/AssignmentList.tsx`
- `frontend/src/components/Gradebook/AssignmentModal.tsx`
- `frontend/src/components/Gradebook/SyllabusUploadFlow.tsx`
- `frontend/src/components/Gradebook/SemesterChips.tsx`
- `frontend/src/components/Gradebook/LetterScaleEditor.tsx`

**Modified:**
- `backend/db/supabase_schema.sql` — append the new gradebook tables
- `backend/main.py` — register `gradebook` router
- `backend/models/__init__.py` — Pydantic bodies
- `backend/prompts/syllabus_extraction.txt` — output `categories` array
- `backend/routes/documents.py` — surface `categories` from `_process_document`
- `frontend/src/lib/api.ts` — typed wrappers for new endpoints
- `frontend/src/lib/types.ts` — `GradebookSummary`, `GradebookCourse`, etc.
- `frontend/src/app/(shell)/gradebook/page.tsx` — render `<GradebookLanding />`

---

## Phase 0 — Database

### Task 1: Write the gradebook migration

**Files:**
- Create: `backend/db/migration_gradebook.sql`
- Modify: `backend/db/supabase_schema.sql` (append)

- [ ] **Step 1: Write the migration file**

Create `backend/db/migration_gradebook.sql`:

```sql
-- Gradebook: extend assignments + user_courses, add course_categories.
-- Idempotent — safe to re-run.

-- 1. Extend assignments with grade fields and a source tag.
ALTER TABLE assignments
  ADD COLUMN IF NOT EXISTS category_id      TEXT,
  ADD COLUMN IF NOT EXISTS points_possible  NUMERIC,
  ADD COLUMN IF NOT EXISTS points_earned    NUMERIC,
  ADD COLUMN IF NOT EXISTS source           TEXT DEFAULT 'manual';

-- Allow null due_date so manually created graded items don't have to invent one.
ALTER TABLE assignments
  ALTER COLUMN due_date DROP NOT NULL;

-- 2. Per-(user, course) grading categories with weights.
CREATE TABLE IF NOT EXISTS course_categories (
  id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
  user_id     TEXT NOT NULL REFERENCES users(id),
  course_id   TEXT NOT NULL REFERENCES courses(id),
  name        TEXT NOT NULL,
  weight      NUMERIC NOT NULL,
  sort_order  INTEGER DEFAULT 0,
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_course_categories_user_course
  ON course_categories(user_id, course_id);

-- 3. Wire assignments.category_id to the new table.
-- PostgreSQL does not support ADD CONSTRAINT IF NOT EXISTS, so guard manually.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'assignments_category_id_fkey'
  ) THEN
    ALTER TABLE assignments
      ADD CONSTRAINT assignments_category_id_fkey
      FOREIGN KEY (category_id) REFERENCES course_categories(id)
      ON DELETE SET NULL;
  END IF;
END $$;

-- 4. Per-(user, course) grade-display preferences.
ALTER TABLE user_courses
  ADD COLUMN IF NOT EXISTS letter_scale     JSONB,
  ADD COLUMN IF NOT EXISTS syllabus_doc_id  TEXT REFERENCES documents(id);
```

- [ ] **Step 2: Append the new tables/columns to the canonical schema**

Open `backend/db/supabase_schema.sql`. Find the `assignments` `CREATE TABLE` (search for `CREATE TABLE IF NOT EXISTS assignments`). Replace it with:

```sql
-- Assignments (from syllabus extraction or manual entry; gradebook-aware)
CREATE TABLE IF NOT EXISTS assignments (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    title           TEXT NOT NULL,
    course_id       TEXT REFERENCES courses(id),
    due_date        TEXT,
    assignment_type TEXT,
    notes           TEXT,
    google_event_id TEXT,
    category_id     TEXT REFERENCES course_categories(id) ON DELETE SET NULL,
    points_possible NUMERIC,
    points_earned   NUMERIC,
    source          TEXT DEFAULT 'manual',
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_assignments_user_due ON assignments(user_id, due_date);
```

Find the `user_courses` `CREATE TABLE` and replace it with the same definition plus the two new columns:

```sql
-- Enrollment join table (user ↔ canonical course)
CREATE TABLE IF NOT EXISTS user_courses (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    course_id       TEXT NOT NULL REFERENCES courses(id),
    nickname        TEXT,
    color           TEXT,
    enrolled_at     TIMESTAMPTZ DEFAULT now(),
    letter_scale    JSONB,
    syllabus_doc_id TEXT REFERENCES documents(id),
    UNIQUE (user_id, course_id)
);

CREATE INDEX IF NOT EXISTS idx_user_courses_user_id ON user_courses(user_id);
```

Then append the new `course_categories` block right after the `assignments` block:

```sql
-- Per-(user, course) grading categories with weights
CREATE TABLE IF NOT EXISTS course_categories (
    id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    user_id     TEXT NOT NULL REFERENCES users(id),
    course_id   TEXT NOT NULL REFERENCES courses(id),
    name        TEXT NOT NULL,
    weight      NUMERIC NOT NULL,
    sort_order  INTEGER DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_course_categories_user_course
  ON course_categories(user_id, course_id);
```

> **Note on existing `user_courses` definition:** match whatever columns are already declared (`nickname`, `color`, etc. may differ). Use `git diff` to confirm only `letter_scale` and `syllabus_doc_id` are new.

- [ ] **Step 3: Apply migration locally**

Run via Supabase SQL editor (or `psql` with the project DB URL):

```bash
psql "$SUPABASE_DB_URL" -f backend/db/migration_gradebook.sql
```

Expected: every statement succeeds; re-running is a no-op due to `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` / `ADD CONSTRAINT IF NOT EXISTS`.

- [ ] **Step 4: Commit**

```bash
git add backend/db/migration_gradebook.sql backend/db/supabase_schema.sql
git commit -m "feat(db): gradebook schema (categories, weights, grades)"
```

---

## Phase 1 — Backend service skeleton

### Task 2: Create the gradebook service module

**Files:**
- Create: `backend/services/gradebook_service.py`

- [ ] **Step 1: Write the module skeleton**

Create `backend/services/gradebook_service.py`:

```python
"""
Pure functions for gradebook math.

No Supabase or HTTP coupling — routes pass in plain rows/dicts and get back
plain dicts. Keeps the calc logic trivially testable.
"""
from __future__ import annotations

from typing import Iterable, Optional, TypedDict


class CategoryRow(TypedDict):
    id: str
    name: str
    weight: float
    sort_order: int


class AssignmentRow(TypedDict, total=False):
    id: str
    title: str
    category_id: Optional[str]
    points_possible: Optional[float]
    points_earned: Optional[float]


# Default letter scale, descending. Keys are floor percentages.
DEFAULT_LETTER_SCALE: list[tuple[float, str]] = [
    (93.0, "A"),
    (90.0, "A-"),
    (87.0, "B+"),
    (83.0, "B"),
    (80.0, "B-"),
    (77.0, "C+"),
    (73.0, "C"),
    (70.0, "C-"),
    (67.0, "D+"),
    (63.0, "D"),
    (60.0, "D-"),
    (0.0,  "F"),
]
```

- [ ] **Step 2: Verify import**

```bash
cd backend && source venv/bin/activate && python -c "from services import gradebook_service; print(gradebook_service.DEFAULT_LETTER_SCALE[0])"
```

Expected: `(93.0, 'A')`.

- [ ] **Step 3: Commit**

```bash
git add backend/services/gradebook_service.py
git commit -m "feat(backend): gradebook_service skeleton"
```

---

## Phase 2 — Grade-calculation logic (TDD)

### Task 3: Implement category-grade calculation

**Files:**
- Modify: `backend/services/gradebook_service.py`
- Create: `backend/tests/test_gradebook_service.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_gradebook_service.py`:

```python
"""Unit tests for services.gradebook_service."""
import pytest

from services import gradebook_service as svc


# ── category_grade ───────────────────────────────────────────────────────────

class TestCategoryGrade:
    def test_returns_none_when_no_graded_items(self):
        assert svc.category_grade([]) is None

    def test_returns_none_when_only_ungraded_items(self):
        items = [
            {"points_possible": 100, "points_earned": None},
            {"points_possible": 50,  "points_earned": None},
        ]
        assert svc.category_grade(items) is None

    def test_averages_points_earned_over_points_possible(self):
        items = [
            {"points_possible": 100, "points_earned": 92},
            {"points_possible": 50,  "points_earned": 40},
        ]
        # (92 + 40) / (100 + 50) = 0.88
        assert svc.category_grade(items) == pytest.approx(0.88)

    def test_skips_items_missing_points_possible(self):
        items = [
            {"points_possible": None, "points_earned": 100},
            {"points_possible": 100,  "points_earned": 80},
        ]
        assert svc.category_grade(items) == pytest.approx(0.80)

    def test_allows_extra_credit(self):
        items = [{"points_possible": 100, "points_earned": 110}]
        assert svc.category_grade(items) == pytest.approx(1.10)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_service.py -v
```

Expected: 5 failures with `AttributeError: module 'services.gradebook_service' has no attribute 'category_grade'`.

- [ ] **Step 3: Implement `category_grade`**

Append to `backend/services/gradebook_service.py`:

```python
def category_grade(items: Iterable[AssignmentRow]) -> Optional[float]:
    """Return the 0–1 grade for one category, or None if no graded items.

    A graded item has both points_possible (> 0) and points_earned (not None).
    Sums earned / sums possible across graded items.
    """
    total_possible = 0.0
    total_earned = 0.0
    for item in items:
        possible = item.get("points_possible")
        earned = item.get("points_earned")
        if possible is None or earned is None:
            continue
        if possible <= 0:
            continue
        total_possible += float(possible)
        total_earned += float(earned)
    if total_possible == 0:
        return None
    return total_earned / total_possible
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_service.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/gradebook_service.py backend/tests/test_gradebook_service.py
git commit -m "feat(backend): gradebook category_grade calc"
```

### Task 4: Implement overall current-grade calculation

**Files:**
- Modify: `backend/services/gradebook_service.py`
- Modify: `backend/tests/test_gradebook_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_gradebook_service.py`:

```python
# ── current_grade ────────────────────────────────────────────────────────────

class TestCurrentGrade:
    def _cat(self, id_: str, weight: float) -> dict:
        return {"id": id_, "name": id_, "weight": weight, "sort_order": 0}

    def test_returns_none_when_no_graded_categories(self):
        cats = [self._cat("exams", 50), self._cat("psets", 50)]
        assignments = [
            {"category_id": "exams", "points_possible": 100, "points_earned": None},
        ]
        assert svc.current_grade(cats, assignments) is None

    def test_normalizes_when_some_categories_ungraded(self):
        cats = [self._cat("exams", 50), self._cat("psets", 50)]
        assignments = [
            {"category_id": "exams", "points_possible": 100, "points_earned": 90},
            # psets has no graded items — drops out, exams gets full weight.
        ]
        # category_grade(exams) = 0.9; only contributing weight; 0.9 * 100 = 90
        assert svc.current_grade(cats, assignments) == pytest.approx(90.0)

    def test_weighted_average_across_categories(self):
        cats = [self._cat("exams", 60), self._cat("psets", 40)]
        assignments = [
            {"category_id": "exams", "points_possible": 100, "points_earned": 80},
            {"category_id": "psets", "points_possible": 100, "points_earned": 100},
        ]
        # (0.8*60 + 1.0*40) / (60+40) = 88 → ×100
        assert svc.current_grade(cats, assignments) == pytest.approx(88.0)

    def test_ignores_assignments_without_a_category(self):
        cats = [self._cat("exams", 100)]
        assignments = [
            {"category_id": None,    "points_possible": 100, "points_earned": 50},
            {"category_id": "exams", "points_possible": 100, "points_earned": 90},
        ]
        assert svc.current_grade(cats, assignments) == pytest.approx(90.0)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_service.py::TestCurrentGrade -v
```

Expected: 4 failures with `AttributeError: module 'services.gradebook_service' has no attribute 'current_grade'`.

- [ ] **Step 3: Implement `current_grade`**

Append to `backend/services/gradebook_service.py`:

```python
def current_grade(
    categories: list[CategoryRow],
    assignments: Iterable[AssignmentRow],
) -> Optional[float]:
    """Return the 0–100 current grade across all categories, or None.

    For each category with at least one graded item, computes the
    category_grade and weights it by the category's weight. Categories
    with no graded items drop out — total weight is renormalized so the
    contributing weights sum to 100.
    """
    by_cat: dict[str, list[AssignmentRow]] = {c["id"]: [] for c in categories}
    for a in assignments:
        cid = a.get("category_id")
        if cid in by_cat:
            by_cat[cid].append(a)

    total_weight = 0.0
    weighted_sum = 0.0
    for cat in categories:
        grade = category_grade(by_cat[cat["id"]])
        if grade is None:
            continue
        total_weight += float(cat["weight"])
        weighted_sum += grade * float(cat["weight"])

    if total_weight == 0:
        return None
    return (weighted_sum / total_weight) * 100.0
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_service.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/gradebook_service.py backend/tests/test_gradebook_service.py
git commit -m "feat(backend): gradebook current_grade calc"
```

### Task 5: Implement letter-grade lookup

**Files:**
- Modify: `backend/services/gradebook_service.py`
- Modify: `backend/tests/test_gradebook_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_gradebook_service.py`:

```python
# ── letter_for ───────────────────────────────────────────────────────────────

class TestLetterFor:
    def test_uses_default_scale_when_none_provided(self):
        assert svc.letter_for(95.0, None) == "A"
        assert svc.letter_for(91.0, None) == "A-"
        assert svc.letter_for(72.5, None) == "C-"
        assert svc.letter_for(40.0, None) == "F"

    def test_returns_none_when_grade_is_none(self):
        assert svc.letter_for(None, None) is None

    def test_uses_custom_scale_when_provided(self):
        # A custom course where 90+ is an A and there is no minus tier.
        scale = [{"min": 90, "letter": "A"}, {"min": 80, "letter": "B"}, {"min": 0, "letter": "F"}]
        assert svc.letter_for(95.0, scale) == "A"
        assert svc.letter_for(85.0, scale) == "B"
        assert svc.letter_for(50.0, scale) == "F"

    def test_handles_boundary_exactly(self):
        assert svc.letter_for(93.0, None) == "A"
        assert svc.letter_for(92.999, None) == "A-"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_service.py::TestLetterFor -v
```

Expected: 4 failures with `AttributeError`.

- [ ] **Step 3: Implement `letter_for`**

Append to `backend/services/gradebook_service.py`:

```python
def letter_for(percent: Optional[float], scale: Optional[list[dict]]) -> Optional[str]:
    """Map a 0–100 percentage to a letter using the given scale (or default).

    Custom scale shape: [{"min": 90, "letter": "A"}, ...] sorted descending
    by min during evaluation. None percent → None letter.
    """
    if percent is None:
        return None
    if scale:
        ordered = sorted(scale, key=lambda x: -float(x.get("min", 0)))
        for tier in ordered:
            if percent >= float(tier["min"]):
                return str(tier["letter"])
        return None
    for floor, letter in DEFAULT_LETTER_SCALE:
        if percent >= floor:
            return letter
    return None
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_service.py -v
```

Expected: all 13 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/gradebook_service.py backend/tests/test_gradebook_service.py
git commit -m "feat(backend): gradebook letter_for lookup"
```

---

## Phase 3 — Pydantic models

### Task 6: Add gradebook request models

**Files:**
- Modify: `backend/models/__init__.py`

- [ ] **Step 1: Append the gradebook models**

Append to `backend/models/__init__.py`:

```python
# ── Gradebook ────────────────────────────────────────────────────────────────

class CategoryItem(BaseModel):
    id: Optional[str] = None              # null on create
    name: str
    weight: float = Field(ge=0, le=100)
    sort_order: int = 0


class CreateCategoryBody(BaseModel):
    user_id: str
    name: str
    weight: float = Field(ge=0, le=100)


class BulkUpdateCategoriesBody(BaseModel):
    user_id: str
    categories: list[CategoryItem]        # full replacement set


class CreateAssignmentBody(BaseModel):
    user_id: str
    course_id: str
    title: str
    category_id: Optional[str] = None
    points_possible: Optional[float] = Field(default=None, gt=0)
    points_earned: Optional[float] = Field(default=None, ge=0)
    due_date: Optional[str] = None
    assignment_type: Optional[str] = None
    notes: Optional[str] = None


class UpdateAssignmentBody(BaseModel):
    user_id: str
    title: Optional[str] = None
    category_id: Optional[str] = None
    points_possible: Optional[float] = Field(default=None, gt=0)
    points_earned: Optional[float] = Field(default=None, ge=0)
    due_date: Optional[str] = None
    assignment_type: Optional[str] = None
    notes: Optional[str] = None


class LetterScaleTier(BaseModel):
    min: float = Field(ge=0, le=100)
    letter: str


class SetLetterScaleBody(BaseModel):
    user_id: str
    scale: Optional[list[LetterScaleTier]] = None  # null clears the override


class SyllabusApplyBody(BaseModel):
    user_id: str
    course_id: str
    doc_id: str
    categories: list[CategoryItem]
    assignments: list[dict]               # uses the same shape as syllabus extraction
```

- [ ] **Step 2: Verify import**

```bash
cd backend && source venv/bin/activate && python -c "from models import CreateCategoryBody, BulkUpdateCategoriesBody, CreateAssignmentBody, UpdateAssignmentBody, SetLetterScaleBody, SyllabusApplyBody"
```

Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add backend/models/__init__.py
git commit -m "feat(backend): gradebook Pydantic models"
```

---

## Phase 4 — Gradebook routes (TDD)

The route module follows the same `table()` + `require_self` pattern as `routes/onboarding.py` and `routes/flashcards.py`. Each task adds one route group with tests.

### Task 7: Create the route module skeleton + register it

**Files:**
- Create: `backend/routes/gradebook.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write the route skeleton**

Create `backend/routes/gradebook.py`:

```python
"""
backend/routes/gradebook.py

User-driven gradebook: categories with weights, graded assignments,
per-course letter-scale override, syllabus-apply.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request

from db.connection import table
from models import (
    CreateCategoryBody,
    BulkUpdateCategoriesBody,
    CreateAssignmentBody,
    UpdateAssignmentBody,
    SetLetterScaleBody,
    SyllabusApplyBody,
)
from services import gradebook_service
from services.auth_guard import require_self

router = APIRouter()


def _user_owns_course(user_id: str, course_id: str) -> bool:
    rows = table("user_courses").select(
        "id",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        limit=1,
    )
    return bool(rows)


def _user_owns_category(user_id: str, category_id: str) -> dict | None:
    rows = table("course_categories").select(
        "*",
        filters={"id": f"eq.{category_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    )
    return rows[0] if rows else None
```

- [ ] **Step 2: Register the router in `main.py`**

Open `backend/main.py`. After the `app.include_router(newsletter_router, prefix="/api/newsletter")` line (line 56), add:

```python
from routes import gradebook
app.include_router(gradebook.router,   prefix="/api/gradebook")
```

(Keep the existing import style — most routers are imported at the top; mirror whichever pattern is already used. If imports are grouped at the top of the file, move the `from routes import gradebook` up there too.)

- [ ] **Step 3: Verify the app starts**

```bash
cd backend && source venv/bin/activate && python -c "from main import app; print([r.path for r in app.routes if '/gradebook' in r.path])"
```

Expected: `[]` (no routes defined yet, but no import error).

- [ ] **Step 4: Commit**

```bash
git add backend/routes/gradebook.py backend/main.py
git commit -m "feat(backend): wire up gradebook router"
```

### Task 8: GET summary endpoint (TDD)

**Files:**
- Modify: `backend/routes/gradebook.py`
- Create: `backend/tests/test_gradebook_routes.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_gradebook_routes.py`:

```python
"""Route tests for /api/gradebook/* — exercise the real Pydantic + service code,
mock only the Supabase `table()` boundary."""
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def _mock_table_rows(rows_by_table):
    """Return a side_effect for `db.connection.table` that returns canned rows.

    rows_by_table: {"users": [...], "courses": [...], ...}
    Each `select(...)` call returns the rows for that table; `insert`,
    `update`, `delete` echo the data back.
    """
    def factory(name):
        m = MagicMock()
        m.select.return_value = rows_by_table.get(name, [])
        m.insert.side_effect = lambda d: [d] if isinstance(d, dict) else d
        m.update.side_effect = lambda d, filters: [d]
        m.delete.return_value = []
        return m
    return factory


def _auth(user_id="u1"):
    return {"user_id": user_id}


# ── GET /summary ─────────────────────────────────────────────────────────────

class TestSummary:
    def test_returns_courses_with_computed_grades(self):
        enrolled = [
            {"course_id": "cs161", "letter_scale": None, "courses": {
                "id": "cs161", "course_code": "CS 161", "course_name": "Intro CS",
                "semester": "Spring 2026"}},
        ]
        cats = [{"id": "exams", "course_id": "cs161", "name": "Exams", "weight": 100, "sort_order": 0}]
        assigns = [
            {"id": "a1", "course_id": "cs161", "title": "Midterm", "category_id": "exams",
             "points_possible": 100, "points_earned": 90},
        ]
        rows = {
            "user_courses": enrolled,
            "course_categories": cats,
            "assignments": assigns,
        }
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.get("/api/gradebook/summary",
                           params={"user_id": "u1", "semester": "Spring 2026"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["courses"]) == 1
        c = body["courses"][0]
        assert c["course_code"] == "CS 161"
        assert c["percent"] == pytest.approx(90.0)
        assert c["letter"] == "A-"
        assert c["graded_count"] == 1
        assert c["total_count"] == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_routes.py::TestSummary -v
```

Expected: 1 failure with 404 (route not defined).

- [ ] **Step 3: Implement the route**

Append to `backend/routes/gradebook.py`:

```python
@router.get("/summary")
def get_summary(request: Request, user_id: str = Query(...), semester: str = Query(...)):
    """Return all enrolled courses for the given semester with computed
    current grade + letter."""
    require_self(user_id, request)

    enrollments = table("user_courses").select(
        "course_id,letter_scale,courses!inner(id,course_code,course_name,semester)",
        filters={
            "user_id": f"eq.{user_id}",
            "courses.semester": f"eq.{semester}",
        },
    )
    if not enrollments:
        return {"courses": []}

    course_ids = [e["course_id"] for e in enrollments]
    in_clause = "in.(" + ",".join(course_ids) + ")"

    cats = table("course_categories").select(
        "*",
        filters={"user_id": f"eq.{user_id}", "course_id": in_clause},
    )
    assigns = table("assignments").select(
        "id,course_id,category_id,points_possible,points_earned",
        filters={"user_id": f"eq.{user_id}", "course_id": in_clause},
    )

    cats_by_course: dict[str, list] = {cid: [] for cid in course_ids}
    for c in cats:
        cats_by_course.setdefault(c["course_id"], []).append(c)
    assigns_by_course: dict[str, list] = {cid: [] for cid in course_ids}
    for a in assigns:
        assigns_by_course.setdefault(a["course_id"], []).append(a)

    out = []
    for e in enrollments:
        cid = e["course_id"]
        course = e["courses"]
        course_assigns = assigns_by_course[cid]
        graded = [a for a in course_assigns
                  if a.get("points_possible") and a.get("points_earned") is not None]
        percent = gradebook_service.current_grade(cats_by_course[cid], course_assigns)
        letter = gradebook_service.letter_for(percent, e.get("letter_scale"))
        out.append({
            "course_id": cid,
            "course_code": course["course_code"],
            "course_name": course["course_name"],
            "semester": course["semester"],
            "percent": percent,
            "letter": letter,
            "graded_count": len(graded),
            "total_count": len(course_assigns),
        })
    return {"courses": out}
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_routes.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/routes/gradebook.py backend/tests/test_gradebook_routes.py
git commit -m "feat(backend): GET /api/gradebook/summary"
```

### Task 9: GET course-detail endpoint (TDD)

**Files:**
- Modify: `backend/routes/gradebook.py`
- Modify: `backend/tests/test_gradebook_routes.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_gradebook_routes.py`:

```python
# ── GET /courses/{course_id} ─────────────────────────────────────────────────

class TestCourseDetail:
    def test_returns_categories_assignments_and_overall(self):
        enrollment = [{"course_id": "cs161", "letter_scale": None,
                       "courses": {"id": "cs161", "course_code": "CS 161",
                                   "course_name": "Intro CS", "semester": "Spring 2026"}}]
        cats = [
            {"id": "exams", "course_id": "cs161", "user_id": "u1",
             "name": "Exams", "weight": 60, "sort_order": 0},
            {"id": "psets", "course_id": "cs161", "user_id": "u1",
             "name": "P-Sets", "weight": 40, "sort_order": 1},
        ]
        assigns = [
            {"id": "a1", "user_id": "u1", "course_id": "cs161", "title": "Midterm",
             "category_id": "exams", "points_possible": 100, "points_earned": 80,
             "due_date": "2026-03-10", "assignment_type": "exam", "notes": None,
             "source": "manual"},
            {"id": "a2", "user_id": "u1", "course_id": "cs161", "title": "P-Set 1",
             "category_id": "psets", "points_possible": 100, "points_earned": 100,
             "due_date": "2026-02-01", "assignment_type": "homework", "notes": None,
             "source": "manual"},
        ]
        rows = {
            "user_courses": enrollment,
            "course_categories": cats,
            "assignments": assigns,
        }
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.get("/api/gradebook/courses/cs161", params={"user_id": "u1"})
        assert r.status_code == 200
        body = r.json()
        assert body["course_code"] == "CS 161"
        # 0.8*60 + 1.0*40 = 88
        assert body["percent"] == pytest.approx(88.0)
        assert body["letter"] == "B+"
        assert {c["name"] for c in body["categories"]} == {"Exams", "P-Sets"}
        assert len(body["assignments"]) == 2

    def test_404_when_user_not_enrolled(self):
        rows = {"user_courses": []}
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.get("/api/gradebook/courses/nope", params={"user_id": "u1"})
        assert r.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_routes.py::TestCourseDetail -v
```

Expected: 2 failures (route not defined → 404 for the first test, but the second already expects 404 so it might pass coincidentally; rely on the first failing).

- [ ] **Step 3: Implement the route**

Append to `backend/routes/gradebook.py`:

```python
@router.get("/courses/{course_id}")
def get_course(course_id: str, request: Request, user_id: str = Query(...)):
    """Full gradebook for one course: categories, assignments, computed grade."""
    require_self(user_id, request)

    enrollment = table("user_courses").select(
        "course_id,letter_scale,courses!inner(id,course_code,course_name,semester)",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        limit=1,
    )
    if not enrollment:
        raise HTTPException(status_code=404, detail="Course not in your gradebook")
    course = enrollment[0]["courses"]
    letter_scale = enrollment[0].get("letter_scale")

    cats = table("course_categories").select(
        "*",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        order="sort_order.asc",
    )
    assigns = table("assignments").select(
        "*",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        order="due_date.asc",
    )

    # Per-category grade for the UI.
    by_cat: dict[str, list] = {c["id"]: [] for c in cats}
    for a in assigns:
        cid = a.get("category_id")
        if cid in by_cat:
            by_cat[cid].append(a)
    for c in cats:
        c["category_grade"] = gradebook_service.category_grade(by_cat[c["id"]])

    percent = gradebook_service.current_grade(cats, assigns)
    letter = gradebook_service.letter_for(percent, letter_scale)

    return {
        "course_id": course["id"],
        "course_code": course["course_code"],
        "course_name": course["course_name"],
        "semester": course["semester"],
        "percent": percent,
        "letter": letter,
        "letter_scale": letter_scale,
        "categories": cats,
        "assignments": assigns,
    }
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_routes.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/routes/gradebook.py backend/tests/test_gradebook_routes.py
git commit -m "feat(backend): GET /api/gradebook/courses/{id}"
```

### Task 10: Categories CRUD (TDD)

**Files:**
- Modify: `backend/routes/gradebook.py`
- Modify: `backend/tests/test_gradebook_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_gradebook_routes.py`:

```python
# ── Categories CRUD ──────────────────────────────────────────────────────────

class TestCategories:
    def test_create_one_category(self):
        rows = {"user_courses": [{"id": "uc1"}]}
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.post(
                "/api/gradebook/courses/cs161/categories",
                json={"user_id": "u1", "name": "Exams", "weight": 40},
            )
        assert r.status_code == 200
        assert r.json()["category"]["name"] == "Exams"

    def test_create_rejects_unknown_course(self):
        rows = {"user_courses": []}
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.post(
                "/api/gradebook/courses/cs999/categories",
                json={"user_id": "u1", "name": "Exams", "weight": 40},
            )
        assert r.status_code == 404

    def test_bulk_update_validates_weight_total(self):
        rows = {"user_courses": [{"id": "uc1"}]}
        body = {
            "user_id": "u1",
            "categories": [
                {"id": "exams", "name": "Exams", "weight": 60, "sort_order": 0},
                {"id": "psets", "name": "P-Sets", "weight": 30, "sort_order": 1},
            ],
        }
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.patch("/api/gradebook/courses/cs161/categories", json=body)
        assert r.status_code == 400
        assert "100" in r.json()["detail"].lower() or "weight" in r.json()["detail"].lower()

    def test_bulk_update_accepts_total_100(self):
        rows = {"user_courses": [{"id": "uc1"}]}
        body = {
            "user_id": "u1",
            "categories": [
                {"id": "exams", "name": "Exams", "weight": 60, "sort_order": 0},
                {"id": "psets", "name": "P-Sets", "weight": 40, "sort_order": 1},
            ],
        }
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.patch("/api/gradebook/courses/cs161/categories", json=body)
        assert r.status_code == 200
        assert len(r.json()["categories"]) == 2

    def test_delete_orphans_assignments(self):
        rows = {"course_categories": [{"id": "exams", "user_id": "u1", "course_id": "cs161"}]}
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.delete("/api/gradebook/categories/exams", params={"user_id": "u1"})
        assert r.status_code == 200
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_routes.py::TestCategories -v
```

Expected: 5 failures (404 from missing routes).

- [ ] **Step 3: Implement the routes**

Append to `backend/routes/gradebook.py`:

```python
@router.post("/courses/{course_id}/categories")
def create_category(course_id: str, body: CreateCategoryBody, request: Request):
    require_self(body.user_id, request)
    if not _user_owns_course(body.user_id, course_id):
        raise HTTPException(status_code=404, detail="Course not in your gradebook")
    new_id = str(uuid.uuid4())
    inserted = table("course_categories").insert({
        "id": new_id,
        "user_id": body.user_id,
        "course_id": course_id,
        "name": body.name,
        "weight": body.weight,
        "sort_order": 0,
    })
    return {"category": inserted[0] if inserted else None}


@router.patch("/courses/{course_id}/categories")
def bulk_update_categories(course_id: str, body: BulkUpdateCategoriesBody, request: Request):
    require_self(body.user_id, request)
    if not _user_owns_course(body.user_id, course_id):
        raise HTTPException(status_code=404, detail="Course not in your gradebook")

    total = sum(c.weight for c in body.categories)
    if abs(total - 100.0) > 0.5:
        raise HTTPException(
            status_code=400,
            detail=f"Category weights must sum to 100% (got {total:g}%)",
        )

    # Replacement set: insert new (no id), update existing.
    saved = []
    for c in body.categories:
        if c.id:
            updated = table("course_categories").update(
                {"name": c.name, "weight": c.weight, "sort_order": c.sort_order},
                filters={"id": f"eq.{c.id}", "user_id": f"eq.{body.user_id}"},
            )
            saved.extend(updated)
        else:
            new = table("course_categories").insert({
                "id": str(uuid.uuid4()),
                "user_id": body.user_id,
                "course_id": course_id,
                "name": c.name,
                "weight": c.weight,
                "sort_order": c.sort_order,
            })
            saved.extend(new)
    return {"categories": saved}


@router.delete("/categories/{category_id}")
def delete_category(category_id: str, request: Request, user_id: str = Query(...)):
    require_self(user_id, request)
    cat = _user_owns_category(user_id, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    # FK is ON DELETE SET NULL → assignments get category_id=null automatically.
    table("course_categories").delete(filters={"id": f"eq.{category_id}"})
    return {"deleted": True}
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_routes.py -v
```

Expected: all tests pass (3 from before + 5 new = 8).

- [ ] **Step 5: Commit**

```bash
git add backend/routes/gradebook.py backend/tests/test_gradebook_routes.py
git commit -m "feat(backend): gradebook categories CRUD"
```

### Task 11: Assignments CRUD (TDD)

**Files:**
- Modify: `backend/routes/gradebook.py`
- Modify: `backend/tests/test_gradebook_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_gradebook_routes.py`:

```python
# ── Assignments CRUD ─────────────────────────────────────────────────────────

class TestAssignments:
    def test_create_assignment_minimal(self):
        rows = {"user_courses": [{"id": "uc1"}]}
        body = {"user_id": "u1", "course_id": "cs161", "title": "Midterm 1"}
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.post("/api/gradebook/assignments", json=body)
        assert r.status_code == 200
        a = r.json()["assignment"]
        assert a["title"] == "Midterm 1"
        assert a["source"] == "manual"

    def test_create_rejects_unknown_course(self):
        rows = {"user_courses": []}
        body = {"user_id": "u1", "course_id": "cs999", "title": "X"}
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.post("/api/gradebook/assignments", json=body)
        assert r.status_code == 404

    def test_create_rejects_zero_points_possible(self):
        rows = {"user_courses": [{"id": "uc1"}]}
        body = {"user_id": "u1", "course_id": "cs161", "title": "X",
                "points_possible": 0}
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.post("/api/gradebook/assignments", json=body)
        assert r.status_code == 422  # Pydantic gt=0 validation

    def test_update_grade_inline(self):
        rows = {"assignments": [{"id": "a1", "user_id": "u1", "course_id": "cs161"}]}
        body = {"user_id": "u1", "points_earned": 87}
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.patch("/api/gradebook/assignments/a1", json=body)
        assert r.status_code == 200

    def test_update_404_when_not_owner(self):
        rows = {"assignments": []}
        body = {"user_id": "u1", "points_earned": 87}
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.patch("/api/gradebook/assignments/a1", json=body)
        assert r.status_code == 404

    def test_delete_assignment(self):
        rows = {"assignments": [{"id": "a1", "user_id": "u1"}]}
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.delete("/api/gradebook/assignments/a1", params={"user_id": "u1"})
        assert r.status_code == 200
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_routes.py::TestAssignments -v
```

Expected: 6 failures (404 from missing routes; the 422 case may already pass via Pydantic default 422 from the bad body).

- [ ] **Step 3: Implement the routes**

Append to `backend/routes/gradebook.py`:

```python
def _user_owns_assignment(user_id: str, assignment_id: str) -> dict | None:
    rows = table("assignments").select(
        "*",
        filters={"id": f"eq.{assignment_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    )
    return rows[0] if rows else None


@router.post("/assignments")
def create_assignment(body: CreateAssignmentBody, request: Request):
    require_self(body.user_id, request)
    if not _user_owns_course(body.user_id, body.course_id):
        raise HTTPException(status_code=404, detail="Course not in your gradebook")
    if body.category_id and not _user_owns_category(body.user_id, body.category_id):
        raise HTTPException(status_code=400, detail="Category not in your gradebook")

    new_id = str(uuid.uuid4())
    inserted = table("assignments").insert({
        "id": new_id,
        "user_id": body.user_id,
        "course_id": body.course_id,
        "title": body.title,
        "category_id": body.category_id,
        "points_possible": body.points_possible,
        "points_earned": body.points_earned,
        "due_date": body.due_date,
        "assignment_type": body.assignment_type,
        "notes": body.notes,
        "source": "manual",
    })
    return {"assignment": inserted[0] if inserted else None}


@router.patch("/assignments/{assignment_id}")
def update_assignment_route(assignment_id: str, body: UpdateAssignmentBody, request: Request):
    require_self(body.user_id, request)
    if not _user_owns_assignment(body.user_id, assignment_id):
        raise HTTPException(status_code=404, detail="Assignment not found")
    if body.category_id and not _user_owns_category(body.user_id, body.category_id):
        raise HTTPException(status_code=400, detail="Category not in your gradebook")

    patch_data = body.model_dump(exclude_unset=True, exclude={"user_id"})
    if not patch_data:
        return {"updated": False}
    table("assignments").update(
        patch_data,
        filters={"id": f"eq.{assignment_id}", "user_id": f"eq.{body.user_id}"},
    )
    return {"updated": True}


@router.delete("/assignments/{assignment_id}")
def delete_assignment_route(assignment_id: str, request: Request, user_id: str = Query(...)):
    require_self(user_id, request)
    if not _user_owns_assignment(user_id, assignment_id):
        raise HTTPException(status_code=404, detail="Assignment not found")
    table("assignments").delete(
        filters={"id": f"eq.{assignment_id}", "user_id": f"eq.{user_id}"},
    )
    return {"deleted": True}
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_routes.py -v
```

Expected: all 14 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/routes/gradebook.py backend/tests/test_gradebook_routes.py
git commit -m "feat(backend): gradebook assignments CRUD"
```

### Task 12: Letter-scale override endpoint (TDD)

**Files:**
- Modify: `backend/routes/gradebook.py`
- Modify: `backend/tests/test_gradebook_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_gradebook_routes.py`:

```python
# ── PATCH /courses/{course_id}/scale ─────────────────────────────────────────

class TestLetterScale:
    def test_set_custom_scale(self):
        rows = {"user_courses": [{"id": "uc1"}]}
        body = {"user_id": "u1", "scale": [
            {"min": 90, "letter": "A"},
            {"min": 80, "letter": "B"},
            {"min": 0,  "letter": "F"},
        ]}
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.patch("/api/gradebook/courses/cs161/scale", json=body)
        assert r.status_code == 200

    def test_clear_scale_with_null(self):
        rows = {"user_courses": [{"id": "uc1"}]}
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.patch("/api/gradebook/courses/cs161/scale",
                             json={"user_id": "u1", "scale": None})
        assert r.status_code == 200

    def test_rejects_non_monotonic_scale(self):
        rows = {"user_courses": [{"id": "uc1"}]}
        body = {"user_id": "u1", "scale": [
            {"min": 80, "letter": "A"},
            {"min": 90, "letter": "B"},  # B requires higher than A — invalid
        ]}
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.patch("/api/gradebook/courses/cs161/scale", json=body)
        assert r.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_routes.py::TestLetterScale -v
```

Expected: 3 failures (404 from missing route).

- [ ] **Step 3: Implement the route**

Append to `backend/routes/gradebook.py`:

```python
@router.patch("/courses/{course_id}/scale")
def set_letter_scale(course_id: str, body: SetLetterScaleBody, request: Request):
    require_self(body.user_id, request)
    if not _user_owns_course(body.user_id, course_id):
        raise HTTPException(status_code=404, detail="Course not in your gradebook")

    scale_payload = None
    if body.scale is not None:
        # Validate monotonic: as `min` increases, the letter must not regress.
        # Simpler check: tiers in input order should already be descending by min.
        prev_min = float("inf")
        for tier in body.scale:
            if tier.min > prev_min:
                raise HTTPException(
                    status_code=400,
                    detail="Letter scale tiers must be ordered descending by min",
                )
            prev_min = tier.min
        scale_payload = [tier.model_dump() for tier in body.scale]

    table("user_courses").update(
        {"letter_scale": scale_payload},
        filters={"user_id": f"eq.{body.user_id}", "course_id": f"eq.{course_id}"},
    )
    return {"updated": True, "letter_scale": scale_payload}
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_routes.py -v
```

Expected: all 17 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/routes/gradebook.py backend/tests/test_gradebook_routes.py
git commit -m "feat(backend): per-course letter scale override"
```

---

## Phase 5 — Syllabus extraction expansion

### Task 13: Update the syllabus extraction prompt to emit categories

**Files:**
- Modify: `backend/prompts/syllabus_extraction.txt`

- [ ] **Step 1: Replace the prompt body**

Open `backend/prompts/syllabus_extraction.txt`. Replace the entire file with:

```
Extract the grading scheme and all assignments/exams/readings/deadlines from this document.

Return TWO arrays:

1) categories — the grading-weight buckets named in the syllabus
   (e.g. "Exams", "Problem Sets", "Final Project").
   - name: short label (under 40 chars)
   - weight: integer 0–100; pass through verbatim from the syllabus, do NOT normalize
   - If the syllabus does not state a clear grading scheme, return [].

2) assignments — every individual deadline.
   - title: assignment or exam name (concise, under 80 chars)
   - due_date: ISO format YYYY-MM-DD. If year is not specified, assume 2026.
   - course_name: course name or code if identifiable
   - assignment_type: one of homework, exam, reading, project, quiz, other
   - notes: one short sentence of extra context, or null
   - Do NOT map assignments to categories — leave that to the user.

Output ONLY a raw JSON object — no markdown fences, no backticks, no explanation:
{
  "categories": [
    { "name": "string", "weight": 40 }
  ],
  "assignments": [
    { "title": "string", "due_date": "YYYY-MM-DD", "course_name": "string", "assignment_type": "string", "notes": "string or null" }
  ],
  "warnings": ["any ambiguous extractions"]
}
```

- [ ] **Step 2: Commit**

```bash
git add backend/prompts/syllabus_extraction.txt
git commit -m "feat(prompts): syllabus extraction emits categories"
```

### Task 14: Surface categories from `_process_document`

**Files:**
- Modify: `backend/routes/documents.py`

- [ ] **Step 1: Locate the syllabus prompt block**

In `backend/routes/documents.py`, find the `_process_document` function (search for `def _process_document`). Find the section of the prompt that says:

```
'  "assignments": []\n'
"}\n"
'If category is "syllabus", populate "assignments" with every deadline found:\n'
```

- [ ] **Step 2: Add `categories` to the prompt and the parsed return**

Update the prompt JSON shape inside `_process_document` to include `categories`, and update the parse step at the bottom of the function to extract them. Specifically:

In the prompt string, change:

```python
'  "assignments": []\n'
```

to:

```python
'  "categories": [],\n'
'  "assignments": []\n'
```

And expand the syllabus instruction to add:

```python
'If category is "syllabus", also populate "categories" with the grading-weight buckets:\n'
'  {"name": "Exams", "weight": 40}  // weight passes through verbatim, do not normalize\n'
'For non-syllabus documents, "categories" must be [].\n'
```

Then in the return-shaping block at the bottom of `_process_document` (where `assignments` is coerced and returned), add:

```python
categories = _coerce_dict_list(raw.get("categories"))
clean_categories = []
for c in categories:
    name = c.get("name")
    weight = c.get("weight")
    if isinstance(name, str) and name.strip() and isinstance(weight, (int, float)):
        clean_categories.append({"name": name.strip(), "weight": float(weight)})
```

Include `"categories": clean_categories,` in the dict returned by `_process_document`.

- [ ] **Step 3: Surface `categories` in the upload response**

In the upload handler (search for `ai = _process_document` around line 282), the response currently includes `summary`, `concept_notes`, `assignments`, etc. Add `"categories": ai.get("categories", []),` to the response payload so the frontend can show extracted categories during the syllabus apply flow.

- [ ] **Step 4: Run existing tests to confirm no regression**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_documents_routes.py -v
```

Expected: all existing tests pass (or existing failures are pre-existing — confirm with `git stash` test against `main`).

- [ ] **Step 5: Commit**

```bash
git add backend/routes/documents.py
git commit -m "feat(backend): surface syllabus categories from upload"
```

### Task 15: Syllabus-apply route (TDD)

**Files:**
- Modify: `backend/routes/gradebook.py`
- Modify: `backend/tests/test_gradebook_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_gradebook_routes.py`:

```python
# ── POST /syllabus/apply ─────────────────────────────────────────────────────

class TestSyllabusApply:
    def test_replaces_categories_and_inserts_assignments(self):
        rows = {
            "user_courses": [{"id": "uc1"}],
            "documents": [{"id": "doc1", "user_id": "u1"}],
            "course_categories": [],   # no existing categories
            "assignments": [],          # no existing assignments to dedupe against
        }
        body = {
            "user_id": "u1",
            "course_id": "cs161",
            "doc_id": "doc1",
            "categories": [
                {"name": "Exams", "weight": 60, "sort_order": 0},
                {"name": "P-Sets", "weight": 40, "sort_order": 1},
            ],
            "assignments": [
                {"title": "Midterm 1", "due_date": "2026-03-10",
                 "assignment_type": "exam", "notes": None},
                {"title": "P-Set 1", "due_date": "2026-02-01",
                 "assignment_type": "homework", "notes": None},
            ],
        }
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.post("/api/gradebook/syllabus/apply", json=body)
        assert r.status_code == 200
        out = r.json()
        assert "course" in out  # returns the course detail payload

    def test_rejects_when_weights_dont_sum_to_100(self):
        rows = {"user_courses": [{"id": "uc1"}], "documents": [{"id": "doc1", "user_id": "u1"}]}
        body = {
            "user_id": "u1",
            "course_id": "cs161",
            "doc_id": "doc1",
            "categories": [
                {"name": "Exams", "weight": 60, "sort_order": 0},
                {"name": "P-Sets", "weight": 30, "sort_order": 1},
            ],
            "assignments": [],
        }
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.post("/api/gradebook/syllabus/apply", json=body)
        assert r.status_code == 400

    def test_rejects_unknown_course(self):
        rows = {"user_courses": [], "documents": [{"id": "doc1", "user_id": "u1"}]}
        body = {
            "user_id": "u1",
            "course_id": "cs999",
            "doc_id": "doc1",
            "categories": [{"name": "X", "weight": 100, "sort_order": 0}],
            "assignments": [],
        }
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.post("/api/gradebook/syllabus/apply", json=body)
        assert r.status_code == 404

    def test_rejects_doc_owned_by_other_user(self):
        rows = {"user_courses": [{"id": "uc1"}], "documents": [{"id": "doc1", "user_id": "other"}]}
        body = {
            "user_id": "u1",
            "course_id": "cs161",
            "doc_id": "doc1",
            "categories": [{"name": "X", "weight": 100, "sort_order": 0}],
            "assignments": [],
        }
        with patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.post("/api/gradebook/syllabus/apply", json=body)
        assert r.status_code == 403
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_routes.py::TestSyllabusApply -v
```

Expected: 4 failures (route not defined → 404 for all).

- [ ] **Step 3: Implement the route**

Append to `backend/routes/gradebook.py`:

```python
@router.post("/syllabus/apply")
def apply_syllabus(body: SyllabusApplyBody, request: Request):
    """Apply user-confirmed extracted categories + assignments to a course.

    - Validates weights sum to 100 (±0.5).
    - Validates the user owns the course AND the document.
    - Wipes existing categories for (user, course); inserts new ones.
    - Inserts assignments with source='syllabus', dedupes by (course_id, title, due_date).
    - Sets user_courses.syllabus_doc_id.
    - Returns the refreshed course detail.
    """
    require_self(body.user_id, request)
    if not _user_owns_course(body.user_id, body.course_id):
        raise HTTPException(status_code=404, detail="Course not in your gradebook")

    doc_rows = table("documents").select(
        "id,user_id",
        filters={"id": f"eq.{body.doc_id}"},
        limit=1,
    )
    if not doc_rows or doc_rows[0]["user_id"] != body.user_id:
        raise HTTPException(status_code=403, detail="Document not yours")

    total = sum(c.weight for c in body.categories)
    if body.categories and abs(total - 100.0) > 0.5:
        raise HTTPException(
            status_code=400,
            detail=f"Category weights must sum to 100% (got {total:g}%)",
        )

    # Wipe + replace categories.
    table("course_categories").delete(filters={
        "user_id": f"eq.{body.user_id}",
        "course_id": f"eq.{body.course_id}",
    })
    new_cats = [
        {
            "id": str(uuid.uuid4()),
            "user_id": body.user_id,
            "course_id": body.course_id,
            "name": c.name,
            "weight": c.weight,
            "sort_order": c.sort_order,
        }
        for c in body.categories
    ]
    if new_cats:
        table("course_categories").insert(new_cats)

    # Dedupe assignments by (course_id, title, due_date).
    existing = table("assignments").select(
        "title,due_date",
        filters={"user_id": f"eq.{body.user_id}", "course_id": f"eq.{body.course_id}"},
    )
    seen = {(e.get("title", ""), e.get("due_date") or "") for e in existing}
    new_assigns = []
    for a in body.assignments:
        title = a.get("title", "")
        due = a.get("due_date") or ""
        if (title, due) in seen:
            continue
        seen.add((title, due))
        new_assigns.append({
            "id": str(uuid.uuid4()),
            "user_id": body.user_id,
            "course_id": body.course_id,
            "title": title,
            "due_date": a.get("due_date"),
            "assignment_type": a.get("assignment_type"),
            "notes": a.get("notes"),
            "category_id": None,
            "points_possible": None,
            "points_earned": None,
            "source": "syllabus",
        })
    if new_assigns:
        table("assignments").insert(new_assigns)

    # Stamp the doc id on the enrollment.
    table("user_courses").update(
        {"syllabus_doc_id": body.doc_id},
        filters={"user_id": f"eq.{body.user_id}", "course_id": f"eq.{body.course_id}"},
    )

    # Return the refreshed course payload so the client can swap state in.
    refreshed = get_course(body.course_id, request, user_id=body.user_id)
    return {"course": refreshed}
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_gradebook_routes.py -v
```

Expected: all 21 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/routes/gradebook.py backend/tests/test_gradebook_routes.py
git commit -m "feat(backend): syllabus apply replaces categories + dedupes assignments"
```

---

## Phase 6 — Frontend types & API client

### Task 16: Add gradebook types

**Files:**
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Append the types**

Append to `frontend/src/lib/types.ts`:

```ts
// ── Gradebook ────────────────────────────────────────────────────────────────

export interface LetterScaleTier {
  min: number;
  letter: string;
}

export interface GradeCategory {
  id: string;
  name: string;
  weight: number;
  sort_order: number;
  category_grade?: number | null;  // 0–1, server-computed; only on detail
}

export interface GradedAssignment {
  id: string;
  title: string;
  course_id: string;
  category_id: string | null;
  points_possible: number | null;
  points_earned: number | null;
  due_date: string | null;
  assignment_type: string | null;
  notes: string | null;
  source: "manual" | "syllabus" | "gradescope";
}

export interface GradebookCourseSummary {
  course_id: string;
  course_code: string;
  course_name: string;
  semester: string;
  percent: number | null;
  letter: string | null;
  graded_count: number;
  total_count: number;
}

export interface GradebookSummary {
  courses: GradebookCourseSummary[];
}

export interface GradebookCourse {
  course_id: string;
  course_code: string;
  course_name: string;
  semester: string;
  percent: number | null;
  letter: string | null;
  letter_scale: LetterScaleTier[] | null;
  categories: GradeCategory[];
  assignments: GradedAssignment[];
}

export interface ExtractedSyllabusCategory {
  name: string;
  weight: number;
}
```

- [ ] **Step 2: Verify type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/types.ts
git commit -m "feat(frontend): gradebook types"
```

### Task 17: Add API client wrappers

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add the wrappers and import**

Open `frontend/src/lib/api.ts`. At the top of the file (with the other type imports), add:

```ts
import type {
  GradebookSummary, GradebookCourse, GradeCategory, GradedAssignment,
  LetterScaleTier,
} from '@/lib/types';
```

(If a `from '@/lib/types'` import already exists, merge the new types into that import.)

At the bottom of the file, append:

```ts
// ── Gradebook ────────────────────────────────────────────────────────────────

export const getGradebookSummary = (userId: string, semester: string) =>
  fetchJSON<GradebookSummary>(
    `/api/gradebook/summary?user_id=${encodeURIComponent(userId)}&semester=${encodeURIComponent(semester)}`,
  );

export const getGradebookCourse = (userId: string, courseId: string) =>
  fetchJSON<GradebookCourse>(
    `/api/gradebook/courses/${encodeURIComponent(courseId)}?user_id=${encodeURIComponent(userId)}`,
  );

export const createCategory = (
  userId: string,
  courseId: string,
  name: string,
  weight: number,
) =>
  fetchJSON<{ category: GradeCategory }>(
    `/api/gradebook/courses/${encodeURIComponent(courseId)}/categories`,
    { method: 'POST', body: JSON.stringify({ user_id: userId, name, weight }) },
  );

export const bulkUpdateCategories = (
  userId: string,
  courseId: string,
  categories: { id?: string; name: string; weight: number; sort_order: number }[],
) =>
  fetchJSON<{ categories: GradeCategory[] }>(
    `/api/gradebook/courses/${encodeURIComponent(courseId)}/categories`,
    { method: 'PATCH', body: JSON.stringify({ user_id: userId, categories }) },
  );

export const deleteCategory = (userId: string, categoryId: string) =>
  fetchJSON<{ deleted: true }>(
    `/api/gradebook/categories/${encodeURIComponent(categoryId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

export const createGradedAssignment = (
  userId: string,
  courseId: string,
  fields: Partial<Omit<GradedAssignment, 'id' | 'course_id' | 'source'>> & { title: string },
) =>
  fetchJSON<{ assignment: GradedAssignment }>('/api/gradebook/assignments', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, course_id: courseId, ...fields }),
  });

export const updateGradedAssignment = (
  userId: string,
  assignmentId: string,
  fields: Partial<Omit<GradedAssignment, 'id' | 'course_id' | 'source'>>,
) =>
  fetchJSON<{ updated: boolean }>(
    `/api/gradebook/assignments/${encodeURIComponent(assignmentId)}`,
    { method: 'PATCH', body: JSON.stringify({ user_id: userId, ...fields }) },
  );

export const deleteGradedAssignment = (userId: string, assignmentId: string) =>
  fetchJSON<{ deleted: true }>(
    `/api/gradebook/assignments/${encodeURIComponent(assignmentId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

export const setLetterScale = (
  userId: string,
  courseId: string,
  scale: LetterScaleTier[] | null,
) =>
  fetchJSON<{ updated: true; letter_scale: LetterScaleTier[] | null }>(
    `/api/gradebook/courses/${encodeURIComponent(courseId)}/scale`,
    { method: 'PATCH', body: JSON.stringify({ user_id: userId, scale }) },
  );

export const applySyllabus = (payload: {
  userId: string;
  courseId: string;
  docId: string;
  categories: { name: string; weight: number; sort_order: number }[];
  assignments: { title: string; due_date: string | null; assignment_type: string | null; notes: string | null }[];
}) =>
  fetchJSON<{ course: GradebookCourse }>('/api/gradebook/syllabus/apply', {
    method: 'POST',
    body: JSON.stringify({
      user_id: payload.userId,
      course_id: payload.courseId,
      doc_id: payload.docId,
      categories: payload.categories,
      assignments: payload.assignments,
    }),
  });
```

- [ ] **Step 2: Verify type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): gradebook API client wrappers"
```

---

## Phase 7 — Frontend landing page

### Task 18: Build the SemesterChips component

**Files:**
- Create: `frontend/src/components/Gradebook/SemesterChips.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/Gradebook/SemesterChips.tsx`:

```tsx
"use client";
import React from "react";

interface Props {
  semesters: string[];        // e.g. ["Spring 2026", "Fall 2025"]
  selected: string;
  onSelect: (semester: string) => void;
}

export function SemesterChips({ semesters, selected, onSelect }: Props) {
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
      {semesters.map((s) => {
        const active = s === selected;
        return (
          <button
            key={s}
            type="button"
            onClick={() => onSelect(s)}
            style={{
              padding: "4px 12px",
              borderRadius: 999,
              border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
              background: active ? "var(--accent)" : "var(--bg)",
              color: active ? "#fff" : "var(--text)",
              fontSize: 12,
              fontWeight: active ? 600 : 400,
              cursor: "pointer",
              transition: "all var(--dur-fast) var(--ease)",
            }}
          >
            {s}
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Verify type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Gradebook/SemesterChips.tsx
git commit -m "feat(frontend): SemesterChips component"
```

### Task 19: Build the GradebookLanding screen

**Files:**
- Create: `frontend/src/components/screens/Gradebook/Landing.tsx`
- Modify: `frontend/src/app/(shell)/gradebook/page.tsx`

- [ ] **Step 1: Write the screen**

Create `frontend/src/components/screens/Gradebook/Landing.tsx`:

```tsx
"use client";
import React from "react";
import Link from "next/link";
import { TopBar } from "../../TopBar";
import { SemesterChips } from "../../Gradebook/SemesterChips";
import { useUser } from "@/context/UserContext";
import { useToast } from "../../ToastProvider";
import { getGradebookSummary, getCourses } from "@/lib/api";
import type { GradebookCourseSummary, EnrolledCourse } from "@/lib/types";

export function GradebookLanding() {
  const { userId, userReady } = useUser();
  const toast = useToast();

  const [semesters, setSemesters] = React.useState<string[]>([]);
  const [selected, setSelected] = React.useState<string>("");
  const [courses, setCourses] = React.useState<GradebookCourseSummary[]>([]);
  const [loading, setLoading] = React.useState(true);

  // Pull all enrollments first to build the semester list.
  React.useEffect(() => {
    if (!userId) return;
    getCourses(userId)
      .then((res) => {
        const all = res.courses as (EnrolledCourse & { semester?: string })[];
        const distinct = Array.from(
          new Set(all.map((c) => (c as any).semester).filter(Boolean)),
        ) as string[];
        // Fall back to "Spring 2026" if backend doesn't return semester yet.
        const list = distinct.length ? distinct : ["Spring 2026"];
        setSemesters(list);
        setSelected(list[0]);
      })
      .catch((err) => toast.error(`Could not load courses: ${err.message}`));
  }, [userId, toast]);

  React.useEffect(() => {
    if (!userId || !selected) return;
    setLoading(true);
    getGradebookSummary(userId, selected)
      .then((res) => setCourses(res.courses))
      .catch((err) => toast.error(`Gradebook failed to load: ${err.message}`))
      .finally(() => setLoading(false));
  }, [userId, selected, toast]);

  if (!userReady) return null;

  return (
    <>
      <TopBar
        title="Gradebook"
        actions={
          <Link
            href={`/gradebook?upload=1`}
            style={{
              padding: "6px 12px",
              borderRadius: "var(--r-sm)",
              background: "var(--accent)",
              color: "#fff",
              fontSize: 13,
              textDecoration: "none",
            }}
          >
            Upload syllabus
          </Link>
        }
      />
      <main style={{ padding: 32 }}>
        <SemesterChips
          semesters={semesters}
          selected={selected}
          onSelect={setSelected}
        />
        {loading ? (
          <p style={{ color: "var(--text-dim)" }}>Loading…</p>
        ) : courses.length === 0 ? (
          <p style={{ color: "var(--text-dim)" }}>
            No courses enrolled for {selected}. Add a course in onboarding to get started.
          </p>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
              gap: 12,
            }}
          >
            {courses.map((c) => (
              <Link
                key={c.course_id}
                href={`/gradebook/${encodeURIComponent(c.course_id)}`}
                style={{
                  padding: 16,
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  background: "var(--bg)",
                  textDecoration: "none",
                  color: "var(--text)",
                  transition: "background var(--dur-fast) var(--ease)",
                }}
              >
                <div className="label-micro">{c.course_code}</div>
                <div style={{ fontWeight: 600, margin: "2px 0 6px" }}>
                  {c.course_name}
                </div>
                <div
                  style={{
                    fontSize: 22,
                    fontWeight: 700,
                    color: "var(--accent)",
                  }}
                >
                  {c.letter ?? "—"}
                </div>
                <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                  {c.percent !== null ? `${c.percent.toFixed(1)}%` : "No grades yet"} ·{" "}
                  {c.graded_count}/{c.total_count} graded
                </div>
              </Link>
            ))}
          </div>
        )}
      </main>
    </>
  );
}
```

- [ ] **Step 2: Wire the page**

Replace the contents of `frontend/src/app/(shell)/gradebook/page.tsx` with:

```tsx
"use client";
import { GradebookLanding } from "@/components/screens/Gradebook/Landing";

export default function GradebookPage() {
  return <GradebookLanding />;
}
```

- [ ] **Step 3: Verify type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Manual smoke**

Start backend (`cd backend && source venv/bin/activate && python main.py`) and frontend (`cd frontend && npm run dev`). Open `http://localhost:3000/gradebook`. Confirm the page renders with the semester chips, even if the course grid is empty.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/screens/Gradebook/Landing.tsx frontend/src/app/\(shell\)/gradebook/page.tsx
git commit -m "feat(frontend): gradebook landing page"
```

---

## Phase 8 — Frontend course detail page

### Task 20: Build CategoryPanel + EditWeightsModal

**Files:**
- Create: `frontend/src/components/Gradebook/CategoryPanel.tsx`
- Create: `frontend/src/components/Gradebook/EditWeightsModal.tsx`

- [ ] **Step 1: Write CategoryPanel**

Create `frontend/src/components/Gradebook/CategoryPanel.tsx`:

```tsx
"use client";
import React from "react";
import type { GradeCategory } from "@/lib/types";

interface Props {
  categories: GradeCategory[];
  onEdit: () => void;
}

export function CategoryPanel({ categories, onEdit }: Props) {
  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: 16,
        marginBottom: 16,
        background: "var(--bg)",
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 8,
        }}
      >
        <div className="label-micro">Categories</div>
        <button
          type="button"
          onClick={onEdit}
          style={{
            fontSize: 12,
            padding: "4px 10px",
            border: "1px solid var(--border)",
            borderRadius: 6,
            background: "var(--bg)",
            cursor: "pointer",
          }}
        >
          Edit weights
        </button>
      </header>
      {categories.length === 0 ? (
        <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
          No categories yet. Click "Edit weights" to add some, or upload a syllabus.
        </p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {categories.map((c) => (
            <li
              key={c.id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                padding: "6px 0",
                borderBottom: "1px dashed var(--border)",
              }}
            >
              <span>
                {c.name} <span style={{ color: "var(--text-dim)" }}>({c.weight}%)</span>
              </span>
              <span style={{ fontWeight: 500 }}>
                {c.category_grade != null
                  ? `${(c.category_grade * 100).toFixed(1)}%`
                  : "—"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Write EditWeightsModal**

Create `frontend/src/components/Gradebook/EditWeightsModal.tsx`:

```tsx
"use client";
import React from "react";
import { createPortal } from "react-dom";
import type { GradeCategory } from "@/lib/types";

interface Draft {
  id?: string;
  name: string;
  weight: number;
  sort_order: number;
}

interface Props {
  open: boolean;
  initial: GradeCategory[];
  onClose: () => void;
  onSave: (categories: Draft[]) => Promise<void>;
}

export function EditWeightsModal({ open, initial, onClose, onSave }: Props) {
  const [mounted, setMounted] = React.useState(false);
  const [drafts, setDrafts] = React.useState<Draft[]>([]);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => setMounted(true), []);
  React.useEffect(() => {
    if (open) {
      setDrafts(
        initial.map((c) => ({
          id: c.id, name: c.name, weight: c.weight, sort_order: c.sort_order,
        })),
      );
    }
  }, [open, initial]);

  if (!mounted || !open) return null;

  const total = drafts.reduce((s, d) => s + Number(d.weight || 0), 0);
  const valid = Math.abs(total - 100) <= 0.5 && drafts.every((d) => d.name.trim() !== "");

  const update = (i: number, patch: Partial<Draft>) =>
    setDrafts((arr) => arr.map((d, idx) => (idx === i ? { ...d, ...patch } : d)));
  const remove = (i: number) =>
    setDrafts((arr) => arr.filter((_, idx) => idx !== i));
  const add = () =>
    setDrafts((arr) => [...arr, { name: "", weight: 0, sort_order: arr.length }]);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg)", borderRadius: 12, padding: 20,
          minWidth: 420, maxWidth: 560, maxHeight: "80vh", overflow: "auto",
        }}
      >
        <h3 style={{ margin: "0 0 12px" }}>Edit categories &amp; weights</h3>
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {drafts.map((d, i) => (
            <li key={i} style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <input
                value={d.name}
                placeholder="Category name"
                onChange={(e) => update(i, { name: e.target.value })}
                style={{ flex: 1, padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
              />
              <input
                type="number"
                value={d.weight}
                min={0}
                max={100}
                onChange={(e) => update(i, { weight: Number(e.target.value) })}
                style={{ width: 70, padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
              />
              <span style={{ alignSelf: "center" }}>%</span>
              <button type="button" onClick={() => remove(i)} aria-label="Remove">
                ✕
              </button>
            </li>
          ))}
        </ul>
        <button type="button" onClick={add} style={{ fontSize: 13, marginTop: 4 }}>
          + Add category
        </button>
        <div
          style={{
            marginTop: 16, padding: "8px 0",
            borderTop: "1px solid var(--border)",
            display: "flex", justifyContent: "space-between", alignItems: "center",
          }}
        >
          <span style={{ color: valid ? "var(--accent)" : "var(--err)" }}>
            Total: {total.toFixed(1)}% {valid ? "✓" : `(need 100%)`}
          </span>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" onClick={onClose}>Cancel</button>
            <button
              type="button"
              disabled={!valid || saving}
              onClick={async () => {
                setSaving(true);
                try { await onSave(drafts); onClose(); }
                finally { setSaving(false); }
              }}
              style={{
                background: valid ? "var(--accent)" : "var(--bg-soft)",
                color: valid ? "#fff" : "var(--text-dim)",
                border: 0, borderRadius: 6, padding: "6px 14px",
                cursor: valid ? "pointer" : "not-allowed",
              }}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
```

- [ ] **Step 3: Verify type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Gradebook/CategoryPanel.tsx frontend/src/components/Gradebook/EditWeightsModal.tsx
git commit -m "feat(frontend): CategoryPanel + EditWeightsModal"
```

### Task 21: Build AssignmentList + AssignmentModal

**Files:**
- Create: `frontend/src/components/Gradebook/AssignmentList.tsx`
- Create: `frontend/src/components/Gradebook/AssignmentModal.tsx`

- [ ] **Step 1: Write AssignmentList**

Create `frontend/src/components/Gradebook/AssignmentList.tsx`:

```tsx
"use client";
import React from "react";
import type { GradedAssignment, GradeCategory } from "@/lib/types";

interface Props {
  assignments: GradedAssignment[];
  categories: GradeCategory[];
  onAdd: () => void;
  onEditGrade: (id: string, pointsEarned: number | null) => void;
  onEditFull: (a: GradedAssignment) => void;
  onSyncGradescope: () => void;  // currently a no-op placeholder
}

export function AssignmentList({
  assignments, categories, onAdd, onEditGrade, onEditFull, onSyncGradescope,
}: Props) {
  const catName = (id: string | null) =>
    categories.find((c) => c.id === id)?.name ?? "Uncategorized";

  return (
    <section
      style={{
        border: "1px solid var(--border)", borderRadius: 8,
        padding: 16, background: "var(--bg)",
      }}
    >
      <header
        style={{
          display: "flex", justifyContent: "space-between",
          alignItems: "baseline", marginBottom: 12,
        }}
      >
        <div className="label-micro">Assignments</div>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" onClick={onAdd}
            style={{
              fontSize: 12, padding: "4px 10px", border: "1px solid var(--border)",
              borderRadius: 6, background: "var(--bg)", cursor: "pointer",
            }}>
            + Add
          </button>
          <button type="button" onClick={onSyncGradescope} disabled
            title="Coming soon"
            style={{
              fontSize: 12, padding: "4px 10px", border: "1px solid var(--border)",
              borderRadius: 6, background: "var(--bg-soft)", color: "var(--text-dim)",
              cursor: "not-allowed",
            }}>
            Sync Gradescope
          </button>
        </div>
      </header>
      {assignments.length === 0 ? (
        <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
          No assignments yet.
        </p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {assignments.map((a) => (
            <li key={a.id}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "8px 0", borderBottom: "1px dashed var(--border)",
              }}>
              <button type="button" onClick={() => onEditFull(a)}
                style={{
                  flex: 1, textAlign: "left", background: "none",
                  border: 0, padding: 0, cursor: "pointer", color: "var(--text)",
                }}>
                <div style={{ fontWeight: 500 }}>{a.title}</div>
                <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                  {catName(a.category_id)}
                  {a.due_date ? ` · due ${a.due_date}` : ""}
                </div>
              </button>
              <input
                type="number"
                placeholder="—"
                defaultValue={a.points_earned ?? ""}
                onBlur={(e) => {
                  const v = e.target.value === "" ? null : Number(e.target.value);
                  if (v !== a.points_earned) onEditGrade(a.id, v);
                }}
                style={{
                  width: 60, padding: 4, textAlign: "right",
                  border: "1px solid var(--border)", borderRadius: 4,
                }}
              />
              <span style={{ color: "var(--text-dim)", fontSize: 12 }}>
                / {a.points_possible ?? "—"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Write AssignmentModal**

Create `frontend/src/components/Gradebook/AssignmentModal.tsx`:

```tsx
"use client";
import React from "react";
import { createPortal } from "react-dom";
import type { GradedAssignment, GradeCategory } from "@/lib/types";

export interface AssignmentDraft {
  title: string;
  category_id: string | null;
  points_possible: number | null;
  points_earned: number | null;
  due_date: string | null;
  assignment_type: string | null;
  notes: string | null;
}

interface Props {
  open: boolean;
  initial?: GradedAssignment | null;
  categories: GradeCategory[];
  onClose: () => void;
  onSave: (draft: AssignmentDraft) => Promise<void>;
  onDelete?: (() => Promise<void>) | null;
}

const TYPE_OPTIONS = ["homework", "exam", "quiz", "reading", "project", "other"];

export function AssignmentModal({
  open, initial, categories, onClose, onSave, onDelete,
}: Props) {
  const [mounted, setMounted] = React.useState(false);
  const [draft, setDraft] = React.useState<AssignmentDraft>({
    title: "",
    category_id: null,
    points_possible: null,
    points_earned: null,
    due_date: null,
    assignment_type: null,
    notes: null,
  });
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => setMounted(true), []);
  React.useEffect(() => {
    if (open) {
      setDraft({
        title: initial?.title ?? "",
        category_id: initial?.category_id ?? null,
        points_possible: initial?.points_possible ?? null,
        points_earned: initial?.points_earned ?? null,
        due_date: initial?.due_date ?? null,
        assignment_type: initial?.assignment_type ?? null,
        notes: initial?.notes ?? null,
      });
    }
  }, [open, initial]);

  if (!mounted || !open) return null;

  const valid = draft.title.trim() !== "" &&
    (draft.points_possible === null || draft.points_possible > 0);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg)", borderRadius: 12, padding: 20,
          minWidth: 420, maxWidth: 520,
        }}
      >
        <h3 style={{ margin: "0 0 12px" }}>
          {initial ? "Edit assignment" : "New assignment"}
        </h3>
        <div style={{ display: "grid", gap: 10 }}>
          <label>
            Title
            <input
              autoFocus
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
            />
          </label>
          <label>
            Category
            <select
              value={draft.category_id ?? ""}
              onChange={(e) =>
                setDraft({ ...draft, category_id: e.target.value || null })
              }
              style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
            >
              <option value="">— Uncategorized —</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            <label style={{ flex: 1 }}>
              Earned
              <input
                type="number"
                value={draft.points_earned ?? ""}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    points_earned: e.target.value === "" ? null : Number(e.target.value),
                  })
                }
                style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
              />
            </label>
            <label style={{ flex: 1 }}>
              Possible
              <input
                type="number"
                value={draft.points_possible ?? ""}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    points_possible: e.target.value === "" ? null : Number(e.target.value),
                  })
                }
                style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
              />
            </label>
          </div>
          <label>
            Due date
            <input
              type="date"
              value={draft.due_date ?? ""}
              onChange={(e) => setDraft({ ...draft, due_date: e.target.value || null })}
              style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
            />
          </label>
          <label>
            Type
            <select
              value={draft.assignment_type ?? ""}
              onChange={(e) =>
                setDraft({ ...draft, assignment_type: e.target.value || null })
              }
              style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
            >
              <option value="">—</option>
              {TYPE_OPTIONS.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </label>
          <label>
            Notes
            <textarea
              value={draft.notes ?? ""}
              onChange={(e) => setDraft({ ...draft, notes: e.target.value || null })}
              rows={2}
              style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
            />
          </label>
        </div>
        <div
          style={{
            marginTop: 16, paddingTop: 12, borderTop: "1px solid var(--border)",
            display: "flex", justifyContent: "space-between", alignItems: "center",
          }}
        >
          <div>
            {onDelete && initial && (
              <button
                type="button"
                onClick={async () => { await onDelete(); onClose(); }}
                style={{ color: "var(--err)" }}
              >
                Delete
              </button>
            )}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" onClick={onClose}>Cancel</button>
            <button
              type="button"
              disabled={!valid || saving}
              onClick={async () => {
                setSaving(true);
                try { await onSave(draft); onClose(); }
                finally { setSaving(false); }
              }}
              style={{
                background: valid ? "var(--accent)" : "var(--bg-soft)",
                color: valid ? "#fff" : "var(--text-dim)",
                border: 0, borderRadius: 6, padding: "6px 14px",
                cursor: valid ? "pointer" : "not-allowed",
              }}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
```

- [ ] **Step 3: Verify type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Gradebook/AssignmentList.tsx frontend/src/components/Gradebook/AssignmentModal.tsx
git commit -m "feat(frontend): AssignmentList + AssignmentModal"
```

### Task 22: Build LetterScaleEditor

**Files:**
- Create: `frontend/src/components/Gradebook/LetterScaleEditor.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/Gradebook/LetterScaleEditor.tsx`:

```tsx
"use client";
import React from "react";
import { createPortal } from "react-dom";
import type { LetterScaleTier } from "@/lib/types";

const DEFAULT_SCALE: LetterScaleTier[] = [
  { min: 93, letter: "A" }, { min: 90, letter: "A-" },
  { min: 87, letter: "B+" }, { min: 83, letter: "B" }, { min: 80, letter: "B-" },
  { min: 77, letter: "C+" }, { min: 73, letter: "C" }, { min: 70, letter: "C-" },
  { min: 67, letter: "D+" }, { min: 63, letter: "D" }, { min: 60, letter: "D-" },
  { min: 0, letter: "F" },
];

interface Props {
  open: boolean;
  initial: LetterScaleTier[] | null;  // null = using default
  onClose: () => void;
  onSave: (scale: LetterScaleTier[] | null) => Promise<void>;
}

export function LetterScaleEditor({ open, initial, onClose, onSave }: Props) {
  const [mounted, setMounted] = React.useState(false);
  const [tiers, setTiers] = React.useState<LetterScaleTier[]>(DEFAULT_SCALE);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => setMounted(true), []);
  React.useEffect(() => {
    if (open) setTiers(initial ?? DEFAULT_SCALE);
  }, [open, initial]);

  if (!mounted || !open) return null;

  const monotonic = tiers.every(
    (t, i) => i === 0 || t.min <= tiers[i - 1].min,
  );

  return createPortal(
    <div
      role="dialog" aria-modal="true"
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg)", borderRadius: 12, padding: 20,
          minWidth: 360, maxHeight: "80vh", overflow: "auto",
        }}
      >
        <h3 style={{ margin: "0 0 12px" }}>Letter scale</h3>
        <p style={{ fontSize: 12, color: "var(--text-dim)", margin: "0 0 12px" }}>
          Edit the floor percentage for each letter. Tiers must stay in descending order.
        </p>
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {tiers.map((t, i) => (
            <li key={i} style={{ display: "flex", gap: 8, marginBottom: 6 }}>
              <input
                value={t.letter}
                onChange={(e) =>
                  setTiers((arr) =>
                    arr.map((x, idx) => (idx === i ? { ...x, letter: e.target.value } : x)),
                  )
                }
                style={{ width: 48, padding: 4, border: "1px solid var(--border)", borderRadius: 4 }}
              />
              <input
                type="number"
                value={t.min}
                onChange={(e) =>
                  setTiers((arr) =>
                    arr.map((x, idx) =>
                      idx === i ? { ...x, min: Number(e.target.value) } : x,
                    ),
                  )
                }
                style={{ width: 70, padding: 4, border: "1px solid var(--border)", borderRadius: 4 }}
              />
              <span style={{ alignSelf: "center", color: "var(--text-dim)" }}>%+</span>
            </li>
          ))}
        </ul>
        <div
          style={{
            marginTop: 12, display: "flex",
            justifyContent: "space-between", alignItems: "center",
          }}
        >
          <button type="button" onClick={() => onSave(null)} disabled={saving}>
            Reset to default
          </button>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" onClick={onClose}>Cancel</button>
            <button
              type="button"
              disabled={!monotonic || saving}
              onClick={async () => {
                setSaving(true);
                try { await onSave(tiers); onClose(); }
                finally { setSaving(false); }
              }}
              style={{
                background: monotonic ? "var(--accent)" : "var(--bg-soft)",
                color: monotonic ? "#fff" : "var(--text-dim)",
                border: 0, borderRadius: 6, padding: "6px 14px",
                cursor: monotonic ? "pointer" : "not-allowed",
              }}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
        {!monotonic && (
          <p style={{ color: "var(--err)", fontSize: 12, marginTop: 6 }}>
            Tiers must be sorted descending by minimum.
          </p>
        )}
      </div>
    </div>,
    document.body,
  );
}
```

- [ ] **Step 2: Verify type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Gradebook/LetterScaleEditor.tsx
git commit -m "feat(frontend): LetterScaleEditor modal"
```

### Task 23: Build SyllabusUploadFlow

**Files:**
- Create: `frontend/src/components/Gradebook/SyllabusUploadFlow.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/Gradebook/SyllabusUploadFlow.tsx`:

```tsx
"use client";
import React from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import {
  uploadDocument, applySyllabus, getCourses,
} from "@/lib/api";
import { useToast } from "../ToastProvider";
import type { EnrolledCourse, ExtractedSyllabusCategory } from "@/lib/types";

interface Props {
  open: boolean;
  userId: string;
  onClose: () => void;
}

interface ExtractedAssignment {
  title: string;
  due_date: string | null;
  assignment_type: string | null;
  notes: string | null;
}

type Step = "pick-course" | "upload" | "review" | "saving";

export function SyllabusUploadFlow({ open, userId, onClose }: Props) {
  const router = useRouter();
  const toast = useToast();
  const [mounted, setMounted] = React.useState(false);
  const [step, setStep] = React.useState<Step>("pick-course");
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [courseId, setCourseId] = React.useState<string>("");
  const [docId, setDocId] = React.useState<string>("");
  const [categories, setCategories] = React.useState<ExtractedSyllabusCategory[]>([]);
  const [assignments, setAssignments] = React.useState<ExtractedAssignment[]>([]);

  React.useEffect(() => setMounted(true), []);
  React.useEffect(() => {
    if (!open) return;
    setStep("pick-course"); setCourseId(""); setDocId(""); setCategories([]); setAssignments([]);
    getCourses(userId).then((res) => setCourses(res.courses));
  }, [open, userId]);

  if (!mounted || !open) return null;

  const total = categories.reduce((s, c) => s + Number(c.weight || 0), 0);
  const weightsValid = categories.length === 0 || Math.abs(total - 100) <= 0.5;

  const handleFile = async (file: File) => {
    if (!courseId) {
      toast.error("Pick a course first");
      return;
    }
    setStep("upload");
    try {
      const res = await uploadDocument({
        userId,
        courseId,
        file,
        category: "syllabus",
      });
      setDocId(res.doc_id);
      setCategories(res.categories ?? []);
      setAssignments(res.assignments ?? []);
      setStep("review");
    } catch (err: any) {
      toast.error(`Upload failed: ${err.message}`);
      setStep("pick-course");
    }
  };

  const handleSave = async () => {
    setStep("saving");
    try {
      await applySyllabus({
        userId,
        courseId,
        docId,
        categories: categories.map((c, i) => ({
          name: c.name, weight: c.weight, sort_order: i,
        })),
        assignments,
      });
      toast.success("Syllabus applied");
      router.push(`/gradebook/${encodeURIComponent(courseId)}`);
      onClose();
    } catch (err: any) {
      toast.error(`Save failed: ${err.message}`);
      setStep("review");
    }
  };

  return createPortal(
    <div
      role="dialog" aria-modal="true"
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg)", borderRadius: 12, padding: 20,
          minWidth: 460, maxWidth: 640, maxHeight: "85vh", overflow: "auto",
        }}
      >
        <h3 style={{ margin: "0 0 12px" }}>Upload syllabus</h3>

        {step === "pick-course" && (
          <>
            <label>
              Course
              <select
                value={courseId}
                onChange={(e) => setCourseId(e.target.value)}
                style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
              >
                <option value="">— Pick a course —</option>
                {courses.map((c) => (
                  <option key={c.course_id} value={c.course_id}>
                    {c.course_code} · {c.course_name}
                  </option>
                ))}
              </select>
            </label>
            <input
              type="file"
              accept=".pdf,.docx,.pptx"
              disabled={!courseId}
              onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
              style={{ marginTop: 12 }}
            />
          </>
        )}

        {step === "upload" && (
          <p style={{ color: "var(--text-dim)" }}>Extracting syllabus…</p>
        )}

        {step === "review" && (
          <>
            <h4 style={{ marginTop: 0 }}>Categories</h4>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {categories.map((c, i) => (
                <li key={i} style={{ display: "flex", gap: 8, marginBottom: 6 }}>
                  <input
                    value={c.name}
                    onChange={(e) =>
                      setCategories((arr) =>
                        arr.map((x, idx) => (idx === i ? { ...x, name: e.target.value } : x)),
                      )
                    }
                    style={{ flex: 1, padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
                  />
                  <input
                    type="number"
                    value={c.weight}
                    onChange={(e) =>
                      setCategories((arr) =>
                        arr.map((x, idx) =>
                          idx === i ? { ...x, weight: Number(e.target.value) } : x,
                        ),
                      )
                    }
                    style={{ width: 70, padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
                  />
                  <span style={{ alignSelf: "center" }}>%</span>
                  <button type="button" onClick={() =>
                    setCategories((arr) => arr.filter((_, idx) => idx !== i))
                  }>✕</button>
                </li>
              ))}
            </ul>
            <button type="button" onClick={() =>
              setCategories((arr) => [...arr, { name: "", weight: 0 }])
            }>+ Add category</button>
            <p style={{ color: weightsValid ? "var(--accent)" : "var(--err)", fontSize: 12 }}>
              Total: {total.toFixed(1)}% {weightsValid ? "✓" : "(need 100%)"}
            </p>

            <h4>Assignments ({assignments.length})</h4>
            <ul style={{ listStyle: "none", margin: 0, padding: 0, maxHeight: 200, overflow: "auto" }}>
              {assignments.map((a, i) => (
                <li key={i} style={{ display: "flex", gap: 8, padding: "4px 0" }}>
                  <input
                    value={a.title}
                    onChange={(e) =>
                      setAssignments((arr) =>
                        arr.map((x, idx) => (idx === i ? { ...x, title: e.target.value } : x)),
                      )
                    }
                    style={{ flex: 1, padding: 4, border: "1px solid var(--border)", borderRadius: 4 }}
                  />
                  <input
                    type="date"
                    value={a.due_date ?? ""}
                    onChange={(e) =>
                      setAssignments((arr) =>
                        arr.map((x, idx) =>
                          idx === i ? { ...x, due_date: e.target.value || null } : x,
                        ),
                      )
                    }
                    style={{ padding: 4, border: "1px solid var(--border)", borderRadius: 4 }}
                  />
                  <button type="button" onClick={() =>
                    setAssignments((arr) => arr.filter((_, idx) => idx !== i))
                  }>✕</button>
                </li>
              ))}
            </ul>

            <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button type="button" onClick={onClose}>Cancel</button>
              <button
                type="button"
                disabled={!weightsValid}
                onClick={handleSave}
                style={{
                  background: weightsValid ? "var(--accent)" : "var(--bg-soft)",
                  color: weightsValid ? "#fff" : "var(--text-dim)",
                  border: 0, borderRadius: 6, padding: "6px 14px",
                }}
              >
                Save to gradebook
              </button>
            </div>
          </>
        )}

        {step === "saving" && (
          <p style={{ color: "var(--text-dim)" }}>Saving…</p>
        )}
      </div>
    </div>,
    document.body,
  );
}
```

- [ ] **Step 2: Confirm `uploadDocument` exists with the expected shape**

In `frontend/src/lib/api.ts` confirm there is an `uploadDocument(...)` helper. If its return type does not yet include `categories` and `assignments`, update it to include them:

```ts
export const uploadDocument = (input: {
  userId: string;
  courseId: string;
  file: File;
  category: string;
}) => {
  const fd = new FormData();
  fd.append('user_id', input.userId);
  fd.append('course_id', input.courseId);
  fd.append('category', input.category);
  fd.append('file', input.file);
  return fetch(`${API_URL}/api/documents/upload`, { method: 'POST', body: fd })
    .then(async (r) => {
      if (!r.ok) throw new Error(await r.text());
      return r.json() as Promise<{
        doc_id: string;
        category: string;
        summary: string;
        assignments: { title: string; due_date: string | null; assignment_type: string | null; notes: string | null }[];
        categories: { name: string; weight: number }[];
      }>;
    });
};
```

(If a different `uploadDocument` already exists, only widen its return type to include `categories`. Do not break existing callers.)

- [ ] **Step 3: Verify type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Gradebook/SyllabusUploadFlow.tsx frontend/src/lib/api.ts
git commit -m "feat(frontend): SyllabusUploadFlow"
```

### Task 24: Build the GradebookCourse screen

**Files:**
- Create: `frontend/src/components/screens/Gradebook/Course.tsx`
- Create: `frontend/src/app/(shell)/gradebook/[courseId]/page.tsx`

- [ ] **Step 1: Write the screen**

Create `frontend/src/components/screens/Gradebook/Course.tsx`:

```tsx
"use client";
import React from "react";
import Link from "next/link";
import { TopBar } from "../../TopBar";
import { useUser } from "@/context/UserContext";
import { useToast } from "../../ToastProvider";
import {
  getGradebookCourse, bulkUpdateCategories, deleteCategory,
  createGradedAssignment, updateGradedAssignment, deleteGradedAssignment,
  setLetterScale,
} from "@/lib/api";
import { CategoryPanel } from "../../Gradebook/CategoryPanel";
import { EditWeightsModal } from "../../Gradebook/EditWeightsModal";
import { AssignmentList } from "../../Gradebook/AssignmentList";
import { AssignmentModal, type AssignmentDraft } from "../../Gradebook/AssignmentModal";
import { LetterScaleEditor } from "../../Gradebook/LetterScaleEditor";
import type { GradebookCourse, GradedAssignment } from "@/lib/types";

interface Props { courseId: string; }

export function GradebookCourseScreen({ courseId }: Props) {
  const { userId, userReady } = useUser();
  const toast = useToast();

  const [data, setData] = React.useState<GradebookCourse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [editWeights, setEditWeights] = React.useState(false);
  const [editScale, setEditScale] = React.useState(false);
  const [assignModal, setAssignModal] = React.useState<{ open: boolean; initial: GradedAssignment | null }>({
    open: false, initial: null,
  });

  const reload = React.useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      setData(await getGradebookCourse(userId, courseId));
    } catch (err: any) {
      toast.error(`Couldn't load course: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [userId, courseId, toast]);

  React.useEffect(() => { reload(); }, [reload]);

  if (!userReady || !userId) return null;
  if (loading || !data) return <main style={{ padding: 32 }}>Loading…</main>;

  return (
    <>
      <TopBar
        breadcrumb={<Link href="/gradebook" style={{ color: "var(--text-dim)" }}>← Gradebook</Link>}
        title={`${data.course_code} · ${data.course_name}`}
        subtitle={data.semester}
        actions={
          <button
            type="button"
            onClick={() => setEditScale(true)}
            style={{
              fontSize: 12, padding: "4px 10px",
              border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)",
            }}
          >
            Letter scale
          </button>
        }
      />
      <main style={{ padding: 32 }}>
        <div
          style={{
            marginBottom: 16,
            display: "flex", justifyContent: "flex-end", alignItems: "baseline", gap: 8,
          }}
        >
          <span style={{ fontSize: 28, fontWeight: 700, color: "var(--accent)" }}>
            {data.letter ?? "—"}
          </span>
          <span style={{ color: "var(--text-dim)" }}>
            {data.percent !== null ? `${data.percent.toFixed(1)}%` : "No grades yet"}
          </span>
        </div>
        <CategoryPanel
          categories={data.categories}
          onEdit={() => setEditWeights(true)}
        />
        <AssignmentList
          assignments={data.assignments}
          categories={data.categories}
          onAdd={() => setAssignModal({ open: true, initial: null })}
          onEditFull={(a) => setAssignModal({ open: true, initial: a })}
          onSyncGradescope={() => toast.info("Gradescope integration coming soon")}
          onEditGrade={async (id, points) => {
            await updateGradedAssignment(userId, id, { points_earned: points });
            await reload();
          }}
        />
      </main>

      <EditWeightsModal
        open={editWeights}
        initial={data.categories}
        onClose={() => setEditWeights(false)}
        onSave={async (drafts) => {
          // Detect deletions: any existing id missing from drafts.
          const draftIds = new Set(drafts.map((d) => d.id).filter(Boolean) as string[]);
          for (const c of data.categories) {
            if (!draftIds.has(c.id)) await deleteCategory(userId, c.id);
          }
          await bulkUpdateCategories(userId, courseId, drafts);
          await reload();
        }}
      />

      <AssignmentModal
        open={assignModal.open}
        initial={assignModal.initial}
        categories={data.categories}
        onClose={() => setAssignModal({ open: false, initial: null })}
        onSave={async (draft: AssignmentDraft) => {
          if (assignModal.initial) {
            await updateGradedAssignment(userId, assignModal.initial.id, draft);
          } else {
            await createGradedAssignment(userId, courseId, draft);
          }
          await reload();
        }}
        onDelete={
          assignModal.initial
            ? async () => {
                await deleteGradedAssignment(userId, assignModal.initial!.id);
                await reload();
              }
            : null
        }
      />

      <LetterScaleEditor
        open={editScale}
        initial={data.letter_scale}
        onClose={() => setEditScale(false)}
        onSave={async (scale) => {
          await setLetterScale(userId, courseId, scale);
          await reload();
        }}
      />
    </>
  );
}
```

- [ ] **Step 2: Wire the page**

Create `frontend/src/app/(shell)/gradebook/[courseId]/page.tsx`:

```tsx
"use client";
import { use } from "react";
import { GradebookCourseScreen } from "@/components/screens/Gradebook/Course";

export default function CoursePage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  return <GradebookCourseScreen courseId={decodeURIComponent(courseId)} />;
}
```

- [ ] **Step 3: Verify type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/screens/Gradebook/Course.tsx frontend/src/app/\(shell\)/gradebook/\[courseId\]/page.tsx
git commit -m "feat(frontend): gradebook course detail page"
```

### Task 25: Wire the SyllabusUploadFlow into the landing page

**Files:**
- Modify: `frontend/src/components/screens/Gradebook/Landing.tsx`

- [ ] **Step 1: Add the upload modal trigger**

In `Landing.tsx`, replace the `<Link href={`/gradebook?upload=1`}>` "Upload syllabus" action with a button that opens a `<SyllabusUploadFlow />` modal. Add state:

```tsx
const [uploadOpen, setUploadOpen] = React.useState(false);
```

Replace the `actions` prop on `<TopBar>` with:

```tsx
actions={
  <button
    type="button"
    onClick={() => setUploadOpen(true)}
    style={{
      padding: "6px 12px",
      borderRadius: "var(--r-sm)",
      background: "var(--accent)",
      color: "#fff",
      fontSize: 13,
      border: 0,
      cursor: "pointer",
    }}
  >
    Upload syllabus
  </button>
}
```

At the bottom of the component (just before the closing `</>`), render:

```tsx
{userId && (
  <SyllabusUploadFlow
    open={uploadOpen}
    userId={userId}
    onClose={() => setUploadOpen(false)}
  />
)}
```

And add the import at the top:

```tsx
import { SyllabusUploadFlow } from "../../Gradebook/SyllabusUploadFlow";
```

- [ ] **Step 2: Verify type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/screens/Gradebook/Landing.tsx
git commit -m "feat(frontend): wire SyllabusUploadFlow into landing"
```

---

## Phase 9 — Manual smoke + final verification

### Task 26: End-to-end manual smoke

**Files:**
- (none changed)

- [ ] **Step 1: Run backend tests**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Smoke the empty state**

Start backend (`python main.py`) and frontend (`npm run dev`). Sign in.
- Navigate to `/gradebook`. The semester chips load; the grid is empty (or shows enrolled courses with "No grades yet").
- Click a course card → lands on `/gradebook/<id>` with empty Categories and Assignments panels.

- [ ] **Step 4: Smoke the manual flow**

On a course detail page:
- "Edit weights" → add `Exams 60%` and `P-Sets 40%` → save. Total chip shows "100% ✓".
- "+ Add" → create "Midterm 1", category Exams, points 100 / 90 → save.
- The current grade displays "90.0% A−". The Exams row shows 90.0%.
- Inline-edit the points_earned to 80 → grade refreshes to "80.0% B−".
- "Letter scale" → change A to 85 → save. Grade becomes "B" (80 < 85).
- Delete the assignment via its modal → grade returns to "—".

- [ ] **Step 5: Smoke the syllabus flow**

From `/gradebook` landing, click "Upload syllabus":
- Pick a course → upload a real syllabus PDF.
- Review screen shows extracted categories with weights and an assignments list.
- Edit one category name, set total to 100, save.
- Lands on the course detail page with categories pre-filled and assignments inserted (uncategorized).

- [ ] **Step 6: Smoke the Gradescope placeholder**

On a course detail page, click "Sync Gradescope". Confirm the button is disabled and a toast/title says "coming soon".

- [ ] **Step 7: Final commit (none expected)**

```bash
git status
```

Expected: clean. If there are stray edits from smoke testing, address them before declaring done.

---

## Self-review notes

- Spec coverage:
  - Schema, categories, weights, grades, syllabus apply, letter scale, multi-semester, Gradescope placeholder — covered by Tasks 1, 6, 8–12, 13–15, 18–25.
  - Calendar interop: assignments table is shared. Existing Calendar reads (`/api/calendar/all/{user_id}`) keep working since added columns are nullable.
- Type consistency:
  - Backend `category_grade` returns 0–1 float; `current_grade` returns 0–100; UI `c.category_grade * 100` matches.
  - `CategoryItem.id` is optional (null for new); used uniformly in routes and frontend payloads.
- Out of scope, intentionally missing: drops/curves/extra-credit categories, what-if calculator, live Gradescope sync.
