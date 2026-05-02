# Gradebook — Design Spec

**Date:** 2026-05-02
**Status:** Approved (brainstorm phase complete)
**Owner:** saplinglearn

## Summary

A user-driven gradebook under the Tools nav section. Users track grades across the semester per enrolled course: define grading categories with weights (manually or by uploading a syllabus), add graded items with points possible/earned, and see a computed current grade and letter for each course. Multi-semester aware. Includes a placeholder button for future Gradescope integration.

## Goals

- Track current grade per course, per semester.
- Manual entry of categories, weights, assignments, and grades.
- Syllabus upload that auto-extracts categories with weights and assignments (user reviews before saving).
- Multi-semester support without nested chrome.
- Reuse the existing `assignments` table so a single record drives both Calendar and Gradebook.

## Non-goals (v1)

- Drop-lowest, curves, extra-credit categories
- "What-if" grade calculator
- Grade sharing or export
- Multiple grading schemes per course
- Live Gradescope integration (button is a no-op placeholder)

## User-facing decisions

| Decision | Choice | Rationale |
|---|---|---|
| Data relationship | One unified `assignments` table extended with grade fields | User mental model: an assignment is one thing, not two. Calendar and Gradebook read the same row. |
| Syllabus extraction | Extract assignments + categories with weights; user manually maps assignments to categories | Categories+weights are usually written explicitly; per-item categorization is error-prone. |
| Page layout | Landing dashboard (semester chips + course grid) → drill into course detail page | No second sidebar (the main `SideNav` is the only nav). Scales across semesters via chip selector. |
| Current grade calc | Earned-only — average of graded items per category, weighted across categories with at least one graded item | Matches the natural intuition of "where I stand right now." |
| Letter grade | Standard scale by default (A 93+, A− 90+, B+ 87+ …), per-(user, course) override via `user_courses.letter_scale` JSONB | Each enrollment can have its own scale; null = default. |

## Architecture

### Data model

Migration: `backend/db/migration_gradebook.sql`

**Extend `assignments`:**

```sql
ALTER TABLE assignments
  ADD COLUMN category_id      TEXT REFERENCES course_categories(id),
  ADD COLUMN points_possible  NUMERIC,
  ADD COLUMN points_earned    NUMERIC,
  ADD COLUMN source           TEXT DEFAULT 'manual';  -- 'manual' | 'syllabus' | 'gradescope'

ALTER TABLE assignments
  ALTER COLUMN due_date DROP NOT NULL;  -- gradebook items may not have a due date
```

`title`, `due_date`, `course_id`, `assignment_type`, `notes` already exist. `assignment_type` (homework/exam/quiz/…) stays — coarse type used for calendar icons. `category_id` is the per-course gradebook bucket and is independent. `due_date` becomes nullable so manually-created graded items don't have to invent one.

**New table `course_categories`** (per user, per course):

```sql
CREATE TABLE course_categories (
  id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
  user_id     TEXT NOT NULL REFERENCES users(id),
  course_id   TEXT NOT NULL REFERENCES courses(id),
  name        TEXT NOT NULL,
  weight      NUMERIC NOT NULL,        -- 0–100
  sort_order  INTEGER DEFAULT 0,
  created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_course_categories_user_course ON course_categories(user_id, course_id);
```

**Extend `user_courses`:**

```sql
ALTER TABLE user_courses
  ADD COLUMN letter_scale     JSONB,                        -- null = default scale
  ADD COLUMN syllabus_doc_id  TEXT REFERENCES documents(id);
```

**Current grade calculation (server-side):**

For each category with at least one graded item:
- `category_grade = sum(points_earned) / sum(points_possible)` across graded items in the category, expressed 0–1.

Then:
- `total_weight = sum(weight)` over contributing categories.
- `current_grade = (sum(category_grade × weight) / total_weight) × 100`, expressed 0–100.

Letter is mapped from `current_grade` (0–100) using the course's `letter_scale` (or default if null). Returned to the client as `{ percent: number, letter: string | null }`.

### Backend routes

New file: `backend/routes/gradebook.py`. All routes guarded by `require_self`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/gradebook/summary?semester=Spring%202026` | All enrolled courses for the semester with computed current grade + letter. |
| GET | `/api/gradebook/courses/{course_id}` | Categories (with weights + per-category grade), assignments (with grades), letter scale, computed overall. |
| POST | `/api/gradebook/courses/{course_id}/categories` | Create one category. Body: `{name, weight}`. |
| PATCH | `/api/gradebook/courses/{course_id}/categories` | Bulk update weights/names/sort_order in one call. Validates total weight = 100 (±0.5). |
| DELETE | `/api/gradebook/categories/{id}` | Delete; orphaned assignments get `category_id = null`. |
| POST | `/api/gradebook/assignments` | Create. Body: `{course_id, title, category_id?, points_possible?, points_earned?, due_date?, assignment_type?, notes?}`. |
| PATCH | `/api/gradebook/assignments/{id}` | Update any field, including `points_earned`. |
| DELETE | `/api/gradebook/assignments/{id}` | Delete. |
| PATCH | `/api/gradebook/courses/{course_id}/scale` | Set/clear `letter_scale` on `user_courses`. |
| POST | `/api/gradebook/syllabus/apply` | Apply extracted categories + assignments after user review. Body: `{course_id, doc_id, categories, assignments}`. Idempotent. |

**Reused route (modified):** `POST /api/documents` upload — when `category=syllabus`, the response now also includes `categories: [{name, weight}]` extracted from the prompt. Persisted only when the user calls `/syllabus/apply`.

### Syllabus extraction prompt

`backend/prompts/syllabus_extraction.txt` — output JSON gains a `categories` field:

```json
{
  "categories": [
    { "name": "Exams", "weight": 40 },
    { "name": "Problem Sets", "weight": 30 },
    { "name": "Final Project", "weight": 30 }
  ],
  "assignments": [ /* unchanged shape */ ],
  "warnings": [...]
}
```

Prompt instructions:
- Return `categories: []` if no clear grading scheme is present.
- Weights pass through verbatim from the syllabus; do not normalize.
- Do **not** map assignments to categories — user assigns each manually after import.

### Frontend

**Pages** (`frontend/src/app/(shell)/gradebook/`):

- `page.tsx` — landing (`/gradebook`). Renders `<GradebookLanding />`.
- `[courseId]/page.tsx` — course detail (`/gradebook/[courseId]`). Renders `<GradebookCourse courseId={...} />`.

**Components:**

| Component | Path | Purpose |
|---|---|---|
| `GradebookLanding` | `components/screens/Gradebook/Landing.tsx` | TopBar + semester chips + course-card grid + "Upload syllabus" button. |
| `GradebookCourse` | `components/screens/Gradebook/Course.tsx` | Course header, `<CategoryPanel />`, `<AssignmentList />`, "Sync Gradescope" placeholder button (disabled). |
| `CategoryPanel` | `components/Gradebook/CategoryPanel.tsx` | Lists categories with weight + per-category grade. "Edit weights" opens `<EditWeightsModal />`. |
| `EditWeightsModal` | `components/Gradebook/EditWeightsModal.tsx` | Add/remove/reorder/rename categories, edit weights. Live "Total: 100% ✓" indicator. Save disabled if total ≠ 100. |
| `AssignmentList` | `components/Gradebook/AssignmentList.tsx` | Items grouped by category, sortable. Inline edit on `points_earned`. "+ Add" opens `<AssignmentModal />`. |
| `AssignmentModal` | `components/Gradebook/AssignmentModal.tsx` | Create/edit form: title, category (dropdown), points possible, points earned, due date, notes. |
| `SyllabusUploadFlow` | `components/Gradebook/SyllabusUploadFlow.tsx` | Pick course → upload PDF → review extracted categories+assignments → apply. |
| `SemesterChips` | `components/Gradebook/SemesterChips.tsx` | Backed by distinct semesters across `user_courses`. "+ Add" opens existing course-search flow scoped to the new semester. |
| `LetterScaleEditor` | `components/Gradebook/LetterScaleEditor.tsx` | Per-course override in a settings popover on the course detail page. |

**API client** (`frontend/src/lib/api.ts`): typed wrappers for every route — `getGradebookSummary`, `getGradebookCourse`, `createCategory`, `bulkUpdateCategories`, `deleteCategory`, `createAssignment`, `updateAssignment`, `deleteAssignment`, `setLetterScale`, `applySyllabus`.

**Shared types** (`frontend/src/lib/types.ts`): `GradebookSummary`, `GradebookCourse`, `GradeCategory`, `GradedAssignment`, `LetterScale`.

### Layout

- Landing: TopBar (title "Gradebook", action "Upload syllabus") → semester chip row (default = current `Spring 2026`, "+ Add" opens course-search flow scoped to the new semester) → course card grid (each card: code, name, current grade, letter, "X/Y graded").
- Detail: back link → course header (code, name, semester, current grade + letter) → `<CategoryPanel />` (weights + per-category grade, "Edit weights" button) → `<AssignmentList />` ("+ Add" + disabled "Sync Gradescope").

### Syllabus apply flow

1. **Pick course** — current semester's enrollments. If none, link to onboarding to enroll.
2. **Upload PDF** — uses existing `/api/documents` upload, awaits processing.
3. **Review** — editable lists of extracted categories (with weights) and assignments. If existing categories already exist for the course, show "This will replace your existing categories" warning.
4. **Save** → `POST /api/gradebook/syllabus/apply` → redirect to `/gradebook/[courseId]`.

Apply behavior:
- Wipes existing `course_categories` for `(user_id, course_id)`. Inserts new ones.
- Inserts assignments with `source='syllabus'`, `category_id=null`, `points_possible=null`. User assigns categories and fills points later.
- Deduplicates assignments by `(course_id, title, COALESCE(due_date, ''))` so re-importing the same syllabus is a no-op.
- Sets `user_courses.syllabus_doc_id = doc_id`.

## Validation & error handling

**Backend** (Pydantic + route logic):
- Each weight `0 ≤ w ≤ 100`; total per course = 100 (±0.5).
- `points_possible > 0`; `points_earned ≥ 0`; `points_earned > points_possible` allowed (extra credit).
- Category delete reassigns its assignments to `category_id = null`.
- `letter_scale` override must be monotonic (A ≥ A− ≥ B+ ≥ …) and bounded `[0, 100]`.

**Frontend:**
- Weight total ≠ 100 → save disabled with inline "Total: 97% (need 100%)".
- Network failures surface via existing `<ToastProvider />`.
- If syllabus extraction fails or returns empty, the user can skip review and go straight to an empty course detail page.

## Testing

- `backend/tests/test_gradebook_routes.py` — CRUD on categories/assignments, weight-sum validation, current-grade calc with mixed graded/ungraded items, letter-scale override edge cases, syllabus apply (replace categories, dedupe assignments).
- Extend `backend/tests/test_documents_routes.py` and any existing syllabus-extraction test — cover syllabi with and without an explicit grading scheme.
- Frontend: no automated harness on this branch; verify with `npx tsc --noEmit` and manual smoke.

## Open items deferred to follow-on specs

- Drop-lowest / curves / extra-credit categories
- What-if grade calculator
- Grade sharing or export
- Live Gradescope integration (replaces the placeholder button)
- Multiple grading schemes per course
