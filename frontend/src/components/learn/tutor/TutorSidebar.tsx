"use client";
import React, { useMemo } from "react";
import type { EnrolledCourse } from "@/lib/api";
import { Icon } from "../../Icon";
import { ChevRight, SidebarGlyph } from "./TutorIcons";
import { WHEN_GROUPS, courseColor, sessionTitle, whenGroup, type TutorSessionRow } from "./sessions";
import styles from "./tutor.module.css";

/** How many recents the sidebar shows before "View all sessions". */
const RECENTS_LIMIT = 12;

/**
 * The Tutor's own sidebar (wireframe "AI tutor structure layout V2", B):
 * New session, a session search, the student's courses (like projects) and
 * their recent sessions grouped by day. Open sessions of the course on screen
 * keep the `loop-session-<id>` test ids the picker strip had.
 */
export function TutorSidebar({
  courses,
  courseId,
  sessions,
  currentSessionId,
  currentCourseView,
  query,
  setQuery,
  newDisabled,
  showNew,
  onNew,
  onCourse,
  onOpen,
  onAll,
  onHide,
}: {
  courses: EnrolledCourse[] | null;
  courseId: string | null;
  sessions: TutorSessionRow[];
  currentSessionId: string | null;
  /** The course page on screen (its row is marked current). */
  currentCourseView: string | null;
  query: string;
  setQuery: (q: string) => void;
  newDisabled: boolean;
  /** False on a phone, where the TopBar carries New session. */
  showNew: boolean;
  onNew: () => void;
  onCourse: (courseId: string) => void;
  onOpen: (row: TutorSessionRow) => void;
  onAll: () => void;
  onHide: () => void;
}) {
  const byId = useMemo(() => new Map((courses ?? []).map((c, i) => [c.course_id, { c, i }])), [courses]);
  const q = query.trim().toLowerCase();
  const shown = sessions
    .filter((s) => !q || sessionTitle(s, byId.get(s.courseId ?? "")?.c).toLowerCase().includes(q))
    .slice(0, RECENTS_LIMIT);
  const hasOpenHere = sessions.some((s) => s.open && s.courseId === courseId);

  return (
    <nav aria-label="Tutor sessions" className={styles.side} data-testid="tutor-sidebar">
      <div className={styles.sideInner}>
        <div className={styles.sideHead}>
          <h2 className="h-serif">Tutor</h2>
          <button type="button" className={styles.iconBtn} onClick={onHide} aria-label="Hide tutor sidebar" data-testid="tutor-sidebar-hide">
            <SidebarGlyph />
          </button>
        </div>
        {showNew && (
          <button
            type="button"
            data-testid="loop-new-session"
            className={`btn btn--primary ${styles.sideNew}`}
            onClick={onNew}
            disabled={newDisabled}
          >
            <Icon name="sparkle" size={14} /> New session
          </button>
        )}
        <label className={styles.search}>
          <Icon name="search" size={14} />
          <input
            type="search"
            data-testid="tutor-session-search"
            placeholder="Search sessions"
            aria-label="Search sessions"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>

        {courses && courses.length > 0 && (
          <div className={styles.sideSec}>
            <span className="label-micro">Courses</span>
            {courses.map((c, i) => (
              <button
                key={c.course_id}
                type="button"
                data-testid={`tutor-course-${c.course_id}`}
                className={styles.sideRow}
                aria-current={currentCourseView === c.course_id ? "true" : undefined}
                onClick={() => onCourse(c.course_id)}
              >
                <span className={styles.cdot} style={{ background: courseColor(c, i) }} aria-hidden />
                {c.course_code && <span className={styles.code}>{c.course_code}</span>}
                <span className={styles.rowText}>{c.nickname || c.course_name}</span>
              </button>
            ))}
          </div>
        )}

        <div className={styles.sideSec}>
          <span className="label-micro">Recents</span>
          {/* One list per day group; a list only while it lists something
              (spec §13 A135). */}
          <div data-testid="loop-session-picker" style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            {WHEN_GROUPS.map((g) => {
              const rows = shown.filter((s) => whenGroup(s.startedAt) === g);
              if (rows.length === 0) return null;
              const labelId = `tutor-recents-${g.replace(/\W+/g, "-").toLowerCase()}`;
              return (
                <React.Fragment key={g}>
                  <div id={labelId} className={styles.sideWhen}>{g}</div>
                  <ul aria-labelledby={labelId} style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 1 }}>
                    {rows.map((s) => {
                      const entry = byId.get(s.courseId ?? "");
                      const title = sessionTitle(s, entry?.c);
                      const current = s.id === currentSessionId;
                      // The picker's ids, kept for the open sessions of this course.
                      const testId = s.open && s.courseId === courseId ? `loop-session-${s.id}` : `tutor-recent-${s.id}`;
                      return (
                        <li key={s.id}>
                          <button
                            type="button"
                            data-testid={testId}
                            className={styles.sideRow}
                            aria-current={current ? "true" : undefined}
                            title={current ? "Current session" : s.open ? `Resume “${title}”` : `Open “${title}” (wrapped up)`}
                            onClick={() => { if (!current) onOpen(s); }}
                          >
                            <span className={`${styles.sdot} ${s.open ? styles.sdotOn : ""}`} aria-hidden />
                            <span className={styles.rowText}>{title}</span>
                            <span className={styles.sr}>{s.open ? "in progress" : "wrapped up"}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </React.Fragment>
              );
            })}
            {shown.length === 0 && (
              <span style={{ fontSize: 12, color: "var(--text-muted)", padding: "4px 8px" }}>
                {q ? "No sessions match." : hasOpenHere ? "" : "None yet"}
              </span>
            )}
          </div>
          <div style={{ padding: "8px 8px 0" }}>
            <button type="button" className={styles.textLink} data-testid="tutor-view-all" onClick={onAll}>
              View all sessions <ChevRight />
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}
