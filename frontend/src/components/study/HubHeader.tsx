"use client";
/**
 * The hub's header, laid out like the Dashboard's: the title and the course
 * on the left, the page's actions (its three tools) on the right.
 */
import React from "react";
import type { EnrolledCourse } from "@/lib/api";
import { CoursePicker } from "./CoursePicker";
import { Glyph, TOOL, TOOL_ORDER, shownTools } from "./hubUi";
import s from "./StudyHub.module.css";
import type { ToolKey } from "./useToolNav";

const TOOL_BUTTONS = TOOL_ORDER.map(key => ({ key, ...TOOL[key] }));

export function HubHeader({ courses, courseId, onPickCourse, upcomingIn, isMobile, quizShown, onTool }: {
  courses: EnrolledCourse[];
  courseId: string;
  onPickCourse: (courseId: string) => void;
  /** Dated work still ahead for a course: the count on its picker row. */
  upcomingIn: (courseId: string) => number;
  isMobile: boolean;
  quizShown: boolean;
  /** Opens a tool's home on this course. */
  onTool: (tool: ToolKey) => void;
}) {
  const upcomingNote = (c: EnrolledCourse) => {
    const n = upcomingIn(c.course_id);
    return n > 0 ? `${n} upcoming` : null;
  };
  return (
    <header className={s.areaHeader} style={{ display: "flex", flexDirection: "column", gap: 10, padding: isMobile ? "14px 0" : "6px 0 18px" }}>
      <div className={s.headRow} style={{ display: "flex", alignItems: "center", gap: 16 }}>
        {/* The Dashboard greeting's size and line box, so the page title sits
            on the same line on both screens, at `.h-serif`'s own medium
            weight: the greeting's 600 is right for a sentence but made this
            one short word read as a slab. */}
        <h1 className="h-serif" style={{ margin: 0, fontSize: isMobile ? 34 : 42, letterSpacing: "-0.02em", lineHeight: 1.15, color: "var(--text)" }}>Study</h1>
        <CoursePicker courses={courses} value={courseId} onChange={onPickCourse} fullWidth={isMobile} meta={upcomingNote} />
        <nav aria-label="Study tools" style={{ display: "flex", gap: 8, flexShrink: 0, marginLeft: "auto" }}>
          {shownTools(TOOL_BUTTONS, quizShown).map(tl => (
            <button key={tl.key} type="button" className={`btn btn--sm ${s.tool}`} onClick={() => onTool(tl.key)}>
              <span aria-hidden="true" style={{ display: "grid", color: tl.fg }}><Glyph name={tl.icon} size={14} /></span>
              {tl.title}
            </button>
          ))}
        </nav>
      </div>
    </header>
  );
}
