"use client";
import React from "react";
import Link from "next/link";
import type { GradebookCourseSummary } from "@/lib/types";

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
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        pointerEvents: "none",
      }}
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
}

export function CourseCard({ course, variant, courseColor }: CourseCardProps) {
  const isHero = variant === "hero";
  // Single canonical "no grades yet" signal. percent === null is the
  // upstream source of truth; letter follows it.
  const isPlaceholder = course.percent === null;

  return (
    <Link
      href={`/gradebook/${encodeURIComponent(course.course_id)}`}
      className="course-card"
      style={{
        gridColumn: isHero ? "span 2" : undefined,
        gridRow: isHero ? "span 2" : undefined,
        display: "flex",
        flexDirection: "column",
        borderRadius: "var(--r-md)",
        background: "var(--bg-panel)",
        textDecoration: "none",
        color: "var(--text)",
        overflow: "hidden",
        height: isHero ? COURSE_CARD_HERO_HEIGHT : COURSE_CARD_HEIGHT,
      }}
    >
      <div
        style={{
          background: courseColor,
          color: "#ffffff",
          height: isHero ? COURSE_CARD_HERO_BAND_HEIGHT : COURSE_CARD_BAND_HEIGHT,
          padding: isHero ? "28px 36px" : "14px 18px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: isHero ? 32 : 14,
          position: "relative",
          overflow: "hidden",
        }}
      >
        <DiscsWatermark seed={course.course_id} courseColor={courseColor} />
        <div
          className="mono"
          style={{
            position: "relative",
            zIndex: 1,
            fontSize: isHero ? 12 : 10.5,
            fontWeight: 600,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: "#ffffff",
            opacity: 0.92,
          }}
        >
          {course.course_code}
        </div>
        <span
          title={
            isPlaceholder
              ? "No assignments graded yet — your letter appears after the first grade lands."
              : "Letter scale  A 90+   B 80+   C 70+   D 60+   F below 60"
          }
          style={{
            position: "relative",
            zIndex: 1,
            display: "inline-block",
            color: "#ffffff",
            fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
            fontWeight: isPlaceholder ? 400 : 500,
            fontStyle: isPlaceholder ? "italic" : "normal",
            fontSize: isHero ? 168 : 64,
            lineHeight: 0.9,
            letterSpacing: "-0.02em",
            opacity: isPlaceholder ? 0.6 : 1,
            cursor: "help",
          }}
        >
          {isPlaceholder ? "—" : (course.letter ?? "—")}
        </span>
      </div>
      <div
        style={{
          padding: isHero ? "20px 32px 28px" : "12px 16px 14px",
          flex: 1,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
            fontWeight: 500,
            fontSize: isHero ? 28 : 18,
            lineHeight: 1.25,
            letterSpacing: "-0.01em",
            color: "var(--text)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
          }}
        >
          {course.course_name}
        </div>
        <div style={{ flex: 1, minHeight: isHero ? 16 : 8 }} />
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            gap: 8,
          }}
        >
          <span
            className="mono"
            style={{
              fontSize: isHero ? 26 : 18,
              fontWeight: 600,
              lineHeight: 1,
              letterSpacing: "-0.02em",
              color: percentColor(course.percent),
            }}
          >
            {course.percent === null ? "Awaiting first grade" : `${course.percent.toFixed(1)}%`}
          </span>
          <span
            className="mono"
            style={{
              fontSize: isHero ? 12 : 11,
              letterSpacing: "0.02em",
              color: "var(--text-dim)",
            }}
          >
            {course.graded_count}/{course.total_count} graded
          </span>
        </div>
      </div>
    </Link>
  );
}
