/**
 * The Daily Goal card's numbers, from the daily read (routes/study.py). The
 * minutes are the server's ESTIMATE from quiz, flashcard and tutor timestamps;
 * nothing here invents any.
 */
import type { StudyDaily, StudyDay } from "@/lib/studyApi";

export const GOAL_MIN = 5;
export const GOAL_MAX = 600;
/** The goals most students pick, in minutes a day. Anything else is "custom". */
export const PRESETS = [15, 30, 45, 60, 90];
/** The goal shown until the daily read answers: the server's own default
 *  (`DEFAULT_GOAL_MIN` in routes/study.py), not the student's saved one. */
export const DEFAULT_GOAL = 30;

export interface GoalStats {
  goal: number;
  /** Seven days, oldest first, ending today; empty until the read answers. */
  week: StudyDay[];
  today: StudyDay | undefined;
  /** Minutes studied today. */
  done: number;
  /** Today's progress toward the goal, 0..100. */
  pct: number;
  met: boolean;
  /** How many of the days before today met the goal, and how many there were. */
  hit: number;
  pastDays: number;
  weekTotal: number;
  /** The chart's ceiling: a little above the goal line, or the tallest day. */
  max: number;
}

export function goalStats(daily: StudyDaily | null): GoalStats {
  const goal = daily?.goal_minutes ?? DEFAULT_GOAL;
  const week = daily?.days || [];
  const today = week.at(-1);
  const done = today?.minutes ?? 0;
  const past = week.slice(0, -1);
  return {
    goal, week, today, done,
    pct: Math.min(100, (done / goal) * 100),
    met: done >= goal,
    hit: past.filter(d => d.minutes >= goal).length,
    pastDays: past.length,
    weekTotal: week.reduce((n, d) => n + d.minutes, 0),
    max: Math.max(goal * 1.25, ...week.map(d => d.minutes), 1),
  };
}

/** A day's bar: its height (a percentage of the chart, or a 3px stub for an
 *  empty day) and its colour (today, a day that met the goal, one that did not). */
export function dayBar(minutes: number, isToday: boolean, goal: number, max: number): { height: string | number; background: string } {
  if (minutes <= 0) return { height: 3, background: "var(--bg-soft)" };
  const height = `${Math.max(6, (Math.min(minutes, max) / max) * 100)}%`;
  if (isToday) return { height, background: "var(--brand-forest)" };
  return { height, background: minutes >= goal ? "var(--sap-300)" : "var(--ink-200)" };
}
