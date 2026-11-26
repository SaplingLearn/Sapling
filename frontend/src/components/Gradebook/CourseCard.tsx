"use client";
import React from "react";
import Link from "next/link";
import type { GradebookCourseSummary } from "@/lib/types";
import { cn } from "@/lib/cn";

export const COURSE_CARD_HEIGHT = 244;
export const COURSE_CARD_BAND_HEIGHT = 132;
export const COURSE_CARD_GRID_GAP = 24;
export const COURSE_CARD_HERO_HEIGHT = COURSE_CARD_HEIGHT * 2 + COURSE_CARD_GRID_GAP;
export const COURSE_CARD_HERO_BAND_HEIGHT = 340;

export function percentColor(percent: number | null): string {
  if (percent === null) return "var(--text-muted)";
  if (percent >= 90) return "var(--grade-a)";
  if (percent >= 80) return "var(--grade-b)";
  if (percent >= 70) return "var(--grade-c)";
  if (percent >= 60) return "var(--grade-d)";
  return "var(--grade-f)";
}

// Deterministic per-course hash so each course's watermark is a stable,
// unique fingerprint — same course always renders the same composition.
function hashSeed(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return h >>> 0;
}

interface Disc {
  cx: number;
  cy: number;
  r: number;
  fill: string;
}

function discFromSeed(
  seed: number,
  idx: number,
  courseColor: string,
  placed: Disc[],
): Disc {
  const mix = (salt: number) => {
    let x = (seed ^ ((idx + 1) * 0x9e3779b1) ^ (salt * 0x85ebca6b)) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0;
    return (x ^ (x >>> 16)) >>> 0;
  };
  const r = idx === 0 ? 42 + (mix(3) % 30) : 14 + (mix(3) % 36); // larger lead disc
  // viewBox is 240x160 with xMaxYMid slice — bias positions toward the
  // right edge so the watermark stays visible when SVG slices off the left.
  // Reject candidates whose center sits within minDist of an already-placed
  // disc so the three discs read as a composition, not a clump. Keep
  // minDist below r_lead + r_max so the artistic overlap survives while
  // ruling out near-coincident centers.
  const minDist = 62;
  let cx = 130 + (mix(1) % 130);
  let cy = 12 + (mix(2) % 140);
  for (let attempt = 0; attempt < 24; attempt++) {
    cx = 130 + (mix(100 + attempt * 7) % 130);
    cy = 12 + (mix(101 + attempt * 7) % 140);
    let ok = true;
    for (const p of placed) {
      const dx = cx - p.cx;
      const dy = cy - p.cy;
      if (dx * dx + dy * dy < minDist * minDist) {
        ok = false;
        break;
      }
    }
    if (ok) break;
  }
  const isDark = mix(4) % 6 === 0; // ~17% dark inkblot
  // color-mix in oklch derives the disc tint from the band color so the
  // watermark adapts to band lightness (subtle highlight on dark bands,
  // subtle shadow on light ones) without per-color tuning.
  const tintPct = isDark ? 6 + (mix(5) % 6) : 10 + (mix(5) % 8);
  const tintColor = isDark ? "black" : "white";
  const fill = `color-mix(in oklch, ${courseColor}, ${tintColor} ${tintPct}%)`;
  return { cx, cy, r, fill };
}

const DiscsWatermark = ({ seed, courseColor }: { seed: string; courseColor: string }) => {
  const h = hashSeed(seed);
  const discs: Disc[] = [];
  for (let i = 0; i < 3; i++) {
    discs.push(discFromSeed(h, i, courseColor, discs));
  }
  return (
    <svg
      viewBox="0 0 240 160"
      preserveAspectRatio="xMaxYMid slice"
      aria-hidden="true"
      className="absolute inset-0 w-full h-full pointer-events-none"
    >
      {discs.map((d, i) => (
        <circle key={i} cx={d.cx} cy={d.cy} r={d.r} fill={d.fill} />
      ))}
    </svg>
  );
};

interface CourseCardProps {
  course: GradebookCourseSummary;
  variant: "hero" | "default";
  courseColor: string;
  // The landing's selected term. Carried on the link so a course enrolled in
  // several terms opens THIS term's enrollment — without it the backend
  // resolves the current term and an archived enrollment 404s (#139).
  semester?: string;
}

export function CourseCard({ course, variant, courseColor, semester }: CourseCardProps) {
  const isHero = variant === "hero";
  // Single canonical "no grades yet" signal. percent === null is the
  // upstream source of truth; letter follows it.
  const isPlaceholder = course.percent === null;

  return (
    <Link
      href={`/gradebook/${encodeURIComponent(course.course_id)}${
        semester ? `?semester=${encodeURIComponent(semester)}` : ""
      }`}
      className={cn("course-card", "flex flex-col rounded-md [background:var(--bg-panel)] no-underline text-text overflow-hidden", isHero ? "[grid-column:span_2]" : "", isHero ? "[grid-row:span_2]" : "")}
      style={{ height: isHero ? COURSE_CARD_HERO_HEIGHT : COURSE_CARD_HEIGHT }}
    >
      <div
        className={cn("text-accent-fg flex flex-col justify-between items-start relative overflow-hidden", isHero ? "h-85" : "h-33", isHero ? "py-7 px-9" : "py-3.5 px-4.5", isHero ? "gap-8" : "gap-3.5")} style={{ background: courseColor }}
      >
        <DiscsWatermark seed={course.course_id} courseColor={courseColor} />
        <div
          className={cn("mono", "relative z-1 font-semibold text-accent-fg opacity-92", isHero ? "text-sm" : "text-[10.5px]")}
        >
          {course.course_code}
        </div>
        <span
          title={
            isPlaceholder
              ? "No assignments graded yet. Your letter appears after the first grade lands."
              : "Letter scale: A 90+, B 80+, C 70+, D 60+, F below 60"
          }
          className={cn("relative z-1 inline-block text-accent-fg font-display leading-[0.9] tracking-[-0.02em] cursor-help", isPlaceholder ? "font-normal" : "font-medium", isPlaceholder ? "italic" : "not-italic", isHero ? "text-[168px]" : "text-[64px]", isPlaceholder ? "opacity-60" : "opacity-100")}
        >
          {isPlaceholder ? "—" : (course.letter ?? "—")}
        </span>
      </div>
      <div
        className={cn("flex-1 flex flex-col", isHero ? "pt-5 px-8 pb-7" : "pt-3 px-4 pb-3.5")}
      >
        <div
          className={cn("font-display font-medium leading-[1.25] tracking-[-0.01em] text-text overflow-hidden text-ellipsis [display:-webkit-box] [-webkit-line-clamp:2] [-webkit-box-orient:vertical]", isHero ? "text-[28px]" : "text-xl")}
        >
          {course.course_name}
        </div>
        <div className={cn("flex-1", isHero ? "min-h-4" : "min-h-2")} />
        <div
          className="flex justify-between items-baseline gap-2"
        >
          <span
            className="font-medium leading-none tracking-[-0.02em] font-display" style={{ fontSize: course.percent === null ? (isHero ? 20 : 16) : (isHero ? 36 : 26), color: percentColor(course.percent) }}
          >
            {course.percent === null ? "Awaiting First Assignment" : `${course.percent.toFixed(1)}%`}
          </span>
          <span
            className={cn("mono", "tracking-[0.02em] text-text-dim", isHero ? "text-sm" : "text-xs")}
          >
            {course.graded_count}/{course.total_count} graded
          </span>
        </div>
      </div>
    </Link>
  );
}
