// The redesigned calendar's model (behind `calendar_v2`; design:
// calendar/v2/__fixtures__/*.design.html, the Claude Design boards). Pure:
// the screens read everything they show from here.
//
// Dates are the calendar's assignments (getAllAssignments). An assignment's
// kind is the Study hub's rule (`classifyAssessment`: exam, quiz, or else
// homework); undated ones have no place on a calendar and are left out. Weeks
// start on Monday, and every date is a local calendar day.
import type { Assignment, EnrolledCourse } from "@/lib/api";
import { plural } from "@/lib/learningCopy";
import { classifyAssessment } from "../../study/studyModel";

export type ItemKind = "Exam" | "Quiz" | "Homework";

export interface CalItem {
  id: string;
  title: string;
  /** YYYY-MM-DD */
  iso: string;
  day: Date;
  kind: ItemKind;
  courseId: string | null;
  /** The course's short name ("CS 112"); "No course" when none. */
  course: string;
  color: string;
  notes: string;
  raw: Assignment;
  /** No due date yet (undatedOf): `iso` is "" and `day` is not a date. */
  undated?: boolean;
}

const DAY_MS = 86_400_000;

/** Courses with no colour of their own, in order: the globals.css course hues. */
export const COURSE_FALLBACK_COLORS = ["var(--c-sky)", "var(--c-rust)", "var(--c-teal)", "var(--c-plum)", "var(--c-amber)", "var(--c-rose)"];

export function parseDay(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

export function dayOf(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

export function addDays(d: Date, n: number): Date {
  const out = new Date(d);
  out.setDate(out.getDate() + n);
  return out;
}

export function isoOf(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Whole days from `from` to `to` (local days; negative when `to` is earlier). */
export function daysBetween(from: Date, to: Date): number {
  return Math.round((dayOf(to).getTime() - dayOf(from).getTime()) / DAY_MS);
}

/** The Monday of `d`'s week. */
export function startOfWeek(d: Date): Date {
  const day = dayOf(d);
  return addDays(day, -((day.getDay() + 6) % 7));
}

export function courseLabel(c: Pick<EnrolledCourse, "course_code" | "course_name">): string {
  return c.course_code || c.course_name;
}

/** Each course's colour: its own, else the next fallback, by enrolment order. */
export function courseColors(courses: readonly EnrolledCourse[]): Map<string, string> {
  return new Map(courses.map((c, i) => [c.course_id, c.color || COURSE_FALLBACK_COLORS[i % COURSE_FALLBACK_COLORS.length]]));
}

/** The calendar's dated assignments as items, soonest first. */
function itemMaker(courses: readonly EnrolledCourse[]) {
  const colors = courseColors(courses);
  const byId = new Map(courses.map((c) => [c.course_id, c]));
  return (a: Assignment, iso: string): CalItem => {
    const course = a.course_id ? byId.get(a.course_id) : undefined;
    return {
      id: a.id,
      title: a.title,
      iso,
      day: iso ? parseDay(iso) : new Date(Number.NaN),
      kind: classifyAssessment(a.assignment_type, a.title) as ItemKind,
      courseId: a.course_id ?? null,
      course: course ? courseLabel(course) : a.course_code || a.course_name || "No course",
      color: (a.course_id && colors.get(a.course_id)) || "var(--text-muted)",
      notes: a.notes ?? "",
      raw: a,
      ...(iso ? {} : { undated: true }),
    };
  };
}

/** Assignments with no due date yet, by title: the agenda's "No date yet" list,
 *  where each opens on the form so it can be given one. */
export function undatedOf(assignments: readonly Assignment[], courses: readonly EnrolledCourse[]): CalItem[] {
  const make = itemMaker(courses);
  return assignments.filter((a) => !a.due_date).map((a) => make(a, "")).sort((x, y) => x.title.localeCompare(y.title));
}

export function toItems(assignments: readonly Assignment[], courses: readonly EnrolledCourse[]): CalItem[] {
  const make = itemMaker(courses);
  return assignments
    .filter((a) => !!a.due_date)
    .map((a) => make(a, String(a.due_date).slice(0, 10)))
    .sort((x, y) => x.iso.localeCompare(y.iso) || x.title.localeCompare(y.title));
}

/** "Today", "Tomorrow", "In 9 days"; past: "Yesterday", "3 days ago". */
export function countdown(day: Date, today: Date): string {
  const n = daysBetween(today, day);
  if (n === 0) return "Today";
  if (n === 1) return "Tomorrow";
  if (n === -1) return "Yesterday";
  return n > 0 ? `In ${n} days` : `${-n} days ago`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const WEEKDAYS_LONG = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

export const shortDate = (d: Date) => `${MONTHS[d.getMonth()]} ${d.getDate()}`;
export const weekdayShort = (d: Date) => WEEKDAYS[(d.getDay() + 6) % 7];
export const longDate = (d: Date) => `${WEEKDAYS_LONG[d.getDay()]}, ${MONTHS_LONG[d.getMonth()]} ${d.getDate()}`;
export const monthTitle = (d: Date) => `${MONTHS_LONG[d.getMonth()]} ${d.getFullYear()}`;

/** "Mar 9 – 15", "Mar 30 – Apr 5". */
export function rangeText(start: Date, end: Date): string {
  return start.getMonth() === end.getMonth()
    ? `${shortDate(start)} – ${end.getDate()}`
    : `${shortDate(start)} – ${shortDate(end)}`;
}

export interface AgendaGroup {
  key: "this" | "next" | "later";
  name: string;
  range: string;
  items: CalItem[];
}

/** The agenda: what is still ahead, in this week, next week and later (each
 *  only when it has something), and what is already past. */
export function agendaOf(items: readonly CalItem[], today: Date): { earlier: CalItem[]; groups: AgendaGroup[] } {
  const monday = startOfWeek(today);
  const nextMonday = addDays(monday, 7);
  const after = addDays(monday, 14);
  const earlier = items.filter((i) => daysBetween(today, i.day) < 0);
  const ahead = items.filter((i) => daysBetween(today, i.day) >= 0);
  const thisWeek = ahead.filter((i) => i.day < nextMonday);
  const nextWeek = ahead.filter((i) => i.day >= nextMonday && i.day < after);
  const later = ahead.filter((i) => i.day >= after);
  const groups: AgendaGroup[] = [
    { key: "this" as const, name: "This week", range: rangeText(monday, addDays(monday, 6)), items: thisWeek },
    { key: "next" as const, name: "Next week", range: rangeText(nextMonday, addDays(nextMonday, 6)), items: nextWeek },
    { key: "later" as const, name: "Later", range: later.length ? rangeText(after, later[later.length - 1].day) : "", items: later },
  ].filter((g) => g.items.length > 0);
  return { earlier, groups };
}

/** "2 due this week, the next one tomorrow" / "Nothing due this week". */
export function weekLine(items: readonly CalItem[], today: Date): string {
  const end = addDays(startOfWeek(today), 7);
  const left = items.filter((i) => daysBetween(today, i.day) >= 0 && i.day < end);
  if (left.length === 0) return "Nothing due this week";
  return `${plural(left.length, "due this week", "due this week")}, the next one ${countdown(left[0].day, today).toLowerCase()}`;
}

export interface DayCell {
  day: Date;
  iso: string;
  inMonth: boolean;
  today: boolean;
  past: boolean;
  weekend: boolean;
  items: CalItem[];
}

function cellOf(day: Date, month: number, today: Date, byIso: Map<string, CalItem[]>): DayCell {
  const iso = isoOf(day);
  const wd = (day.getDay() + 6) % 7;
  return {
    day, iso,
    inMonth: day.getMonth() === month,
    today: daysBetween(today, day) === 0,
    past: daysBetween(today, day) < 0,
    weekend: wd >= 5,
    items: byIso.get(iso) ?? [],
  };
}

function itemsByIso(items: readonly CalItem[]): Map<string, CalItem[]> {
  const map = new Map<string, CalItem[]>();
  for (const i of items) map.set(i.iso, [...(map.get(i.iso) ?? []), i]);
  return map;
}

/** Six Monday-first weeks around `cursor`'s month: every month fits. */
export function monthCells(cursor: Date, items: readonly CalItem[], today: Date): DayCell[] {
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const start = startOfWeek(first);
  const byIso = itemsByIso(items);
  return Array.from({ length: 42 }, (_, i) => cellOf(addDays(start, i), first.getMonth(), today, byIso));
}

/** The seven days of `cursor`'s week. */
export function weekCells(cursor: Date, items: readonly CalItem[], today: Date): DayCell[] {
  const start = startOfWeek(cursor);
  const byIso = itemsByIso(items);
  return Array.from({ length: 7 }, (_, i) => cellOf(addDays(start, i), addDays(start, i).getMonth(), today, byIso));
}

/** "10 due in March, 2 of them exams". */
export function monthLine(cursor: Date, items: readonly CalItem[]): string {
  const inMonth = items.filter((i) => i.day.getMonth() === cursor.getMonth() && i.day.getFullYear() === cursor.getFullYear());
  const exams = inMonth.filter((i) => i.kind === "Exam").length;
  const name = MONTHS_LONG[cursor.getMonth()];
  if (inMonth.length === 0) return `Nothing due in ${name}`;
  return `${inMonth.length} due in ${name}` + (exams ? `, ${exams === 1 ? "1 of them an exam" : `${exams} of them exams`}` : "");
}

export interface WeekLoad {
  start: Date;
  label: string;
  range: string;
  count: number;
  exams: number;
}

/** Each of `weeks` weeks from `start`'s Monday: how much is due in it. */
export function weekLoads(start: Date, weeks: number, items: readonly CalItem[]): WeekLoad[] {
  const monday = startOfWeek(start);
  return Array.from({ length: weeks }, (_, w) => {
    const s = addDays(monday, w * 7);
    const e = addDays(s, 7);
    const inWeek = items.filter((i) => i.day >= s && i.day < e);
    return {
      start: s, label: shortDate(s), range: rangeText(s, addDays(s, 6)),
      count: inWeek.length, exams: inWeek.filter((i) => i.kind === "Exam").length,
    };
  });
}

/** "3 due, 2 exams" / "Nothing due". */
export function loadText(w: Pick<WeekLoad, "count" | "exams">): string {
  if (w.count === 0) return "Nothing due";
  return `${w.count} due` + (w.exams ? `, ${plural(w.exams, "exam")}` : "");
}

/** The heaviest week from this one on, within `weeks`: the most due (ties to
 *  the one with more exams, then the earliest), and only when it is heavy
 *  (3 or more, or 2 exams). */
export function busiestWeek(items: readonly CalItem[], today: Date, weeks = 8): (WeekLoad & { items: CalItem[] }) | null {
  const loads = weekLoads(today, weeks, items);
  let best: WeekLoad | null = null;
  for (const w of loads) if (!best || w.count > best.count || (w.count === best.count && w.exams > best.exams)) best = w;
  if (!best || (best.count < 3 && best.exams < 2)) return null;
  const end = addDays(best.start, 7);
  return { ...best, items: items.filter((i) => i.day >= best!.start && i.day < end) };
}

/** The semester view's span: `weeks` weeks from the week before `cursor`'s. */
export function semesterStart(cursor: Date): Date {
  return addDays(startOfWeek(cursor), -7);
}


/** The courses the items name, in first-seen order, with their colours. */
export function coursesOf(items: readonly CalItem[]): { id: string; label: string; color: string }[] {
  const seen = new Map<string, { id: string; label: string; color: string }>();
  for (const i of items) {
    const id = i.courseId ?? "none";
    if (!seen.has(id)) seen.set(id, { id, label: i.course, color: i.color });
  }
  return [...seen.values()];
}

export interface SemesterLane {
  id: string;
  label: string;
  color: string;
  /** One list per week: that course's items due in it, soonest first. */
  cells: CalItem[][];
}

/** The semester grid: a row per course that has something due in the `weeks`
 *  weeks from `start`'s Monday, a cell per week. */
export function semesterLanes(items: readonly CalItem[], start: Date, weeks: number): SemesterLane[] {
  const monday = startOfWeek(start);
  const end = addDays(monday, weeks * 7);
  const inSpan = items.filter((i) => i.day >= monday && i.day < end);
  return coursesOf(inSpan).map((c) => ({
    ...c,
    cells: Array.from({ length: weeks }, (_, w) => {
      const s = addDays(monday, w * 7);
      const e = addDays(s, 7);
      return inSpan.filter((i) => (i.courseId ?? "none") === c.id && i.day >= s && i.day < e);
    }),
  }));
}
