"use client";

/**
 * The readiness ring — "how ready are you for this exam" (spec §3.6).
 *
 * NOT a progress bar. Progress answers "how much have you done"; this
 * answers "would you pass", which is a different and more useful question
 * and can legitimately go DOWN as an exam approaches without the student
 * doing anything wrong. The copy has to carry that, so the ring always
 * names what it is measured against.
 *
 * The number arrives computed from the server. Nothing here recalculates
 * it — see the note on `getRoadmap` in lib/api.
 */

import React from "react";
import type { RoadmapExam } from "@/lib/api";

/** Geometry in a fixed viewBox so the ring scales with its container. */
const BOX = 120;
const R = 48;
const STROKE = 10;
const CIRCUMFERENCE = 2 * Math.PI * R;

function daysUntil(due: string): number {
  const exam = new Date(`${due}T00:00:00Z`).getTime();
  const today = new Date();
  const utcToday = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((exam - utcToday) / 86_400_000);
}

/** "in 9 days" / "tomorrow" / "today" / "passed". Plain words beat a date
 *  here: the student is deciding what to do tonight, not filing a calendar. */
export function examCountdown(due: string): string {
  const days = daysUntil(due);
  if (days < 0) return "passed";
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

export function ReadinessRing({
  readiness,
  exam,
  onExplain,
}: {
  readiness: number;
  exam: RoadmapExam | null;
  onExplain?: () => void;
}) {
  const pct = Math.round(readiness * 100);
  // The arc is drawn with a dash offset rather than a path arc so it cannot
  // degenerate at 0% or wrap at 100%.
  const filled = CIRCUMFERENCE * Math.max(0, Math.min(1, readiness));

  return (
    <div className="roadmap-ring" data-testid="roadmap-readiness-ring">
      <svg viewBox={`0 0 ${BOX} ${BOX}`} className="roadmap-ring__svg" aria-hidden="true">
        <circle
          cx={BOX / 2}
          cy={BOX / 2}
          r={R}
          fill="none"
          stroke="var(--border)"
          strokeWidth={STROKE}
        />
        <circle
          cx={BOX / 2}
          cy={BOX / 2}
          r={R}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={STROKE}
          strokeLinecap="round"
          strokeDasharray={`${filled} ${CIRCUMFERENCE - filled}`}
          // Start at 12 o'clock rather than 3.
          transform={`rotate(-90 ${BOX / 2} ${BOX / 2})`}
        />
        <text
          x={BOX / 2}
          y={BOX / 2}
          textAnchor="middle"
          dominantBaseline="central"
          className="roadmap-ring__pct"
        >
          {pct}%
        </text>
      </svg>

      <div className="roadmap-ring__caption">
        {/* The ring is meaningless without naming its target — 63% ready for
            WHAT is the whole content of the number. */}
        <p className="roadmap-ring__label">
          {exam ? (
            <>
              ready for <strong>{exam.title}</strong>
              <span className="roadmap-ring__when"> {examCountdown(exam.due_date)}</span>
            </>
          ) : (
            <>ready for this course</>
          )}
        </p>
        {onExplain && (
          <button type="button" className="roadmap-ring__why" onClick={onExplain}>
            Why this number?
          </button>
        )}
      </div>

      {/* The accessible summary, which must say what the ring means rather
          than reading out a bare percentage. */}
      <span className="sr-only">
        {pct}% ready{exam ? ` for ${exam.title}, ${examCountdown(exam.due_date)}` : " for this course"}
      </span>
    </div>
  );
}
