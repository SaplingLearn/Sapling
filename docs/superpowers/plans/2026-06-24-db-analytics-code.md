# db/analytics-code — slice plan (2026-06-24)

Base branch: `db/academics-code` (has academics spine + `services/academics.py` + migrations 0019–0027).
Branch: `db/analytics-code`.

## Context: what academics already did vs. what's left

The analytics re-key (migration `0022_analytics.sql`) renamed the class-analytics
tables and dropped the last free-text `semester` columns:

- `course_concept_stats` → `offering_concept_stats` (PK `offering_id` → `course_offerings`)
- `course_summary` → `offering_summary` (PK `offering_id`)

The academics slice (PR2 on this base) **already**:

- Rewired `services/course_context_service.py` to key entirely on `offering_id`,
  read `enrollments`/`course_offerings`/`courses`, and upsert the new
  `offering_*` tables. (0 refs to the old analytics tables remain there.)
- Reshaped `courses` into the **abstract catalog** (`id, school_id, course_code,
  course_name, department, credits, description, …`) via `0020_academics_split.sql`.
  The old offering-shaped `courses` (with `user_id`, `semester`, `course_name`
  per enrollment) became `course_offerings`; per-user links became `enrollments`
  (`user_id`, `offering_id`).

Verified residuals (grep over `routes/` + `services/`, excluding tests):
- **No** `table("course_concept_stats")` / `table("course_summary")` calls remain
  anywhere. (The two grep hits in `course_context_service.py` are a response dict
  key `"course_summary"` and a stale comment — not table calls, out of scope.)

## What's LEFT — the holdout: `routes/social.py`

One offending line:

```python
# routes/social.py  (get_students, GET /api/social/students)
courses_rows = table("courses").select("user_id,course_name")   # line 430
...
courses_by_user[c["user_id"]].append(c["course_name"])          # line 435
```

After `0020`, the abstract `courses` table has **no** `user_id` column and no
per-user rows — `course_name` is a single catalog value per abstract course.
This query is reading the *old* offering-shaped `courses`. It must be repointed
to resolve each user's courses through the enrollment chain:

`enrollments(user_id) → course_offerings(course_id) → courses(course_name)`

The canonical PostgREST shape for this (already used in `routes/profile.py:183`
and asserted in `tests/test_shared_course_context.py`) is an embedded select:

```python
table("enrollments").select("user_id,course_offerings(courses(course_name))")
```

Each enrollment row then yields `row["course_offerings"]["courses"]["course_name"]`.
This is per-offering, so a student in two offerings of the same abstract course
would list it twice — the existing code already `sorted()`s the list but does not
dedup; to preserve the "lightweight profile" intent and avoid term-driven
duplicates, dedup per user before sorting.

Everything else in `social.py` is unrelated to analytics/offerings:
`rooms`, `room_members`, `room_messages`, `room_reactions`, `room_activity`,
`users`, `graph_nodes` — all unchanged, untouched.

## File-by-file change map

- `backend/routes/social.py` — `get_students`: replace the
  `table("courses").select("user_id,course_name")` read with an
  `table("enrollments")` embedded read through `course_offerings(courses(...))`;
  build `courses_by_user` from the joined rows; dedup per user. Preserve the
  exact `/api/social/students` response shape (`students[].courses` = sorted list
  of course-name strings).

No other files in scope require edits (residual grep is clean).

## Test list (new, in `tests/test_social_students.py`)

TDD — written first, must fail against the old `table("courses")` read, pass after:

1. `test_students_courses_resolved_via_enrollments` — enrollments embed returns
   course names per user; response groups them under the right `user_id`.
2. `test_students_courses_deduped_and_sorted` — same abstract course across two
   offerings appears once; list is sorted.
3. `test_students_no_enrollments_yields_empty_courses` — user with no enrollments
   gets `courses: []` (and still appears in the list).
4. `test_students_response_shape_preserved` — top-level `students[]` items keep
   `user_id,name,streak,courses,stats,top_concepts`.

Patch `routes.social.table` with a MagicMock-per-table factory (mirrors
`tests/test_social_messages.py` + `tests/test_shared_course_context.py`); the
endpoint requires a session, so patch `get_session_user_id` via the existing
auth test pattern / dependency override.

## Out of scope (do NOT touch)

- `services/course_context_service.py` (already done; read-only reference).
- `routes/study_guide.py`, `onboarding.py`, `flashcards.py`, `learn.py`,
  `documents.py`, `services/graph_service.py` — their `table("courses")` calls
  already key on the abstract `id` (correct).
- `services/academics.py` (locked).
- graph / gradebook / study / identity / ops files.
