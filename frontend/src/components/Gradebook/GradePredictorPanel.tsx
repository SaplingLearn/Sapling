"use client";
import React from "react";
import type { GradedAssignment, GradeCategory } from "@/lib/types";
import {
  clampEarned,
  dueSuffix,
  fractionToPercentText,
  parseCurvePercent,
  parseFinite,
  resolveSliderRow,
  type HypotheticalScore,
  type SliderRowValues,
} from "./predictorRow";
import { cn } from "@/lib/cn";

interface Props {
  open: boolean;
  onToggle: () => void;
  ungradedAssignments: GradedAssignment[];
  categories: GradeCategory[];
  hypotheticals: Map<string, HypotheticalScore>;
  onHypotheticalChange: (id: string, score: HypotheticalScore) => void;
  onReset: () => void;
  predictedPercent: number | null;
  predictedLetter: string | null;
  isCurved: boolean;
  predictorCurveEnabled: boolean;
  onTogglePredictorCurve: () => void;
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
  isCurved,
  predictorCurveEnabled,
  onTogglePredictorCurve,
}: Props) {
  const catMap = React.useMemo(
    () => new Map(categories.map((c) => [c.id, c.name])),
    [categories],
  );

  const allHaveTotal =
    ungradedAssignments.length > 0 &&
    ungradedAssignments.every(
      (a) =>
        (a.points_possible !== null && (a.points_possible as number) > 0) ||
        (hypotheticals.get(a.id)?.possible ?? 0) > 0,
    );

  if (ungradedAssignments.length === 0) {
    return (
      <div
        className="border-t border-t-border py-2.5 px-0 text-sm text-text-muted font-sans"
      >
        Predict your grade by adding an unscored assignment.
      </div>
    );
  }

  return (
    <div className="mb-(--pad-xl)">
      {/* Toggle row */}
      <button
        type="button"
        onClick={onToggle}
        className={cn("flex items-center gap-2 w-full py-2.5 px-0 [background:none] border-0 border-t border-t-border cursor-pointer text-left font-sans", open ? "border-b-0" : "border-b border-b-border")}
      >
        <span
          className={cn("inline-block [transition:transform_0.2s] text-accent text-md", open ? "[transform:rotate(0deg)]" : "[transform:rotate(-90deg)]")}
        >
          ▾
        </span>
        <span className="text-md font-medium text-accent">
          Predict My Grade
        </span>
        <span className="text-xs text-text-dim">
          Set hypothetical scores for {ungradedAssignments.length} ungraded assignment
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
          isCurved={isCurved}
          predictorCurveEnabled={predictorCurveEnabled}
          onTogglePredictorCurve={onTogglePredictorCurve}
        />
      )}
    </div>
  );
}

function PredictorBody({
  ungradedAssignments,
  catMap,
  hypotheticals,
  onHypotheticalChange,
  onReset,
  predictedPercent: _predictedPercent,
  predictedLetter: _predictedLetter,
  allHaveTotal,
  isCurved,
  predictorCurveEnabled,
  onTogglePredictorCurve,
}: {
  ungradedAssignments: GradedAssignment[];
  catMap: Map<string | null, string>;
  hypotheticals: Map<string, HypotheticalScore>;
  onHypotheticalChange: (id: string, score: HypotheticalScore) => void;
  onReset: () => void;
  predictedPercent: number | null;
  predictedLetter: string | null;
  allHaveTotal: boolean;
  isCurved: boolean;
  predictorCurveEnabled: boolean;
  onTogglePredictorCurve: () => void;
}) {
  return (
    <div
      className="bg-bg-subtle border border-border rounded-md py-(--pad-md) px-(--pad-lg) mt-2"
    >
      {/* Header */}
      <div
        className="flex items-center justify-between mb-4 pb-3 border-b border-b-border"
      >
        <div className="flex items-center gap-2.5">
          <span
            className="mono text-sm text-text-muted"
          >
            {!allHaveTotal ? "Set totals to enable prediction" : "Hypothetical Scores"}
          </span>
          {isCurved && (
            <div className="flex bg-bg rounded-[20px] p-0.5 border border-border">
              {(["Raw", "Curved"] as const).map((mode) => {
                const active = mode === "Curved" ? predictorCurveEnabled : !predictorCurveEnabled;
                return (
                  <button
                    key={mode}
                    type="button"
                    onClick={active ? undefined : onTogglePredictorCurve}
                    className={cn("py-[3px] px-2.5 rounded-[18px] text-2xs font-medium border-0 font-sans", active ? "bg-accent" : "bg-transparent", active ? "text-accent-fg" : "text-text-dim", active ? "cursor-default" : "cursor-pointer")}
                  >
                    {mode}
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={onReset}
          className="btn py-1 px-3 text-sm bg-accent-fg"
        >
          Reset All
        </button>
      </div>

      {/* Per-assignment slider rows */}
      <div className="flex flex-col gap-0.5">
        {ungradedAssignments.map((a) => (
          <AssignmentSliderRow
            key={a.id}
            assignment={a}
            categoryName={catMap.get(a.category_id) ?? "Uncategorized"}
            hyp={hypotheticals.get(a.id) ?? null}
            isCurved={predictorCurveEnabled}
            onChange={(score) => onHypotheticalChange(a.id, score)}
          />
        ))}
      </div>

      <p className="text-xs text-text-muted mt-3.5 mb-0">
        Scores shown are hypothetical only. Nothing is saved until you enter grades above.
      </p>
    </div>
  );
}

type EmitScore = (patch: Partial<HypotheticalScore>) => void;

function AssignmentSliderRow({
  assignment,
  categoryName,
  hyp,
  isCurved,
  onChange,
}: {
  assignment: GradedAssignment;
  categoryName: string;
  hyp: HypotheticalScore | null;
  isCurved: boolean;
  onChange: (score: HypotheticalScore) => void;
}) {
  // Predictor override takes priority; falls back to stored assignment class stats
  const row = resolveSliderRow(assignment, hyp);
  const { earned, possible, curveClassMean, curveClassSd } = row;

  const emit: EmitScore = (patch) =>
    onChange({ earned, possible, curveClassMean, curveClassSd, ...patch });

  const handleEarnedChange = (val: number) => {
    emit({ earned: clampEarned(val, possible) });
  };

  const handlePossibleChange = (val: number) => {
    if (val <= 0) return;
    emit({ possible: val, earned: Math.min(earned, val) });
  };

  // The row's slots are filled by plain render functions (called, never
  // mounted as components) so the element tree is exactly the inline one.
  return (
    <div
      className="grid grid-cols-[minmax(0,_1fr)_minmax(160px,_220px)_auto] gap-3 items-center py-2.5 px-0 border-b border-b-border"
    >
      {renderRowMeta(assignment, categoryName, row)}
      {renderEarnedSlider(row, handleEarnedChange)}
      {renderScoreInputs(assignment, hyp, row, handleEarnedChange, handlePossibleChange)}
      {/* Inline class stats — shown when curved mode is on; overrides stored assignment stats */}
      {isCurved && renderCurveStats(assignment, hyp, row, emit)}
    </div>
  );
}

/** Name + meta column. */
function renderRowMeta(assignment: GradedAssignment, categoryName: string, row: SliderRowValues) {
  return (
    <div className="min-w-0">
      <div
        className="font-serif text-md font-medium text-text overflow-hidden text-ellipsis whitespace-nowrap"
      >
        {assignment.title}
      </div>
      <div
        className="mono text-xs text-text-dim mt-0.5"
      >
        {categoryName}
        {dueSuffix(assignment.due_date)}
      </div>
      {!row.hasTotal && (
        <div
          className="mono text-xs text-err mt-[3px] font-medium"
        >
          ⚠ No Total Score
        </div>
      )}
    </div>
  );
}

/** Slider column. */
function renderEarnedSlider(row: SliderRowValues, onEarned: (val: number) => void) {
  return (
    <div className="flex flex-col gap-[3px]">
      <input
        type="range"
        min={0}
        max={row.sliderMax}
        step="any"
        value={row.earned}
        onChange={(e) => onEarned(Number(e.target.value))}
        className="w-full accent-accent"
      />
      <div
        className="mono flex justify-between text-[9px] text-text-muted"
      >
        <span>0</span>
        <span>{row.hasTotal ? `${row.possible} pts` : "— pts"}</span>
      </div>
    </div>
  );
}

/** Earned / Total inputs column. */
function renderScoreInputs(
  assignment: GradedAssignment,
  hyp: HypotheticalScore | null,
  row: SliderRowValues,
  onEarned: (val: number) => void,
  onPossible: (val: number) => void,
) {
  return (
    <div className="flex items-center gap-1 whitespace-nowrap">
      <input
        type="number"
        value={row.earned}
        min={0}
        step="any"
        onChange={(e) => { const v = parseFinite(e.target.value); if (v !== null) onEarned(v); }}
        className="w-13 py-1 px-1.5 border border-border rounded-sm text-right text-md font-sans"
      />
      <span className="text-text-muted text-sm">/</span>
      {row.hasSetTotal ? (
        <span
          className="mono text-md text-text-muted min-w-8"
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
            if (v > 0) onPossible(v);
          }}
          className="w-11.5 py-1 px-1.5 border border-dashed border-border rounded-sm text-right text-sm font-sans bg-bg"
        />
      )}
    </div>
  );
}

/** Bell-curve class-stat row (full grid width). */
function renderCurveStats(
  assignment: GradedAssignment,
  hyp: HypotheticalScore | null,
  row: SliderRowValues,
  emit: EmitScore,
) {
  return (
    <div
      className="[grid-column:1_/_-1] flex gap-2 items-center mt-1.5 pt-1.5 [border-top:1px_dashed_var(--border)]"
    >
      <span className="mono text-2xs text-text-muted whitespace-nowrap">
        Bell Curve:
      </span>
      {renderCurveField("Class Avg", assignment.curve_class_mean, hyp?.curveClassMean, (v) => emit({ curveClassMean: v }))}
      {renderCurveField("SD", assignment.curve_class_sd, hyp?.curveClassSd, (v) => emit({ curveClassSd: v }))}
      {(row.curveClassMean !== null || row.curveClassSd !== null) && (
        <span className="mono text-2xs text-accent ml-0.5">
          ✓ Curve Active
        </span>
      )}
    </div>
  );
}

/** One class-stat percent input: stored stat as placeholder, override as value. */
function renderCurveField(
  label: string,
  stored: number | null,
  override: number | null | undefined,
  onValue: (v: number | null) => void,
) {
  return (
    <label className="flex items-center gap-1 text-xs">
      <span className="text-text-dim">{label}</span>
      <input
        type="number"
        min={0}
        max={100}
        step="any"
        placeholder={fractionToPercentText(stored, "—")}
        value={fractionToPercentText(override, "")}
        onChange={(e) => {
          const v = parseCurvePercent(e.target.value);
          if (v !== undefined) onValue(v);
        }}
        className="w-11 py-0.5 px-1 border border-accent-border rounded-xs text-right text-xs font-sans bg-accent-soft"
      />
      <span className="text-text-muted">%</span>
    </label>
  );
}
