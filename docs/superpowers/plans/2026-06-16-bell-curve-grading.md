# Bell Curve Grading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bell curve grade adjustments (per-assignment and/or final grade) with a Raw ↔ Curved toggle that flows through the composition bar, grade projector, and assignment rows.

**Architecture:** Pure `apply_curve` math function added to the backend service and mirrored as a frontend utility; curve parameters stored as plain floats on assignments and user_courses; the Raw/Curved toggle is persisted per-course and drives a `curvedAssignments` derivation in Course.tsx that feeds all existing visualization components unchanged.

**Tech Stack:** Python (FastAPI, Pydantic), React/TypeScript, Supabase (PostgREST via httpx), existing Sapling CSS tokens.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| **Supabase dashboard** | Schema | Add curve columns to `assignments` and `user_courses` |
| `backend/services/gradebook_service.py` | Modify | Add `apply_curve`, extend `category_grade` + `current_grade` |
| `backend/models/__init__.py` | Modify | Add curve fields to `UpdateAssignmentBody`, `CreateAssignmentBody`; add `CurveSettingsBody` |
| `backend/routes/gradebook.py` | Modify | Allow curve fields in update route; add `PATCH /courses/{course_id}/curve`; return curve data from `get_course` |
| `backend/tests/test_gradebook_service.py` | Modify | Add `apply_curve` tests and curved `category_grade`/`current_grade` tests |
| `frontend/src/lib/types.ts` | Modify | Add curve fields to `GradedAssignment` and `GradebookCourse` |
| `frontend/src/components/Gradebook/curveUtils.ts` | **Create** | Pure `applyCurve`, `applyCurveToAssignment`, `applyFinalCurve` functions |
| `frontend/src/lib/api.ts` | Modify | Add `setCurveSettings`; extend `updateGradedAssignment` + `createGradedAssignment` to pass curve fields |
| `frontend/src/components/Gradebook/AssignmentModal.tsx` | Modify | Add collapsible Bell Curve section with class mean/SD inputs |
| `frontend/src/components/screens/Gradebook/Course.tsx` | Modify | Add Raw/Curved toggle; derive `curvedAssignments`; apply final curve; pass to bar + projector |
| `frontend/src/components/Gradebook/AssignmentList.tsx` | Modify | Show curved score + raw in muted text when curved toggle is on |

---

## Task 0: Database Schema — Add Curve Columns

**Files:** Supabase dashboard (SQL editor)

- [ ] **Step 1: Run this SQL in your Supabase project's SQL editor**

```sql
-- Curve parameters on individual assignments (all nullable — curve is optional)
ALTER TABLE assignments
  ADD COLUMN IF NOT EXISTS curve_class_mean  float,
  ADD COLUMN IF NOT EXISTS curve_class_sd    float,
  ADD COLUMN IF NOT EXISTS curve_avg_target  float,
  ADD COLUMN IF NOT EXISTS curve_sd_delta    float;

-- Curve policy and mode on the enrollment row
ALTER TABLE user_courses
  ADD COLUMN IF NOT EXISTS curve_mode        text    DEFAULT 'raw',
  ADD COLUMN IF NOT EXISTS curve_avg_target  float,
  ADD COLUMN IF NOT EXISTS curve_sd_delta    float,
  ADD COLUMN IF NOT EXISTS curve_final_mean  float,
  ADD COLUMN IF NOT EXISTS curve_final_sd    float;
```

- [ ] **Step 2: Verify columns exist**

In the Supabase Table Editor, open `assignments` and `user_courses` and confirm the new columns appear.

---

## Task 1: Backend — `apply_curve` pure function + tests

**Files:**
- Modify: `backend/services/gradebook_service.py`
- Modify: `backend/tests/test_gradebook_service.py`

- [ ] **Step 1: Write failing tests first**

Open `backend/tests/test_gradebook_service.py`. Add at the top of the file (after existing imports):

```python
from services.gradebook_service import apply_curve
```

Add these test cases:

```python
class TestApplyCurve:
    def test_at_mean_returns_avg_target(self):
        # Score exactly at the class mean → maps to avg_target
        result = apply_curve(0.68, class_mean=0.68, class_sd=0.12,
                             avg_target=0.83, sd_delta=0.10)
        assert abs(result - 0.83) < 1e-9

    def test_one_sd_above_mean(self):
        # z=1.0 → avg_target + 1*sd_delta
        result = apply_curve(0.80, class_mean=0.68, class_sd=0.12,
                             avg_target=0.83, sd_delta=0.10)
        assert abs(result - 0.93) < 1e-9

    def test_one_sd_below_mean(self):
        # z=-1.0 → avg_target - sd_delta
        result = apply_curve(0.56, class_mean=0.68, class_sd=0.12,
                             avg_target=0.83, sd_delta=0.10)
        assert abs(result - 0.73) < 1e-9

    def test_clamp_above_100(self):
        # Very high score should clamp to 1.0
        result = apply_curve(1.0, class_mean=0.50, class_sd=0.05,
                             avg_target=0.83, sd_delta=0.10)
        assert result == 1.0

    def test_clamp_below_0(self):
        # Very low score should clamp to 0.0
        result = apply_curve(0.0, class_mean=0.80, class_sd=0.05,
                             avg_target=0.50, sd_delta=0.15)
        assert result == 0.0

    def test_sd_zero_returns_raw_score(self):
        # Entire class same score → skip curve, return raw
        result = apply_curve(0.75, class_mean=0.75, class_sd=0.0,
                             avg_target=0.83, sd_delta=0.10)
        assert result == 0.75
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_gradebook_service.py::TestApplyCurve -v
```

Expected: `ImportError: cannot import name 'apply_curve'`

- [ ] **Step 3: Implement `apply_curve` in `gradebook_service.py`**

Add after `_coerce_drop` (around line 52):

```python
def apply_curve(
    score_pct: float,
    class_mean: float,
    class_sd: float,
    avg_target: float,
    sd_delta: float,
) -> float:
    """Apply a bell curve adjustment to a single score percentage (0–1).

    Maps the student's score to a curved grade based on how many standard
    deviations above/below the class mean they are.

        z             = (score - class_mean) / class_sd
        curved_grade  = avg_target + z * sd_delta

    Clamps to [0, 1]. Returns score_pct unchanged if class_sd == 0
    (prevents division by zero when all students scored identically).
    """
    if class_sd <= 0:
        return score_pct
    z = (score_pct - class_mean) / class_sd
    return max(0.0, min(1.0, avg_target + z * sd_delta))
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd backend && python -m pytest tests/test_gradebook_service.py::TestApplyCurve -v
```

Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/services/gradebook_service.py backend/tests/test_gradebook_service.py
git commit -m "feat(gradebook): add apply_curve pure function with tests"
```

---

## Task 2: Backend — Extend `category_grade` and `current_grade` for curve mode

**Files:**
- Modify: `backend/services/gradebook_service.py`
- Modify: `backend/tests/test_gradebook_service.py`

- [ ] **Step 1: Write failing tests**

Add to `test_gradebook_service.py`:

```python
class TestCategoryGradeCurved:
    ITEMS = [
        {"id": "a1", "points_possible": "100", "points_earned": "80",
         "curve_class_mean": 0.68, "curve_class_sd": 0.12,
         "curve_avg_target": None, "curve_sd_delta": None},
        {"id": "a2", "points_possible": "100", "points_earned": "60",
         "curve_class_mean": 0.55, "curve_class_sd": 0.10,
         "curve_avg_target": None, "curve_sd_delta": None},
    ]

    def test_raw_mode_ignores_curve(self):
        result = category_grade(self.ITEMS, curve_mode="raw",
                                curve_avg_target=0.83, curve_sd_delta=0.10)
        # raw average of 0.80 and 0.60
        assert abs(result - 0.70) < 1e-9

    def test_curved_mode_applies_curve(self):
        # a1: z=(0.80-0.68)/0.12=1.0 → 0.83+0.10=0.93
        # a2: z=(0.60-0.55)/0.10=0.5 → 0.83+0.05=0.88
        # mean = (0.93+0.88)/2 = 0.905
        result = category_grade(self.ITEMS, curve_mode="curved",
                                curve_avg_target=0.83, curve_sd_delta=0.10)
        assert abs(result - 0.905) < 1e-9

    def test_curved_skips_items_without_curve_data(self):
        items = [
            {"id": "a1", "points_possible": "100", "points_earned": "80",
             "curve_class_mean": None, "curve_class_sd": None,
             "curve_avg_target": None, "curve_sd_delta": None},
        ]
        result = category_grade(items, curve_mode="curved",
                                curve_avg_target=0.83, curve_sd_delta=0.10)
        # No curve data → raw score used
        assert abs(result - 0.80) < 1e-9

class TestCurrentGradeFinalCurve:
    def test_final_curve_applied_after_weighted_average(self):
        cats = [{"id": "c1", "weight": 100.0, "drop_lowest": 0}]
        assigns = [
            {"id": "a1", "category_id": "c1", "points_possible": "100",
             "points_earned": "68",  # raw 68% → z=0 at mean
             "curve_class_mean": None, "curve_class_sd": None,
             "curve_avg_target": None, "curve_sd_delta": None},
        ]
        # raw grade = 68%; final curve: mean=0.68, SD=0.12, avg_target=0.83
        # z = (0.68-0.68)/0.12 = 0 → curved = 0.83 = 83%
        result = current_grade(
            cats, assigns,
            curve_mode="curved",
            curve_avg_target=0.83, curve_sd_delta=0.10,
            curve_final_mean=0.68, curve_final_sd=0.12,
        )
        assert abs(result - 83.0) < 1e-6
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_gradebook_service.py::TestCategoryGradeCurved tests/test_gradebook_service.py::TestCurrentGradeFinalCurve -v
```

Expected: TypeError — `category_grade` and `current_grade` don't accept `curve_mode` yet.

- [ ] **Step 3: Update `category_grade` signature and body**

Replace the existing `category_grade` function:

```python
def category_grade(
    items: Iterable[AssignmentRow],
    drop_lowest: int = 0,
    curve_mode: str = "raw",
    curve_avg_target: Optional[float] = None,
    curve_sd_delta: Optional[float] = None,
) -> Optional[float]:
    """Return the 0–1 grade for one category, or None if no graded items.

    Each assignment is weighted equally (mean of earned/possible ratios).
    When curve_mode='curved' and an assignment has curve_class_mean and
    curve_class_sd set, apply_curve() is called on its score before averaging.
    Assignments without curve data are used at their raw score.
    """
    items = list(items)
    dropped = set(dropped_assignment_ids(items, drop_lowest))
    scores: list[float] = []
    for item in items:
        possible = item.get("points_possible")
        earned = item.get("points_earned")
        if possible is None or earned is None:
            continue
        if float(possible) <= 0:
            continue
        if item.get("id") in dropped:
            continue
        raw_pct = float(earned) / float(possible)
        if curve_mode == "curved":
            item_mean = item.get("curve_class_mean")
            item_sd = item.get("curve_class_sd")
            item_avg = item.get("curve_avg_target") or curve_avg_target
            item_sd_delta = item.get("curve_sd_delta") or curve_sd_delta
            if (item_mean is not None and item_sd is not None
                    and item_avg is not None and item_sd_delta is not None):
                raw_pct = apply_curve(
                    float(raw_pct), float(item_mean), float(item_sd),
                    float(item_avg), float(item_sd_delta)
                )
        scores.append(raw_pct)
    if not scores:
        return None
    return sum(scores) / len(scores)
```

- [ ] **Step 4: Update `current_grade` signature and body**

Replace the existing `current_grade` function:

```python
def current_grade(
    categories: list[CategoryRow],
    assignments: Iterable[AssignmentRow],
    curve_mode: str = "raw",
    curve_avg_target: Optional[float] = None,
    curve_sd_delta: Optional[float] = None,
    curve_final_mean: Optional[float] = None,
    curve_final_sd: Optional[float] = None,
) -> Optional[float]:
    """Return the 0–100 current grade across all categories, or None.

    When curve_mode='curved':
    - Per-assignment curves are applied inside category_grade().
    - If curve_final_mean, curve_final_sd, curve_avg_target, and curve_sd_delta
      are all set, a bell curve is also applied to the final weighted average.
    """
    by_cat: dict[str, list[AssignmentRow]] = {c["id"]: [] for c in categories}
    for a in assignments:
        cid = a.get("category_id")
        if cid in by_cat:
            by_cat[cid].append(a)

    total_weight = 0.0
    weighted_sum = 0.0
    for cat in categories:
        grade = category_grade(
            by_cat[cat["id"]], cat.get("drop_lowest", 0),
            curve_mode=curve_mode,
            curve_avg_target=curve_avg_target,
            curve_sd_delta=curve_sd_delta,
        )
        if grade is None:
            continue
        total_weight += float(cat["weight"])
        weighted_sum += grade * float(cat["weight"])

    if total_weight == 0:
        return None

    result = (weighted_sum / total_weight) * 100.0

    if (curve_mode == "curved"
            and curve_final_mean is not None
            and curve_final_sd is not None
            and curve_avg_target is not None
            and curve_sd_delta is not None):
        result = apply_curve(
            result / 100.0,
            curve_final_mean, curve_final_sd,
            curve_avg_target, curve_sd_delta,
        ) * 100.0

    return result
```

- [ ] **Step 5: Run all gradebook service tests**

```bash
cd backend && python -m pytest tests/test_gradebook_service.py -v
```

Expected: All pass (new + pre-existing).

- [ ] **Step 6: Commit**

```bash
git add backend/services/gradebook_service.py backend/tests/test_gradebook_service.py
git commit -m "feat(gradebook): extend category_grade and current_grade for bell curve mode"
```

---

## Task 3: Backend — Models + route changes for curve fields

**Files:**
- Modify: `backend/models/__init__.py`
- Modify: `backend/routes/gradebook.py`

- [ ] **Step 1: Add curve fields to `CreateAssignmentBody` and `UpdateAssignmentBody`**

In `backend/models/__init__.py`, update both classes:

```python
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
    curve_class_mean: Optional[float] = Field(default=None, ge=0, le=1)
    curve_class_sd: Optional[float] = Field(default=None, ge=0, le=1)
    curve_avg_target: Optional[float] = Field(default=None, ge=0, le=1)
    curve_sd_delta: Optional[float] = Field(default=None, ge=0, le=1)


class UpdateAssignmentBody(BaseModel):
    user_id: str
    title: Optional[str] = None
    category_id: Optional[str] = None
    points_possible: Optional[float] = Field(default=None, gt=0)
    points_earned: Optional[float] = Field(default=None, ge=0)
    due_date: Optional[str] = None
    assignment_type: Optional[str] = None
    notes: Optional[str] = None
    curve_class_mean: Optional[float] = Field(default=None, ge=0, le=1)
    curve_class_sd: Optional[float] = Field(default=None, ge=0, le=1)
    curve_avg_target: Optional[float] = Field(default=None, ge=0, le=1)
    curve_sd_delta: Optional[float] = Field(default=None, ge=0, le=1)
```

- [ ] **Step 2: Add `CurveSettingsBody` to `models/__init__.py`**

Add after `UpdateAssignmentBody`:

```python
class CurveSettingsBody(BaseModel):
    user_id: str
    curve_mode: str = "raw"  # "raw" | "curved"
    curve_avg_target: Optional[float] = Field(default=None, ge=0, le=1)
    curve_sd_delta: Optional[float] = Field(default=None, ge=0, le=1)
    curve_final_mean: Optional[float] = Field(default=None, ge=0, le=1)
    curve_final_sd: Optional[float] = Field(default=None, ge=0, le=1)
```

- [ ] **Step 3: Update `update_assignment_route` to allow curve fields**

In `backend/routes/gradebook.py`, change the `ALLOWED` set in `update_assignment_route`:

```python
ALLOWED = {
    "title", "category_id", "due_date", "assignment_type",
    "curve_class_mean", "curve_class_sd", "curve_avg_target", "curve_sd_delta",
}
```

(Curve fields are plain floats — no encryption needed.)

- [ ] **Step 4: Update `create_assignment` to save curve fields**

In the `create_assignment` function (around line 245), update the insert dict to include curve fields:

```python
inserted = table("assignments").insert({
    "id": new_id,
    "user_id": body.user_id,
    "course_id": body.course_id,
    "category_id": body.category_id,
    "title": body.title,
    "due_date": body.due_date,
    "assignment_type": body.assignment_type,
    "points_possible": encrypt_if_present(body.points_possible),
    "points_earned": encrypt_if_present(body.points_earned),
    "notes": encrypt_if_present(body.notes),
    "source": "manual",
    "curve_class_mean": body.curve_class_mean,
    "curve_class_sd": body.curve_class_sd,
    "curve_avg_target": body.curve_avg_target,
    "curve_sd_delta": body.curve_sd_delta,
})
```

- [ ] **Step 5: Add `CurveSettingsBody` import to `gradebook.py`**

Add `CurveSettingsBody` to the import from models in `gradebook.py`:

```python
from models import (
    CreateCategoryBody,
    BulkUpdateCategoriesBody,
    CreateAssignmentBody,
    UpdateAssignmentBody,
    SetLetterScaleBody,
    SyllabusApplyBody,
    CurveSettingsBody,
)
```

- [ ] **Step 6: Add `PATCH /courses/{course_id}/curve` endpoint**

Add after the `set_letter_scale` route in `gradebook.py`:

```python
@router.patch("/courses/{course_id}/curve")
def set_curve_settings(course_id: str, body: CurveSettingsBody, request: Request):
    """Persist bell curve policy and mode for a course."""
    require_self(body.user_id, request)
    if not _user_owns_course(body.user_id, course_id):
        raise HTTPException(status_code=404, detail="Course not in your gradebook")
    if body.curve_mode not in ("raw", "curved"):
        raise HTTPException(status_code=400, detail="curve_mode must be 'raw' or 'curved'")
    table("user_courses").update(
        {
            "curve_mode": body.curve_mode,
            "curve_avg_target": body.curve_avg_target,
            "curve_sd_delta": body.curve_sd_delta,
            "curve_final_mean": body.curve_final_mean,
            "curve_final_sd": body.curve_final_sd,
        },
        filters={"user_id": f"eq.{body.user_id}", "course_id": f"eq.{course_id}"},
    )
    return {"updated": True}
```

- [ ] **Step 7: Update `get_course` to select and return curve fields**

In `get_course`, update the `user_courses` select to include curve columns:

```python
enrollment = table("user_courses").select(
    "course_id,letter_scale,curve_mode,curve_avg_target,curve_sd_delta,curve_final_mean,curve_final_sd,courses!inner(id,course_code,course_name,semester)",
    filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    limit=1,
)
```

Extract the curve fields:

```python
course = enrollment[0]["courses"]
letter_scale = enrollment[0].get("letter_scale")
curve_mode = enrollment[0].get("curve_mode") or "raw"
curve_avg_target = enrollment[0].get("curve_avg_target")
curve_sd_delta = enrollment[0].get("curve_sd_delta")
curve_final_mean = enrollment[0].get("curve_final_mean")
curve_final_sd = enrollment[0].get("curve_final_sd")
```

Update the `assigns` select to include curve fields:

```python
assigns = table("assignments").select(
    "id,user_id,course_id,category_id,title,due_date,assignment_type,points_possible,points_earned,notes,source,curve_class_mean,curve_class_sd,curve_avg_target,curve_sd_delta",
    filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    order="due_date.asc",
)
```

Update the `current_grade` call to pass curve params:

```python
percent = gradebook_service.current_grade(
    cats, assigns,
    curve_mode=curve_mode,
    curve_avg_target=curve_avg_target,
    curve_sd_delta=curve_sd_delta,
    curve_final_mean=curve_final_mean,
    curve_final_sd=curve_final_sd,
)
```

Update the return dict to include curve settings:

```python
return {
    "course_id": course["id"],
    "course_code": course["course_code"],
    "course_name": course["course_name"],
    "semester": course["semester"],
    "percent": percent,
    "letter": letter,
    "letter_scale": letter_scale,
    "curve_mode": curve_mode,
    "curve_avg_target": curve_avg_target,
    "curve_sd_delta": curve_sd_delta,
    "curve_final_mean": curve_final_mean,
    "curve_final_sd": curve_final_sd,
    "categories": cats,
    "assignments": assigns,
    "dropped_assignment_ids": dropped_ids,
}
```

- [ ] **Step 8: Run existing gradebook route tests**

```bash
cd backend && python -m pytest tests/test_gradebook_routes.py -v
```

Expected: All pre-existing tests pass.

- [ ] **Step 9: Commit**

```bash
git add backend/models/__init__.py backend/routes/gradebook.py
git commit -m "feat(gradebook): add curve fields to models/routes and curve settings endpoint"
```

---

## Task 4: Frontend — Extend TypeScript types + create `curveUtils.ts`

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Create: `frontend/src/components/Gradebook/curveUtils.ts`

- [ ] **Step 1: Add curve fields to `GradedAssignment` in `types.ts`**

In `frontend/src/lib/types.ts`, update `GradedAssignment`:

```ts
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
  // Bell curve fields — null when no curve applied
  curve_class_mean: number | null;
  curve_class_sd: number | null;
  curve_avg_target: number | null;
  curve_sd_delta: number | null;
}
```

- [ ] **Step 2: Add curve fields to `GradebookCourse` in `types.ts`**

```ts
export interface GradebookCourse {
  course_id: string;
  course_code: string;
  course_name: string;
  semester: string;
  percent: number | null;
  letter: string | null;
  letter_scale: LetterScaleTier[] | null;
  curve_mode: "raw" | "curved";
  curve_avg_target: number | null;
  curve_sd_delta: number | null;
  curve_final_mean: number | null;
  curve_final_sd: number | null;
  categories: GradeCategory[];
  assignments: GradedAssignment[];
  dropped_assignment_ids: string[];
}
```

- [ ] **Step 3: Create `curveUtils.ts`**

Create `frontend/src/components/Gradebook/curveUtils.ts`:

```ts
import type { GradedAssignment, GradebookCourse } from "@/lib/types";

/**
 * Apply a bell curve adjustment to a single score percentage (0–1).
 *
 * z_score      = (score_pct - class_mean) / class_sd
 * curved_grade = avg_target + z_score * sd_delta
 *
 * Returns score_pct unchanged when class_sd === 0 (prevents division by zero).
 * Result is clamped to [0, 1].
 */
export function applyCurve(
  scorePct: number,
  classMean: number,
  classSd: number,
  avgTarget: number,
  sdDelta: number,
): number {
  if (classSd <= 0) return scorePct;
  const z = (scorePct - classMean) / classSd;
  return Math.max(0, Math.min(1, avgTarget + z * sdDelta));
}

/**
 * Return a GradedAssignment with its points_earned replaced by the curved
 * value. Returns the original assignment unchanged if it has no curve data.
 */
export function applyCurveToAssignment(
  a: GradedAssignment,
  coursePolicy: { curve_avg_target: number; curve_sd_delta: number },
): GradedAssignment {
  if (
    a.points_earned === null ||
    a.curve_class_mean == null ||
    a.curve_class_sd == null
  ) return a;
  const rawPct = a.points_earned / (a.points_possible ?? 1);
  const avgTarget = a.curve_avg_target ?? coursePolicy.curve_avg_target;
  const sdDelta = a.curve_sd_delta ?? coursePolicy.curve_sd_delta;
  const curved = applyCurve(rawPct, a.curve_class_mean, a.curve_class_sd, avgTarget, sdDelta);
  return { ...a, points_earned: curved * (a.points_possible ?? 1) };
}

/**
 * Apply a final-grade bell curve to a 0–100 percentage.
 * Returns pct unchanged if the course has no final curve configured.
 */
export function applyFinalCurve(
  pct: number,
  course: Pick<GradebookCourse, "curve_final_mean" | "curve_final_sd" | "curve_avg_target" | "curve_sd_delta">,
): number {
  if (
    course.curve_final_mean == null ||
    course.curve_final_sd == null ||
    course.curve_avg_target == null ||
    course.curve_sd_delta == null
  ) return pct;
  return applyCurve(
    pct / 100,
    course.curve_final_mean,
    course.curve_final_sd,
    course.curve_avg_target,
    course.curve_sd_delta,
  ) * 100;
}

/** Returns true when the assignment has enough data for a curve to be applied. */
export function hasCurveData(a: GradedAssignment): boolean {
  return a.curve_class_mean != null && a.curve_class_sd != null;
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/components/Gradebook/curveUtils.ts
git commit -m "feat(gradebook): add curve types and curveUtils functions"
```

---

## Task 5: Frontend — API functions

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add `setCurveSettings` function**

In `frontend/src/lib/api.ts`, add after `setLetterScale`:

```ts
export async function setCurveSettings(
  userId: string,
  courseId: string,
  settings: {
    curve_mode: "raw" | "curved";
    curve_avg_target: number | null;
    curve_sd_delta: number | null;
    curve_final_mean: number | null;
    curve_final_sd: number | null;
  },
): Promise<{ updated: boolean }> {
  return fetchJSON(`/api/gradebook/courses/${courseId}/curve`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, ...settings }),
  });
}
```

- [ ] **Step 2: Extend `updateGradedAssignment` to pass curve fields**

Find `updateGradedAssignment` and update its fields type to include curve fields. The function already uses `Partial<...>` — the new fields on `GradedAssignment` are automatically included since we updated the type in Task 4. No code change needed here — TypeScript will infer them.

Verify by checking the existing signature accepts an object with `curve_class_mean` etc. without a type error. If the function body passes fields directly, it already works.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(gradebook): add setCurveSettings API function"
```

---

## Task 6: Frontend — `AssignmentModal` Bell Curve section

**Files:**
- Modify: `frontend/src/components/Gradebook/AssignmentModal.tsx`

The modal currently has: Title, Category, Earned, Total, Due Date, Notes.
Add a collapsible "Bell Curve" section after Notes.

- [ ] **Step 1: Add curve fields to `AssignmentDraft`**

In `AssignmentModal.tsx`, update `AssignmentDraft`:

```ts
export interface AssignmentDraft {
  title: string;
  category_id: string | null;
  points_possible: number | null;
  points_earned: number | null;
  due_date: string | null;
  assignment_type: string | null;
  notes: string | null;
  curve_class_mean: number | null;
  curve_class_sd: number | null;
  curve_avg_target: number | null;
  curve_sd_delta: number | null;
}
```

- [ ] **Step 2: Add `curveOpen` state and populate from `initial`**

Add state and update the effect that populates from `initial`:

```ts
const [curveOpen, setCurveOpen] = React.useState(false);
```

In the `useEffect` that sets draft when `open` changes, add the curve fields:

```ts
setDraft({
  title: initial?.title ?? "",
  category_id: initial?.category_id ?? null,
  points_possible: initial?.points_possible ?? null,
  points_earned: initial?.points_earned ?? null,
  due_date: initial?.due_date ?? null,
  assignment_type: initial?.assignment_type ?? null,
  notes: initial?.notes ?? null,
  curve_class_mean: initial?.curve_class_mean ?? null,
  curve_class_sd: initial?.curve_class_sd ?? null,
  curve_avg_target: initial?.curve_avg_target ?? null,
  curve_sd_delta: initial?.curve_sd_delta ?? null,
});
// Auto-open curve section if assignment already has curve data
setCurveOpen(!!(initial?.curve_class_mean != null));
```

- [ ] **Step 3: Add Bell Curve section to the form JSX**

Add after the Notes `<label>` block, before the closing `</div>` of the form grid:

```tsx
          {/* Bell Curve section */}
          <div>
            <button
              type="button"
              onClick={() => setCurveOpen((v) => !v)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                background: "none",
                border: 0,
                padding: "4px 0",
                cursor: "pointer",
                fontFamily: "var(--font-sans)",
                fontSize: 13,
                color: "var(--accent)",
                fontWeight: 500,
              }}
            >
              <span style={{
                display: "inline-block",
                transition: "transform 0.15s",
                transform: curveOpen ? "rotate(0deg)" : "rotate(-90deg)",
              }}>▾</span>
              Bell Curve
            </button>
            {curveOpen && (
              <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
                <p style={{ margin: 0, fontSize: 11, color: "var(--text-dim)", lineHeight: 1.5 }}>
                  A bell curve adjusts your score based on class performance.
                  Enter the statistics your professor posted after this exam.
                </p>
                <div style={{ display: "flex", gap: 8 }}>
                  <label style={{ flex: 1 }}>
                    Class Average (%)
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step="any"
                      placeholder="e.g. 68"
                      value={draft.curve_class_mean !== null ? (draft.curve_class_mean * 100).toFixed(1) : ""}
                      onChange={(e) => setDraft({
                        ...draft,
                        curve_class_mean: e.target.value === "" ? null : Number(e.target.value) / 100,
                      })}
                      style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
                    />
                  </label>
                  <label style={{ flex: 1 }}>
                    Std Dev (%)
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step="any"
                      placeholder="e.g. 12"
                      value={draft.curve_class_sd !== null ? (draft.curve_class_sd * 100).toFixed(1) : ""}
                      onChange={(e) => setDraft({
                        ...draft,
                        curve_class_sd: e.target.value === "" ? null : Number(e.target.value) / 100,
                      })}
                      style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
                    />
                  </label>
                </div>
                <p style={{ margin: 0, fontSize: 11, color: "var(--text-muted)" }}>
                  Override course curve policy for this assignment only (optional):
                </p>
                <div style={{ display: "flex", gap: 8 }}>
                  <label style={{ flex: 1 }}>
                    Avg maps to (%)
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step="any"
                      placeholder="Course default"
                      value={draft.curve_avg_target !== null ? (draft.curve_avg_target * 100).toFixed(1) : ""}
                      onChange={(e) => setDraft({
                        ...draft,
                        curve_avg_target: e.target.value === "" ? null : Number(e.target.value) / 100,
                      })}
                      style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
                    />
                  </label>
                  <label style={{ flex: 1 }}>
                    Grade per SD (%)
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step="any"
                      placeholder="Course default"
                      value={draft.curve_sd_delta !== null ? (draft.curve_sd_delta * 100).toFixed(1) : ""}
                      onChange={(e) => setDraft({
                        ...draft,
                        curve_sd_delta: e.target.value === "" ? null : Number(e.target.value) / 100,
                      })}
                      style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
                    />
                  </label>
                </div>
                {(draft.curve_class_mean !== null || draft.curve_class_sd !== null) && (
                  <button
                    type="button"
                    onClick={() => setDraft({
                      ...draft,
                      curve_class_mean: null,
                      curve_class_sd: null,
                      curve_avg_target: null,
                      curve_sd_delta: null,
                    })}
                    style={{ fontSize: 11, color: "var(--err)", background: "none", border: 0,
                      padding: 0, cursor: "pointer", textAlign: "left" }}
                  >
                    Remove curve from this assignment
                  </button>
                )}
              </div>
            )}
          </div>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Gradebook/AssignmentModal.tsx
git commit -m "feat(gradebook): add Bell Curve section to AssignmentModal"
```

---

## Task 7: Frontend — Raw/Curved toggle + curve derivations in `Course.tsx`

**Files:**
- Modify: `frontend/src/components/screens/Gradebook/Course.tsx`

- [ ] **Step 1: Import curve utilities and `setCurveSettings` API function**

Add to the imports at the top of `Course.tsx`:

```ts
import { applyCurveToAssignment, applyFinalCurve, hasCurveData } from "@/components/Gradebook/curveUtils";
import { setCurveSettings } from "@/lib/api";
```

- [ ] **Step 2: Add `curveSettingsOpen` state and `handleToggleCurveMode` callback**

After the existing `predictorOpen` state, add:

```ts
const [curveSettingsOpen, setCurveSettingsOpen] = React.useState(false);
```

After the existing `handleTogglePredictor` callback, add:

```ts
const handleToggleCurveMode = React.useCallback(async () => {
  if (!data || !userId) return;
  const newMode = data.curve_mode === "curved" ? "raw" : "curved";
  // Optimistic update
  setData((prev) => prev ? { ...prev, curve_mode: newMode } : prev);
  try {
    await setCurveSettings(userId, courseId, {
      curve_mode: newMode,
      curve_avg_target: data.curve_avg_target,
      curve_sd_delta: data.curve_sd_delta,
      curve_final_mean: data.curve_final_mean,
      curve_final_sd: data.curve_final_sd,
    });
  } catch {
    // Revert on failure
    setData((prev) => prev ? { ...prev, curve_mode: data.curve_mode } : prev);
  }
}, [data, userId, courseId]);
```

- [ ] **Step 3: Derive `curvedAssignments` and `curvedPercent`**

After the existing `augmentedAssignments` memo (predictor-related), add:

```ts
const hasCurve = React.useMemo(
  () => (data?.assignments ?? []).some(hasCurveData) ||
        (data?.curve_final_mean != null),
  [data],
);

const curvedAssignments = React.useMemo(() => {
  if (!data || data.curve_mode !== "curved") return data?.assignments ?? [];
  const policy = {
    curve_avg_target: data.curve_avg_target ?? 0.83,
    curve_sd_delta: data.curve_sd_delta ?? 0.10,
  };
  return data.assignments.map((a) => applyCurveToAssignment(a, policy));
}, [data]);

const curvedPercent = React.useMemo(() => {
  if (!data || data.curve_mode !== "curved" || data.percent == null) return data?.percent ?? null;
  return applyFinalCurve(data.percent, data);
}, [data]);
```

- [ ] **Step 4: Add Raw/Curved toggle to the TopBar actions**

Find the `actions` prop on `<TopBar` (around line 248). Add the toggle after the Letter Scale button, only when `hasCurve` is true:

```tsx
        actions={
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {hasCurve && data && (
              <div style={{ display: "flex", background: "var(--bg-subtle)", borderRadius: 20, padding: 2 }}>
                {(["raw", "curved"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={data.curve_mode !== mode ? handleToggleCurveMode : undefined}
                    style={{
                      padding: "4px 12px",
                      borderRadius: 18,
                      fontSize: 11,
                      fontWeight: 500,
                      background: data.curve_mode === mode ? "var(--accent)" : "transparent",
                      color: data.curve_mode === mode ? "#fff" : "var(--text-dim)",
                      border: 0,
                      cursor: data.curve_mode !== mode ? "pointer" : "default",
                      fontFamily: "var(--font-sans)",
                    }}
                  >
                    {mode === "raw" ? "Raw" : "Curved"}
                  </button>
                ))}
              </div>
            )}
            <button
              type="button"
              onClick={() => setEditScale(true)}
              className="btn"
              style={{ padding: "4px 12px", fontSize: 12 }}
            >
              Letter scale
            </button>
          </div>
        }
```

- [ ] **Step 5: Pass curved data to `GradeCompositionBar`**

Update the `<GradeCompositionBar` usage to use curved data when mode is curved:

```tsx
              <GradeCompositionBar
                categories={data.categories}
                assignments={
                  predictorOpen
                    ? augmentedAssignments
                    : data.curve_mode === "curved"
                      ? curvedAssignments
                      : data.assignments
                }
                letterScale={data.letter_scale}
                currentPercent={
                  predictorOpen
                    ? (predictedProjection?.current ?? null)
                    : curvedPercent
                }
                onEditWeights={() => setEditWeights(true)}
                onSegmentClick={focusCategory}
                isPredicted={predictorOpen}
              />
```

- [ ] **Step 6: Pass `curveMode` and `curvedAssignments` to `AssignmentList`**

Update `AssignmentList` to receive curve-aware props (we'll use these in Task 8):

```tsx
              {/* AssignmentList always receives real grades — the predictor is display-only */}
              <AssignmentList
                assignments={data.assignments}
                curvedAssignments={data.curve_mode === "curved" ? curvedAssignments : undefined}
                categories={data.categories}
                droppedIds={droppedAssignmentIds(data.categories, data.assignments)}
                highlightedCategory={highlightedCategory}
                onAdd={() => setAssignModal({ open: true, initial: null })}
                onEditFull={(a) => setAssignModal({ open: true, initial: a })}
                onEditGrade={onEditGrade}
                onSyncGradescope={onClickSyncButton}
                onGradescopeSettings={
                  gscope.ready ? () => setSyncOpen(true) : undefined
                }
                gradescopeReady={gscope.ready}
                gradescopeBusy={gscopeBusy}
                gradescopeLastSyncedAt={gscope.lastSyncedAt}
              />
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/screens/Gradebook/Course.tsx
git commit -m "feat(gradebook): add Raw/Curved toggle and curved grade derivation to course page"
```

---

## Task 8: Frontend — `AssignmentList` curved score display

**Files:**
- Modify: `frontend/src/components/Gradebook/AssignmentList.tsx`

- [ ] **Step 1: Add `curvedAssignments` to Props**

In `AssignmentList.tsx`, update the Props interface:

```ts
interface Props {
  assignments: GradedAssignment[];
  curvedAssignments?: GradedAssignment[];   // parallel array with curved scores; undefined = raw mode
  categories: GradeCategory[];
  droppedIds?: Set<string>;
  onAdd: () => void;
  onEditGrade: (id: string, pointsEarned: number | null) => void;
  onEditFull: (a: GradedAssignment) => void;
  onSyncGradescope?: () => void;
  onGradescopeSettings?: () => void;
  gradescopeReady?: boolean;
  gradescopeBusy?: boolean;
  gradescopeLastSyncedAt?: string | null;
  highlightedCategory?: string | null;
}
```

Destructure in the function signature:

```ts
export function AssignmentList({
  assignments,
  curvedAssignments,
  ...
```

- [ ] **Step 2: Build a lookup map from curved assignments**

After the `dropped` and `sortedCats` memos, add:

```ts
const curvedMap = React.useMemo(
  () => new Map((curvedAssignments ?? []).map((a) => [a.id, a])),
  [curvedAssignments],
);
```

- [ ] **Step 3: Display curved score in assignment rows**

Inside `CategoryGroup` (the inner component that renders each row), the `items.map((a) => ...)` block renders each row. Find where the score input and `/ {total}` are shown (around line 402). Update the row to show curved vs raw:

After `const isDropped = droppedIds.has(a.id);`, add:

```ts
const curved = curvedMap.get(a.id);
const isCurved = curved != null && curved.points_earned !== a.points_earned;
const displayEarned = isCurved ? (curved.points_earned ?? null) : a.points_earned;
const rawEarned = a.points_earned;
```

Update the subtitle line (due date) to show curve info when applicable. After the date display, add:

```tsx
                  {isCurved && (
                    <span style={{ color: "var(--accent)", marginLeft: 6 }}>
                      Bell Curve Applied
                    </span>
                  )}
```

Update the score display to show curved value and raw in muted text:

```tsx
              <span className="mono" style={{
                fontSize: 13,
                color: isCurved ? "var(--accent)" : "var(--text)",
                fontWeight: isCurved ? 600 : 400,
                minWidth: 52,
                textAlign: "right",
              }}>
                {displayEarned !== null
                  ? `${((displayEarned / (a.points_possible ?? 1)) * 100).toFixed(1)}%`
                  : "—"}
                {isCurved && rawEarned !== null && (
                  <span style={{ fontSize: 10, color: "var(--text-muted)", fontWeight: 400, marginLeft: 4 }}>
                    (raw {((rawEarned / (a.points_possible ?? 1)) * 100).toFixed(0)}%)
                  </span>
                )}
              </span>
```

Note: this changes the score display from showing raw points (e.g. `85 / 100`) to showing a percentage (e.g. `91.3%`) when curved is active, to make the comparison meaningful. For the raw grade input (the number input the user types into), keep it pointing at `a.points_earned` — the user always edits the real score.

- [ ] **Step 4: Pass `curvedMap` down to `CategoryGroup`**

`CategoryGroup` is an inner function in AssignmentList that takes props. Add `curvedMap` to its props and pass it through from the parent `AssignmentList` render call.

Find `function CategoryGroup({` and add `curvedMap: Map<string, GradedAssignment>` to its props interface. Pass `curvedMap={curvedMap}` where `CategoryGroup` is rendered.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Gradebook/AssignmentList.tsx
git commit -m "feat(gradebook): show curved score in assignment rows when curve mode is active"
```

---

## Task 9: Frontend — Course Curve Settings UI

**Files:**
- Modify: `frontend/src/components/screens/Gradebook/Course.tsx`

The Raw/Curved toggle is wired in Task 7. This task adds a way to configure the course-level curve policy (avg target, SD delta, final curve mean/SD). This is reached via a gear/settings button or a section in the existing EditWeightsModal — we'll add it as a new modal triggered from the Curved pill.

- [ ] **Step 1: Create `CurveSettingsModal` inline in Course.tsx**

Add before the `export function GradebookCourseScreen` line:

```tsx
function CurveSettingsModal({
  open,
  course,
  onClose,
  onSave,
}: {
  open: boolean;
  course: import("@/lib/types").GradebookCourse;
  onClose: () => void;
  onSave: (settings: {
    curve_avg_target: number | null;
    curve_sd_delta: number | null;
    curve_final_mean: number | null;
    curve_final_sd: number | null;
  }) => Promise<void>;
}) {
  const [mounted, setMounted] = React.useState(false);
  const [avgTarget, setAvgTarget] = React.useState<string>(
    course.curve_avg_target != null ? (course.curve_avg_target * 100).toFixed(0) : "83"
  );
  const [sdDelta, setSdDelta] = React.useState<string>(
    course.curve_sd_delta != null ? (course.curve_sd_delta * 100).toFixed(0) : "10"
  );
  const [finalMean, setFinalMean] = React.useState<string>(
    course.curve_final_mean != null ? (course.curve_final_mean * 100).toFixed(0) : ""
  );
  const [finalSd, setFinalSd] = React.useState<string>(
    course.curve_final_sd != null ? (course.curve_final_sd * 100).toFixed(0) : ""
  );
  const [saving, setSaving] = React.useState(false);
  React.useEffect(() => setMounted(true), []);
  if (!mounted || !open) return null;

  const toFloat = (s: string): number | null =>
    s.trim() === "" ? null : Number(s) / 100;

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
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "var(--bg)", borderRadius: 12, padding: 24,
        minWidth: 400, maxWidth: 480,
      }}>
        <h3 style={{ margin: "0 0 4px" }}>Bell Curve Settings</h3>
        <p style={{ margin: "0 0 16px", fontSize: 12, color: "var(--text-dim)", lineHeight: 1.5 }}>
          The curve policy comes from your syllabus. The class average maps to a target
          grade; each standard deviation above or below shifts the grade by a fixed amount.
        </p>

        <div style={{ display: "grid", gap: 10, marginBottom: 16 }}>
          <p style={{ margin: 0, fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase",
            letterSpacing: "0.1em", fontFamily: "var(--font-mono)" }}>
            Course Policy (from syllabus)
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <label style={{ flex: 1 }}>
              Average maps to (%)
              <input type="number" min={0} max={100} value={avgTarget}
                onChange={(e) => setAvgTarget(e.target.value)}
                style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }} />
            </label>
            <label style={{ flex: 1 }}>
              Grade per SD (%)
              <input type="number" min={0} max={50} value={sdDelta}
                onChange={(e) => setSdDelta(e.target.value)}
                style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }} />
            </label>
          </div>
        </div>

        <div style={{ display: "grid", gap: 10, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
          <p style={{ margin: 0, fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase",
            letterSpacing: "0.1em", fontFamily: "var(--font-mono)" }}>
            Final Grade Curve (optional)
          </p>
          <p style={{ margin: 0, fontSize: 12, color: "var(--text-dim)" }}>
            If your professor curves the final grade at the end of semester, enter the class stats here.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <label style={{ flex: 1 }}>
              Class Final Avg (%)
              <input type="number" min={0} max={100} value={finalMean} placeholder="—"
                onChange={(e) => setFinalMean(e.target.value)}
                style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }} />
            </label>
            <label style={{ flex: 1 }}>
              Class Final SD (%)
              <input type="number" min={0} max={100} value={finalSd} placeholder="—"
                onChange={(e) => setFinalSd(e.target.value)}
                style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }} />
            </label>
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 20,
          paddingTop: 12, borderTop: "1px solid var(--border)" }}>
          <button type="button" onClick={onClose}>Cancel</button>
          <button
            type="button"
            disabled={saving}
            onClick={async () => {
              setSaving(true);
              try {
                await onSave({
                  curve_avg_target: toFloat(avgTarget),
                  curve_sd_delta: toFloat(sdDelta),
                  curve_final_mean: toFloat(finalMean),
                  curve_final_sd: toFloat(finalSd),
                });
                onClose();
              } finally { setSaving(false); }
            }}
            style={{
              background: "var(--accent)", color: "#fff",
              border: 0, borderRadius: 6, padding: "6px 14px", cursor: "pointer",
            }}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
```

You'll need `createPortal` imported — add it to the React import at the top of Course.tsx:
```ts
import { createPortal } from "react-dom";
```

- [ ] **Step 2: Add `curveSettingsOpen` state and handler**

(State was already added in Task 7 Step 2.) Add the save handler after `handleToggleCurveMode`:

```ts
const handleSaveCurveSettings = React.useCallback(
  async (settings: {
    curve_avg_target: number | null;
    curve_sd_delta: number | null;
    curve_final_mean: number | null;
    curve_final_sd: number | null;
  }) => {
    if (!data || !userId) return;
    await setCurveSettings(userId, courseId, {
      curve_mode: data.curve_mode,
      ...settings,
    });
    setData((prev) => prev ? { ...prev, ...settings } : prev);
  },
  [data, userId, courseId],
);
```

- [ ] **Step 3: Add a ⚙ button next to the Curved pill to open settings**

In the Curved pill render (from Task 7 Step 4), add a settings button after the pill when mode is "curved":

```tsx
            {hasCurve && data && data.curve_mode === "curved" && (
              <button
                type="button"
                onClick={() => setCurveSettingsOpen(true)}
                className="btn btn--sm"
                title="Bell curve settings"
                style={{ fontSize: 13 }}
              >
                ⚙
              </button>
            )}
```

- [ ] **Step 4: Render `CurveSettingsModal` in the modals block**

In the `{data && (...)}` block where other modals are rendered, add:

```tsx
          <CurveSettingsModal
            open={curveSettingsOpen}
            course={data}
            onClose={() => setCurveSettingsOpen(false)}
            onSave={handleSaveCurveSettings}
          />
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/screens/Gradebook/Course.tsx
git commit -m "feat(gradebook): add CurveSettingsModal for course-level bell curve policy"
```

---

## Task 10: Smoke Test

- [ ] **Step 1: Start backend and frontend**

```powershell
# Terminal 1
cd backend && python main.py

# Terminal 2
cd frontend && npm run dev
```

- [ ] **Step 2: Test per-assignment curve**

1. Open a course, edit an assignment.
2. Expand "Bell Curve" section. Enter Class Average = 68, Std Dev = 12.
3. Save. The assignment row should look unchanged (toggle is still "Raw").
4. The "Raw / Curved" toggle now appears in the top bar. Click "Curved".
5. The assignment row shows the curved percentage in accent color with raw in muted text.
6. The composition bar updates to reflect the curved grade.

- [ ] **Step 3: Test course policy via ⚙**

1. With "Curved" mode on, click the ⚙ gear button.
2. Set Average maps to = 83, Grade per SD = 10. Save.
3. The grade projector should recalculate using the policy.

- [ ] **Step 4: Test final grade curve**

1. In the ⚙ modal, enter Class Final Avg = 74, Class Final SD = 8. Save.
2. Confirm the final grade percentage in the composition bar header changes.

- [ ] **Step 5: Test Raw toggle**

1. Click "Raw" — all scores return to original values, bar returns to real grade.
2. Toggle back to "Curved" — curved values return.

- [ ] **Step 6: Run backend tests**

```bash
cd backend && python -m pytest tests/test_gradebook_service.py tests/test_gradebook_routes.py -v
```

Expected: All pass.

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "feat(gradebook): bell curve grading complete"
```
