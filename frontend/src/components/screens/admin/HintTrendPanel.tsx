"use client";

/**
 * Admin learning-loop: hints to criterion (spec §10's htc_k KPI). Admin only —
 * nothing here reaches a student. Reads `htc_k_trend` of
 * GET /api/admin/analytics/learning-loop (services/admin/analytics/
 * learning_loop.py::_htc_k_trend): per concept, the mean hint rung students
 * had reached (`max_rung_used`, H0 = no hint) on the steps they got right, per
 * ISO week of the KPI window ending at the range's end. As students learn a
 * concept they should need less help to get it right, so the mean should
 * FALL. Every figure carries its n (the week's correct steps).
 *
 * Concepts that are getting worse come first: a rising concept is the one to
 * look at. A concept with only one week in the window cannot have a trend and
 * is counted, not listed.
 */

import React from "react";
import type { LoopConceptTrend } from "@/lib/types";

type Direction = LoopConceptTrend["direction"];

const th: React.CSSProperties = {
  textAlign: "left", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em",
  color: "var(--text-muted)", padding: "4px 8px",
};
const thNum: React.CSSProperties = { ...th, textAlign: "right" };
const td: React.CSSProperties = { fontSize: 13, padding: "6px 8px", borderTop: "1px solid var(--border)" };
const tdNum: React.CSSProperties = { ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" };
const muted: React.CSSProperties = { color: "var(--text-muted)", fontSize: 13, margin: "0 0 12px" };

/** Worst first: the concepts needing more help to get it right lead. */
const ORDER: Direction[] = ["rising", "flat", "falling", "insufficient"];

const LABEL: Record<Direction, string> = {
  rising: "Rising",
  flat: "Flat",
  falling: "Falling",
  insufficient: "One week only",
};

const COLOR: Record<Direction, string> = {
  rising: "var(--err)",
  flat: "var(--text-muted)",
  falling: "var(--accent)",
  insufficient: "var(--text-muted)",
};

/** "H1.5": a mean rung, to one decimal. */
export const rung = (value: number) => `H${Number(value.toFixed(1))}`;

/** How many concepts move each way, in ORDER. */
export function directionCounts(trend: LoopConceptTrend[]): Record<Direction, number> {
  const counts: Record<Direction, number> = { rising: 0, flat: 0, falling: 0, insufficient: 0 };
  for (const concept of trend) counts[concept.direction] += 1;
  return counts;
}

/** The concepts with a trend (two weeks or more), worst first, then by id. */
export function trendRows(trend: LoopConceptTrend[]): LoopConceptTrend[] {
  return trend
    .filter((concept) => concept.direction !== "insufficient")
    .sort((a, b) => ORDER.indexOf(a.direction) - ORDER.indexOf(b.direction) || a.concept_id.localeCompare(b.concept_id));
}

function Row({ concept }: { concept: LoopConceptTrend }) {
  const first = concept.weeks[0];
  const last = concept.weeks[concept.weeks.length - 1];
  const steps = concept.weeks.reduce((sum, week) => sum + week.steps, 0);
  return (
    <tr data-testid={`admin-loop-htc-row-${concept.concept_id}`}>
      <td style={td}><code>{concept.concept_id}</code></td>
      <td style={tdNum}>{concept.weeks.length}</td>
      <td style={tdNum}>{rung(first.mean_rung)} ({first.steps})</td>
      <td style={tdNum}>{rung(last.mean_rung)} ({last.steps})</td>
      <td style={tdNum}>{steps}</td>
      <td style={{ ...td, color: COLOR[concept.direction], fontWeight: 600 }}>{LABEL[concept.direction]}</td>
    </tr>
  );
}

/** The section for LearningLoopPanelBody. */
export function HintTrendPanel({ trend }: { trend: LoopConceptTrend[] }) {
  const counts = directionCounts(trend);
  const rows = trendRows(trend);
  return (
    <section data-testid="admin-loop-htc-trend">
      <h3 className="h-serif" style={{ fontSize: 15, margin: "16px 0 8px" }}>Do students need fewer hints?</h3>
      <p style={muted}>
        Per concept and week, the mean hint level (H0 = no hint) students had reached on the steps they got
        right, over the last weeks of the range. It should fall as students learn the concept. First and last
        are the window&apos;s first and last weeks with such steps, each with its count of steps.
      </p>
      {trend.length === 0 ? (
        <p data-testid="admin-loop-htc-empty" style={muted}>No correct steps with a hint level in this range.</p>
      ) : (
        <>
          <p data-testid="admin-loop-htc-summary" style={{ fontSize: 13, margin: "0 0 8px" }}>
            {ORDER.map((direction, i) => (
              <React.Fragment key={direction}>
                {i > 0 && " · "}
                <span style={{ color: COLOR[direction] }}>{LABEL[direction]}</span> {counts[direction]}
              </React.Fragment>
            ))}
          </p>
          {rows.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={th}>Concept</th>
                    <th style={thNum}>Weeks</th>
                    <th style={thNum}>First week</th>
                    <th style={thNum}>Last week</th>
                    <th style={thNum}>Steps</th>
                    <th style={th}>Trend</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((concept) => <Row key={concept.concept_id} concept={concept} />)}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
