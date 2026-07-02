# Calendar / assignments rewire to the enrollment-keyed schema — design

**Date:** 2026-06-28
**Status:** Approved (pending spec review) → next: implementation plan
**Owner:** backend

## Problem

The DB modular redesign (migration `0021_gradebook.sql`) did
`DROP TABLE assignments CASCADE` and recreated `assignments` as the
**enrollment-keyed gradebook table**: columns are
`id, enrollment_id, category_id, title, due_date, assignment_type, notes,
points_possible, points_earned, source, google_event_id, gradescope_*, curve_*`.
There is **no `user_id`, no `course_id`, and no `assignments→courses` relationship**.

`routes/calendar.py` and `services/calendar_service.py` were never rewired and
still speak the pre-redesign schema (`select user_id,course_id,courses!left(...)`,
`filter user_id=…`, `insert {user_id, course_id}`). Every such call now returns a
PostgREST `400`, which the route does not catch → unhandled → **HTTP 500**. The
migration itself flagged this as deferred: *"(was assignments.\*) → … See issues
filed for the code rewire."*

### Evidence (staging, reproduced against the live DB for the real user)

| Endpoint | Result |
|---|---|
| `/api/users` | OK |
| `/api/auth/me` | OK |
| `/api/graph/{user}` (+ `/recommendations`, `/courses`) | OK |
| **`/api/calendar/upcoming/{user}`** | **400 from PostgREST on `assignments`** |
| `/api/learn/sessions/{user}` | OK |
| `/api/profile/{user}/achievements` | OK |

The dashboard issues these in a `Promise.all`, so the single calendar 500 tanks
the whole dashboard load. **Blast radius is the calendar/assignments domain
only**; all other redesigned domains are healthy.

## Decisions (approved)

1. **Every assignment is tied to a course.** No standalone/course-less items, so
   no schema migration — assignments key on `enrollment_id`, reached via
   `enrollment → offering → course`.
2. **Auto-create the enrollment on write.** A manual or syllabus save for a
   course the user is not yet enrolled in resolves/creates the current-term
   offering and an enrollment, so saves never silently drop.
3. **Full-domain rewire** (read + write + sync/export + syllabus-save + tests),
   not just a read-path band-aid.

## Design

Mirror the already-migrated `routes/gradebook.py` helpers rather than invent a
parallel pattern or rely on fragile nested PostgREST embeds (the `academics`
module explicitly avoids embedded-filter syntax). The HTTP request/response
shapes are **unchanged**, so the frontend needs no edits.

### 1. Shared resolver — `services/academics.py`

```
enrollment_id_for(user_id, course_id, *, create=False) -> str | None
```

Resolve `(user, abstract course)` → the user's current-term `enrollment_id`,
reusing `resolve_offering` / `user_offering_ids_for_course` / `current_term`.
With `create=True`: ensure an offering (`resolve_offering(course_id, create=True)`)
and an enrollment row exist (insert if missing), then return its id. Enrollment
resolution living in `academics.py` matches the CLAUDE.md convention.

### 2. Read path — `get_upcoming`, `get_all`, `suggest_study_blocks`

1. Fetch the user's enrollments: `table("enrollments").select("id,offering_id",
   filters={"user_id": f"eq.{user_id}"})` → `enrollment_id`s + offering map.
2. **No enrollments → return `{"assignments": []}`** (this is what unblocks the
   dashboard for new users).
3. `table("assignments").select("id,enrollment_id,title,due_date,assignment_type,
   notes,google_event_id,source", filters={"enrollment_id": f"in.({ids})", …})`
   (+ `due_date >= today` for `upcoming`), `order=due_date.asc`.
4. Decrypt `notes` (`decrypt_if_present`). Attach `course_id` (abstract),
   `course_code`, `course_name` per assignment by mapping
   `enrollment_id → offering_id → _course_meta(offering_id)` (cache per offering).
5. Response keeps the existing shape, echoing `user_id` (the path param) and the
   abstract `course_id`.

### 3. Write path — `save_assignments`, `services/calendar_service.insert_new_assignments`, syllabus-save callers

- A `course_id` is **required** on write (consistent with decision 1). Both
  syllabus-save call sites in `documents.py` already attach `course_id` per
  assignment dict.
- For each assignment: `enrollment_id = academics.enrollment_id_for(user_id,
  course_id, create=True)`; insert `{enrollment_id, title, due_date,
  assignment_type, notes: encrypt_if_present(...), google_event_id, source}`.
- `source` = `'manual'` for `POST /save`, `'syllabus'` for syllabus extraction.
- **Dedup rewire:** `calendar_service.load_existing_assignment_keys` currently
  queries `assignments` by `user_id`; it must dedup against the assignments in
  the user's enrollment set (resolve the user's `enrollment_id`s first, then
  query by `enrollment_id in (...)`). Dedup key stays trimmed-title + calendar-day.

### 4. Ownership scoping — `update_assignment`, `delete_assignment`, `sync_to_google`, `export_to_google`

Replace `user_id` filters with enrollment-ownership checks: the assignment's
`enrollment_id` must belong to one of the caller's enrollments. Concretely,
resolve the user's `enrollment_id`s once and require the target assignment's
`enrollment_id` to be in that set before read/update/delete/push. This preserves
the existing defense-in-depth guarantees (#123) under the new key.
`oauth_tokens` (Google credentials) is **unchanged** — still keyed by `user_id`.

### 5. Encryption

`assignments.notes` is column-encrypted: `encrypt_if_present` at write,
`decrypt_if_present` at read (both already imported in `calendar.py`). Points
columns are not touched by the calendar feature.

## Files touched

- `services/academics.py` — add `enrollment_id_for(...)`.
- `routes/calendar.py` — `get_upcoming`, `get_all`, `save_assignments`,
  `suggest_study_blocks`, `update_assignment`, `delete_assignment`,
  `sync_to_google`, `export_to_google`.
- `services/calendar_service.py` — `insert_new_assignments`,
  `load_existing_assignment_keys`, `save_assignments_to_db` (thread `source`).
- `routes/documents.py` — confirm the two syllabus-save call sites pass
  `course_id` (they do); thread `source='syllabus'`.
- `backend/tests/` — rewrite calendar tests against the enrollment-keyed schema.

## Testing

TDD per project conventions (`backend/tests/`, mock Supabase in `conftest.py`).
Cover: read with/without enrollments (empty-list path), read course-meta mapping,
write resolves an existing enrollment, write auto-creates when none exists, dedup
across the enrollment set, and ownership scoping rejects another user's
assignment id. Update any existing calendar test asserting the old schema.

## Out of scope

- No schema migration (decision 1).
- No frontend changes (request/response shapes preserved).
- Gradebook route (already migrated), other domains (verified healthy).
- Standalone/course-less assignments (explicitly excluded).

## Verification / rollout

- Backend test suite green (`python -m pytest tests/ -q`).
- Re-run the staging reproduction harness: `/api/calendar/upcoming/{user}` returns
  `200 {"assignments": []}` for the new user; dashboard `Promise.all` resolves.
- Manual: add a course → upload a syllabus → assignment appears in the calendar.
