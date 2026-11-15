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
        style={{
          borderTop: "1px solid var(--border)",
          padding: "10px 0",
          fontSize: 12,
          color: "var(--text-muted)",
          fontFamily: "var(--font-sans)",
        }}
      >
        Predict your grade by adding an unscored assignment.
      </div>
    );
  }

  return (
    <div style={{ marginBottom: "var(--pad-xl)" }}>
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
      style={{
        background: "var(--bg-subtle)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-md)",
        padding: "var(--pad-md) var(--pad-lg)",
        marginTop: 8,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
          paddingBottom: 12,
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span
            className="mono"
            style={{ fontSize: 10, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--text-muted)" }}
          >
            {!allHaveTotal ? "Set totals to enable prediction" : "Hypothetical Scores"}
          </span>
          {isCurved && (
            <div style={{ display: "flex", background: "var(--bg)", borderRadius: 20, padding: 2, border: "1px solid var(--border)" }}>
              {(["Raw", "Curved"] as const).map((mode) => {
                const active = mode === "Curved" ? predictorCurveEnabled : !predictorCurveEnabled;
                return (
                  <button
                    key={mode}
                    type="button"
                    onClick={active ? undefined : onTogglePredictorCurve}
                    style={{
                      padding: "3px 10px",
                      borderRadius: 18,
                      fontSize: 10,
                      fontWeight: 500,
                      background: active ? "var(--accent)" : "transparent",
                      color: active ? "#fff" : "var(--text-dim)",
                      border: 0,
                      cursor: active ? "default" : "pointer",
                      fontFamily: "var(--font-sans)",
                    }}
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
          className="btn"
          style={{ padding: "4px 12px", fontSize: 12, background: "#fff" }}
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
            isCurved={predictorCurveEnabled}
            onChange={(score) => onHypotheticalChange(a.id, score)}
          />
        ))}
      </div>

      <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 14, marginBottom: 0 }}>
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
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) minmax(160px, 220px) auto",
        gap: 12,
        alignItems: "center",
        padding: "10px 0",
        borderBottom: "1px solid var(--border)",
      }}
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
    <div style={{ minWidth: 0 }}>
      <div
        style={{
          fontFamily: "var(--font-serif)",
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
        {dueSuffix(assignment.due_date)}
      </div>
      {!row.hasTotal && (
        <div
          className="mono"
          style={{ fontSize: 11, color: "var(--err)", marginTop: 3, fontWeight: 500 }}
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
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <input
        type="range"
        min={0}
        max={row.sliderMax}
        step="any"
        value={row.earned}
        onChange={(e) => onEarned(Number(e.target.value))}
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
    <div style={{ display: "flex", alignItems: "center", gap: 4, whiteSpace: "nowrap" }}>
      <input
        type="number"
        value={row.earned}
        min={0}
        step="any"
        onChange={(e) => { const v = parseFinite(e.target.value); if (v !== null) onEarned(v); }}
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
      {row.hasSetTotal ? (
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
            if (v > 0) onPossible(v);
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
      style={{
        gridColumn: "1 / -1",
        display: "flex",
        gap: 8,
        alignItems: "center",
        marginTop: 6,
        paddingTop: 6,
        borderTop: "1px dashed var(--border)",
      }}
    >
      <span className="mono" style={{ fontSize: 10, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
        Bell Curve:
      </span>
      {renderCurveField("Class Avg", assignment.curve_class_mean, hyp?.curveClassMean, (v) => emit({ curveClassMean: v }))}
      {renderCurveField("SD", assignment.curve_class_sd, hyp?.curveClassSd, (v) => emit({ curveClassSd: v }))}
      {(row.curveClassMean !== null || row.curveClassSd !== null) && (
        <span className="mono" style={{ fontSize: 10, color: "var(--accent)", marginLeft: 2 }}>
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
    <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}>
      <span style={{ color: "var(--text-dim)" }}>{label}</span>
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
        style={{
          width: 44, padding: "2px 4px", border: "1px solid var(--accent-border)",
          borderRadius: 4, textAlign: "right", fontSize: 11,
          fontFamily: "var(--font-mono)", background: "var(--accent-soft)",
        }}
      />
      <span style={{ color: "var(--text-muted)" }}>%</span>
    </label>
  );
}
