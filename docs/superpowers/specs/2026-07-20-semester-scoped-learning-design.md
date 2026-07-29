# Semester-scoped learning + Courses & Semesters hub — design

**Date:** 2026-07-20
**Status:** Approved (pending spec review) → next: implementation plan
**Owner:** full-stack (backend + frontend)

## Problem

A student's enrolled courses span multiple semesters (terms), but the learning
surfaces give no way to organize or scope by semester:

- The knowledge graph is keyed on the **abstract `course_id`** and is deliberately
  cumulative across terms (`graph_nodes.course_id`; `graph_service.get_courses`
  counts nodes per `course_id`). `GET /api/graph/{user_id}` returns **every**
  term's nodes mixed into one graph.
- `ManageCoursesModal` lists enrolled courses as one flat list
  (`ManageCoursesModal.tsx:109`) with no hint that terms exist.
- Tree / Learn / Study / Quiz all read `getCourses(userId)` (all terms) with no
  term filter, so previous-semester courses are technically reachable but
  undifferentiated.

The user wants: (1) a way to switch the active semester and scope the learning
experience to it, (2) enrolled courses organized by semester, (3) a rule that a
course already taken in any (incl. previous) semester cannot be added again, and
(4) a placeholder "Personal learning" entry marked "Coming soon".

## Decisions (approved)

1. **No retakes.** Each abstract course lives in exactly one semester for a user.
   Re-adding a course already enrolled in any term is blocked. This makes each
   course's graph effectively single-semester already.
2. **Path A — filter by semester, no schema change.** Because of decision 1, we do
   NOT re-key `graph_nodes` from `course_id` → `offering_id` and do NOT migrate
   data. Semester scoping is a **read-time filter** on the existing graph. Purely
   additive; omitting the filter preserves today's behavior.
   - Explicitly out of scope: the earlier "separate graph per retake" idea. With
     retakes blocked, each course has exactly one graph, scoped to its one term.
3. **Settings-only hub.** The redesigned `ManageCoursesModal` ("Courses &
   Semesters") is the single home for both **managing** courses and **switching**
   the active study semester. No separate always-visible switcher for now (can be
   added later if switching feels buried).
4. **Active semester scopes Tree / Learn / Study / Quiz AND the Dashboard graph.**
   The Dashboard graph respects the active semester so the setting has a visible
   effect on the home screen.

## Design

### 1. Backend — term-scoped reads (`services/academics.py`, `routes/graph.py`)

No data model changes. Add one resolver primitive and thread an optional
`semester` param through the learning reads.

**New helper — `services/academics.py`:**

```
user_course_ids_for_term(user_id: str, term_id: str) -> set[str]
```

Returns the abstract `course_id`s the user is enrolled in for that term:
`enrollments (user_id) → offering_id → course_offerings (term_id) → course_id`.
Multi-step reads (no PostgREST embedded filters), matching this module's house
style; short-circuit on empty sets. **Not cached** — enrollments mutate.

A term **label → term_id** mapping is already implemented as
`routes/gradebook.py::_term_id_for_semester`; extract/reuse an equivalent so the
`semester` query value (a term label, e.g. "Spring 2026") resolves consistently.

**Endpoint changes** (all optional param; absent = all terms, unchanged behavior):

- `GET /api/graph/{user_id}` (`routes/graph.py:24`, `get_user_graph`) gains
  `semester: str | None = Query(None)`. When present: resolve `term_id`, compute
  `allowed = user_course_ids_for_term(user_id, term_id)`, return only nodes whose
  `course_id ∈ allowed`, filter edges to surviving node ids, and **recompute
  `stats` over the filtered set** (mastered/learning/struggling/unexplored/total).
- `GET /api/graph/{user_id}/recommendations` (`routes/graph.py:30`) gains the same
  `semester` param and restricts recommendations to that term's courses.
- Session listing and quiz-exam listing that feed the learning surfaces take the
  same optional `semester` and filter to the term's courses. Quiz already keys on
  `offering_id`, so this is threading the param through, not re-keying.

**No-retake guard — `create_course` (`routes/graph.py:63`) / `graph_service.add_course`:**
Before enrolling, reject if the user already has **any** offering of that abstract
course (any term). Return a structured error (e.g. `already_existed=True` with a
message naming the term), so the rule holds even if the UI is bypassed. Today
`add_course` only checks the current-term offering; broaden to all terms.

### 2. Frontend — "Courses & Semesters" hub (`ManageCoursesModal.tsx`)

Redesign the modal into the single management + switching hub:

- **Term tabs / selector** at the top listing the terms the user is enrolled in
  (derived from `getCourses`' per-course `term` label), newest first. Selecting a
  term sets the **active semester** (see §3).
- **Enrolled courses grouped by semester** — replace the flat `courses.map`
  (`ManageCoursesModal.tsx:109`) with per-term groups (term header + its courses).
- **Add-a-course** section: mechanics unchanged (`addCourse` →
  `resolve_offering`), plus the re-add rule (§4).
- **"Personal learning"** row at the bottom: a **disabled** button with a
  **"Coming soon"** caption beneath it. Non-functional placeholder.
- **Entry point** stays the existing dashboard "Manage" button
  (`Dashboard.tsx:435` sidebar `CoursesKey`, `Dashboard.tsx:737` legacy panel);
  relabel it "Courses & Semesters".

### 3. Active-semester context + persistence

- A lightweight **`useActiveSemester` hook + context**, same shape as the existing
  `useLayoutPref`, backed by `localStorage` (per user), **defaulting to the current
  term**. Value is a term label (matching the `semester` query param).
- **Tree, Learn, Study, Quiz, and the Dashboard graph** read the active semester
  and pass it as `semester` to the scoped endpoints (§1), showing only that term's
  courses/graph. Selecting a term in the hub updates the context; all readers
  react.
- Default resolution: if the persisted value is missing/not among the user's
  enrolled terms, fall back to the current term (or the most-recent enrolled term).

### 4. No-retake rule + messaging (`ManageCoursesModal.tsx`)

- Enrollment dedup is already by `course_id` across all terms
  (`enrolledIds`, `ManageCoursesModal.tsx:65`). Make it **explicit**: a course
  taken in any semester shows a disabled **"Already taken · <term>"** in the
  add-search results, replacing the generic "Enrolled" (`:157`). The term label
  comes from the matching enrolled course.
- Backend enforces the same rule defensively (§1 guard), so a bypassed UI can't
  create a duplicate-across-terms enrollment.

### 5. Testing

Backend (pytest, mock Supabase/Gemini per `tests/conftest.py`):

- `user_course_ids_for_term` resolves the correct course set for a term and
  returns empty for a term the user has no enrollment in.
- `GET /api/graph/{user}?semester=` returns only that term's nodes/edges and
  recomputes stats; omitting `semester` is unchanged (all terms).
- `create_course` / `add_course` rejects enrolling in a course the user already
  has in a different term, with a clear error.

Frontend:

- Hub groups enrolled courses by term and lists term tabs.
- `useActiveSemester` persists across reloads and defaults to the current term.
- Selecting a term scopes the course list; scoped readers pass the `semester` param.
- A prior-term course renders the disabled "Already taken · <term>" state.

## Non-goals

- Re-keying the graph to `offering_id` or any data migration (Path B).
- Supporting retakes with separate graphs.
- A separate always-visible semester switcher outside the hub.
- Implementing "Personal learning" (placeholder only).
- Changing Gradebook's existing `SemesterChips` (it keeps its own semester UI).
