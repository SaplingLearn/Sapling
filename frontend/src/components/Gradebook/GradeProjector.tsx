"use client";
import React from "react";
import { percentColor } from "@/components/Gradebook/CourseCard";
import type {
  GradeCategory,
  GradedAssignment,
  LetterScaleTier,
} from "@/lib/types";

// ───────────────────────────────────────────────────────────────────────────
// Projection math
// ───────────────────────────────────────────────────────────────────────────

export interface GradeProjection {
  current: number;   // weighted average of graded work, normalized to 100
  floor: number;    // final percent if everything ungraded scored 0
  ceiling: number;  // final percent if everything ungraded scored 100
}

// "Drop the lowest N" helper. Sort score-asc, drop the N lowest, return the
// sum of scores and count of kept items. Each assignment is equally weighted —
// the category grade is scoreSum/count, not total-earned/total-possible.
function dropAndSum(
  items: { score: number; earned: number; possible: number }[],
  drop: number,
): { scoreSum: number; count: number } {
  if (drop >= items.length) return { scoreSum: 0, count: 0 };
  const kept = drop <= 0 ? items : [...items].sort((a, b) => a.score - b.score).slice(drop);
  return {
    scoreSum: kept.reduce((s, x) => s + x.score, 0),
    count: kept.length,
  };
}

/**
 * Compute floor / current / ceiling final percent from assignment data.
 *
 * Per category: drops the lowest `drop_lowest` graded assignments before
 * averaging the current scenario. For floor (ungraded → 0) and ceiling
 * (ungraded → full), the drop is applied across all items with their
 * hypothetical scores — so drops can erase imagined-zero floors and
 * imagined-full ceilings alike. Categories with no point-bearing
 * assignments are skipped.
 *
 * Returns null if no category had any computable data.
 */
export function projectGrade(
  categories: GradeCategory[],
  assignments: GradedAssignment[],
): GradeProjection | null {
  let weightSum = 0;
  let weightedCurrent = 0;
  let weightedFloor = 0;
  let weightedCeiling = 0;

  for (const cat of categories) {
    if (cat.weight <= 0) continue;
    const items = assignments.filter(
      (a) =>
        a.category_id === cat.id &&
        a.points_possible !== null &&
        (a.points_possible as number) > 0,
    );
    if (items.length === 0) continue;
    const drop = Math.max(0, cat.drop_lowest ?? 0);

    // Current scenario — only graded items count, drop the N lowest of those.
    const currentItems = items
      .filter((a) => a.points_earned !== null)
      .map((a) => {
        const p = a.points_possible as number;
        const e = a.points_earned as number;
        return { score: e / p, earned: e, possible: p };
      });
    const currentDS = dropAndSum(currentItems, drop);
    const catCurrent =
      currentDS.count > 0 ? currentDS.scoreSum / currentDS.count : 0;

    // Floor scenario — ungraded = 0.
    const floorItems = items.map((a) => {
      const p = a.points_possible as number;
      const e = a.points_earned !== null ? (a.points_earned as number) : 0;
      return { score: e / p, earned: e, possible: p };
    });
    const floorDS = dropAndSum(floorItems, drop);
    const catFloor =
      floorDS.count > 0 ? floorDS.scoreSum / floorDS.count : 0;

    // Ceiling scenario — ungraded = full marks.
    const ceilingItems = items.map((a) => {
      const p = a.points_possible as number;
      const e = a.points_earned !== null ? (a.points_earned as number) : p;
      return { score: e / p, earned: e, possible: p };
    });
    const ceilingDS = dropAndSum(ceilingItems, drop);
    const catCeiling =
      ceilingDS.count > 0 ? ceilingDS.scoreSum / ceilingDS.count : 0;

    weightSum += cat.weight;
    weightedCurrent += cat.weight * catCurrent;
    weightedFloor += cat.weight * catFloor;
    weightedCeiling += cat.weight * catCeiling;
  }

  if (weightSum === 0) return null;
  return {
    current: (weightedCurrent / weightSum) * 100,
    floor: (weightedFloor / weightSum) * 100,
    ceiling: (weightedCeiling / weightSum) * 100,
  };
}

/**
 * Identify the IDs of assignments currently being dropped across all
 * categories, given the present graded state. Same tiebreak as backend:
 * lowest score percent, then higher points_possible, then id asc.
 *
 * For UI badges only — drops can shift as more assignments are graded.
 */
export function droppedAssignmentIds(
  categories: GradeCategory[],
  assignments: GradedAssignment[],
): Set<string> {
  const dropped = new Set<string>();
  for (const cat of categories) {
    const drop = Math.max(0, cat.drop_lowest ?? 0);
    if (drop <= 0) continue;
    const graded = assignments
      .filter(
        (a) =>
          a.category_id === cat.id &&
          a.points_possible !== null &&
          (a.points_possible as number) > 0 &&
          a.points_earned !== null,
      )
      .map((a) => ({
        id: a.id,
        score: (a.points_earned as number) / (a.points_possible as number),
        possible: a.points_possible as number,
      }));
    if (graded.length === 0) continue;
    graded.sort((a, b) => {
      if (a.score !== b.score) return a.score - b.score;
      if (a.possible !== b.possible) return b.possible - a.possible;
      return a.id.localeCompare(b.id);
    });
    for (const item of graded.slice(0, drop)) dropped.add(item.id);
  }
  return dropped;
}

// ───────────────────────────────────────────────────────────────────────────
// Visualization
// ───────────────────────────────────────────────────────────────────────────

interface Props {
  categories: GradeCategory[];
  assignments: GradedAssignment[];
  currentPercent: number | null;
  letterScale: LetterScaleTier[] | null;
  isPredicted?: boolean;
}

// Default scale used when a course has no per-course letter scale set.
const DEFAULT_SCALE: LetterScaleTier[] = [
  { letter: "A", min: 90 },
  { letter: "B", min: 80 },
  { letter: "C", min: 70 },
  { letter: "D", min: 60 },
];

function majorTicks(scale: LetterScaleTier[]): { letter: string; min: number }[] {
  // Collapse +/- tiers into the major letter per first-character, taking the
  // highest min for each. Output sorted ascending by min for left-to-right
  // tick placement.
  const seen = new Set<string>();
  const out: { letter: string; min: number }[] = [];
  for (const t of [...scale].sort((a, b) => b.min - a.min)) {
    const prefix = t.letter.charAt(0).toUpperCase();
    if (!seen.has(prefix) && /^[A-D]$/.test(prefix)) {
      seen.add(prefix);
      out.push({ letter: prefix, min: t.min });
    }
  }
  return out.sort((a, b) => a.min - b.min);
}

function tierFor(scale: LetterScaleTier[], pct: number): string | undefined {
  // First tier from the top whose min the value clears.
  return [...scale].sort((a, b) => b.min - a.min).find((t) => pct >= t.min)?.letter;
}

export function GradeProjector({
  categories,
  assignments,
  currentPercent,
  letterScale,
  isPredicted = false,
}: Props) {
  const projection = projectGrade(categories, assignments);
  // Prefer the server-computed current percent; fall back to our computation
  // only if the API didn't give one.
  const current = currentPercent ?? projection?.current ?? null;
  const scale = letterScale && letterScale.length > 0 ? letterScale : DEFAULT_SCALE;
  const ticks = majorTicks(scale);

  if (current === null) {
    return (
      <div
        style={{
          padding: "32px 0",
          fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
          fontSize: 15,
          lineHeight: 1.6,
          color: "var(--text-dim)",
        }}
      >
        Once your first assignment is graded, this becomes a live projector
        showing what&apos;s guaranteed, what&apos;s Still Reachable, and what
        you need on the remaining work to hit each letter.
      </div>
    );
  }

  const nextUp = [...scale]
    .sort((a, b) => a.min - b.min)
    .find((t) => current < t.min);

  // Build the "actionable" line for the middle stat.
  let actionLabel: string;
  let actionValue: string;
  if (!nextUp) {
    actionLabel = "Top tier";
    actionValue = "Already there";
  } else if (projection && projection.floor >= nextUp.min) {
    actionLabel = `${nextUp.letter} secured`;
    actionValue = "Already guaranteed";
  } else if (projection && projection.ceiling < nextUp.min) {
    actionLabel = `${nextUp.letter} (${nextUp.min}+)`;
    actionValue = `Out of reach by ${(nextUp.min - projection.ceiling).toFixed(1)} pts`;
  } else if (projection) {
    // Fraction of the floor->ceiling span you need to cover to hit the target.
    const span = projection.ceiling - projection.floor;
    const need = nextUp.min - projection.floor;
    const requiredAvg = span > 0 ? (need / span) * 100 : 0;
    actionLabel = `For ${nextUp.letter} (${nextUp.min}+)`;
    actionValue = `${Math.max(0, Math.ceil(requiredAvg))}%+ avg on remaining`;
  } else {
    actionLabel = `Next: ${nextUp.letter}`;
    actionValue = `${(nextUp.min - current).toFixed(1)} pts away`;
  }

  // The current percent's letter (for the "Now" label below the marker).
  const currentTier = tierFor(scale, current);
  const floorTier = projection ? tierFor(scale, projection.floor) : undefined;
  const ceilingTier = projection ? tierFor(scale, projection.ceiling) : undefined;

  return (
    <div style={{ position: "relative" }}>
      {/* Letter ticks above the bar */}
      <div style={{ position: "relative", height: 30, marginBottom: 8 }}>
        {ticks.map(({ letter, min }) => (
          <div
            key={letter}
            style={{
              position: "absolute",
              left: `${min}%`,
              top: 0,
              transform: "translateX(-50%)",
              textAlign: "center",
            }}
          >
            <div
              className="mono"
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: "var(--text-dim)",
                letterSpacing: "-0.01em",
                lineHeight: 1,
              }}
            >
              {letter}
            </div>
            <div
              className="mono"
              style={{
                fontSize: 9,
                color: "var(--text-muted)",
                letterSpacing: "-0.01em",
                lineHeight: 1.2,
                marginTop: 2,
              }}
            >
              {min}
            </div>
          </div>
        ))}
      </div>

      {/* The bar — neutral track + earned-so-far solid + reachable hatched range + current pin */}
      <div style={{ position: "relative", height: 18, marginBottom: 28 }}>
        {/* Track */}
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: 0,
            background: "var(--bg-subtle)",
            borderRadius: "var(--r-full)",
          }}
        />

        {/* Guaranteed-floor zone: 0 -> floor% */}
        {projection && projection.floor > 0 && (
          <div
            aria-hidden="true"
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: 0,
              width: `${projection.floor}%`,
              background: percentColor(projection.floor),
              borderTopLeftRadius: "var(--r-full)",
              borderBottomLeftRadius: "var(--r-full)",
            }}
          />
        )}

        {/* Reachable-range zone: floor% -> ceiling%, hatched */}
        {projection && projection.ceiling > projection.floor && (
          <div
            aria-hidden="true"
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: `${projection.floor}%`,
              width: `${projection.ceiling - projection.floor}%`,
              backgroundImage: `repeating-linear-gradient(135deg, color-mix(in oklch, ${percentColor(projection.ceiling)}, transparent 40%) 0 5px, transparent 5px 10px)`,
            }}
          />
        )}

        {/* Vertical letter tick lines crossing the bar */}
        {ticks.map(({ letter, min }) => (
          <div
            key={`tick-${letter}`}
            aria-hidden="true"
            style={{
              position: "absolute",
              left: `${min}%`,
              top: -4,
              bottom: -4,
              width: 1,
              background: "var(--border-strong)",
              transform: "translateX(-0.5px)",
            }}
          />
        ))}

        {/* Current marker — bold pin, indexed above ticks */}
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            left: `${current}%`,
            top: -8,
            bottom: -8,
            width: 3,
            background: "var(--text)",
            borderRadius: 1,
            transform: "translateX(-50%)",
          }}
        />
      </div>

      {/* "Now" label, centered under the marker */}
      <div style={{ position: "relative", height: 38, marginBottom: 8 }}>
        <div
          style={{
            position: "absolute",
            left: `clamp(0%, ${current}%, 100%)`,
            transform: "translateX(-50%)",
            textAlign: "center",
            whiteSpace: "nowrap",
          }}
        >
          <div
            className="mono"
            style={{
              fontSize: 9,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--text-muted)",
              marginBottom: 2,
            }}
          >
            now
          </div>
          <div
            style={{
              fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
              fontSize: 18,
              fontWeight: 500,
              color: percentColor(current),
              letterSpacing: "-0.01em",
              lineHeight: 1.1,
            }}
          >
            {current.toFixed(1)}%
            {currentTier && (
              <span
                style={{
                  marginLeft: 6,
                  fontSize: 12,
                  color: "var(--text-dim)",
                  fontWeight: 400,
                }}
              >
                {currentTier}
              </span>
            )}
          </div>
        </div>
      </div>

      {isPredicted && (
        <div
          className="mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--accent)",
            background: "var(--accent-soft)",
            border: "1px solid var(--accent-border)",
            borderRadius: "var(--r-full)",
            padding: "2px 8px",
            display: "inline-block",
            marginBottom: 10,
          }}
        >
          Predicted
        </div>
      )}
      {/* Footer trio: Floor · Action · Ceiling */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 24,
          paddingTop: 18,
          borderTop: "1px solid var(--border)",
        }}
      >
        <Stat
          label="If you stop here"
          value={projection ? `${projection.floor.toFixed(1)}%` : "—"}
          suffix={floorTier}
          muted
        />
        <Stat label={actionLabel} value={actionValue} emphasis />
        <Stat
          label="If you ace remaining"
          value={projection ? `${projection.ceiling.toFixed(1)}%` : "—"}
          suffix={ceilingTier}
          muted
        />
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  suffix,
  muted,
  emphasis,
}: {
  label: string;
  value: string;
  suffix?: string;
  muted?: boolean;
  emphasis?: boolean;
}) {
  return (
    <div>
      <div
        className="mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: "var(--text-muted)",
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
          fontWeight: emphasis ? 600 : 500,
          fontSize: emphasis ? 22 : 20,
          color: muted ? "var(--text-dim)" : "var(--text)",
          letterSpacing: "-0.01em",
          lineHeight: 1.15,
        }}
      >
        {value}
        {suffix && (
          <span
            style={{
              marginLeft: 8,
              fontSize: 12,
              color: "var(--text-muted)",
              fontWeight: 400,
            }}
          >
            {suffix}
          </span>
        )}
      </div>
    </div>
  );
}
