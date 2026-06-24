# `db/academics-code` Implementation Plan (epic slice PR2)

> **For agentic workers:** code-only slice. The schema already landed in PR #264 (migrations
> 0019–0027 on `epic/db-modular-redesign`). This slice rewires the application code onto the
> new `courses` (abstract) / `course_offerings` / `terms` / `enrollments` schema. Branch:
> `db/academics-code` → PR into `epic/db-modular-redesign`. The epic may stay WIP-red for
> other domains; this slice must leave the **academics spine** green.

**Goal:** Make the backend run against the academics split — enrollment keyed on an offering,
the knowledge graph keyed on the abstract course, and the whole app term/semester-aware —
without changing the public API's `course_id` contract.

## Locked product contract (decided with the user 2026-06-24)

- **API boundary keeps the abstract `course_id`.** No section/instructor anywhere in the
  contract; those stay carried columns on `course_offerings`, defaulted/ignored.
- **Semester/term is the real second axis.** `terms` is the source of truth. Add
  `GET /api/semesters`. `get_courses` starts returning each course's term label.
- **Enrollment = (user, offering)**, offering = (course, term, `section = NULL`). On enroll
  with no term given, resolve to the **current term** (date-derived) and **create the offering
  if the catalog lacks it** — new enrollments land in the real current semester, not legacy
  `Spring 2026`.
- **Knowledge graph stays on the abstract `course_id`** (cumulative across terms); resolve
  `enrollment.offering_id → course_offerings.course_id` to reach it.
- **`gradebook.py` is NOT in this slice** — it goes whole to `db/gradebook-code` (with curve +
  drop-lowest, #266), built on this slice's enrollment-by-semester resolver.
- **`course_context_service` (analytics) IS in this slice** — the migrated
  `offering_concept_stats`/`offering_summary` tables force offering-keying, which is inseparable
  from the enrollment spine. `db/analytics-code` (PR4) therefore shrinks to `social.py` + any
  aggregation refinement.
- **`school` is retired** (free-text `courses.school` dropped; `schools` table unpopulated). It
  surfaces as `""`/None until a follow-up links `school_id`. Flag as a frontend/seed follow-up.

## Schema facts (already landed)

- `courses` (abstract): `id, school_id, course_code, course_name, department, credits, description`.
- `course_offerings` (was old `courses`): `id, course_id→courses, term_id→terms, section,
  instructor_name, meeting_times, location, syllabus_url`. Lost `course_name/department/credits/
  description/semester/school`.
- `terms`: `id, term, year, label ('Spring 2026'), start_date, end_date, sort_key`.
  "current term" = `current_date BETWEEN start_date AND end_date`.
- `enrollments` (was `user_courses`): `id, user_id, offering_id→course_offerings, color,
  nickname, enrolled_at` (+ curve_*/syllabus_doc_id from other slices). `UNIQUE(user_id, offering_id)`.
- `table()` API: `.select(cols, filters=, order=, limit=)` with PostgREST operators in filter
  values (`eq.`, `in.(a,b)`, `lte.`, `gte.`, `ilike.`); `.insert(dict)`; `.update(dict, filters=)`;
  `.delete(filters)`; `.upsert(dict, on_conflict=)`. Hand-build text ids with `uuid.uuid4()`
  (existing convention).

## Foundation — `services/academics.py` (NEW, build first)

Pure functions over `table()`, easily mockable (each test patches `services.academics.table`):

- `current_term(today=None) -> dict | None` — term whose date range contains today; **fallback**
  to the latest term by `sort_key.desc` so a date outside all ranges still resolves.
- `list_terms() -> list[dict]` — all terms, `sort_key.desc` (for `GET /api/semesters`).
- `resolve_offering(course_id, term_id=None, *, create=False) -> str | None` — offering id for
  (course, term); term defaults to `current_term()`. If none and `create`, insert
  `{id, course_id, term_id}` (NULL section) and return the new id. If none and not `create`,
  fall back to any existing offering of that course.
- `offering_course_id(offering_id) -> str | None` — abstract course id for an offering.
- `user_offering_ids_for_course(user_id, course_id) -> list[str]` — two-step (offerings of the
  course, then the user's enrollments intersected) to avoid fragile embedded filters.
- `term_for_offering(offering_id) -> dict | None` — the offering's term row (for labels).

## Work groups (independent files — parallelizable after the helper lands)

**A. `services/graph_service.py`** + `tests/test_graph_service.py`
- `_user_enrolled_courses` / `get_courses`: query `enrollments` with nested
  `course_offerings!inner(course_id,courses!inner(course_code,course_name,department),terms!inner(label))`;
  **reshape** to the legacy flat shape consumers expect — `course_id` = the *abstract*
  `course_offerings.course_id`, `courses` = `{course_code, course_name, department, school:""}`,
  plus new `offering_id` and `term` (label). `get_courses` counts nodes by abstract `course_id`.
- `add_course(user_id, course_id)`: verify abstract course in `courses`; `offering_id =
  resolve_offering(course_id, create=True)`; dedupe enrollment by `(user_id, offering_id)`;
  insert `{id, user_id, offering_id, color, nickname}`; `update_course_context(offering_id)`.
- `update_course_color`/`update_course_nickname`/`delete_course(user_id, course_id)`: resolve
  `user_offering_ids_for_course`; update/delete enrollments filtered `offering_id=in.(…)`;
  refresh context per offering.
- `apply_graph_update` / `delete_node` analytics refresh: for each touched **abstract**
  course_id, `update_course_context(off)` for each `user_offering_ids_for_course(user_id, cid)`.
- Graph node writes stay on abstract `course_id` (unchanged).

**B. `services/course_context_service.py` + `agents/tools/graph_read.py`** +
`tests/test_shared_course_context.py`, `tests/test_graph_read_tools.py`
- `update_course_context(offering_id)`: enrolled users via `enrollments` filtered
  `offering_id`; resolve `offering_course_id` for `graph_nodes` (abstract) + `term_for_offering`
  for the label; upsert `offering_concept_stats` (`on_conflict="offering_id,concept_name"`, no
  semester) and `offering_summary` (`on_conflict="offering_id"`). Empty-enrollment purge keys on
  `offering_id`.
- `get_course_context(offering_id)`: read `offering_summary`/`offering_concept_stats` by
  `offering_id`; drop the `semester` filter/field; preserve the return dict shape otherwise.
- `graph_read.read_misconceptions_for_course`: read `offering_concept_stats` filtered
  `offering_id` (param stays named `course_id` at the tool boundary but is an offering id from
  deps). `read_concepts_for_user` stays on abstract `course_id` (graph) — unchanged.

**C. `routes/onboarding.py` + `routes/graph.py` + `routes/academics.py` (NEW) + `main.py` +
`models/__init__.py`** + `tests/test_onboarding_routes.py`
- `onboarding.search_courses`: already hits abstract `courses` — keep; it returns `id`
  (abstract). No change beyond confirming columns exist.
- `onboarding.save_onboarding_profile` enroll loop: for each abstract `course_id`, `offering_id
  = resolve_offering(course_id, create=True)`; dedupe by `(user_id, offering_id)`; insert
  `enrollments{id,user_id,offering_id}`.
- `routes/graph.py`: unchanged call signatures (`get_courses`/`add_course` take abstract
  `course_id`); responses now carry `term`.
- `routes/academics.py`: `GET /semesters` → `{"semesters": list_terms()}`. Mount in `main.py`
  at `/api` (yields `/api/semesters`). Update `models` docstrings (`AddCourseBody` etc.) to say
  abstract course id.

**D. `routes/profile.py` + `routes/learn.py`** + `tests/test_learn_routes.py`
- `profile.get_public_profile`: `enrollments` join `course_offerings(courses(school_id))`;
  school is `""`/None for now.
- `learn._get_course_id_for_topic`: resolve via `enrollments` join `course_offerings(course_id,
  courses(course_code,course_name))`; **return the abstract `course_id`** (graph + session key).
  `_get_course_info(course_id)` reads the abstract `courses` row (already keyed by abstract id —
  works once the resolver returns abstract ids). `get_course_context` call may pass the abstract
  id and degrade to `{}` until a later study slice wires offering context into sessions — leave a
  `# TODO(db/study-code)` note; do not break the session flow.

## Test/verify

- Per group: `cd backend && venv/bin/python -m pytest tests/<file> -q`.
- Whole-slice gate: `venv/bin/python -m pytest tests/test_onboarding_routes.py
  tests/test_learn_routes.py tests/test_graph_service.py tests/test_shared_course_context.py
  tests/test_graph_read_tools.py tests/test_academics.py -q` green; `ruff check .` clean.
- Acceptance: enroll → `get_courses` returns the course with its term; a fresh enroll with no
  current-term offering creates one; `GET /api/semesters` lists terms; no `Spring 2026` literal
  remains in academics code; graph still keys on abstract `course_id`.

## Out of scope (other slices, leave broken-but-untouched)

`gradebook.py`/`gradebook_service.py` (PR3) · `graph_nodes`/`graph_edges` integrity + mastery
events (PR5) · `documents.py`/`notes.py`/`quiz.py`/`study_guide.py`/`flashcards.py` (PR7) ·
`social.py` (PR4) · identity profile fields (PR6). These keep their current `course_id` calls;
they degrade gracefully (empty reads / no-op writes) until their slice lands.
