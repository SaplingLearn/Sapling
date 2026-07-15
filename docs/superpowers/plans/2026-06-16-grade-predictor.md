# Grade Predictor Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an expandable "Predict My Grade" panel below the composition bar where students set hypothetical scores on ungraded assignments and see live letter/percentage predictions on the composition bar.

**Architecture:** The panel holds a `hypotheticals` Map in Course.tsx state. When open, an `augmentedAssignments` array is derived (real assignments with hypothetical scores injected for ungraded ones) and passed to the existing `GradeCompositionBar` — no new grade math needed. A new `GradePredictorPanel` component owns the slider/input rendering.

**Tech Stack:** React (useState, useMemo, useCallback), TypeScript, existing Sapling CSS tokens (var(--accent), var(--bg-subtle), etc.), no new dependencies.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `frontend/src/components/Gradebook/GradePredictorPanel.tsx` | **Create** | Toggle button + expandable panel with per-assignment sliders |
| `frontend/src/components/screens/Gradebook/Course.tsx` | **Modify** | Add predictor state, derive augmented assignments, wire panel + isPredicted into composition bar |
| `frontend/src/components/Gradebook/GradeProjector.tsx` | **Modify** | Add optional `isPredicted` prop to show "Predicted" label in the footer stats |

---

## Task 1: Add `isPredicted` prop to `GradeProjector`

**Files:**
- Modify: `frontend/src/components/Gradebook/GradeProjector.tsx`

- [ ] **Step 1: Add `isPredicted` to Props interface**

In `GradeProjector.tsx`, find the `interface Props` block (around line 156) and add the optional prop:

```ts
interface Props {
  categories: GradeCategory[];
  assignments: GradedAssignment[];
  currentPercent: number | null;
  letterScale: LetterScaleTier[] | null;
  isPredicted?: boolean;
}
```

- [ ] **Step 2: Destructure the new prop in the component**

In the `export function GradeProjector({` signature, add `isPredicted = false`:

```ts
export function GradeProjector({
  categories,
  assignments,
  currentPercent,
  letterScale,
  isPredicted = false,
}: Props) {
```

- [ ] **Step 3: Render a "Predicted" label in the footer trio**

Find the footer trio `<div>` (the grid with "If you stop here" / action / "If you ace remaining" stats, around line 434). Add a `isPredicted` label just above it:

```tsx
      {isPredicted && (
        <div
          className="mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--accent)",
            background: "var(--accent-soft)",
            border: "1px solid var(--accent-border)",
            borderRadius: "var(--r-full)",
            padding: "2px 8px",
            display: "inline-block",
            marginBottom: 10,
          }}
        >
          Predicted
        </div>
      )}
      {/* Footer trio: Floor · Action · Ceiling */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Gradebook/GradeProjector.tsx
git commit -m "feat(gradebook): add isPredicted prop to GradeProjector"
```

---

## Task 2: Add `isPredicted` prop to `GradeCompositionBar` in Course.tsx

**Files:**
- Modify: `frontend/src/components/screens/Gradebook/Course.tsx`

The `GradeCompositionBar` function is defined inline in Course.tsx around line 503.

- [ ] **Step 1: Add `isPredicted` to GradeCompositionBar's props**

Find the props destructuring for `GradeCompositionBar` (the `function GradeCompositionBar({` block around line 503) and add `isPredicted`:

```ts
function GradeCompositionBar({
  categories,
  assignments,
  letterScale,
  currentPercent,
  onEditWeights,
  onSegmentClick,
  isPredicted = false,
}: {
  categories: GradeCategory[];
  assignments: GradedAssignment[];
  letterScale: LetterScaleTier[] | null;
  currentPercent: number | null;
  onEditWeights: () => void;
  onSegmentClick: (categoryId: string) => void;
  isPredicted?: boolean;
}) {
```

- [ ] **Step 2: Show PREDICTED badge in SectionHead when isPredicted**

Find `<SectionHead label="Composition"` (around line 579) and add a badge node to `meta`:

```tsx
      <SectionHead
        label="Composition"
        onEdit={onEditWeights}
        meta={
          <>
            {isPredicted && (
              <span
                className="mono"
                style={{
                  fontSize: 9,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--accent)",
                  background: "var(--accent-soft)",
                  border: "1px solid var(--accent-border)",
                  borderRadius: "var(--r-full)",
                  padding: "2px 8px",
                }}
              >
                Predicted
              </span>
            )}
            {current !== null && (
              <CompositionStatus
                current={current}
                currentTier={currentTier}
                projection={projection}
                scale={scale}
                isPredicted={isPredicted}
              />
            )}
          </>
        }
      />
```

- [ ] **Step 3: Add `isPredicted` to `CompositionStatus` and show suffix**

Find `function CompositionStatus({` (around line 936) and add the prop + suffix:

```ts
function CompositionStatus({
  current,
  currentTier,
  projection,
  scale,
  isPredicted = false,
}: {
  current: number;
  currentTier: string | undefined;
  projection: ReturnType<typeof projectGrade>;
  scale: LetterScaleTier[];
  isPredicted?: boolean;
}) {
```

Then in the JSX, after the `· {action}` span, add the predicted suffix:

```tsx
      <span
        style={{
          fontSize: 12,
          color: "var(--text-dim)",
          marginLeft: 4,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        · {action}
        {isPredicted && (
          <span style={{ color: "var(--text-muted)", marginLeft: 4 }}>(predicted)</span>
        )}
      </span>
```

- [ ] **Step 4: Add dashed border on the bar container when isPredicted**

Find the `<div` that wraps the bar (the one with `display: "flex", height: 46`, around line 623) and add a conditional border:

```tsx
        <div
          style={{
            display: "flex",
            height: 46,
            width: "100%",
            background: "var(--bg-subtle)",
            borderRadius: "var(--r-md)",
            overflow: "hidden",
            border: isPredicted
              ? "1.5px dashed var(--accent-border)"
              : "1px solid var(--border)",
          }}
        >
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/screens/Gradebook/Course.tsx
git commit -m "feat(gradebook): add isPredicted visual mode to GradeCompositionBar"
```

---

## Task 3: Create `GradePredictorPanel` component

**Files:**
- Create: `frontend/src/components/Gradebook/GradePredictorPanel.tsx`

- [ ] **Step 1: Create the file with its Props interface and toggle button**

```tsx
"use client";
import React from "react";
import type { GradedAssignment, GradeCategory } from "@/lib/types";

interface HypotheticalScore {
  earned: number;
  possible: number;
}

interface Props {
  open: boolean;
  onToggle: () => void;
  ungradedAssignments: GradedAssignment[];
  categories: GradeCategory[];
  hypotheticals: Map<string, HypotheticalScore>;
  onHypotheticalChange: (id: string, earned: number, possible: number) => void;
  onReset: () => void;
  predictedPercent: number | null;
  predictedLetter: string | null;
}

export function GradePredictorPanel({
  open,
  onToggle,
  ungradedAssignments,
  categories,
  hypotheticals,
  onHypotheticalChange,
  onReset,
  predictedPercent,
  predictedLetter,
}: Props) {
  if (ungradedAssignments.length === 0) return null;

  const catMap = React.useMemo(
    () => new Map(categories.map((c) => [c.id, c.name])),
    [categories],
  );

  const allHaveTotal = ungradedAssignments.every(
    (a) =>
      (a.points_possible !== null && (a.points_possible as number) > 0) ||
      (hypotheticals.get(a.id)?.possible ?? 0) > 0,
  );

  return (
    <div style={{ marginBottom: 32 }}>
      {/* Toggle row */}
      <button
        type="button"
        onClick={onToggle}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
          padding: "10px 0",
          background: "none",
          border: 0,
          borderTop: "1px solid var(--border)",
          borderBottom: open ? "none" : "1px solid var(--border)",
          cursor: "pointer",
          textAlign: "left",
          fontFamily: "var(--font-sans)",
        }}
      >
        <span
          style={{
            display: "inline-block",
            transition: "transform 0.2s",
            transform: open ? "rotate(0deg)" : "rotate(-90deg)",
            color: "var(--accent)",
            fontSize: 13,
          }}
        >
          ▾
        </span>
        <span style={{ fontSize: 13, fontWeight: 500, color: "var(--accent)" }}>
          Predict My Grade
        </span>
        <span style={{ fontSize: 11, color: "var(--text-dim)" }}>
          — set hypothetical scores for {ungradedAssignments.length} ungraded assignment
          {ungradedAssignments.length !== 1 ? "s" : ""}
        </span>
      </button>

      {open && (
        <PredictorBody
          ungradedAssignments={ungradedAssignments}
          catMap={catMap}
          hypotheticals={hypotheticals}
          onHypotheticalChange={onHypotheticalChange}
          onReset={onReset}
          predictedPercent={predictedPercent}
          predictedLetter={predictedLetter}
          allHaveTotal={allHaveTotal}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add the `PredictorBody` sub-component (result badge + assignment rows)**

Append to the same file:

```tsx
function PredictorBody({
  ungradedAssignments,
  catMap,
  hypotheticals,
  onHypotheticalChange,
  onReset,
  predictedPercent,
  predictedLetter,
  allHaveTotal,
}: {
  ungradedAssignments: GradedAssignment[];
  catMap: Map<string | null, string>;
  hypotheticals: Map<string, HypotheticalScore>;
  onHypotheticalChange: (id: string, earned: number, possible: number) => void;
  onReset: () => void;
  predictedPercent: number | null;
  predictedLetter: string | null;
  allHaveTotal: boolean;
}) {
  return (
    <div
      style={{
        background: "var(--bg-subtle)",
        border: "1px solid var(--border)",
        borderTop: "none",
        borderRadius: "0 0 var(--r-md) var(--r-md)",
        padding: "16px 20px",
      }}
    >
      {/* Result badge */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "10px 14px",
          background: "var(--bg-panel)",
          border: "1px solid var(--accent-border)",
          borderRadius: 8,
          marginBottom: 16,
        }}
      >
        <span
          className="mono"
          style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--text-muted)" }}
        >
          Predicted
        </span>
        {!allHaveTotal ? (
          <span style={{ fontSize: 13, color: "var(--text-dim)", fontStyle: "italic" }}>
            Set totals to enable prediction
          </span>
        ) : (
          <>
            <span
              style={{
                fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
                fontSize: 26,
                fontWeight: 500,
                color: "var(--accent)",
                letterSpacing: "-0.02em",
                lineHeight: 1,
              }}
            >
              {predictedLetter ?? "—"}
            </span>
            <span
              className="mono"
              style={{ fontSize: 18, fontWeight: 600, color: "var(--accent)", letterSpacing: "-0.02em" }}
            >
              {predictedPercent !== null ? `${predictedPercent.toFixed(1)}%` : "—"}
            </span>
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>(hypothetical)</span>
          </>
        )}
        <button
          type="button"
          onClick={onReset}
          className="btn btn--ghost btn--sm"
          style={{ marginLeft: "auto" }}
        >
          Reset All
        </button>
      </div>

      {/* Per-assignment slider rows */}
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {ungradedAssignments.map((a) => (
          <AssignmentSliderRow
            key={a.id}
            assignment={a}
            categoryName={catMap.get(a.category_id) ?? "Uncategorized"}
            hyp={hypotheticals.get(a.id) ?? null}
            onChange={(earned, possible) => onHypotheticalChange(a.id, earned, possible)}
          />
        ))}
      </div>

      <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 14, marginBottom: 0 }}>
        Scores shown are hypothetical only — nothing is saved until you enter grades above.
      </p>
    </div>
  );
}
```

- [ ] **Step 3: Add the `AssignmentSliderRow` sub-component**

Append to the same file:

```tsx
function AssignmentSliderRow({
  assignment,
  categoryName,
  hyp,
  onChange,
}: {
  assignment: GradedAssignment;
  categoryName: string;
  hyp: { earned: number; possible: number } | null;
  onChange: (earned: number, possible: number) => void;
}) {
  const hasSetTotal = assignment.points_possible !== null && (assignment.points_possible as number) > 0;
  const possible = hyp?.possible ?? (hasSetTotal ? (assignment.points_possible as number) : 100);
  const earned = hyp?.earned ?? Math.round(possible / 2);
  const sliderMax = possible > 0 ? possible : 100;

  const handleEarnedChange = (val: number) => {
    const clamped = Math.max(0, val);
    onChange(clamped, possible);
  };

  const handlePossibleChange = (val: number) => {
    if (val <= 0) return;
    const newEarned = Math.min(earned, val);
    onChange(newEarned, val);
  };

  const dueDisplay = assignment.due_date
    ? `Due ${assignment.due_date.slice(5, 7)}/${assignment.due_date.slice(8, 10)}/${assignment.due_date.slice(0, 4)}`
    : "No Due Date";

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) minmax(160px, 220px) auto",
        gap: 12,
        alignItems: "center",
        padding: "10px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      {/* Name + meta */}
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
            fontSize: 13,
            fontWeight: 500,
            color: "var(--text)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {assignment.title}
        </div>
        <div
          className="mono"
          style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 2 }}
        >
          {categoryName}
          {assignment.due_date ? ` · ${dueDisplay}` : ""}
          {!hasSetTotal && !hyp?.possible && (
            <span style={{ color: "var(--warn)", marginLeft: 4 }}>· no total set</span>
          )}
        </div>
      </div>

      {/* Slider */}
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <input
          type="range"
          min={0}
          max={sliderMax}
          step="any"
          value={earned}
          onChange={(e) => handleEarnedChange(Number(e.target.value))}
          style={{ width: "100%", accentColor: "var(--accent)" }}
        />
        <div
          className="mono"
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 9,
            color: "var(--text-muted)",
          }}
        >
          <span>0</span>
          <span>{hasSetTotal || hyp?.possible ? `${possible} pts` : "— pts"}</span>
        </div>
      </div>

      {/* Earned / Total inputs */}
      <div style={{ display: "flex", alignItems: "center", gap: 4, whiteSpace: "nowrap" }}>
        <input
          type="number"
          value={earned}
          min={0}
          step="any"
          onChange={(e) => handleEarnedChange(Number(e.target.value))}
          style={{
            width: 52,
            padding: "4px 6px",
            border: "1px solid var(--border)",
            borderRadius: 6,
            textAlign: "right",
            fontSize: 13,
            fontFamily: "var(--font-mono)",
          }}
        />
        <span style={{ color: "var(--text-muted)", fontSize: 12 }}>/</span>
        {hasSetTotal ? (
          <span
            className="mono"
            style={{ fontSize: 13, color: "var(--text-muted)", minWidth: 32 }}
          >
            {assignment.points_possible}
          </span>
        ) : (
          <input
            type="number"
            value={hyp?.possible ?? ""}
            min={1}
            step="any"
            placeholder="—"
            onChange={(e) => {
              const v = Number(e.target.value);
              if (v > 0) handlePossibleChange(v);
            }}
            style={{
              width: 46,
              padding: "4px 6px",
              border: "1px dashed var(--border)",
              borderRadius: 6,
              textAlign: "right",
              fontSize: 12,
              fontFamily: "var(--font-mono)",
              background: "var(--bg)",
            }}
          />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Gradebook/GradePredictorPanel.tsx
git commit -m "feat(gradebook): add GradePredictorPanel component"
```

---

## Task 4: Wire predictor state into Course.tsx

**Files:**
- Modify: `frontend/src/components/screens/Gradebook/Course.tsx`

- [ ] **Step 1: Import `GradePredictorPanel`**

Add to the imports block at the top of Course.tsx:

```ts
import { GradePredictorPanel } from "@/components/Gradebook/GradePredictorPanel";
```

Also add `tierFor` to the existing import from GradeProjector (it's already defined in Course.tsx locally, so no change needed).

- [ ] **Step 2: Add predictor state to `GradebookCourseScreen`**

Inside `GradebookCourseScreen`, after the existing `const [assignModal, ...]` state (around line 109), add:

```ts
  const [predictorOpen, setPredictorOpen] = React.useState(false);
  const [hypotheticals, setHypotheticals] = React.useState<
    Map<string, { earned: number; possible: number }>
  >(new Map());
```

- [ ] **Step 3: Derive `augmentedAssignments` and predictor outputs**

After the `data` state is declared, add a `useMemo` that derives the augmented array and predicted values. Place this after the existing `focusCategory` callback (around line 209):

```ts
  const ungradedAssignments = React.useMemo(
    () => (data?.assignments ?? []).filter((a) => a.points_earned === null),
    [data],
  );

  const augmentedAssignments = React.useMemo(() => {
    if (!predictorOpen || !data) return data?.assignments ?? [];
    return data.assignments.map((a) => {
      const hyp = hypotheticals.get(a.id);
      if (a.points_earned !== null || !hyp) return a;
      return {
        ...a,
        points_earned: hyp.earned,
        points_possible: hyp.possible > 0 ? hyp.possible : a.points_possible,
      };
    });
  }, [predictorOpen, data, hypotheticals]);

  const predictedProjection = React.useMemo(
    () =>
      predictorOpen && data
        ? projectGrade(data.categories, augmentedAssignments)
        : null,
    [predictorOpen, data, augmentedAssignments],
  );

  const predictedLetter = React.useMemo(() => {
    if (!predictedProjection || !data) return null;
    // DEFAULT_SCALE is already defined at the top of Course.tsx
    const scale =
      data.letter_scale && data.letter_scale.length > 0
        ? data.letter_scale
        : DEFAULT_SCALE;
    const pct = predictedProjection.current;
    return (
      [...scale].sort((a, b) => b.min - a.min).find((t) => pct >= t.min)
        ?.letter ?? null
    );
  }, [predictedProjection, data]);
```

- [ ] **Step 4: Add `handleHypotheticalChange` and `handleResetPredictor` callbacks**

After the `focusCategory` callback:

```ts
  const handleHypotheticalChange = React.useCallback(
    (id: string, earned: number, possible: number) => {
      setHypotheticals((prev) => {
        const next = new Map(prev);
        next.set(id, { earned, possible });
        return next;
      });
    },
    [],
  );

  const handleResetPredictor = React.useCallback(() => {
    setHypotheticals(new Map());
  }, []);

  const handleTogglePredictor = React.useCallback(() => {
    setPredictorOpen((prev) => {
      if (prev) setHypotheticals(new Map()); // reset on close
      return !prev;
    });
  }, []);
```

- [ ] **Step 5: Pass `isPredicted` and `augmentedAssignments` to `GradeCompositionBar`**

Find the `<GradeCompositionBar` usage (around line 281) and update it:

```tsx
              <GradeCompositionBar
                categories={data.categories}
                assignments={predictorOpen ? augmentedAssignments : data.assignments}
                letterScale={data.letter_scale}
                currentPercent={predictorOpen ? (predictedProjection?.current ?? null) : data.percent}
                onEditWeights={() => setEditWeights(true)}
                onSegmentClick={focusCategory}
                isPredicted={predictorOpen}
              />
```

- [ ] **Step 6: Render `GradePredictorPanel` between the composition bar and assignment list**

Find the render block (around line 289) and insert the panel between `GradeCompositionBar` and `AssignmentList`:

```tsx
              <GradeCompositionBar
                categories={data.categories}
                assignments={predictorOpen ? augmentedAssignments : data.assignments}
                letterScale={data.letter_scale}
                currentPercent={predictorOpen ? (predictedProjection?.current ?? null) : data.percent}
                onEditWeights={() => setEditWeights(true)}
                onSegmentClick={focusCategory}
                isPredicted={predictorOpen}
              />
              <GradePredictorPanel
                open={predictorOpen}
                onToggle={handleTogglePredictor}
                ungradedAssignments={ungradedAssignments}
                categories={data.categories}
                hypotheticals={hypotheticals}
                onHypotheticalChange={handleHypotheticalChange}
                onReset={handleResetPredictor}
                predictedPercent={predictedProjection?.current ?? null}
                predictedLetter={predictedLetter}
              />
              <AssignmentList
```

- [ ] **Step 7: Clear hypothetical when a real grade is saved**

In `onEditGrade` (around line 188), after the optimistic update line, clear the hypothetical for that assignment:

```ts
  const onEditGrade = React.useCallback(
    async (id: string, points: number | null) => {
      if (!userId || !data) return;
      const prev = data;
      // Clear any hypothetical for this assignment now that it has a real score
      setHypotheticals((h) => {
        if (!h.has(id)) return h;
        const next = new Map(h);
        next.delete(id);
        return next;
      });
      setData({
        ...data,
        assignments: data.assignments.map((a) =>
          a.id === id ? { ...a, points_earned: points } : a,
        ),
      });
      try {
        await updateGradedAssignment(userId, id, { points_earned: points });
        await refresh();
      } catch (err: any) {
        setData(prev);
        toast.error(`Couldn't save: ${err.message}`);
      }
    },
    [userId, data, refresh, toast],
  );
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/screens/Gradebook/Course.tsx
git commit -m "feat(gradebook): wire GradePredictorPanel into course page"
```

---

## Task 5: Smoke test

- [ ] **Step 1: Start frontend dev server**

```bash
cd frontend && npm run dev
```

- [ ] **Step 2: Open a course that has ungraded assignments**

Navigate to `/gradebook/<course-id>`. Verify the "Predict My Grade" toggle appears below the composition bar.

- [ ] **Step 3: Expand the panel and move a slider**

Confirm: slider moves → earned input updates → composition bar rerenders with "PREDICTED" badge and dashed border → letter/percentage in bar header updates.

- [ ] **Step 4: Test assignment with no `points_possible`**

If a course has an assignment with no total set, confirm the editable total field (dashed border) appears and that the assignment is excluded from prediction until a total is entered.

- [ ] **Step 5: Test Reset All**

Click "Reset All" — all sliders should return to midpoint defaults.

- [ ] **Step 6: Close the panel**

Click the toggle again — bar returns to real data, PREDICTED badge disappears.

- [ ] **Step 7: Enter a real grade while predictor is open**

Enter a grade in the assignment list input while the predictor is open — confirm the hypothetical for that assignment clears and the predictor updates.

- [ ] **Step 8: Final commit**

```bash
git add -A
git commit -m "feat(gradebook): grade predictor panel complete"
```
