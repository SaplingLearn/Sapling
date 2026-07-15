"use client";
import React from "react";
import type { GradedAssignment, GradeCategory } from "@/lib/types";

interface HypotheticalScore {
  earned: number;
  possible: number;
  curveClassMean: number | null;  // overrides stored assignment class stats
  curveClassSd: number | null;
}

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
  const hasSetTotal = assignment.points_possible !== null && (assignment.points_possible as number) > 0;
  const possible = hyp?.possible ?? (hasSetTotal ? (assignment.points_possible as number) : 100);
  const earned = hyp?.earned ?? Math.round(possible / 2);
  const sliderMax = possible > 0 ? possible : 100;
  // Predictor override takes priority; falls back to stored assignment class stats
  const curveClassMean = hyp?.curveClassMean !== undefined ? hyp.curveClassMean : (assignment.curve_class_mean ?? null);
  const curveClassSd = hyp?.curveClassSd !== undefined ? hyp.curveClassSd : (assignment.curve_class_sd ?? null);

  const emit = (patch: Partial<HypotheticalScore>) =>
    onChange({ earned, possible, curveClassMean, curveClassSd, ...patch });

  const parseFinite = (s: string): number | null => {
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  };

  const handleEarnedChange = (val: number) => {
    const clamped = Math.max(0, Math.min(val, possible));
    emit({ earned: clamped });
  };

  const handlePossibleChange = (val: number) => {
    if (val <= 0) return;
    emit({ possible: val, earned: Math.min(earned, val) });
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
          {assignment.due_date ? ` · ${dueDisplay}` : ""}
        </div>
        {!hasSetTotal && !hyp?.possible && (
          <div
            className="mono"
            style={{ fontSize: 11, color: "var(--err)", marginTop: 3, fontWeight: 500 }}
          >
            ⚠ No Total Score
          </div>
        )}
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
          onChange={(e) => { const v = parseFinite(e.target.value); if (v !== null) handleEarnedChange(v); }}
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

      {/* Inline class stats — shown when curved mode is on; overrides stored assignment stats */}
      {isCurved && (
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
          <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}>
            <span style={{ color: "var(--text-dim)" }}>Class Avg</span>
            <input
              type="number"
              min={0}
              max={100}
              step="any"
              placeholder={assignment.curve_class_mean != null ? `${(assignment.curve_class_mean * 100).toFixed(0)}` : "—"}
              value={hyp?.curveClassMean != null ? (hyp.curveClassMean * 100).toFixed(0) : ""}
              onChange={(e) => {
                if (e.target.value === "") { emit({ curveClassMean: null }); return; }
                const v = parseFinite(e.target.value);
                if (v !== null) emit({ curveClassMean: v / 100 });
              }}
              style={{
                width: 44, padding: "2px 4px", border: "1px solid var(--accent-border)",
                borderRadius: 4, textAlign: "right", fontSize: 11,
                fontFamily: "var(--font-mono)", background: "var(--accent-soft)",
              }}
            />
            <span style={{ color: "var(--text-muted)" }}>%</span>
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}>
            <span style={{ color: "var(--text-dim)" }}>SD</span>
            <input
              type="number"
              min={0}
              max={100}
              step="any"
              placeholder={assignment.curve_class_sd != null ? `${(assignment.curve_class_sd * 100).toFixed(0)}` : "—"}
              value={hyp?.curveClassSd != null ? (hyp.curveClassSd * 100).toFixed(0) : ""}
              onChange={(e) => {
                if (e.target.value === "") { emit({ curveClassSd: null }); return; }
                const v = parseFinite(e.target.value);
                if (v !== null) emit({ curveClassSd: v / 100 });
              }}
              style={{
                width: 44, padding: "2px 4px", border: "1px solid var(--accent-border)",
                borderRadius: 4, textAlign: "right", fontSize: 11,
                fontFamily: "var(--font-mono)", background: "var(--accent-soft)",
              }}
            />
            <span style={{ color: "var(--text-muted)" }}>%</span>
          </label>
          {(curveClassMean !== null || curveClassSd !== null) && (
            <span className="mono" style={{ fontSize: 10, color: "var(--accent)", marginLeft: 2 }}>
              ✓ Curve Active
            </span>
          )}
        </div>
      )}
    </div>
  );
}
