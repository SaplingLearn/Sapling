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
 *
 * The arc is SPLIT by mastery tier, so the ring says where its number comes
 * from rather than only how big it is: readiness is Σ(w·m·f)/Σw, and each
 * concept's term lands in its tier's slice. Two invariants make that safe to
 * read — the TOTAL filled length is still the server's figure (the split is a
 * ratio applied to it, never a re-derivation), and `unexplored` contributes a
 * zero-length slice by construction because its mastery is 0, so unstarted
 * work shows up as the ring's GAP and never as a slice implying credit.
 *
 * Colour is the §3.8 encoding, unchanged: course hue through the
 * `TIER_OPACITY` ramp. Nothing invents a tier palette, so a slice here, a row
 * marker in the accordion, and that concept's node on /tree stay the same
 * colour at the same strength. §3.8 also warns that opacity alone is weak at
 * this scale, which is why the legend repeats each tier as a glyph and a
 * number.
 */

import React from "react";
import { TIER_ORDER, glyphFor, opacityFor, type MasteryTier } from "@/lib/graph/nodeStyle";
import type { RoadmapExam, RoadmapSubtopic } from "@/lib/api";

/** Geometry in a fixed viewBox so the ring scales with its container. */
const BOX = 120;
const R = 48;
const STROKE = 10;
const CIRCUMFERENCE = 2 * Math.PI * R;

/** How each tier is named where the ring explains itself. */
const TIER_LABEL: Record<MasteryTier, string> = {
  mastered: "Mastered",
  learning: "Learning",
  struggling: "Struggling",
  unexplored: "Not started",
};

export type ReadinessSegment = {
  tier: MasteryTier;
  /** Concepts in this tier — including the ones contributing nothing. */
  count: number;
  /** This tier's share of the readiness figure, as a 0..1 fraction of the
   *  WHOLE ring (so the segments sum to `readiness`, not to 1). */
  share: number;
};

/**
 * Split one readiness figure into per-tier slices.
 *
 * The split is a RATIO of the server's number, never a second computation of
 * it: slices are `contribution / Σcontribution` scaled by `readiness`. So if
 * the backend ever weights rows unevenly — `subtopic_readiness` already takes
 * a `weight` this client never sees — the ring still fills to exactly the
 * figure printed inside it, and only the proportions come from here.
 *
 * Every tier is returned, zero-share ones included, because the legend has to
 * be able to say "4 concepts not started" — that is the explanation for the
 * empty part of the ring, and dropping the row would delete it.
 */
export function readinessSegments(
  rows: RoadmapSubtopic[],
  readiness: number,
): ReadinessSegment[] {
  const total = rows.reduce((sum, r) => sum + (r.contribution || 0), 0);
  return TIER_ORDER.map(tier => {
    const mine = rows.filter(r => r.tier === tier);
    const contribution = mine.reduce((sum, r) => sum + (r.contribution || 0), 0);
    return {
      tier,
      count: mine.length,
      share: total > 0 ? (contribution / total) * readiness : 0,
    };
  });
}

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
  rows = [],
  baseHue,
}: {
  readiness: number;
  exam: RoadmapExam | null;
  onExplain?: () => void;
  /** Every concept in scope — the same rows the accordion draws. */
  rows?: RoadmapSubtopic[];
  /** The course colour, so a slice matches that course's marks elsewhere. */
  baseHue: string;
}) {
  const pct = Math.round(readiness * 100);
  // The arc is drawn with a dash offset rather than a path arc so it cannot
  // degenerate at 0% or wrap at 100%.
  const filled = CIRCUMFERENCE * Math.max(0, Math.min(1, readiness));

  const segments = readinessSegments(rows, Math.max(0, Math.min(1, readiness)));
  const drawn = segments.filter(seg => seg.share > 0);
  // One slice needs no seam, so it keeps the rounded cap the ring has always
  // had. Several do: butt caps there, or each round cap would overlap its
  // neighbour and smear the boundary the colours exist to show.
  const cap = drawn.length > 1 ? "butt" : "round";

  // Each slice starts where the previous one ended, accumulated with a
  // reduce rather than a mutable cursor: this runs during render, and the
  // React compiler (correctly) refuses a variable reassigned across a map.
  const arcs = drawn.reduce<Array<ReadinessSegment & { length: number; start: number }>>(
    (acc, seg) => {
      const prev = acc[acc.length - 1];
      const start = prev ? prev.start + prev.length : 0;
      return [...acc, { ...seg, length: CIRCUMFERENCE * seg.share, start }];
    },
    [],
  );

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
        {/* No rows (loading, or a course with nothing in it yet) — draw the
            single accent arc the ring has always drawn, so an empty split
            never silently erases the figure. */}
        {arcs.length === 0 && filled > 0 && (
          <circle
            cx={BOX / 2}
            cy={BOX / 2}
            r={R}
            fill="none"
            stroke="var(--accent)"
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={`${filled} ${CIRCUMFERENCE - filled}`}
            transform={`rotate(-90 ${BOX / 2} ${BOX / 2})`}
          />
        )}

        {arcs.map(seg => (
          <circle
            key={seg.tier}
            data-testid={`roadmap-ring-slice-${seg.tier}`}
            cx={BOX / 2}
            cy={BOX / 2}
            r={R}
            fill="none"
            stroke={baseHue}
            strokeOpacity={opacityFor(seg.tier)}
            strokeWidth={STROKE}
            strokeLinecap={cap}
            strokeDasharray={`${seg.length} ${CIRCUMFERENCE - seg.length}`}
            // Negative offset advances the dash, placing this slice after
            // everything already drawn.
            strokeDashoffset={-seg.start}
            // Start at 12 o'clock rather than 3.
            transform={`rotate(-90 ${BOX / 2} ${BOX / 2})`}
          />
        ))}
        <text
          x={BOX / 2}
          y={BOX / 2}
          textAnchor="middle"
          dominantBaseline="central"
          className="roadmap-ring__pct"
          // Own testid: the key below now prints a "+N%" per tier INSIDE the
          // ring, so "the first percentage in this element" stopped being a
          // locator and became a fact about DOM order.
          data-testid="roadmap-ring-pct"
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

      {/* The key. Without it the slices are decoration: four strengths of one
          hue carry no meaning on their own, which is the weakness §3.8 names.
          Glyph and number are the redundant channels — the same two the
          accordion rows use. */}
      {segments.some(seg => seg.count > 0) && (
        <ul className="roadmap-ring__key" data-testid="roadmap-ring-key">
          {segments
            .filter(seg => seg.count > 0)
            .map(seg => (
              <li key={seg.tier} data-testid={`roadmap-ring-key-${seg.tier}`}>
                <span
                  className="roadmap-ring__swatch"
                  style={{ background: baseHue, opacity: opacityFor(seg.tier) }}
                  aria-hidden="true"
                />
                <span className="roadmap-ring__key-glyph" aria-hidden="true">
                  {glyphFor(seg.tier)}
                </span>
                <span className="roadmap-ring__key-name">{TIER_LABEL[seg.tier]}</span>
                <span className="roadmap-ring__key-count">{seg.count}</span>
                {/* Percentage POINTS of the ring, not a percentage of the
                    tier — this is the share of the figure above that these
                    concepts account for. */}
                <span className="roadmap-ring__key-share">
                  +{Math.round(seg.share * 100)}%
                </span>
              </li>
            ))}
        </ul>
      )}

      {/* The accessible summary, which must say what the ring means rather
          than reading out a bare percentage. */}
      <span className="sr-only">
        {pct}% ready{exam ? ` for ${exam.title}, ${examCountdown(exam.due_date)}` : " for this course"}
        {segments
          .filter(seg => seg.count > 0)
          .map(
            seg =>
              `. ${TIER_LABEL[seg.tier]}: ${seg.count} concept${seg.count === 1 ? "" : "s"}, ` +
              `${Math.round(seg.share * 100)} percentage points`,
          )
          .join("")}
      </span>
    </div>
  );
}
