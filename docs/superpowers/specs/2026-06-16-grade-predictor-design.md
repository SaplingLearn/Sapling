# Grade Predictor Panel — Design Spec
**Date:** 2026-06-16
**Status:** Approved

## Overview

An expandable "Predict My Grade" panel beneath the existing grade projector bar on the course page. Students set hypothetical earned/total scores on ungraded assignments using sliders + number inputs. The composition bar and grade projector update live to reflect the prediction, clearly marked as hypothetical. Nothing is saved until the student actually enters grades in the assignment list.

---

## UX / Layout

### Toggle button
A slim toggle row sits between the `GradeProjector` section and the assignment list:

```
▾ Predict My Grade  —  set hypothetical scores for N ungraded assignments
```

- Uses Sapling `--font-sans`, `--accent` green for the label, `--text-dim` for the count
- Clicking expands/collapses the panel with a smooth transition
- Arrow rotates 180° when open

### Predicted mode indicator on the composition bar
When the panel is open, the `GradeCompositionBar` renders in **predicted mode**:
- A `PREDICTED` badge appears in the composition section header (monospace, uppercase, accent color, soft background chip)
- The bar itself gains a subtle dashed border to distinguish it from the real bar
- The letter/percentage in the `CompositionStatus` line gains a `(predicted)` suffix in muted text

### Predictor panel
Full-width panel, `--bg-subtle` background, `--border` top edge:

**Result badge** (top of panel):
```
PREDICTED   B+   89.3%   (hypothetical)        [Reset All]
```
- `PREDICTED` label: mono, 10px, uppercase, `--text-muted`
- Letter: `--font-display` (Playfair), 26px, `--accent` color
- Percentage: mono, 18px, `--accent`
- `(hypothetical)`: 11px, `--text-muted`
- `Reset All` button: right-aligned, small, ghost style

**Assignment rows** (one per ungraded assignment with `points_possible > 0` set):

```
[Assignment name]          [━━━━━●━━━━━━━] [85] / 100
[Category · Due date]       0             100 pts
```

- Name: `--font-serif` (Spectral), 13px, `--text`
- Category + due date: mono, 11px, `--text-dim`
- Slider: full width, `accent-color: var(--accent)`, range `0 → points_possible`
- Earned input: number field, right-aligned, synced to slider
- Total: static `/ 100` label

**Assignments without `points_possible`** (no total set):
```
[Assignment name]          [━━━━━●━━━━━━━] [40] / [___]
[Category · Due date · no total set]
```
- Slider range defaults to `0 → 100` until user sets a custom total
- Total field: dashed border (`--border`), `--bg` background, placeholder `—`
- When user types a total, slider max updates to match
- Assignments with no `points_possible` and no custom total entered are **excluded from prediction** (they cannot contribute to the average without a denominator)

**Disclaimer** (bottom of panel):
```
Scores shown are hypothetical only — nothing is saved until you enter grades above.
```
11px, `--text-muted`.

---

## Data Flow

```
hypotheticals: Map<assignmentId, { earned: number; possible: number }>
     │
     ▼
augmentedAssignments = assignments.map(a =>
  isUngraded(a) && hypotheticals.has(a.id)
    ? { ...a, points_earned: hyp.earned, points_possible: hyp.possible ?? a.points_possible }
    : a
)
     │
     ├──▶ GradeCompositionBar (predictorOpen ? augmentedAssignments : assignments)
     └──▶ GradeProjector      (predictorOpen ? augmentedAssignments : assignments)
```

- `isUngraded(a)` = `a.points_earned === null`
- `augmentedAssignments` is a derived value, never written to state or the backend
- `GradeCompositionBar` and `GradeProjector` receive the same `assignments` prop they already accept — no changes to those components' interfaces

---

## State

Lifted to `Course.tsx`, local to the course page:

```ts
const [predictorOpen, setPredictorOpen] = React.useState(false);
const [hypotheticals, setHypotheticals] = React.useState<Map<string, { earned: number; possible: number }>>(new Map());
```

- `hypotheticals` resets to an empty Map when the panel closes (`setPredictorOpen(false)` also calls `setHypotheticals(new Map())`)
- Slider default on open: `Math.round((points_possible ?? 100) / 2)` — midpoint, neutral starting position
- "Reset All" sets hypotheticals back to the midpoint defaults

---

## New Component

**`GradePredictorPanel`** — `frontend/src/components/Gradebook/GradePredictorPanel.tsx`

Props:
```ts
interface Props {
  open: boolean;
  onToggle: () => void;
  ungradedAssignments: GradedAssignment[];   // already filtered to ungraded only
  categories: GradeCategory[];
  hypotheticals: Map<string, { earned: number; possible: number }>;
  onHypotheticalChange: (id: string, earned: number, possible: number) => void;
  onReset: () => void;
  predictedPercent: number | null;           // computed by parent from augmentedAssignments
  predictedLetter: string | null;
}
```

The component owns the slider/input rendering. The parent (`Course.tsx`) owns the `hypotheticals` map and derives `augmentedAssignments` + the predicted letter/percent.

---

## Edge Cases

| Case | Behaviour |
|---|---|
| Assignment has no `points_possible` | Slider defaults 0–100; editable total field shown; excluded from prediction until total is set |
| All ungraded assignments have no total | Panel shows "Set totals to enable prediction" in place of result badge |
| Drop-lowest active in category | Existing drop logic runs on augmented data — hypothetical scores can be dropped too |
| Extra credit (earned > possible) | Slider max = `points_possible`; user can type a higher value in the earned field manually |
| Panel open, user edits a real grade | Real grade update triggers data refresh; hypotheticals for that assignment are cleared |
| Zero ungraded assignments | Toggle button hidden entirely |

---

## Files Changed

| File | Change |
|---|---|
| `frontend/src/components/Gradebook/GradePredictorPanel.tsx` | **New** — panel component |
| `frontend/src/components/screens/Gradebook/Course.tsx` | Add predictor state, `augmentedAssignments` derivation, predicted badge on composition bar, pass augmented data when open |
| `frontend/src/components/Gradebook/GradeProjector.tsx` | No logic changes; optional `isPredicted` prop added to render a "Predicted" label beneath the bar stats |
| `GradeCompositionBar` (inline in `Course.tsx`) | Optional `isPredicted` prop shows badge + dashed border on the bar |

---

## Out of Scope

- Saving hypothetical scenarios
- Sharing predictions
- Modifying already-graded assignments via the predictor
