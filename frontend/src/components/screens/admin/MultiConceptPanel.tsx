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

import type { LoopMultiConcept, LoopMultiConceptBlock } from "@/lib/types";
import { StaggerBody, StaggerRow } from "./adminMotion";
import t from "./adminTable.module.css";

const th = t.th;
const thNum = `${t.th} ${t.num}`;
const td = t.td;
const tdNum = `${t.td} ${t.num}`;

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
    <StaggerRow data-testid={testid}>
      <td className={td}>{label}</td>
      <td className={tdNum}>{block.items}{block.held ? ` (${block.held} held)` : ""}</td>
      <td className={tdNum}>{block.served}</td>
      <td className={tdNum}>{block.answered}</td>
      <td className={tdNum}>{block.answered ? `${block.unassisted_correct} of ${block.unassisted}` : "—"}</td>
      <td className={tdNum}>{block.students}</td>
      <td className={tdNum}>{rateWithCi(block)}</td>
    </StaggerRow>
  );
}

/** The section for LearningLoopPanelBody. `data` undefined: the backend
 *  predates A141 (nothing renders); null: its reads failed for this range. */
export function MultiConceptPanel({ data }: { data: LoopMultiConcept | null | undefined }) {
  if (data === undefined) return null;
  const heading = (
    <h3 className={`h-serif ${t.heading}`}>
      Questions that combine concepts
    </h3>
  );
  if (data === null) {
    return (
      <section data-testid="admin-loop-multi-concept">
        {heading}
        <p data-testid="admin-loop-multi-concept-unavailable" className={t.lede}>
          Multi-concept question data could not be read for this range.
        </p>
      </section>
    );
  }
  return (
    <section data-testid="admin-loop-multi-concept">
      {heading}
      <p className={t.lede}>
        Each of these questions combines a concept with one or two of its prerequisites. A student is
        asked one only once they are proficient in every concept it combines, at most once a concept a
        session; the answer counts as half an observation on the concept it builds up to. Served counts the
        questions posed in the range; the outcomes are the graded answers in it.
      </p>
      {data.overall.items === 0 && data.courses.length === 0 ? (
        <p data-testid="admin-loop-multi-concept-empty" className={t.lede}>
          No questions that combine concepts are stored yet.
        </p>
      ) : (
        <div className={t.scrollX}>
          <table className={`${t.table} ${t.minMultiConcept}`}>
            <thead>
              <tr>
                <th className={th}>Course</th>
                <th className={thNum}>Questions</th>
                <th className={thNum}>Served</th>
                <th className={thNum}>Answered</th>
                <th className={thNum}>Right unaided</th>
                <th className={thNum}>Students</th>
                <th className={thNum}>Right</th>
              </tr>
            </thead>
            <StaggerBody>
              {data.courses.map((c) => (
                <Row
                  key={c.course_id ?? "none"}
                  block={c}
                  label={c.course_id ?? "No course"}
                  testid={`admin-loop-multi-concept-course-${c.course_id ?? "none"}`}
                />
              ))}
              <Row block={data.overall} label="All courses" testid="admin-loop-multi-concept-overall" />
            </StaggerBody>
          </table>
        </div>
      )}
    </section>
  );
}
