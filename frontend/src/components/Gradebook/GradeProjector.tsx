"use client";
import React from "react";
import { percentColor } from "@/components/Gradebook/CourseCard";
import type {
  GradeCategory,
  GradedAssignment,
  LetterScaleTier,
} from "@/lib/types";
import { cn } from "@/lib/cn";

// ───────────────────────────────────────────────────────────────────────────
// Projection math
// ───────────────────────────────────────────────────────────────────────────

export interface GradeProjection {
  current: number;   // weighted average of graded work, normalized to 100
  floor: number;    // final percent if everything ungraded scored 0
  ceiling: number;  // final percent if everything ungraded scored 100
}

// "Drop the lowest N" helper. Sort score-asc, drop the N lowest, return the
// sum of earned points and sum of possible points for the kept items.
// Mirrors the backend points-weighted calculation: grade = totalEarned/totalPossible.
//
// Tie-break mirrors the backend and droppedAssignmentIds() exactly: lowest
// score first, then higher points_possible, then id asc — so on tied score
// ratios the predictor drops the same assignment the badge/server does.
function dropAndSum(
  items: { id: string; score: number; earned: number; possible: number }[],
  drop: number,
): { totalEarned: number; totalPossible: number } {
  if (drop >= items.length) return { totalEarned: 0, totalPossible: 0 };
  const kept =
    drop <= 0
      ? items
      : [...items]
          .sort((a, b) => {
            if (a.score !== b.score) return a.score - b.score;
            if (a.possible !== b.possible) return b.possible - a.possible;
            return a.id.localeCompare(b.id);
          })
          .slice(drop);
  return {
    totalEarned: kept.reduce((s, x) => s + x.earned, 0),
    totalPossible: kept.reduce((s, x) => s + x.possible, 0),
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
  let currentWeightSum = 0;
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
        return { id: a.id, score: e / p, earned: e, possible: p };
      });
    const currentDS = dropAndSum(currentItems, drop);
    const catCurrent =
      currentDS.totalPossible > 0 ? currentDS.totalEarned / currentDS.totalPossible : 0;

    // Floor scenario — ungraded = 0.
    const floorItems = items.map((a) => {
      const p = a.points_possible as number;
      const e = a.points_earned !== null ? (a.points_earned as number) : 0;
      return { id: a.id, score: e / p, earned: e, possible: p };
    });
    const floorDS = dropAndSum(floorItems, drop);
    const catFloor =
      floorDS.totalPossible > 0 ? floorDS.totalEarned / floorDS.totalPossible : 0;

    // Ceiling scenario — ungraded = full marks.
    const ceilingItems = items.map((a) => {
      const p = a.points_possible as number;
      const e = a.points_earned !== null ? (a.points_earned as number) : p;
      return { id: a.id, score: e / p, earned: e, possible: p };
    });
    const ceilingDS = dropAndSum(ceilingItems, drop);
    const catCeiling =
      ceilingDS.totalPossible > 0 ? ceilingDS.totalEarned / ceilingDS.totalPossible : 0;

    weightSum += cat.weight;
    weightedFloor += cat.weight * catFloor;
    weightedCeiling += cat.weight * catCeiling;
    if (currentDS.totalPossible > 0) {
      currentWeightSum += cat.weight;
      weightedCurrent += cat.weight * catCurrent;
    }
  }

  if (weightSum === 0 || currentWeightSum === 0) return null;
  return {
    current: (weightedCurrent / currentWeightSum) * 100,
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

// Default scale — matches backend DEFAULT_LETTER_SCALE exactly.
const DEFAULT_SCALE: LetterScaleTier[] = [
  { letter: "A",  min: 93 },
  { letter: "A-", min: 90 },
  { letter: "B+", min: 87 },
  { letter: "B",  min: 83 },
  { letter: "B-", min: 80 },
  { letter: "C+", min: 77 },
  { letter: "C",  min: 73 },
  { letter: "C-", min: 70 },
  { letter: "D+", min: 67 },
  { letter: "D",  min: 63 },
  { letter: "D-", min: 60 },
  { letter: "F",  min: 0  },
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
  // Round to 4dp to match backend letter_for() exactly — strips float noise
  // without promoting values semantically below a boundary (89.95 stays B+,
  // not A-, which a 1dp round would wrongly push to 90.0).
  const rounded = Math.round(pct * 1e4) / 1e4;
  return [...scale].sort((a, b) => b.min - a.min).find((t) => rounded >= t.min)?.letter;
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
        className="py-8 px-0 font-serif text-[15px] leading-[1.6] text-text-dim"
      >
        Once your first assignment is graded, this becomes a live projector
        showing what&apos;s guaranteed, what&apos;s still reachable, and what
        you need on the remaining work to hit each letter.
      </div>
    );
  }

  const roundedCurrent = Math.round(current * 1e4) / 1e4;
  const nextUp = [...scale]
    .sort((a, b) => a.min - b.min)
    .find((t) => roundedCurrent < t.min);

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
    actionValue = `Out of reach by ${(nextUp.min - projection.ceiling).toFixed(1)}%`;
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
    <div className="relative">
      {/* Letter ticks above the bar */}
      <div className="relative h-7.5 mb-2">
        {ticks.map(({ letter, min }) => (
          <div
            key={letter}
            className="absolute top-0 [transform:translateX(-50%)] text-center" style={{ left: `${min}%` }}
          >
            <div
              className="mono text-xs font-bold text-text-dim tracking-[-0.01em] leading-none"
            >
              {letter}
            </div>
            <div
              className="mono text-[9px] text-text-muted tracking-[-0.01em] leading-[1.2] mt-0.5"
            >
              {min}
            </div>
          </div>
        ))}
      </div>

      {/* The bar — neutral track + earned-so-far solid + reachable hatched range + current pin */}
      <div className="relative h-4.5 mb-7">
        {/* Track */}
        <div
          aria-hidden="true"
          className="absolute inset-0 bg-bg-subtle rounded-[var(--r-full)]"
        />

        {/* Guaranteed-floor zone: 0 -> floor% */}
        {projection && projection.floor > 0 && (
          <div
            aria-hidden="true"
            className="absolute top-0 bottom-0 left-0 [border-top-left-radius:var(--r-full)] [border-bottom-left-radius:var(--r-full)]" style={{ width: `${projection.floor}%`, background: percentColor(projection.floor) }}
          />
        )}

        {/* Reachable-range zone: floor% -> ceiling%, hatched */}
        {projection && projection.ceiling > projection.floor && (
          <div
            aria-hidden="true"
            className="absolute top-0 bottom-0" style={{ left: `${projection.floor}%`, width: `${projection.ceiling - projection.floor}%`, backgroundImage: `repeating-linear-gradient(135deg, color-mix(in oklch, ${percentColor(projection.ceiling)}, transparent 40%) 0 5px, transparent 5px 10px)` }}
          />
        )}

        {/* Vertical letter tick lines crossing the bar */}
        {ticks.map(({ letter, min }) => (
          <div
            key={`tick-${letter}`}
            aria-hidden="true"
            className="absolute -top-1 -bottom-1 w-px bg-border-strong [transform:translateX(-0.5px)]" style={{ left: `${min}%` }}
          />
        ))}

        {/* Current marker — bold pin, indexed above ticks */}
        <div
          aria-hidden="true"
          className="absolute -top-2 -bottom-2 w-[3px] bg-text rounded-[1px] [transform:translateX(-50%)]" style={{ left: `${current}%` }}
        />
      </div>

      {/* "Now" label, centered under the marker */}
      <div className="relative h-9.5 mb-2">
        <div
          className="absolute [transform:translateX(-50%)] text-center whitespace-nowrap" style={{ left: `clamp(0%, ${current}%, 100%)` }}
        >
          <div
            className="mono text-xs text-text-muted mb-0.5"
          >
            now
          </div>
          <div
            className="font-display text-xl font-medium tracking-[-0.01em] leading-[1.1]" style={{ color: percentColor(current) }}
          >
            {current.toFixed(1)}%
            {currentTier && (
              <span
                className="ml-1.5 text-sm text-text-dim font-normal"
              >
                {currentTier}
              </span>
            )}
          </div>
        </div>
      </div>

      {isPredicted && (
        <div className="chip chip--accent mb-2.5">
          Predicted
        </div>
      )}
      {/* Footer trio: Floor · Action · Ceiling */}
      <div
        className="grid grid-cols-[1fr_1fr_1fr] gap-6 pt-4.5 border-t border-t-border"
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
        className="mono text-sm text-text-muted mb-1.5"
      >
        {label}
      </div>
      <div
        className={cn("font-display tracking-[-0.01em] leading-[1.15]", emphasis ? "font-semibold" : "font-medium", emphasis ? "text-2xl" : "text-[20px]", muted ? "text-text-dim" : "text-text")}
      >
        {value}
        {suffix && (
          <span
            className="ml-2 text-sm text-text-muted font-normal"
          >
            {suffix}
          </span>
        )}
      </div>
    </div>
  );
}
