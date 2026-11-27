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
import { cn } from "@/lib/cn";

const TOOL_BUTTONS = TOOL_ORDER.map(key => ({ key, ...TOOL[key] }));

export function HubHeader({ courses, courseId, onPickCourse, upcomingIn, isMobile, quizShown, onTool }: {
  courses: EnrolledCourse[];
  courseId: string;
  onPickCourse: (courseId: string) => void;
  /** Dated work still ahead for a course: the count on its picker row. */
  upcomingIn: (courseId: string) => number;
  isMobile: boolean;
  quizShown: boolean;
  /** Opens a tool's home. */
  onTool: (tool: ToolKey) => void;
}) {
  const upcomingNote = (c: EnrolledCourse) => {
    const n = upcomingIn(c.course_id);
    return n > 0 ? `${n} upcoming` : null;
  };
  return (
    <header className={cn(s.areaHeader, "flex flex-col gap-2.5", isMobile ? "py-3.5 px-0" : "pt-1.5 px-0 pb-4.5")}>
      <div className={cn(s.headRow, "flex items-center gap-4")}>
        {/* The Dashboard greeting's size and line box, so the page title sits
            on the same line on both screens, at `.h-serif`'s own medium
            weight: the greeting's 600 is right for a sentence but made this
            one short word read as a slab. */}
        <h1 className={cn("h-serif", "m-0 tracking-[-0.02em] leading-[1.15] text-text", isMobile ? "text-[34px]" : "text-[42px]")}>Study</h1>
        <CoursePicker courses={courses} value={courseId} onChange={onPickCourse} fullWidth={isMobile} meta={upcomingNote} />
        <nav aria-label="Study tools" className="flex gap-2 shrink-0 ml-auto">
          {shownTools(TOOL_BUTTONS, quizShown).map(tl => (
            <button key={tl.key} type="button" className={`btn btn--sm ${s.tool}`} onClick={() => onTool(tl.key)}>
              <span aria-hidden="true" className="grid" style={{ color: tl.fg }}><Glyph name={tl.icon} size={14} /></span>
              {tl.title}
            </button>
          ))}
        </nav>
      </div>
    </header>
  );
}
