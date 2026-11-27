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
import { StaggerBody, StaggerRow } from "./adminMotion";
import t from "./adminTable.module.css";
import s from "./HintTrendPanel.module.css";

type Direction = LoopConceptTrend["direction"];

const th = t.th;
const thNum = `${t.th} ${t.num}`;
const td = t.td;
const tdNum = `${t.td} ${t.num}`;

/** Worst first: the concepts needing more help to get it right lead. */
const ORDER: Direction[] = ["rising", "flat", "falling", "insufficient"];

const LABEL: Record<Direction, string> = {
  rising: "Rising",
  flat: "Flat",
  falling: "Falling",
  insufficient: "One week only",
};

/** The colour of each direction: worse is the error hue, better the accent. */
const TONE: Record<Direction, string> = {
  rising: s.rising,
  flat: s.flat,
  falling: s.falling,
  insufficient: s.flat,
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
    <StaggerRow data-testid={`admin-loop-htc-row-${concept.concept_id}`}>
      <td className={td}><code>{concept.concept_id}</code></td>
      <td className={tdNum}>{concept.weeks.length}</td>
      <td className={tdNum}>{rung(first.mean_rung)} ({first.steps})</td>
      <td className={tdNum}>{rung(last.mean_rung)} ({last.steps})</td>
      <td className={tdNum}>{steps}</td>
      <td className={`${td} ${t.strong} ${TONE[concept.direction]}`}>{LABEL[concept.direction]}</td>
    </StaggerRow>
  );
}

/** The section for LearningLoopPanelBody. */
export function HintTrendPanel({ trend }: { trend: LoopConceptTrend[] }) {
  const counts = directionCounts(trend);
  const rows = trendRows(trend);
  return (
    <section data-testid="admin-loop-htc-trend">
      <h3 className={`h-serif ${t.heading}`}>Do students need fewer hints?</h3>
      <p className={t.lede}>
        Per concept and week, the mean hint level (H0 = no hint) students had reached on the steps they got
        right, over the last weeks of the range. It should fall as students learn the concept. First and last
        are the window&apos;s first and last weeks with such steps, each with its count of steps.
      </p>
      {trend.length === 0 ? (
        <p data-testid="admin-loop-htc-empty" className={t.lede}>No correct steps with a hint level in this range.</p>
      ) : (
        <>
          <p data-testid="admin-loop-htc-summary" className={s.summary}>
            {ORDER.map((direction, i) => (
              <React.Fragment key={direction}>
                {i > 0 && " · "}
                <span className={TONE[direction]}>{LABEL[direction]}</span> {counts[direction]}
              </React.Fragment>
            ))}
          </p>
          {rows.length > 0 && (
            <div className={t.scrollX}>
              <table className={t.tableFull}>
                <thead>
                  <tr>
                    <th className={th}>Concept</th>
                    <th className={thNum}>Weeks</th>
                    <th className={thNum}>First week</th>
                    <th className={thNum}>Last week</th>
                    <th className={thNum}>Steps</th>
                    <th className={th}>Trend</th>
                  </tr>
                </thead>
                <StaggerBody>
                  {rows.map((concept) => <Row key={concept.concept_id} concept={concept} />)}
                </StaggerBody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
