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
  const catMap = React.useMemo(
    () => new Map(categories.map((c) => [c.id, c.name])),
    [categories],
  );

  const allHaveTotal = ungradedAssignments.every(
    (a) =>
      (a.points_possible !== null && (a.points_possible as number) > 0) ||
      (hypotheticals.get(a.id)?.possible ?? 0) > 0,
  );

  if (ungradedAssignments.length === 0) return null;

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

function AssignmentSliderRow({
  assignment,
  categoryName,
  hyp,
  onChange,
}: {
  assignment: GradedAssignment;
  categoryName: string;
  hyp: HypotheticalScore | null;
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
