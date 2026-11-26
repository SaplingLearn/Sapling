"use client";

// The graph's course key ("My courses"): always open, one row per course with
// its colour and code. It is the only
// course legend the graph has: the host wires hover (the graph fades every other course) and click
// (the Dashboard zooms to the course, the Tree filters to it).

import React from "react";
import type { EnrolledCourse } from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import { cn } from "@/lib/cn";

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
  // host's course list, e.g. the Dashboard's "Courses · Manage →".)
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

  return (
    <div
      data-testid={`${testIdPrefix}-courses-key`}
      role="group"
      aria-label="My courses"
      className="absolute max-w-[min(220px,_calc(100%_-_28px))] py-1.5 px-2 z-2 text-sm" style={{ ...(placement === "top-left" ? { top: 44, left: 12 } : { bottom: 14, right: 14 }) }}
    >
      <div className="flex flex-col gap-px">
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
              className={cn("flex items-center gap-[7px] my-0 -mx-1.5 py-[3px] px-1.5 border-0 rounded-sm text-left text-inherit [font:inherit] [transition:background_150ms_ease]", lit || chosen ? "bg-[rgba(255,255,255,0.8)]" : "bg-transparent", onSelectCourse ? "cursor-pointer" : "cursor-default")} style={{ boxShadow: chosen ? `inset 0 0 0 1.5px ${color}` : "none" }}
            >
              <span className="w-[9px] h-[9px] rounded-[50%] shrink-0 [box-shadow:0_0_0_2px_rgba(255,255,255,0.95)]" style={{ background: color }} />
              <span
                data-testid={`${testIdPrefix}-course-code`}
                className={cn("text-sm overflow-hidden text-ellipsis whitespace-nowrap", lit || chosen ? "font-semibold" : "font-medium")} style={{ ...legibleText }}
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
