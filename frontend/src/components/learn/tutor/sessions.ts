import type { EnrolledCourse, LoopOpenSession, Session } from "@/lib/api";

/** One session as the Tutor lists it (sidebar recents, a course, all sessions). */
export type TutorSessionRow = {
  id: string;
  topic: string;
  courseId: string | null;
  startedAt: string;
  /** Still open: it resumes. Otherwise it was wrapped up and opens read-only. */
  open: boolean;
};

export type WhenGroup = "Today" | "Yesterday" | "Previous 7 days" | "Older";
export const WHEN_GROUPS: WhenGroup[] = ["Today", "Yesterday", "Previous 7 days", "Older"];

const DAY_MS = 86_400_000;

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function whenGroup(iso: string, now: Date = new Date()): WhenGroup {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "Older";
  const days = Math.floor((startOfDay(now) - startOfDay(new Date(t))) / DAY_MS);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "Previous 7 days";
  return "Older";
}

/** "today", "yesterday", "Mon", or "Nov 3" — the short date a row shows. */
export function shortWhen(iso: string, now: Date = new Date()): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const g = whenGroup(iso, now);
  if (g === "Today") return "today";
  if (g === "Yesterday") return "yesterday";
  const d = new Date(t);
  if (g === "Previous 7 days") return d.toLocaleDateString(undefined, { weekday: "short" });
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * Every session the Tutor lists: the loop's open sessions of the course on
 * screen (authoritative, and they include one just started) merged over the
 * student's recent sessions in every course. Newest first, review rows never
 * appear (the backend leaves them out).
 */
export function mergeSessions(
  recent: Session[] | null,
  open: LoopOpenSession[] | null,
  courseId: string | null,
): TutorSessionRow[] {
  const rows = new Map<string, TutorSessionRow>();
  for (const s of recent ?? []) {
    rows.set(s.id, {
      id: s.id,
      topic: s.topic,
      courseId: s.course_id,
      startedAt: s.started_at,
      open: !!s.loop_open,
    });
  }
  // The course on screen: its open list decides which of its rows are open.
  if (open && courseId) {
    const openIds = new Set(open.map((s) => s.session_id));
    for (const row of rows.values()) {
      if (row.courseId === courseId && row.open && !openIds.has(row.id)) row.open = false;
    }
    for (const s of open) {
      const prev = rows.get(s.session_id);
      rows.set(s.session_id, {
        id: s.session_id,
        topic: s.topic || prev?.topic || "",
        courseId,
        startedAt: s.started_at || prev?.startedAt || "",
        open: true,
      });
    }
  }
  return [...rows.values()].sort((a, b) => Date.parse(b.startedAt || "0") - Date.parse(a.startedAt || "0"));
}

/** The course colour: its own, else a stable pick from the map's palette. */
const FALLBACK_COLORS = ["var(--c-crimson)", "var(--c-rust)", "var(--c-sage)", "var(--c-amber)", "var(--c-brown)"];
export function courseColor(course: EnrolledCourse | undefined, index: number): string {
  return course?.color || FALLBACK_COLORS[Math.abs(index) % FALLBACK_COLORS.length];
}

/** A session's name. A course-wide session is titled after its course, which
 *  the breadcrumb and the course dot already show: it reads "Guided session". */
export function sessionTitle(row: Pick<TutorSessionRow, "topic">, course?: EnrolledCourse): string {
  const topic = row.topic?.trim() ?? "";
  if (!topic) return "Guided session";
  const sameAsCourse = !!course && [course.course_name, course.nickname, course.course_code]
    .some((n) => !!n && n.trim().toLowerCase() === topic.toLowerCase());
  return sameAsCourse ? "Guided session" : topic;
}

/** The course's listed open session a start wraps up when none is on screen (a
 *  read-only transcript; LoopLearn's newSession, #866 Z64), named as the home
 *  names it; null while a session is on screen or none is open. */
export function listedOpenTitle(sessionId: string | null, open: LoopOpenSession[] | null, course?: EnrolledCourse): string | null {
  const row = sessionId ? null : open?.[0];
  return row ? sessionTitle(row, course) : null;
}

/** The session a "start a new one" wraps up first: the one on screen while it
 *  is open; with none on screen (a read-only transcript), the course's listed
 *  open session — one open session per course (#866 Z64). */
export function sessionToLeave(onScreen: string | null, onScreenOpen: boolean, open: LoopOpenSession[] | null): string | null {
  if (onScreen) return onScreenOpen ? onScreen : null;
  return open?.[0]?.session_id ?? null;
}
