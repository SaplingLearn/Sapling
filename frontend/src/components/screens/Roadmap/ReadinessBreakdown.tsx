"use client";

/**
 * The "why?" panel behind the ring (spec §3.6).
 *
 * The contract this panel exists to honour: every number shown is one the
 * server's formula produced, and the rows sum to the figure in the ring.
 * A breakdown that merely gestures at "coverage and freshness" without
 * closing arithmetically would be worse than no breakdown — it would look
 * like an explanation while being an assertion.
 */

import React from "react";
import type { RoadmapReadiness } from "@/lib/api";
import { examCountdown } from "./ReadinessRing";

export function ReadinessBreakdown({
  data,
  onClose,
}: {
  data: RoadmapReadiness;
  onClose: () => void;
}) {
  const totalWeight = data.factors.reduce((sum, f) => sum + f.weight, 0);

  return (
    <div className="roadmap-why" data-testid="roadmap-readiness-breakdown">
      <div className="roadmap-why__head">
        <h3>
          {data.exam ? (
            <>
              Readiness for {data.exam.title}{" "}
              <span className="roadmap-why__when">{examCountdown(data.exam.due_date)}</span>
            </>
          ) : (
            <>Readiness for this course</>
          )}
        </h3>
        <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>
          Close
        </button>
      </div>

      <p className="roadmap-why__formula">
        Each topic contributes what you&apos;ve <strong>mastered</strong>, discounted by
        how long it&apos;s been since you last <strong>proved</strong> it.
        {data.exam
          ? " Freshness is measured against this exam, so the same topic can be stale for a near deadline and fresh for a distant one."
          : " With no exam selected nothing is discounted for staleness."}
      </p>

      <table className="roadmap-why__table">
        <thead>
          <tr>
            <th scope="col">Topic</th>
            <th scope="col">Mastered</th>
            <th scope="col">Freshness</th>
            <th scope="col">Contribution</th>
          </tr>
        </thead>
        <tbody>
          {data.factors.map(f => (
            <tr key={f.topic_id ?? "unfiled"}>
              <th scope="row">
                {f.concept_name}
                {f.stale > 0 && (
                  <span className="roadmap-why__stale"> · {f.stale} need review</span>
                )}
              </th>
              <td>
                {f.mastered}/{f.total}
              </td>
              <td>{Math.round(f.freshness * 100)}%</td>
              <td>
                {totalWeight > 0
                  ? `${Math.round((f.contribution / totalWeight) * 100)}%`
                  : "0%"}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row" colSpan={3}>
              Overall
            </th>
            <td>
              <strong>{Math.round(data.readiness * 100)}%</strong>
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
