# Bell Curve Grading — Design Spec
**Date:** 2026-06-16
**Status:** Approved

## Overview

Students can apply bell curve grade adjustments to individual assignments or to the final computed grade. The curve policy (what grade the average maps to, how much each standard deviation shifts the grade) comes from the course syllabus and is set up once. After each exam, the student enters the class statistics posted by the professor (mean and standard deviation) to calculate their curved score.

A **Raw ↔ Curved toggle** at the top of the course page switches between the original scores and the curved scores everywhere — assignment rows, composition bar, and grade projector. Both scopes (per-assignment and final grade) can coexist on the same course.

---

## Bell Curve Formula

```
z_score       = (student_score_pct - class_mean_pct) / class_std_dev_pct
curved_grade  = curve_avg_target + z_score × curve_sd_delta
```

- `student_score_pct` — student's raw score as a 0–1 ratio (earned / possible)
- `class_mean_pct` — class average as a 0–1 ratio (professor-posted)
- `class_std_dev_pct` — class standard deviation as a 0–1 ratio
- `curve_avg_target` — what grade the average maps to (0–1), from syllabus (e.g. B = 0.83)
- `curve_sd_delta` — how much one standard deviation shifts the grade (0–1), from syllabus (e.g. 0.10 = 10%)

**Example:** Class mean 68%, SD 12%, student scored 80%, avg target B (83%), SD delta 10%.
`z = (0.80 − 0.68) / 0.12 = 1.0` → curved = `0.83 + 1.0 × 0.10 = 0.93 (A−)`

Curved scores are clamped to `[0, 1]` (no negative grades, no grades above 100%).

---

## Curve Scope

### Per-Assignment Curve
- Applied to individual assignments/exams.
- Student enters **class mean** and **class SD** per assignment after the professor posts them.
- Only assignments with curve data entered show a curved score.
- Assignments without curve data are unaffected — shown as normal, no label.
- The curved score replaces the raw score in grade calculations when the Curved toggle is on.

### Final Grade Curve
- Applied to the overall final computed percentage (after all category weights and drops).
- Student enters class final-grade mean and SD once (typically end of semester).
- Curved final grade is shown at the course level (composition bar header, course card).
- Individual assignment scores are unaffected.

### Coexistence
Both scopes can be active simultaneously. When both are enabled:
1. Per-assignment curves adjust individual scores.
2. Those curved scores flow into the weighted category average.
3. The resulting final percentage is then run through the final grade curve.

---

## Curve Policy (Syllabus Settings)

The curve policy defines what the bell curve looks like for this course. Set once at course level.

| Field | Description | Example |
|---|---|---|
| `curve_avg_target` | Grade the class average maps to (0–1) | 0.83 (B) |
| `curve_sd_delta` | Grade shift per standard deviation (0–1) | 0.10 (10%) |

These defaults apply to all per-assignment curves. Individual assignments can override them if the professor announces a different policy for that specific exam.

---

## Data Model Changes

### `GradedAssignment` — new optional fields
```ts
curve_class_mean?: number | null;   // class mean as 0–1 (e.g. 0.68 for 68%)
curve_class_sd?: number | null;     // class SD as 0–1 (e.g. 0.12)
curve_avg_target?: number | null;   // override course policy; null = use course default
curve_sd_delta?: number | null;     // override course policy; null = use course default
```

A `GradedAssignment` is "curved" when `curve_class_mean` and `curve_class_sd` are both set.

### `GradebookCourse` — new fields
```ts
curve_mode: "raw" | "curved";       // current toggle state, persisted
curve_avg_target: number | null;    // course-level policy (0–1)
curve_sd_delta: number | null;      // course-level policy (0–1)
curve_final_mean: number | null;    // final grade curve: class mean (0–1)
curve_final_sd: number | null;      // final grade curve: class SD (0–1)
```

### Backend columns (Supabase)
- `gradebook_assignments`: add `curve_class_mean`, `curve_class_sd`, `curve_avg_target`, `curve_sd_delta` (all float, nullable)
- `gradebook_courses`: add `curve_mode` (text, default `'raw'`), `curve_avg_target`, `curve_sd_delta`, `curve_final_mean`, `curve_final_sd` (all float/text, nullable)

---

## UI Components

### Raw ↔ Curved Toggle
- Sits in the course page header area, next to the Letter Scale button in the TopBar actions.
- Pill-style toggle: two segments — "Raw" and "Curved".
- Only visible when at least one assignment has curve data OR a final grade curve is set.
- Persisted via `PATCH /api/gradebook/:userId/courses/:courseId` (updates `curve_mode`).
- When switched to Curved: composition bar, grade projector, and assignment rows all re-render with curved values.

### Assignment Row (AssignmentList)
- When curved toggle is ON and the assignment has curve data:
  - Score shows the curved percentage with the raw score in muted text: `88.4% (was 76%)`
  - A small `Bell curve applied` subtitle appears below the assignment name with class mean/SD
- When curved toggle is OFF or no curve data: row shows as normal.

### Assignment Modal (edit)
- New collapsible "Bell Curve" section in the edit assignment modal.
- Fields: Class Average (%), Class Std Dev (%), and optionally override Avg Target Grade and SD Delta (defaults to course policy).
- Brief explanation: "A bell curve adjusts your score based on how the class performed. Enter the stats your professor posted."

### Course Settings (EditWeightsModal or new tab)
- New "Curve Policy" section: set `curve_avg_target` and `curve_sd_delta` for the course.
- Final Grade Curve subsection: enter `curve_final_mean` and `curve_final_sd`.

### Grade Projector + Composition Bar
- When `curve_mode = "curved"`, `projectGrade()` and `GradeCompositionBar` receive curved assignments instead of raw.
- Final grade curve applied after `projectGrade()` computes the weighted average.
- "Curved" label shown (reuses existing `isPredicted`-style chip pattern with a different label).

---

## Grade Calculation Changes

### Frontend (`GradeProjector.tsx`, `Course.tsx`)
New pure function `applyCurve(assignment, coursePolicy)`:
```ts
function applyCurve(
  a: GradedAssignment,
  coursePolicy: { avg_target: number; sd_delta: number },
): GradedAssignment {
  if (a.points_earned === null || a.curve_class_mean == null || a.curve_class_sd == null) return a;
  const rawPct = a.points_earned / (a.points_possible ?? 1);
  const avgTarget = a.curve_avg_target ?? coursePolicy.avg_target;
  const sdDelta = a.curve_sd_delta ?? coursePolicy.sd_delta;
  const z = (rawPct - a.curve_class_mean) / a.curve_class_sd;
  const curved = Math.max(0, Math.min(1, avgTarget + z * sdDelta));
  return { ...a, points_earned: curved * (a.points_possible ?? 1) };
}
```

`curvedAssignments = curve_mode === "curved" ? assignments.map(a => applyCurve(a, policy)) : assignments`

Final grade curve applied after `projectGrade()`:
```ts
function applyFinalCurve(pct, course): number {
  if (!course.curve_final_mean || !course.curve_final_sd) return pct;
  const z = (pct/100 - course.curve_final_mean) / course.curve_final_sd;
  return Math.max(0, Math.min(100, (course.curve_avg_target + z * course.curve_sd_delta) * 100));
}
```

### Backend (`gradebook_service.py`)
Same `applyCurve` logic in Python applied before `category_grade()` when `curve_mode = "curved"`.

---

## Edge Cases

| Case | Behaviour |
|---|---|
| Assignment has no curve data | Used as-is; no label shown |
| Only final grade curve set (no per-assignment) | Individual rows unchanged; final % is curved |
| Curved score > 100% | Clamped to 100% |
| Curved score < 0% | Clamped to 0% |
| SD = 0 (whole class same score) | Division by zero → skip curve, use raw score |
| `curve_mode = "raw"` | All raw scores used; toggle hidden if no curve data exists |
| Drop-lowest + curve | Drop applied to curved scores (curved score determines which is lowest) |

---

## Out of Scope
- Sapling computing class statistics from multiple students' data
- Curve history / audit trail
- Non-bell-curve adjustments (flat add, root curve, etc.) — future work
