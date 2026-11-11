"use client";

/**
 * Admin learning-loop: multi-concept items (spec §13 A141, flag
 * `multi_concept_items`). Admin only — nothing here reaches a student. Reads
 * the additive `multi_concept` field of GET /api/admin/analytics/learning-loop
 * (learning/multi_concept_report.py): per course and overall, how many items
 * that combine a concept with its prerequisites are stored (and held), how
 * many were served in the range, and how students did on them — answered,
 * right, right with no help, by how many students, and the share right with
 * its 95% interval. Every figure carries its n; a rate with nothing behind it
 * reads "—", never a zero.
 */

import React from "react";
import type { LoopMultiConcept, LoopMultiConceptBlock } from "@/lib/types";

const th: React.CSSProperties = {
  textAlign: "left", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em",
  color: "var(--text-muted)", padding: "4px 8px",
};
const thNum: React.CSSProperties = { ...th, textAlign: "right" };
const td: React.CSSProperties = { fontSize: 13, padding: "6px 8px", borderTop: "1px solid var(--border)" };
const tdNum: React.CSSProperties = { ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" };
const muted: React.CSSProperties = { color: "var(--text-muted)", fontSize: 13, margin: "0 0 12px" };

const pct = (v: number | null) => (v == null ? "—" : `${Number((v * 100).toFixed(1))}%`);

/** "61.5% (40.2–79.1%) of 26", or "—" when nothing was answered. */
export function rateWithCi(b: LoopMultiConceptBlock): string {
  if (b.correct_rate == null) return "—";
  const ci = b.correct_ci_low != null && b.correct_ci_high != null
    ? ` (${pct(b.correct_ci_low)}–${pct(b.correct_ci_high)})`
    : "";
  return `${pct(b.correct_rate)}${ci} of ${b.answered}`;
}

function Row({ block, label, testid }: { block: LoopMultiConceptBlock; label: string; testid: string }) {
  return (
    <tr data-testid={testid}>
      <td style={td}>{label}</td>
      <td style={tdNum}>{block.items}{block.held ? ` (${block.held} held)` : ""}</td>
      <td style={tdNum}>{block.served}</td>
      <td style={tdNum}>{block.answered}</td>
      <td style={tdNum}>{block.answered ? `${block.unassisted_correct} of ${block.unassisted}` : "—"}</td>
      <td style={tdNum}>{block.students}</td>
      <td style={tdNum}>{rateWithCi(block)}</td>
    </tr>
  );
}

/** The section for LearningLoopPanelBody. `data` undefined: the backend
 *  predates A141 (nothing renders); null: its reads failed for this range. */
export function MultiConceptPanel({ data }: { data: LoopMultiConcept | null | undefined }) {
  if (data === undefined) return null;
  const heading = (
    <h3 className="h-serif" style={{ fontSize: 15, margin: "16px 0 8px" }}>
      Questions that combine concepts
    </h3>
  );
  if (data === null) {
    return (
      <section data-testid="admin-loop-multi-concept">
        {heading}
        <p data-testid="admin-loop-multi-concept-unavailable" style={muted}>
          Multi-concept question data could not be read for this range.
        </p>
      </section>
    );
  }
  return (
    <section data-testid="admin-loop-multi-concept">
      {heading}
      <p style={muted}>
        Each of these questions combines a concept with one or two of its prerequisites. A student is
        asked one only once they are proficient in every concept it combines, at most once a concept a
        session; the answer counts as half an observation on the concept it builds up to. Served counts the
        questions posed in the range; the outcomes are the graded answers in it.
      </p>
      {data.overall.items === 0 && data.courses.length === 0 ? (
        <p data-testid="admin-loop-multi-concept-empty" style={muted}>
          No questions that combine concepts are stored yet.
        </p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", minWidth: 680 }}>
            <thead>
              <tr>
                <th style={th}>Course</th>
                <th style={thNum}>Questions</th>
                <th style={thNum}>Served</th>
                <th style={thNum}>Answered</th>
                <th style={thNum}>Right unaided</th>
                <th style={thNum}>Students</th>
                <th style={thNum}>Right</th>
              </tr>
            </thead>
            <tbody>
              {data.courses.map((c) => (
                <Row
                  key={c.course_id ?? "none"}
                  block={c}
                  label={c.course_id ?? "No course"}
                  testid={`admin-loop-multi-concept-course-${c.course_id ?? "none"}`}
                />
              ))}
              <Row block={data.overall} label="All courses" testid="admin-loop-multi-concept-overall" />
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
