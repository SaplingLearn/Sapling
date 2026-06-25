# `db/gradebook-code` Implementation Plan (epic slice — gradebook)

> **For agentic workers:** code-only slice. The schema already landed (migrations 0019–0027,
> incl. `0021_gradebook.sql`). This slice rewires the gradebook application code onto the new
> enrollment-keyed shape and adds bell-curve + drop-lowest + GPA. Branch: `db/gradebook-code`
> based on `db/academics-code` (carries the academics spine + `services/academics.py`).

**Goal:** Make the gradebook semester-aware on the new schema. Categories and assignments key on
`enrollment_id` (not `user_id`+`course_id`). The public API keeps the abstract `course_id` plus
the existing `semester` query param. Add bell-curve (raw vs curved) and drop-lowest to the
weighted-score computation, and add per-semester + cumulative (credit-weighted) GPA.

## Locked product contract

- **API boundary keeps the abstract `course_id`.** Routes still receive `course_id`; the
  `GET /summary` route still receives `semester`. Per-course routes accept an optional
  `semester` query param (default = current term).
- **Term/semester is a real second axis.** `terms` is the source of truth (`GET /api/semesters`
  exists). A `semester` value is a term **label** (e.g. `"Spring 2026"`); we map it to a
  `term_id` via `terms.label`, falling back to treating the value as a `term_id` directly.
- **Resolution:** `(course_id, term)` → the user's **enrollment** = intersect
  `services.academics.user_offering_ids_for_course(user_id, course_id)` with the offerings in
  that term. The gradebook keys `gradebook_categories.enrollment_id` /
  `assignments.enrollment_id` on that enrollment. The knowledge graph stays on the abstract
  `course_id` (out of this slice).
- **Encryption:** `points_possible` / `points_earned` stay 🔒 **TEXT** (numeric semantics);
  `notes` stays 🔒 TEXT. `encrypt_if_present` at write, `decrypt_numeric` / `decrypt_if_present`
  at read.
- **Gradescope is out of scope** — just don't break the `gradescope_assignment_id` column.

## Schema facts (read off `db/migrations/0021_gradebook.sql`)

- **`enrollments`** gained: `curve_mode TEXT NOT NULL DEFAULT 'raw' CHECK IN ('raw','curved')`,
  `curve_avg_target NUMERIC`, `curve_sd_delta NUMERIC`. Keeps `id, user_id, offering_id, color,
  nickname, enrolled_at, letter_scale (JSONB), syllabus_doc_id`.
- **`gradebook_categories`** (was `course_categories`): `id, enrollment_id→enrollments (CASCADE),
  name, weight NUMERIC, sort_order INTEGER DEFAULT 0, drop_lowest INTEGER NOT NULL DEFAULT 0
  CHECK (>=0), created_at, updated_at`. **No `user_id`/`course_id` columns.**
- **`assignments`** (recreated): `id, enrollment_id→enrollments (nullable; CASCADE),
  category_id→gradebook_categories (SET NULL), title, due_date DATE,
  assignment_type TEXT CHECK IN ('homework','exam','reading','project','quiz','other'),
  notes 🔒, points_possible 🔒 TEXT, points_earned 🔒 TEXT,
  source TEXT NOT NULL DEFAULT 'manual' CHECK IN ('manual','syllabus'), google_event_id,
  gradescope_assignment_id, curve_class_mean NUMERIC, curve_class_sd NUMERIC,
  curve_avg_target NUMERIC, curve_sd_delta NUMERIC, created_at, updated_at`.
  **No `user_id`/`course_id` columns.** Curve stats are plaintext NUMERIC (class stats, not
  student-identifying).
- **`courses`** (abstract catalog) carries `credits INTEGER` — the GPA credit weight.

### Exact CHECK enum value sets (read off 0021)

- `enrollments.curve_mode ∈ {'raw','curved'}`
- `assignments.assignment_type ∈ {'homework','exam','reading','project','quiz','other'}`
- `assignments.source ∈ {'manual','syllabus'}`
- `gradebook_categories.drop_lowest >= 0`

## Resolver (use `services.academics`, do not edit it)

- `current_term()` → current term row (date-derived).
- `list_terms()` → all terms.
- `user_offering_ids_for_course(user_id, course_id)` → offerings of the abstract course the user
  is enrolled in.
- `term_for_offering(offering_id)` → term row (for the semester label in responses).
- `resolve_offering(course_id, term_id=None, *, create=False)` — not needed for reads here.

New local helper in `routes/gradebook.py`:
`_resolve_enrollment(user_id, course_id, semester=None) -> dict | None` — maps `semester`→term_id
(via `terms.label`), lists the user's offerings of the course, picks the offering whose
`term_id` matches the resolved term (or the only/most-recent offering when no term given),
then loads the matching `enrollments` row. Returns the enrollment dict (with `curve_*`,
`letter_scale`, `offering_id`) or `None`.

## File-by-file change map (current → new)

### `services/gradebook_service.py`
Pure math, no DB. Current: `category_grade`, `current_grade`, `letter_for`,
`DEFAULT_LETTER_SCALE`. Changes:
- **`category_grade(items, drop_lowest=0)`** — when `drop_lowest > 0`, drop the N graded items
  with the lowest per-item ratio (`earned/possible`) before summing. Items with
  `possible <= 0` or missing earned still skip. Document the formula.
- **`apply_curve(raw_percent, *, class_mean, class_sd, avg_target, sd_delta)`** — new pure fn.
  Linear z-score rescale: `curved = avg_target + (raw - class_mean) * (new_sd / class_sd)` where
  `new_sd = class_sd + sd_delta`. Falls back to `raw_percent` when `class_sd` is missing/0 or
  `avg_target` is None. Clamp to `[0, 100]`. Document the formula.
- **`current_grade(categories, assignments, *, curve_mode='raw', curve_avg_target=None,
  curve_sd_delta=None)`** — pass each category's `drop_lowest` into `category_grade`; when
  `curve_mode == 'curved'`, apply `apply_curve` to the final weighted percent using the
  enrollment-level avg target/sd delta against the **class mean/sd derived from the assignments'
  per-assignment `curve_class_mean`/`curve_class_sd`** when present, else enrollment targets only.
  (Enrollment-level curve is the primary path; per-assignment curve stats are carried but the
  weighted-percent curve uses the enrollment policy. Documented as an assumption.)
- **`gpa_points(percent, scale=None)`** — new: map a percent → 4.0-scale grade points using a
  standard letter→points table (A=4.0, A-=3.7, B+=3.3, …, F=0.0), reusing `letter_for`.
- **`weighted_gpa(course_grades)`** — new: credit-weighted mean of grade points across a list of
  `{"grade_points": x, "credits": c}`; ignores entries with `grade_points is None`. Returns the
  cumulative/transcript GPA.

### `routes/gradebook.py`
Replace **all** `user_courses` / `course_categories` references and the `user_id`+`course_id`
keying with enrollment keying.
- `_user_owns_course` → `_resolve_enrollment(user_id, course_id, semester)` returning the
  enrollment row (or None). Ownership = a resolvable enrollment.
- `_user_owns_category(user_id, category_id)` → look up `gradebook_categories` by id, then verify
  its `enrollment_id` belongs to the user (load enrollment, check `user_id`).
- `_user_owns_assignment(user_id, assignment_id)` → look up `assignments` by id, verify its
  `enrollment_id` belongs to the user.
- **`GET /summary`** — list the user's enrollments (optionally filtered to the `semester` term),
  join `course_offerings` → `courses` for code/name + `terms` for the label, load
  `gradebook_categories`/`assignments` by `enrollment_id`, compute curved/dropped grade + letter,
  return per-course rows **plus** a `gpa` field (term GPA across the listed courses).
- **`GET /courses/{course_id}`** — accept optional `semester`; resolve enrollment; load cats +
  assigns by `enrollment_id`; apply drop-lowest + curve; return categories (with `drop_lowest`
  and per-category grade), assignments, percent, letter, `letter_scale`, `curve_mode`, semester
  label.
- **categories CRUD** — insert/update/delete on `gradebook_categories` keyed on `enrollment_id`
  (resolved from `course_id`+`semester`). Carry `drop_lowest` through create/bulk-update.
- **assignments CRUD** — `CreateAssignmentBody`/`UpdateAssignmentBody` resolve to an enrollment;
  insert/update `assignments` with `enrollment_id` (no `user_id`/`course_id`). Keep
  decrypt-on-return.
- **`POST /syllabus/apply`** — resolve enrollment; wipe + replace `gradebook_categories` by
  `enrollment_id`; insert assignments keyed on `enrollment_id`; stamp `enrollments.syllabus_doc_id`.
- **`PATCH /courses/{course_id}/scale`** — update `enrollments.letter_scale` for the resolved
  enrollment.
- **NEW curve route** `PATCH /courses/{course_id}/curve` — set
  `enrollments.curve_mode`/`curve_avg_target`/`curve_sd_delta`.
- **NEW GPA route** `GET /gpa` — cumulative/transcript GPA: across all the user's offerings of
  all enrolled courses, credit-weighted (`courses.credits`), with per-course and overall numbers.

### `models/__init__.py` (gradebook section)
- `CreateCategoryBody`: add optional `course_id`-less? No — `course_id` stays in the path; add
  `semester: Optional[str]` and `drop_lowest: int = Field(default=0, ge=0)`.
- `CategoryItem`: add `drop_lowest: int = Field(default=0, ge=0)`.
- `BulkUpdateCategoriesBody`: add `semester: Optional[str]`.
- `CreateAssignmentBody` / `UpdateAssignmentBody`: add `semester: Optional[str]`; constrain
  `assignment_type: Optional[Literal['homework','exam','reading','project','quiz','other']]`.
- `SetLetterScaleBody` / `SyllabusApplyBody`: add `semester: Optional[str]`.
- New `SetCurveBody`: `user_id, semester: Optional[str], curve_mode: Literal['raw','curved'],
  curve_avg_target: Optional[float], curve_sd_delta: Optional[float]`.

### `tests/test_gradebook_routes.py`
Rewrite the mocked rows to the enrollment-keyed shape (`enrollments` rows with `offering_id`,
`course_offerings`/`courses`/`terms` rows, `gradebook_categories`/`assignments` keyed on
`enrollment_id`). Keep coverage of: summary, course detail, 404 when not enrolled, categories
CRUD + weight validation, assignments CRUD + `gt=0` 422, letter scale set/clear/non-monotonic,
syllabus apply (replace, weight reject, unknown course, foreign doc). Add:
- curve route sets enrollment curve fields,
- GET /gpa returns credit-weighted cumulative GPA.

## Formulas

**Drop-lowest** (per category): given graded items with ratio `r_i = earned_i / possible_i`
(`possible_i > 0`), drop the `drop_lowest` items with the smallest `r_i`, then
`category_grade = Σ earned_kept / Σ possible_kept`. If `drop_lowest >=` graded count, the
category has no contributing items → grade `None` (drops out of the weighted sum, weight
renormalized — same as today).

**Bell curve** (linear z-rescale, applied to the final weighted percent when
`curve_mode='curved'`):
```
new_sd = class_sd + sd_delta          # sd_delta shifts spread (e.g. -5 tightens)
curved = avg_target + (raw - class_mean) * (new_sd / class_sd)
curved = clamp(curved, 0, 100)
```
Falls back to `raw` when `class_sd` is falsy/0 or `avg_target` is None. `class_mean`/`class_sd`
default from per-assignment `curve_class_mean`/`curve_class_sd` averages when present; otherwise
the curve degenerates to a recenter on `avg_target` is skipped (returns raw). Assumption
documented: enrollment-level `curve_avg_target`/`curve_sd_delta` are the policy; class stats come
from assignment rows.

**GPA:**
- Letter→points: A=4.0, A-=3.7, B+=3.3, B=3.0, B-=2.7, C+=2.3, C=2.0, C-=1.7, D+=1.3, D=1.0,
  D-=0.7, F=0.0 (default scale; custom letter_scale maps by letter).
- Per-course grade points = `gpa_points(curved_percent, letter_scale)`.
- **Per-semester GPA** = credit-weighted mean across the one term's courses:
  `Σ(points_i * credits_i) / Σ credits_i` (courses with no grade omitted; credits default 1 when
  null).
- **Cumulative/transcript GPA** = same credit-weighted mean across **all** the user's offerings
  of all enrolled courses, across terms.

## Hand-computed GPA fixture (asserted exactly)
Two courses, current term:
- **CS161** (credits 3): one category Exams weight 100, one graded assignment 90/100 → 90% →
  letter `A-` → 3.7 points.
- **MATH200** (credits 4): one category HW weight 100, one graded assignment 80/100 → 80% →
  letter `B-` → 2.7 points.

Term GPA = `(3.7*3 + 2.7*4) / (3+4) = (11.1 + 10.8) / 7 = 21.9 / 7 = 3.12857… ≈ 3.13`.
The fixture asserts `pytest.approx(3.1285714, rel=1e-4)`.

A second fixture exercises drop-lowest + curve to assert the weighted-percent path
(hand-computed in the test).

## Out of scope
- Gradescope sync (no gradescope code on this branch). Don't break `gradescope_assignment_id` /
  `gradescope_course_links`.
- `services/academics.py`, `graph_service.py`, `course_context_service.py` (do not edit).
- Graph / analytics / study / identity files.
