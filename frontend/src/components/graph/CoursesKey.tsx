"use client";

// The graph's course key ("My courses"): always open, one row per course with
// its colour and code. It is the only
// course legend the graph has: the host wires hover (the graph fades every other course) and click
// (the Dashboard zooms to the course, the Tree filters to it).

import React from "react";
import type { EnrolledCourse } from "@/lib/api";
import type { GraphNode } from "@/lib/data";

export type CourseProgressEntry = {
  course: Pick<EnrolledCourse, "course_id" | "course_code" | "course_name" | "color">;
  mastered: number;
  learning: number;
  struggling: number;
  unexplored: number;
  total: number;
  progress: number;
};

/** Per-course tier counts for the key, from the graph's own nodes. */
export function courseProgressFor(
  courses: CourseProgressEntry["course"][],
  nodes: GraphNode[],
): CourseProgressEntry[] {
  return courses.map((c) => {
    const courseNodes = nodes.filter((n) => n.course_id === c.course_id && !n.is_subject_root);
    const mastered = courseNodes.filter((n) => n.mastery_tier === "mastered").length;
    const learning = courseNodes.filter((n) => n.mastery_tier === "learning").length;
    const struggling = courseNodes.filter((n) => n.mastery_tier === "struggling").length;
    const unexplored = courseNodes.filter((n) => n.mastery_tier === "unexplored" || !n.mastery_tier).length;
    const total = courseNodes.length;
    return { course: c, mastered, learning, struggling, unexplored, total, progress: total ? mastered / total : 0 };
  });
}

export function CoursesKey({
  courseProgress,
  placement = "bottom-right",
  testIdPrefix = "dashboard",
  rowTestId,
  activeCourseId = null,
  selectedCourseId = null,
  onHoverCourse,
  onSelectCourse,
  selectHint,
}: {
  courseProgress: CourseProgressEntry[];
  /** Corner of the graph the key sits in. */
  placement?: "bottom-right" | "top-left";
  /** testid namespace: `<prefix>-courses-key`, `<prefix>-course-code`, … */
  testIdPrefix?: string;
  /** Per-row testid instead of the shared `<prefix>-course-row` (the Tree's
   *  `graph-course-filter-{courseId}`, since the key is its course filter). */
  rowTestId?: (courseId: string) => string;
  /** Row lit by a hover (here or on a concept in the graph). */
  activeCourseId?: string | null;
  /** Row that is the screen's chosen course (Tree filter, Dashboard zoom). */
  selectedCourseId?: string | null;
  /** Hovering a row: the graph fades every other course. */
  onHoverCourse?: (courseId: string | null) => void;
  /** Clicking a row: the screen decides (Dashboard zooms, Tree filters). */
  onSelectCourse?: (courseId: string) => void;
  /** Tooltip on each row, e.g. "Click to zoom". */
  selectHint?: string;
}) {
  // No course in the graph → nothing to key. (Managing courses lives with the
  // host's course list, e.g. the Dashboard's "Open courses →".)
  if (courseProgress.length === 0) return null;

  // A white outline painted BEHIND the glyphs (`paint-order: stroke fill`)
  // plus a soft halo, so the text reads over graph nodes and edges without
  // needing a backdrop.
  const legibleText: React.CSSProperties = {
    WebkitTextStroke: "3px rgba(255,255,255,0.95)",
    paintOrder: "stroke fill" as React.CSSProperties["paintOrder"],
    textShadow:
      "0 0 4px rgba(255,255,255,0.95), " +
      "0 0 2px rgba(255,255,255,1), " +
      "0 0 8px rgba(255,255,255,0.6)",
  };
  const legibleDot: React.CSSProperties = {
    boxShadow: "0 0 0 2px rgba(255,255,255,0.95)",
  };

  return (
    <div
      data-testid={`${testIdPrefix}-courses-key`}
      role="group"
      aria-label="My courses"
      style={{
        position: "absolute",
        ...(placement === "top-left" ? { top: 44, left: 12 } : { bottom: 14, right: 14 }),
        maxWidth: "min(220px, calc(100% - 28px))",
        padding: "6px 8px",
        zIndex: 2,
        fontSize: 12,
        // No title: the coloured dots say what it is.
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
        {courseProgress.map(({ course }) => {
          const color = course.color || "var(--accent)";
          const lit = activeCourseId === course.course_id;
          const chosen = selectedCourseId === course.course_id;
          return (
            <button
              key={course.course_id}
              type="button"
              data-testid={rowTestId ? rowTestId(course.course_id) : `${testIdPrefix}-course-row`}
              data-course-id={course.course_id}
              aria-pressed={selectedCourseId != null ? chosen : undefined}
              title={course.course_name && course.course_code ? `${course.course_name}${selectHint ? ` · ${selectHint}` : ""}` : selectHint}
              onPointerEnter={() => onHoverCourse?.(course.course_id)}
              onPointerLeave={() => onHoverCourse?.(null)}
              onFocus={() => onHoverCourse?.(course.course_id)}
              onBlur={() => onHoverCourse?.(null)}
              onClick={() => onSelectCourse?.(course.course_id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 7,
                margin: "0 -6px",
                padding: "3px 6px",
                border: 0,
                borderRadius: "var(--r-sm)",
                background: lit || chosen ? "rgba(255,255,255,0.8)" : "transparent",
                boxShadow: chosen ? `inset 0 0 0 1.5px ${color}` : "none",
                textAlign: "left",
                color: "inherit",
                font: "inherit",
                cursor: onSelectCourse ? "pointer" : "default",
                transition: "background 150ms ease",
              }}
            >
              <span style={{ width: 9, height: 9, borderRadius: "50%", background: color, flexShrink: 0, ...legibleDot }} />
              <span
                data-testid={`${testIdPrefix}-course-code`}
                style={{
                  fontSize: 12,
                  fontWeight: lit || chosen ? 600 : 500,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  ...legibleText,
                }}
              >
                {course.course_code || course.course_name}
              </span>
            </button>
          );
        })}

      </div>
    </div>
  );
}
