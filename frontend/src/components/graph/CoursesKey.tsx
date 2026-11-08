"use client";

// The graph's course key ("My courses"): one row per course with its colour,
// code, mastery % and four-tier bar. It is the only course legend the graph
// has: the host wires hover (the graph fades every other course) and click
// (the Dashboard zooms to the course, the Tree filters to it).

import React from "react";
import { Icon } from "../Icon";
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
  hasCourses,
  semesterActive,
  onManage,
  placement = "bottom-right",
  defaultCollapsed = true,
  testIdPrefix = "dashboard",
  activeCourseId = null,
  selectedCourseId = null,
  onHoverCourse,
  onSelectCourse,
  selectHint,
}: {
  courseProgress: CourseProgressEntry[];
  hasCourses: boolean;
  semesterActive: boolean;
  /** The cog (Courses & Semesters). Omitted → no cog. */
  onManage?: () => void;
  /** Corner of the graph the key sits in. */
  placement?: "bottom-right" | "top-left";
  defaultCollapsed?: boolean;
  /** testid namespace: `<prefix>-courses-key-toggle`, `<prefix>-course-code`, … */
  testIdPrefix?: string;
  /** Row lit by a hover (here or on a concept in the graph). */
  activeCourseId?: string | null;
  /** Row that is the screen's chosen course (the Tree's filter). */
  selectedCourseId?: string | null;
  /** Hovering a row: the graph fades every other course. */
  onHoverCourse?: (courseId: string | null) => void;
  /** Clicking a row: the screen decides (Dashboard zooms, Tree filters). */
  onSelectCourse?: (courseId: string) => void;
  /** Tooltip on each row, e.g. "Click to zoom". */
  selectHint?: string;
}) {
  const [collapsed, setCollapsed] = React.useState(defaultCollapsed);

  // No enrolled courses at all → nothing to key, render nothing (the original
  // null case). But when courses exist and the active semester merely has none
  // of them, keep the panel so the "Nothing enrolled this semester." empty
  // state below is reachable.
  if (courseProgress.length === 0 && !(hasCourses && semesterActive)) return null;

  // A thick white outline painted BEHIND the glyphs, plus a soft halo.
  // `paint-order: stroke fill` pushes the stroke under the fill so
  // letters stay clean-edged. Works against any background colour
  // (graph nodes, edges, labels) without needing a backdrop.
  const legibleText: React.CSSProperties = {
    WebkitTextStroke: "3px rgba(255,255,255,0.95)",
    paintOrder: "stroke fill" as React.CSSProperties["paintOrder"],
    textShadow:
      "0 0 4px rgba(255,255,255,0.95), " +
      "0 0 2px rgba(255,255,255,1), " +
      "0 0 8px rgba(255,255,255,0.6)",
  };
  // Progress-bar track gets a white ring so the bar geometry reads
  // even when a colored graph node passes right behind it.
  const legibleBar: React.CSSProperties = {
    boxShadow: "0 0 0 1.5px rgba(255,255,255,0.95), 0 0 6px rgba(255,255,255,0.6)",
  };
  const legibleDot: React.CSSProperties = {
    boxShadow: "0 0 0 2px rgba(255,255,255,0.95)",
  };
  // Soft white halo around each icon — blurred drop-shadows stacked at
  // the same origin so the glow follows the icon's shape with no hard
  // edges. Button itself stays transparent.
  const paddedIconBtn: React.CSSProperties = {
    padding: 0,
    background: "transparent",
    border: "none",
    fontSize: 10,
    lineHeight: 0,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
    filter:
      "drop-shadow(0 0 2px rgba(255,255,255,1)) " +
      "drop-shadow(0 0 4px rgba(255,255,255,0.85)) " +
      "drop-shadow(0 0 6px rgba(255,255,255,0.55))",
  };

  return (
    <div
      style={{
        position: "absolute",
        ...(placement === "top-left" ? { top: 44, left: 12 } : { bottom: 14, right: 14 }),
        width: collapsed ? "auto" : 300,
        maxWidth: "calc(100% - 28px)",
        background: "transparent",
        border: "none",
        borderRadius: 0,
        boxShadow: "none",
        padding: collapsed ? "8px 12px" : "14px 16px 12px",
        zIndex: 2,
        fontSize: 13,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
          marginBottom: collapsed ? 0 : 12,
        }}
      >
        <div className="label-micro" style={{ fontSize: 11, ...legibleText }}>My courses</div>
        <div style={{ display: "flex", gap: 6 }}>
          {!collapsed && onManage && (
            <button
              className="btn btn--ghost btn--sm"
              onClick={onManage}
              title="Courses & Semesters"
              aria-label="Courses & Semesters"
              style={paddedIconBtn}
              data-testid={`${testIdPrefix}-courses-manage`}
            >
              <Icon name="cog" size={13} />
            </button>
          )}
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => setCollapsed(c => !c)}
            aria-label={collapsed ? "Expand courses key" : "Collapse courses key"}
            style={paddedIconBtn}
            data-testid={`${testIdPrefix}-courses-key-toggle`}
          >
            <Icon name={collapsed ? "plus" : "x"} size={13} />
          </button>
        </div>
      </div>

      {!collapsed && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {courseProgress.map(({ course, mastered, learning, struggling, unexplored, total, progress }) => {
            const pct = Math.round(progress * 100);
            const baseColor = course.color || "var(--accent)";
            const segs = [
              { count: mastered,   color: baseColor,         opacity: 1 },
              { count: learning,   color: baseColor,         opacity: 0.78 },
              { count: struggling, color: baseColor,         opacity: 0.55 },
              { count: unexplored, color: "var(--bg-soft)",  opacity: 1 },
            ];
            const lit = activeCourseId === course.course_id;
            const chosen = selectedCourseId === course.course_id;
            return (
              <button
                key={course.course_id}
                type="button"
                data-testid={`${testIdPrefix}-course-row`}
                data-course-id={course.course_id}
                aria-pressed={selectedCourseId != null ? chosen : undefined}
                title={selectHint}
                onPointerEnter={() => onHoverCourse?.(course.course_id)}
                onPointerLeave={() => onHoverCourse?.(null)}
                onFocus={() => onHoverCourse?.(course.course_id)}
                onBlur={() => onHoverCourse?.(null)}
                onClick={() => onSelectCourse?.(course.course_id)}
                style={{
                  display: "block",
                  width: "calc(100% + 12px)",
                  margin: "-4px -6px",
                  padding: "4px 6px",
                  border: 0,
                  borderRadius: "var(--r-sm)",
                  background: lit || chosen ? "rgba(255,255,255,0.75)" : "transparent",
                  boxShadow: chosen ? `inset 0 0 0 1.5px ${baseColor}` : "none",
                  textAlign: "left",
                  color: "inherit",
                  font: "inherit",
                  cursor: onSelectCourse ? "pointer" : "default",
                  transition: "background 150ms ease",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5, gap: 8 }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                    <span style={{ width: 11, height: 11, borderRadius: "50%", background: baseColor, flexShrink: 0, ...legibleDot }} />
                    <strong
                      data-testid={`${testIdPrefix}-course-code`}
                      style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", ...legibleText }}
                    >
                      {course.course_code || course.course_name}
                    </strong>
                  </span>
                  <span className="mono" style={{ color: "var(--text-dim)", fontSize: 12, ...legibleText }}>{pct}%</span>
                </div>
                {total > 0 ? (
                  <div
                    style={{
                      display: "flex",
                      height: 8,
                      background: "var(--bg-soft)",
                      borderRadius: "var(--r-full)",
                      overflow: "hidden",
                      ...legibleBar,
                    }}
                    title={`Mastered ${mastered} · Learning ${learning} · Struggling ${struggling} · Unexplored ${unexplored}`}
                  >
                    {segs.map((s, i) => s.count > 0 && (
                      <div
                        key={i}
                        style={{
                          width: `${(s.count / total) * 100}%`,
                          background: s.color,
                          opacity: s.opacity,
                          transition: "width var(--dur) var(--ease)",
                        }}
                      />
                    ))}
                  </div>
                ) : (
                  <div style={{ height: 8, background: "var(--bg-soft)", borderRadius: "var(--r-full)", ...legibleBar }} />
                )}
              </button>
            );
          })}

          {courseProgress.length === 0 && (
            <div style={{ fontSize: 12, color: "var(--text-dim)", ...legibleText }}>
              Nothing enrolled this semester.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
