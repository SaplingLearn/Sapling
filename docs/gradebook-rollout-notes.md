# Gradebook — Rollout Notes

**Date:** 2026-05-02
**Branch:** `feat/gradebook` (merged into `main`)
**Spec:** [`docs/superpowers/specs/2026-05-02-gradebook-design.md`](superpowers/specs/2026-05-02-gradebook-design.md)
**Plan:** [`docs/superpowers/plans/2026-05-02-gradebook.md`](superpowers/plans/2026-05-02-gradebook.md)

---

## What shipped

All 25 implementation tasks (Phases 0-8 of the plan) completed across 27 commits.

### Backend

- **New table** `course_categories` (per-user, per-course grading buckets with weights)
- **Extended `assignments`**: new columns `category_id`, `points_possible`, `points_earned`, `source`; `due_date` now nullable
- **Extended `user_courses`**: `letter_scale` (JSONB) and `syllabus_doc_id` (FK to `documents`)
- **New service** `services/gradebook_service.py` — pure-functional grade math (`category_grade`, `current_grade`, `letter_for`, default scale)
- **New routes** in `routes/gradebook.py` exposing 10 endpoints under `/api/gradebook/*`, all guarded by `require_self`
- **Syllabus extraction** prompt + `_process_document` now emit a `categories` array alongside assignments

### Frontend

- **New types** in `lib/types.ts`: `GradebookSummary`, `GradebookCourse`, `GradeCategory`, `GradedAssignment`, `LetterScaleTier`, `ExtractedSyllabusCategory`
- **New API helpers** in `lib/api.ts`: `getGradebookSummary`, `getGradebookCourse`, `createCategory`, `bulkUpdateCategories`, `deleteCategory`, `createGradedAssignment`, `updateGradedAssignment`, `deleteGradedAssignment`, `setLetterScale`, `applySyllabus`, `uploadSyllabus`
- **New components** under `components/Gradebook/`: `SemesterChips`, `CategoryPanel`, `EditWeightsModal`, `AssignmentList`, `AssignmentModal`, `LetterScaleEditor`, `SyllabusUploadFlow`
- **New screens**: `Landing` at `/gradebook`, `Course` at `/gradebook/[courseId]`

### DB migrations

- `backend/db/migration_drop_legacy_grade_tables.sql` — drops three empty parallel tables (`grade_items`, `grade_categories`, `grade_scales`) that were created out-of-band and overlapped with the new design
- `backend/db/migration_gradebook.sql` — applies the new schema

Both applied to the live Supabase project. Row counts preserved (`assignments=31`, `user_courses=13`, `documents=11`); legacy tables were empty before drop.

---

## Verification status

| Check | Status |
|---|---|
| Backend tests | **382 passing**, 1 pre-existing failure (`test_graph_service::test_skips_self_edges` — fails on `main` too, unrelated) |
| Frontend `tsc --noEmit` | Clean for new code; pre-existing `flashcardParsers` errors persist |
| Live DB schema | Migrations applied, structure verified |
| **Manual UI smoke (Task 26)** | **NOT done at merge time** — first browser run still pending |

---

## Known soft spots

1. **`getCourses` API doesn't return `semester`.** The `EnrolledCourse` type lacks the field, so `GradebookLanding` falls back to a hardcoded `["Spring 2026"]` chip. Works today because every course in the DB defaults to that semester. **Real fix:** surface `semester` from `/api/graph/<user>/courses`.

2. **Dead URL parameter.** The "Upload syllabus" button used to link to `/gradebook?upload=1`; it's now a state-driven modal. Nothing reads the query param. Deep-linking to "open upload modal" is gone. Cosmetic.

3. **No DB-level CHECK constraints on `weight` or `source`.** Application-layer Pydantic validation is the only gate. A direct DB insert (e.g. via Supabase Studio) bypassing the API could store invalid data.

4. **Code-quality review skipped on Phases 2-8.** Only Task 1 (the migration) got a formal two-stage review (spec + code quality). Phases 2-8 had spec compliance verified but full quality review was deferred for speed. Subtle issues may be lurking — find them via runtime behavior or a follow-on pass.

5. **`apply_syllabus` route depends on the `user_courses ↔ courses` join shape.** It ends by calling `get_course(...)` to return the refreshed payload, which expects the join. Production data has it; mocks needed enrichment to pass. Fragile if the join behavior changes upstream.

6. **Concurrent parallel commits in Wave 2 succeeded by luck.** Four subagents pushed to the same branch concurrently and didn't collide because the file paths were disjoint. Don't rely on this if the next batch overlaps.

---

## What's next

- **Manual smoke (Task 26 of the plan):** empty state → manual flow (add categories → add assignment → see grade → letter-scale override) → syllabus upload review/apply. Walk through the UI and confirm.
- **Follow-up: surface `semester` in `getCourses`** so multi-semester chips actually populate.
- **Deferred from spec:** drop-lowest, curves, what-if calculator, grade sharing/export, live Gradescope sync, multiple grading schemes per course.
